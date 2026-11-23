#!/usr/bin/env python
"""cloud-setup.sh makes a bare `python` resolve and must not fail the
environment when one already does.

The script creates a link in a system folder when `python` is missing, so the
passing case here runs only where `python` already resolves and the script
therefore writes nothing.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "cloud-setup.sh"
BASH = shutil.which("bash")


def run_script(env=None):
    with tempfile.TemporaryDirectory(prefix="cs-") as cwd:
        return subprocess.run([BASH, str(SCRIPT)], cwd=cwd, env=env,
                              capture_output=True, text=True, timeout=120)


@unittest.skipUnless(BASH, "no bash on PATH")
class CloudSetup(unittest.TestCase):
    @unittest.skipUnless(shutil.which("python"), "no bare `python`: the script would write a link")
    def test_a_python_that_resolves_is_left_alone(self):
        for _ in range(2):  # a second run is the same
            r = run_script()
            self.assertEqual(0, r.returncode, r.stderr)
            self.assertIn("python: OK (python already resolves", r.stdout)
            self.assertIn("[cloud-setup] done", r.stdout)

    def test_no_python_at_all_fails_and_says_so(self):
        with tempfile.TemporaryDirectory(prefix="cs-path-") as empty:
            r = run_script(env=dict(os.environ, PATH=empty))
        self.assertEqual(1, r.returncode, r.stdout)
        self.assertIn("neither 'python' nor 'python3' found on PATH", r.stderr)
        self.assertNotIn("[cloud-setup] done", r.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2 if "-v" in sys.argv else 1)
