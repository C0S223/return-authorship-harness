"""Tests for log-escape.sh's tool_name fast path.

The regex is a hint, never the decider:
an empty match falls through to jq, and only a match anchored to the top-level
object may exit early.

Each case copies the hooks dir into a temp root and runs it there with
CLAUDE_PROJECT_DIR pointing at it -- nothing here writes the real action log.
LOG_ESCAPE_HOOK overrides the source file (red proof against a pristine copy).
"""
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HOOK = Path(os.environ.get("LOG_ESCAPE_HOOK")
            or REPO / ".claude" / "hooks" / "log-escape.sh")
PUSH = '"tool_input":{"command":"git push origin lane"}'


class LogEscapeCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="logescape-root-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        # The whole hooks dir, run with CLAUDE_PROJECT_DIR at the temp root the way
        # settings.json runs it: the hook's helpers (shell-scope.py, filetool-scope.py,
        # any file it grows) resolve under $ROOT, so a copy of the .sh alone tests a
        # hook with its fallbacks missing.
        shutil.copytree(HOOK.parent, self.root / ".claude" / "hooks")
        self.hook = self.root / ".claude" / "hooks" / HOOK.name
        self.env = dict(os.environ, CLAUDE_PROJECT_DIR=self.root.as_posix())

    def logged_bytes(self, raw):
        # read_text() would normalise a stray CR to LF and hide F4 entirely;
        # the whole point of that finding is a byte the text reader erases.
        r = subprocess.run(["bash", self.hook.as_posix()], input=raw,
                           capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return b"".join(p.read_bytes()
                        for p in (self.root / ".agent-log").glob("*.md"))

    def logged(self, raw):
        r = subprocess.run(["bash", self.hook.as_posix()], input=raw,
                           capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return "".join(p.read_text(encoding="utf-8")
                       for p in (self.root / ".agent-log").glob("*.md"))

    def test_without_jq_a_loggable_event_leaves_a_raw_line(self):
        # PATH holds only the tools the hook needs, jq left out (probe P1).
        bin_dir = self.root / "nojq-bin"
        bin_dir.mkdir()
        for tool in ("bash", "mkdir", "tr", "sed", "cat", "date", "python", "python3"):
            found = shutil.which(tool)
            if found:
                (bin_dir / tool).symlink_to(found)
        env = dict(self.env, PATH=str(bin_dir))
        # F25 (review SE-5): a real payload's command starts past byte 160.
        lead = ('"session_id":"%s","transcript_path":"/root/.claude/projects/%s.jsonl",'
                '"cwd":"/home/user/repo","hook_event_name":"PostToolUse",'
                % ("s" * 36, "p" * 120))
        for raw in ('{%s"tool_name":"Bash",%s}' % (lead, PUSH),
                    '{"tool_name":"Agent","tool_input":{"subagent_type":"x"}}',
                    '{"tool_name":"Read","tool_input":{"file_path":"a"}}'):
            r = subprocess.run([shutil.which("bash"), self.hook.as_posix()], input=raw,
                               capture_output=True, text=True, env=env)
            self.assertEqual(r.returncode, 0, r.stderr)
        text = "".join(p.read_text(encoding="utf-8")
                       for p in (self.root / ".agent-log").glob("*.md"))
        self.assertIn("UNPARSED (jq missing): Bash", text)
        self.assertIn("git push origin lane", text)
        self.assertIn("UNPARSED (jq missing): Agent", text)
        self.assertNotIn("Read", text)    # a class the hook never logs stays silent

    def test_the_line_carries_local_date_and_time(self):
        # The stamp moved from bash's printf clock to `date` (board 6177).
        before = time.strftime("%Y-%m-%d")
        text = self.logged('{"tool_name":"Bash",%s}' % PUSH)
        after = time.strftime("%Y-%m-%d")
        names = sorted(p.name for p in (self.root / ".agent-log").glob("*.md"))
        self.assertIn(names, (["%s.md" % before], ["%s.md" % after]))
        self.assertRegex(text, r"^- \d\d:\d\d:\d\d \[log-escape\] push: git push origin lane\n$")

    def test_a_failing_date_still_logs_the_line(self):
        # The ERR trap stays, so a failed timestamp must not end the hook.
        bin_dir = self.root / "baddate-bin"
        bin_dir.mkdir()
        (bin_dir / "date").write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        (bin_dir / "date").chmod(0o755)
        self.env["PATH"] = bin_dir.as_posix() + os.pathsep + self.env.get("PATH", "")
        self.logged('{"tool_name":"Bash",%s}' % PUSH)
        self.assertEqual((self.root / ".agent-log" / "undated.md").read_text(encoding="utf-8"),
                         "- ??:??:?? [log-escape] push: git push origin lane\n")

    def test_a_push_is_logged(self):
        self.assertIn("push: git push origin lane",
                      self.logged('{"tool_name":"Bash",%s}' % PUSH))

    def test_a_read_exits_with_no_line(self):
        self.assertEqual(self.logged(
            '{"tool_name":"Read","tool_input":{"file_path":"x"}}'), "")

    def test_a_nested_decoy_key_cannot_silence_a_push(self):
        # tool_input first, carrying its own tool_name: the unanchored
        # leftmost match read "Read" and exited before jq saw "Bash".
        self.assertIn("push:", self.logged(
            '{"tool_input":{"tool_name":"Read","command":"git push origin lane"},'
            '"tool_name":"Bash"}'))

    def test_a_key_the_regex_cannot_read_falls_through_to_jq(self):
        # `tool_name` is `tool_name` to jq and invisible to the regex;
        # an empty match used to exit 0 silently.
        self.assertIn("push:", self.logged(
            '{"tool\\u005fname":"Bash",%s}' % PUSH))

    # Every case below is a shape the substring matcher `*"git push"*`
    # could not see, measured on a real log: a `git -C` push and three PR sends
    # left no [log-escape] line at all, while three printf
    # appends that merely quoted the words were filed as pushes.
    def test_git_dash_c_push_is_logged(self):
        # CLAUDE.md s3 mandates `git -C <abs>` for main-tree ops, so this is
        # the form the tree pushes in -- and the one that logged nothing.
        self.assertIn("push:", self.logged(
            '{"tool_name":"Bash","tool_input":{"command":'
            '"git -C /home/user/repo push -u origin lane-1-fixture"}}'))

    def test_gh_pr_create_is_logged(self):
        # A PR send matched no class at all; gh is a network client by
        # definition, so every invocation is egress worth a line.
        self.assertIn("net:", self.logged(
            '{"tool_name":"Bash","tool_input":{"command":'
            '"gh pr create --title x --body y"}}'))

    def test_a_quoted_mention_is_not_filed_as_the_act(self):
        # Three real lines on 2026-09-14: log appends whose TEXT contained the
        # words were recorded as pushes. Discussing an escape is not one.
        out = self.logged(
            '{"tool_name":"Bash","tool_input":{"command":'
            '"printf -- \'- 18:40 ran git push -u origin lane\\n\' '
            '>> .agent-log/2026-09-14.md"}}')
        self.assertNotIn("push:", out)

    def test_a_hyphen_flanked_push_is_not_a_push(self):
        # `push` inside a branch name is not the verb. git-guard.py hit exactly
        # this (three false positives, all `...-push-...`); the anchors here are
        # the same shape, so this holds the line for the logger too.
        self.assertNotIn("push:", self.logged(
            '{"tool_name":"Bash","tool_input":{"command":'
            '"git switch lane-1-log-escape-push"}}'))

    # Review-03 (2026-09-17). Every case below was a REGRESSION introduced by
    # Measured: the old hook got each
    # one right, and the rewrite did not. A fix that breaks what it replaces
    # is not a fix, and none of these had a reader until now.
    def test_an_apostrophe_in_a_double_quoted_argument_cannot_hide_a_push(self):
        # F1, the serious one. The two blanking passes ran separately with
        # single quotes FIRST, so the apostrophe in `operator's` opened a span
        # that closed at the quote before `lane-x` and swallowed `git push`
        # whole -- the push ran and NO line was written at all. 3 of 4 real
        # push shapes were silent. A missed push is the one direction this
        # gate must never fail; over-reporting costs a reader a second.
        self.assertIn("push:", self.logged(
            '{"tool_name":"Bash","tool_input":{"command":'
            '"git commit -m \\"the operator\'s ruling\\" '
            '&& git push origin \'lane-x\'"}}'))

    def test_the_parity_dependence_itself_is_pinned(self):
        # The same shape with one EARLIER balanced single-quoted span logged
        # fine, which is why the hole hid: whether a push is audited depended
        # on how many apostrophes preceded it. Both spellings must log.
        self.assertIn("push:", self.logged(
            '{"tool_name":"Bash","tool_input":{"command":'
            '"echo \'starting\' && git commit -m \\"hub\'s fix\\" && git push"}}'))

    def test_no_quoting_shape_can_silence_a_real_push(self):
        # Review-04 F1. Blanking quoted spans with sed knows nothing of heredocs,
        # comments or escapes, so each shape below ran a push and logged NOTHING
        # under both the shipped hook and FIX.patch. Invariant: text matching
        # RE_PUSH unblanked always yields a line -- `push?:` when only the raw
        # text matches, so a mention stays distinguishable from the act.
        for cmd in (
            "git commit -F - <<'EOF'\nthe hub's fix\nEOF\ngit push -u origin 'claude/lane'",
            "cat > n.md <<EOF\nit's late\nEOF\ngit push origin 'lane-x'",
            "# don't forget\ngit push origin 'lane'",
            """git commit -m "say \\"it's\\" ok" && git push origin 'x'""",
            "echo it\\'s && git push origin 'x'",
        ):
            with self.subTest(cmd=cmd):
                self.setUp()
                self.assertRegex(self.logged(json.dumps(
                    {"tool_name": "Bash", "tool_input": {"command": cmd}})),
                    r"\] push\??: ")

    def test_no_quoting_shape_can_silence_a_send_or_an_install(self):
        # Review-05 F1: the raw-text fallback covered RE_PUSH only, so the same
        # apostrophe swallowed curl / npm / gh whole -- a regression against master.
        for cmd, marker in (
            ("# don't forget\ncurl -d @f http://localhost/'x'", "net"),
            ("cat > n.md <<EOF\nit's late\nEOF\nwget 'http://localhost/'", "net"),
            ("# don't\nnpm install 'left-pad'", "install"),
            ("# don't\ngh pr create --title 'x'", "net"),
        ):
            with self.subTest(cmd=cmd):
                self.setUp()
                self.assertRegex(self.logged(json.dumps(
                    {"tool_name": "Bash", "tool_input": {"command": cmd}})),
                    r"\] %s\??: " % marker)

    def test_the_question_mark_marker_is_pinned_per_shape(self):
        # Review-05 F2: `?` had no reader. Bare marker = matched outside quotes;
        # `?` = matched only inside what the blanker took for a quoted span.
        for cmd, want in (
            ("git push origin lane", "] push: "),
            ("echo 'git push'", "] push?: "),
            ("curl http://localhost/", "] net: "),
            ("echo 'curl is a tool'", "] net?: "),
        ):
            with self.subTest(cmd=cmd):
                self.setUp()
                self.assertIn(want, self.logged(json.dumps(
                    {"tool_name": "Bash", "tool_input": {"command": cmd}})))

    def test_a_line_continuation_between_git_and_push_still_logs(self):
        # F2's fix makes a newline a barrier so a heredoc body cannot join the
        # command. This pins that it did not buy that quiet with a blind spot:
        # continuations are joined first, so `git \<newline> push` still logs.
        self.assertIn("push:", self.logged(json.dumps(
            {"tool_name": "Bash",
             "tool_input": {"command": "git \\\n  push origin main"}})))

    def test_a_heredoc_body_naming_push_is_not_a_push(self):
        # F2. Newlines were folded to spaces, so a commit MESSAGE became
        # command text and the span reached across it. 12 of the 14 `push:`
        # lines on the live 2026-09-17 log were not pushes -- the "mostly
        # legitimate traffic" demotion trigger of docs/enforcement/CLAUDE.md.
        self.assertNotIn("push:", self.logged(json.dumps(
            {"tool_name": "Bash", "tool_input": {"command":
             "git add x.md && git commit -q -F - <<'EOF'\n"
             "handoff: present the push list\nEOF"}})))

    def test_gh_as_a_path_component_is_not_a_send(self):
        # F5. The flanking class admitted `/`, so reading a file under a
        # directory named gh was filed as network egress.
        self.assertNotIn("net:", self.logged(
            '{"tool_name":"Bash","tool_input":{"command":'
            '"cat /home/user/gh/notes.md"}}'))

    def test_gh_as_a_file_suffix_is_not_a_send(self):
        self.assertNotIn("net:", self.logged(
            '{"tool_name":"Bash","tool_input":{"command":"wc -l report.gh"}}'))

    def test_a_relative_path_gh_is_still_a_send(self):
        # The narrowing must not cost a real invocation: `/` still leads, so
        # ./gh and /usr/bin/gh keep matching. Pinned beside the two above so
        # both directions live in one fixture, per the review's prescription.
        self.assertIn("net:", self.logged(
            '{"tool_name":"Bash","tool_input":{"command":"./gh pr view 287"}}'))

    def test_a_carriage_return_in_a_peer_id_is_stripped(self):
        # F4. An earlier edit replaced the literal CR in both `tr -d` arguments of the
        # mailbox branch with a literal LF -- stripping a byte `$( )` has
        # already removed, and no longer stripping the one line 34 says is
        # stripped "everywhere". The review recorded this as host-dependent
        # and unfireable on Linux; it is fireable when the VALUE carries the
        # CR rather than jq's line ending, which is what this feeds.
        out = self.logged_bytes(
            '{"tool_name":"mcp__claude-code-remote__fire_trigger","tool_input":'
            '{"trigger_id":"trig_abc\\r","text":"x"}}')
        self.assertIn(b"peer-", out)
        self.assertNotIn(b"\r", out)

    # Claude_Code_Remote was live on managed 2026-09-17;
    # claude-code-remote was observed
    # 2026-10-04. Both spellings keep their trail.
    ROUTINE_PREFIXES = ("mcp__claude-code-remote__", "mcp__Claude_Code_Remote__")

    def peer_payload(self, prefix):
        return json.dumps({"tool_name": prefix + "fire_trigger",
                           "tool_input": {"trigger_id": "trig_abc", "text": "xyz"}})

    def test_both_routine_spellings_log_a_peer_line(self):
        for prefix in self.ROUTINE_PREFIXES:
            with self.subTest(prefix=prefix):
                shutil.rmtree(self.root / ".agent-log", ignore_errors=True)
                self.assertIn("peer-fire_trigger: trig_abc bytes=3",
                              self.logged(self.peer_payload(prefix)))

    def test_both_routine_spellings_take_the_python_fast_path(self):
        # The line above still lands if log-escape.py declines (jq runs
        # instead), so pin the .py answering for each spelling on its own.
        py = self.root / ".claude" / "hooks" / "log-escape.py"
        if not py.exists():
            self.skipTest("this hook has no fast path")
        for prefix in self.ROUTINE_PREFIXES:
            with self.subTest(prefix=prefix):
                r = subprocess.run([sys.executable, py.as_posix(), prefix + "fire_trigger"],
                                   input=self.peer_payload(prefix).encode(),
                                   capture_output=True, env=self.env)
                self.assertTrue(r.stdout.endswith(b"FAST=1"), r.stdout)
                self.assertIn(b"TID='trig_abc'", r.stdout)


class OnlyPython3OnPath(unittest.TestCase):
    """A host with `python3` and no `python` still gets every scope line.

    log-escape.sh's shell-scope and filetool-scope `--log` calls and
    log-escape-fast.sh's log-escape.py call ran a bare `python`. With only
    `python3` on PATH (macOS with a python.org or Homebrew install) each failed
    quietly and the out-of-tree write logged nothing. They now start through
    run-python.sh. PATH here holds only the tools the hooks use, `python3`
    among them; the "slow" cases delete log-escape-fast.sh from the copy so the
    two `--log` calls in log-escape.sh are what answer."""

    setUp = LogEscapeCase.setUp

    def run_hook(self, payload, fast=True):
        if not fast:
            (self.root / ".claude" / "hooks" / "log-escape-fast.sh").unlink()
        bin_dir = self.root / "py3only-bin"
        bin_dir.mkdir()
        for tool in ("bash", "mkdir", "tr", "sed", "cat", "date", "jq"):
            found = shutil.which(tool)
            if found:
                (bin_dir / tool).symlink_to(found)
        (bin_dir / "python3").symlink_to(sys.executable)
        self.assertIsNone(shutil.which("python", path=str(bin_dir)))
        r = subprocess.run(["bash", self.hook.as_posix()], input=json.dumps(payload),
                           capture_output=True, text=True, env=self.host_env(bin_dir))
        self.assertEqual(r.returncode, 0, r.stderr)
        return "".join(p.read_text(encoding="utf-8")
                       for p in (self.root / ".agent-log").glob("*.md"))

    def host_env(self, bin_dir):
        # A host, not a cloud boundary: under the marker filetool-scope --log
        # prints nothing by design, which would hide the defect.
        env = {k: v for k, v in self.env.items()
               if k not in ("CLAUDE_CODE_REMOTE", "HARNESS_BOUNDARY")}
        env["PATH"] = str(bin_dir)
        return env

    def outside(self):
        return Path(tempfile.gettempdir(), "zz-outside", "probe.txt").as_posix()

    def shell_write(self):
        return {"tool_name": "Bash", "tool_input": {"command": "echo x > %s" % self.outside()}}

    def file_write(self):
        return {"tool_name": "Edit", "tool_input": {
            "file_path": self.outside(), "old_string": "a", "new_string": "b"}}

    @unittest.skipIf(shutil.which("jq") is None, "jq not found")
    def test_a_shell_write_logs_through_the_fast_path(self):
        self.assertIn("shellwrite:", self.run_hook(self.shell_write()))

    @unittest.skipIf(shutil.which("jq") is None, "jq not found")
    def test_a_file_write_logs_through_the_fast_path(self):
        self.assertIn("filewrite:", self.run_hook(self.file_write()))

    @unittest.skipIf(shutil.which("jq") is None, "jq not found")
    def test_the_fast_path_itself_answers_with_python3_only(self):
        # The slow path gives the same line, so the line alone cannot show that
        # fast() still reaches log-escape.py; FAST=1 can.
        bin_dir = self.root / "py3only-bin"
        bin_dir.mkdir()
        for tool in ("bash", "tr", "sed", "jq"):
            (bin_dir / tool).symlink_to(shutil.which(tool))
        (bin_dir / "python3").symlink_to(sys.executable)
        fast = self.root / ".claude" / "hooks" / "log-escape-fast.sh"
        r = subprocess.run(
            ["bash", "-c", 'ROOT="$2"; TOOL=Edit; FAST=""; . "$1"; '
             'IFS= read -r -d "" INPUT; fast; echo "FAST=$FAST"',
             "x", fast.as_posix(), self.root.as_posix()],
            input=json.dumps(self.file_write()), capture_output=True, text=True,
            env=self.host_env(bin_dir))
        self.assertEqual(r.stdout.split()[-1:], ["FAST=1"], r.stdout + r.stderr)

    @unittest.skipIf(shutil.which("jq") is None, "jq not found")
    def test_a_shell_write_logs_through_shell_scope_log(self):
        self.assertIn("shellwrite:", self.run_hook(self.shell_write(), fast=False))

    @unittest.skipIf(shutil.which("jq") is None, "jq not found")
    def test_a_file_write_logs_through_filetool_scope_log(self):
        self.assertIn("filewrite:", self.run_hook(self.file_write(), fast=False))

    @unittest.skipIf(shutil.which("jq") is None, "jq not found")
    def test_no_python_at_all_still_never_blocks(self):
        # These hooks log only: no Python means no scope line, never a block.
        (self.root / "py3only-bin").mkdir()
        bin_dir = self.root / "py3only-bin"
        for tool in ("bash", "mkdir", "tr", "sed", "cat", "date", "jq"):
            (bin_dir / tool).symlink_to(shutil.which(tool))
        for payload in (self.shell_write(), self.file_write()):
            with self.subTest(tool=payload["tool_name"]):
                r = subprocess.run(["bash", self.hook.as_posix()], input=json.dumps(payload),
                                   capture_output=True, text=True, env=self.host_env(bin_dir))
                self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))

