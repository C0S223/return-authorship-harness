"""Tests for the consuming side of the one-shot unlocks.

Written immediately after teaching this gate to read session-keyed grants,
because "it compiles" is not "it works" and the failure mode here has no way
out: if consumption breaks, the file that repairs it is itself a protected path,
and the grant that would authorize that repair can no longer be consumed. The
gate gates its own repair.

So every test below is a lockout guard first and a feature test second. The
unkeyed fallback especially -- it is the only thing keeping grants consumable
until the arming side switches names.

Nothing here touches the real tree: each run points the hook at a fresh
temporary root and writes its own grant files there.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import shutil
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# POLICY_MUTATE_HOOK mirrors test_shell_scope.py's SHELL_SCOPE_HOOK seam: point
# it at a COPY of the whole hooks dir to run this suite against a mutated gate.
# The copy has to be the whole directory, not one file, because policy-mutate
# imports its shell-scope sibling from its OWN dirname -- so a seam naming only
# this file would still load the real predicate and mutants of it would survive
# untested. Without this the suite cannot be mutation-tested at all.
HOOK = Path(os.environ.get("POLICY_MUTATE_HOOK")
            or ROOT / ".claude" / "hooks" / "policy-mutate.py")

SESSION_A = "11111111-aaaa-4aaa-8aaa-111111111111"
SESSION_B = "22222222-bbbb-4bbb-8bbb-222222222222"


class ConsumeCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="consume-test-"))
        (self.root / ".agent-log").mkdir()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def norm(self, rel):
        return os.path.normcase(os.path.realpath(os.path.join(self.root, rel)))

    def grant_file(self, session=None):
        name = ("policy-unlock-%s.json" % session) if session else "policy-unlock.json"
        return self.root / ".agent-log" / name

    def write_grant(self, rel="CLAUDE.md", session=None, used=False, age=0):
        f = self.grant_file(session)
        f.write_text(json.dumps({"path": rel, "norm": self.norm(rel),
                                 "epoch": time.time() - age, "used": used}),
                     encoding="utf-8")
        return f

    def attempt(self, rel="CLAUDE.md", session=SESSION_A):
        """Try to mutate `rel`. Returns True if the gate allowed it through."""
        r = subprocess.run(
            [sys.executable, str(HOOK)],
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


class ExpiredGrantSaysSo(ConsumeCase):
    """An expired grant is still refused, and the refusal now says
    EXPIRED instead of reading exactly like no grant at all."""

    def deny_text(self):
        r = subprocess.run(
            [sys.executable, str(HOOK)],
            input=json.dumps({"session_id": SESSION_A, "tool_name": "Edit",
                              "cwd": str(self.root),
                              "tool_input": {"file_path": str(self.root / "CLAUDE.md")}}),
            capture_output=True, text=True,
            env=dict(os.environ, HARNESS_ROOT=str(self.root)))
        self.assertEqual(r.returncode, 0, r.stderr)   # a crash is a fail-open
        self.assertIn('"permissionDecision": "deny"', r.stdout)
        return r.stdout

    def test_expired_grant_is_named(self):
        self.write_grant(session=SESSION_A, age=1800 + 600)
        self.assertIn("EXPIRED 10 min ago", self.deny_text())

    def test_no_grant_and_fresh_mismatch_get_no_clause(self):
        self.assertNotIn("EXPIRED", self.deny_text())
        self.write_grant(rel="other.md", session=SESSION_A)
        self.assertNotIn("EXPIRED", self.deny_text())

    def test_absurd_epoch_does_not_crash(self):
        # Both branches: a grant that covers the file (the spend arithmetic) and
        # one that does not (the note). 365 review F1/F2: an int too big for a
        # float, and non-numeric epochs that only the isinstance guard stops.
        # BOTH signs of that int: -10**400 is what the LOWER
        # half of each `-1e12 <` bound decides, and the only negative absurd
        # epoch here before it, -1e999, parses to float -inf and never raises.
        f = self.grant_file(SESSION_A)
        for rel in ("CLAUDE.md", "other.md"):
            for epoch in ("1e999", "-1e999", "NaN", "true", str(10 ** 400),
                          str(-10 ** 400),
                          '"1700000000"', "[]", "null", "{}"):
                with self.subTest(rel=rel, epoch=epoch[:12]):
                    f.write_text('{"path": "%s", "norm": %s, "epoch": %s, "used": false}'
                                 % (rel, json.dumps(self.norm(rel)), epoch), encoding="utf-8")
                    self.deny_text()


class TheGateStillOpens(ConsumeCase):
    """Lockout guards. Every one of these must stay green forever."""

    def test_a_session_keyed_grant_is_consumed(self):
        self.write_grant(session=SESSION_A)
        self.assertTrue(self.attempt(), "the operator's own grant was refused")

    # test_an_unkeyed_grant_is_still_honoured was deleted: unkeyed grants are refused.
    # Its premise ("the arming side still writes this name") was false:
    # policy-prompt.py keys every policy grant it arms, so the transition this
    # guarded was already complete. The unkeyed slot it pinned was a forger's
    # landing pad — a renamed file could occupy it, and it was read as a
    # fallback. Its narrower replacement, covering the arm that genuinely
    # prevents a lockout, is TheSidAbsentArmIsStillHonoured in
    # work/63-70-hook-fixes/tests/test_64_grant_forgery.py.

    def test_a_non_policy_path_needs_no_grant_at_all(self):
        self.assertTrue(self.attempt("projects/app/notes.md"))


class TheGateStillCloses(ConsumeCase):
    """The refusals. A gate that opens for everything is not a gate."""

    def test_with_no_grant_at_all(self):
        self.assertFalse(self.attempt())

    def test_a_spent_grant_is_refused(self):
        self.write_grant(session=SESSION_A, used=True)
        self.assertFalse(self.attempt())

    def test_an_expired_grant_is_refused(self):
        self.write_grant(session=SESSION_A, age=1801)
        self.assertFalse(self.attempt())

    def test_a_grant_for_a_different_path_is_refused(self):
        self.write_grant(rel="README.md", session=SESSION_A)
        self.assertFalse(self.attempt("CLAUDE.md"))


class ShellClauseScoping(ConsumeCase):
    """Earlier fixes, the policy-path half. The out-of-tree half lives in
    test_shell_scope.py; these cases need is_policy, so they belong here.

    The shared predicate used to harvest every path token in the whole command
    once any write verb appeared anywhere in it. This gate is DENY-tier -- it
    bites in every mode, bypass included -- so that defect refused ordinary
    reads and refused writing notes about the gates.
    """

    def shell(self, command):
        """Try `command` as Bash. Returns True if the gate allowed it."""
        r = subprocess.run(
            [sys.executable, str(HOOK)],
            input=json.dumps({
                "session_id": SESSION_A, "tool_name": "Bash",
                "cwd": str(self.root), "tool_input": {"command": command},
            }),
            capture_output=True, text=True,
            env=dict(os.environ, HARNESS_ROOT=str(self.root)))
        self.assertEqual(r.returncode, 0, r.stderr)
        return '"permissionDecision": "deny"' not in r.stdout

    def test_reading_a_policy_file_beside_an_unrelated_write_is_allowed(self):
        self.assertTrue(self.shell("cat CLAUDE.md && rm scratch.tmp"))
        self.assertTrue(self.shell("mkdir -p tmp/x && head -5 CLAUDE.md"))

    def test_a_note_about_the_gates_is_not_a_write_to_what_it_names(self):
        # The incident report naming the gate was blocked by
        # the gate it named.
        self.assertTrue(self.shell(
            "cat > work/n.md <<'EOF'\npolicy-mutate denies rm on CLAUDE.md\nEOF"))

    def test_a_commit_message_naming_a_policy_path_is_not_a_mutation(self):
        self.assertTrue(self.shell(
            "git commit -F - <<'EOF'\nremoved CLAUDE.md rules, rm of dead text\nEOF"))

    def test_the_real_mutations_are_all_still_denied(self):
        self.assertFalse(self.shell("sed -i 's/a/b/' CLAUDE.md"))
        self.assertFalse(self.shell("echo x > .claude/hooks/net-post.py"))
        self.assertFalse(self.shell("cp /tmp/x.py .claude/hooks/policy-prompt.py"))
        self.assertFalse(self.shell("rm .claude/hooks/git-guard.py"))
        self.assertFalse(self.shell("echo start && rm CLAUDE.md"))

    def test_a_policy_path_piped_into_xargs_is_denied(self):
        # Earlier fixes: the path is xargs' operand, supplied on stdin; a
        # path-qualified xargs is the same binary.
        self.assertFalse(self.shell("echo CLAUDE.md | xargs rm"))
        self.assertFalse(self.shell("echo CLAUDE.md | /usr/bin/xargs rm"))
        self.assertFalse(self.shell("echo CLAUDE.md | ./bin/xargs rm"))
        self.assertFalse(self.shell("echo CLAUDE.md | .\\bin\\xargs.exe rm"))

    def test_a_newline_inside_a_substitution_does_not_hide_the_redirect(self):
        # An earlier fix. Its round 2 closed the quoted-span half of this class and
        # recorded `$( ... )`/backticks as still open -- a real hole at DENY
        # tier, since this gate imports the predicate. Both spellings.
        self.assertFalse(self.shell(
            "cat <<'EOF' $(echo\nfoo) > CLAUDE.md\nrewritten contract\nEOF"))
        self.assertFalse(self.shell(
            "cat <<'EOF' `echo\nfoo` > CLAUDE.md\nrewritten contract\nEOF"))

    def test_a_policy_mutation_inside_an_interpreter_heredoc_is_denied(self):
        # This gate is DENY-tier, so when the
        # first cut of the 175 fix stripped every heredoc body unconditionally,
        # `bash <<EOF rm CLAUDE.md EOF` became an ungated route to a policy
        # path in every mode -- and log-escape shares the predicate, so the
        # crossing was neither blocked nor recorded.
        self.assertFalse(self.shell("bash <<EOF\nrm CLAUDE.md\nEOF"))
        self.assertFalse(self.shell("sudo bash <<EOF\nrm .claude/hooks/x.py\nEOF"))

    def test_a_redirect_on_the_introducer_line_is_not_swallowed(self):
        # The strip used to run AFTER the caller flattened
        # newlines, so a cut running from `<<DELIM` to the terminator also ate
        # whatever shared the introducer's own line. Here that is the redirect
        # overwriting the contract itself, on a DENY-tier gate.
        self.assertFalse(self.shell(
            "cat <<'EOF' > CLAUDE.md\nrewritten contract\nEOF"))
        self.assertFalse(self.shell(
            "cat <<'EOF' >> .claude/hooks/net-post.py\nappended\nEOF"))

    def test_a_redirect_behind_an_fd_duplication_is_not_swallowed(self):
        # The introducer-line walk used to
        # halt at the first token it could not read as a redirect, and `2>&1`
        # was such a token because the target class excluded `&`. So ONE extra
        # token reopened every crossing above. There is no walk any more: the
        # whole introducer line is kept, so `2>&1` is just more of it.
        self.assertFalse(self.shell(
            "cat <<'EOF' 2>&1 > CLAUDE.md\nrewritten contract\nEOF"))
        self.assertFalse(self.shell(
            "cat <<'EOF' 2>&1 >> .claude/hooks/net-post.py\nappended\nEOF"))

    def test_a_newline_inside_a_quoted_span_does_not_hide_the_redirect(self):
        # A round-2 review, finding F1, at the tier that bites in every mode.
        # The introducer-line walk had no quote state, so a newline sitting
        # INSIDE `'...'` ended the kept region early and the redirect that
        # followed the quote's close -- onto the contract itself -- was never
        # scanned. Two shapes of one root cause: an even backslash run before
        # the newline (round-1 parity regression) and a bare newline (open
        # since 213, disclosed in the docstring, closed by the same walk).
        self.assertFalse(self.shell(
            "cat <<'EOF' 'x\\\\\ny' > CLAUDE.md\nrewritten contract\nEOF"))
        self.assertFalse(self.shell(
            "cat <<'EOF' 'x\ny' > CLAUDE.md\nrewritten contract\nEOF"))

    def test_a_pipe_on_the_introducer_line_is_not_swallowed(self):
        # The body is piped into an interpreter and so
        # RUNS, but the `| bash` saying so also lived on the introducer line
        # and went out with the body -- leaving the INTERP prefix check
        # looking at a bare `cat`.
        self.assertFalse(self.shell(
            "cat <<'EOF' | bash\nrm CLAUDE.md\nEOF"))

    def test_bounding_the_cut_does_not_start_blocking_ordinary_heredocs(self):
        # A gate that denies everything passes every
        # deny test. The introducer-line tail is significant; the BODY is still
        # prose, and naming a policy path in prose is not writing to it (90).
        self.assertTrue(self.shell(
            "cat <<'EOF' > work/n.md\npolicy-mutate denies rm on CLAUDE.md\nEOF"))
        self.assertTrue(self.shell(
            "cat > work/n.md <<'EOF'\npolicy-mutate denies rm on CLAUDE.md\nEOF"))

    def test_a_markdown_blockquote_in_a_body_is_not_a_redirect(self):
        # Round 1 reconstructed the
        # introducer's line end from shell grammar because its callers had
        # already flattened the newlines away. That could not tell `> CLAUDE.md`
        # opening a body from `> CLAUDE.md` on the introducer, so writing a
        # markdown blockquote about the contract was denied at DENY tier -- in
        # a tree whose desk artifacts are markdown heredocs. The fix is to stop
        # flattening before the strip; these are the shapes it recovers.
        blockquote = "\n> CLAUDE.md is the contract\nEOF"
        self.assertTrue(self.shell("cat <<'EOF'" + blockquote))
        self.assertTrue(self.shell("cat > work/n.md <<'EOF'" + blockquote))
        # The incident shape from an earlier fix itself.
        self.assertTrue(self.shell("git commit -F - <<'EOF'" + blockquote))

    def test_an_interpreter_is_seen_across_the_prefix_line_seam(self):
        # An earlier fix round 4, review finding S1 -- and the safety-side test S2
        # said was missing, so the mutation that reintroduces the bug goes red.
        # The guard tests `prefix + " " + line`. Those two regions are NOT
        # adjacent in the command: prefix ends before `<<`, line begins after
        # the delimiter. Concatenated bare, `bash<<EOF-1` builds the word
        # `bash-1`, INTERP's trailing (?![\w-]) stops matching, and a body bash
        # really does execute is stripped unseen. The reviewer ran these
        # against a scratch victim and watched the file be deleted.
        # A sweep of all 24 interpreter words x 9 word-extending characters
        # found the bare form blind on every one of the 24, not on these three.
        for cmd in ("bash<<EOF-1\nrm CLAUDE.md\nEOF-1",
                    "bash<<'EOF'x\nrm CLAUDE.md\nEOFx",
                    "sh<<EOF-1\nrm CLAUDE.md\nEOF-1"):
            self.assertFalse(self.shell(cmd),
                             "an executed body was stripped: " + repr(cmd))

    def test_a_body_opening_with_an_interpreter_word_is_still_prose(self):
        # Renamed in round 5. It was called
        # test_the_seam_space_does_not_manufacture_an_interpreter, and the swing
        # 4 review showed that name claims something the case cannot test: its
        # `prefix` already ends in a space and its `line` is empty, so the join
        # changes nothing and the test stays green even with the space removed.
        # The property it DOES pin is worth keeping -- a body whose first word
        # is `sh` is prose, not an executed body -- so it keeps the case under
        # an honest name. The seam direction it used to claim is a real
        # over-block and is on an earlier fix, not pinned here.
        self.assertTrue(self.shell(
            "cat > work/n.md <<EOF\nsh mentions CLAUDE.md in prose\nEOF"))

    def test_the_elided_introducer_does_not_weld_two_tokens(self):
        # Round 4 review, F2, both directions. The output join elides `<<DELIM`
        # and used to abut the characters either side of it, welding a token
        # that exists neither in the command nor in the shell's parse.
        # Over-block: bash writes a file named `CLAUDE` here, and the welded
        # `CLAUDE.md` denied it at deny tier.
        self.assertTrue(self.shell("echo hi > CLAUDE<<'X'.md\nbody\nX"))

    def test_a_command_after_an_introducer_line_operator_is_still_seen(self):
        # An earlier fix round 3, review finding A1 -- the safety-side companion to
        # the permissive test below, whose absence let round 2 ship a hole.
        # `cat <<'EOF' && rm CLAUDE.md` really deletes the file; round 2's cut
        # discarded the successor along with the body and the gate saw `cat `.
        # The reviewer confirmed all four by running them against a scratch
        # victim file. Every one of these is open on master too.
        for op in ("&&", ";", "&", "||"):
            self.assertFalse(
                self.shell("cat <<'EOF' " + op + " rm CLAUDE.md\nbody\nEOF"),
                "a policy delete after `" + op + "` on the introducer line "
                "was invisible to a deny-tier gate")

    def test_the_rest_of_the_introducer_line_is_never_cut(self):
        # Round 1 and round 2 both walked
        # the introducer's line looking for redirect-shaped tokens and stopped
        # at the first token that was not one, so ONE unremarkable token hid a
        # real write. The reviewer confirmed all five really write. The fix is
        # to stop walking: the body starts at the line's end, so everything
        # before that newline is kept whatever shape it has.
        BS = chr(92)
        for label, cmd in (
                ("a plain argument", "tee <<'EOF' CLAUDE.md\nbody\nEOF"),
                ("an input redirect",
                 "cat <<'EOF' < /dev/null > CLAUDE.md\nbody\nEOF"),
                ("a line continuation",
                 "cat <<'EOF' " + BS + "\n> CLAUDE.md\nbody\nEOF"),
                ("a second introducer",
                 "cat <<'A' <<'B' > CLAUDE.md\nx\nA\ny\nB"),
                ("a delimiter named like the target",
                 "cat <<'CLAUDE' > CLAUDE.md\nx\nCLAUDE")):
            self.assertFalse(self.shell(cmd),
                             "the walk stopped early at " + label)

    def test_a_body_piped_to_a_non_interpreter_is_still_prose(self):
        # Round 1's review called this F2 and judged it not
        # free to fix, because net-post must keep catching `| curl -d @-` while
        # both copies stay byte-identical. Reading the line end costs nothing
        # here: the send VERB and its host live on the introducer's line, which
        # is kept, so net-post still sees the send while the prose body goes.
        for tool in ("wc -l", "tee work/n.md", "grep x"):
            self.assertTrue(
                self.shell("cat <<'EOF' | " + tool +
                           "\n> CLAUDE.md is the contract\nEOF"),
                "prose piped to `" + tool + "` was judged as a command")

    def test_an_operator_after_the_introducer_does_not_capture_the_body(self):
        # `&&`, `||`, `;` and `&` TERMINATE
        # the command, so the body is not the successor's stdin -- but round 1
        # treated all four as "the line runs on" and kept the whole body, so an
        # ordinary in-tree write whose prose mentioned a policy path was denied.
        # Only a bare pipe genuinely feeds the body onward.
        body = "\n> CLAUDE.md is the contract\nEOF"
        for tail in (" && git add work/n.md", " || true", " ; ls", " &"):
            self.assertTrue(
                self.shell("cat > work/n.md <<'EOF'" + tail + body),
                "denied an ordinary in-tree write ending in: " + tail)

    def test_trailing_shell_punctuation_does_not_defeat_a_basename_rule(self):
        # The discriminating case for the punctuation strip. is_policy's PREFIX
        # rules match `.claude/hooks/x.py)` regardless, so only the
        # CLAUDE.md/AGENTS.md/README.md family can tell the strip apart from
        # nothing: unstripped, the basename reads `claude.md)` and sails past a
        # deny-tier gate.
        self.assertFalse(self.shell("(rm CLAUDE.md)"))
        self.assertFalse(self.shell("rm CLAUDE.md&"))


class TheGrantBelongsToOneSession(ConsumeCase):
    """A grant one operator typed must not be spendable by another."""

    def test_another_sessions_keyed_grant_is_not_consumed(self):
        self.write_grant(session=SESSION_B)
        self.assertFalse(self.attempt(session=SESSION_A),
                         "session A spent a grant session B's operator typed")

    def test_the_keyed_grant_wins_over_a_stale_unkeyed_one(self):
        self.write_grant(session=SESSION_A)
        self.write_grant(session=None, used=True)   # a spent leftover
        self.assertTrue(self.attempt(), "a stale unkeyed grant shadowed the real one")

    def test_consumption_marks_the_file_it_actually_read(self):
        self.write_grant(session=SESSION_A)
        legacy = self.write_grant(session=None)
        self.assertTrue(self.attempt())
        keyed = json.loads(self.grant_file(SESSION_A).read_text(encoding="utf-8"))
        self.assertTrue(keyed["used"], "the keyed grant was read but not spent")
        self.assertFalse(json.loads(legacy.read_text(encoding="utf-8"))["used"],
                         "spending one grant must not silently spend another")


class TheGrantItselfIsSealed(ConsumeCase):
    """RED UNTIL FIXED -- an earlier fix, and the sharpest finding of the night.

    The gate's code is a protected path. The gate's *state* was not: the grant
    file matched no branch of is_policy(), and the file-tool gate allows any path
    under the tree root. So an agent could write itself a well-formed grant and
    then mutate the contract, the settings, or the hooks, with no human turn
    anywhere in the chain -- authorization forged by the party it authorizes.

    `write_grant` above is a working demonstration of exactly that, which is how
    this was missed: it was read as a fixture rather than as a proof.

    There is deliberately NO unlock for this. An unlock would be circular -- the
    grant that authorizes writing the grant is the grant. It is a never-item, in
    the style of the git operations that have no unlock either.
    """

    def deny_reason(self, payload):
        r = subprocess.run(
            [sys.executable, str(HOOK)], input=json.dumps(payload),
            capture_output=True, text=True,
            env=dict(os.environ, HARNESS_ROOT=str(self.root)))
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_a_file_tool_cannot_write_a_grant(self):
        for name in ("policy-unlock.json", "policy-unlock-%s.json" % SESSION_A,
                     "net-unlock.json", "env-unlock.json"):
            with self.subTest(name=name):
                out = self.deny_reason({
                    "session_id": SESSION_A, "tool_name": "Write",
                    "cwd": str(self.root),
                    "tool_input": {"file_path": str(self.root / ".agent-log" / name)}})
                self.assertIn('"permissionDecision": "deny"', out, name)

    def test_a_shell_redirect_cannot_write_a_grant(self):
        # The other half of the channel. Sealing only the file tool would leave
        # the identical effect reachable one tool over -- the failure this tree
        # has already recorded twice as "a gate keyed to a name is bypassed by
        # anything reaching the same effect".
        out = self.deny_reason({
            "session_id": SESSION_A, "tool_name": "Bash", "cwd": str(self.root),
            "tool_input": {"command": "echo x > .agent-log/policy-unlock.json"}})
        self.assertIn('"permissionDecision": "deny"', out)

    def test_a_held_grant_does_not_authorize_writing_a_grant(self):
        # The circularity, stated as a test: even a perfectly valid grant for the
        # grant file must not open it, or the seal is just another policy path.
        self.write_grant(rel=".agent-log/policy-unlock.json", session=SESSION_A)
        out = self.deny_reason({
            "session_id": SESSION_A, "tool_name": "Write", "cwd": str(self.root),
            "tool_input": {"file_path": str(self.root / ".agent-log/policy-unlock.json")}})
        self.assertIn('"permissionDecision": "deny"', out)

    def test_the_rest_of_the_log_directory_is_still_writable(self):
        # Lockout guard. The action log lives here too and agents append to it by
        # design -- an in-tree tool writes its own send lines, and §4 requires the agent to
        # narrate judgement calls. Sealing the directory would break that.
        out = self.deny_reason({
            "session_id": SESSION_A, "tool_name": "Write", "cwd": str(self.root),
            "tool_input": {"file_path": str(self.root / ".agent-log" / "2026-08-24.md")}})
        self.assertNotIn('"permissionDecision": "deny"', out,
                         "sealing the grants must not seal the audit log")


class ABrokenGrantIsNotAnAbsentOne(ConsumeCase):
    """RED UNTIL FIXED -- finding F3, class C2.

    Consumption reads the session-keyed grant and falls back to the shared
    unkeyed one, and `except Exception: continue` gives that fallback three
    different meanings: the keyed grant is ABSENT, it is CORRUPT, or it is
    UNREADABLE. Only the first justifies reaching for the shared slot.

    The other two are reachable without an adversary. The arming side opens the
    grant "w" and then dumps; a crash, a full disk or a killed process between
    truncate and dump leaves a zero-length or half-written file under the keyed
    name. The session then spends whatever sits in the shared slot -- which is
    an earlier fix's cross-session grant-spending, arriving through the very mechanism
    added to prevent it.

    Twenty lines above, the same function denies outright on unreadable hook
    input. Same class of failure; fail-closed there, fail-open here.

    So each test below plants a perfectly good unkeyed grant for the same path
    and then breaks the keyed one. Consuming it is the bug.
    """

    def setUp(self):
        super().setUp()
        self.write_grant(session=None)      # the shared slot, valid and unspent

    def break_keyed(self, text):
        self.grant_file(SESSION_A).write_text(text, encoding="utf-8")

    def test_a_corrupt_keyed_grant_does_not_reach_the_shared_slot(self):
        self.break_keyed('{"path": "CLAUDE.md", "epo')     # died mid-dump
        self.assertFalse(self.attempt(),
                         "a truncated grant fell through and spent the shared slot")

    def test_a_zero_length_keyed_grant_does_not_reach_the_shared_slot(self):
        self.break_keyed("")                # truncated by "w", never dumped
        self.assertFalse(self.attempt(),
                         "an empty grant fell through and spent the shared slot")

    def test_a_keyed_grant_that_is_not_an_object_is_refused(self):
        # Valid JSON, wrong shape: json.load succeeds, so nothing is caught and
        # u.get() raises out of the hook. A crashing PreToolUse hook is not a
        # denial -- the tool proceeds. Fail-open by traceback.
        self.break_keyed('["not", "a", "grant"]')
        self.assertFalse(self.attempt(), "a non-object grant was not refused")

    def test_an_unreadable_keyed_grant_is_refused(self):
        # The third collapsed state. A directory under the grant's name is the
        # portable way to make open() fail with something other than absence.
        self.grant_file(SESSION_A).mkdir()
        self.assertFalse(self.attempt(),
                         "an unreadable grant fell through and spent the shared slot")


class _IsPolicyRoot:
    """The throwaway root the two is_policy classes below share.

    Deliberately NOT a TestCase: mixed into each concrete class, so unittest
    collects each class's own tests once and every class gets its own root.
    """

    @classmethod
    def setUpClass(cls):
        # HARNESS_ROOT before import, or `NROOT` falls to the hardcoded default and
        # this class grades worktree code against MAIN-tree disk state -- which
        # also breaks the module docstring's "nothing here touches the real
        # tree". The prefix rule for skills/scripts/templates is existence-
        # gated, so the root must contain a real file to test it against.
        import importlib.util
        cls.root = Path(tempfile.mkdtemp(prefix="is-policy-test-"))
        # addClassCleanup, not tearDownClass: unittest skips tearDownClass when
        # setUpClass raises, and exec_module below is the line most likely to
        # raise (a syntax error in the very hook under repair lands there).
        cls.addClassCleanup(shutil.rmtree, cls.root, ignore_errors=True)
        # The shape rules run at every checkout root, so the
        # existence-gated family needs a real file at the tree root, under a
        # NON-root `skills/`, and inside a worktree checkout (root-level and
        # nested) -- one file per shape the two items name. The last three are
        # the OVER-gating guard: real files whose paths
        # merely CONTAIN a component spelled `Scripts`/`templates`/`scripts`,
        # which is what the existence gate would otherwise wave through, since
        # `os.path.exists` folds case on Windows.
        for rel in ("scripts/prepush_check.py",
                    ".claude/skills/cite-check/cite_check.py",
                    "worktrees/lane-x/scripts/prepush_check.py",
                    "projects/app/worktrees/drive-a/scripts/run_tests.py",
                    "projects/p/.venv/Scripts/activate",
                    "projects/p/.venv/Lib/site-packages/x/templates/t.md",
                    ".agent-log/delegate/d1/work/scripts/run.py"):
            f = cls.root.joinpath(*rel.split("/"))
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("", encoding="utf-8")
        # RESTORE, never pop: popping deletes a pre-existing HARNESS_ROOT instead of
        # putting it back. scripts/prepush_check.py does the same save/restore
        # around the identical exec_module.
        prev = os.environ.get("HARNESS_ROOT")
        os.environ["HARNESS_ROOT"] = str(cls.root)
        try:
            spec = importlib.util.spec_from_file_location("policymutate", HOOK)
            cls.mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cls.mod)
        finally:
            if prev is None:
                os.environ.pop("HARNESS_ROOT", None)
            else:
                os.environ["HARNESS_ROOT"] = prev

    def policy(self, rel):
        # NROOT is already normcase'd; `rel` deliberately is not.
        return self.mod.is_policy(self.mod.NROOT + os.sep + rel.replace("/", os.sep))


class TheMatchIsCaseCorrectOffWindows(_IsPolicyRoot, unittest.TestCase):
    """`is_policy` compared a basename against lowercase literals.

    The comparison only worked because `os.path.normcase` had already folded
    the path -- and normcase folds case on Windows ONLY; on POSIX it is the
    identity function. So on a Linux host `CLAUDE.md` arrived as `CLAUDE.md`,
    matched nothing, and the tree's most protected file was ungated.

    This runs on Windows and still pins the POSIX behaviour, because the
    defect is reachable without a POSIX host: feed `is_policy` a path whose
    ROOT half is folded (so the containment check passes for the right
    reason) and whose FILENAME half is not. That is exactly the shape POSIX
    produces, and it is the shape that used to return False.
    """

    def test_the_module_really_took_this_classs_root(self):
        """Pins the fixture itself, which nothing else in this class can.

        Without it, deleting the HARNESS_ROOT line leaves the suite green: NROOT
        falls back to the hardcoded main tree, which genuinely contains a
        `scripts/prepush_check.py`, so every assertion below still passes --
        against the wrong tree. That is precisely the state this fixture was
        added to escape, and it could regress into it silently.
        """
        self.assertEqual(os.path.normcase(os.path.realpath(str(self.root))),
                         self.mod.NROOT,
                         "the hook resolved a different root than this class built")

    def test_uppercase_policy_filenames_are_gated(self):
        for rel in ("CLAUDE.md", "AGENTS.md", "README.md",
                    "projects/app/CLAUDE.md", "codex/AGENTS.md",
                    "AGENTS.override.md", "projects/x/AGENTS.override.md"):
            with self.subTest(rel=rel):
                self.assertTrue(self.policy(rel),
                                "%s went ungated with its real-world casing" % rel)

    def test_the_lowercase_spellings_still_match(self):
        # Guards the repair itself: .lower() must widen the match, not move it.
        for rel in ("claude.md", "agents.md", "readme.md"):
            with self.subTest(rel=rel):
                self.assertTrue(self.policy(rel))

    def test_it_did_not_become_a_blanket_match(self):
        # README is root-only, and folding case must not gate ordinary files.
        # The last four are the anchoring guard: the basename rule is exact
        # membership, and a suffix, prefix or substring match would over-gate an
        # ordinary file and deny a legitimate edit with a policy-path message.
        # BOTH directions are needed -- a suffix-only guard leaves a prefix
        # widening green, and `CLAUDE.md.orig` is what a merge conflict beside a
        # policy edit actually leaves on disk.
        for rel in ("docs/README.md", "Notes.md", "projects/app/README.md",
                    "notes-claude.md", "myagents.md",
                    "CLAUDE.md.bak", "README.md.orig"):
            with self.subTest(rel=rel):
                self.assertFalse(self.policy(rel),
                                 "%s is not a policy path" % rel)

    def test_the_prefix_rules_fold_case_too(self):
        """Fold `rel` wholesale.

        Until then only three basenames folded and this test pinned the
        OPPOSITE -- `.CLAUDE/hooks/x` had to return False -- on the ground that
        a POSIX tree may hold a distinct `Scripts/`. The ruling accepts that
        loss because the bypass is live in exactly the checkout a gate must
        protect: Claude Code on Linux against a bind mount of a case-insensitive
        host volume (or macOS on APFS), where normcase folds nothing and
        `.CLAUDE/hooks/policy-mutate.py` IS the real file. On a case-sensitive
        tree the other spelling is a different file that nothing loads, so
        over-gating it costs one refused edit of a file that should not exist.

        `SCRIPTS/prepush_check.py` still rides on os.path.exists: True here
        because Windows resolves it, and on a case-sensitive host it is False
        for the right reason (no such file), which is the one place the old
        `Scripts/` distinction genuinely survives.
        """
        self.assertTrue(self.policy("scripts/prepush_check.py"))
        # Existence-gated, so True only where the filesystem folds. Whether it
        # folds is measured on this class's own root, not read off the platform:
        # macOS's APFS folds by default too (board 6177).
        folds = (self.root / "SCRIPTS" / "prepush_check.py").exists()
        self.assertEqual(self.policy("SCRIPTS/prepush_check.py"), folds)
        if sys.platform == "win32":
            self.assertTrue(folds, "Windows folds case; the probe itself is broken")
        for rel in (".CLAUDE/hooks/policy-mutate.py",
                    ".Claude/settings.json", ".GIT/config",
                    ".CLAUDE/keybindings.json", ".Claude/agents/x.md",
                    ".git/HOOKS/pre-push"):
            with self.subTest(rel=rel):
                self.assertTrue(self.policy(rel),
                                "%s slipped the prefix rule on casing" % rel)

    def test_the_prefix_rules_are_untouched(self):
        self.assertTrue(self.policy(".claude/hooks/policy-mutate.py"))
        self.assertTrue(self.policy(".claude/agents/senior-engineer.md"))
        self.assertTrue(self.policy(".claude/settings.json"))
        self.assertFalse(self.policy(".claude/settings/nested.json"))
        self.assertTrue(self.policy(".codex/config.toml"))
        self.assertTrue(self.policy("worktrees/lane-1/.codex/hooks.json"))
        self.assertFalse(self.policy("projects/x/.codex/config.toml"))

    def test_the_root_prefix_compare_folds_too(self):
        """An earlier fix folded every rule BELOW the root; the compare that
        decides whether the path is under the root at all kept comparing
        normcase'd strings -- the identity on POSIX. So on the same
        case-insensitive mount that fix was written for, a differently-cased ROOT
        prefix named the real file and returned False before one rule ran, and
        that folding never got the chance to matter.

        Reproduced 2026-09-08 with normcase patched to the identity: both
        `<ROOT.upper()>/.claude/hooks/x.py` and `<ROOT.upper()>/CLAUDE.md`
        came back False. On Windows the same shape is reachable without the
        patch, because NROOT arrives already folded.

        HOST DEPENDENCE, declared: the vectors below are
        split by whether they touch disk. The rules above the tail walk decide
        on the string alone, so they hold on every host. The
        skills/scripts/templates family is existence-gated on the UNFOLDED path,
        so `<ROOT.upper()>/scripts/prepush_check.py` is True here only because
        Windows' `os.path.exists` folds; on a case-sensitive host it is False
        because no such file exists, not because of the ROOT casing. Both directions are pinned,
        so this class stays green on either host.
        """
        up = self.mod.NROOT.upper()
        for rel in ("CLAUDE.md", "AGENTS.md", ".claude/hooks/policy-mutate.py",
                    ".claude/agents/x.md", ".claude/settings.json",
                    ".git/config"):
            with self.subTest(rel=rel):
                self.assertTrue(
                    self.mod.is_policy(up + os.sep + rel.replace("/", os.sep)),
                    "%s escaped on the casing of the ROOT prefix" % rel)
        from unittest import mock
        disk = up + os.sep + os.path.join("scripts", "prepush_check.py")
        self.assertEqual(self.mod.is_policy(disk), os.path.exists(disk),
                         "the existence-gated family must follow this host's "
                         "own exists(), which is the only thing deciding it")
        with mock.patch.object(  # the case-sensitive host, simulated
                self.mod.os.path, "exists",
                lambda p: p in (str(self.root / "scripts" / "prepush_check.py"),)):
            self.assertFalse(self.mod.is_policy(disk),
                             "existence-gated on a case-sensitive host: the "
                             "uppercase root names no file (no such file, not ROOT casing)")
            self.assertTrue(self.mod.is_policy(up + os.sep + "CLAUDE.md"),
                            "the string-only rules do not depend on the host")

    def test_folding_the_root_did_not_widen_it_to_other_trees(self):
        # The guard on the repair. Folding must widen the compare to spellings
        # of THIS root and nothing else -- in particular a sibling directory
        # whose name merely STARTS with the root's has to stay outside, which
        # is what the `+ S` in the prefix test buys and what a bare startswith
        # would lose.
        for other in (str(self.root) + "-elsewhere", str(self.root) + "2"):
            with self.subTest(other=other):
                self.assertFalse(self.mod.is_policy(
                    os.path.normcase(other + os.sep + "CLAUDE.md")),
                    "%s is a different tree" % other)

    def test_the_log_directory_compare_folds_too(self):
        """215 in the sibling predicate, where the stakes are worse.

        `is_grant` decides the seal by comparing the file's directory against
        `<root>/.agent-log` -- the same two unfolded strings. A grant the seal
        misses on casing is one `open()` the consumer finds on the same
        case-insensitive mount, which re-opens an earlier fix by spelling alone.
        """
        d = self.mod.NROOT + os.sep + ".AGENT-LOG" + os.sep
        self.assertTrue(self.mod.is_grant(d + "policy-unlock.json"))
        self.assertFalse(self.mod.is_grant(d + "2026-09-08.md"))
        self.assertFalse(self.mod.is_grant(
            self.mod.NROOT + os.sep + "docs" + os.sep + "policy-unlock.json"),
            "the seal is the log directory, not the filename alone")


class TheShapeRulesAreDepthIndependent(_IsPolicyRoot, unittest.TestCase):
    """Earlier fixes -- one defect, seen from two sides.

    `is_policy` matched its prefixes against the path relative to the MAIN
    root, so the identical file was ungated one directory down. Only the
    `CLAUDE.md`/`AGENTS.md` basename rule was depth-independent.

    399, measured against the live hook 2026-09-08: the skills/scripts/
    templates family was a ROOT-relative prefix, and this tree has never had a
    root `skills/` or `templates/` -- the real skills are at `.claude/skills/`.
    A Write to `.claude/skills/cite-check/cite_check.py` passed silently while
    `.claude/hooks/net-post.py`, `scripts/run_tests.py` and `CLAUDE.md` all
    denied. The contract has therefore named a protection that never once
    applied to a real file.

    Measured on a lane worktree: the operator armed an
    `auth-policy-batch` over 6 worktree paths; the grant reported 4 one-shots
    still unspent when it was replaced, yet all 6 files had been edited. Only
    the two `CLAUDE.md` entries spent -- the rest never needed a grant.
    """

    def test_a_worktree_copy_of_the_gate_is_gated(self):
        for rel in ("worktrees/lane-x/.claude/hooks/policy-mutate.py",
                    "worktrees/lane-x/.claude/agents/senior-engineer.md",
                    "worktrees/lane-x/.claude/settings.json",
                    "worktrees/lane-x/.claude/settings.local.json",
                    "worktrees/lane-x/.claude/keybindings.json",
                    "worktrees/lane-x/.git/config",
                    "worktrees/lane-x/.git/hooks/pre-push",
                    "worktrees/lane-x/scripts/prepush_check.py"):
            with self.subTest(rel=rel):
                self.assertTrue(self.policy(rel),
                                "%s mutates with no grant" % rel)

    def test_the_skills_directory_this_tree_actually_has_is_gated(self):
        # The whole of an earlier fix: `skills/` as a root-relative prefix matched
        # nothing at all, because the skills live under `.claude/`.
        self.assertTrue(self.policy(".claude/skills/cite-check/cite_check.py"),
                        "the skills family protected no real file")

    def test_a_nested_worktrees_directory_is_a_checkout_root_too(self):
        # The anchor is the SHAPE `worktrees/<n>/`, wherever it sits: this tree
        # carries checkouts at `worktrees/` and at `projects/app/worktrees/`,
        # and 391 is about both.
        for rel in ("projects/app/worktrees/drive-a/.claude/hooks/x.py",
                    "projects/app/worktrees/drive-a/scripts/run_tests.py"):
            with self.subTest(rel=rel):
                self.assertTrue(self.policy(rel),
                                "%s is a checkout copy of the gate" % rel)

    def test_a_directory_merely_spelled_scripts_is_not_a_checkout_root(self):
        """2026-09-09 review F1. The shapes run at checkout roots, not at every
        component-aligned tail.

        An unanchored walk gated every EXISTING file under any directory named
        `scripts`, `skills` or `templates` at any depth -- and `os.path.exists`
        folds case on Windows, so a virtualenv's `Scripts\\` bin directory
        satisfied the `scripts` clause. Measured over the on-disk tree that was
        111 files outside any checkout, 78 of them inside the venv of the
        a project's own runtime, each one denied at deny tier
        needing a typed one-shot. `git ls-files` cannot see one of them, which
        is why the first measurement of this widening read zero collateral.

        Every path here is a REAL file in the fixture, so the existence gate is
        not what makes these False.
        """
        for rel in ("projects/p/.venv/Scripts/activate",
                    "projects/p/.venv/Lib/site-packages/x/templates/t.md",
                    ".agent-log/delegate/d1/work/scripts/run.py"):
            with self.subTest(rel=rel):
                self.assertFalse(self.policy(rel),
                                 "%s is not policy: no checkout root above it "
                                 "(F1 over-gating)" % rel)

    def test_depth_did_not_become_a_blanket_match(self):
        # Widening the SHAPES must not widen the tree. An ordinary file that
        # merely lives deep stays ungated; `readme.md` stays root-only, or
        # every README in the tree becomes a policy path; the settings rule
        # keeps its no-separator clause at every depth; and the existence gate
        # on the skills/scripts/templates family still decides.
        for rel in ("worktrees/lane-x/projects/app/app_server.py",
                    "worktrees/lane-x/docs/README.md",
                    "docs/README.md",
                    "worktrees/lane-x/.claude/settings/nested.json",
                    "projects/app/scripts-notes.md",
                    "worktrees/lane-x/scripts/does_not_exist.py"):
            with self.subTest(rel=rel):
                self.assertFalse(self.policy(rel), "%s is not a policy path" % rel)

    def test_the_tracked_pre_push_hook_sources_are_gated_at_checkout_roots(self):
        """The
        LIVE pre-push hook is `.githooks/pre-push` -- the main tree's
        core.hooksPath names it -- and `tools/git-hooks/pre-push-dispatcher`
        is the dispatcher's source. Both tracked, neither in is_policy, so both
        mutated ungranted. Shape rule, no existence gate, at every checkout
        root; near-misses and the `.claude/` anchor stay out."""
        for rel in (".githooks/pre-push",
                    "tools/git-hooks/pre-push-dispatcher",
                    "worktrees/zz/.githooks/pre-push",
                    "worktrees/zz/tools/git-hooks/pre-push-dispatcher"):
            with self.subTest(rel=rel):
                self.assertTrue(self.policy(rel),
                                "%s mutates with no grant" % rel)
        for rel in ("githooks/x",                    # no dot
                    "tools/other/x",                 # a sibling of git-hooks/
                    "tools/git-hooks-notes.md",      # a prefix, not the directory
                    "projects/p/.githooks/pre-push", # no checkout root above it
                    ".claude/.githooks/x",           # the .claude anchor is not a root
                    ".claude/tools/git-hooks/x"):
            with self.subTest(rel=rel):
                self.assertFalse(self.policy(rel), "%s is not a policy path" % rel)

    def test_roles_and_graphs_are_gated_at_checkout_roots(self):
        for rel in ("roles/super-doer.md", "graphs/lane.md",
                    "worktrees/zz/roles/new.md", "worktrees/zz/graphs/grill.md"):
            with self.subTest(rel=rel):
                self.assertTrue(self.policy(rel), "%s mutates with no grant" % rel)
        for rel in ("docs/roles/x.md", "projects/p/graphs/x.md",
                    ".claude/roles/x.md", "roles-notes.md"):
            with self.subTest(rel=rel):
                self.assertFalse(self.policy(rel), "%s is not a policy path" % rel)


class TheSpendNeverTruncatesTheGrant(ConsumeCase):
    """An earlier fix, second spend site.

    The old spend was `open(grant, "w")` + `json.dump` over the whole `entries`
    array: a crash mid-dump left a partial grant, and two racing hooks could
    each roll the other's spend back (up to 8 one-shots under auth-policy-batch).
    The spend is now claim-by-rename with a value compare, the mechanism of
    unlock_consume.py. The race itself is measured there (7,500
    rounds); these pin what this file can check cheaply: batch semantics survive
    the new write path, no temp name is left behind, and the truncating form
    never returns.
    """

    def write_batch(self, rels, session=SESSION_A):
        f = self.grant_file(session)
        f.write_text(json.dumps({
            "epoch": time.time(),
            "entries": [{"path": r, "norm": self.norm(r), "used": False}
                        for r in rels]}), encoding="utf-8")
        return f

    def test_one_entry_of_a_batch_is_spent_and_the_rest_stay_armed(self):
        f = self.write_batch(["CLAUDE.md", "README.md"])
        self.assertTrue(self.attempt("CLAUDE.md"))
        u = json.loads(f.read_text(encoding="utf-8"))   # valid JSON: not partial
        used = {e["path"]: e["used"] for e in u["entries"]}
        self.assertEqual(used, {"CLAUDE.md": True, "README.md": False})
        self.assertFalse(self.attempt("CLAUDE.md"), "spent entry re-spent")
        self.assertTrue(self.attempt("README.md"), "sibling one-shot lost")

    def test_the_swap_leaves_no_claim_or_spent_file_behind(self):
        f = self.write_batch(["CLAUDE.md"])
        self.assertTrue(self.attempt())
        leftovers = [p.name for p in f.parent.iterdir()
                     if ".claim." in p.name or ".spent." in p.name]
        self.assertEqual(leftovers, [])

    def test_a_crash_mid_dump_denies_and_leaves_the_grant_pristine(self):
        # The behavioural pin (non-author review F1): the old spend wrote the
        # live path directly, so a dump that dies half-way left `{"epo` on
        # disk. Run the hook in-process with json.dump patched to do exactly
        # that; the new spend dies in the .spent temp, the grant is unchanged,
        # and the mutation is refused. Fails on the truncating hook.
        import contextlib, io, runpy
        from unittest import mock
        f = self.write_batch(["CLAUDE.md"])
        before = f.read_bytes()
        payload = json.dumps({"session_id": SESSION_A, "tool_name": "Edit",
                              "cwd": str(self.root),
                              "tool_input": {"file_path": str(self.root / "CLAUDE.md")}})

        def torn(obj, fh, *a, **k):
            fh.write('{"epo')
            raise OSError("disk full mid-dump")

        out = io.StringIO()
        with mock.patch.object(json, "dump", torn), \
                mock.patch.object(sys, "stdin", io.StringIO(payload)), \
                mock.patch.dict(os.environ, {"HARNESS_ROOT": str(self.root)}), \
                contextlib.redirect_stdout(out), \
                self.assertRaises(SystemExit) as cm:
            runpy.run_path(str(HOOK), run_name="__main__")
        self.assertEqual(cm.exception.code, 0)
        self.assertIn('"permissionDecision": "deny"', out.getvalue())
        self.assertEqual(f.read_bytes(), before, "the live grant was torn")

    def test_the_truncating_write_is_gone(self):
        src = HOOK.read_text(encoding="utf-8")
        self.assertNotIn('open(grant, "w"', src,
                         "the live grant path is being truncated again")
        self.assertIn("os.replace(spent, grant)", src)


class TheSealCoversEveryGrantStem(ConsumeCase):
    """The seal is what keeps a grant file from being armed by
    the agent's own Write. It used to ENUMERATE stems, so a stem it did not
    name was an ordinary in-tree file -- and that failed in production twice:
    A later change hand-added `browse` as the third stem, and on 2026-09-08 a
    `use` verb shipped unsealed and a Write to `use-unlock-<sid>.json` passed. The
    stem is a SHAPE now, so the next verb arrives sealed and this class stops
    being a list somebody has to remember to extend."""

    def test_every_armed_stem_is_sealed(self):
        for name in ["policy-unlock-%s.json" % SESSION_A, "policy-unlock.json",
                     "net-unlock.json", "env-unlock.json",
                     "browse-unlock-%s.json" % SESSION_A,
                     "use-unlock-%s.json" % SESSION_A]:
            self.assertFalse(self.attempt(".agent-log/" + name),
                             "%s is writable by a tool call: the grant is self-armable" % name)

    def test_a_stem_nobody_has_hand_added_yet_is_sealed(self):
        # An earlier fix, stated as the test the enumerated list could not pass.
        # None of these are verbs this tree arms today; that is the point. A
        # seal that already denies them is a seal the next ADR does not have
        # to remember to edit, which is the step both of those changes missed.
        for name in ("desk-unlock.json", "lane-unlock-%s.json" % SESSION_A,
                     "spawn-unlock.json",
                     "lane-look-unlock-%s.json" % SESSION_A):
            with self.subTest(name=name):
                self.assertFalse(self.attempt(".agent-log/" + name),
                                 "%s is forgeable by an in-tree Write" % name)

    def test_an_unrelated_log_dir_file_is_not_sealed(self):
        # the seal is a filename SHAPE, not a directory lock: the action log
        # and ordinary notes stay writable, which the action-log section
        # requires -- an in-tree tool appends its send lines here and the agent narrates
        # judgement calls here. `notes-unlock.json` sat on this list while the
        # seal was a stem list; it IS a grant shape, so the shape rule seals
        # it, and the guard is carried by names that are not one.
        self.assertTrue(self.attempt(".agent-log/2026-09-05.md"))
        self.assertTrue(self.attempt(".agent-log/session-notes.json"))
        self.assertTrue(self.attempt(".agent-log/unlock.json"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
