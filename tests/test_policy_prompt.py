"""Tests for the arming side of the one-shot unlocks.

This gate is the mechanism standing between an agent and the contract, the
settings, and the hooks themselves. Until 2026-08-24 it had no test of any kind,
which is why three defects in the hook layer were all found by accident in one
day.

**Two classes of test live here and the split is deliberate.** `ArmsOnTheRealInstruction`
must pass before and after any change: it is the lockout guard, and a "fix" that
breaks it locks the operator out of their own tree with no way back in, since
repairing the gate requires the gate. `RefusesAMention` is red on purpose until
the mention defect is fixed — those are the contract, written down before the
code that satisfies them.

Nothing here touches the real tree: every run points the hook at a fresh
temporary root, so the unlock files it writes land there and expire unread.
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
# Seams: a scratch copy of the hooks dir runs this suite against a
# candidate or a mutant without touching the policy paths.
HOOK = Path(os.environ.get("POLICY_PROMPT_HOOK")
            or ROOT / ".claude" / "hooks" / "policy-prompt.py")
MUTATE = Path(os.environ.get("POLICY_MUTATE_HOOK")
              or ROOT / ".claude" / "hooks" / "policy-mutate.py")

GRANTS = {"policy": "policy-unlock", "net": "net-unlock", "env": "env-unlock"}

SESSION_A = "11111111-aaaa-4aaa-8aaa-111111111111"
SESSION_B = "22222222-bbbb-4bbb-8bbb-222222222222"

# The real denial, verbatim in shape (666 wording). It names the exact path and
# instructs the human to submit it, which is what makes pasting it back the
# likeliest way this gate ever opens by accident.
DENIAL = ("policy-mutate: 'CLAUDE.md' is a policy path. Submit "
          "'auth-policy CLAUDE.md' as its own user message, then retry the "
          "mutation. That arms a task unlock for the named path: every "
          "mutation of it is allowed until a new session, 'revoke-policy', "
          "a new unlock, or 8 h.")


class HookCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="unlock-test-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def submit(self, prompt, session=SESSION_A):
        """Run the hook exactly as the harness does: one JSON payload on stdin.

        `session_id` is a guaranteed field on the real UserPromptSubmit payload,
        confirmed against the published hook documentation rather than assumed --
        the fix below is worthless if it is ever absent, because both sides would
        fall back to one shared slot without saying so.
        """
        r = subprocess.run(
            [sys.executable, str(HOOK)],
            input=json.dumps({"prompt": prompt, "session_id": session}),
            capture_output=True, text=True,
            env=dict(os.environ, HARNESS_ROOT=str(self.root)))
        self.assertEqual(r.returncode, 0, r.stderr)
        return self.grants(session)

    def grants(self, session=SESSION_A):
        """Whatever grants exist for this session, session-keyed file preferred.

        The fallback to the unkeyed name is not laziness -- it is the transition
        the real fix has to make in the same order. Flipping the arming side to a
        session-keyed name before the consuming side can read one would mean no
        grant is consumable by anybody, and the edit that repairs that needs a
        grant. The consuming side learns to read both names first.
        """
        out = {}
        for tag, fname in GRANTS.items():
            keyed = self.root / ".agent-log" / ("%s-%s.json" % (fname, session))
            legacy = self.root / ".agent-log" / (fname + ".json")
            f = keyed if keyed.exists() else legacy
            if f.exists():
                out[tag] = json.loads(f.read_text(encoding="utf-8"))
        return out

    def norm_of(self, rel):
        return os.path.normcase(os.path.realpath(os.path.join(self.root, rel)))

    def assertNothingArmed(self, prompt):
        armed = self.submit(prompt)
        self.assertEqual(armed, {}, "armed on a message that is not the instruction")


class ArmsOnTheRealInstruction(HookCase):
    """The lockout guard. Every one of these must stay green through any fix --
    the gate that cannot be opened deliberately is worse than the one that opens
    by accident, because repairing it requires opening it."""

    def test_the_bare_instruction_arms(self):
        armed = self.submit("auth-policy CLAUDE.md")
        self.assertIn("policy", armed)
        self.assertEqual(armed["policy"]["path"], "CLAUDE.md")
        self.assertEqual(armed["policy"]["norm"], self.norm_of("CLAUDE.md"))
        self.assertFalse(armed["policy"]["used"])

    def test_a_nested_path_arms(self):
        armed = self.submit(r"auth-policy .claude\hooks\policy-prompt.py")
        self.assertEqual(armed["policy"]["norm"],
                         self.norm_of(r".claude\hooks\policy-prompt.py"))

    def test_surrounding_whitespace_is_tolerated(self):
        # The operator types this by hand many times a day.
        self.assertIn("policy", self.submit("  auth-policy CLAUDE.md \n"))

    def test_a_quoted_path_arms(self):
        for form in ("auth-policy `CLAUDE.md`", "auth-policy 'CLAUDE.md'",
                     'auth-policy "CLAUDE.md"'):
            with self.subTest(form=form):
                self.assertEqual(self.submit(form)["policy"]["path"], "CLAUDE.md")

    def test_the_net_vocabulary_arms(self):
        self.assertEqual(self.submit("auth-net example.invalid")["net"]["host"],
                         "example.invalid")

    def test_the_env_vocabulary_arms(self):
        self.assertIn("env", self.submit("auth-env"))

    def test_an_unrelated_message_arms_nothing(self):
        self.assertNothingArmed("please read the contract and tell me what it says")


class RefusesAMention(HookCase):
    """RED UNTIL FIXED -- these are the contract, not a description of the code.

    The defect: the pattern searches the whole message for the keyword anywhere,
    so it cannot tell the human *instructing* the unlock from text *mentioning*
    it. Confirmed by an operator-run probe on 2026-08-24: all four inputs armed,
    including one whose normalized path pointed at the real protected file.

    Severity comes from the channel. Arming is trusted because only the composer
    can arm -- but the human's message routinely carries text the human did not
    author: pasted logs, diagnostic output, documentation, file contents. That is
    untrusted text reaching the authorization layer through the trusted channel.
    """

    def test_the_pasted_denial_does_not_arm(self):
        # The sharpest case. The system prints this text with the exact path and
        # tells the human to submit it, so the matching correlation is
        # manufactured rather than coincidental.
        self.assertNothingArmed(DENIAL)

    def test_a_description_of_the_syntax_does_not_arm(self):
        self.assertNothingArmed(
            "The syntax is: auth-policy CLAUDE.md as documented.")

    def test_a_prohibition_does_not_arm(self):
        # The pattern has no notion of polarity: text forbidding the action arms
        # it just as well as text requesting it.
        self.assertNothingArmed(
            "Never run auth-policy CLAUDE.md without reading it first.")

    def test_a_trailing_question_does_not_arm(self):
        # Returned by outside counsel as the bypass that kills prefix-anchoring:
        # anchored, names a real protected file, and is the natural thing a human
        # types immediately after a denial.
        self.assertNothingArmed(
            "auth-policy CLAUDE.md -- the gate told me to run this; why?")

    def test_pasted_diagnostic_output_does_not_arm(self):
        # This one reproduced live: pasting probe output into the session armed a
        # real grant.
        self.assertNothingArmed(
            "all 4 armed\n"
            'auth-policy <path>    armed=True {"path": "<path>"}\n'
            'auth-policy CLAUDE.md armed=True {"path": "CLAUDE.md"}')

    def test_prose_after_the_keyword_does_not_arm(self):
        self.assertNothingArmed("you will need to auth-policy it.")

    def test_a_mention_of_the_net_vocabulary_does_not_arm(self):
        self.assertNothingArmed(
            "the send gate is opened with auth-net example.invalid, for reference")

    def test_a_mention_of_the_env_vocabulary_does_not_arm(self):
        # The most exposed of the three: it takes no argument, so there is no
        # downstream path match to absorb a bad arm. Nothing stands between a
        # mention and a live grant.
        self.assertNothingArmed("the third vocabulary is auth-env, which I did not use")

    def test_only_the_first_match_arms_and_the_rest_are_discarded(self):
        # Recorded because it is real and currently silent, not because the fix
        # should special-case it: a message naming several protected paths arms
        # exactly one, chosen by position. Whole-message occupancy makes it moot.
        self.assertNothingArmed(
            "auth-policy CLAUDE.md and also auth-policy .claude/settings.json")


class GrantIsSessionScoped(HookCase):
    """RED UNTIL FIXED -- an earlier fix, and it fired for real before it was filed.

    One global grant slot, opened `"w"`. On 2026-08-24 the operator armed a grant
    at 21:45:45; a second session in the same tree armed its own at 21:46:06 and
    consumed it at 21:46:18. The operator's grant was destroyed 21 seconds after
    they typed it and the edit it authorized was refused.

    Two defects sit here and only the first is an inconvenience. The clobber costs
    availability. The sharper one is that consumption matches on normalized path
    alone, with no session identity -- so two sessions touching the SAME protected
    path means either can spend a grant the other operator typed. An earlier fix needs an
    accident to fire. This needs two sessions, which is the normal working pattern.
    """

    def test_the_grant_is_readable_by_the_session_that_armed_it(self):
        self.assertIn("policy", self.submit("auth-policy CLAUDE.md", SESSION_A))

    def test_a_second_session_does_not_destroy_a_pending_grant(self):
        self.submit("auth-policy CLAUDE.md", SESSION_A)
        self.submit(r"auth-policy .claude\settings.json", SESSION_B)
        still = self.grants(SESSION_A)
        self.assertIn("policy", still, "session B's arm destroyed session A's grant")
        self.assertEqual(still["policy"]["path"], "CLAUDE.md")
        self.assertFalse(still["policy"]["used"])

    def test_two_sessions_hold_different_grants_at_once(self):
        self.submit("auth-policy CLAUDE.md", SESSION_A)
        self.submit(r"auth-policy .claude\settings.json", SESSION_B)
        self.assertEqual(self.grants(SESSION_A)["policy"]["path"], "CLAUDE.md")
        self.assertEqual(self.grants(SESSION_B)["policy"]["path"],
                         r".claude\settings.json")

    def test_net_and_env_stay_unkeyed_until_their_consumers_can_read_keyed(self):
        """A residual, asserted so it stays deliberate.

        The first version of this test demanded all three vocabularies be
        session-keyed, which is the right end state and the wrong next step:
        net-post.py and env-global.py have not learned to read a keyed name, so
        keying these would make their grants unfindable and silently unusable.
        Same ordering rule that governs the policy grant -- reader first, writer
        second -- and the test asserted the destination instead of the step.

        Until then these two still share one slot and are still clobberable
        across sessions. auth-env is the most exposed of the three: it takes no
        argument, so no downstream path match can absorb a grant that leaked.
        """
        for prompt, tag in (("auth-env", "env"),
                            ("auth-net example.invalid", "net")):
            with self.subTest(tag=tag):
                self.submit(prompt, SESSION_A)
                log = self.root / ".agent-log"
                self.assertTrue((log / (GRANTS[tag] + ".json")).exists(),
                                "%s grant vanished from the name its consumer reads" % tag)
                self.assertFalse(
                    (log / ("%s-%s.json" % (GRANTS[tag], SESSION_A))).exists(),
                    "%s was keyed before its consumer could read a keyed name" % tag)


class ARefusalIsAudible(HookCase):
    """RED UNTIL FIXED -- senior engineer F4.

    Occupancy is right, but it made failure invisible: a message carrying an
    unlock verb that fails occupancy produces no grant, no log line, and no
    output, so "my unlock did not take" and "I typed nothing" are the same
    observation. That matters more here than anywhere else in the tree, because
    the file that would add the diagnostic is behind the gate -- if arming ever
    breaks, silence is the only symptom and there is no in-band way back.

    It also costs §4 a signal it has already used: an earlier fix was found by counting
    armed lines against consumed lines. A refusal that appears in neither count
    is invisible to exactly the audit that caught the original defect.
    """

    def log_text(self):
        f = self.root / ".agent-log" / "2026-08-24.md"
        if not f.exists():
            f = next(iter((self.root / ".agent-log").glob("*.md")), None)
        return f.read_text(encoding="utf-8") if f else ""

    def run_hook(self, prompt, session=SESSION_A):
        return subprocess.run(
            [sys.executable, str(HOOK)],
            input=json.dumps({"prompt": prompt, "session_id": session}),
            capture_output=True, text=True,
            env=dict(os.environ, HARNESS_ROOT=str(self.root))).stdout

    def test_a_refused_arming_is_logged(self):
        self.run_hook("The syntax is: auth-policy CLAUDE.md as documented.")
        self.assertIn("refused", self.log_text().lower(),
                      "a refused unlock left no trace in the audit log")

    def test_a_refused_arming_tells_the_operator(self):
        out = self.run_hook("Never run auth-policy CLAUDE.md without reading it first.")
        self.assertTrue(out.strip(), "a refused unlock said nothing to anyone")

    def test_a_message_with_no_unlock_verb_stays_silent(self):
        # The other half: refusing loudly must not mean narrating every message.
        self.run_hook("please read the contract and tell me what it says")
        self.assertNotIn("refused", self.log_text().lower())

    def test_a_successful_arming_is_not_logged_as_a_refusal(self):
        self.run_hook("auth-policy CLAUDE.md")
        log = self.log_text()
        self.assertIn("unlock-armed", log)
        self.assertNotIn("refused", log.lower())

    def test_the_policy_arm_line_carries_the_sid_and_net_env_do_not(self):
        # The policy arm line is policy-integrity's grant-end marker
        # (a new unlock replaces the old grant), keyed by ` sid=` at the end;
        # the prefix an earlier fix counts on is untouched, and net/env stay as they
        # were (one-shot, unkeyed).
        self.run_hook("auth-policy CLAUDE.md")
        self.run_hook("auth-policy-batch AGENTS.md README.md")
        self.run_hook("auth-net example.invalid")
        self.run_hook("auth-env")
        lines = [l for l in self.log_text().splitlines() if "unlock-armed" in l]
        self.assertEqual(4, len(lines))
        self.assertTrue(lines[0].endswith("unlock-armed (policy): CLAUDE.md sid=%s"
                                          % SESSION_A), lines[0])
        self.assertTrue(lines[1].endswith(
            "unlock-armed (policy): 2 path(s): AGENTS.md README.md sid=%s"
            % SESSION_A), lines[1])
        self.assertTrue(lines[2].endswith("unlock-armed (net): example.invalid"), lines[2])
        self.assertTrue(lines[3].endswith("unlock-armed (env): global env mutation"), lines[3])


class KnownResiduals(HookCase):
    """What the fix deliberately does NOT cover, asserted so it stays true.

    This class exists because the first draft of this file asserted the opposite
    and was wrong. It required a bare placeholder to be refused outright, which
    can only be enforced by checking that the captured token resolves to an
    existing file -- and that check breaks a real workflow: a policy path under
    the hooks directory is protected whether or not it exists yet, and the
    operator unlocked exactly such a path on 2026-08-24 in order to CREATE it.
    An existence check would have locked them out of their own tree that day.

    So the placeholder still arms, and that is accepted: it is unconsumable,
    because consumption demands an exact normalized-path match against a real
    write target. That was the original board finding and it was correct. The
    defect was never the placeholder -- it was the mention.
    """

    def test_a_lone_placeholder_arms_but_policy_mutate_will_not_consume_it(self):
        armed = self.submit("auth-policy <path>")
        self.assertIn("policy", armed, "occupancy does not and need not catch this")
        # The old body only checked the path string did not exist,
        # which cannot fail because '<path>' is not a legal filename. The real
        # claim is that the armed placeholder confers no power: hold it, attempt
        # a real policy mutation, require a denial.
        r = subprocess.run(
            [sys.executable, str(MUTATE)],
            input=json.dumps({
                "session_id": SESSION_A, "tool_name": "Edit",
                "cwd": str(self.root),
                "tool_input": {"file_path": str(self.root / "CLAUDE.md")}}),
            capture_output=True, text=True,
            env=dict(os.environ, HARNESS_ROOT=str(self.root)))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('"permissionDecision": "deny"', r.stdout,
                      "a placeholder grant was consumable against a real policy path")

    def test_a_grant_for_a_path_that_does_not_exist_yet_still_arms(self):
        # The lockout case, stated as its own test so no future fix quietly adds
        # an existence check: creating a new protected file needs the unlock too.
        armed = self.submit(r"auth-policy .claude\hooks\not-written-yet.py")
        self.assertEqual(armed["policy"]["norm"],
                         self.norm_of(r".claude\hooks\not-written-yet.py"))
# 2026-09-21: UseWindowIsOneTurnWide and BrowseWindowIsOneTurnWide removed
# with browser-loopback and the auth-browse/auth-use verbs they covered.


class RetiredVerbsSayRetired(HookCase):
    """RED UNTIL FIXED -- grill F-E, 2026-09-22 (senior F1 on the removal).

    auth-browse and auth-use arm nothing since 2026-09-21. Typed
    alone, they must not get the occupancy refusal: that tells the operator to
    retype the same message, which cannot ever work. They get their own event
    and say "retired".
    """

    log_text = ARefusalIsAudible.log_text
    run_hook = ARefusalIsAudible.run_hook

    def test_a_bare_retired_verb_is_refused_as_retired(self):
        for verb in ("auth-browse", "auth-use"):
            with self.subTest(verb=verb):
                self.root = Path(tempfile.mkdtemp(prefix="unlock-test-"))
                self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
                out = self.run_hook(verb)
                log = self.log_text()
                self.assertIn("retired", out.lower())
                self.assertIn("unlock-retired (%s)" % verb, log)
                self.assertNotIn("message was not the instruction alone", log)
                self.assertEqual(self.grants(), {})
                # senior-02: grants() reads only policy/net/env; no window file either.
                self.assertEqual(list((self.root / ".agent-log").glob("*unlock*.json")), [])

    def test_a_padded_bare_retired_verb_is_still_retired(self):
        # senior-03: dropping .strip() survived the suite; master armed padded verbs too.
        out = self.run_hook("  auth-browse\n")
        self.assertIn("retired", out.lower())
        self.assertIn("unlock-retired (auth-browse)", self.log_text())

    def test_a_retired_verb_before_a_live_one_keeps_the_occupancy_refusal(self):
        # senior-02 F1: F-E ruled on the BARE verb. A mixed message must still
        # be told it was not the instruction alone, as on master.
        out = self.run_hook("auth-browse auth-policy CLAUDE.md")
        log = self.log_text()
        self.assertIn("entire message", out)
        self.assertIn("unlock-refused", log)
        self.assertNotIn("unlock-retired", log)
        self.assertEqual(self.grants(), {})


class OnlyTheComposerArms(HookCase):
    """A function-hook plugin can submit a prompt that runs this
    hook. `source` other than `user` arms and revokes nothing; `user` and an
    absent field keep arming (lockout guard)."""

    def submit_from(self, prompt, source):
        payload = {"prompt": prompt, "session_id": SESSION_A}
        if source is not None:
            payload["source"] = source
        r = subprocess.run(
            [sys.executable, str(HOOK)], input=json.dumps(payload),
            capture_output=True, text=True,
            env=dict(os.environ, HARNESS_ROOT=str(self.root)))
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_user_and_absent_source_still_arm(self):
        for src in ("user", None):
            # Fresh grant slot per value, or the "user" grant masks a refused None.
            shutil.rmtree(self.root / ".agent-log", ignore_errors=True)
            self.submit_from("auth-policy CLAUDE.md", src)
            self.assertIn("policy", self.grants(), "source=%r locked out" % src)

    def test_non_composer_sources_arm_nothing(self):
        for src in ("system", "sdk", "loop_wakeup", "schedule_wakeup", "poll_event"):
            for prompt in ("auth-policy CLAUDE.md", "auth-policy-batch CLAUDE.md AGENTS.md",
                           "auth-net example.com", "auth-env"):
                out = self.submit_from(prompt, src)
                self.assertEqual(self.grants(), {}, "%r armed %r" % (src, prompt))
                self.assertIn("did not come from the composer", out)
        log = "".join(f.read_text(encoding="utf-8")
                      for f in (self.root / ".agent-log").glob("*.md"))
        self.assertIn("unlock-refused (source)", log, "a refusal left no audit line")

    def test_non_composer_cannot_revoke(self):
        self.submit_from("auth-policy CLAUDE.md", "user")
        self.submit_from("revoke-policy", "system")
        self.assertIn("policy", self.grants(), "a plugin prompt revoked the grant")

    def test_non_composer_prompt_without_a_verb_stays_silent(self):
        out = self.submit_from("please summarise the board", "system")
        self.assertEqual(out.strip(), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
