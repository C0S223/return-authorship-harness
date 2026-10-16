# log-escape.py -- log-escape.sh's one Python process.
#
# The hook used to fork jq, tr and sed several times per call, then start
# shell-scope.py or filetool-scope.py as a second Python on top. Each start
# costs 25-60 ms on Windows. This helper answers all of those questions in ONE
# process and hands the answers back to the hook as shell assignments:
#
#   python log-escape.py <tool_name>  <<<"$INPUT"
#
# It answers only where its answer is byte-for-byte what the pipelines would
# have produced. Anything else -- JSON that python and jq might read
# differently, a value jq would print as JSON rather than raw, a byte the hook
# cannot carry through a variable -- prints NOTHING, and the hook runs its
# original pipelines instead. Declining is always safe; guessing never is.
#
# The scope scripts are frozen and shared with the gates, so they are not
# re-implemented here: they run unchanged, in-process, under the same argv,
# stdin and stdout text encodings a child `python <script> --log` would get.
import io
import json
import os
import re
import runpy
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# The sed blanker of log-escape.sh. At any start, the quote character decides
# the alternative, so leftmost-first here is sed's leftmost-longest.
BLANK = re.compile(r"""'[^']*'|"[^"]*\"""")
# log-escape.sh's classify(), for ASCII text only: there [[:alnum:]] is the same
# in every locale, and match or no match is the same in POSIX ERE and here.
RE_PUSH = re.compile(r"(^|[^-A-Za-z0-9_])git[^|;&]*[^-A-Za-z0-9_]push([^-A-Za-z0-9_]|$)")
RE_GH = re.compile(r"(^|[^-A-Za-z0-9_.])gh([^-A-Za-z0-9_/.]|$)")
CLASS_WORDS = ("curl", "wget", "Invoke-WebRequest", "Invoke-RestMethod",
               "Start-BitsTransfer", "npx", "npm install", "npm i ", "pip install",
               "uv add", "uv pip", "pnpm add", "pnpm install", "winget", "choco")
# Bytes the hand-back cannot carry: NUL is dropped by $( ) (with a warning the
# pipelines would print), 0x01 and 0x7f are bash's internal quoting bytes.
UNSAFE = (b"\x00", b"\x01", b"\x7f")


class Decline(Exception):
    """This call is not one the helper can answer exactly."""


def _refuse(_):
    raise Decline("NaN/Infinity: jq reads these differently")


def _check(v, d=0):
    """Decline what jq parses differently from python, anywhere in the input:
    nesting past its depth limit (256 in 1.6), and a lone UTF-16 surrogate
    escape, which jq 1.7 rejects as a parse error and 1.6 turns into U+FFFD."""
    if d > 100:
        raise Decline("nesting")
    if isinstance(v, str):
        _utf8(v)
    elif isinstance(v, dict):
        for k, x in v.items():
            _utf8(k)
            _check(x, d + 1)
    elif isinstance(v, list):
        for x in v:
            _check(x, d + 1)


def _utf8(s):
    try:
        return s.encode("utf-8")
    except UnicodeEncodeError:
        raise Decline("lone surrogate")


def parse(raw):
    try:
        text = raw.decode("utf-8")      # jq would replace invalid bytes
        data = json.loads(text, parse_constant=_refuse)
    except Decline:
        raise
    except Exception:
        raise Decline("unreadable")     # jq's error text is the pipelines' job
    if not isinstance(data, dict):
        raise Decline("not an object")
    _check(data)
    return data


def jq_field(data, key):
    """`.tool_input.<key>` as jq evaluates it: None for null/missing."""
    ti = data.get("tool_input")
    if ti is None:
        return None
    if not isinstance(ti, dict):
        raise Decline("jq errors indexing a non-object")
    return ti.get(key)


def absent(v):
    # jq's `//` falls through on null and false only ("" and 0 are values).
    return v is None or v is False


def jq_alt(data, keys, default):
    """`.tool_input.a // .tool_input.b // default` for string results."""
    for k in keys:
        v = jq_field(data, k)
        if not absent(v):
            if not isinstance(v, str):
                raise Decline("jq -r would print JSON, not text")
            return v
    return default


def piped(s):
    """What `$(jq -r ... | tr -d '\\r')` leaves of the string s."""
    return _utf8(s).replace(b"\r", b"").rstrip(b"\n")


