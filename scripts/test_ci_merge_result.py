"""The `gate` job's (c) suite must test what will merge, not a stale PR head.

A PR whose head was far behind the default branch merged
green, because (c) ran the head as checked out and nothing ran the merge.

The step's own `run:` block is executed here under `sh` (as P4 in
test_ci_policy_check.py does for `operator-merge`), in a temp repo laid out
as the runner lays out head/, so what is asserted is the shipped shell:

  M1  a head behind the base runs the base's newer test: the suite sees the
      base's commit merged in, and the summary names the merge.
  M2  a head that conflicts with the base fails with a summary line naming
      the conflict, and the PR's runner never starts.
  M3  a head already containing the base still runs, and passes.
  M4  the base merged is the run's `github.sha`, the commit base/ holds
      under pull_request_target, never the event's possibly stale base.sha.

Every git call is against a temp repo this file creates.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WORKFLOW = os.path.join(ROOT, ".github", "workflows", "ci.yml")

try:
    import yaml
except ImportError:  # the host and the runner both have it; skip loudly
    yaml = None

# The PR's runner, stubbed: it passes only when the base's newer test file is
# present, and records that it ran.
RUNNER = """import os, sys
open("ran", "w").close()
sys.exit(0 if os.path.exists("scripts/test_from_base.py") else 3)
"""


def suite_step():
    with open(WORKFLOW, encoding="utf-8") as fh:
        steps = yaml.safe_load(fh)["jobs"]["gate"]["steps"]
    return next(s for s in steps if s.get("id") == "suite")


def git(cwd, *args):
    done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if done.returncode:
        raise AssertionError("git %s: %s" % (" ".join(args), done.stderr))
    return done.stdout.strip()


def commit(cwd, path, text, msg):
    full = os.path.join(cwd, path)
    os.makedirs(os.path.dirname(full) or cwd, exist_ok=True)
    with open(full, "w") as fh:
        fh.write(text)
    git(cwd, "add", path)
    git(cwd, "commit", "-q", "-m", msg)
    return git(cwd, "rev-parse", "HEAD")


@unittest.skipUnless(yaml and shutil.which("sh") and shutil.which("git"),
                     "needs pyyaml, an `sh` and git")
class TestSuiteRunsTheMergeResult(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.head = os.path.join(self.tmp, "head")
        os.makedirs(self.head)
        # The runner has no git identity; commits here carry their own.
        gitcfg = os.path.join(self.tmp, "gitconfig")
        open(gitcfg, "w").close()
        bindir = os.path.join(self.tmp, "bin")
        os.makedirs(bindir)
        os.symlink(sys.executable, os.path.join(bindir, "python"))
        self.env = dict(os.environ, HOME=self.tmp, GIT_CONFIG_GLOBAL=gitcfg,
                        GIT_CONFIG_NOSYSTEM="1",
                        PATH=bindir + os.pathsep + os.environ.get("PATH", ""),
                        GITHUB_STEP_SUMMARY=os.path.join(self.tmp, "summary.md"),
                        DEFAULT_BRANCH="main")
        for var in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL",
                    "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL", "GIT_DIR"):
            self.env.pop(var, None)
        git(self.head, "init", "-q", "-b", "main")
        git(self.head, "config", "user.name", "fixture")
        git(self.head, "config", "user.email", "fixture@invalid")
        commit(self.head, "f.txt", "x\n", "root")
        self.root = commit(self.head, "scripts/run_tests.py", RUNNER, "runner")

    def run_step(self, head_sha, base_sha):
        step = suite_step()
        self.assertEqual(step.get("working-directory"), "head")
        git(self.head, "checkout", "-q", "--detach", head_sha)
        # The fixture identity must not stand in for one the step should set.
        git(self.head, "config", "--unset", "user.name")
        git(self.head, "config", "--unset", "user.email")
        env = dict(self.env, HEAD_SHA=head_sha, BASE_SHA=base_sha)
        done = subprocess.run(["sh", "-c", step["run"]], cwd=self.head, env=env,
                              capture_output=True, text=True)
        try:
            with open(env["GITHUB_STEP_SUMMARY"], encoding="utf-8") as fh:
                summary = fh.read()
        except FileNotFoundError:
            summary = ""
        ran = os.path.exists(os.path.join(self.head, "ran"))
        return done, summary, ran

    def branch(self, name, start):
        git(self.head, "checkout", "-q", "-b", name, start)

    def test_m1_head_behind_base_runs_the_base_test(self):
        self.branch("pr", self.root)
        head = commit(self.head, "pr.txt", "pr\n", "pr work")
        git(self.head, "checkout", "-q", "main")
        base = commit(self.head, "scripts/test_from_base.py", "", "base moves on")
        done, summary, ran = self.run_step(head, base)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr + summary)
        self.assertTrue(ran)
        self.assertIn(base, summary)
        self.assertIn("(c) suite: PASS", summary)
        # The merge commit has both parents: what the suite ran is what merges.
        self.assertEqual(git(self.head, "rev-parse", "HEAD^1", "HEAD^2").split(), [head, base])

    def test_m2_conflict_fails_and_never_runs_the_suite(self):
        self.branch("pr", self.root)
        head = commit(self.head, "f.txt", "head\n", "pr edits f")
        git(self.head, "checkout", "-q", "main")
        base = commit(self.head, "f.txt", "base\n", "base edits f")
        done, summary, ran = self.run_step(head, base)
        self.assertNotEqual(done.returncode, 0, summary)
        self.assertFalse(ran, "the suite ran on an unmerged head")
        self.assertIn("does not merge cleanly", summary)
        self.assertIn(base, summary)
        self.assertNotIn("PASS", summary)

    def test_m3_head_containing_base_runs(self):
        base = commit(self.head, "scripts/test_from_base.py", "", "base")
        self.branch("pr", base)
        head = commit(self.head, "pr.txt", "pr\n", "pr work")
        done, summary, ran = self.run_step(head, base)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr + summary)
        self.assertTrue(ran)
        self.assertIn("(c) suite: PASS", summary)

    def test_m4_base_is_the_runs_sha(self):
        step = suite_step()
        self.assertEqual(step["env"]["BASE_SHA"], "${{ github.sha }}")
        self.assertNotIn("base.sha", str(step))


if __name__ == "__main__":
    unittest.main()
