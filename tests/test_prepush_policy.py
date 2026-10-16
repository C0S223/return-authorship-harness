""".githooks/pre-push's default-branch rules, driven on stdin ref records.

The default branch is origin's, read from refs/remotes/origin/HEAD whatever its
name (build-1 today); a missing or dangling origin/HEAD refuses every push. The
hook runs from a temp copy whose APPROVED_ORIGIN_URL placeholder is replaced, so
the tracked file (a policy path) is never written. No real push is made.
PREPUSH_HOOK overrides the hook path so a mutant copy can be tested.
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOK = Path(os.environ.get("PREPUSH_HOOK") or ROOT / ".githooks" / "pre-push")
URL = "https://example.invalid/o/r.git"
ZERO = "0" * 40


class PrePushDefaultBranch(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="prepush-policy-"))
        self.repo = self.tmp / "repo"
        self.git("init", "-q", "-b", "work", str(self.repo), cwd=self.tmp)
        self.git("config", "user.email", "t@t")
        self.git("config", "user.name", "t")
        for n in ("c1", "c2"):
            (self.repo / "f.txt").write_text(n + "\n")
            self.git("add", "f.txt")
            self.git("commit", "-q", "-m", n)
        self.c2 = self.git("rev-parse", "HEAD")
        self.c1 = self.git("rev-parse", "HEAD~1")
        src = HOOK.read_text()
        placeholder = 'APPROVED_ORIGIN_URL="https://github.com/OWNER/REPO.git"'
        self.assertIn(placeholder, src, "the placeholder anchor moved")
        self.hook = self.tmp / "pre-push"
        self.hook.write_text(src.replace(placeholder, 'APPROVED_ORIGIN_URL="%s"' % URL))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def git(self, *args, cwd=None):
        r = subprocess.run(["git", *args], cwd=str(cwd or self.repo),
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def set_default(self, name, oid=None):
        self.git("update-ref", "refs/remotes/origin/" + name, oid or self.c1)
        self.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/" + name)

    def push(self, branch, agent, delete=False):
        local = "(delete) %s" % ZERO if delete else "refs/heads/%s %s" % (branch, self.c2)
        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
        if agent:
            env["CLAUDECODE"] = "1"
        r = subprocess.run(["sh", str(self.hook), "origin", URL], cwd=str(self.repo),
                           input="%s refs/heads/%s %s\n" % (local, branch, self.c1),
                           capture_output=True, text=True, env=env)
        return r.returncode, r.stderr.strip()

    def test_human_push_to_the_default_branch_is_allowed(self):
        self.set_default("build-1")
        rc, err = self.push("build-1", agent=False)
        print("\n  default=build-1, human push to build-1: rc=%d %s" % (rc, err or "ALLOWED"))
        self.assertEqual(rc, 0, err)

    def test_agent_push_to_the_default_branch_is_denied_by_its_real_name(self):
        self.set_default("build-1")
        rc, err = self.push("build-1", agent=True)
        self.assertEqual(rc, 1)
        self.assertIn("default-branch push", err)
        # master is an ordinary branch when origin/HEAD names another one.
        rc, err = self.push("master", agent=True)
        self.assertEqual(rc, 0, err)

    def test_default_named_master_still_gates_master(self):
        self.set_default("master")
        rc, err = self.push("master", agent=True)
        self.assertEqual(rc, 1)
        self.assertIn("default-branch push", err)

    def test_deleting_the_default_branch_is_denied(self):
        self.set_default("build-1")
        rc, err = self.push("build-1", agent=False, delete=True)
        self.assertEqual(rc, 1)
        self.assertIn("deletion of the default branch", err)

    def test_unresolvable_default_denies_every_push(self):
        # No origin/HEAD at all; a master-named ref alone is not the default.
        self.git("update-ref", "refs/remotes/origin/master", self.c1)
        rc, err = self.push("lane-1", agent=False)
        print("\n  origin/HEAD unset, push to lane-1: rc=%d %s" % (rc, err))
        self.assertEqual(rc, 1)
        self.assertIn("default branch cannot be resolved", err)

    def test_dangling_default_denies_every_push(self):
        self.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/gone")
        rc, err = self.push("lane-1", agent=False)
        print("\n  origin/HEAD -> origin/gone, push to lane-1: rc=%d %s" % (rc, err))
        self.assertEqual(rc, 1)
        self.assertIn("default branch cannot be resolved", err)


if __name__ == "__main__":
    unittest.main(verbosity=2)