# Bash syntax later than 3.2, which is macOS's /bin/bash: the printf clock
# format silently disabled log-escape there (board 6177, item 1). Each entry is
# (pattern, a line it must catch). Full-line comments are not scanned.
_NAME = r"([A-Za-z_][A-Za-z0-9_]*|[0-9]+|[@*])"        # a parameter: name, positional, @ or *
_DECL = r"\b(declare|typeset|local|readonly)(\s+-[a-zA-Z]+)*\s+-[a-zA-Z]*"
LATER_THAN_BASH_3_2 = {
    # name: (pattern, [every spelling it must catch]). Each spelling is self-tested
    # and planted in a scratch hook (SE r1 F1: one example per row hid six misses).
    "printf clock format, 4.2": (r"%\([^)]*\)T",
        ["printf -v NOW '%(%T)T' -1", "printf '%(%F)T\\n' -1"]),
    "associative array, 4.0": (_DECL + "A",
        ["local -A seen", "declare -gA m", "typeset -r -A m", "readonly -A m"]),
    "nameref, 4.3": (_DECL + "n",
        ["local -n ref=x", "declare -rn ref=x"]),
    "declare -g, 4.2": (_DECL + "g", ["declare -g G=1", "typeset -gx G"]),
    "case-converting attribute -l/-u/-c, 4.0": (_DECL + "[luc]",
        ["declare -l K", "local -u K", "typeset -x -l K"]),
    "local -, 4.4": (r"\blocal\s+-(?=\s|$|;)", ["local -", "local - ; set -f"]),
    "mapfile, readarray or coproc, 4.0": (r"\b(mapfile|readarray|coproc)\b",
        ["mapfile -t L < f", "readarray L", "coproc cat"]),
    "case modification, 4.0": (r"\$\{" + _NAME + r"(\[[^]]*\])?(,,?|\^\^?)",
        ['x="${x,,}"', 'K="${1,,}"', 'K="${TOOL,,[A-Z]}"', 'K="${x^}"', 'K="${a[0]^^}"',
         'K="${@,,}"']),
    "parameter transformation, 4.4": (r"\$\{[^}]*@[QEPAaKkUuL]\}",
        ['echo "${x@Q}"', 'echo "${a[@]@Q}"']),
    "-v or -R test, 4.2/4.3": (r"(\[\[|\[|\btest)\s+(!\s+)?-[vR]\s",
        ["[[ -v X ]] || exit", "[ -v X ] || true", "test -v X || true", "[[ ! -v X ]]",
         "if [ -v X ]; then :; fi", "[[ -R ref ]]"]),
    "EPOCHSECONDS, EPOCHREALTIME, BASHPID, SRANDOM or BASH_ARGV0":
        (r"\b(EPOCHSECONDS|EPOCHREALTIME|BASHPID|SRANDOM|BASH_ARGV0)\b",
         ["NOW=$EPOCHSECONDS", "echo ${BASHPID}"]),
    "&>>, 4.0": (r"&>>", ["echo x &>> f", "echo x&>>f"]),
    "|&, 4.0": (r"\|&(?![]])", ["cmd |& tee f", "cmd|&tee f"]),
    "case fall-through, 4.0": (r";;?&(?![&\]])",
        ["a) x ;&", "a) x ;;&", "case $x in a) echo a;& b) echo b;; esac"]),
    # The first colon must start an offset: `${x:-...}`, `:=`, `:+` and `:?` are
    # 3.2 operators whose words may hold `:-` (SE r2 F3).
    "negative substring length, 4.2": (r"\$\{" + _NAME + r"(\[[^]]*\])?:(?![-=+?])[^}:]*:\s*-",
        ['echo "${x:0:-1}"', 'K="${CMD:0:-$n}"', 'K="${1:0:-1}"', 'K="${x: 1 : -2}"',
         'K="${a[0]:1:-1}"']),
    # Only `${name[-...` or an assignment `name[-...]=`: a bare `word[-...]` is a
    # glob or regex bracket expression in 3.2 (SE r2 F3).
    "negative array index, 4.3": (r"\$\{[#!]?[A-Za-z_][A-Za-z0-9_]*\[\s*-|"
                                  r"(^|[\s;&|(])[A-Za-z_][A-Za-z0-9_]*\[\s*-[^]]*\]\+?=",
        ['echo "${a[-1]}"', 'K="${a[-1]:-x}"', 'K="${a[ -1 ]}"', 'K="${a[-$n]}"',
         "a[-1]=x", 'K="${#a[-1]}"', "local a[-1]=x"]),
    "shopt option newer than 3.2": (
        r"\bshopt\s+(-[a-z]+\s+)*([A-Za-z0-9_]+\s+)*(autocd|checkjobs|dirspell|globstar|lastpipe|"
        r"direxpand|globasciiranges|inherit_errexit|localvar_inherit|localvar_unset|"
        r"assoc_expand_once|progcomp_alias|complete_fullquote|patsub_replacement|"
        r"varredir_close|noexpand_translation|globskipdots|compat3[2-9]|compat4[0-9])\b",
        ["shopt -s lastpipe", "shopt -s inherit_errexit", "shopt -s nullglob globstar"]),
    "wait -n/-f/-p, 4.3+": (r"\bwait\s+-[a-z]*[nfp]", ["wait -n", "wait -fn $p"]),
    "{varname} redirection, 4.1": (r"(?<![$\w])\{[A-Za-z_][A-Za-z0-9_]*\}(<>|>>?|<|>&|<&)",
        ["exec {fd}>/dev/null", "exec {fd}<f", "exec {fd}>&-"]),
    "read -N or -i, 4.0/4.1": (r"\bread\s+(-[a-zA-Z]+\s+)*-[a-zA-Z]*[Ni]",
        ["read -N 3 K", "read -r -N 1 K", "read -e -i x K"]),
    "brace sequence step or zero padding, 4.0":
        (r"\{-?[0-9a-zA-Z]+\.\.-?[0-9a-zA-Z]+\.\.|\{-?0[0-9]+\.\.",
         ["for i in {1..10..2}; do :; done", "echo {01..10}"]),
    # Only `case` opening the substitution: bash before 4.0 reads the first
    # pattern's `)` as the end of `$(`. A `case` later inside `$( )` is not seen.
    "case opening a command substitution": (r"\$\(\s*case\s",
        ['K="$(case $TOOL in Bash) echo b;; esac)"']),
}

