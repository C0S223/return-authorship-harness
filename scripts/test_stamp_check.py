"""Self-check for scripts/stamp_check.py: the owed cases from four review
rounds (1-25), the own-desk exclusion cases (26-31), gaps carried from the
senior-engineer delta review (32-34), round-2 review repairs (35-38: the
policy-named carve-out, the `..`-segment guard, and the review's own residual
risks), per-kind voiding and its repair (45-48: a voided BLOCK never revives an
older APPROVE), and base merges (49-64: a clean
merge of the base keeps stamps; hand-resolved files void per kind).

New tool, no baseline defect: red-before-green does not apply. Each case's
docstring names the single-point mutant of stamp_check.py that would make the
checker pass wrongly for that fixture — that stands in for the missing baseline.

Every fixture is a throwaway git repo under a fresh temp dir, built and
torn down per test. This file never reads or writes this repo's own
history — commits carry a fixed fixture identity so no host git config is
needed. Run from scripts/:

    python test_stamp_check.py

Tests 15 and 16 import stamp_check as a module and call run()
in-process, monkeypatching module-level state, rather than going through
the subprocess CLI every other case uses -- that is the only way to stub
a single git call inside covers() (test 15) or delete a source line for a
single run (test 16, via a patched module copy) without ever touching the
committed file. Both restore what they patch in a finally block.
"""
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CHECKER = os.path.join(HERE, "stamp_check.py")

# Running as `python test_stamp_check.py` (direct or via run_tests.py, which
# invokes it with cwd=HERE) puts HERE at sys.path[0] already; this insert is
# only for the case something else imports this file by dotted path.
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import stamp_check  # noqa: E402  (import after sys.path fix, by design)


def _clear_readonly(func, path, _exc):
    """git's object files land read-only; a plain rmtree chokes on Windows."""
    os.chmod(path, stat.S_IWRITE)
    func(path)


class StampCheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="stamp-check-")
        self.repo = os.path.join(self.tmp, "repo")
        os.makedirs(self.repo)
        self._git("init", "-q")
        self._git("symbolic-ref", "HEAD", "refs/heads/master")
        self._commit({"README.md": "base\n"}, "base")

    def tearDown(self):
        shutil.rmtree(self.tmp, onerror=_clear_readonly)

    # -- fixture plumbing ---------------------------------------------------

    def _git(self, *args):
        done = subprocess.run(["git", "-C", self.repo, *args],
                              capture_output=True, text=True, timeout=30)
        self.assertEqual(0, done.returncode, done.stderr)
        return done.stdout.strip()

    def _commit(self, files, message):
        for name, content in files.items():
            path = os.path.join(self.repo, *name.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(content)
        self._git("add", "-A")
        self._git("-c", "user.email=fixture@example.invalid",
                  "-c", "user.name=fixture", "-c", "commit.gpgsign=false",
                  "commit", "-q", "-m", message)
        return self._git("rev-parse", "HEAD")

    def _branch(self, name, at="HEAD"):
        self._git("checkout", "-q", "-b", name, at)

    def _stamp(self, path, stamp, reviewer, revision, body="notes\n"):
        return {path: "STAMP: %s\nREVIEWER: %s\nREVISION: %s\n\n%s"
                % (stamp, reviewer, revision, body)}

    def _run(self, base, head):
        proc = subprocess.run(
            [sys.executable, CHECKER, "--base", base, "--head", head],
            cwd=self.repo, capture_output=True, text=True, timeout=30)
        return proc.returncode, proc.stdout + proc.stderr

    def _run_inprocess(self, base, head):
        """Same effect as _run, but in this process, so a monkeypatch on
        stamp_check module state is visible to it."""
        cwd = os.getcwd()
        os.chdir(self.repo)
        try:
            return stamp_check.run(base, head)
        finally:
            os.chdir(cwd)

    # -- the ten owed cases ---------------------------------------

    def test_1_code_change_covering_se_approve(self):
        self._branch("lane")
        rev = self._commit({"foo.py": "x = 1\n"}, "code change")
        self._commit(self._stamp("grills/se.md",
                                  "APPROVE", "senior-engineer", rev), "se stamp")
        code, out = self._run("master", "lane")
        self.assertEqual(0, code, out)

    def test_2_prose_change_covering_ar_approve(self):
        self._branch("lane")
        rev = self._commit({"notes.md": "prose\n"}, "prose change")
        self._commit(self._stamp("grills/ar.md",
                                  "APPROVE", "adversarial-reviewer", rev),
                     "ar stamp")
        code, out = self._run("master", "lane")
        self.assertEqual(0, code, out)

    def test_3_mixed_change_se_only(self):
        self._branch("lane")
        rev = self._commit({"foo.py": "x = 1\n", "notes.md": "prose\n"},
                           "mixed change")
        self._commit(self._stamp("grills/se.md",
                                  "APPROVE", "senior-engineer", rev), "se stamp")
        code, out = self._run("master", "lane")
        self.assertEqual(1, code, out)

    def test_4_post_review_commit_modifies_subject(self):
        self._branch("lane")
        rev = self._commit({"foo.py": "x = 1\n"}, "code change")
        self._commit(self._stamp("grills/se.md",
                                  "APPROVE", "senior-engineer", rev), "se stamp")
        self._commit({"foo.py": "x = 2\n"}, "post-review edit")
        code, out = self._run("master", "lane")
        self.assertEqual(1, code, out)

    def test_5_post_review_commit_adds_only_grills(self):
        self._branch("lane")
        rev = self._commit({"foo.py": "x = 1\n"}, "code change")
        self._commit(self._stamp("grills/se.md",
                                  "APPROVE", "senior-engineer", rev), "se stamp")
        self._commit({"grills/note.md": "fyi\n"},
                     "later grills note")
        code, out = self._run("master", "lane")
        self.assertEqual(0, code, out)

    def test_6_short_sha_in_revision(self):
        self._branch("lane")
        rev = self._commit({"foo.py": "x = 1\n"}, "code change")
        self._commit(self._stamp("grills/se.md",
                                  "APPROVE", "senior-engineer", rev[:7]),
                     "bad se stamp")
        code, out = self._run("master", "lane")
        self.assertEqual(1, code, out)

    def test_7_covering_block_beside_covering_approve(self):
        self._branch("lane")
        rev = self._commit({"foo.py": "x = 1\n"}, "code change")
        self._commit(self._stamp("grills/se-a.md",
                                  "APPROVE", "senior-engineer", rev), "se approve")
        self._commit(self._stamp("grills/se-b.md",
                                  "BLOCK", "senior-engineer", rev), "se block")
        code, out = self._run("master", "lane")
        self.assertEqual(1, code, out)

    def test_8_revision_not_descended_from_merge_base(self):
        # An orphan root commit shares no history with master's tip at all,
        # so master's tip can never be its ancestor — a stale/foreign
        # REVISION, distinct from "not yet merged" (which test 4/7's shapes
        # already exercise via a REVISION that IS on the lane).
        self._git("checkout", "-q", "--orphan", "stale")
        stale_rev = self._commit({"stale.txt": "x\n"}, "stale lineage")
        self._git("checkout", "-q", "master")
        self._branch("lane")
        self._commit({"foo.py": "x = 1\n"}, "code change")
        self._commit(self._stamp("grills/se.md",
                                  "APPROVE", "senior-engineer", stale_rev),
                     "se stamp of a stale revision")
        code, out = self._run("master", "lane")
        self.assertEqual(1, code, out)

    def test_9_malformed_stamp_line(self):
        self._branch("lane")
        rev = self._commit({"foo.py": "x = 1\n"}, "code change")
        self._commit(
            {"grills/se.md":
                "STAMP: MAYBE\nREVIEWER: senior-engineer\nREVISION: %s\n" % rev},
            "malformed stamp")
        code, out = self._run("master", "lane")
        self.assertEqual(1, code, out)

    def test_10_nonexistent_head(self):
        code, out = self._run("master", "totally-bogus-ref-xyz")
        self.assertEqual(2, code, out)

    # -- H1: grills/ non-.md and nested-path bypass ---------------

    def test_11_post_review_commit_adds_nongrills_py_under_grills(self):
        """H1: a post-review commit sneaking grills/x.py in
        (status A, under the grills/ prefix, but not a flat .md) must NOT be
        waved through by the "REVISION..HEAD only adds grills/" allowance —
        it is not a stamp-shaped addition, so it invalidates the SE stamp's
        coverage the same as any other post-review edit would."""
        self._branch("lane")
        rev = self._commit({"foo.py": "x = 1\n"}, "code change")
        self._commit(self._stamp("grills/se.md",
                                  "APPROVE", "senior-engineer", rev), "se stamp")
        self._commit({"grills/x.py": "y = 2\n"},
                     "sneak code in under grills/")
        code, out = self._run("master", "lane")
        self.assertEqual(1, code, out)

    def test_12_nested_grills_md_is_a_subject(self):
        """H1's other face: grills/sub/x.md (nested, so not a
        stamp candidate either) must NOT be excluded from the subject set as
        though it were a reviewed artifact — it is prose like any other file,
        so adversarial-reviewer is required and a covering stamp is what
        makes this pass, not the path merely sitting under grills/."""
        self._branch("lane")
        rev = self._commit({"grills/sub/x.md": "nested doc\n"},
                           "nested grills change")
        self._commit(self._stamp("grills/ar.md",
                                  "APPROVE", "adversarial-reviewer", rev),
                     "ar stamp")
        code, out = self._run("master", "lane")
        self.assertEqual(0, code, out)

    # -- round 3: fail-closed classification, any-reviewer BLOCK, git
    # -- failures, -z paths, BOM/stray-char candidacy ------------------------

    def test_13a_unknown_extension_is_code(self):
        """Spec change 1: classification inverts —
        prose is only .md; a .cs file is code, so an AR-only APPROVE cannot
        cover it. Mutant killed: reverting to an explicit CODE_EXTS
        allowlist that omits .cs."""
        self._branch("lane")
        rev = self._commit({"lib/Probe.cs": "class Probe {}\n"},
                           "non-py code change")
        self._commit(self._stamp("grills/ar.md",
                                  "APPROVE", "adversarial-reviewer", rev),
                     "ar stamp only")
        code, out = self._run("master", "lane")
        self.assertEqual(1, code, out)
        self.assertIn("senior-engineer: FAIL - no covering APPROVE", out)

    def test_13b_extensionless_only_is_code(self):
        """round 4 F7: split out of the old combined test 13, which changed
        .cs and Dockerfile together — a .cs file alone already keeps
        code_present true, so that combined fixture could not tell apart
        "extensionless classified as code" from "any non-prose extension
        classified as code". This fixture has NO .cs
        file, only an extensionless one, so it kills only the mutant that
        specifically carves out extensionless names as prose (PROSE_EXTS
        gaining "" via os.path.splitext("Dockerfile") == ("Dockerfile","")).
        """
        self._branch("lane")
        rev = self._commit({"Dockerfile": "FROM x\n"}, "extensionless change")
        self._commit(self._stamp("grills/ar.md",
                                  "APPROVE", "adversarial-reviewer", rev),
                     "ar stamp only")
        code, out = self._run("master", "lane")
        self.assertEqual(1, code, out)
        self.assertIn("senior-engineer: FAIL - no covering APPROVE", out)

    def test_14_covering_block_from_nonrequired_reviewer_still_fails(self):
        """Spec change 2: a prose-only subject requires only
        adversarial-reviewer, but a covering senior-engineer BLOCK at the
        same revision must still fail the gate. Mutant killed: scoping the
        BLOCK check to `required` reviewers only (round-1/2 shape)."""
        self._branch("lane")
        rev = self._commit({"notes.md": "prose\n"}, "prose change")
        self._commit(self._stamp("grills/ar.md",
                                  "APPROVE", "adversarial-reviewer", rev),
                     "ar approve")
        self._commit(self._stamp("grills/se.md",
                                  "BLOCK", "senior-engineer", rev),
                     "se block, not required")
        code, out = self._run("master", "lane")
        self.assertEqual(1, code, out)
        self.assertIn("FAIL - covering BLOCK", out)

    def test_15_git_failure_inside_covers_exits_2(self):
        """Spec change 3: a git call failing outright inside
        covers() must exit 2, never read as "does not cover". Stubbed
        in-process: stamp_check._git is monkeypatched so the
        `merge-base --is-ancestor <merge-base> <REVISION>` call for this
        candidate's REVISION returns 128 (a real git error code, probed
        separately: disjoint histories return 1, a genuinely bad object
        returns 128) instead of delegating to real git; every other call
        goes through the real _git unchanged. Mutant killed: catching
        GitError nowhere (or swallowing it back into a covers()-internal
        `return False, ...`)."""
        self._branch("lane")
        rev = self._commit({"foo.py": "x = 1\n"}, "code change")
        self._commit(self._stamp("grills/se.md",
                                  "APPROVE", "senior-engineer", rev), "se stamp")
        base_commit = self._git("rev-parse", "master")

        real_git = stamp_check._git

        def stub(*args):
            if (len(args) >= 4 and args[0] == "merge-base"
                    and args[1] == "--is-ancestor"
                    and args[2] == base_commit and args[3] == rev):
                return 128, "", "stubbed: fatal: bad object"
            return real_git(*args)

        stamp_check._git = stub
        try:
            code, lines = self._run_inprocess("master", "lane")
        finally:
            stamp_check._git = real_git
        out = "\n".join(lines)
        self.assertEqual(2, code, out)
        self.assertIn("stubbed: fatal: bad object", out)

    def test_16_merge_base_ancestry_check_required(self):
        """Spec change/review finding: REVISION must descend from the merge-base, not
        merely be an ancestor of HEAD. Fixture (SE grill F4's prescription):
        master goes root -> C1 (foo.py=v1) -> C2 (foo.py=v2, the lane's
        merge-base); the lane branches at C2, then a commit L1 REVERTS
        foo.py back to v1 (byte-identical to C1), then an SE APPROVE cites
        REVISION=C1 -- a real commit, an ancestor of HEAD, but NOT a
        descendant of the merge-base C2. diff(C1, HEAD) shows foo.py
        unchanged (the revert restored C1's exact content) plus the added
        stamp file, so without the merge-base-ancestor check this would
        wrongly look like a covering, all-grills-since-REVISION APPROVE."""
        c1 = self._commit({"foo.py": "v1\n"}, "master c1")
        c2 = self._commit({"foo.py": "v2\n"}, "master c2 (merge-base)")
        self.assertNotEqual(c1, c2)
        self._branch("lane")
        self._commit({"foo.py": "v1\n"}, "lane reverts foo.py to v1")
        self._commit(self._stamp("grills/se.md",
                                  "APPROVE", "senior-engineer", c1),
                     "se approve of pre-merge-base c1")
        code, out = self._run("master", "lane")
        self.assertEqual(1, code, out)
        self.assertIn("stale base", out)

        # Prove the fixture actually isolates the merge-base-ancestor check:
        # with only that check deleted from a patched copy of covers(), the
        # same fixture must flip to a wrong PASS.
        import types
        patched = types.ModuleType("stamp_check_mutant_f4")
        with open(stamp_check.__file__, encoding="utf-8") as fh:
            src = fh.read()
        # The base-merge change moved the check into a branch: the mutant drops the gate.
        marker = '    if _is_ancestor(base_commit, rev):\n'
        self.assertIn(marker, src, "F4 mutant site text moved; update the marker")
        mutated_src = src.replace(marker, "    if True:\n", 1)
        exec(compile(mutated_src, stamp_check.__file__, "exec"), patched.__dict__)
        cwd = os.getcwd()
        os.chdir(self.repo)
        try:
            mcode, mlines = patched.run("master", "lane")
        finally:
            os.chdir(cwd)
        self.assertEqual(0, mcode, "\n".join(mlines))

    def test_17_malformed_candidate_beside_valid_approve(self):
        """Spec change/review finding: a malformed stamp candidate must FAIL the gate
        even when a separate, valid, covering APPROVE exists. Mutant
        killed: dropping `fail = True` for the malformed-candidate branch
        (so it becomes a no-op skip, same as an ordinary non-candidate
        grills file)."""
        self._branch("lane")
        rev = self._commit({"foo.py": "x = 1\n"}, "code change")
        self._commit(self._stamp("grills/se-good.md",
                                  "APPROVE", "senior-engineer", rev),
                     "valid se approve")
        self._commit(
            {"grills/se-bad.md":
                "STAMP: MAYBE\nREVIEWER: senior-engineer\nREVISION: %s\n" % rev},
            "malformed se stamp")
        code, out = self._run("master", "lane")
        self.assertEqual(1, code, out)
        self.assertIn("FAIL candidate", out)
        self.assertIn("malformed stamp header", out)

    def test_18_nonascii_path_extension_survives_quoting(self):
        """Spec change 4, fixture chosen for what -z actually still
        changes after spec change 1: under the default (plain
        --name-status) form git C-quotes a non-ASCII path, e.g.
        '"not\\303\\244s.md"', whose os.path.splitext extension is '.md"'
        (probed) -- not '.md', so under change 1's fail-closed default
        (unrecognized extension = code) a purely prose file would flip to
        requiring senior-engineer instead of adversarial-reviewer. -z
        never quotes, so the real '.md' extension reaches the classifier.
        A pure code file with a non-ASCII name does NOT distinguish -z from
        its absence here: its corrupted extension ('.py"') is still not in
        PROSE_EXTS either way, so change 1 alone already keeps it "code"
        with or without -z -- that combination cannot kill this mutant,
        which is why this fixture is prose-side, not code-side."""
        self._branch("lane")
        rev = self._commit({"docs/notäs.md": "prose\n"},
                           "non-ascii prose change")
        self._commit(self._stamp("grills/ar.md",
                                  "APPROVE", "adversarial-reviewer", rev),
                     "ar stamp only")
        code, out = self._run("master", "lane")
        self.assertEqual(0, code, out)
        self.assertIn("adversarial-reviewer: PASS - covering APPROVE", out)

    def test_19a_bom_block_alone_not_ignored(self):
        """Spec change 5 (SE BOM note / AR note 1), split out of the old
        combined test 19 (round 4 F7): a BOM'd SE BLOCK, alone beside a
        valid covering SE APPROVE, must parse clean after the BOM strip and
        count as a covering BLOCK, not be silently ignored as "not a
        candidate". Mutant killed: candidate detection reverted wholesale
        to the pre-round-3 `content.splitlines()[0].startswith("STAMP:")`
        (no BOM handling anywhere) — under that revert this BOM'd file's
        raw first line does not start with "STAMP:", so it is dropped and
        the lone APPROVE wrongly passes the gate alone."""
        self._branch("lane")
        rev = self._commit({"foo.py": "x = 1\n"}, "code change")
        self._commit(self._stamp("grills/se-good.md",
                                  "APPROVE", "senior-engineer", rev),
                     "valid se approve")
        bom_content = "﻿STAMP: BLOCK\nREVIEWER: senior-engineer\nREVISION: %s\n\nnotes\n" % rev
        self._commit({"grills/se-bom.md": bom_content},
                     "bom'd se block")
        code, out = self._run("master", "lane")
        self.assertEqual(1, code, out)
        self.assertIn("FAIL - covering BLOCK", out)

    def test_19b_stray_space_block_alone_not_ignored(self):
        """Spec change 5 (AR note 1), split out of the old combined test 19
        (round 4 F7): a " STAMP: BLOCK" line (leading space, no BOM), alone
        beside a valid covering SE APPROVE, must be named FAIL as a
        malformed candidate, not silently ignored. This is the fixture that
        actually isolates the candidate-detection mutant: under the old
        combined test, the BOM half alone already produced a covering
        BLOCK (its content still parses once the BOM is stripped, even
        under a partial revert that keeps the BOM strip but moves the
        detection back to line-1-only), so the OR'd assertion passed even
        when this stray-space half was silently dropped. Mutant killed:
        candidate detection reverted wholesale to
        `content.splitlines()[0].startswith("STAMP:")` — under that
        revert this file's raw first line does not start with "STAMP:", so
        it is dropped and the lone APPROVE wrongly passes the gate alone."""
        self._branch("lane")
        rev = self._commit({"foo.py": "x = 1\n"}, "code change")
        self._commit(self._stamp("grills/se-good.md",
                                  "APPROVE", "senior-engineer", rev),
                     "valid se approve")
        space_content = " STAMP: BLOCK\nREVIEWER: senior-engineer\nREVISION: %s\n\nnotes\n" % rev
        self._commit({"grills/se-space.md": space_content},
                     "stray-space se block")
        code, out = self._run("master", "lane")
        self.assertEqual(1, code, out)
        self.assertIn("malformed stamp header", out)

    # -- round 4 spec change 4: prose narrowed to .md only -------------------

    def test_20_txt_only_is_code(self):
        """Spec change 4: .txt moves from prose to code. The AR delta showed
        that .txt-as-prose let an AR-only APPROVE pass
        `projects/app/requirements.txt` and
        `projects/app/allowlist.txt` (Operator gate 1). Mutant killed:
        PROSE_EXTS reverted to include ".txt"."""
        self._branch("lane")
        rev = self._commit({"requirements.txt": "requests==2\n"},
                           "txt-only change")
        self._commit(self._stamp("grills/ar.md",
                                  "APPROVE", "adversarial-reviewer", rev),
                     "ar stamp only")
        code, out = self._run("master", "lane")
        self.assertEqual(1, code, out)
        self.assertIn("senior-engineer: FAIL - no covering APPROVE", out)

    # -- round 4 F3: a git call that never answers, inside
    # -- covers(), must exit 2, never read as "does not cover" --------------

    def _block_at_rev1_approve_at_rev2(self):
        """The SE delta grill's probe shape:
        a code change (REV1), a covering SE BLOCK citing REVISION=REV1,
        then a covering SE APPROVE citing REVISION=REV2 (the commit that
        added the BLOCK file itself — still just a grills addition, so
        REV1..HEAD and REV2..HEAD are both grills-only and both stamps
        genuinely cover under real git). With real git this exits 1 (the
        covering BLOCK fails the gate); the three tests below each stub a
        single failing git call and must still see exit 2, never a
        silent 0 from the BLOCK's coverage check being swallowed."""
        self._branch("lane")
        rev1 = self._commit({"foo.py": "x = 1\n"}, "code change")
        rev2 = self._commit(self._stamp("grills/se-block.md",
                                         "BLOCK", "senior-engineer", rev1),
                            "se block at rev1")
        self._commit(self._stamp("grills/se-approve.md",
                                  "APPROVE", "senior-engineer", rev2),
                     "se approve at rev2")
        merge_base = self._git("merge-base", "master", "lane")
        return rev1, rev2, merge_base

    def test_21_timeout_on_ancestry_call_exits_2(self):
        """subprocess.run itself raises TimeoutExpired for the
        `merge-base --is-ancestor <merge-base> <REV1>` call inside
        covers() for the BLOCK candidate. Stubbed at the subprocess.run
        layer (not _git), so this actually exercises _git's own
        OSError/SubprocessError -> GitError conversion, not just the
        callers built on top of it. Mutant killed: _git catching
        (OSError, SubprocessError) and returning (1, "", str(exc)) instead
        of raising -- under that shape returncode 1 reads as _is_ancestor's
        real "no", the BLOCK does not cover, and only the APPROVE remains,
        so the gate wrongly exits 0."""
        rev1, _rev2, merge_base = self._block_at_rev1_approve_at_rev2()
        real_run = stamp_check.subprocess.run
        target = ["-c", "core.longpaths=true", "merge-base",
                  "--is-ancestor", merge_base, rev1]

        def stub(cmd, *a, **kw):
            if cmd[1:] == target:
                raise subprocess.TimeoutExpired(cmd=cmd, timeout=kw.get("timeout", 30))
            return real_run(cmd, *a, **kw)

        stamp_check.subprocess.run = stub
        try:
            code, lines = self._run_inprocess("master", "lane")
        finally:
            stamp_check.subprocess.run = real_run
        self.assertEqual(2, code, "\n".join(lines))

    def test_22_timeout_on_commit_lookup_exits_2(self):
        """subprocess.run itself raises TimeoutExpired for the
        `rev-parse --verify --quiet REV1^{commit}` call that resolves the
        BLOCK candidate's REVISION inside covers(). Mutant killed: same as
        test 21 -- _git swallowing the exception into returncode 1, which
        resolve_commit's old shape read as "does not resolve", dropping
        the BLOCK candidate as though its REVISION never existed."""
        rev1, _rev2, _merge_base = self._block_at_rev1_approve_at_rev2()
        real_run = stamp_check.subprocess.run
        target = ["-c", "core.longpaths=true", "rev-parse", "--verify",
                  "--quiet", rev1 + "^{commit}"]

        def stub(cmd, *a, **kw):
            if cmd[1:] == target:
                raise subprocess.TimeoutExpired(cmd=cmd, timeout=kw.get("timeout", 30))
            return real_run(cmd, *a, **kw)

        stamp_check.subprocess.run = stub
        try:
            code, lines = self._run_inprocess("master", "lane")
        finally:
            stamp_check.subprocess.run = real_run
        self.assertEqual(2, code, "\n".join(lines))

    def test_23_bad_object_on_commit_lookup_exits_2(self):
        """The same `rev-parse --verify --quiet REV1^{commit}` call, this
        time returning exit 128 (a real git failure code, never 0 or 1)
        instead of raising. Mutant killed: resolve_commit's old
        `if code != 0: return None` shape, which read ANY nonzero exit —
        128 included — as "does not resolve", not only the real "no"
        (exit 1)."""
        rev1, _rev2, _merge_base = self._block_at_rev1_approve_at_rev2()
        real_run = stamp_check.subprocess.run
        target = ["-c", "core.longpaths=true", "rev-parse", "--verify",
                  "--quiet", rev1 + "^{commit}"]

        def stub(cmd, *a, **kw):
            if cmd[1:] == target:
                return subprocess.CompletedProcess(
                    cmd, 128, stdout="", stderr="stubbed: fatal: bad object")
            return real_run(cmd, *a, **kw)

        stamp_check.subprocess.run = stub
        try:
            code, lines = self._run_inprocess("master", "lane")
        finally:
            stamp_check.subprocess.run = real_run
        self.assertEqual(2, code, "\n".join(lines))

    # -- : own-desk .md exclusion ------------------------------------

    def test_26_own_desk_report_md_excluded(self):
        """Spec 1-3: a code change plus the lane's own work/26-x/REPORT.md,
        covered by a lone SE APPROVE. The desk .md is excluded from the
        subject, leaving only foo.py (code), so no AR is required and the
        gate passes. Mutant killed: dropping the exclusion call entirely
        (subject stays 2 files, AR required, exit 1)."""
        self._branch("lane-26")
        rev = self._commit(
            {"foo.py": "x = 1\n",
             "work/26-x/REPORT.md": "report\n"},
            "code change plus own desk report")
        self._commit(self._stamp("grills/se.md",
                                  "APPROVE", "senior-engineer", rev), "se stamp")
        code, out = self._run("master", "lane-26")
        self.assertEqual(0, code, out)
        self.assertIn(
            "EXCLUDED: 1 own-desk prose file(s) under work/26-*/",
            out)

    def test_27_other_items_desk_md_not_excluded(self):
        """Spec 2: another item's work/99-y/NOTE.md sits beside the lane's
        own work/27-x/REPORT.md. Only the own-item file is excluded; the
        other item's prose stays a subject, so AR is required and a
        lone SE APPROVE is not enough. Mutant killed: matching any
        work/*/*.md regardless of lane id (subject would
        stay 1 file, code only, and the gate would wrongly pass)."""
        self._branch("lane-27")
        rev = self._commit(
            {"foo.py": "x = 1\n",
             "work/27-x/REPORT.md": "report\n",
             "work/99-y/NOTE.md": "note\n"},
            "code change plus own and other desk files")
        self._commit(self._stamp("grills/se.md",
                                  "APPROVE", "senior-engineer", rev), "se stamp")
        code, out = self._run("master", "lane-27")
        self.assertEqual(1, code, out)
        self.assertIn("adversarial-reviewer: FAIL - no covering APPROVE", out)

    def test_28_sha_head_no_exclusion(self):
        """Spec 1: the same repo as 26, but --head is a raw sha instead of
        `lane-26` -- fail closed, no exclusion at all. The desk REPORT.md
        stays a subject, AR is required, and the lone SE APPROVE is not
        enough. Mutant killed: deriving the "own" desk id from a
        work/<digits>-* path seen in the subject itself,
        instead of gating on --head's own shape first (probed: this wrongly
        excludes REPORT.md here too, flipping the gate to a wrong PASS,
        even though --head is a sha and spec 1 says a sha excludes
        nothing)."""
        self._branch("lane-28")
        rev = self._commit(
            {"foo.py": "x = 1\n",
             "work/28-x/REPORT.md": "report\n"},
            "code change plus own desk report")
        self._commit(self._stamp("grills/se.md",
                                  "APPROVE", "senior-engineer", rev), "se stamp")
        head_sha = self._git("rev-parse", "lane-28")
        code, out = self._run("master", head_sha)
        self.assertEqual(1, code, out)
        self.assertNotIn("EXCLUDED:", out)
        self.assertIn("adversarial-reviewer: FAIL - no covering APPROVE", out)

    def test_29_desk_only_lane_passes(self):
        """Overturning an earlier spec: a lane whose only change is its own
        work/29-x/WORK-ORDER.md excludes down to an empty subject and
        PASSES with no reviewer required. Mutant killed: keeping the old
        "nothing to stamp" FAIL for an excluded-to-empty subject."""
        self._branch("lane-29")
        self._commit({"work/29-x/WORK-ORDER.md": "wo\n"},
                     "desk work order only")
        code, out = self._run("master", "lane-29")
        self.assertEqual(0, code, out)
        self.assertIn("EXCLUDED: 1", out)
        self.assertIn("SUBJECT: desk-only, nothing to stamp", out)

    def test_29b_desk_only_lane_covering_block_fails(self):
        """E3 keeps "a blocking finding is never silently discarded": a
        desk-only lane with a covering BLOCK still fails. Mutant killed:
        returning PASS before the candidates are evaluated."""
        self._branch("lane-29")
        rev = self._commit({"work/29-x/SPEC.md": "s\n"},
                           "desk spec only")
        self._commit(self._stamp("grills/ar.md",
                                  "BLOCK", "adversarial-reviewer", rev),
                     "ar block")
        code, out = self._run("master", "lane-29")
        self.assertEqual(1, code, out)
        self.assertIn("BLOCK: FAIL - covering BLOCK", out)

    def test_29c_empty_subject_nothing_excluded_still_fails(self):
        """E3 is scoped to own-desk prose: a lane that adds only a flat
        grills file has an empty subject with nothing excluded, and keeps
        the "nothing to stamp" FAIL. Mutant killed: passing every empty
        subject instead of only an excluded-to-empty one."""
        self._branch("lane-29")
        self._commit({"grills/note.md": "n\n"}, "grills only")
        code, out = self._run("master", "lane-29")
        self.assertEqual(1, code, out)
        self.assertNotIn("EXCLUDED:", out)
        self.assertIn('SUBJECT: FAIL ("nothing to stamp; operator\'s call")',
                      out)
        self.assertEqual("RESULT: FAIL", out.strip().splitlines()[-1])

    def test_30_prefix_exactness_no_partial_id_match(self):
        """Spec 2 prefix exactness: --head lane-66 must not treat
        work/668-x/R.md as its own (a naive `path.startswith("work/" + id)`
        without the trailing hyphen would wrongly match "668-" against id
        "66"). Not excluded, so AR is required and the lone SE APPROVE is
        not enough. Mutant killed: dropping the trailing "-" from the
        exclusion prefix."""
        self._branch("lane-66")
        rev = self._commit(
            {"foo.py": "x = 1\n",
             "work/668-x/R.md": "r\n"},
            "code change plus a different item's desk md")
        self._commit(self._stamp("grills/se.md",
                                  "APPROVE", "senior-engineer", rev), "se stamp")
        code, out = self._run("master", "lane-66")
        self.assertEqual(1, code, out)
        self.assertNotIn("EXCLUDED:", out)
        self.assertIn("adversarial-reviewer: FAIL - no covering APPROVE", out)

    def test_31_own_desk_py_not_excluded(self):
        """Spec 2: only .md is excluded -- a .py file under the lane's own
        desk dir stays code, so senior-engineer is still required even
        with a covering AR APPROVE. Mutant killed: excluding the whole
        work/<id>-*/ dir regardless of extension."""
        self._branch("lane-31")
        rev = self._commit(
            {"work/31-x/probe.py": "y = 1\n"},
            "own desk py file")
        self._commit(self._stamp("grills/ar.md",
                                  "APPROVE", "adversarial-reviewer", rev),
                     "ar stamp only")
        code, out = self._run("master", "lane-31")
        self.assertEqual(1, code, out)
        self.assertIn("senior-engineer: FAIL - no covering APPROVE", out)

    # -- spec change 32-34: delta-review RESIDUAL-RISKS 1 and 4,
    # -- carried from the senior-engineer delta review

    def test_32_covers_diff_failure_exits_2(self):
        """RESIDUAL-RISKS 1 / F3b: name_status(REVISION, head) failing inside
        covers() (the name_status call) must exit 2, never read as "does not
        cover". Stubbed at the subprocess.run layer like 21-23, targeting the
        `diff -z --no-renames --name-status <REV1> <head>` call covers()
        makes for the BLOCK candidate's REVISION. Mutant killed: the raise
        replaced with `return False, "..."` -- under that mutant the BLOCK
        candidate wrongly reads as not-covering, and only the covering
        APPROVE remains, so the gate wrongly exits 0."""
        rev1, _rev2, _merge_base = self._block_at_rev1_approve_at_rev2()
        head_commit = self._git("rev-parse", "lane")
        real_run = stamp_check.subprocess.run
        target = ["-c", "core.longpaths=true", "diff", "-z", "--no-renames",
                  "--name-status", rev1, head_commit]

        def stub(cmd, *a, **kw):
            if cmd[1:] == target:
                return subprocess.CompletedProcess(
                    cmd, 128, stdout="", stderr="stubbed: fatal: diff broke")
            return real_run(cmd, *a, **kw)

        stamp_check.subprocess.run = stub
        try:
            code, lines = self._run_inprocess("master", "lane")
        finally:
            stamp_check.subprocess.run = real_run
        out = "\n".join(lines)
        self.assertEqual(2, code, out)
        self.assertIn("stubbed: fatal: diff broke", out)

    def test_33_blob_read_failure_exits_2(self):
        """RESIDUAL-RISKS 1 / F3c: reading a candidate's blob via
        `git show <head>:<path>` failing (the blob read) must exit 2.
        Stubbed at the subprocess.run layer, targeting the
        `show <head>:grills/se-block.md` call. Mutant
        killed: the raise replaced with `continue` -- under that mutant the
        BLOCK candidate is silently dropped as though it were never a
        candidate at all, and only the covering APPROVE remains, so the
        gate wrongly exits 0."""
        _rev1, _rev2, _merge_base = self._block_at_rev1_approve_at_rev2()
        head_commit = self._git("rev-parse", "lane")
        real_run = stamp_check.subprocess.run
        target = ["-c", "core.longpaths=true", "show",
                  "%s:grills/se-block.md" % head_commit]

        def stub(cmd, *a, **kw):
            if cmd[1:] == target:
                return subprocess.CompletedProcess(
                    cmd, 128, stdout="", stderr="stubbed: fatal: blob broke")
            return real_run(cmd, *a, **kw)

        stamp_check.subprocess.run = stub
        try:
            code, lines = self._run_inprocess("master", "lane")
        finally:
            stamp_check.subprocess.run = real_run
        out = "\n".join(lines)
        self.assertEqual(2, code, out)
        self.assertIn("stubbed: fatal: blob broke", out)

    def test_34_head_resolution_git_error_exits_2(self):
        """RESIDUAL-RISKS 4: a GitError raised while resolving --head itself
        (run()'s top-level resolve_commit(head), not a candidate REVISION)
        must still exit 2. Stubbed at the subprocess.run layer, targeting
        `rev-parse --verify --quiet lane^{commit}` (the raw --head string,
        never a resolved sha, so this cannot be confused with the REVISION
        lookups 22/23 already cover). resolve_commit's own "does not
        resolve" (exit-code-1) branch also produces exit 2 via a different
        CONFIG line, so exit code alone cannot distinguish the mutant from
        the unmutated raise -- this also asserts the raised GitError's own
        stubbed stderr text, which only reaches the output through the
        raise path. Mutant killed: resolve_commit's trailing
        `raise GitError(...)` replaced with `return None`."""
        self._branch("lane")
        rev = self._commit({"foo.py": "x = 1\n"}, "code change")
        self._commit(self._stamp("grills/se.md",
                                  "APPROVE", "senior-engineer", rev), "se stamp")
        real_run = stamp_check.subprocess.run
        target = ["-c", "core.longpaths=true", "rev-parse", "--verify",
                  "--quiet", "lane^{commit}"]

        def stub(cmd, *a, **kw):
            if cmd[1:] == target:
                return subprocess.CompletedProcess(
                    cmd, 128, stdout="",
                    stderr="stubbed: fatal: head lookup broke")
            return real_run(cmd, *a, **kw)

        stamp_check.subprocess.run = stub
        try:
            code, lines = self._run_inprocess("master", "lane")
        finally:
            stamp_check.subprocess.run = real_run
        out = "\n".join(lines)
        self.assertEqual(2, code, out)
        self.assertIn("stubbed: fatal: head lookup broke", out)

    # -- round 2: review repairs (S2-1 policy carve-out, S2-2
    # -- '..'-segment guard) and the SE review's own RESIDUAL-RISKS 1-3 -----

    def test_35_own_desk_policy_named_md_not_excluded(self):
        """S2-1 (operator ruling "Close it in round 2"): a
        policy-named file under the lane's own desk dir -- here
        work/35-x/CLAUDE.md -- is never excluded, because CLAUDE.md is
        policy "at any depth" (docs/enforcement/CLAUDE.md:31) and must
        keep its reviewer regardless of which desk dir it sits under. AR
        is still required, and the lone SE APPROVE is not enough. Mutant
        killed: dropping the POLICY_BASENAMES check (the file would be
        excluded, subject drops to code-only, and the gate would wrongly
        pass)."""
        self._branch("lane-35")
        rev = self._commit(
            {"foo.py": "x = 1\n",
             "work/35-x/CLAUDE.md": "policy\n"},
            "code change plus own desk CLAUDE.md")
        self._commit(self._stamp("grills/se.md",
                                  "APPROVE", "senior-engineer", rev), "se stamp")
        code, out = self._run("master", "lane-35")
        self.assertEqual(1, code, out)
        self.assertIn("adversarial-reviewer: FAIL - no covering APPROVE", out)

    def test_36_ref_shape_beyond_bare_lane_n_no_exclusion(self):
        """SE R1a (RESIDUAL-RISK 1): the same fixture as test 26 (own desk
        REPORT.md, lone SE APPROVE), but --head is `refs/heads/lane-26`
        instead of the bare `lane-26` shape spec 1 anchors on.
        lane_id_from_head anchors with ^...$, so this ref shape derives no
        lane id at all -- no exclusion fires, the desk REPORT.md stays a
        subject, AR is required, and the lone SE APPROVE is not enough.
        Mutant killed: matching with an unanchored re.search instead of
        the anchored match (or dropping the trailing "$"), which would
        derive id "26" from this ref shape too and wrongly exclude the
        desk file."""
        self._branch("lane-26")
        rev = self._commit(
            {"foo.py": "x = 1\n",
             "work/26-x/REPORT.md": "report\n"},
            "code change plus own desk report")
        self._commit(self._stamp("grills/se.md",
                                  "APPROVE", "senior-engineer", rev), "se stamp")
        code, out = self._run("master", "refs/heads/lane-26")
        self.assertEqual(1, code, out)
        self.assertNotIn("EXCLUDED:", out)
        self.assertIn("adversarial-reviewer: FAIL - no covering APPROVE", out)

    def test_37_desk_direct_file_no_further_dir_not_excluded(self):
        """SE R1b (RESIDUAL-RISK 2): work/37-x.md sits directly under
        work/, with no further directory level -- not the lane's own desk
        *item* dir, just a same-prefixed file. Not excluded, so AR is
        required and the lone SE APPROVE is not enough. Mutant killed:
        dropping the "at least one further '/'" requirement ("/" in
        rest), which would wrongly exclude this file too."""
        self._branch("lane-37")
        rev = self._commit(
            {"foo.py": "x = 1\n",
             "work/37-x.md": "notes\n"},
            "code change plus desk-level md, no item dir")
        self._commit(self._stamp("grills/se.md",
                                  "APPROVE", "senior-engineer", rev), "se stamp")
        code, out = self._run("master", "lane-37")
        self.assertEqual(1, code, out)
        self.assertNotIn("EXCLUDED:", out)
        self.assertIn("adversarial-reviewer: FAIL - no covering APPROVE", out)

    def test_38_is_own_desk_prose_unit_probes(self):
        """Direct calls to is_own_desk_prose, no git fixture needed.
        Covers: SE R1c (RESIDUAL-RISK 3) -- a status T or R row (a
        type-change, or a rename that --no-renames should split before it
        ever reaches here, but the function must still fail closed on its
        own) is never excluded (mutant killed: dropping the A/M/D status
        guard -- see m38a); S2-2 -- a `..` path segment is never excluded,
        even though real git does not emit one (SE RESIDUAL-RISK 4, a
        trust-boundary guard; mutant killed: dropping the `..`-segment
        check -- see m38b); S2-1 -- a policy basename is never excluded
        regardless of nesting or case (same guard as test 35, exercised
        here at the unit level); and a control case confirming the
        predicate still returns True for an ordinary own-desk .md, so the
        guards above are not accidentally excluding everything.

        The order's own `../../../CLAUDE.md` shape also matches the S2-1
        policy-basename guard (its basename is `CLAUDE.md` regardless of
        the leading `..` segments), so that assertion alone is jointly
        pinned by S2-1 and S2-2 together, not S2-2 in isolation -- probed:
        removing only the `..`-segment check left it passing. The
        `../../../NOTES.md` probe below isolates S2-2: a non-policy
        basename that only the `..`-segment guard catches."""
        is_own = stamp_check.is_own_desk_prose
        self.assertFalse(is_own("T", "work/38-x/REPORT.md", "38"))
        self.assertFalse(is_own("R", "work/38-x/REPORT.md", "38"))
        self.assertFalse(is_own(
            "M", "work/38-x/../../../CLAUDE.md", "38"))
        self.assertFalse(is_own(
            "M", "work/38-x/../../../NOTES.md", "38"))
        self.assertFalse(is_own(
            "A", "work/38-x/sub/AGENTS.override.md", "38"))
        self.assertFalse(is_own(
            "A", "work/38-x/Claude.MD", "38"))
        self.assertTrue(is_own(
            "A", "work/38-x/REPORT.md", "38"))

    # -- per-kind voiding -------

    def _mixed_both_approved(self):
        self._branch("lane")
        rev = self._commit({"foo.py": "x = 1\n", "notes.md": "prose\n"},
                           "mixed change")
        self._commit(self._stamp("grills/se.md",
                                  "APPROVE", "senior-engineer", rev), "se stamp")
        self._commit(self._stamp("grills/ar.md",
                                  "APPROVE", "adversarial-reviewer", rev),
                     "ar stamp")
        return rev

    def test_39_prose_repair_keeps_se_approve(self):
        """A README-only repair after both APPROVEs needs only a fresh AR
        stamp; the SE APPROVE still covers."""
        self._mixed_both_approved()
        rev2 = self._commit({"notes.md": "prose, repaired\n"}, "prose repair")
        self._commit(self._stamp("grills/ar2.md",
                                  "APPROVE", "adversarial-reviewer", rev2),
                     "ar re-stamp")
        code, out = self._run("master", "lane")
        self.assertEqual(0, code, out)
        self.assertIn("senior-engineer: PASS - covering APPROVE "
                      "(grills/se.md)", out)

    def test_40_code_repair_keeps_ar_approve(self):
        self._mixed_both_approved()
        rev2 = self._commit({"foo.py": "x = 2\n"}, "code repair")
        self._commit(self._stamp("grills/se2.md",
                                  "APPROVE", "senior-engineer", rev2),
                     "se re-stamp")
        code, out = self._run("master", "lane")
        self.assertEqual(0, code, out)
        self.assertIn("adversarial-reviewer: PASS - covering APPROVE "
                      "(grills/ar.md)", out)

    def test_41_prose_repair_still_voids_ar_approve(self):
        self._mixed_both_approved()
        self._commit({"notes.md": "prose, repaired\n"}, "prose repair")
        code, out = self._run("master", "lane")
        self.assertEqual(1, code, out)
        self.assertIn("adversarial-reviewer: FAIL - no covering APPROVE", out)
        self.assertIn("senior-engineer: PASS", out)

    def test_42_code_repair_still_voids_se_approve(self):
        """Includes a code-classified file under grills/ (H1's x.py): it is
        code, so it voids the SE APPROVE even though AR's survives."""
        self._mixed_both_approved()
        self._commit({"grills/x.py": "y = 2\n"},
                     "sneak code in under grills/")
        code, out = self._run("master", "lane")
        self.assertEqual(1, code, out)
        self.assertIn("senior-engineer: FAIL - no covering APPROVE", out)
        self.assertIn("adversarial-reviewer: PASS", out)

    def test_43_block_voided_by_change_of_other_kind(self):
        """An SE BLOCK on a README clause clears when the README is
        repaired: BLOCKs keep the any-change rule."""
        self._branch("lane")
        rev1 = self._commit({"foo.py": "x = 1\n", "notes.md": "prose\n"},
                            "mixed change")
        self._commit(self._stamp("grills/se-block.md",
                                  "BLOCK", "senior-engineer", rev1),
                     "se block on readme clause")
        rev2 = self._commit({"notes.md": "prose, repaired\n"}, "readme repair")
        self._commit(self._stamp("grills/se2.md",
                                  "APPROVE", "senior-engineer", rev2), "se")
        self._commit(self._stamp("grills/ar.md",
                                  "APPROVE", "adversarial-reviewer", rev2), "ar")
        code, out = self._run("master", "lane")
        self.assertEqual(0, code, out)
        self.assertIn("se-block.md stamp=BLOCK", out)
        self.assertIn("covers=no", out)

    def test_44_is_prose_unit_probes(self):
        self.assertTrue(stamp_check.is_prose("a/README.MD"))
        self.assertTrue(stamp_check.is_prose("notes.md"))
        self.assertFalse(stamp_check.is_prose("notes.txt"))
        self.assertFalse(stamp_check.is_prose("Makefile"))
        self.assertFalse(stamp_check.is_prose("x.md.py"))

    # -- Review finding: a voided BLOCK never revives an older APPROVE ----

    def test_45_own_desk_commit_does_not_revive_older_se_approve(self):
        """Probe P5: code-only lane, SE APPROVE@R0, own-desk REPORT (R1),
        SE BLOCK@R1 on unchanged code, another own-desk report."""
        self._branch("lane-77")
        r0 = self._commit({"foo.py": "x = 1\n"}, "code")
        self._commit(self._stamp("grills/se1.md",
                                  "APPROVE", "senior-engineer", r0), "se approve")
        r1 = self._commit({"work/77-x/REPORT.md": "r\n"}, "report")
        self._commit(self._stamp("grills/se2.md",
                                  "BLOCK", "senior-engineer", r1), "se block")
        self._commit({"work/77-x/REPORT-SWING2.md": "r2\n"},
                     "report 2")
        code, out = self._run("master", "lane-77")
        self.assertEqual(1, code, out)
        self.assertIn("se1.md superseded by BLOCK grills/se2.md", out)
        self.assertIn("senior-engineer: FAIL - no covering APPROVE", out)

    def test_46_prose_commit_does_not_revive_older_se_approve(self):
        """Probe P1, mixed lane."""
        self._branch("lane")
        r0 = self._commit({"foo.py": "x = 1\n", "notes.md": "p\n"}, "mixed")
        self._commit(self._stamp("grills/se1.md",
                                  "APPROVE", "senior-engineer", r0), "se approve")
        r1 = self._commit({"notes.md": "p1\n"}, "prose")
        self._commit(self._stamp("grills/se2.md",
                                  "BLOCK", "senior-engineer", r1), "se block")
        r2 = self._commit({"notes.md": "p2\n"}, "prose again")
        self._commit(self._stamp("grills/ar.md",
                                  "APPROVE", "adversarial-reviewer", r2), "ar")
        code, out = self._run("master", "lane")
        self.assertEqual(1, code, out)
        self.assertIn("senior-engineer: FAIL - no covering APPROVE", out)

    def test_47_code_commit_does_not_revive_older_ar_approve(self):
        """Probe P2, the mirror."""
        self._branch("lane")
        r0 = self._commit({"foo.py": "x = 1\n", "notes.md": "p\n"}, "mixed")
        self._commit(self._stamp("grills/ar1.md",
                                  "APPROVE", "adversarial-reviewer", r0), "ar")
        r1 = self._commit({"foo.py": "x = 2\n"}, "code")
        self._commit(self._stamp("grills/ar2.md",
                                  "BLOCK", "adversarial-reviewer", r1), "ar block")
        r2 = self._commit({"foo.py": "x = 3\n"}, "code again")
        self._commit(self._stamp("grills/se.md",
                                  "APPROVE", "senior-engineer", r2), "se")
        code, out = self._run("master", "lane")
        self.assertEqual(1, code, out)
        self.assertIn("adversarial-reviewer: FAIL - no covering APPROVE", out)

    def test_48_block_at_same_revision_supersedes_approve(self):
        """Same REVISION: fail closed, the BLOCK wins even once a change
        of the other kind has voided it."""
        self._branch("lane")
        r0 = self._commit({"foo.py": "x = 1\n", "notes.md": "p\n"}, "mixed")
        self._commit(self._stamp("grills/se1.md",
                                  "APPROVE", "senior-engineer", r0), "se approve")
        self._commit(self._stamp("grills/se2.md",
                                  "BLOCK", "senior-engineer", r0), "se block")
        r1 = self._commit({"notes.md": "p1\n"}, "prose")
        self._commit(self._stamp("grills/ar.md",
                                  "APPROVE", "adversarial-reviewer", r1), "ar")
        code, out = self._run("master", "lane")
        self.assertEqual(1, code, out)
        self.assertIn("se1.md superseded by BLOCK", out)


    # -- a clean base merge keeps stamps -----------------------------------

    def _merge(self, other, message="merge base"):
        self._git("-c", "user.email=fixture@example.invalid",
                  "-c", "user.name=fixture", "-c", "commit.gpgsign=false",
                  "merge", "-q", "--no-ff", "-m", message, other)
        return self._git("rev-parse", "HEAD")

    def _advance_master(self, files, message="master moves"):
        self._git("checkout", "-q", "master")
        sha = self._commit(files, message)
        self._git("checkout", "-q", "lane")
        return sha

    def test_49_clean_base_merge_keeps_both_approves(self):
        self._mixed_both_approved()
        self._advance_master({"other.py": "o = 1\n", "other.md": "o\n"})
        self._merge("master")
        code, out = self._run("master", "lane")
        self.assertEqual(0, code, out)
        self.assertIn("senior-engineer: PASS", out)
        self.assertIn("adversarial-reviewer: PASS", out)

    def test_50_code_conflict_fix_voids_se_only(self):
        self._mixed_both_approved()
        self._advance_master({"foo.py": "x = 9\n"})
        self.assertEqual(1, self._merge_no_commit("master"), "fixture needs a conflict")
        self._commit({"foo.py": "x = 10\n"}, "resolve conflict")
        code, out = self._run("master", "lane")
        self.assertEqual(1, code, out)
        self.assertIn("senior-engineer: FAIL - no covering APPROVE", out)
        self.assertIn("adversarial-reviewer: PASS", out)

    def test_51_prose_conflict_fix_voids_ar_only(self):
        self._mixed_both_approved()
        self._advance_master({"notes.md": "master prose\n"})
        self.assertEqual(1, self._merge_no_commit("master"), "fixture needs a conflict")
        self._commit({"notes.md": "resolved prose\n"}, "resolve conflict")
        code, out = self._run("master", "lane")
        self.assertEqual(1, code, out)
        self.assertIn("adversarial-reviewer: FAIL - no covering APPROVE", out)
        self.assertIn("senior-engineer: PASS", out)

    def test_52_both_sides_auto_merge_counts_as_resolved(self):
        """Fail closed: a file both sides changed is unreviewed in its merged
        form even when git merged it without a conflict (the hub's default,
        stricter than the ruling's "hand-resolved")."""
        self._commit({"foo.py": "a\nb\nc\nd\ne\nf\n"}, "base foo")
        self._branch("lane")
        rev = self._commit({"foo.py": "A\nb\nc\nd\ne\nf\n"}, "lane edit")
        self._commit(self._stamp("grills/se.md",
                                  "APPROVE", "senior-engineer", rev), "se")
        self._advance_master({"foo.py": "a\nb\nc\nd\ne\nF\n"})
        self._merge("master")
        code, out = self._run("master", "lane")
        self.assertEqual(1, code, out)
        self.assertIn("senior-engineer: FAIL - no covering APPROVE", out)

    def test_53_merge_of_non_base_branch_still_stale(self):
        self._mixed_both_approved()
        self._git("checkout", "-q", "-b", "side", "master")
        self._commit({"side.py": "s = 1\n"}, "unreviewed side work")
        self._git("checkout", "-q", "lane")
        self._advance_master({"other.py": "o = 1\n"})
        self._merge("side", "merge a side branch")
        self._merge("master")
        code, out = self._run("master", "lane")
        self.assertEqual(1, code, out)
        self.assertIn("is not a base merge", out)

    def test_54_revision_on_base_still_stale_with_base_merge(self):
        """Test 16's shape plus a later base merge: REVISION is a master
        commit, so no merge rescues it. Killing the on-base guard flips it."""
        c1 = self._commit({"foo.py": "v1\n"}, "master c1")
        self._commit({"foo.py": "v2\n"}, "master c2 (fork point)")
        self._branch("lane")
        self._commit({"foo.py": "v1\n"}, "lane reverts foo.py to v1")
        self._advance_master({"other.txt": "o\n"})
        self._merge("master")
        self._commit(self._stamp("grills/se.md",
                                  "APPROVE", "senior-engineer", c1),
                     "se approve of a master commit")
        code, out = self._run("master", "lane")
        self.assertEqual(1, code, out)
        self.assertIn("stale base", out)

        import types
        patched = types.ModuleType("stamp_check_mutant_merge")
        with open(stamp_check.__file__, encoding="utf-8") as fh:
            src = fh.read()
        marker = '    if _is_ancestor(rev, base_commit):\n        return None, STALE_BASE\n'
        self.assertIn(marker, src, "merge mutant site text moved; update the marker")
        exec(compile(src.replace(marker, "", 1), stamp_check.__file__, "exec"),
             patched.__dict__)
        cwd = os.getcwd()
        os.chdir(self.repo)
        try:
            mcode, mlines = patched.run("master", "lane")
        finally:
            os.chdir(cwd)
        self.assertEqual(0, mcode, "\n".join(mlines))

    def test_55_block_survives_clean_base_merge(self):
        self._branch("lane")
        rev = self._commit({"foo.py": "x = 1\n"}, "code")
        self._commit(self._stamp("grills/se.md",
                                  "BLOCK", "senior-engineer", rev), "se block")
        self._advance_master({"other.py": "o = 1\n"})
        self._merge("master")
        code, out = self._run("master", "lane")
        self.assertEqual(1, code, out)
        self.assertIn("BLOCK: FAIL - covering BLOCK", out)

    def test_56_lane_merged_into_base_copy_is_off_chain(self):
        """A merge whose first parent is the base side leaves REVISION off
        HEAD's first-parent chain: still stale."""
        self._mixed_both_approved()
        self._advance_master({"other.py": "o = 1\n"})
        self._git("checkout", "-q", "-b", "flipped", "master")
        self._merge("lane", "merge lane into a base copy")
        code, out = self._run("master", "flipped")
        self.assertEqual(1, code, out)
        self.assertIn("first-parent chain", out)

    def test_57_lane_commit_after_base_merge_still_voids(self):
        self._mixed_both_approved()
        self._advance_master({"other.py": "o = 1\n"})
        self._merge("master")
        self._commit({"foo.py": "x = 2\n"}, "post-merge code edit")
        code, out = self._run("master", "lane")
        self.assertEqual(1, code, out)
        self.assertIn("senior-engineer: FAIL - no covering APPROVE", out)
        self.assertIn("adversarial-reviewer: PASS", out)

    def _merge_no_commit(self, other):
        # merge checks identity even with --no-commit; CI has none
        done = subprocess.run(["git", "-C", self.repo,
                               "-c", "user.email=fixture@example.invalid",
                               "-c", "user.name=fixture", "merge", "-q",
                               "--no-ff", "--no-commit", other],
                              capture_output=True, text=True, timeout=30)
        return done.returncode

    def _finish_merge(self, message="merge base"):
        self._git("-c", "user.email=fixture@example.invalid",
                  "-c", "user.name=fixture", "-c", "commit.gpgsign=false",
                  "commit", "-q", "--no-edit", "-m", message)

    def test_58_merge_s_ours_voids_kind_of_dropped_base_change(self):
        """SE round-1 F1: `-s ours` keeps the lane's tree, so no path differs
        from every parent, yet master's change is silently undone."""
        self._mixed_both_approved()
        self._advance_master({"other.py": "o = 1\n"})
        self._git("-c", "user.email=fixture@example.invalid",
                  "-c", "user.name=fixture", "-c", "commit.gpgsign=false",
                  "merge", "-q", "-s", "ours", "-m", "merge base, ours", "master")
        code, out = self._run("master", "lane")
        self.assertEqual(1, code, out)
        self.assertIn("senior-engineer: FAIL - no covering APPROVE", out)
        self.assertIn("adversarial-reviewer: PASS", out)

    def test_59_checkout_ours_conflict_fix_voids_its_kind(self):
        self._mixed_both_approved()
        self._advance_master({"foo.py": "x = 9\n"})
        self.assertEqual(1, self._merge_no_commit("master"), "fixture needs a conflict")
        self._git("checkout", "--ours", "foo.py")
        self._git("add", "foo.py")
        self._finish_merge()
        code, out = self._run("master", "lane")
        self.assertEqual(1, code, out)
        self.assertIn("senior-engineer: FAIL - no covering APPROVE", out)
        self.assertIn("adversarial-reviewer: PASS", out)

    def test_60_merge_removing_base_added_file_voids_its_kind(self):
        self._mixed_both_approved()
        self._advance_master({"new.py": "n = 1\n"})
        self.assertEqual(0, self._merge_no_commit("master"))
        self._git("rm", "-q", "-f", "new.py")
        self._finish_merge()
        code, out = self._run("master", "lane")
        self.assertEqual(1, code, out)
        self.assertIn("senior-engineer: FAIL - no covering APPROVE", out)
        self.assertIn("adversarial-reviewer: PASS", out)

    def test_61_merge_removing_reviewed_lane_file_voids_its_stamp(self):
        """The merge drops the lane's only code file, so the PR needs no SE
        stamp and the gate passes; the SE APPROVE itself no longer covers."""
        self._mixed_both_approved()
        self._advance_master({"other.md": "o\n"})
        self.assertEqual(0, self._merge_no_commit("master"))
        self._git("rm", "-q", "foo.py")
        self._finish_merge()
        code, out = self._run("master", "lane")
        self.assertEqual(0, code, out)
        self.assertIn("covers=no (REVISION..HEAD adds or changes "
                      "non-grills-addition(s): [('M', 'foo.py')])", out)
        self.assertIn("adversarial-reviewer: PASS", out)

    def test_62_octopus_merge_with_base_is_not_a_base_merge(self):
        """SE round-1 F3: the three-parent guard, pinned by its reason."""
        self._mixed_both_approved()
        self._git("checkout", "-q", "-b", "side", "master")
        self._commit({"side.md": "s\n"}, "unreviewed side work")
        self._git("checkout", "-q", "lane")
        self._advance_master({"other.py": "o = 1\n"})
        self._git("-c", "user.email=fixture@example.invalid",
                  "-c", "user.name=fixture", "-c", "commit.gpgsign=false",
                  "merge", "-q", "--no-ff", "-m", "octopus", "master", "side")
        self.assertEqual(3, len(self._git("rev-list", "--parents", "-n1",
                                          "HEAD").split()) - 1)
        code, out = self._run("master", "lane")
        self.assertEqual(1, code, out)
        self.assertIn("is not a base merge", out)
    def test_63_identical_change_on_both_sides_does_not_count(self):
        """SE round-2 F1: master adds a byte-identical foo.py; the merge takes
        it unchanged from either parent, so both APPROVEs still cover."""
        self._mixed_both_approved()
        self._advance_master({"foo.py": "x = 1\n"})
        self._merge("master")
        code, out = self._run("master", "lane")
        self.assertEqual(0, code, out)
        self.assertRegex(out, r"senior-engineer: \S+ stamp=APPROVE \S+ covers=yes")
        self.assertIn("adversarial-reviewer: PASS", out)

    def test_64_stacked_lane_with_two_merge_bases_is_stale(self):
        """SE round-2 F2: lane forks sibling lane x; master merges x between
        two base merges, so the second has two merge-bases: refused."""
        self._branch("x")
        self._commit({"x.py": "x\n"}, "x work")
        self._branch("lane")
        rev = self._commit({"foo.py": "x = 1\n", "notes.md": "p\n"}, "lane")
        self._commit(self._stamp("grills/se.md",
                                  "APPROVE", "senior-engineer", rev), "se")
        self._commit(self._stamp("grills/ar.md",
                                  "APPROVE", "adversarial-reviewer", rev), "ar")
        self._advance_master({"m1.py": "1\n"})
        self._merge("master")
        self._git("checkout", "-q", "master")
        self._merge("x", "master merges x")
        self._git("checkout", "-q", "lane")
        self._merge("master")
        self.assertEqual(2, len(self._git("merge-base", "--all",
                                          "HEAD^1", "HEAD^2").split()))
        code, out = self._run("master", "lane")
        self.assertEqual(1, code, out)
        self.assertIn("has 2 merge-bases", out)

if __name__ == "__main__":
    unittest.main()
