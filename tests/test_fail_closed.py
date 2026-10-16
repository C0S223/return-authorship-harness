"""Every PreToolUse gate fails closed when it crashes.

A PreToolUse hook that exits 1 is non-blocking, so before 798 an uncaught raise
let the call through: `echo x > "" && rm CLAUDE.md` crashed shell-scope's
write_targets, and policy-mutate, which shares it, passed the rm it denies on
its own. This suite does not test any input's classification. It tests what a
gate does when it raises, whatever the input: deny on the deny tier, ask on
the ask tier, a line in --log mode, and never rc 1.

What it proves, and no more: a wired gate answers a JSON array on stdin with a
decision, never rc 1. For six gates that array reaches a raise inside main(),
so the wrapper is what answers. spawn-roster and trigger-shape refuse a
non-object before any raise and no stdin shape reaches one in either, so their
wrappers are unproven here. A gate that fails to compile or import
raises before its wrapper exists and still exits 1; this suite then fails
loudly, since it runs every gate, but production would pass the call.

The gates are read from .claude/settings.json, so a new PreToolUse gate joins
the suite on the day it is wired. Nothing here touches the real tree: each run
points the hooks at a fresh temporary root. FAIL_CLOSED_HOOKS names a copy of
the hooks directory, to run this suite against a mutant.
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
HOOKS = Path(os.environ.get("FAIL_CLOSED_HOOKS") or REPO / ".claude" / "hooks")
ASK_TIER = {"shell-scope.py", "filetool-scope.py"}


def pretooluse_gates():
    settings = json.loads((REPO / ".claude" / "settings.json").read_text(encoding="utf-8"))
    names = set()
    for row in settings["hooks"]["PreToolUse"]:
        for h in row["hooks"]:
            names.add(Path(h["command"].split()[-1].strip('"').replace("\\", "/")).name)
    return sorted(names)


class FailClosed(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="fail-closed-"))
        (self.root / ".agent-log").mkdir()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        log = str(self.root / ".agent-log")
        self.env = dict(os.environ, HARNESS_ROOT=str(self.root), CLAUDE_PROJECT_DIR=str(self.root),
                        SPAWN_ROSTER_LOG_DIR=log, TRIGGER_SHAPE_LOG_DIR=log)

    def run_hook(self, name, payload, *args):
        raw = payload if isinstance(payload, str) else json.dumps(payload)
        return subprocess.run([sys.executable, str(HOOKS / name)] + list(args), input=raw,
                              capture_output=True, text=True, env=self.env, timeout=30)

    def decision(self, r):
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"]

    def test_the_settings_wire_the_eight_gates_798_covers(self):
        self.assertEqual(pretooluse_gates(), sorted([
            "env-global.py", "filetool-scope.py", "git-guard.py", "net-post.py",
            "policy-mutate.py", "shell-scope.py", "spawn-roster.py", "trigger-shape.py"]))

    def test_every_gate_refuses_when_it_crashes(self):
        # A JSON array parses, and six gates then call .get on it and raise.
        # spawn-roster and trigger-shape refuse a non-object first: for them
        # this asserts only that they still refuse (see the docstring).
        for name in pretooluse_gates():
            with self.subTest(gate=name):
                want = "ask" if name in ASK_TIER else "deny"
                self.assertEqual(self.decision(self.run_hook(name, "[]")), want)

    def test_a_deny_tier_crash_leaves_a_line_in_the_log(self):
        for name in pretooluse_gates():
            if name in ASK_TIER:
                continue
            with self.subTest(gate=name):
                self.run_hook(name, "[]")
        text = (self.root / ".agent-log" / (time.strftime("%Y-%m-%d") + ".md")).read_text(encoding="utf-8")
        for tag in ("[env-global]", "[git-guard]", "[net-post]", "[policy-mutate]"):
            with self.subTest(tag=tag):
                self.assertIn(tag, text)
        self.assertIn

    def test_the_empty_redirect_no_longer_carries_a_command_past_the_gates(self):
        # The reported bypass. Plain `rm CLAUDE.md` is denied by policy-mutate;
        # prefixed with a crashing redirect it passed.
        cmd = 'echo x > "" && rm CLAUDE.md'
        payload = {"session_id": "s", "tool_name": "Bash", "tool_input": {"command": cmd},
                   "cwd": str(self.root)}
        self.assertEqual(self.decision(self.run_hook("policy-mutate.py", payload)), "deny")
        r = self.run_hook("shell-scope.py", payload)
        self.assertEqual(self.decision(r), "ask")
        # Review finding: the prompt says the gate could not verify, and never names
        # the crash as a write target.
        reason = json.loads(r.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("cannot verify", reason)
        self.assertNotIn("write target '", reason)
        r = self.run_hook("shell-scope.py", payload, "--log")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(r.stdout.startswith("shellwrite: (shell-scope crashed: "), r.stdout)
        self.assertIn(cmd, r.stdout)

    def test_log_mode_crashes_leave_a_line(self):
        for name, prefix in (("shell-scope.py", "shellwrite: (shell-scope crashed: "),
                             ("filetool-scope.py", "filewrite: (filetool-scope crashed: ")):
            with self.subTest(gate=name):
                r = self.run_hook(name, "[]", "--log")
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertTrue(r.stdout.startswith(prefix), r.stdout)

    def test_env_global_does_not_offer_a_grant_for_a_crash(self):
        reason = json.loads(self.run_hook("env-global.py", "[]").stdout)[
            "hookSpecificOutput"]["permissionDecisionReason"]
        self.assertNotIn("auth-env", reason)


if __name__ == "__main__":
    unittest.main(verbosity=2)