# Bash 3.2 forms near the patterns above that must stay unflagged.
BASH_3_2_LOOKALIKES = [
    'x="${x:-a}"', 'x="${x: -1}"', 'x="${a[${#a[@]}-1]}"', "RE='[^|;&]'",
    "RE='(^|[^-[:alnum:]_])git'", 'local x=$(echo -n y)', "read -r -d '' INPUT",
    "grep -v x f", 'printf "%s" "$x"', 'echo "${#a[@]}" "${!x}"', "x+=(y)",
    '[ -n "$x" ]', "local LC_ALL=C", "echo {a,b}", "for i in {1..3}; do :; done",
    'echo "${x/#a/b}"', "shopt -s nullglob", "wait $p", 'echo "${!pre@}"',
    # SE r2 F3: valid 3.2 lines the round-2 table flagged.
    "${A:-${B:-x}}", "${x:-a:-b}", "'foo[-_]bar'", "a[-_]*", '"a[-z]"', '"^v[-0-9]"',
    "'s/$/;&/'", '"a?x=1;&y=2"', "shopt -q extglob && echo lastpipe",
]

# Rows matched against the line with quoted spans blanked: these operators mean
# nothing inside quotes, where `;&` or `|&` is sed or regex text (SE r2 F3).
UNQUOTED_ROWS = {"&>>, 4.0", "|&, 4.0", "case fall-through, 4.0"}


