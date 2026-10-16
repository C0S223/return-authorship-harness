# git-guard — PreToolUse Bash|PowerShell. Single job: block the git
# never-items — force push, new remotes / remote rewrites, tag pushes,
# default-branch pushes. NO unlock exists: the human types these
# commands, always. Quoted spans are stripped first so a commit message
# containing "push master" cannot false-deny (the earlier version friction lesson).
# Residual, stated: a bare `git push` (no refspec) passes — the target
# branch is not decidable from the args; propose-and-stop (S3) and
# log-escape's push line carry it.
#
# 2026-08-24: extended to the `gh` binary. The gate was keyed to the word
# "git", so `gh repo create --source . --remote origin --push` performed two
# never-items — remote creation and a default-branch push — and matched
# nothing. Found when the operator explicitly authorized that command and the
# agent declined on the prose rule; the hook was then read and would have
# allowed it. The general shape, which is the part worth carrying: a gate
# keyed to a BINARY NAME is bypassed by any other binary reaching the same
# effect, while the contract's escape principle is written in terms of effect.
# Expect a third tool. When it appears, add its name here rather than
# reasoning about whether it is "really" git.
#
# 2026-08-26: both rows matched the bare WORD "push" anywhere after
# the binary name, so an ordinary unquoted ARGUMENT containing it false-denied.
# Measured: a `gh pr create` denied on its branch name alone, and
# `git diff my-push-feature master` denied as a default-branch push — a read.
# The fix is one anchor on each side. The git row requires `push` to be a whole
# TOKEN, which is all three false positives needed: every one of them was
# `...-push-...`, hyphen-flanked. The gh row matches the --push FLAG, the
# never-item the 2026-08-24 row was written for.
#
# READ THIS BEFORE TOUCHING THE GIT ROW. The first attempt at that fix required
# `push` to be the SUBCOMMAND, skipping git's global options via an enumeration
# (-c, -C, --git-dir=, --work-tree=, and a generic flag catchall). It shipped
# green against a 30-command suite and it opened SIX holes, every one of them a
# never-item this gate exists to stop: `git.exe push origin master` (the `.` is
# a word boundary, so the subcommand never followed the binary), any global
# option in SEPARATE-VALUE form — `git --work-tree C:/repo push --force` — since
# the catchall consumed the flag but not its value, and `--git-dir` with a path
# containing no `.git` component, which had only ever passed by coincidence.
# Caught by non-author review before landing, not by the suite.
#
# The lesson is directional and it outranks precision here: narrowing a gate
# until only known-good shapes reach the check makes every unmodelled shape fail
# OPEN. This gate must fail closed. An anchor constrains the token you already
# match; an enumeration lists the world and loses to whatever is not on the
# list — the same failure as the 2026-08-24 lesson above, one grain finer.
# Coverage here is not asserted, it is differential:
# a differential matcher suite (kept outside this tree) runs every must-deny command
# against THIS file and against the previous revision, and fails on anything the
# old one denied and this one allows. A suite that only checks must-deny cannot
# fail a matcher that denies everything; one that only checks the current
# revision cannot see a regression. It needs both halves.
#
# One more, worth carrying because it will recur: this defect protected itself.
# The old row denied shell commands whose text merely discussed it — any
# UNQUOTED prose containing both `gh` and `push`, which is every useful commit
# message and test scaffold for the fix. (Quoted prose was always fine;
# strip_quoted runs first. The narrower true statement, since the first draft of
# this note overstated it.) The patch was applied through the file tool under a
# typed policy unlock — escalation, not paraphrase-and-retry: git-guard judges
# submitted commands, and no command was submitted.
import json
import os
import re
import sys
import time
from datetime import datetime

