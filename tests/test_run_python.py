"""run-python.sh picks a working Python 3 and gets out of the way.

Each case builds a bin directory holding only the interpreter names under test
and runs the real launcher with PATH set to that directory alone, so nothing
else on the machine can answer for `python3` or `python`. A fake interpreter is
a two-line sh script that records its own name in RUN_PYTHON_TEST_NAME and
execs this suite's interpreter, so the hook reports which candidate actually
ran. What differs from a live machine: the fakes are scripts, not binaries, and
PATH holds nothing else; the launcher uses only shell builtins, so neither
matters. Skips when bash is absent.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

LAUNCHER = Path(__file__).resolve().parents[1] / ".claude" / "hooks" / "run-python.sh"
BASH = shutil.which("bash")

ECHO_HOOK = r"""
import json, os, sys
data = sys.stdin.read()
print(json.dumps({"ran": os.environ.get("RUN_PYTHON_TEST_NAME"), "stdin": data,
                  "argv": sys.argv[1:]}))
sys.exit(int(os.environ.get("HOOK_RC", "0")))
"""


@unittest.skipIf(BASH is None, "bash not found")
class RunPython(unittest.TestCase):
    def setUp(self):
        # A space in the path: the project directory may have one.
        self.tmp = Path(tempfile.mkdtemp(prefix="run python "))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.hook = self.tmp / "echo hook.py"
        self.hook.write_text(ECHO_HOOK, encoding="utf-8")

    def fake(self, name, body=None):
        p = self.bin / name
        body = body or 'RUN_PYTHON_TEST_NAME=%s exec "%s" "$@"' % (name, sys.executable)
        p.write_text("#!/bin/sh\n%s\n" % body, encoding="utf-8")
        p.chmod(0o755)

    def run_launcher(self, *args, stdin="", **env):
        e = {"PATH": str(self.bin)}
        if os.name == "nt":
            e["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", "")
        e.update(env)
        return subprocess.run([BASH, str(LAUNCHER)] + [str(a) for a in args], input=stdin,
                              capture_output=True, text=True, env=e, timeout=30)

    def ran(self, r):
        self.assertEqual(r.stderr, "")
        return json.loads(r.stdout)

    def test_python3_only(self):
        self.fake("python3")
        r = self.run_launcher(self.hook, stdin='{"tool_name": "Bash"}')
        self.assertEqual(r.returncode, 0)
        out = self.ran(r)
        self.assertEqual(out["ran"], "python3")
        self.assertEqual(out["stdin"], '{"tool_name": "Bash"}')

    def test_python_only(self):
        self.fake("python")
        self.assertEqual(self.ran(self.run_launcher(self.hook))["ran"], "python")

    def test_both_prefers_python3(self):
        self.fake("python3")
        self.fake("python")
        self.assertEqual(self.ran(self.run_launcher(self.hook))["ran"], "python3")

    def test_neither_blocks_with_one_plain_line(self):
        r = self.run_launcher(self.hook)
        self.assertEqual(r.returncode, 2)
        self.assertEqual(r.stdout, "")
        self.assertEqual(len(r.stderr.strip().splitlines()), 1, r.stderr)
        self.assertIn("Install Python 3", r.stderr)

    def test_a_python3_that_is_not_python_3_is_skipped_silently(self):
        # The Windows Store alias prints a message and exits 9009; a Python 2
        # `python` fails the version probe. Neither may leak into stdout.
        self.fake("python3", 'echo "Python was not found; run without arguments to install"; exit 9009')
        self.fake("python")
        r = self.run_launcher(self.hook)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(self.ran(r)["ran"], "python")

    def test_only_a_stub_blocks(self):
        self.fake("python3", "echo stub; exit 9009")
        r = self.run_launcher(self.hook)
        self.assertEqual((r.returncode, r.stdout), (2, ""))

    def test_exit_code_and_args_pass_through(self):
        self.fake("python3")
        r = self.run_launcher(self.hook, "--log", "x y", HOOK_RC="3")
        self.assertEqual(r.returncode, 3)
        self.assertEqual(self.ran(r)["argv"], ["--log", "x y"])

    def test_missing_hook_file_blocks_and_names_it(self):
        self.fake("python3")
        gone = self.tmp / "gone.py"
        r = self.run_launcher(gone)
        self.assertEqual((r.returncode, r.stdout), (2, ""))
        self.assertIn(str(gone), r.stderr)
        self.assertIn("settings.json", r.stderr)

    def test_no_hook_named_blocks(self):
        self.fake("python3")
        r = self.run_launcher()
        self.assertEqual(r.returncode, 2)
        self.assertIn("no hook file", r.stderr)

    def test_a_crashing_hook_keeps_its_own_exit_code(self):
        # Not converted to a block: see the launcher's header for why.
        self.fake("python3")
        self.hook.write_text("raise RuntimeError('boom')\n", encoding="utf-8")
        r = self.run_launcher(self.hook)
        self.assertEqual(r.returncode, 1)
        self.assertIn("RuntimeError: boom", r.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
