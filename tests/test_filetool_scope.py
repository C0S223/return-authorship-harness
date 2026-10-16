"""Tests for filetool-scope, driven as a subprocess.

First tests this hook has ever had: until the HARNESS_ROOT seam landed
the gate could only be exercised against the real tree. Each run points the
hook at a fresh temporary root via HARNESS_ROOT. FILETOOL_SCOPE_HOOK overrides
the hook path so the suite can run against a pristine copy (the red proof).

The scratchpad case names the real Temp\\claude constant but never writes to
it — the hook only classifies paths.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOK = Path(os.environ.get("FILETOOL_SCOPE_HOOK")
            or ROOT / ".claude" / "hooks" / "filetool-scope.py")

# The hook derives this from tempfile.gettempdir(); mirror it.
SCRATCH = os.path.join(tempfile.gettempdir(), "claude")


class FiletoolScopeCase(unittest.TestCase):
    def setUp(self):
        # mkdtemp's default parent is %TEMP% itself, NOT Temp\claude — so
        # this root is out-of-tree to an unfixed hook (the red proof).
        self.root = Path(tempfile.mkdtemp(prefix="ftscope-root-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def run_hook(self, payload):
        if not isinstance(payload, str):
            payload = json.dumps(payload)
        r = subprocess.run(
            [sys.executable, str(HOOK)], input=payload,
            capture_output=True, text=True,
            env=dict(os.environ, HARNESS_ROOT=str(self.root)))
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def write_payload(self, path, cwd=""):
        return {"tool_name": "Write", "cwd": cwd,
                "tool_input": {"file_path": str(path)}}

    def assertAsks(self, payload):
        self.assertIn('"permissionDecision": "ask"', self.run_hook(payload))

    def assertAllows(self, payload):
        self.assertEqual(self.run_hook(payload), "",
                         "expected silent allow for: %r" % (payload,))


class Allows(FiletoolScopeCase):
    def test_write_inside_root(self):
        self.assertAllows(self.write_payload(self.root / "f.txt"))

    def test_write_to_the_scratchpad(self):
        self.assertAllows(self.write_payload(
            os.path.join(SCRATCH, "ftscope-probe.txt")))

    def test_write_to_a_suffixed_scratchpad(self):
        # A cloud session's scratchpad is <tmp>/claude-<uid>/...
        self.assertAllows(self.write_payload(os.path.join(
            tempfile.gettempdir(), "claude-0", "proj", "scratchpad", "f.txt")))

    def test_relative_path_resolves_against_cwd(self):
        self.assertAllows(self.write_payload("sub/f.txt", cwd=str(self.root)))


class Asks(FiletoolScopeCase):
    def test_write_outside_root(self):
        outside = Path(tempfile.mkdtemp(prefix="ftscope-out-"))
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        self.assertAsks(self.write_payload(outside / "f.txt"))

    def test_a_claude_lookalike_outside_the_scratchpad_asks(self):
        self.assertAsks(self.write_payload(os.path.join(
            tempfile.gettempdir(), "claudex", "f.txt")))

    def test_missing_path_asks(self):
        self.assertAsks({"tool_name": "Write", "cwd": "", "tool_input": {}})

    def test_unreadable_stdin_asks(self):
        self.assertAsks("this is not json")


if __name__ == "__main__":
    unittest.main(verbosity=2)
