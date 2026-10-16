"""git-guard push never-items, driven as a subprocess on stdin JSON.

GIT_GUARD_HOOK overrides the hook path so a mutant copy can be tested; the
hook is a policy path, so mutants are never written over the tracked file.
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
HOOK = Path(os.environ.get("GIT_GUARD_HOOK")
            or ROOT / ".claude" / "hooks" / "git-guard.py")


def make_repo(default="main"):
    """A temp repo whose refs/remotes/origin/HEAD names `default` (None: unset)."""
    d = Path(tempfile.mkdtemp(prefix="git-guard-"))
    def git(*a):
        subprocess.run(["git", "-C", str(d), *a], check=True, capture_output=True)
    git("init", "-q", "-b", "work")
    git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "c1")
    if default:
        git("update-ref", "refs/remotes/origin/" + default, "HEAD")
        git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/" + default)
    return d


class GitGuardPush(unittest.TestCase):
    root = None     # HARNESS_ROOT for verdict(); setUp builds one with origin/HEAD -> main

    def setUp(self):
        self.root = make_repo("main")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def verdict(self, command):
        return '"permissionDecision": "deny"' in self.run_hook(command)

    def run_hook(self, command):
        r = subprocess.run(
            [sys.executable, str(HOOK)],
            input=json.dumps({"tool_name": "Bash", "cwd": str(self.root),
                              "tool_input": {"command": command}}),
            capture_output=True, text=True, cwd=str(self.root),
            env=dict(os.environ, HARNESS_ROOT=str(self.root)))
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_the_default_branch_is_origin_head_by_its_real_name(self):
        for cmd in ("git push origin main", "git push origin HEAD:refs/heads/main",
                    "git push origin HEAD:main", "out=$(git push origin main)"):
            with self.subTest(cmd=cmd):
                self.assertTrue(self.verdict(cmd))
        # master is an ordinary branch when origin/HEAD names another one;
        # a name that only ends in the default is not it.
        for cmd in ("git push origin master", "git push origin feature/main",
                    "git push origin build-1"):
            with self.subTest(cmd=cmd):
                self.assertFalse(self.verdict(cmd))

    def test_an_unresolvable_default_denies_every_push(self):
        unset = make_repo(None)
        self.addCleanup(shutil.rmtree, unset, ignore_errors=True)
        dangling = make_repo(None)
        self.addCleanup(shutil.rmtree, dangling, ignore_errors=True)
        subprocess.run(["git", "-C", str(dangling), "symbolic-ref", "refs/remotes/origin/HEAD",
                        "refs/remotes/origin/gone"], check=True)
        for self.root in (unset, dangling):
            with self.subTest(root=self.root.name):
                # F26 (review SE-6): the named deny, not the crash handler's.
                self.assertIn("default branch cannot be resolved",
                              self.run_hook("git push origin lane-1"))
                self.assertFalse(self.verdict("git status"))
                # F22 (review SE-2): a command that only names push is not one.
                for cmd in ("git stash push -m wip", "git config --get push.default",
                            "git help push"):
                    self.assertFalse(self.verdict(cmd), cmd)
                for cmd in ("git -C stash push origin lane-1",
                            "git stash push $(git push origin lane-1)",
                            "git stash push && git push origin lane-1"):
                    self.assertTrue(self.verdict(cmd), cmd)

    def test_moving_origin_head_is_a_never_item(self):
        for cmd in ("git remote set-head origin lane-1", "git remote set-head origin --auto",
                    "git symbolic-ref refs/remotes/origin/HEAD refs/remotes/origin/lane-1",
                    "git symbolic-ref refs/remotes/origin/HEAD 'refs/remotes/origin/x'",
                    "git symbolic-ref -d refs/remotes/origin/HEAD",
                    "git symbolic-ref $R refs/heads/x",
                    "git update-ref refs/remotes/origin/main HEAD",
                    "git update-ref --stdin",
                    # F21 (review SE-1): each moved origin/HEAD past the first rows.
                    "git symbolic-ref refs/remotes/orig\\in/HEAD refs/remotes/orig\\in/lane-1",
                    "git -c alias.sr=symbolic-ref sr refs/remotes/origin/HEAD refs/remotes/origin/l",
                    '"$(git --exec-path)"/git-symbolic-ref refs/remotes/origin/HEAD refs/heads/l',
                    "cd .git && git symbolic-ref refs/remotes/orig?n/HEAD refs/remotes/orig?n/l",
                    "git symbolic-ref refs/remotes/ORIGIN/HEAD refs/remotes/ORIGIN/lane-1",
                    "git symbolic-ref -qd refs/remotes/origin/HEAD",
                    "git update-ref refs/remotes/orig\\in/main HEAD",
                    "git update-ref refs/remotes/{origin,x}/main HEAD",
                    "git symbolic-ref refs/remotes/origin/HEAD > /tmp/x refs/heads/l",
                    # FC-8: neither word is literal, so only _operand's unescape-and-fold
                    # denies this; it pins F21 and changes no pattern (docs/adr/0001).
                    "git symbolic-ref refs/remot\\es/orig\\in/HEAD refs/heads/l",
                    # SE6159-1: no lower-case word either, so only the fold denies this.
                    "git symbolic-ref refs/REMotes/ORIGIN/HEAD refs/REMotes/ORIGIN/lane-1"):
            with self.subTest(cmd=cmd):
                self.assertTrue(self.verdict(cmd))
        # Reads of the same ref, and prose quoting the command, stay allowed.
        for cmd in ("git symbolic-ref -q refs/remotes/origin/HEAD",
                    "git symbolic-ref -q --short refs/remotes/origin/HEAD 2>/dev/null",
                    "git update-ref refs/heads/lane-1 HEAD@{1}",
                    # F27 (review SE-7): a redirect target is not an operand.
                    "git symbolic-ref refs/remotes/origin/HEAD > /tmp/x",
                    "git symbolic-ref -q refs/remotes/origin/HEAD 2> /dev/null",
                    "git symbolic-ref HEAD", "git remote -v", "git rev-parse origin/main",
                    "git commit -m 'never git symbolic-ref refs/remotes/origin/HEAD x'"):
            with self.subTest(cmd=cmd):
                self.assertFalse(self.verdict(cmd))

    def test_short_flag_clusters_with_f_are_force(self):
        for flags in ("-uf", "-fu", "-vf", "-f"):
            with self.subTest(flags=flags):
                self.assertTrue(self.verdict("git push %s origin lane-1" % flags))

    def test_follow_tags_is_a_tag_push(self):
        self.assertTrue(self.verdict("git push --follow-tags origin lane-1"))

    def test_an_ordinary_lane_push_passes(self):
        for cmd in ("git push -u origin lane-1", "git push origin feature-f",
                    "git push --no-follow-tags origin lane-1"):
            with self.subTest(cmd=cmd):
                self.assertFalse(self.verdict(cmd))


if __name__ == "__main__":
    unittest.main()
