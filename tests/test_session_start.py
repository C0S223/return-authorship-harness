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
    """The nudge prints only when the push guard is armed, .agent-log/onboarded
    is absent, and neither cloud marker is set. Each case sets or strips the
    markers itself, so the caller's environment (cloud or run_tests.py, which
    strips them) cannot decide it. Each case fails if its condition leaves the hook."""

    def setUp(self):
        self.repo = Path(tempfile.mkdtemp(prefix="session-start-onb-"))
        self.addCleanup(shutil.rmtree, self.repo, ignore_errors=True)
        subprocess.run(["git", "-C", str(self.repo), "init", "-q", "-b", "main"],
                       check=True, capture_output=True)

    def prepush(self, url_line):
        hooks = self.repo / ".githooks"
        hooks.mkdir(exist_ok=True)
        (hooks / "pre-push").write_text("#!/bin/sh\nset -f\n\n" + url_line + "ZERO=0\n",
                                        encoding="utf-8")

    def run_hook(self, **extra):
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(self.repo))
        env.pop("CLAUDE_CODE_REMOTE", None)
        env.pop("HARNESS_BOUNDARY", None)
        env.update(extra)
        r = subprocess.run(["bash", str(HOOK)], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.splitlines()

    def nudges(self, **extra):
        return [l for l in self.run_hook(**extra) if NUDGE in l]

    def test_placeholder_present_no_line(self):
        self.prepush(PLACEHOLDER)
        self.assertEqual(self.nudges(), [])

    def test_armed_with_marker_no_line(self):
        self.prepush(ARMED)
        (self.repo / ".agent-log").mkdir()
        (self.repo / ".agent-log" / "onboarded").write_text("", encoding="utf-8")
        self.assertEqual(self.nudges(), [])

    def test_armed_no_marker_local_one_line(self):
        self.prepush(ARMED)
        out = self.nudges()
        self.assertEqual(len(out), 1, out)
        self.assertIn("ONBOARDING.md", out[0])

    def test_armed_no_marker_managed_cloud_no_line(self):
        self.prepush(ARMED)
        self.assertEqual(self.nudges(CLAUDE_CODE_REMOTE="true"), [])

    def test_armed_no_marker_selfhost_no_line(self):
        self.prepush(ARMED)
        self.assertEqual(self.nudges(HARNESS_BOUNDARY="selfhost"), [])

    def test_no_prepush_file_no_line(self):
        self.assertEqual(self.nudges(), [])

    # Armed is the value sh assigns, not the line text (review SE r1 F1).
    def test_empty_value_no_line(self):
        self.prepush('APPROVED_ORIGIN_URL=""   # operator sets this\n')
        self.assertEqual(self.nudges(), [])

    def test_placeholder_then_armed_one_line(self):
        self.prepush(PLACEHOLDER + ARMED)
        self.assertEqual(len(self.nudges()), 1)

    def test_trailing_comment_is_not_the_value(self):
        for line in ('APPROVED_ORIGIN_URL="https://github.com/me/r.git"   # was OWNER/REPO\n',
                     "APPROVED_ORIGIN_URL='https://github.com/me/r.git' # was OWNER/REPO\n",
                     "APPROVED_ORIGIN_URL=https://github.com/me/r.git   # was OWNER/REPO\n"):
            with self.subTest(line=line):
                (self.repo / ".githooks" / "pre-push").unlink(missing_ok=True)
                self.prepush(line)
                self.assertEqual(len(self.nudges()), 1)

    # Only the exact cloud_boundary() values suppress (SE r1 R1).
    def test_other_cloud_marker_values_still_nudge(self):
        self.prepush(ARMED)
        for extra in ({"CLAUDE_CODE_REMOTE": "1"}, {"CLAUDE_CODE_REMOTE": "false"},
                      {"HARNESS_BOUNDARY": "managed"}):
            with self.subTest(**extra):
                self.assertEqual(len(self.nudges(**extra)), 1)

    # Any entry at the marker path counts, a directory included (SE r1 R3).
    def test_marker_directory_no_line(self):
        self.prepush(ARMED)
        (self.repo / ".agent-log" / "onboarded").mkdir(parents=True)
        self.assertEqual(self.nudges(), [])

    # The nudge sits between the dirty line and the log tail, which must
    # still print (SE r1 R2).
    def test_output_order_branch_dirty_nudge_log(self):
        self.prepush(ARMED)
        today = subprocess.run(["date", "+%F"], capture_output=True, text=True,
                               check=True).stdout.strip()
        (self.repo / ".agent-log").mkdir()
        (self.repo / ".agent-log" / (today + ".md")).write_text("LOGLINE-X\n", encoding="utf-8")
        out = self.run_hook()
        want = ["session-start: this checkout is on", "dirty file(s)", NUDGE,
                "today's action-log tail", "LOGLINE-X"]
        self.assertEqual(len(out), len(want), out)
        for line, piece in zip(out, want):
            self.assertIn(piece, line)


@unittest.skipUnless(shutil.which("bash") and shutil.which("git"), "needs bash and git")
class SessionStartSharedMarker(unittest.TestCase):
    """The tour marker is shared across worktrees (item 6180): .agent-log/onboarded
    counts in the main checkout (the folder holding the .git named by
    `git rev-parse --git-common-dir`) or in the checkout the session runs in.
    Fixtures use real `git worktree add` and `git init --separate-git-dir`."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="session-start-shared-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def git(self, cwd, *a):
        subprocess.run(["git", "-C", str(cwd), "-c", "user.email=t@t", "-c", "user.name=t", *a],
                       check=True, capture_output=True)

    def armed(self, root):
        hooks = Path(root) / ".githooks"
        hooks.mkdir(exist_ok=True)
        (hooks / "pre-push").write_text("#!/bin/sh\nset -f\n\n" + ARMED + "ZERO=0\n",
                                        encoding="utf-8")

    def mark(self, root):
        (Path(root) / ".agent-log").mkdir(exist_ok=True)
        (Path(root) / ".agent-log" / "onboarded").write_text("", encoding="utf-8")

    def main_and_linked(self):
        main = self.tmp / "main"
        main.mkdir()
        self.git(main, "init", "-q", "-b", "main")
        self.armed(main)
        self.git(main, "add", ".githooks/pre-push")
        self.git(main, "commit", "-q", "-m", "c1")
        linked = self.tmp / "linked"
        self.git(main, "worktree", "add", "-q", str(linked), "-b", "lane-x")
        self.assertTrue((linked / ".githooks" / "pre-push").is_file())
        return main, linked

    def nudges(self, root):
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
        env.pop("CLAUDE_CODE_REMOTE", None)
        env.pop("HARNESS_BOUNDARY", None)
        r = subprocess.run(["bash", str(HOOK)], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return [l for l in r.stdout.splitlines() if NUDGE in l]

    def test_linked_worktree_marker_only_in_main_no_line(self):
        main, linked = self.main_and_linked()
        self.mark(main)
        self.assertFalse((linked / ".agent-log" / "onboarded").exists())
        self.assertEqual(self.nudges(linked), [])

    def test_linked_worktree_no_marker_anywhere_one_line(self):
        main, linked = self.main_and_linked()
        self.assertEqual(len(self.nudges(linked)), 1)

    def test_linked_worktree_marker_only_in_linked_no_line(self):
        main, linked = self.main_and_linked()
        self.mark(linked)
        self.assertEqual(self.nudges(linked), [])

    def test_non_git_folder_marker_no_line(self):
        root = self.tmp / "plain"
        root.mkdir()
        self.armed(root)
        self.mark(root)
        self.assertEqual(self.nudges(root), [])

    def test_non_git_folder_no_marker_one_line(self):
        root = self.tmp / "plain"
        root.mkdir()
        self.armed(root)
        self.assertEqual(len(self.nudges(root)), 1)

    def test_non_git_folder_still_prints_the_log_tail(self):
        # Outside a git work tree no git failure may end the hook early.
        root = self.tmp / "plain"
        root.mkdir()
        today = subprocess.run(["date", "+%F"], capture_output=True, text=True,
                               check=True).stdout.strip()
        (root / ".agent-log").mkdir()
        (root / ".agent-log" / (today + ".md")).write_text("LOGLINE-Y\n", encoding="utf-8")
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
        r = subprocess.run(["bash", str(HOOK)], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("LOGLINE-Y", r.stdout)

    def test_separate_git_dir_marker_in_work_tree_no_line(self):
        # The git dir is not named .git, so MAIN is the work tree, not the git dir's parent.
        root = self.tmp / "tree"
        root.mkdir()
        self.git(root, "init", "-q", "-b", "main", "--separate-git-dir", str(self.tmp / "store"))
        self.armed(root)
        self.mark(root)
        self.assertEqual(self.nudges(root), [])

    def test_separate_git_dir_no_marker_one_line(self):
        root = self.tmp / "tree"
        root.mkdir()
        self.git(root, "init", "-q", "-b", "main", "--separate-git-dir", str(self.tmp / "store"))
        self.armed(root)
        self.assertEqual(len(self.nudges(root)), 1)

    def test_separate_git_dir_marker_beside_store_does_not_count(self):
        # A marker in the git dir's parent (self.tmp) must not be read as MAIN's.
        root = self.tmp / "tree"
        root.mkdir()
        self.git(root, "init", "-q", "-b", "main", "--separate-git-dir", str(self.tmp / "store"))
        self.armed(root)
        self.mark(self.tmp)
        self.assertEqual(len(self.nudges(root)), 1)


if __name__ == "__main__":
    unittest.main()
