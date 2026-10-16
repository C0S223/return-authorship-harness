# shell-scope — PreToolUse Bash|PowerShell. Single job: catch shell commands
# that EXPLICITLY name an out-of-tree absolute path in write position
# (redirects, write cmdlets, copy/move targets, deletes, mkdir, sed -i) and
# route them to the platform's per-call permission prompt (permissionDecision
# "ask"). Uninspectable syntax (vars, substitution) PASSES by design — v2
# takes false negatives + audit over the earlier version's false-positive tax; the same predicate runs under --log from log-escape.sh so
# the residual leaves a trail. Born from the first dogfood test: a Bash
# redirect walked past filetool-scope unprompted and unlogged.
#
# write_targets() is the shared predicate — policy-mutate.py imports it.
# Predicates + tests are the harness-neutral spec; the hook envelope
# (stdin schema, permissionDecision JSON) is the Claude Code adapter.
import importlib.util
import json
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))

try:
    _spec = importlib.util.spec_from_file_location(
        "unlockconsume", os.path.join(HERE, "unlock_consume.py"))
    uc = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(uc)
except Exception:
    uc = None      # absent = never cloud-off, stays live

TREE = [
    os.environ.get("HARNESS_ROOT")            # test seam; unset in production
    or os.environ.get("CLAUDE_PROJECT_DIR")
    or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
]
ROOTS = [os.path.normcase(os.path.realpath(p)) for p in TREE]
# The scratchpad, the same exception filetool-scope carries: <tmp>/claude or
# <tmp>/claude-<suffix> (a cloud session's is /tmp/claude-<uid>/...).
TMP = os.path.normcase(os.path.realpath(tempfile.gettempdir()))
NULLS = {"nul", "/dev/null"}

# fd-prefixed redirects included: 2> file writes stderr to file
REDIR_RE = re.compile(r'\d?>{1,2}\s*("([^"]*)"|\'([^\']*)\'|([^\s;|&]+))')
# cp-family: only the LAST path is the write target (copy IN stays free)
VERB_CP = re.compile(r'(?i)(?<![\w./\\-])(cp|copy-item|robocopy)(?![\w-])')
# mv-family and write/delete verbs: every named path is a write target
# (mv destroys its source; contract treats move per effect)
# `rename-item` added so a rename ONTO a grant filename is at least SEEN by
# policy-mutate's seal. `move` and `ren` were proposed and REJECTED -- this file
# has no quote-stripping (_cands needs the contents of quoted spans, because a
# quoted path with a space is a real target), so a bare English word matches
# inside a quoted argument and turns a read-only invocation into a policy deny.
# A hyphenated cmdlet name is not English. Residuals (`cmd /c move`, bare `ren`,
# bare-newname renames) cost detection, not safety: dropping the unkeyed grant
# slot is what stops the forged grant being consumed, rename or no rename.
VERB_WR = re.compile(
    r'(?i)(?<![\w./\\-])(mv|move-item|rename-item|out-file|set-content|'
    r'add-content|tee-object|new-item|mkdir|md|tee|rm|del|rmdir|'
    r'remove-item)(?![\w-])')
# xargs takes its operands from stdin, so the paths clause N printed are
# the paths clause N+1 writes. Only xargs, only across a pipe, only when the
# xargs clause itself carries a write verb -- never the pipeline as a unit.
# `truncate` counts as
# a write verb in THAT clause only (must-catch case 4): global, it would be
# one more bare English word matching inside quoted arguments.
# Residual, named: `parallel` and `while read` consume stdin the same way and
# are not attributed; add one on a must-catch case, not before.
# A path-qualified xargs (`/usr/bin/xargs`, `.\bin\xargs.exe`) is the same binary.
XARGS_RE = re.compile(r'(?i)^\s*(?:\S*[\\/])?xargs(?![\w-])')
XARGS_WR = re.compile(r'(?i)(?<![\w./\-])truncate(?![\w-])')
SED_RE = re.compile(r'(?i)\bsed\b[^|;]*\s-i')

# A heredoc BODY handed to a NON-interpreter is data, not command.
# `git commit -F - <<'EOF' ... EOF` and `cat > f <<EOF ... EOF` both carry prose
# that names files and verbs, and the gates were reading that prose as write
# targets -- which is how writing a note ABOUT the gates came to be blocked BY
# the gates. The redirect target sits BEFORE the introducer, so
# cutting the body keeps it.
# The delimiter is a WORD, and bash builds it from quoted and unquoted
# parts alike -- `<<'EOF'sh` is the single delimiter `EOFsh`. Stopping at the
# closing quote sought the wrong terminator AND handed the leftover `sh` to the
# INTERP test, which kept prose bodies at deny tier. Group 3 is the unquoted
# tail; the delimiter is groups 2+3.
HEREDOC_RE = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1([A-Za-z0-9_]*)")