def _unquoted(line):
    return re.sub(r"'[^']*'|\"(\\.|[^\"\\])*\"", "''", line)


def row_matches(name, line):
    pat = LATER_THAN_BASH_3_2[name][0]
    return re.search(pat, _unquoted(line) if name in UNQUOTED_ROWS else line) is not None


def bash_3_2_scan(paths):
    """Hits of LATER_THAN_BASH_3_2 in `paths`, one string per (line, row)."""
    hits = []
    for h in paths:
        for n, line in enumerate(h.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            for name in LATER_THAN_BASH_3_2:
                if row_matches(name, line):
                    hits.append("%s:%d %s: %s" % (h.name, n, name, line.strip()[:80]))
    return hits


class HooksRunOnBash32(unittest.TestCase):
    """Every shell hook keeps to bash 3.2 syntax.

    No bash 3.2 runs here, so this is a scan, not an execution: it shows the
    hooks need nothing a 3.2 shell lacks, from the list above. A construct the
    list does not name is not caught."""

    def test_each_pattern_catches_every_listed_spelling(self):
        for name, (pat, examples) in LATER_THAN_BASH_3_2.items():
            for ex in examples:
                with self.subTest(name=name, example=ex):
                    self.assertTrue(row_matches(name, ex))

    def test_bash_3_2_lookalikes_are_not_flagged(self):
        for line in BASH_3_2_LOOKALIKES:
            for name in LATER_THAN_BASH_3_2:
                with self.subTest(line=line, name=name):
                    self.assertFalse(row_matches(name, line))

    def test_the_scan_reports_every_spelling_planted_in_a_hook(self):
        d = Path(tempfile.mkdtemp(prefix="bash32-scan-"))
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        planted = [ex for _, examples in LATER_THAN_BASH_3_2.values() for ex in examples]
        hook = d / "planted.sh"
        hook.write_text("#!/bin/bash\n# a comment: [ -v X ] is not code\n"
                        + "\n".join(planted) + "\n", encoding="utf-8")
        flagged = {int(h.split(":")[1].split()[0]) for h in bash_3_2_scan([hook])}
        missed = [ex for n, ex in enumerate(planted, 3) if n not in flagged]
        self.assertEqual(missed, [])
        self.assertNotIn(2, flagged)

    def test_no_hook_uses_syntax_later_than_bash_3_2(self):
        hooks = sorted((REPO / ".claude" / "hooks").rglob("*.sh"))
        self.assertIn("log-escape.sh", [h.name for h in hooks])
        self.assertEqual(bash_3_2_scan(hooks), [])


def scope_rules():
    """{name: pattern} for every module-level re.compile in shell-scope.py, plus
    NULLS, the redirect targets it skips."""
    src = (HOOK.parent / "shell-scope.py").read_text(encoding="utf-8")
    rules = {}
    for n in ast.parse(src).body:
        if not isinstance(n, ast.Assign) or not isinstance(n.targets[0], ast.Name):
            continue
        if isinstance(n.value, ast.Call) and getattr(n.value.func, "attr", "") == "compile":
            rules[n.targets[0].id] = n.value.args[0].value
        elif n.targets[0].id == "NULLS":
            rules["NULLS"] = ast.literal_eval(n.value)
    return rules


class FastPathTracksShellScope(unittest.TestCase):
    """log-escape-fast.sh's ss_quiet skips shell-scope.py --log when it
    can prove shell-scope prints nothing, and that proof is a hand copy of
    shell-scope's rules. A rule added there must fail here, not go quiet in the
    action log."""

    setUp = LogEscapeCase.setUp          # not a subclass: that would rerun its tests
    logged = LogEscapeCase.logged

    # The rules ss_quiet was written against, every one pinned: review finding showed the
    # "only narrows" argument for leaving some out was wrong for HEREDOC_RE and
    # XARGS_RE. A new rule, or a change to one: extend ss_quiet in
    # log-escape-fast.sh to cover it (or make it decline), then update this.
    PINNED = {
        "XARGS_RE": r'(?i)^\s*(?:\S*[\\/])?xargs(?![\w-])',
        "HEREDOC_RE": r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1([A-Za-z0-9_]*)",
        "INTERP": r'(?i)(?<![\w./\\-])(bash|sh|zsh|dash|ksh|python\d?(?:\.\d+)?|py|node|'
                  r'perl|ruby|php|pwsh|powershell|cmd|ssh|docker|kubectl|env|xargs|eval|'
                  r'sudo|nohup|timeout)(?![\w-])',
        "REDIR_RE": r'\d?>{1,2}\s*("([^"]*)"|\'([^\']*)\'|([^\s;|&]+))',
        "VERB_CP": r'(?i)(?<![\w./\\-])(cp|copy-item|robocopy)(?![\w-])',
        "VERB_WR": r'(?i)(?<![\w./\\-])(mv|move-item|rename-item|out-file|set-content|'
                   r'add-content|tee-object|new-item|mkdir|md|tee|rm|del|rmdir|'
                   r'remove-item)(?![\w-])',
        "XARGS_WR": r'(?i)(?<![\w./\-])truncate(?![\w-])',
        "SED_RE": r'(?i)\bsed\b[^|;]*\s-i',
        "NULLS": {"nul", "/dev/null"},
    }

    def test_shell_scope_has_no_rule_ss_quiet_was_not_written_against(self):
        rules = scope_rules()
        self.assertEqual(set(rules), set(self.PINNED))
        for name, want in self.PINNED.items():
            with self.subTest(rule=name):
                self.assertEqual(rules[name], want)

    def test_every_write_verb_shell_scope_names_still_logs(self):
        out = Path(tempfile.gettempdir(), "zz-outside", "probe.txt").as_posix()
        rules = scope_rules()
        verbs = [v for name in ("VERB_CP", "VERB_WR")
                 for v in re.search(r"\(([a-z|-]+)\)", rules[name]).group(1).split("|")]
        self.assertIn("mv", verbs)                  # the extraction itself works
        cmds = ["%s a.txt %s" % (v, out) for v in verbs] + [
            "echo %s | xargs truncate -s 0" % out,
            "sed -i s/a/b/ %s" % out,
            "echo x > %s" % out,
            "echo x 2>> %s" % out,
        ]
        for cmd in cmds:
            with self.subTest(cmd=cmd):
                shutil.rmtree(self.root / ".agent-log", ignore_errors=True)
                self.assertIn("shellwrite:", self.logged(json.dumps(
                    {"tool_name": "Bash", "tool_input": {"command": cmd}})))

    def shell_fast(self, stdout, **env):
        """rc of log-escape-fast.sh's shell_fast on a quiet Bash call: 0 = it
        answered, 1 = it declined to log-escape.py."""
        fast = self.root / ".claude" / "hooks" / "log-escape-fast.sh"
        if not fast.exists():
            self.skipTest("this hook has no fast path")
        raw = json.dumps({"tool_name": "Bash", "tool_input": {"command": "git status"},
                          "tool_response": {"stdout": stdout}}, ensure_ascii=False)
        r = subprocess.run(["bash", "-c", '. "$1"; IFS= read -r -d "" INPUT; shell_fast; echo "rc=$?"',
                            "x", fast.as_posix()], input=raw.encode("utf-8"),
                           capture_output=True, env=dict(self.env, **env))
        return r.stdout.decode().split()[-1]

    def test_each_cap_on_the_bash_reader_declines_on_its_own(self):
        # Review finding: past 12 KB or 400 backslashes the reader's cost
        # passes Python's. Each cap alone, and the size cap counted in bytes.
        self.assertEqual(self.shell_fast("ok"), "rc=0")
        self.assertEqual(self.shell_fast("a" * 13000), "rc=1")
        self.assertEqual(self.shell_fast("\n" * 450), "rc=1")
        self.assertEqual(self.shell_fast("—" * 5000, LANG="C.UTF-8", LC_ALL="C.UTF-8"), "rc=1")
        # Review finding: Shift_JIS reads UTF-8 bytes as other multibyte characters.
        self.assertEqual(self.shell_fast("—" * 5000, LC_ALL="ja_JP.SJIS"), "rc=1")

    def against_original(self, raw, **env):
        """[new, original]: (rc, stderr, logged bytes) of one payload through this
        hook and through a frozen copy of the hooks before the rewrite, each in its
        own root. LOG_ESCAPE_ORIGINAL names that copy; without it these cases skip."""
        original = Path(os.environ.get("LOG_ESCAPE_ORIGINAL") or REPO / "work" / "original-hooks")
        if not original.exists():
            self.skipTest("the frozen original is gone")
        other = Path(tempfile.mkdtemp(prefix="logescape-orig-"))
        self.addCleanup(shutil.rmtree, other, ignore_errors=True)
        shutil.copytree(original, other / ".claude" / "hooks")
        got = []
        for root in (self.root, other):
            shutil.rmtree(root / ".agent-log", ignore_errors=True)
            r = subprocess.run(["bash", (root / ".claude/hooks/log-escape.sh").as_posix()],
                               input=raw.encode(), capture_output=True,
                               env=dict(self.env, CLAUDE_PROJECT_DIR=root.as_posix(), **env))
            mark = root.as_posix().encode()
            got.append((r.returncode, r.stderr.replace(mark, b"R"),
                        b"".join(p.read_bytes()[11:].replace(mark, b"R")
                                 for p in (root / ".agent-log").glob("*.md"))))
        return got

    def test_a_cr_inside_a_filetool_line_logs_as_the_original_does(self):
        # Review finding: the original's `tr -d` holds a literal CR, which Git Bash
        # drops and Linux bash keeps, so only a side-by-side run is right on both.
        out = Path(tempfile.gettempdir(), "zz-outside").as_posix()
        for name in ("x\r\ny.txt", "tail\r", "plain.txt"):
            new, orig = self.against_original(json.dumps({"tool_name": "Edit", "tool_input": {
                "file_path": "%s/%s" % (out, name), "old_string": "a", "new_string": "b"}}))
            with self.subTest(name=name):
                self.assertTrue(new[2])
                self.assertEqual(new, orig)

    def test_an_uninstalled_locale_warns_no_more_than_the_original(self):
        # Review finding: undoing a function-local LC_ALL re-applied an uninstalled
        # locale and printed a second setlocale warning on every Bash call.
        new, orig = self.against_original(
            json.dumps({"tool_name": "Bash", "tool_input": {"command": "git status"}}),
            LC_ALL="xx_YY.UTF-8")
        self.assertEqual(new, orig)

    def test_a_large_tool_response_still_logs_inside_the_hook_timeout(self):
        # SE review F1: the bash JSON reader cost size x escapes, and a 75 KB
        # tool_response ran past settings.json's 10 s timeout, logging nothing.
        stdout = "\n".join('{"n": %d, "path": "a\\\\b"}' % i for i in range(3000))
        raw = json.dumps({"tool_name": "Bash",
                          "tool_input": {"command": "gh api repos/o/r/pulls"},
                          "tool_response": {"stdout": stdout, "stderr": ""}})
        r = subprocess.run(["bash", self.hook.as_posix()], input=raw, capture_output=True,
                           text=True, env=self.env, timeout=10)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("net: gh api repos/o/r/pulls", "".join(
            p.read_text(encoding="utf-8") for p in (self.root / ".agent-log").glob("*.md")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