ROOT = (os.environ.get("HARNESS_ROOT") or os.environ.get("CLAUDE_PROJECT_DIR")
        or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# `push` as a whole token, NOT as a substring: `my-push-feature` must not match.
# The reach back to the binary stays deliberately loose — see the header. Do not
# replace this with an enumeration of git's global options.
PUSH_RE = re.compile(r'(?i)\bgit\b[^|;&]*?(?<![-\w])push(?![-\w.])([^|;&]*)')
# F22 (review SE-2): with origin/HEAD unresolved every push is denied, and so
# was any git command whose text held the word: `git stash push`, `git help
# push` (and `push.default`, now no match above: a config key, never a verb).
# Only those two subcommands, directly after the binary, are exempt from the
# unresolved deny; every other `push` word in the command still counts, so
# `git -C stash push ...` and a push nested after a stash both stay denied.
# `git log --grep push` is still denied while unresolved: fail closed.
PUSH_WORD = re.compile(r'(?i)(?<![-\w])push(?![-\w.])')
NOT_A_PUSH = re.compile(r'(?i)(?:^|[\s;&|(`])(?:\S*/)?git(?:\.exe)?\s+(?:stash|help)\s+$')
REMOTE_RE = re.compile(r'(?i)\bgit\b[^|;&]*?\bremote\b\s+(add|set-url|set-head)\b')
# refs/remotes/origin/HEAD is every gate's trust anchor for "the default
# branch" (pre-push, policy-integrity, review_order, this file), so moving it
# is a never-item like rewriting the remote. Judged on the unquoted text with
# each quoted span kept as ONE word, so a quoted target still counts as an
# argument; the subcommand must be a whole whitespace-bounded token, so prose
# inside a quoted message never matches. A read (`symbolic-ref [-q] [--short]
# <name>`, one positional) passes; a write or delete that names an origin ref,
# or hides its operands behind an expansion, is denied. Every update-ref that
# could touch origin's refs (`--stdin` included) is a write.
# F21 (review SE-1): the verb is anchored like the push row's, so an alias
# value (`alias.x=symbolic-ref`) and the dashed binary (`.../git-symbolic-ref`)
# count; operands are judged with shell escapes removed and case folded
# (`orig\in`, `ORIGIN`), and a glob or brace a shell could expand into an
# origin ref counts as hidden, like `$`.
SYMREF_RE = re.compile(r'(?i)\bgit\b[^|;&]*?(?<![\w-])(?:git-)?symbolic-ref(?=\s|$)([^|;&)`]*)')
UPDREF_RE = re.compile(r'(?i)\bgit\b[^|;&]*?(?<![\w-])(?:git-)?update-ref(?=\s|$)([^|;&)`]*)')
HIDDEN = re.compile(r'origin|remotes|[$`*?\[]|\{[^}]*(?:,|\.\.)')


REDIRECT = re.compile(r'^(?:\d*[<>]{1,2}&?|&>>?)$')


def _operand(t):
    return t.replace("\\", "").lower()


def _args(s):
    """Tokens minus redirections (F27, review SE-7): an attached one
    (`2>/dev/null`) and a bare operator with its target (`> /tmp/x`) are the
    shell's, so a read redirected to a file is still one positional."""
    out, skip = [], False
    for t in s.split():
        if skip:
            skip = False
        elif REDIRECT.match(t):
            skip = True
        elif not re.search(r'[<>]', t):
            out.append(t)
    return out


def moves_origin_ref(text):
    w = re.sub(QUOTED, _one_word, text.replace("\n", " "))
    for m in SYMREF_RE.finditer(w):
        toks = _args(m.group(1))
        pos = [t for t in toks if not t.startswith("-")]
        delete = "--delete" in toks or any(re.match(r'^-[A-Za-z]*d', t) for t in toks)
        if (len(pos) >= 2 or delete) and any(HIDDEN.search(_operand(t)) for t in pos):
            return True
    for m in UPDREF_RE.finditer(w):
        args = _operand(m.group(1))
        if "--stdin" in args or HIDDEN.search(args):
            return True
    return False
# A cloud boot found these three by spelling, not by reasoning: a
# refspec says the same thing four ways and only one of them was written down.
# A leading `+` on a refspec IS --force; `tag <name>` IS a tag push; and
# `HEAD:refs/heads/master` IS the default branch. Each was allowed, rc=0.
# A token also ends at `)` or a backtick: the close of `$(…)`, `(…)` or
# `…` (`out=$(git push origin master)` was allowed).
# A short-flag cluster carries -f anywhere in it: `-uf` and `-fu` force too.
# --follow-tags pushes annotated tags alongside the branch: a tag push.
FORCE_RE = re.compile(r'(?:^|\s)(--force(?:-with-lease(?:=\S*)?)?|-[A-Za-z]*f[A-Za-z]*)(?=[\s)`]|$)'
                      r'|(?:^|\s)\+(?=\S)')
TAGS_RE = re.compile(r'(?:^|\s)--(?:follow-)?tags(?=[\s)`=]|$)|refs/tags/|(?:^|\s)tag(?=[\s)`]|$)')
MIRROR_RE = re.compile(r'(?:^|\s)--mirror(?=[\s)`]|$)')
# The default branch is origin's, read from refs/remotes/origin/HEAD in ROOT,
# never a guessed name. `feature/main` is NOT the default branch: the optional
# `refs/heads/` must be the whole prefix, so only a bare, `:`-led or `+`-led
# name matches.
ORIGIN = "refs/remotes/origin/"


def default_branch():
    """origin's default branch name, or None when origin/HEAD is unset, points
    outside refs/remotes/origin/, or names no commit. None fails closed."""
    import subprocess
    try:
        r = subprocess.run(["git", "-C", ROOT, "symbolic-ref", "-q", ORIGIN + "HEAD"],
                           capture_output=True, text=True, timeout=10)
        ref = r.stdout.strip()
        if r.returncode or not ref.startswith(ORIGIN) or ref == ORIGIN:
            return None
        v = subprocess.run(["git", "-C", ROOT, "rev-parse", "-q", "--verify",
                            ref + "^{commit}"], capture_output=True, text=True, timeout=10)
        return ref[len(ORIGIN):] if v.returncode == 0 else None
    except Exception:
        return None


def default_re(name):
    return re.compile(r'(?:^|\s|:|\+)(?:refs/heads/)?' + re.escape(name) + r'(?=[\s)`]|$)')

# What may FOLLOW a never-item flag for it to count as that whole flag: white
# space, gh's `--flag=value` form (`--admin=true` executes as
# `--admin`), a separator the `[^|;&]` spans stop at (`--admin;`,
# `--admin&&`, `-X DELETE|` were the last token of their segment and
# `(?=\s|$)` let all three through), the close of a substitution (# `out=$(gh pr merge 12 --admin)`, the backtick form), or the end.
END = r'(?=[\s=;&|)`]|$)'

# gh never-items, by effect rather than by resemblance to git. Each of these
# reaches an outcome the human types or does not happen: standing up or
# destroying a remote, changing who can read one or how it is governed,
# publishing history to it, writing credentials into it, or landing past its
# required checks. `gh repo sync` is NOT here — it acts on a remote that
# already exists under an already-made decision. Nor is `gh pr merge` without
# `--admin`: the decision it acts under is CI's — a plain merge
# lands only what the required checks passed, and `--auto` is the sanctioned
# landing. `--admin` merges past a red check with the shared login, which
# is why it is the one `pr merge` shape here. The `gh api` doors to the same
# effect are judged in code below, per segment, because they hinge on
# ARGUMENT tokens rather than a subcommand word.
GH_NEVER = (
    (re.compile(r'(?i)\bgh\b[^|;&]*?\brepo\s+create\b'), "gh repo create"),
    (re.compile(r'(?i)\bgh\b[^|;&]*?\brepo\s+delete\b'), "gh repo delete"),
    (re.compile(r'(?i)\bgh\b[^|;&]*?\brepo\s+rename\b'), "gh repo rename"),
    # Every flag, not only --visibility: --default-branch,
    # --enable-auto-merge and --delete-branch-on-merge each change how the default branch
    # is governed. Flagless `gh repo edit` is interactive, which an agent cannot
    # drive, so the whole subcommand goes rather than an enumeration of its
    # flags — the header's lesson, applied.
    (re.compile(r'(?i)\bgh\b[^|;&]*?\brepo\s+edit\b'), "gh repo edit"),
    (re.compile(r'(?i)\bgh\b[^|;&]*?\bsecret\s+(set|delete)\b'), "gh secret write"),
    # The FLAG, anchored — never the bare word. `gh pr create --head my-push-br`
    # is not a never-item; `gh repo create ... --push` is.
    (re.compile(r'(?i)\bgh\b[^|;&]*?\s--push' + END), "gh --push"),
    # The FLAG, anywhere after `pr merge`: it lands past red required checks.
    (re.compile(r'(?i)\bgh\b[^|;&]*?\bpr\s+merge\b[^|;&]*?\s--admin' + END),
     "gh pr merge --admin"),
    # An alias can wrap any row here, and a `!` alias runs shell.
    # `gh alias list` and `delete` stay allowed.
    (re.compile(r'(?i)\bgh\b[^|;&]*?\balias\s+(set|import)\b'), "gh alias set/import"),
)

# `gh api` never-items.
# The default branch is gated by its ruleset, which requires CI's `gate` and
# `operator-merge` checks — and an admin identity
# BYPASSES it, so these are the api routes that rewrite or skip the gate.
# A segment is judged a WRITE by its explicit -X/--method when it has one
# (so `-X GET -F k=v` is a query, F4), else by a body flag, which makes gh
# POST (F7). EVERY method token counts and only GET or HEAD reads as a read:
# gh keeps the last of `-X GET -X DELETE`, and a token this text cannot
# resolve (`$M`, `$'DELETE'`) must fail closed, not excuse a body flag. gh's
# bool `-i` bundles in front of a shorthand (`-iX DELETE`, `-iF k=v`; gh
# 2.95 parses both). The gate ENDPOINTS: repos/<o>/<r> exactly, trailing slash or not
# (R4); its rulesets; a branch's protection; and a pull's merge (R2, the REST
# route to a merge) — bare, /-led, or as a full URL, in either order with the
# flags. Three REST routes are added
# that write the default branch without a PR: a ref (`git/refs`, anything under it), a
# server-side merge (`merges`), and a file (`contents`). A GET on any of them,
# and a write anywhere else (pulls, issues, comments, statuses), is ordinary
# traffic and passes. A GraphQL `mutation` is the same door again (R1), and
# it counts only in the QUERY: a `query=` field, or the stdin that
# `query=@-` / graphql's `--input -` takes. A query this
# text cannot read — a file, piped stdin, a `$` or backtick expansion —
# fails closed.
API_HEAD_RE = re.compile(r'(?i)\bgh\b[^|;&]*?\bapi\b')
API_METHOD_RE = re.compile(r'(?i)\s(?:-i*X|--method)[\s=]*([^\s)`]*)')
API_BODY_RE = re.compile(r'\s(?:-i*[fF]|--field\b|--raw-field\b|--input\b)')
API_READS = ("GET", "HEAD")
EP_END = r'(?=[\s/?;&|)`]|$)'
API_GATE_EP_RE = re.compile(
    r'(?i)(?:^|\s|/)repos/[^\s/]+/[^\s/]+'
    r'(?:/?(?=[\s?;&|)`]|$)'
    r'|/rulesets' + EP_END +
    r'|/branches/[^\s/]+/protection' + EP_END +
    r'|/pulls/[^\s/]+/merge' + EP_END +
    r'|/git/refs?' + EP_END +
    r'|/merges' + EP_END +
    r'|/contents' + EP_END + r')')
GRAPHQL_EP_RE = re.compile(r'(?i)(?:^|\s)(?:\S*/)?graphql(?=[\s?)`]|$)')
QUERY_RE = re.compile(r'(?i)\s(?:-i*[fF]|--field|--raw-field)[\s=]*query=(\S*)')
INPUT_RE = re.compile(r'(?i)\s--input[\s=]+(\S+)')
EXPANSION_RE = re.compile(r'(?<!\\)[$`]')
MUTATION_RE = re.compile(r'(?i)\bmutation\b')

QUOTED = r'"[^"]*"|\'[^\']*\''
HEREDOC_RE = re.compile(r'<<(-?)[ \t]*((?:\'[^\'\n]*\'|"[^"\n]*"|\\.|[^\s;|&<>()])+)')
# ponytail: no heredoc body is ever cut as data; every body line is read as
# commands too. Round 3 cut the bodies of "data" openers (git commit, gh api,
# cat) to stop false denies on prose, and the hook's idea of where
# a heredoc opens then drifted from bash's (`x\<<EOF` opens none,
# so the "body" ran). Operator ruling: prose naming a never-item in a heredoc is denied, fail
# closed; write the message to a file and use `git commit -F <file>` or
# `gh pr create --body-file`. A gh api heredoc is still read as its stdin.


def strip_quoted(cmd):
    return re.sub(QUOTED, ' ', cmd)


def _one_word(m):
    # The quote marks come off; what was inside stays ONE shell word, so a
    # space or a separator inside quotes is data, never a token boundary. A
    # single-quoted `$` or backtick expands nothing, so it is masked.
    s = m.group(0)
    inner = re.sub(r'[$`]', '\x02', s[1:-1]) if s[0] == "'" else s[1:-1]
    return re.sub(r'[\s|;&]', '\x01', inner)


def scan(cmd):
    """One quote-, `$(`- and heredoc-aware walk. Returns (text, pieces).
    `text` is cmd itself (no body is cut; see HEREDOC_RE's note); every flat
    row reads it. `pieces` holds one dict per simple command at every `$(` depth:
    `full` is its text including its substitutions' text (an
    endpoint inside a `$(` that spans lines), `outer` blanks them (a `-X GET`
    inside `$(…)` is the inner call's, not this one's), `stdin` is the body
    of a heredoc it opened. Pieces end at unquoted `|`, `;`, `&` and
    newlines, because an explicit method DECIDES: flattened, a `-X GET` on one
    line excused a body flag on the next. A separator inside `$(` ends the
    inner piece only. Line continuations (sh `\\`, PowerShell backtick) join;
    a `#` at a word's start comments out the rest of its line. A heredoc's
    body becomes its opener's `stdin` and is then walked as commands like
    any other line."""
    pieces, pending, stack = [], [], []

    def start(f):
        f["p"] = {"full": [], "outer": [], "stdin": None, "quoted": False,
                  "sep": None, "clean": f["clean"]}
        pieces.append(f["p"])

    def push(kind, in_dq=False):
        clean = (stack[-1]["clean"] if stack else True) and (kind != "sub" or in_dq)
        stack.append({"kind": kind, "depth": 0, "clean": clean})
        if kind in ("top", "sub"):
            start(stack[-1])

    def cmds():
        return [f for f in stack if f["kind"] in ("top", "sub")]

    def emit(s):
        cs = cmds()
        for f in cs:
            f["p"]["full"].append(s)
        cs[-1]["p"]["outer"].append(s)

    push("top")
    i, n = 0, len(cmd)
    while i < n:
        f, ch, two = stack[-1], cmd[i], cmd[i:i + 2]
        cont = re.match(r'(\\|`)\r?\n', cmd[i:i + 3])
        if cont:
            if cont.group(1) == "`":
                emit(" ")
            i += len(cont.group(0))
            continue
        if f["kind"] == "sq":
            emit(ch)
            if ch == "'":
                stack.pop()
        elif f["kind"] == "dq":
            emit(two if two == "$(" else ch)
            if two == "$(":
                push("sub", in_dq=True)
                i += 1
            elif ch == '"':
                stack.pop()
        elif ch in "'\"":
            emit(ch)
            push("sq" if ch == "'" else "dq")
        elif two == "$(":
            emit(two)
            push("sub")
            i += 1
        elif f["kind"] == "sub" and ch in "()":
            if ch == ")" and not f["depth"]:
                f["p"]["sep"] = ")"
                stack.pop()
            else:
                f["depth"] += 1 if ch == "(" else -1
            emit(ch)
        elif ch in "|;&\n":
            cs = cmds()
            cs[-1]["p"]["sep"] = ch
            start(cs[-1])
            for g in cs[:-1]:
                g["p"]["full"].append(" ")
            if ch == "\n" and pending:
                j = i + 1
                for p, delim, dash, quoted in pending:
                    body = j
                    while True:
                        k = cmd.find("\n", j)
                        line = cmd[j:n if k < 0 else k].rstrip("\r")
                        end = (line.lstrip("\t") if dash else line) == delim
                        if end or k < 0:
                            p["stdin"], p["quoted"] = cmd[body:j if end else n], quoted
                            j = n if k < 0 else k + 1
                            break
                        j = k + 1
                pending = []
        elif cmd.startswith("<<<", i):   # a here-string, not a heredoc
            emit("<<<")
            i += 3
            continue
        elif ch == "#" and (i == 0 or cmd[i - 1] in " \t\n;|&()"):
            k = cmd.find("\n", i)
            k = n if k < 0 else k
            emit(cmd[i:k])               # a comment opens no heredoc
            i = k
            continue
        else:
            m = HEREDOC_RE.match(cmd, i) if two == "<<" else None
            if m:
                delim = re.sub(r'[\'"\\]', "", m.group(2))
                pending.append((cmds()[-1]["p"], delim,
                                bool(m.group(1)), delim != m.group(2)))
                emit(two)
                i += 2
                continue
            emit(ch)
        i += 1
    return cmd, pieces


def api_write(full, outer):
    # Every method token counts and only GET or HEAD reads as a read: gh keeps
    # the last `-X`, and a token this text cannot resolve (`$M`) fails closed.
    # A write method anywhere, a substitution's included, counts; only this
    # call's OWN read method excuses its body flags.
    if any(m.upper() not in API_READS for m in API_METHOD_RE.findall(full)):
        return True
    if API_METHOD_RE.search(outer):
        return False
    return API_BODY_RE.search(full) is not None


def graphql_mutation(seg, p):
    stdin = p["stdin"]
    # An unquoted `<<EOF` expands its body and rewrites its backslashes,
    # so either makes
    # the query unreadable here, which fails closed.
    if stdin is not None and not p["quoted"] and (
            EXPANSION_RE.search(stdin) or "\\" in stdin):
        stdin = None
    sources = QUERY_RE.findall(seg)
    if GRAPHQL_EP_RE.search(seg):
        sources += ["@" + v for v in INPUT_RE.findall(seg)]
    for v in sources:
        q = stdin if v == "@-" else None if v[:1] == "@" or EXPANSION_RE.search(v) else v
        if q is None or MUTATION_RE.search(q):
            return True
    return False


def judge_api(pieces):
    for p in pieces:
        full = "".join(p["full"])
        if not API_HEAD_RE.search(strip_quoted(full)):
            continue
        full = re.sub(QUOTED, _one_word, full)
        outer = re.sub(QUOTED, _one_word, "".join(p["outer"]))
        if graphql_mutation(full, p):
            deny("gh api graphql mutation")
        if api_write(full, outer) and API_GATE_EP_RE.search(full):
            deny("gh api write to a ruleset, branch protection, repo settings, "
                 "a pull's merge, a ref, a merge or a file")


def deny(reason):
    try:
        d = os.path.join(ROOT, ".agent-log")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, time.strftime("%Y-%m-%d") + ".md"),
                  "a", encoding="utf-8") as f:
            f.write("- %s [git-guard] DENY %s\n"
                    % (datetime.now().strftime("%H:%M:%S"), reason))
    except Exception:
        pass
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason":
            "git-guard: %s — no unlock exists; the human types this "
            "(contract S2 L1)" % reason,
    }}))
    sys.exit(0)


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)          # no command text = nothing to judge
    cmd = (data.get("tool_input") or {}).get("command") or ""
    if not cmd:
        sys.exit(0)
    text, pieces = scan(cmd)
    flat = strip_quoted(text.replace("\n", " "))
    for pattern, reason in GH_NEVER:
        if pattern.search(flat):
            deny(reason)
    judge_api(pieces)
    if REMOTE_RE.search(flat):
        deny("git remote add/set-url/set-head")
    if moves_origin_ref(text):
        deny("a write to refs/remotes/origin/ (moves the default branch every gate reads)")
    dflt = False     # resolved once, on the first push
    for m in PUSH_RE.finditer(flat):
        args = m.group(1)
        if FORCE_RE.search(args):
            deny("force push")
        if MIRROR_RE.search(args):
            deny("mirror push")
        if TAGS_RE.search(args):
            deny("tag push")
        if dflt is False:
            dflt = default_branch()
        if dflt is None:
            if any(not NOT_A_PUSH.search(flat[:p.start()]) for p in PUSH_WORD.finditer(flat)):
                deny("push while origin's default branch cannot be resolved "
                     "(refs/remotes/origin/HEAD unset or dangling); the human runs "
                     "`git remote set-head origin --auto`")
        elif default_re(dflt).search(args):
            deny("default-branch push")
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # An uncaught raise exits 1, which Claude Code treats as
        # non-blocking, so a crash let the call through. Fail closed instead.
        deny("crashed (%s) -- refusing rather than passing the call ungated" % type(e).__name__)
