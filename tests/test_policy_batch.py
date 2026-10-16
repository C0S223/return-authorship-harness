"""Tests for auth-policy-batch: N one-shots typed in one message.

Both halves in one file, because the feature is a handshake and testing either
side alone proves nothing: the arming hook writes a shape the consuming hook has
to recognise, and the bug that would actually happen -- a batch grant that arms
cleanly and is then unspendable -- lives exactly in that seam. Several tests
below run the real arming hook and the real consuming hook in sequence against
one temporary root.

The regression guards matter as much as the feature tests. A batch grant is a
LIST of one-shots; the pre-157 flat grant is that list with one element. If the
single-path verb ever stops being consumable, the file that repairs it is itself
a policy path and the grant repairing it is unconsumable -- the lockout this
whole gate family is written to avoid.

Nothing here touches the real tree: every run points both hooks at a fresh
temporary root.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Seams: point both hooks at a scratch copy of the hooks dir to run this
# suite against a candidate or a mutant without touching the policy paths.
ARM = Path(os.environ.get("POLICY_PROMPT_HOOK")
           or ROOT / ".claude" / "hooks" / "policy-prompt.py")
GATE = Path(os.environ.get("POLICY_MUTATE_HOOK")
            or ROOT / ".claude" / "hooks" / "policy-mutate.py")

SESSION = "11111111-aaaa-4aaa-8aaa-111111111111"


class BatchCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="batch-test-"))
        (self.root / ".agent-log").mkdir()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    # -- the two hooks, run for real ------------------------------------------

    def arm(self, prompt, session=SESSION):
        r = subprocess.run(
            [sys.executable, str(ARM)],
            input=json.dumps({"prompt": prompt, "session_id": session}),
            capture_output=True, text=True,
            env=dict(os.environ, HARNESS_ROOT=str(self.root)))
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def attempt(self, rel, session=SESSION):
        """Try to mutate `rel`. True if the gate let it through."""
        r = subprocess.run(
            [sys.executable, str(GATE)],
            input=json.dumps({
                "session_id": session,
                "tool_name": "Edit",
                "cwd": str(self.root),
                "tool_input": {"file_path": str(self.root / rel)},
            }),
            capture_output=True, text=True,
            env=dict(os.environ, HARNESS_ROOT=str(self.root)))
        self.assertEqual(r.returncode, 0, r.stderr)
        return '"permissionDecision": "deny"' not in r.stdout

    # -- grant files ----------------------------------------------------------

    def grant_path(self, session=SESSION):
        return self.root / ".agent-log" / ("policy-unlock-%s.json" % session)

    def grant(self, session=SESSION):
        return json.loads(self.grant_path(session).read_text(encoding="utf-8"))

    def norm(self, rel):
        return os.path.normcase(os.path.realpath(os.path.join(self.root, rel)))

    def write_raw(self, payload, session=SESSION):
        self.grant_path(session).write_text(json.dumps(payload), encoding="utf-8")


class Arming(BatchCase):
    def test_two_paths_arm_two_unspent_entries_under_one_epoch(self):
        self.arm("auth-policy-batch CLAUDE.md AGENTS.md")
        g = self.grant()
        self.assertEqual(["CLAUDE.md", "AGENTS.md"],
                         [e["path"] for e in g["entries"]])
        self.assertEqual([False, False], [e["used"] for e in g["entries"]])
        self.assertIsInstance(g["epoch"], float)
        self.assertEqual("task", g["mode"], "666: an armed grant is task-lived")

    def test_eight_is_the_ceiling_and_nine_arms_nothing(self):
        self.arm("auth-policy-batch " + " ".join("p%d.md" % i for i in range(8)))
        self.assertEqual(8, len(self.grant()["entries"]))
        self.grant_path().unlink()
        out = self.arm("auth-policy-batch "
                       + " ".join("p%d.md" % i for i in range(9)))
        self.assertFalse(self.grant_path().exists(), "a 9-path batch armed")
        self.assertIn("armed nothing", out)

    def test_occupancy_holds_for_the_batch_verb_too(self):
        # The whole message must BE the instruction. Prose around it arms
        # nothing -- otherwise a pasted log quoting the verb is authorization.
        out = self.arm("please run auth-policy-batch CLAUDE.md when you can")
        self.assertFalse(self.grant_path().exists())
        self.assertIn("armed nothing", out)

    def test_traversal_absolute_and_glob_tokens_arm_nothing(self):
        # The rooted pair is the load-bearing half (F1, pass 3). `pathish` and
        # the `..` clause already own every other token here, so before the
        # rooted forms were added this test was green with the clause it names
        # deleted -- the fourth hollow proof this suite has produced. Deleting
        # `t[0] in "/\\"` now reddens it, which is the whole point.
        for tok in ("../CLAUDE.md", "..\\CLAUDE.md", "a/../../b.md",
                    "/CLAUDE.md", "\\Users\\x\\CLAUDE.md",
                    "C:\\Users\\x\\CLAUDE.md", "*.md", "hooks/[a-z].py"):
            with self.subTest(tok=tok):
                # Clear first: the subtests share one grant file, so a single
                # token that DOES arm leaves it on disk and every later subtest
                # reports "armed a grant" without arming anything. Measured --
                # deleting the rooted clause produced one real failure and four
                # cascades, which is a suite that cannot localise its own result.
                self.grant_path().unlink(missing_ok=True)
                self.arm("auth-policy-batch CLAUDE.md %s" % tok)
                self.assertFalse(self.grant_path().exists(),
                                 "%r armed a grant" % tok)

    def test_a_batch_message_is_not_read_as_the_single_verb(self):
        # `auth-policy-batch` starts with `auth-policy`; if branch order ever
        # flips, this message logs a refusal instead of arming, because the
        # single verb would see three tokens and fail occupancy.
        self.arm("auth-policy-batch CLAUDE.md AGENTS.md")
        self.assertIn("entries", self.grant())


class Consuming(BatchCase):
    def test_each_entry_covers_its_own_path_and_survives_the_edit(self):
        # 666 rewrite. Was test_each_entry_is_its_own_one_shot: asserted the
        # first Edit marked CLAUDE.md used and the second marked AGENTS.md.
        # A task grant marks nothing used; both entries stay armed.
        self.arm("auth-policy-batch CLAUDE.md AGENTS.md")
        self.assertTrue(self.attempt("CLAUDE.md"), "first entry was refused")
        self.assertEqual({"CLAUDE.md": False, "AGENTS.md": False},
                         {e["path"]: e["used"] for e in self.grant()["entries"]},
                         "a task grant marked an entry used")
        self.assertTrue(self.attempt("AGENTS.md"), "second entry was refused")
        self.assertFalse(any(e["used"] for e in self.grant()["entries"]))

    def test_a_batch_covers_repeated_edits_but_only_its_named_paths(self):
        # 666 rewrite. Was test_a_batch_is_not_a_blanket_unlock: asserted the
        # second Edit of CLAUDE.md was denied (one-shot). Now: repeated edits
        # of a named path are allowed; "not blanket" means the unnamed path
        # is still denied, which is the test below.
        self.arm("auth-policy-batch CLAUDE.md AGENTS.md")
        self.assertTrue(self.attempt("CLAUDE.md"))
        self.assertTrue(self.attempt("CLAUDE.md"),
                        "a task grant refused a second edit of a named path")

    def test_a_path_outside_the_batch_is_denied(self):
        self.arm("auth-policy-batch CLAUDE.md")
        self.assertFalse(self.attempt("AGENTS.md"))

    def test_a_stale_or_future_legacy_batch_is_refused(self):
        # No `mode`: the legacy one-shot shape keeps its 30 min (T7 pins it).
        for age in (1801, -120):
            with self.subTest(age=age):
                self.write_raw({"epoch": time.time() - age, "entries": [
                    {"path": "CLAUDE.md", "norm": self.norm("CLAUDE.md"),
                     "used": False}]})
                self.assertFalse(self.attempt("CLAUDE.md"))

    def test_malformed_entries_refuse_rather_than_crash_open(self):
        # rc 1 on a PreToolUse hook is NON-blocking, so a crash here is a crash
        # OPEN. Every junk shape must produce an ordinary deny.
        for ents in ("nope", 42, [1, 2], [None], {"a": 1}):
            with self.subTest(ents=ents):
                self.write_raw({"epoch": time.time(), "entries": ents})
                self.assertFalse(self.attempt("CLAUDE.md"))


class TheSinglePathVerbStillWorks(BatchCase):
    """Lockout guards: the flat pre-157 grant is one entry and must stay spendable."""

    def test_the_flat_legacy_grant_is_still_consumed(self):
        self.write_raw({"path": "CLAUDE.md", "norm": self.norm("CLAUDE.md"),
                        "epoch": time.time(), "used": False})
        self.assertTrue(self.attempt("CLAUDE.md"),
                        "the pre-157 grant shape stopped being consumable")

    def test_a_spent_flat_grant_is_still_refused(self):
        self.write_raw({"path": "CLAUDE.md", "norm": self.norm("CLAUDE.md"),
                        "epoch": time.time(), "used": True})
        self.assertFalse(self.attempt("CLAUDE.md"))

    def test_the_single_verb_still_arms_the_flat_shape(self):
        self.arm("auth-policy CLAUDE.md")
        g = self.grant()
        self.assertEqual("CLAUDE.md", g["path"])
        self.assertNotIn("entries", g)
        self.assertEqual("task", g["mode"])
        self.assertTrue(self.attempt("CLAUDE.md"))


class ReviewFindings(BatchCase):
    """One test per finding from the non-author review of the first build.

    Each was red against the unrepaired file; that is the only reason any of
    them is worth keeping.
    """

    def log_lines(self, needle):
        f = self.root / ".agent-log" / (time.strftime("%Y-%m-%d") + ".md")
        if not f.exists():
            return []
        return [l for l in f.read_text(encoding="utf-8").splitlines()
                if needle in l]

    def test_f1_a_whitespace_only_batch_arms_nothing_and_keeps_the_live_grant(self):
        # The tail pattern can consume a lone whitespace character, so this
        # message reached the arming call with zero tokens: it truncated the
        # operator's live grant, wrote {"entries": []}, and printed success.
        self.arm("auth-policy CLAUDE.md")
        before = self.grant_path().read_bytes()
        out = self.arm("auth-policy-batch \t \n")
        self.assertEqual(before, self.grant_path().read_bytes(),
                         "an empty batch destroyed a live grant")
        self.assertIn("armed nothing", out)
        self.assertTrue(self.attempt("CLAUDE.md"),
                        "the surviving grant was not consumable")

    def test_f2_prose_after_the_verb_arms_nothing_at_all(self):
        # The harm is not the junk word -- it is the REAL policy path sitting in
        # the prose beside it, which armed and was spendable.
        for prompt in (
            "auth-policy-batch CLAUDE.md and also .claude/settings.json",
            "auth-policy-batch scripts/run_tests.py\nalso update CLAUDE.md later",
            "auth-policy-batch CLAUDE.md please",
        ):
            with self.subTest(prompt=prompt):
                out = self.arm(prompt)
                self.assertFalse(self.grant_path().exists(),
                                 "prose armed a grant: %r" % prompt)
                self.assertIn("armed nothing", out)
                self.assertFalse(self.attempt("CLAUDE.md"),
                                 "a path named in prose became consumable")

    def test_f3_every_spend_writes_its_own_consumed_line(self):
        # policy-prompt.py:21-28 declares the armed-vs-consumed line count load
        # bearing: an earlier fix was found by comparing them, and a comma-joined line
        # logged ONE line for two spends.

        # This has to be ONE mutation spending two entries. The first version of
        # this test used two separate Edits, which write two lines under the
        # comma-join too -- it passed against the very defect it was written for,
        # caught by running it against the unrepaired file. An assertion that is
        # green on the bug proves nothing, so the shell payload is the test.
        self.arm("auth-policy-batch CLAUDE.md AGENTS.md")
        r = subprocess.run(
            [sys.executable, str(GATE)],
            input=json.dumps({
                "session_id": SESSION,
                "tool_name": "Bash",
                "cwd": str(self.root),
                "tool_input": {"command": "echo a > CLAUDE.md; echo b > AGENTS.md"},
            }),
            capture_output=True, text=True,
            env=dict(os.environ, HARNESS_ROOT=str(self.root)))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn('"permissionDecision": "deny"', r.stdout)
        self.assertEqual(2, len(self.log_lines("unlock-consumed")),
                         "two one-shots were spent under one audit line")
        self.assertEqual(1, len(self.log_lines("unlock-armed")))

    def test_f4_replacing_a_batch_says_what_it_discarded(self):
        # Truncation is correct -- one grant slot per session, an earlier fix, and
        # merging arms would build the blanket unlock 157 forbids. The defect
        # was doing it silently.
        # 666 rewrite: was "2 unspent" (one-shots); a task grant's entries are
        # never spent, so the count is the paths the old grant still covered.
        self.arm("auth-policy-batch CLAUDE.md AGENTS.md")
        out = self.arm("auth-policy README.md")
        self.assertIn("REPLACED", out)
        self.assertIn("2 path", out)
        self.assertEqual(1, len(self.log_lines("unlock-replaced")))

    def test_f4_replacing_nothing_stays_quiet(self):
        self.assertNotIn("REPLACED", self.arm("auth-policy CLAUDE.md"))

    def test_d3_the_replace_warning_is_policy_only(self):
        # The warning lives in the shared arm(), which is right -- one guard
        # where all four callers route through. Its WORDING does not travel:
        # net and env are deliberately unkeyed and shared across sessions, and
        # auth-env has no path to re-submit. Re-arming those is idempotent.
        self.arm("auth-env")
        self.assertNotIn("REPLACED", self.arm("auth-env"))
        self.arm("auth-net example.invalid")
        self.assertNotIn("REPLACED", self.arm("auth-net example.invalid"))

    def test_d1_a_quoted_path_arms_like_the_single_verb_does(self):
        for prompt in ('auth-policy-batch "CLAUDE.md" "AGENTS.md"',
                       "auth-policy-batch 'CLAUDE.md' 'AGENTS.md'",
                       "auth-policy-batch `CLAUDE.md` `AGENTS.md`"):
            with self.subTest(prompt=prompt):
                self.arm(prompt)
                self.assertEqual(["CLAUDE.md", "AGENTS.md"],
                                 [e["path"] for e in self.grant()["entries"]])
                self.assertTrue(self.attempt("CLAUDE.md"))
                self.grant_path().unlink()

    def test_d4_the_warning_count_matches_what_was_really_consumable(self):
        # The entries normalization is written twice, in two hooks, and an earlier fix
        # forbids sharing a module between them -- so the copies have to be
        # pinned by a test instead. `lost` is what arm() reports; the loop below
        # is what the gate actually honours. They must be the same number.
        # 666 rewrite: was `really` over the two UNEDITED paths and "%d unspent";
        # under a task grant every named path stays honoured after an edit, so
        # the count arm() reports must equal what the gate still allows: all 3.
        self.arm("auth-policy-batch CLAUDE.md AGENTS.md README.md")
        self.assertTrue(self.attempt("CLAUDE.md"))
        really = sum(1 for rel in ("CLAUDE.md", "AGENTS.md", "README.md")
                     if self.attempt(rel))
        self.assertEqual(3, really)
        out = self.arm("auth-policy CLAUDE.md")
        self.assertIn("%d path" % really, out,
                      "arm() reported a count the gate would not have honoured")

    def test_prose_words_carrying_a_dot_still_arm_nothing(self):
        # Reviewer residual 1: `pathish` is a shape test and occupancy is a
        # structure property, so dotted prose slipped through the shape test.
        for prompt in ("auth-policy-batch CLAUDE.md AGENTS.md thanks.",
                       "auth-policy-batch CLAUDE.md e.g. .claude/settings.json"):
            with self.subTest(prompt=prompt):
                self.assertIn("armed nothing", self.arm(prompt))
                self.assertFalse(self.grant_path().exists())


class MultiTargetMutations(BatchCase):
    """The seam the first suite never drove: one mutation, several hits.

    `Edit` carries one file_path, so every earlier test produced exactly one
    hit and neither the dedupe nor the multi-entry spend ever ran. A shell
    command with two redirects is the only shape that produces more, and it is
    the shape work-order decision 3 makes a claim about.
    """

    def shell(self, cmd, session=SESSION):
        r = subprocess.run(
            [sys.executable, str(GATE)],
            input=json.dumps({
                "session_id": session,
                "tool_name": "Bash",
                "cwd": str(self.root),
                "tool_input": {"command": cmd},
            }),
            capture_output=True, text=True,
            env=dict(os.environ, HARNESS_ROOT=str(self.root)))
        self.assertEqual(r.returncode, 0, r.stderr)
        return '"permissionDecision": "deny"' not in r.stdout

    def consumed(self):
        f = self.root / ".agent-log" / (time.strftime("%Y-%m-%d") + ".md")
        if not f.exists():
            return []
        return [l for l in f.read_text(encoding="utf-8").splitlines()
                if "unlock-consumed" in l]

    def test_the_same_path_named_twice_logs_exactly_one_line(self):
        # 666 rewrite: was ..._spends_exactly_one_entry, asserting unspent()
        # == []. The dedupe still holds -- one mutation naming one file twice
        # is one authorization -- and is now visible as ONE consumed line.
        self.arm("auth-policy CLAUDE.md")
        self.assertTrue(self.shell("echo a > CLAUDE.md; echo b > CLAUDE.md"),
                        "one mutation naming one file twice was refused")
        self.assertEqual(1, len(self.consumed()))

    def test_two_paths_in_one_mutation_log_both(self):
        # 666 rewrite: was ..._spend_both_entries, asserting unspent() == [].
        self.arm("auth-policy-batch CLAUDE.md AGENTS.md")
        self.assertTrue(self.shell("echo a > CLAUDE.md; echo b > AGENTS.md"))
        self.assertEqual(2, len(self.consumed()), "a covered hit went unlogged")

    def test_a_repeated_path_still_arms_two_entries(self):
        # 666 rewrite: was test_a_repeated_path_arms_a_repeated_one_shot,
        # asserting the first mutation left one entry unspent and the second
        # spent it. Parsing is unchanged (a repeated token is a repeated
        # entry) and the repeat is now moot: both mutations are allowed
        # either way, and nothing is marked used.
        self.arm("auth-policy-batch CLAUDE.md CLAUDE.md")
        self.assertEqual(2, len(self.grant()["entries"]),
                         "a repeated token did not arm a second entry")
        self.assertTrue(self.shell("echo a > CLAUDE.md"), "first edit refused")
        self.assertTrue(self.shell("echo b > CLAUDE.md"), "second edit refused")
        self.assertFalse(any(e["used"] for e in self.grant()["entries"]))

    def test_a_partly_covered_mutation_is_denied_and_logs_nothing(self):
        # T2. Was ..._spends_nothing, asserting unspent() == ["CLAUDE.md"].
        # A task grant spends nothing anyway; the observable is the ledger:
        # no `unlock-consumed` line for a mutation that was refused.
        self.arm("auth-policy CLAUDE.md")
        self.assertFalse(self.shell("echo a > CLAUDE.md; echo b > AGENTS.md"))
        self.assertEqual([], self.consumed(),
                         "a refused mutation wrote a consumed line")


class TaskGrants(BatchCase):
    """Task-lived policy grants: session id + `revoke-policy` + 8 h cap. T1-T7 and T9 of the
    work order; T8 lives in scripts/test_policy_integrity.py."""

    def consumed(self):
        return self.log_lines("unlock-consumed")

    def deny_text(self, rel, session=SESSION):
        r = subprocess.run(
            [sys.executable, str(GATE)],
            input=json.dumps({"session_id": session, "tool_name": "Edit",
                              "cwd": str(self.root),
                              "tool_input": {"file_path": str(self.root / rel)}}),
            capture_output=True, text=True,
            env=dict(os.environ, HARNESS_ROOT=str(self.root)))
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def task_grant(self, rel="CLAUDE.md", age=0, mode="task"):
        g = {"epoch": time.time() - age, "entries": [
            {"path": rel, "norm": self.norm(rel), "used": False}]}
        if mode:
            g["mode"] = mode
        self.write_raw(g)

    def test_t1_one_grant_two_edits_two_consumed_lines(self):
        self.arm("auth-policy CLAUDE.md")
        self.assertTrue(self.attempt("CLAUDE.md"))
        self.assertTrue(self.attempt("CLAUDE.md"), "second edit refused")
        self.assertEqual(2, len(self.consumed()),
                         "one line per allowed edit is the integrity ledger")

    def log_lines(self, needle):
        f = self.root / ".agent-log" / (time.strftime("%Y-%m-%d") + ".md")
        if not f.exists():
            return []
        return [l for l in f.read_text(encoding="utf-8").splitlines()
                if needle in l]

    def test_t3_the_cap_is_eight_hours(self):
        # 28790, not 28799 (S2-4, SE R2): a subprocess start under load ate
        # the 1 s margin; the boundary itself is pinned by the deny below.
        self.task_grant(age=28790)
        self.assertTrue(self.attempt("CLAUDE.md"), "denied inside the cap")
        self.task_grant(age=28800)
        out = self.deny_text("CLAUDE.md")
        self.assertIn('"permissionDecision": "deny"', out)
        self.assertIn("grants last 8 h", out)
        self.assertNotIn("30 min", out)
        self.assertIn("revoke-policy", out)

    def test_t4_revoke_alone_ends_the_grant_and_a_mention_does_not(self):
        self.arm("auth-policy CLAUDE.md")
        # Leading prose, then TRAILING prose (S2-2): the trailing form
        # is the vector that kills prefix-anchoring, and it is what an
        # operator types right after a denial ("revoke-policy -- why?").
        for mention in ("please revoke-policy", "revoke-policy please",
                        "revoke-policy -- why?"):
            with self.subTest(mention=mention):
                out = self.arm(mention)
                self.assertTrue(self.grant_path().exists(),
                                "a mention revoked: %r" % mention)
                self.assertIn("armed nothing", out)
        self.assertEqual(3, len(self.log_lines("unlock-refused")),
                         "a refused revoke left no audible line")
        self.assertTrue(self.attempt("CLAUDE.md"), "a mention ended the grant")
        out = self.arm("revoke-policy")
        self.assertFalse(self.grant_path().exists(), "revoke left the grant")
        self.assertIn("revoked", out)
        self.assertFalse(self.attempt("CLAUDE.md"), "edit allowed after revoke")
        # S2-1: every revoke line ends in ` sid=<sid>` -- policy-integrity's
        # grant-end marker for this session and no other.
        self.assertEqual(1, len(self.log_lines(
            "unlock-revoked (policy): 1 path(s) sid=%s" % SESSION)))
        self.arm("  revoke-policy \n")
        self.assertEqual(1, len(self.log_lines(
            "unlock-revoked (policy): nothing to revoke sid=%s" % SESSION)))

    def test_t5_rearm_with_another_path_replaces_the_grant(self):
        self.arm("auth-policy CLAUDE.md")
        self.assertTrue(self.attempt("CLAUDE.md"))
        self.arm("auth-policy AGENTS.md")
        self.assertFalse(self.attempt("CLAUDE.md"), "the old path survived")
        self.assertTrue(self.attempt("AGENTS.md"), "the new path was refused")

    def test_t6_another_session_cannot_use_the_grant(self):
        self.arm("auth-policy CLAUDE.md")
        self.assertFalse(self.attempt("CLAUDE.md", session="other-session"))
        self.assertTrue(self.attempt("CLAUDE.md"))

    def test_t7_a_legacy_grant_is_still_one_shot_and_30_min(self):
        self.task_grant(mode=None)
        self.assertTrue(self.attempt("CLAUDE.md"))
        self.assertFalse(self.attempt("CLAUDE.md"), "a legacy grant re-spent")
        self.task_grant(mode=None, age=1801)
        out = self.deny_text("CLAUDE.md")
        self.assertIn("grants last 30 min", out)

    def test_t9_on_cloud_revoke_arms_and_revokes_nothing(self):
        self.arm("auth-policy CLAUDE.md")
        for prompt in ("revoke-policy", "auth-policy AGENTS.md"):
            with self.subTest(prompt=prompt):
                r = subprocess.run(
                    [sys.executable, str(ARM)],
                    input=json.dumps({"prompt": prompt, "session_id": SESSION}),
                    capture_output=True, text=True,
                    env=dict(os.environ, HARNESS_ROOT=str(self.root),
                             CLAUDE_CODE_REMOTE="true"))
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn("NOTHING", r.stdout)
                self.assertEqual("CLAUDE.md", self.grant()["path"],
                                 "the cloud boundary touched the grant")


class MalformedGrantsRefuse(BatchCase):
    """Crash-open guard. rc 1 on a PreToolUse hook is NON-BLOCKING, so any
    uncaught exception here is a gate that fails open. Every junk shape must
    produce an ordinary deny and rc 0."""

    def test_junk_grant_shapes_all_deny(self):
        for payload in (
            {"epoch": time.time(), "entries": {}},
            {"epoch": time.time(), "entries": [[]]},
            {"epoch": time.time(), "entries": [None, 1, "x"]},
            {"epoch": time.time(), "entries": [{"norm": None}]},
            {"epoch": time.time(), "entries": [{}, {}]},
            # D2: this entry carries a CORRECT norm on purpose. Without it the
            # deny came from the unmatched path, `covered` went False, and the
            # epoch conjunct was never evaluated -- the case was green whether
            # or not the isinstance guard existed. Same failure as the first F3
            # test: an assertion green on the defect it names. With the norm
            # right, the epoch is the only thing left that can refuse it.
            {"epoch": "junk", "entries": [{"path": "CLAUDE.md",
                                           "norm": self.norm("CLAUDE.md"),
                                           "used": False}]},
            # The one truthy non-list shape, which drives the `not isinstance(
            # ents, list)` fallback rather than the empty-pool path.
            {"epoch": time.time(), "entries": "a string"},
            {"epoch": time.time(), "entries": None, "path": "CLAUDE.md",
             "used": False},
            {"epoch": time.time()},
            {},
        ):
            with self.subTest(payload=payload):
                self.write_raw(payload)
                self.assertFalse(self.attempt("CLAUDE.md"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
