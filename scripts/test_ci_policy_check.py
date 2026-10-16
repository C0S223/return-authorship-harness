"""Self-check for ci_policy_check.py and the workflow that runs it.

Run from scripts/:
    python test_ci_policy_check.py

  P1  the classifier: .github/** is policy and is_policy() alone does not say
      so (the rule is load-bearing); the live gate runs against THIS checkout,
      so an existing scripts/ file flags, a new one does not, CLAUDE.md flags,
      an ordinary project file does not, the tracked pre-push hook sources
      (.githooks/, tools/git-hooks/) flag by the hook's own rule
      while githooks/ and tools/other/ do not, and .githooks/ is still not
      .github/ to is_github.
  P2  end to end, as a subprocess, against a throwaway git repo: a branch
      touching only an ordinary file exits 0 with no POLICY line; one adding
      .github/workflows/x.yml exits 1 and names it; one editing a path that
      EXISTS under this checkout's scripts/ exits 1 (existence is judged
      against the checkout the script ships in, never the diff's repo); one
      pure-renaming that path exits 1 and names its OLD name (--no-renames:
      with rename detection only the new name is listed, it exists nowhere,
      and the check passes); a head that does not resolve exits 2.
  P3  .github/workflows/ci.yml parses, and carries the trigger, permissions,
      concurrency, and the two jobs the default-branch ruleset requires by id (item
      702): `gate` runs (b) stamp and (c) suite, `operator-merge` runs (a);
      each has the base/head checkouts; no step uses a cache; no job widens
      `permissions` past the workflow's `contents: read`.
  P4  the `operator-merge` step's own shell, run under `sh` against a stub
      checker: exit 1 is summarised as the operator's merge cue and any other
      nonzero exit as "could not run", never as the cue.

Every git call here is against a temp repo this file creates; nothing touches
this checkout's history.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CHECKER = os.path.join(HERE, "ci_policy_check.py")
WORKFLOW = os.path.join(ROOT, ".github", "workflows", "ci.yml")

sys.path.insert(0, HERE)
import ci_policy_check as cpc  # noqa: E402

try:
    import yaml
except ImportError:  # the host and the runner both have it; P3 skips loudly
    yaml = None


def git(*args, cwd):
    done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    assert done.returncode == 0, "git %s failed:\n%s" % (" ".join(args), done.stderr)
    return done.stdout


def fixture_repo(tmp):
    """master: f.txt. topic-plain edits it. topic-github adds
    .github/workflows/x.yml. topic-scripts edits scripts/prepush_check.py
    (a path that exists under THIS checkout, which is what the classifier
    judges existence against). topic-rename pure-renames that file to
    scripts/moved_zz.py, a name that exists nowhere."""
    git("init", "-q", "-b", "master", cwd=tmp)
    git("config", "user.email", "t@t", cwd=tmp)
    git("config", "user.name", "t", cwd=tmp)
    git("config", "diff.renames", "true", cwd=tmp)

    def commit(rel, text, msg):
        path = os.path.join(tmp, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(text)
        git("add", rel, cwd=tmp)
        git("commit", "-q", "-m", msg, cwd=tmp)

    commit("f.txt", "a\n", "c1")
    commit("scripts/prepush_check.py", "x = 1\n", "c2")
    for branch, rel in (("topic-plain", "f.txt"),
                        ("topic-github", ".github/workflows/x.yml"),
                        ("topic-scripts", "scripts/prepush_check.py")):
        git("checkout", "-q", "-b", branch, "master", cwd=tmp)
        commit(rel, "changed\n", branch)
    git("checkout", "-q", "-b", "topic-rename", "master", cwd=tmp)
    git("mv", "scripts/prepush_check.py", "scripts/moved_zz.py", cwd=tmp)
    git("commit", "-q", "-m", "topic-rename", cwd=tmp)
    git("checkout", "-q", "master", cwd=tmp)


def run_checker(repo, head):
    done = subprocess.run(
        [sys.executable, CHECKER, "--repo", repo, "--base", "master", "--head", head],
        capture_output=True, text=True)
    return done.returncode, done.stdout + done.stderr


def load_workflow():
    with open(WORKFLOW, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


class TestClassifier(unittest.TestCase):
    def test_p1_github_and_live_predicate(self):
        checker = cpc.pc._load_is_policy()
        self.assertIsNotNone(checker, "the live predicate must load from this checkout")
        flagged = ["scripts/prepush_check.py",   # exists here: policy
                   "CLAUDE.md",
                   ".claude/hooks/x.py",
                   ".github/workflows/ci.yml",
                   ".github/CODEOWNERS",
                   ".GitHub/x",                  # folded, like every rule in the hook
                   # The tracked pre-push hook
                   # sources -- the LIVE hook (core.hooksPath) and its dispatcher.
                   ".githooks/pre-push",
                   "tools/git-hooks/pre-push-dispatcher",
                   "roles/senior-engineer.md",
                   "graphs/lane.md"]
        clean = ["projects/app/handler.py",
                 "scripts/does_not_exist_zz.py",  # new under scripts/: not policy
                 "docs/github.md",
                 "github/x",                      # no dot: not the workflows dir
                 "githooks/x",                    # no dot: not the hooks dir either
                 "tools/other/x"]                 # a sibling of git-hooks/
        got = set(cpc.flagged(flagged + clean, checker))
        self.assertEqual(got, set(flagged), "flagged %r, expected %r" % (got, flagged))
        # The .github rule is load-bearing: the hook itself does not flag it.
        np = os.path.normcase(os.path.realpath(
            os.path.join(ROOT, ".github", "workflows", "ci.yml")))
        self.assertFalse(checker(np), "is_policy() now flags .github/**; retire is_github")
        # .githooks/ flags above through is_policy; is_github's prefix must
        # still not match it (the claim the old `clean` entry carried).
        self.assertFalse(cpc.is_github(".githooks/pre-push"))


class TestEndToEnd(unittest.TestCase):
    def test_p2_exit_codes_and_listing(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture_repo(tmp)
            code, out = run_checker(tmp, "topic-plain")
            self.assertEqual(code, 0, out)
            self.assertNotIn("POLICY:", out)
            self.assertIn("RESULT: PASS", out)

            code, out = run_checker(tmp, "topic-github")
            self.assertEqual(code, 1, out)
            self.assertIn("POLICY: .github/workflows/x.yml", out)
            self.assertIn("RESULT: FAIL (1 policy path(s))", out)

            code, out = run_checker(tmp, "topic-scripts")
            self.assertEqual(code, 1, out)
            self.assertIn("POLICY: scripts/prepush_check.py", out)

            code, out = run_checker(tmp, "topic-rename")
            self.assertEqual(code, 1, out)
            self.assertIn("POLICY: scripts/prepush_check.py", out)

            code, out = run_checker(tmp, "no-such-branch")
            self.assertEqual(code, 2, out)
            self.assertIn("CONFIG:", out)


class TestDefaultBase(unittest.TestCase):
    """(a): with no --base, both gate scripts read origin's default branch from
    refs/remotes/origin/HEAD, whatever its name, and fail closed (exit 2) when
    that ref is unset or dangling -- never falling back to a guessed name."""

    def both(self, tmp, head):
        stamp = os.path.join(HERE, "stamp_check.py")
        a = subprocess.run([sys.executable, CHECKER, "--repo", tmp, "--head", head],
                           capture_output=True, text=True)
        b = subprocess.run([sys.executable, stamp, "--head", head], cwd=tmp,
                           capture_output=True, text=True)
        return (a.returncode, a.stdout + a.stderr), (b.returncode, b.stdout + b.stderr)

    def test_origin_head_resolves_and_its_absence_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture_repo(tmp)
            miss = "default branch was not found"
            # A master-named ref alone is not the default branch.
            git("update-ref", "refs/remotes/origin/master", "master", cwd=tmp)
            for code, out in self.both(tmp, "topic-github"):
                self.assertEqual(code, 2, out)
                self.assertIn(miss, out)
            git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/gone", cwd=tmp)
            for code, out in self.both(tmp, "topic-github"):
                self.assertEqual(code, 2, out)
                self.assertIn(miss, out)
            git("update-ref", "-d", "refs/remotes/origin/master", cwd=tmp)
            git("update-ref", "refs/remotes/origin/trunk", "master", cwd=tmp)
            git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/trunk", cwd=tmp)
            (pc_code, pc_out), (st_code, st_out) = self.both(tmp, "topic-github")
            self.assertEqual(pc_code, 1, pc_out)
            self.assertIn("POLICY: .github/workflows/x.yml", pc_out)
            self.assertIn(st_code, (0, 1), st_out)
            self.assertNotIn(miss, st_out)


class TestWorkflow(unittest.TestCase):
    @unittest.skipUnless(yaml, "pyyaml not importable; the runner pip-installs it")
    def test_p3_workflow_shape(self):
        wf = load_workflow()
        # PyYAML (YAML 1.1) reads a bare `on` key as boolean True.
        on = wf.get("on", wf.get(True))
        self.assertEqual(list(on), ["pull_request_target"])
        # The base is the default branch by name-free test, not a branch filter.
        self.assertNotIn("branches", on["pull_request_target"])
        self.assertEqual(on["pull_request_target"]["types"],
                         ["opened", "synchronize", "reopened", "ready_for_review"])
        self.assertEqual(wf["permissions"], {"contents": "read"})
        self.assertIn("github.event.pull_request.number", wf["concurrency"]["group"])
        self.assertIs(wf["concurrency"]["cancel-in-progress"], True)
        # The job ids are the default-branch ruleset's required contexts:
        # renaming either one blocks every PR to master.
        self.assertEqual(list(wf["jobs"]), ["gate", "operator-merge"])
        for name, job in wf["jobs"].items():
            self.assertEqual(job["runs-on"], "ubuntu-latest", name)
            self.assertEqual(job["env"]["DEFAULT_BRANCH"],
                             "${{ github.event.repository.default_branch }}", name)
            # A PR into any other branch fails before either checkout: base/
            # would hold that branch's scripts. Unconditional, never skipped.
            names = [s.get("name", "") for s in job["steps"]]
            refuse = names.index("Refuse a PR whose base is not the default branch")
            self.assertLess(refuse, names.index("Checkout base"), name)
            base_guard = job["steps"][refuse]
            self.assertNotIn("if", base_guard)
            self.assertEqual(base_guard["env"]["BASE_REF"],
                             "${{ github.event.pull_request.base.ref }}")
            self.assertIn('[ "$BASE_REF" != "$DEFAULT_BRANCH" ]', base_guard["run"])
            self.assertRegex(base_guard["run"].rstrip(), r"exit 1\n\s*fi$")
            # Review finding: a job's own `permissions:` overrides the workflow's, and
            # `gate` runs head code in (c) -- so no job may carry one at all.
            self.assertNotIn("permissions", job, name)
            steps = job["steps"]
            checkouts = [s for s in steps if str(s.get("uses", "")).startswith("actions/checkout@")]
            self.assertEqual([c["with"]["path"] for c in checkouts], ["base", "head"], name)
            for c in checkouts:
                self.assertEqual(c["with"]["fetch-depth"], 0, c)
                self.assertIs(c["with"]["persist-credentials"], False, c)
            self.assertIn("pull_request.head.sha", checkouts[1]["with"]["ref"])
            for s in steps:  # sweep row 36: PR code would run in master's cache scope
                self.assertNotIn("cache", str(s.get("uses", "")).lower(), (name, s.get("name")))
                self.assertNotIn("cache", str(s.get("with") or {}).lower(), (name, s.get("name")))
        gate = {s["id"]: s for s in wf["jobs"]["gate"]["steps"] if "id" in s}
        merge = {s["id"]: s for s in wf["jobs"]["operator-merge"]["steps"] if "id" in s}
        self.assertEqual(sorted(gate), ["stamp", "suite"])
        self.assertEqual(sorted(merge), ["policy"])
        for s in list(gate.values()) + list(merge.values()):
            self.assertIn("GITHUB_STEP_SUMMARY", s["run"], s["id"])
        # (c) reports even when (b) is red, but only for a same-repo head.
        self.assertEqual(gate["stamp"].get("if"), "${{ !cancelled() }}")
        self.assertEqual(gate["suite"].get("if"),
                         "${{ !cancelled() && github.event.pull_request.head.repo.full_name"
                         " == github.repository }}")
        guard = wf["jobs"]["gate"]["steps"][1]
        self.assertNotIn("if", guard)
        self.assertIn('[ "$HEAD_REPO" != "$GITHUB_REPOSITORY" ]', guard["run"])
        self.assertIn("head.repo.full_name", guard["env"]["HEAD_REPO"])
        self.assertRegex(guard["run"].rstrip(), r"exit 1\n\s*fi$")
        for name, job in wf["jobs"].items():  # a tag can be moved; a sha cannot
            for s in job["steps"]:
                if "uses" in s:
                    self.assertRegex(s["uses"], r"^[\w.-]+/[\w.-]+@[0-9a-f]{40}$", (name, s["uses"]))
                if "pip install" in s.get("run", ""):
                    self.assertEqual(s["run"].split(), ["pip", "install", "pyyaml"], name)
        self.assertIn("base/scripts/ci_policy_check.py", merge["policy"]["run"])
        self.assertIn("base/scripts/stamp_check.py", gate["stamp"]["run"])
        for s in (merge["policy"], gate["stamp"]):  # never the script's own default
            self.assertIn('--base "origin/$DEFAULT_BRANCH"', s["run"], s["id"])
        self.assertEqual(gate["stamp"]["working-directory"], "head")
        self.assertIn("scripts/run_tests.py", gate["suite"]["run"])
        self.assertEqual(gate["suite"]["working-directory"], "head")

    @unittest.skipUnless(yaml and shutil.which("sh"), "needs pyyaml and an `sh`")
    def test_p4_operator_merge_summary_tells_exit_1_from_could_not_run(self):
        """Review finding: ci_policy_check exits 1 on a policy path and 2 when it
        could not run (predicate did not load, git failed). The step's
        summary made every nonzero exit read as the operator's merge cue.
        The step's own `run:` block is executed here under `sh`, with a stub
        `base/scripts/ci_policy_check.py` exiting each code and a temp
        GITHUB_STEP_SUMMARY, so what is asserted is the shipped shell."""
        run = next(s["run"] for s in load_workflow()["jobs"]["operator-merge"]["steps"]
                   if s.get("id") == "policy")
        cue = "the operator merges"
        for rc, must, must_not in ((0, "PASS", cue),
                                   (1, cue, "could not run"),
                                   (2, "exit 2", cue)):
            with tempfile.TemporaryDirectory() as tmp:
                stub = os.path.join(tmp, "base", "scripts", "ci_policy_check.py")
                os.makedirs(os.path.dirname(stub))
                with open(stub, "w") as fh:
                    fh.write("import sys\nsys.exit(%d)\n" % rc)
                summary = os.path.join(tmp, "summary.md").replace("\\", "/")
                done = subprocess.run(["sh", "-c", run], cwd=tmp, capture_output=True,
                                      text=True, env=dict(os.environ, GITHUB_STEP_SUMMARY=summary))
                self.assertEqual(done.returncode, rc, done.stdout + done.stderr)
                with open(summary, encoding="utf-8") as fh:
                    text = fh.read()
                self.assertIn(must, text, (rc, text))
                self.assertNotIn(must_not, text, (rc, text))


if __name__ == "__main__":
    unittest.main()