def child(script, raw):
    """stdout bytes of `python <HERE>/<script> --log` fed `raw` on stdin.

    Streams are rebuilt the way CPython builds a child's pipe stdio: this
    process was started the same way, so its own encodings are the child's.
    stderr went to /dev/null there, and an exception there was exit 1 with
    whatever stdout had taken so far; both hold here."""
    newline = None if os.name == "nt" else "\n"
    stdin = io.TextIOWrapper(io.BytesIO(raw), encoding=sys.stdin.encoding,
                             errors=sys.stdin.errors, newline=newline)
    buf = io.BytesIO()
    stdout = io.TextIOWrapper(buf, encoding=sys.stdout.encoding,
                              errors=sys.stdout.errors, newline=newline)
    path = os.path.join(HERE, script)
    saved = sys.argv, sys.stdin, sys.stdout, sys.stderr
    sys.argv, sys.stdin, sys.stdout, sys.stderr = [path, "--log"], stdin, stdout, io.StringIO()
    try:
        runpy.run_path(path, run_name="__main__")
    except BaseException:
        pass
    finally:
        try:
            stdout.flush()
        except Exception:
            pass
        sys.argv, sys.stdin, sys.stdout, sys.stderr = saved
    return buf.getvalue()


def classified(text):
    """True when classify() certainly sets a class; False when unsure."""
    if not text.isascii():
        return False
    return bool(RE_PUSH.search(text) or RE_GH.search(text)
                or any(w in text for w in CLASS_WORDS))


def answer(mode, raw):
    """-> ([(shell variable, bytes)], whether the hook will certainly log)."""
    if mode == "shell":
        data = parse(raw)
        cmd = jq_field(data, "command")
        if absent(cmd):
            cmd = ""                    # `// empty`
        elif not isinstance(cmd, str):
            raise Decline("jq -r would print JSON, not text")
        rawb = piped(cmd)
        src = rawb.decode("utf-8").replace("\\\n", " ").replace("\n", ";")
        scan = BLANK.sub(" ", src).encode("utf-8")
        ss = child("shell-scope.py", raw).replace(b"\r", b"").rstrip(b"\n")
        scanned = scan if scan or not rawb else src.encode("utf-8")
        logs = bool(ss) or classified(scanned.decode("utf-8")) or classified(src)
        return [("RAW", rawb), ("SCAN", scan), ("SS_LINE", ss)], logs
    if mode == "file":
        # log-escape.sh's `tr -d` here holds a literal CR byte. Linux bash keeps it
        # and deletes every CR; Git Bash drops it on reading the script, so only $( )
        # trims a trailing CRLF there (SE review F3). The two agree unless a CR sits
        # inside the line, so answer only then.
        ft = child("filetool-scope.py", raw)
        body = ft
        while body.endswith(b"\n"):
            body = body[:-2] if body.endswith(b"\r\n") else body[:-1]
        if b"\r" in body:
            raise Decline("a CR the pipelines keep on Windows and drop on Linux")
        return [("FT_LINE", body)], bool(body)
    data = parse(raw)
    if mode == "spawn":
        return [("KIND", piped(jq_alt(data, ["subagent_type"], "unnamed"))),
                ("DESC", piped(jq_alt(data, ["description"], "")))], True
    if mode == "peer":
        tid = piped(jq_alt(data, ["trigger_id", "name"], ""))
        text = jq_field(data, "text")
        if absent(text):
            text = ""
        elif not isinstance(text, str):
            raise Decline("jq's length of a non-string")
        return [("TID", tid), ("LEN", str(len(text)).encode())], True
    if mode == "web":
        return [("Q", piped(jq_alt(data, ["url", "query"], "")))], True
    raise Decline("unknown mode")


# The hook's `case "$TOOL"` arms, name for name.
MODES = {"Agent": "spawn", "Task": "spawn",
         "Bash": "shell", "PowerShell": "shell",
         "Write": "file", "Edit": "file", "NotebookEdit": "file",
         "WebFetch": "web", "WebSearch": "web"}


def mode_of(tool):
    if tool.startswith(("mcp__claude-code-remote__", "mcp__Claude_Code_Remote__")):
        return "peer"
    return MODES.get(tool, "")


def make_log_dir():
    """The hook's `mkdir -p "$ROOT/.agent-log"`, done here to save its process.

    argv[0] is the "$ROOT/.claude/hooks/log-escape.py" the hook passed, after
    any path conversion Git Bash applied to it, so cutting the suffix leaves
    the hook's own $ROOT. Only called when a line will certainly be written;
    the hook still runs mkdir itself whenever the directory is not there, so a
    failure here (a file in the way) still fails there, as before."""
    tail = "/.claude/hooks/log-escape.py"
    if sys.argv[0].endswith(tail):
        try:
            os.makedirs(sys.argv[0][:-len(tail)] + "/.agent-log", exist_ok=True)
        except OSError:
            pass


def main():
    raw = sys.stdin.buffer.read()
    if raw.endswith(b"\n"):
        raw = raw[:-1]                  # the here-string's own newline
    try:
        pairs, logs = answer(mode_of(sys.argv[1] if len(sys.argv) > 1 else ""), raw)
    except Decline:
        return
    out = [b"#log-escape"]
    for name, val in pairs:
        if any(u in val for u in UNSAFE):
            return
        out.append(name.encode() + b"='" + val.replace(b"'", b"'\\''") + b"'")
    if logs:
        make_log_dir()
    out.append(b"FAST=1")
    sys.stdout.buffer.write(b"\n".join(out))
    sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()