# ...but a body fed to an INTERPRETER is EXECUTED, so stripping it there
# converts a false positive into a real hole. The first cut of the 175 fix
# stripped unconditionally and did exactly that: `bash <<EOF rm CLAUDE.md EOF`
# passed policy-mutate, which is DENY-tier and bites in every mode, and
# log-escape shares this predicate so the crossing was neither blocked NOR
# recorded. Found the same day, while writing the same guard for net-post --
# where the question is unavoidable, because ssh's body IS the send.
#
# The default when in doubt is to KEEP the body: the noisy answer, never the
# blind one. `sudo`/`nohup`/`timeout`/`xargs` are here because they wrap an
# interpreter without being one.
INTERP = re.compile(
    r'(?i)(?<![\w./\\-])(bash|sh|zsh|dash|ksh|python\d?(?:\.\d+)?|py|node|'
    r'perl|ruby|php|pwsh|powershell|cmd|ssh|docker|kubectl|env|xargs|eval|'
    r'sudo|nohup|timeout)(?![\w-])')

# Trailing shell punctuation is not part of a filename. Note this only changes
# verdicts for is_policy's BASENAME rules -- its prefix rules match
# `.claude/hooks/x.py)` regardless -- so the shape it actually closes is
# `(rm CLAUDE.md)`, whose basename would otherwise read `claude.md)` and pass.
PUNCT = ";,&|)("


def norm(p, cwd):
    p = p.strip("'\"")
    if not p or p.lower() in NULLS or p.startswith(("$", "&", "-")):
        return None
    m = re.match(r'(?i)^/([a-z])/(.*)$', p)      # git-bash /c/foo -> c:/foo
    if m:
        p = m.group(1) + ":/" + m.group(2)
    # On POSIX `/tmp/x` is already absolute; joining it onto an empty
    # cwd returned None here and every out-of-tree write passed unasked.
    posix_abs = os.name == "posix" and p.startswith("/")
    if not (posix_abs or re.match(r'(?i)^[a-z]:[\\/]', p)):
        if not cwd:
            return None
        p = os.path.join(cwd, p)
    return os.path.normcase(os.path.realpath(p))


def in_tree(np):
    if np.startswith(TMP + os.sep):
        top = np[len(TMP) + 1:].split(os.sep, 1)[0]
        if top == "claude" or top.startswith("claude-"):
            return True
    return any(np == r or np.startswith(r + os.sep) for r in ROOTS)


def _cands(cmd):
    """Path-looking tokens: absolute, git-bash /c/ style, or relative with a
    separator or extension. Flags, vars, robocopy /E switches skipped."""
    toks = [a or b or c for a, b, c in
            re.findall(r'"([^"]+)"|\'([^\']+)\'|(\S+)', cmd)]
    out = []
    for t in toks:
        if t.startswith(("-", "$", "&")) or re.match(r'^/[A-Za-z]+$', t):
            continue
        if re.match(r'(?i)^[a-z]:[\\/]', t) or re.match(r'(?i)^/[a-z]/', t):
            out.append(t)
        elif ("/" in t or "\\" in t or "." in t) and t.lower() not in NULLS:
            out.append(t)
    return out


