"""policy-integrity must not run a child checkout's core.fsmonitor.

The SessionStart baseline lists each repos/<child> contract with `git ls-files`,
and git runs a configured core.fsmonitor command during that call. A child's
config is its own, unwatched policy, so the hook passes `-c core.fsmonitor=false`.

    python tests/test_policy_integrity_child_fsmonitor.py
    POLICY_INTEGRITY_HOOK=<path> to run a candidate hook file (red against base).

Self-contained: it builds its own throwaway harness and child under a temp dir
and reads the day log the hook writes. It sets HARNESS_ROOT (the hook's root
override) and scrubs CLAUDE_PROJECT_DIR, CLAUDE_CODE_REMOTE and HARNESS_BOUNDARY
so a runner's own environment cannot leak in.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HOOK = Path(os.environ.get("POLICY_INTEGRITY_HOOK")
            or REPO / ".claude" / "hooks" / "policy-integrity.py")
SID = "sess-fsmonitor"


class ChildFsmonitorCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="pi-fsm-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.root = self.tmp / "tree"
        (self.root / ".agent-log").mkdir(parents=True)
        (self.root / "CLAUDE.md").write_text("contract v1\n")
        (self.root / ".gitignore").write_text(".agent-log/\nrepos/\n")
        self.git(self.root, "init", "-q")
        self.git(self.root, "add", "-A")
        self.git(self.root, "commit", "-qm", "base")
        self.child = self.root / "repos" / "child"
        self.child.mkdir(parents=True)
        (self.child / "CLAUDE.md").write_text("child contract\n")
        self.git(self.child, "init", "-q")
        self.git(self.child, "add", ".")
        # Configure last: git add above would itself run the monitor.
        self.marker = self.tmp / "fsmonitor-ran"
        script = self.tmp / "fsmonitor.sh"
        script.write_text("#!/bin/sh\ntouch '%s'\nexit 1\n" % self.marker.as_posix())
        script.chmod(0o755)
        self.git(self.child, "config", "core.fsmonitor", script.as_posix())
        self.env = dict(os.environ, HARNESS_ROOT=str(self.root))
        for k in ("CLAUDE_PROJECT_DIR", "CLAUDE_CODE_REMOTE", "HARNESS_BOUNDARY"):
            self.env.pop(k, None)

    def git(self, where, *args):
        subprocess.run(["git", "-C", str(where), "-c", "user.email=t@t",
                        "-c", "user.name=t", "-c", "commit.gpgsign=false", *args],
                       check=True, capture_output=True)

    def hook(self, event, **extra):
        payload = dict({"session_id": SID, "hook_event_name": event,
                        "cwd": str(self.root)}, **extra)
        r = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                           capture_output=True, text=True, env=self.env, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)

    def log(self):
        p = self.root / ".agent-log" / (time.strftime("%Y-%m-%d") + ".md")
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def test_baseline_does_not_run_child_fsmonitor(self):
        self.hook("SessionStart", source="startup")
        self.assertFalse(self.marker.exists(),
                         "the baseline ran the child's core.fsmonitor: " + self.log())
        # The contract is still baselined: an edit to it is recorded.
        (self.child / "CLAUDE.md").write_text("child contract changed\n")
        self.hook("PostToolUse", tool_name="Bash", tool_input={})
        self.assertIn("UNGRANTED CHANGED repos/child/CLAUDE.md", self.log())
        self.assertFalse(self.marker.exists(),
                         "the compare ran the child's core.fsmonitor")


if __name__ == "__main__":
    unittest.main()
