"""run-python.sh picks a working Python 3 and gets out of the way.

Each case builds a bin directory holding only the interpreter names under test
and runs the real launcher with PATH set to that directory alone, so nothing
else on the machine can answer for `python3` or `python`. A fake interpreter is
a two-line sh script that records its own name in RUN_PYTHON_TEST_NAME and
execs this suite's interpreter, so the hook reports which candidate actually
ran. What differs from a live machine: the fakes are scripts, not binaries, and
PATH holds nothing else; the launcher uses only shell builtins, so neither
matters. Skips when bash is absent.

The second class runs the real settings.json command strings and the real
preflight.sh against a copy of `.claude/` in a temp project, with files
removed, a stale project directory, or a PATH without Python or jq. It runs
each command under every one of sh and bash found here, since which shell
Claude Code hands a command to differs by platform.
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
        self.assertIn("Safety check file missing", r.stderr)

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


REPO = Path(__file__).resolve().parents[1]
SHELLS = [s for s in (shutil.which("sh"), BASH) if s]
JQ = shutil.which("jq")
MISSING = "Safety check file missing"


def settings_commands():
    cfg = json.loads((REPO / ".claude" / "settings.json").read_text(encoding="utf-8"))
    for event, groups in cfg["hooks"].items():
        for g in groups:
            for h in g["hooks"]:
                yield event, h["command"]


@unittest.skipIf(BASH is None, "bash not found")
class Wiring(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wired project "))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.proj = self.tmp / "proj"
        shutil.copytree(REPO / ".claude", self.proj / ".claude",
                        ignore=shutil.ignore_patterns("state.json", "__pycache__"))
        self.hooks = self.proj / ".claude" / "hooks"
        self.bin = self.tmp / "bin"
        self.bin.mkdir()

    def link(self, name, target):
        p = self.bin / name
        p.write_text('#!/bin/sh\nexec "%s" "$@"\n' % target, encoding="utf-8")
        p.chmod(0o755)

    def run_cmd(self, shell, cmd, project=None, path=None, stdin="{}"):
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project or self.proj))
        if path is not None:
            env["PATH"] = path
        return subprocess.run([shell, "-c", cmd], input=stdin, capture_output=True,
                              text=True, env=env, timeout=30)

    def cmd_for(self, name):
        for event, c in settings_commands():
            if c.endswith('/%s"' % name) or ('/%s";' % name) in c:
                return event, c
        self.fail("no command wires " + name)

    def assertBlocked(self, r, code=2):
        self.assertEqual(r.returncode, code, r.stderr)
        self.assertEqual(r.stdout, "")
        self.assertEqual(len(r.stderr.strip().splitlines()), 1, r.stderr)
        self.assertIn(MISSING, r.stderr)

    def test_missing_launcher_blocks_every_python_hook(self):
        (self.hooks / "run-python.sh").unlink()
        n = 0
        for _, c in settings_commands():
            if "run-python.sh" in c:
                for sh in SHELLS:
                    with self.subTest(shell=sh, cmd=c[-40:]):
                        self.assertBlocked(self.run_cmd(sh, c))
                n += 1
        self.assertGreater(n, 0)

    def test_missing_hook_file_blocks(self):
        (self.hooks / "policy-mutate.py").unlink()
        _, c = self.cmd_for("policy-mutate.py")
        for sh in SHELLS:
            with self.subTest(shell=sh):
                r = self.run_cmd(sh, c)
                self.assertBlocked(r)
                self.assertIn("policy-mutate.py", r.stderr)

    def test_missing_preflight_blocks(self):
        (self.hooks / "preflight.sh").unlink()
        _, c = self.cmd_for("preflight.sh")
        for sh in SHELLS:
            with self.subTest(shell=sh):
                r = self.run_cmd(sh, c)
                self.assertBlocked(r)
                self.assertIn("preflight.sh", r.stderr)

    def test_a_stale_project_dir_never_exits_127(self):
        # The 6174 fail-open: CLAUDE_PROJECT_DIR named a folder that was gone.
        gone = self.tmp / "moved away"
        legacy = 'bash "$CLAUDE_PROJECT_DIR/.claude/hooks/auto-compact/check.sh"'
        for event, c in settings_commands():
            if c == legacy:  # pinned by test_failure_hooks; see test_settings_portable
                continue
            for sh in SHELLS:
                with self.subTest(event=event, shell=sh, cmd=c[-40:]):
                    self.assertBlocked(self.run_cmd(sh, c, project=gone),
                                       code=1 if event == "Stop" else 2)

    def test_no_python_blocks_through_the_real_command(self):
        self.link("bash", BASH)
        _, c = self.cmd_for("git-guard.py")
        r = self.run_cmd(SHELLS[0], c, path=str(self.bin))
        self.assertEqual((r.returncode, r.stdout), (2, ""))
        self.assertIn("no Python 3 found", r.stderr)

    def test_a_hooks_own_exit_1_passes_through(self):
        (self.hooks / "git-guard.py").write_text("import sys; sys.exit(1)\n", encoding="utf-8")
        (self.hooks / "session-start.sh").write_text("exit 1\n", encoding="utf-8")
        for name in ("git-guard.py", "session-start.sh"):
            _, c = self.cmd_for(name)
            for sh in SHELLS:
                with self.subTest(hook=name, shell=sh):
                    self.assertEqual(self.run_cmd(sh, c).returncode, 1)

    # --- preflight.sh, run for real against the copied settings ---------------

    def preflight(self, path=None):
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(self.proj))
        if path is not None:
            env["PATH"] = path
        return subprocess.run([BASH, str(self.hooks / "preflight.sh")], input="{}",
                              capture_output=True, text=True, env=env, timeout=30)

    def tool_path(self, *names):
        for n in names:
            self.link(n, {"bash": BASH, "jq": JQ, "python3": sys.executable}[n])
        return str(self.bin)

    @unittest.skipIf(JQ is None, "jq not found")
    def test_preflight_passes_a_whole_tree(self):
        r = self.preflight(self.tool_path("bash", "jq", "python3"))
        self.assertEqual(r.returncode, 0, r.stderr)

    @unittest.skipIf(JQ is None, "jq not found")
    def test_preflight_blocks_a_missing_hook_file(self):
        (self.hooks / "net-post.py").unlink()
        r = self.preflight()
        self.assertEqual(r.returncode, 2)
        self.assertIn("script missing: %s" % (self.hooks / "net-post.py"), r.stderr)

    @unittest.skipIf(JQ is None, "jq not found")
    def test_preflight_blocks_a_missing_launcher(self):
        (self.hooks / "run-python.sh").unlink()
        r = self.preflight()
        self.assertEqual(r.returncode, 2)
        self.assertIn("run-python.sh", r.stderr)

    @unittest.skipIf(JQ is None, "jq not found")
    def test_preflight_blocks_without_python(self):
        r = self.preflight(self.tool_path("bash", "jq"))
        self.assertEqual(r.returncode, 2)
        self.assertIn("no Python 3 found", r.stderr)

    def test_preflight_still_blocks_without_jq(self):
        r = self.preflight(self.tool_path("bash", "python3"))
        self.assertEqual(r.returncode, 2)
        self.assertIn("jq not found", r.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