# A cut running from `<<DELIM` to the terminator also ate whatever shared
# the introducer's OWN line: `> CLAUDE.md` overwrote a policy path, `| bash`
# executed the body, `| curl -d @-` sent it, `&& rm CLAUDE.md` deleted one, and
# each of them then read as a bare `cat` with the evidence deleted.
#
# The body starts at the introducer's line END. That is the rule; it is
# approximate in TWO places, both named below -- quote state and the backslash
# test. Two earlier cuts of this fix tried to RECONSTRUCT that line end from
# shell grammar -- walk the redirects, then decide from the operator that
# follows -- because
# every caller flattened newlines before this ran. Both approximations leaked in
# both directions: a markdown blockquote opening a body read as a redirect and
# denied ordinary writes at deny tier, while `tee <<'EOF' CLAUDE.md`, `2>&1`,
# `<` and a second `<<` each ended the walk early and hid a real write.
#
# So the callers stop flattening (they flatten after this returns) and the
# newline is simply READ. Everything from `<<DELIM` to that newline is COMMAND
# -- redirects, operators, a piped successor, arguments -- and is kept verbatim.
# Only the body is cut. The two token-class regexes this replaced are gone.
#
# Precisely: the first newline that is neither escaped nor inside a quoted span.
# The walk tracks `'...'` and `"..."` because backslash
# parity alone cannot decide it -- inside single quotes bash gives a backslash no
# escaping power at all, so a run there is not a line end however it counts, and
# the redirect following the quote's close on the SAME logical line was cut
# unseen: blind at deny tier, since policy-mutate.py imports this predicate.
# The same walk tracks `$( ... )` depth and backtick state: a newline
# inside a command substitution on the introducer's line used to end the kept
# region early and cut the redirect after it, blind at deny tier in the same way.
# Depth is enough here -- quotes are already tracked, so a `$(` inside `'...'` is
# never counted -- and an unbalanced opener at the terminator keeps the remainder
# verbatim, the same monotone direction as an unterminated quote.
# split_clauses() below tracks quote state as well and is deliberately
# NOT reused: it splits clauses rather than finding a line end, and reaching for
# it would run a second full scan on a predicate that fires on every Bash call.
#
# The INTERP test now sees the introducer's line too, not just the text before
# `<<`: `cat <<'EOF' | bash` puts the interpreter AFTER the introducer, and a
# body that will be EXECUTED has to be kept whole.
#
# ponytail: input with no newline at all -- a body already flattened by some
# other path -- falls through to keeping the whole span. That is the safe
# direction for this gate: scan everything, never cut blind.


