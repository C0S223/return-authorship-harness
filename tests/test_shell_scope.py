"""Tests for shell-scope's write-target predicate, driven as a subprocess.

First tests this hook has ever had: until the HARNESS_ROOT seam landed,
the gate could only be exercised against the real tree, so it was never
exercised at all. Every case pins what the predicate DOES today — the parked
false-negative classes (uninspectable syntax, verb gaps) are design, not bugs,
and the variable-target test pins the pass side of that trade on purpose.

Nothing here touches the real tree: each run points the hook at a fresh
temporary root via HARNESS_ROOT. SHELL_SCOPE_HOOK overrides the hook path so the
suite can run against a pristine copy.
"""
import importlib.util
import inspect
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOK = Path(os.environ.get("SHELL_SCOPE_HOOK")
            or ROOT / ".claude" / "hooks" / "shell-scope.py")


class ShellScopeCase(unittest.TestCase):
    def setUp(self):
        # mkdtemp's default parent is %TEMP% itself, NOT the Temp\claude
        # scratchpad the hook exempts — so these roots are out-of-tree to an
        # unfixed hook, which is exactly what the red proof needs.
        self.root = Path(tempfile.mkdtemp(prefix="shellscope-root-"))
        self.outside = Path(tempfile.mkdtemp(prefix="shellscope-out-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.outside, ignore_errors=True)

    def run_hook(self, command, cwd="", log=False):
        argv = [sys.executable, str(HOOK)] + (["--log"] if log else [])
        r = subprocess.run(
            argv,
            input=json.dumps({"tool_name": "Bash", "cwd": cwd,
                              "tool_input": {"command": command}}),
            capture_output=True, text=True,
            env=dict(os.environ, HARNESS_ROOT=str(self.root)))
        self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def assertAsks(self, command, cwd=""):
        out = self.run_hook(command, cwd).stdout
        self.assertIn('"permissionDecision": "ask"', out, command)

    def assertAllows(self, command, cwd=""):
        out = self.run_hook(command, cwd).stdout
        self.assertEqual(out, "", "expected silent allow for: " + command)


class SuffixedScratchpad(ShellScopeCase):
    def test_a_suffixed_scratchpad_is_in_tree(self):
        import tempfile as _t
        self.assertAllows("echo x > %s" % os.path.join(
            _t.gettempdir(), "claude-0", "proj", "scratchpad", "f.txt"))

    def test_a_claude_lookalike_is_not(self):
        import tempfile as _t
        self.assertAsks("echo x > %s" % os.path.join(_t.gettempdir(), "claudex", "f.txt"))


class OutOfTreeWritesAsk(ShellScopeCase):
    def test_redirect_to_out_of_tree_absolute_path(self):
        self.assertAsks("echo hi > %s" % (self.outside / "f.txt"))

    def test_a_redirect_on_the_introducer_line_is_caught(self):
        # The redirect target sat AFTER the
        # introducer, so the cut from `<<DELIM` to the terminator took it with
        # the body and the gate saw a bare `cat`.
        self.assertAsks("cat <<'EOF' > %s\nbody text\nEOF"
                        % (self.outside / "f.txt"))

    def test_a_write_verb_abutting_the_introducer_is_still_a_verb(self):
        # Round 4 review, F2, the false-negative direction. The output join
        # elided `<<DELIM` and abutted what sat either side of it, so
        # `tee<<EOF-1 <path>` rebuilt the word `tee-1`; VERB_WR's (?![\w-])
        # then refused to see the verb and a real out-of-tree write went
        # unflagged AND unlogged, since log-escape.sh shares this predicate.
        # Open on master too -- it is the class this change-set exists to close.
        self.assertAsks("tee<<EOF-1 %s\nbody text\nEOF-1"
                        % (self.outside / "f.txt"))

    def test_an_introducer_line_redirect_into_the_tree_still_allows(self):
        # ...and the same shape aimed inside the tree must stay silent: the
        # tail is now read, so this is where over-blocking would show up.
        self.assertAllows("cat <<'EOF' > %s\nbody naming %s\nEOF"
                          % (self.root / "f.txt", self.outside / "g.txt"))

    def test_fd_redirect_is_caught(self):
        self.assertAsks("somecmd 2> %s" % (self.outside / "err.log"))

    def test_cp_family_flags_only_the_last_path(self):
        # copy OUT asks; copy IN (below, in the allow class) stays free
        self.assertAsks("cp %s %s" % (self.root / "a.txt",
                                      self.outside / "b.txt"))

    def test_mv_family_flags_both_paths(self):
        # mv destroys its source: an out-of-tree SOURCE alone must trip the
        # gate even when the destination is inside the root.
        self.assertAsks("mv %s %s" % (self.outside / "a.txt",
                                      self.root / "b.txt"))
        self.assertAsks("mv %s %s" % (self.root / "a.txt",
                                      self.outside / "b.txt"))

    def test_sed_in_place_is_caught(self):
        self.assertAsks("sed -i s/a/b/ %s" % (self.outside / "f.txt"))


class InTreeAndNonTargetsAllow(ShellScopeCase):
    """The HARNESS_ROOT seam itself: every case here writes INSIDE the env-set
    root. Red against the unfixed hook, which only knows the hardcoded tree."""

    def test_redirect_inside_root(self):
        self.assertAllows("echo hi > %s" % (self.root / "f.txt"))

    def test_cp_into_root_is_a_copy_in(self):
        self.assertAllows("cp %s %s" % (self.outside / "a.txt",
                                        self.root / "b.txt"))

    @unittest.skipUnless(sys.platform == "win32", "git-bash drive spelling")
    def test_gitbash_style_path_is_normalized(self):
        # /c/Users/... must resolve to the same root, not read as relative.
        drive = str(self.root)[0].lower()
        rest = str(self.root)[3:].replace("\\", "/")
        self.assertAllows("echo hi > /%s/%s/f.txt" % (drive, rest))

    def test_null_devices_are_ignored(self):
        self.assertAllows("somecmd > nul")
        self.assertAllows("somecmd > /dev/null")

    def test_variable_and_substitution_targets_pass(self):
        # The documented design: uninspectable syntax passes (false negatives
        # + audit over a false-positive tax). Pinned so a future "fix" that
        # starts guessing at variables shows up as a diff here.
        self.assertAllows("echo hi > $OUT")
        self.assertAllows("echo hi > $(mktemp)")


class ClauseScoping(ShellScopeCase):
    """Earlier fixes. The predicate used to ask whether a write verb appeared
    ANYWHERE in the command and then harvest EVERY path token in the WHOLE
    command, so one write verb in one clause made every path named anywhere a
    write target. policy-mutate imports this and is deny-tier, so the defect
    bit in every mode including bypass -- three logged false positives on
    legitimate traffic, and writing a note ABOUT the gates was blocked BY the
    gates.

    These cases are the out-of-tree half; the policy-path half of the same bug
    lives in a separate corpus outside this tree, which needs
    the real tree to exercise is_policy.
    """

    def test_a_write_in_one_clause_does_not_capture_another_clauses_path(self):
        self.assertAllows("cat %s && rm scratch.tmp"
                          % (self.outside / "f.txt"), cwd=str(self.root))

    def test_heredoc_body_is_data_not_command(self):
        # Prose naming a write verb and a path is a commit message, not a write.
        self.assertAllows("git commit -F - <<'EOF'\nrm %s today\nEOF"
                          % (self.outside / "f.txt"), cwd=str(self.root))

    def test_the_redirect_before_a_heredoc_still_counts(self):
        # Stripping the body must not strip the target: `cat > out <<EOF` names
        # a real write, and it sits BEFORE the introducer.
        self.assertAsks("cat > %s <<'EOF'\nsome prose\nEOF"
                        % (self.outside / "note.md"), cwd=str(self.root))

    def test_sed_i_past_an_and_does_not_reach_back(self):
        # SED_RE's [^|;]* never treated && as a clause break, so a plain read
        # denied whenever any -i flag appeared past the &&.
        self.assertAllows("sed -n 1,5p %s && grep -i x y.txt"
                          % (self.outside / "f.txt"), cwd=str(self.root))

    def test_clause_split_is_quote_aware(self):
        # The false-negative guard: a quote-blind split of a multi-expression
        # sed script strands -i in clause 1 and the real target in a verbless
        # clause 2, losing it. Fixing false positives must not manufacture
        # false negatives on a safety predicate.
        self.assertAsks("sed -i 's/a/b/;s/c/d/' %s"
                        % (self.outside / "f.txt"), cwd=str(self.root))

    def test_a_real_write_in_a_later_clause_is_still_caught(self):
        self.assertAsks("echo start && rm %s"
                        % (self.outside / "f.txt"), cwd=str(self.root))

    def test_a_write_inside_an_interpreter_heredoc_is_still_caught(self):
        # The first cut of
        # this fix stripped every heredoc body, which made `bash <<EOF rm
        # <out-of-tree> EOF` pass -- a real hole traded for a false positive.
        self.assertAsks("bash <<EOF\nrm %s\nEOF" % (self.outside / "f.txt"),
                        cwd=str(self.root))

    def test_a_wrapper_that_is_not_itself_an_interpreter_still_keeps_the_body(self):
        # `sudo bash` would prove nothing -- `bash` matches on its own. xargs is
        # the discriminating shape: it is not an interpreter, but it feeds the
        # body to one as ARGUMENTS, so `xargs rm <<EOF <path> EOF` really does
        # delete the path. Drop xargs from INTERP and the body is stripped and
        # the target lost.
        self.assertAsks("xargs rm <<EOF\n%s\nEOF" % (self.outside / "f.txt"),
                        cwd=str(self.root))

    def test_only_the_current_clause_decides_who_receives_the_body(self):
        # An interpreter earlier in the line says nothing about who receives
        # THIS body, so the guard must not over-keep either.
        self.assertAllows("cat s.sh | bash; cat > n.md <<EOF\nrm %s\nEOF"
                          % (self.outside / "f.txt"), cwd=str(self.root))

    def test_a_quoted_delimiter_with_an_unquoted_tail_is_one_word(self):
        # Heredoc fix (c). `<<'EOF'sh` is the single delimiter word `EOFsh`. HEREDOC_RE
        # used to stop at the closing quote, so it sought terminator `EOF` and
        # left `sh` at the head of the introducer's line -- INTERP matched that
        # `sh`, kept a prose body, and over-blocked at deny tier.
        self.assertAllows("cat > n.md <<'EOF'sh\nrm %s today\nEOFsh"
                          % (self.outside / "f.txt"), cwd=str(self.root))

    def test_a_doubled_backslash_ends_the_introducer_line(self):
        # Heredoc fix (c). A DOUBLE backslash is an escaped backslash and the line ENDS
        # there. The old one-character test read it as a continuation, walked
        # past the newline, and carried the body's prose into what is scanned.
        self.assertAllows("cat > n.md <<'EOF' \\\\\nrm %s today\nEOF"
                          % (self.outside / "f.txt"), cwd=str(self.root))

    def test_a_newline_inside_a_quoted_span_does_not_end_the_kept_region(self):
        # A round-2 review, finding F1. The round-1 parity test counted the
        # backslash run with NO quote state, so an EVEN run ending an OPEN
        # single-quoted span read as "line ends here" -- and the kept region
        # stopped at a newline that bash reads as ordinary quoted text, before
        # the quote closed and before the real redirect that follows it on the
        # same logical line. The redirect was then discarded from what the gate
        # scans. Both live importers inherit it: this gate and policy-mutate's
        # sealed deny (its CLAUDE.md variant is
        # test_policy_mutate.py::ShellClauseScoping::
        # test_a_newline_inside_a_quoted_span_does_not_hide_the_redirect).
        self.assertAsks("cat <<'EOF' 'x\\\\\ny' > %s\nbody\nEOF"
                        % (self.outside / "f.txt"), cwd=str(self.root))

    def test_a_bare_newline_inside_a_quoted_span_is_covered_too(self):
        # The earlier half of the same root cause, disclosed in the function's
        # docstring as long open: no backslash at all, just a newline
        # inside `'...'` on the introducer's line. One quote-aware walk closes
        # both, so this is pinned rather than left as prose.
        self.assertAsks("cat <<'EOF' 'x\ny' > %s\nbody\nEOF"
                        % (self.outside / "f.txt"), cwd=str(self.root))

    def test_a_newline_inside_a_command_substitution_does_not_end_it(self):
        # The walk
        # tracked quotes but not `$( ... )`, so a newline INSIDE a substitution
        # on the introducer's line ended the kept region and the redirect after
        # its close was cut -- the same blindness as F1, one syntax over. The
        # policy-path variant is
        # test_policy_mutate.py::ShellClauseScoping::
        # test_a_newline_inside_a_substitution_does_not_hide_the_redirect.
        self.assertAsks("cat <<'EOF' $(echo\nfoo) > %s\nbody\nEOF"
                        % (self.outside / "f.txt"), cwd=str(self.root))

    def test_a_newline_inside_backticks_does_not_end_it_either(self):
        # Backticks are the other spelling of the same construct; tracking one
        # and not the other would leave the hole open under a rename.
        self.assertAsks("cat <<'EOF' `echo\nfoo` > %s\nbody\nEOF"
                        % (self.outside / "f.txt"), cwd=str(self.root))

    # The punctuation strip is deliberately NOT tested here. On an out-of-tree
    # ABSOLUTE path a trailing `)` survives realpath and the target is still
    # out of tree, so the case passes with or without the strip -- it proves
    # nothing. It discriminates only against is_policy's basename rules, so it
    # lives in test_policy_mutate.py::ShellClauseScoping. Verified by mutation:
    # the mutant that drops the strip SURVIVES this file and is CAUGHT there.


class PowerShellHereStrings(ShellScopeCase):
    """This hook is PreToolUse Bash|PowerShell, but every case
    above is POSIX, and an earlier fix says a command proven only in bash is not
    proven for this host. PowerShell has no `<<` heredoc: `@'`...`'@` and
    `@"`...`"@` never match HEREDOC_RE, so a PS here-string body is scanned
    whole. That is the over-block direction and is left alone deliberately --
    cutting it would put a second here-string grammar in a gate whose only safe
    fallback is scan-everything.

    What the probe found was a MISS. A `<<WORD` sitting inside a PS here-string
    body never terminates, and the old rule for an unterminated heredoc cut
    everything after the introducer to the end of the command -- taking the real
    write that followed the `'@` with it, blind at deny tier.
    """

    def test_a_here_string_body_naming_an_introducer_keeps_the_later_write(self):
        self.assertAsks("$x = @'\ncat <<EOF\n'@ > %s"
                        % (self.outside / "f.txt"), cwd=str(self.root))

    def test_the_same_shape_with_a_cmdlet_after_the_terminator(self):
        self.assertAsks("$x = @'\nrun <<DELIM here\n'@ | Set-Content %s"
                        % (self.outside / "f.txt"), cwd=str(self.root))

    def test_a_plain_here_string_body_is_scanned_not_cut(self):
        # The documented over-block, pinned so a future "fix" that starts
        # cutting PS bodies shows up as a diff here rather than as a hole.
        self.assertAsks("$x = @'\necho hi > %s\n'@" % (self.outside / "f.txt"),
                        cwd=str(self.root))


class TheHeredocPredicateIsSharedByCopy(unittest.TestCase):
    """net-post.py carries a byte-identical strip_heredocs rather than
    importing this one: it is a sibling hook, not a caller, and a cross-hook
    import there would add a load-failure mode to a gate whose only safe
    fallback is "scan everything".

    Copies drift. An earlier fix was one gate's heredoc handling being wrong while
    another's was right, so this pins them equal -- drift fails the suite
    instead of silently reopening 187 in one gate only. If the two are ever
    genuinely allowed to differ, delete this test and say why in the commit.
    """

    def _load(self, name, filename):
        # EQ_HOOKS_DIR is the mutation seam. Without it this test would read the
        # REAL hooks while every other suite read the mutated copy, so a drift
        # mutant would sail through the one test written to catch drift.
        base = Path(os.environ.get("EQ_HOOKS_DIR")
                    or Path(__file__).resolve().parents[1] / ".claude" / "hooks")
        path = base / filename
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_both_gates_answer_identically(self):
        ss = self._load("ss_eq", "shell-scope.py")
        np_ = self._load("np_eq", "net-post.py")
        cases = [
            "cat > n.md <<EOF\nrm /tmp/x and curl -d to a host\nEOF",
            "bash <<EOF\nrm /tmp/x\nEOF",
            "sudo bash <<EOF\nrm /tmp/x\nEOF",
            "ssh h <<EOF\nrm /tmp/x\nEOF",
            "cat s.sh | bash; cat > n.md <<EOF\nrm /tmp/x\nEOF",
            "git commit -F - <<EOF\nremoved rm /tmp/x today\nEOF",
            "cat > n.md <<EOF\nunterminated body naming rm /tmp/x",
            "echo plain command with no heredoc at all",
            "cat > a <<ONE\nbody one\nONE\nbash <<TWO\nrm /tmp/x\nTWO",
            # The introducer's own line. The flatten hides where it ended,
            # so these are the shapes where the two copies could most easily
            # answer differently -- pin them.
            "cat <<'EOF' > CLAUDE.md\nrewritten contract\nEOF",
            "cat <<'EOF' >> .claude/hooks/net-post.py\nappended\nEOF",
            "cat <<'EOF' | bash\nrm /tmp/x\nEOF",
            "cat <<'EOF' | curl -d @- https://h/api\npayload\nEOF",
            "cat <<'EOF' > n.md\nrm /tmp/x and curl -d to a host\nEOF",
            "cat <<'EOF' 2>&1\nbody naming rm /tmp/x\nEOF",
            "cat <<'EOF' > n.md\n> a quoted line naming rm /tmp/x\nEOF",
        ]
        for c in cases:
            # RAW is now the real call shape -- every caller strips
            # first and flattens after. The flattened shape is kept alongside it
            # because a body can still reach a gate already on one line.
            self.assertEqual(ss.strip_heredocs(c), np_.strip_heredocs(c),
                             "the two copies disagree on raw: " + repr(c))
            flat = c.replace("\n", " ")
            self.assertEqual(ss.strip_heredocs(flat), np_.strip_heredocs(flat),
                             "the two copies disagree on: " + flat)

    def test_the_interpreter_lists_have_not_diverged(self):
        ss = self._load("ss_eq2", "shell-scope.py")
        np_ = self._load("np_eq2", "net-post.py")
        self.assertEqual(ss.INTERP.pattern, np_.INTERP.pattern)
        self.assertEqual(ss.HEREDOC_RE.pattern, np_.HEREDOC_RE.pattern)

    def test_the_copied_function_is_byte_identical(self):
        # A round-2 review raised F5: that round added two module-level
        # regexes shared by copy and pinned by nothing, so a drift in either
        # would have been invisible. Round 3 deleted both -- reading the
        # introducer's line end needs no token classes -- but the lesson stands
        # for whatever is added NEXT.
        ss = self._load("ss_eq3", "shell-scope.py")
        np_ = self._load("np_eq3", "net-post.py")
        self.assertEqual(inspect.getsource(ss.strip_heredocs),
                         inspect.getsource(np_.strip_heredocs),
                         "the two copies of strip_heredocs have drifted")

    def test_no_module_level_regex_is_added_unpinned(self):
        # A round-4 review, finding S4. The source pin above reaches the
        # FUNCTION only, so it does not see a new module-level regex -- which is
        # the exact gap F5 named. Demonstrated: adding `NEWRE` to one copy with
        # a different pattern survived all 86 checks.

        # Each module's regex names are frozen here. Adding one to either file
        # fails this test, which forces the author to say whether it is shared
        # by copy and, if so, to pin it two tests up. That is the point: the
        # cost is one test edit per new regex, paid deliberately.
        def names(mod):
            return sorted(n for n, v in vars(mod).items()
                          if n.isupper() and hasattr(v, "pattern"))
        ss = self._load("ss_eq4", "shell-scope.py")
        np_ = self._load("np_eq4", "net-post.py")
        self.assertEqual(
            names(ss),
            # XARGS_RE / XARGS_WR: shell-scope only; net-post has no
            # write-target attribution to share them with.
            ["HEREDOC_RE", "INTERP", "REDIR_RE", "SED_RE", "VERB_CP", "VERB_WR",
             "XARGS_RE", "XARGS_WR"],
            "shell-scope gained or lost a module-level regex -- if it is shared "
            "with net-post, pin it in test_the_interpreter_lists_have_not_diverged")
        self.assertEqual(
            names(np_),
            ["BARE_HOST", "BODY", "CLAUSE_SPLIT", "HEREDOC_RE", "INTERP", "SCP", "SCP_HOST", "SEND_TOOL",
             "URL_HOST"],
            "net-post gained or lost a module-level regex -- if it is shared "
            "with shell-scope, pin it in test_the_interpreter_lists_have_not_diverged")


class StdinAttribution(ShellScopeCase):
    """An earlier fix: a path printed by one
    clause and consumed by `xargs` across a pipe is that clause's write target.
    Red on the pre-214 hook: exactly the four must-catch cases."""

    def setUp(self):
        super().setUp()
        self.p = str(self.outside / "f.txt")

    def test_must_catch_echo_into_xargs_rm(self):
        self.assertAsks("echo %s | xargs rm" % self.p)

    def test_must_catch_echo_into_xargs_sed_in_place(self):
        self.assertAsks("echo %s | xargs -I{} sed -i s/a/b/ {}" % self.p)

    def test_must_catch_find_outside_into_xargs_rm(self):
        self.assertAsks("find %s -name '*.txt' | xargs rm" % self.outside)

    def test_must_catch_printf_into_xargs_truncate(self):
        self.assertAsks("printf '%%s\n' %s | xargs truncate -s0" % self.p)

    def test_must_catch_a_path_prefixed_xargs(self):
        # `^\s*xargs` missed a path-qualified binary.
        self.assertAsks("echo %s | /usr/bin/xargs rm" % self.p)

    def test_must_catch_a_relative_path_xargs(self):
        # An in-tree binary path does not ask on its own, so only
        # the stdin attribution can catch this one.
        self.assertAsks("echo %s | ./bin/xargs rm" % self.p)

    def test_must_catch_a_backslash_path_xargs(self):
        # 449 review F1: PowerShell spells the same relative binary with `\`.
        self.assertAsks("echo %s | .\\bin\\xargs.exe rm" % self.p)

    def test_a_quoted_pipe_into_a_prefixed_xargs_is_data(self):
        self.assertAllows("python -c \"print('%s | /usr/bin/xargs cat')\"" % self.p)

    def test_reads_piped_into_tee_stay_green(self):
        # The trade the tee fix bought: the read path is not a target.
        self.assertAllows("grep -rn %s . | tee out.txt" % self.p)
        self.assertAllows("cat %s | tee out.txt" % self.p)

    def test_path_in_an_interpreter_literal_stays_green(self):
        self.assertAllows("python -c \"print(open(r'%s').read())\"" % self.p)

    def test_a_quoted_pipe_into_xargs_is_data(self):
        # Rides the quote-aware clause split. Write verbs stay out of the
        # quotes: a bare verb inside quotes already asks.
        self.assertAllows("python -c \"print('%s | xargs cat')\"" % self.p)
        self.assertAllows("echo '%s | xargs' | cat" % self.p)
        self.assertAllows("echo '| xargs' %s | xargs cat" % self.p)

    def test_xargs_without_a_write_verb_is_a_read(self):
        self.assertAllows("echo %s | xargs cat" % self.p)
        self.assertAllows("echo %s | xargs wc -l" % self.p)

    def test_only_a_pipe_feeds_stdin(self):
        self.assertAllows("echo %s; xargs rm < /dev/null" % self.p)
        self.assertAllows("echo %s && xargs rm < /dev/null" % self.p)

    def test_truncate_is_a_write_verb_only_inside_the_xargs_clause(self):
        # Global, it would be one more bare English word matching inside a
        # quoted argument -- this commit message would ask.
        self.assertAllows('git commit -m "hooks: truncate fast path %s"' % self.p)


class LogMode(ShellScopeCase):
    """The --log contract with log-escape.sh: same stdin, --log argv, targets
    on stdout, always exit 0."""

    def test_log_mode_prints_the_target_and_exits_zero(self):
        cmd = "echo hi > %s" % (self.outside / "f.txt")
        r = self.run_hook(cmd, log=True)
        self.assertIn("shellwrite:", r.stdout)
        self.assertIn(str(self.outside / "f.txt"), r.stdout)

    def test_log_mode_is_silent_for_in_tree_writes(self):
        r = self.run_hook("echo hi > %s" % (self.root / "f.txt"), log=True)
        self.assertEqual(r.stdout, "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
