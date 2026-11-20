"""session-start.sh's branch line names origin/HEAD's target, never a guessed
`master`. Each case runs the real hook with CLAUDE_PROJECT_DIR at a temp repo.
"""
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / ".claude" / "hooks" / "session-start.sh"


def non_git_env(root, ceiling):
    """Stop discovery before a checkout containing TMPDIR can be found."""
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root),
               GIT_CEILING_DIRECTORIES=str(ceiling.resolve()))
    probe = subprocess.run(["git", "-C", str(root), "rev-parse", "--git-dir"],
                           capture_output=True, text=True, env=env)
    if probe.returncode == 0:
        raise AssertionError("non-git fixture resolved a git directory: " + probe.stdout)
    return env


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

    def nudges(self, root, env=None):
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root)) if env is None else env.copy()
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
        self.assertEqual(self.nudges(root, non_git_env(root, self.tmp)), [])

    def test_non_git_folder_no_marker_one_line(self):
        root = self.tmp / "plain"
        root.mkdir()
        self.armed(root)
        self.assertEqual(len(self.nudges(root, non_git_env(root, self.tmp))), 1)

    def test_non_git_folder_still_prints_the_log_tail(self):
        # Outside a git work tree no git failure may end the hook early.
        root = self.tmp / "plain"
        root.mkdir()
        today = subprocess.run(["date", "+%F"], capture_output=True, text=True,
                               check=True).stdout.strip()
        (root / ".agent-log").mkdir()
        (root / ".agent-log" / (today + ".md")).write_text("LOGLINE-Y\n", encoding="utf-8")
        env = non_git_env(root, self.tmp)
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

    def test_relative_common_dir_from_a_subfolder_resolves_against_root(self):
        # SE r1 R1: from a subfolder of a main checkout git answers `../.git`,
        # relative to ROOT, not to the hook's cwd. Run from a cwd outside the
        # repo so a resolution against cwd (or none) misses the marker.
        main = self.tmp / "main"
        sub = main / "sub"
        sub.mkdir(parents=True)
        self.git(main, "init", "-q", "-b", "main")
        self.armed(sub)
        self.mark(main)
        gcd = subprocess.run(["git", "-C", str(sub), "rev-parse", "--git-common-dir"],
                             check=True, capture_output=True, text=True).stdout.strip()
        if os.path.isabs(gcd):
            self.skipTest("this git prints an absolute common dir (%s); the relative "
                          "branch is unreachable here" % gcd)
        elsewhere = self.tmp / "elsewhere" / "deep"
        elsewhere.mkdir(parents=True)
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(sub))
        env.pop("CLAUDE_CODE_REMOTE", None)
        env.pop("HARNESS_BOUNDARY", None)
        r = subprocess.run(["bash", str(HOOK)], capture_output=True, text=True, env=env,
                           cwd=str(elsewhere))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([l for l in r.stdout.splitlines() if NUDGE in l], [], r.stdout)


ORIGIN_CLAIMS = ("unset or dangling", "git remote set-head")
# The commands session-start.sh runs besides git and shell builtins.
HOOK_TOOLS = ("wc", "tr", "grep", "tail", "date", "dirname", "sleep")