def strip_heredocs(cmd):
    """Remove <<DELIM ... DELIM spans that are NOT fed to an interpreter.

    Input is the RAW command with newlines intact: every caller flattens AFTER
    this returns, never before, so the introducer's line end is read rather than
    reconstructed from shell grammar. The terminator is still matched
    as a word rather than anchored to a line of its own -- deliberately loose, so
    a body that reached us already flattened by some other path still ends. That
    looseness is not free: a body containing the delimiter as a bare word ends
    the span early and leaves the rest of the body in what the gate scans, which
    over-blocks at deny tier. Named cost, still open; line-anchoring it when the
    input HAS newlines is the fix and is deliberately not in this change-set.

    shell-scope.py and net-post.py carry this function byte-identical rather
    than sharing a module: they are sibling hooks, not caller and callee, and an
    import would add a load-failure mode to a gate whose only safe fallback is
    "scan everything". The pair is pinned equal by
    test_shell_scope.py::TheHeredocPredicateIsSharedByCopy, so drift fails the
    suite instead of silently reopening 187 or 213 in one gate only.
    """
    out, i = [], 0
    while True:
        m = HEREDOC_RE.search(cmd, i)
        if not m:
            out.append(cmd[i:])
            break
        # Only the current clause decides: `cat f | bash` earlier in the line
        # says nothing about who receives THIS body.
        prefix = re.split(r'&&|\|\||[;|]', cmd[:m.start()])[-1]
        delim = m.group(2) + m.group(3)
        end = re.search(r"(?<![\w-])%s(?![\w-])" % re.escape(delim),
                        cmd[m.end():])
        if not end:
            # The former rule -- "unterminated heredoc: everything after
            # the introducer is the body" -- cut to the end of the command and
            # took real writes with it. This gate also fires on PowerShell,
            # which has NO `<<` heredoc, so every match in a PS command is a
            # false one and never terminates: a PS here-string whose body names
            # `<<EOF` lost the `> CLAUDE.md` sitting after its `'@` terminator,
            # blind at deny tier. Probed 2026-09-07; PS here-strings do not
            # match HEREDOC_RE at all, so keeping costs them nothing new.
            # No terminator means we cannot see where the body ends, so keep it
            # -- the noisy answer, never the blind one, same as INTERP below.
            out.append(cmd[i:])
            break
        stop = m.end() + end.end()
        # Where the introducer's line ends -- a backslash escapes the newline and
        # keeps the same logical line going. No newline before the terminator
        # means we cannot see the body's start: keep everything.
        # One quote-aware walk, not a backslash test. A DOUBLE backslash at
        # top level is an escaped backslash and the line ENDS there (the former
        # one-character test read it as a continuation and carried body text into
        # `line`); a backslash INSIDE `'...'` escapes nothing, so the parity
        # replacement then ended the line at a newline bash reads as quoted text
        # and cut the redirect after the quote's close (round-2 review, F1).
        # Scanning quote state settles both, and an unterminated quote keeps the
        # remainder verbatim -- monotone toward blocking, the same direction the
        # unterminated-heredoc branch above takes.
        j, q, sub, tick = m.end(), None, 0, False
        while j < stop:
            c = cmd[j]
            if c == "\\" and q != "'":
                j += 2          # escapes the next character, a newline included
                continue
            if q:
                if c == q:
                    q = None
            elif c in "'\"":
                q = c
            elif c == "`":
                tick = not tick     # not nestable, so a toggle, not a counter
            elif c == "$" and cmd[j + 1:j + 2] == "(":
                sub += 1
                j += 2
                continue
            elif sub and c == ")":
                sub -= 1
            elif c == "\n" and not sub and not tick:
                break
            j += 1
        if q or sub or tick or j > stop:
            j = stop
        line = cmd[m.end():j]
        # The space is load-bearing. `prefix` ends at the character before
        # `<<` and `line` starts at the character after the delimiter, so a
        # bare concatenation ABUTS two characters that are not adjacent in the
        # command: `bash<<EOF-1` builds the word `bash-1`, INTERP's `(?![\w-])`
        # stops matching, and a body bash really does execute gets stripped.
        # Measured: without it, `bash<<EOF-1` + `rm CLAUDE.md` deletes the file
        # unseen by a deny-tier gate. INTERP has 23 alternatives; a sweep of the
        # 24 concrete words they spell (`python\d?` gives python and python3)
        # against 9 word-extending characters found the bare join blind on all 24.

        # It is NOT free in the other direction, and the earlier claim here that
        # it "can only break a seam word, never make one" was false. The space
        # gives `line[0]` a left word-boundary it does not have in the command,
        # so `cat > n.md<<'EOF'sh` -- which bash reads as the single delimiter
        # word `EOFsh` -- used to match `sh` and KEEP a prose body at deny tier.
        # Fixed at the root: HEREDOC_RE now consumes the unquoted tail, so
        # `line` starts past it and the terminator sought is the real one.
        if INTERP.search(prefix + " " + line):
            out.append(cmd[i:stop])     # executed: keep it, verbatim
        else:
            # Same seam, same space, same reason (F2). What is
            # elided here is `<<DELIM`, never fewer than two characters, so a
            # space is a truer stand-in than nothing. Without it,
            # `tee<<EOF-1 <out-of-tree path>` rebuilt the word `tee-1` and
            # VERB_WR stopped matching a real out-of-tree write, while
            # `echo hi > CLAUDE<<'X'.md` rebuilt `CLAUDE.md` and denied, at
            # deny tier, a write to a file actually named `CLAUDE`.
            out.append(cmd[i:m.start()] + " " + line)
        i = stop
    return "".join(out)


def split_clauses(cmd):
    """Split on ; && || | that are OUTSIDE quotes.

    Quote-aware, and that is not decoration. A quote-blind split of
    `sed -i 's/a/b/;s/c/d/' <out-of-tree>` leaves `-i` in clause 1 and the real
    target alone in a verbless clause 2, so the target is LOST -- a false
    negative manufactured by the false-positive fix, which is the wrong trade
    on a safety predicate.

    # ponytail: a hand-rolled scanner, not shlex. shlex.split eats backslashes
    # on Windows paths, which is the exact class of path this gate exists to
    # catch. This tracks quote state and nothing else.
    """
    parts, buf, q, i = [], [], None, 0
    while i < len(cmd):
        c = cmd[i]
        if q:
            buf.append(c)
            if c == q:
                q = None
            i += 1
            continue
        if c in "'\"":
            q = c
            buf.append(c)
            i += 1
            continue
        if cmd[i:i + 2] in ("&&", "||"):
            parts.append("".join(buf))
            buf, i = [], i + 2
            continue
        # `2>&1` and `>|` are redirects, not clause breaks: a bare | preceded by
        # > belongs to the redirect. REDIR_RE handles those; never split there.
        if c in ";|" and not (c == "|" and cmd[i - 1:i] == ">"):
            parts.append("".join(buf))
            buf, i = [], i + 1
            continue
        buf.append(c)
        i += 1
    parts.append("".join(buf))
    return [p for p in parts if p.strip()]


