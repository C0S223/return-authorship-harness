"""session-start.sh's branch line names origin/HEAD's target, never a guessed
`master`. Each case runs the real hook with CLAUDE_PROJECT_DIR at a temp repo.
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / ".claude" / "hooks" / "session-start.sh"


@unittest.skipUnless(shutil.which("bash"), "needs bash")
class SessionStartBranchLine(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp(prefix="session-start-"))
        self.addCleanup(shutil.rmtree, self.repo, ignore_errors=True)
        self.git("init", "-q", "-b", "main")
        self.git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q",
                 "--allow-empty", "-m", "c1")

    def git(self, *a):
        subprocess.run(["git", "-C", str(self.repo), *a], check=True, capture_output=True)

    def line(self):
        r = subprocess.run(["bash", str(HOOK)], capture_output=True, text=True,
                           env=dict(os.environ, CLAUDE_PROJECT_DIR=str(self.repo)))
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.splitlines()[0]

    def set_default(self, name):
        self.git("update-ref", "refs/remotes/origin/" + name, "HEAD")
        self.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/" + name)

    def test_on_the_default_branch_by_its_real_name(self):
        self.set_default("main")
        out = self.line()
        self.assertIn("on the default branch 'main'", out)
        self.assertIn("a commit IS a push", out)
        self.assertIn("origin/main", out)

    def test_off_the_default_branch(self):
        self.set_default("main")
        self.git("checkout", "-q", "-b", "master")
        self.assertIn("on 'master', not the default branch 'main'", self.line())

    def test_unknown_default_says_so(self):
        self.assertIn("default branch is unknown", self.line())

    def test_a_dangling_default_is_unknown(self):
        # F23 (review SE-3): the gates refuse every push in this state, so the
        # line must not name 'gone' as the default.
        self.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/gone")
        out = self.line()
        self.assertIn("default branch is unknown", out)
        self.assertNotIn("'gone'", out)


PLACEHOLDER = 'APPROVED_ORIGIN_URL="https://github.com/OWNER/REPO.git"   # operator sets this\n'
ARMED = 'APPROVED_ORIGIN_URL="https://github.com/someone/my-repo.git"   # operator sets this\n'
NUDGE = "Say 'onboard me'"


@unittest.skipUnless(shutil.which("bash"), "needs bash")
class SessionStartOnboardingNudge(unittest.TestCase):
    """The nudge prints only when the push guard is armed and no lane has run
    (no grills/, no work/). Each case fails if its condition leaves the hook."""

    def setUp(self):
        self.repo = Path(tempfile.mkdtemp(prefix="session-start-onb-"))
        self.addCleanup(shutil.rmtree, self.repo, ignore_errors=True)
        subprocess.run(["git", "-C", str(self.repo), "init", "-q", "-b", "main"],
                       check=True, capture_output=True)

    def prepush(self, url_line):
        hooks = self.repo / ".githooks"
        hooks.mkdir()
        (hooks / "pre-push").write_text("#!/bin/sh\nset -f\n\n" + url_line + "ZERO=0\n",
                                        encoding="utf-8")

    def nudges(self):
        r = subprocess.run(["bash", str(HOOK)], capture_output=True, text=True,
                           env=dict(os.environ, CLAUDE_PROJECT_DIR=str(self.repo)))
        self.assertEqual(r.returncode, 0, r.stderr)
        return [l for l in r.stdout.splitlines() if NUDGE in l]

    def test_placeholder_present_no_line(self):
        self.prepush(PLACEHOLDER)
        self.assertEqual(self.nudges(), [])

    def test_armed_with_grills_no_line(self):
        self.prepush(ARMED)
        (self.repo / "grills").mkdir()
        self.assertEqual(self.nudges(), [])

    def test_armed_with_work_no_line(self):
        self.prepush(ARMED)
        (self.repo / "work").mkdir()
        self.assertEqual(self.nudges(), [])

    def test_armed_with_neither_one_line(self):
        self.prepush(ARMED)
        out = self.nudges()
        self.assertEqual(len(out), 1, out)
        self.assertIn("ONBOARDING.md", out[0])

    def test_no_prepush_file_no_line(self):
        self.assertEqual(self.nudges(), [])


if __name__ == "__main__":
    unittest.main()