@unittest.skipUnless(shutil.which("bash") and shutil.which("git"), "needs bash and git")
class SessionStartNoOriginClaimWithoutGit(unittest.TestCase):
    """SE r1 F1: when git cannot run in ROOT the hook says nothing about
    origin/HEAD (an unusable git is not an unset origin/HEAD), and the log tail
    still prints. With working git and origin/HEAD unset the line still prints
    (SessionStartBranchLine.test_unknown_default_says_so)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="session-start-nogit-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.today = subprocess.run(["date", "+%F"], capture_output=True, text=True,
                                    check=True).stdout.strip()

    def git(self, cwd, *a):
        subprocess.run(["git", "-C", str(cwd), "-c", "user.email=t@t", "-c", "user.name=t", *a],
                       check=True, capture_output=True)

    def log(self, root):
        (Path(root) / ".agent-log").mkdir(exist_ok=True)
        (Path(root) / ".agent-log" / (self.today + ".md")).write_text("LOGLINE-Z\n",
                                                                     encoding="utf-8")

    def bin_dir(self, git_target=None):
        """A PATH holding only the hook's tools, as symlinks; `git` links to
        git_target when given (a git that fails), else there is no git."""
        d = self.tmp / ("bin-" + (Path(git_target).name if git_target else "nogit"))
        d.mkdir()
        try:
            for tool in HOOK_TOOLS:
                real = shutil.which(tool)
                if not real:
                    self.skipTest("cannot build a git-free PATH: no %s" % tool)
                os.symlink(real, str(d / tool))
            if git_target:
                os.symlink(git_target, str(d / "git"))
        except OSError as e:
            self.skipTest("cannot build a git-free PATH: symlink failed: %s" % e)
        if not git_target:
            self.assertIsNone(shutil.which("git", path=str(d)))
        return str(d)

    def run_hook(self, root, path=None, env=None):
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root)) if env is None else env.copy()
        if path is not None:
            env["PATH"] = path
        r = subprocess.run([shutil.which("bash"), str(HOOK)], capture_output=True,
                           text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def assert_no_origin_claim_and_tail(self, out):
        for line in out.splitlines():
            for claim in ORIGIN_CLAIMS:
                self.assertNotIn(claim, line, out)
        self.assertIn("LOGLINE-Z", out)

    def test_plain_non_git_folder(self):
        root = self.tmp / "plain"
        root.mkdir()
        self.log(root)
        self.assert_no_origin_claim_and_tail(
            self.run_hook(root, env=non_git_env(root, self.tmp)))

    def test_git_directory_without_work_tree_reports_unknown_origin(self):
        # --git-dir succeeds here, while --show-toplevel would hide the warning.
        for bare in (True, False):
            with self.subTest(bare=bare):
                repo = self.tmp / ("bare.git" if bare else "tree")
                repo.mkdir()
                self.git(repo, "init", "-q", "-b", "main", *(["--bare"] if bare else []))
                root = repo if bare else repo / ".git"
                # Pin bare-repository discovery: safe.bareRepository=explicit in the
                # host's config would hide both roots from the hook and from this probe.
                env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root), GIT_CONFIG_COUNT="1",
                           GIT_CONFIG_KEY_0="safe.bareRepository", GIT_CONFIG_VALUE_0="all")
                for option, succeeds in (("--git-dir", True), ("--show-toplevel", False),
                                         ("--verify", False)):
                    args = ["git", "-C", str(root), "rev-parse", option]
                    if option == "--verify":
                        args.append("refs/remotes/origin/HEAD")
                    probe = subprocess.run(args, capture_output=True, text=True, env=env)
                    self.assertEqual(probe.returncode == 0, succeeds, probe.stderr)
                self.assertIn("origin's default branch is unknown",
                              self.run_hook(root, env=env))

    def test_linked_worktree_with_origin_head_set_and_git_unusable(self):
        main = self.tmp / "main"
        main.mkdir()
        self.git(main, "init", "-q", "-b", "main")
        self.git(main, "commit", "-q", "--allow-empty", "-m", "c1")
        self.git(main, "update-ref", "refs/remotes/origin/main", "HEAD")
        self.git(main, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        linked = self.tmp / "linked"
        self.git(main, "worktree", "add", "-q", str(linked), "-b", "lane-x")
        self.log(linked)
        # Control: with git working, origin/HEAD is read as set.
        out = self.run_hook(linked)
        self.assertIn("on 'lane-x', not the default branch 'main'", out)
        variants = [("git absent from PATH", None)]
        if shutil.which("false"):
            variants.append(("git that always fails", shutil.which("false")))
        for name, target in variants:
            with self.subTest(name):
                self.assert_no_origin_claim_and_tail(self.run_hook(linked, self.bin_dir(target)))


SID = "sid-race"
UNKNOWN = "default branch is unknown"
PI = ROOT / ".claude" / "hooks" / "policy-integrity.py"
RUN_PY = ROOT / ".claude" / "hooks" / "run-python.sh"


@unittest.skipUnless(shutil.which("bash") and shutil.which("git"), "needs bash and git")
class SessionStartAfterPolicyIntegrity(unittest.TestCase):
    """SessionStart hooks run in parallel, and in managed cloud
    policy-integrity.py sets an unset origin/HEAD and only then writes this
    session's baseline. The `unknown` line must describe origin/HEAD after that
    attempt, not before it. Fixture as scripts/test_policy_integrity.py's
    with_origin: a clone of a local bare origin, its origin/HEAD removed."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="session-start-race-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        seed = self.tmp / "seed"
        self.git(self.tmp, "init", "-q", "-b", "main", str(seed))
        self.git(seed, "commit", "-q", "--allow-empty", "-m", "c1")
        self.origin = self.tmp / "origin.git"
        self.git(self.tmp, "clone", "-q", "--bare", str(seed), str(self.origin))
        self.repo = self.tmp / "clone"
        self.git(self.tmp, "clone", "-q", str(self.origin), str(self.repo))
        self.git(self.repo, "update-ref", "-d", "--no-deref", "refs/remotes/origin/HEAD")
        self.baseline = self.repo / ".agent-log" / ("policy-baseline-unlock-%s.json" % SID)

    def git(self, cwd, *a):
        subprocess.run(["git", "-C", str(cwd), "-c", "user.email=t@t", "-c", "user.name=t", *a],
                       check=True, capture_output=True)

    def env(self, managed=True):
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(self.repo))
        for k in ("CLAUDE_CODE_REMOTE", "HARNESS_BOUNDARY", "HARNESS_ROOT"):
            env.pop(k, None)
        if managed:
            env["CLAUDE_CODE_REMOTE"] = "true"
        return env

    def payload(self, source="startup"):
        return json.dumps({"session_id": SID, "transcript_path": "/x/%s.jsonl" % SID,
                           "hook_event_name": "SessionStart", "source": source})

    def start(self, argv, env, payload=""):
        p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, env=env)
        self.addCleanup(lambda: p.poll() is None and p.kill())
        p.stdin.write(payload)
        p.stdin.close()
        return p

    def finish(self, p):
        out, err = p.communicate(timeout=30)
        self.assertEqual(p.returncode, 0, err)
        return out

    def session_start(self, env, payload):
        return self.start(["bash", str(HOOK)], env, payload)

    def stand_in(self, env, delay, set_ref):
        """policy-integrity's startup order, slowed down: after `delay` seconds
        point origin/HEAD at origin/main (or leave it), then write the baseline."""
        ref = ("git -C '%s' symbolic-ref refs/remotes/origin/HEAD refs/remotes/origin/main\n"
               % self.repo) if set_ref else ""
        script = "sleep %s\n%smkdir -p '%s'\necho '{}' > '%s'\n" % (
            delay, ref, self.baseline.parent, self.baseline)
        return self.start(["bash", "-c", script], env)

    def test_waits_for_the_baseline_before_calling_the_default_unknown(self):
        # Red before the fix: session-start read origin/HEAD at once and warned.
        env = self.env()
        other = self.stand_in(env, 1, set_ref=True)
        out = self.finish(self.session_start(env, self.payload()))
        self.finish(other)
        self.assertNotIn(UNKNOWN, out)
        self.assertIn("on the default branch 'main'", out)

    def test_real_policy_integrity_in_parallel(self):
        env = self.env()
        other = self.start(["bash", str(RUN_PY), str(PI)], env, self.payload())
        out = self.finish(self.session_start(env, self.payload()))
        self.finish(other)
        log = "".join(f.read_text(encoding="utf-8")
                      for f in (self.repo / ".agent-log").glob("*.md"))
        self.assertIn("origin/HEAD was unset; set to refs/remotes/origin/main", log)
        self.assertNotIn(UNKNOWN, out)
        self.assertIn("on the default branch 'main'", out)

    def test_still_warns_when_the_attempt_leaves_it_unset(self):
        env = self.env()
        other = self.stand_in(env, 0.5, set_ref=False)
        t0 = time.monotonic()
        out = self.finish(self.session_start(env, self.payload()))
        elapsed = time.monotonic() - t0
        self.finish(other)
        self.assertIn(UNKNOWN, out)
        self.assertLess(elapsed, 4, "waited on past the baseline: %.1fs" % elapsed)

    def test_no_wait_where_policy_integrity_sets_nothing(self):
        # No baseline ever appears here, so any wait would run to its bound.
        cases = (("host", self.env(managed=False), self.payload()),
                 ("compact", self.env(), self.payload("compact")),
                 ("clear", self.env(), self.payload("clear")),
                 ("no input", self.env(), ""))
        for name, env, payload in cases:
            with self.subTest(name):
                t0 = time.monotonic()
                out = self.finish(self.session_start(env, payload))
                self.assertIn(UNKNOWN, out)
                self.assertLess(time.monotonic() - t0, 3)

    def test_resume_with_a_baseline_already_on_disk_does_not_wait(self):
        self.baseline.parent.mkdir()
        self.baseline.write_text("{}", encoding="utf-8")
        t0 = time.monotonic()
        out = self.finish(self.session_start(self.env(), self.payload("resume")))
        self.assertIn(UNKNOWN, out)
        self.assertLess(time.monotonic() - t0, 3)


if __name__ == "__main__":
    unittest.main()