def write_targets(cmd, cwd):
    """All (raw, normalized) paths this command names in write position.

    175/90: scoped PER CLAUSE. The former version asked whether a write verb
    appeared anywhere in the command and then harvested every path-looking
    token in the whole command, so one write verb in one clause turned every
    path named anywhere -- other clauses, heredoc bodies, commit messages --
    into a write target. Both gates import this, and policy-mutate is
    deny-tier, so that single defect denied `cat CLAUDE.md && rm scratch.tmp`
    in every mode including bypass.

    Redirects still scan the whole command: REDIR_RE anchors on the `>` itself,
    so it is clause-scoped by construction.
    """
    res = []
    # Strip FIRST, flatten after. Everything below this line wants one
    # line; strip_heredocs is the only thing that needs the newlines, so it is
    # the only thing that sees them. Callers pass `cmd` raw.
    body_free = strip_heredocs(cmd).replace("\n", " ")
    for m in REDIR_RE.finditer(body_free):
        target = m.group(2) or m.group(3) or m.group(4)
        np = norm(target.strip(PUNCT), cwd)
        if np:
            res.append((target, np))
    clauses = split_clauses(body_free)
    pos = 0
    for k, clause in enumerate(clauses):
        # Where this clause sits, so the separator before it can be read. The
        # split is quote-aware; this walk inherits that, which is what keeps a
        # quoted `| xargs rm` from attributing (a bare regex over the command
        # would not).
        pos = body_free.find(clause, pos)
        piped = body_free[:pos].rstrip().endswith("|") and             not body_free[:pos].rstrip().endswith("||")
        pos += len(clause)
        cp = VERB_CP.search(clause)
        xargs = piped and k and XARGS_RE.match(clause)
        wr = VERB_WR.search(clause) or SED_RE.search(clause) or             (xargs and XARGS_WR.search(clause))
        if not (cp or wr):
            continue
        cands = []
        for t in _cands(clause):
            np = norm(t.strip(PUNCT), cwd)
            if np:
                cands.append((t, np))
        # The stdin-consuming successor. Its operands are the previous
        # clause's output, so that clause's paths are its targets too.
        if xargs:
            for t in _cands(clauses[k - 1]):
                np = norm(t.strip(PUNCT), cwd)
                if np:
                    cands.append((t, np))
        if not cands:
            continue
        # cp-family: only the LAST path is the target (copy IN stays free).
        res.extend(cands if wr else [cands[-1]])
    return res


def first_hit(cmd, cwd):
    """Return the offending out-of-tree path string, or None."""
    for t, np in write_targets(cmd, cwd):
        if not in_tree(np):
            return t
    return None


def main():
    log_mode = "--log" in sys.argv
    # Cloud-off under the
    # marker, but ONLY the gating call -- log_mode is log-escape.sh's audit
    # trail (row "log-escape": status "ported", stays live on cloud), and
    # must keep firing there. Windows unaffected (uc.cloud_boundary() reads
    # None there, always -- see its docstring).
    if not log_mode and uc is not None and uc.cloud_boundary():
        sys.exit(0)
    try:
        data = json.load(sys.stdin)
    except Exception:
        if log_mode:
            sys.exit(0)
        data = None
    if data is None:
        hit, cmd = "(unreadable hook input)", ""
    else:
        cmd = (data.get("tool_input") or {}).get("command") or ""
        if not cmd:
            sys.exit(0)
        try:
            hit = first_hit(cmd, data.get("cwd") or "")   # Raw; see write_targets
        except Exception as e:
            # The predicate crashed (`> ""` did, at write_targets). In
            # --log mode record the command; otherwise the __main__ handler
            # asks with the crash reason (this template named the
            # crash as a write target).
            if not log_mode:
                raise
            hit = "(shell-scope crashed: %s)" % type(e).__name__
    if not hit:
        sys.exit(0)
    if log_mode:
        print("shellwrite: %s <- %s" % (hit, cmd.replace("\n", " ")[:160]))
        sys.exit(0)
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "ask",
        "permissionDecisionReason":
            "shell-scope: command names out-of-tree write target '%s' — "
            "per-call user permission is the unlock (contract S2 L1)" % hit,
    }}))
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # Anything main() raises outside the predicate. Same decision.
        why = "shell-scope crashed: %s" % type(e).__name__
        if "--log" in sys.argv:
            print("shellwrite: (%s)" % why)
            sys.exit(0)
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": why + " -- cannot verify write targets",
        }}))
        sys.exit(0)
