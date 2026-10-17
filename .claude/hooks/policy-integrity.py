# policy-integrity — PostToolUse Bash|PowerShell|Write|Edit|NotebookEdit|Agent
# and SessionStart startup|resume. The layer of RECORD for policy-path
# mutation. Asks the files what happened, never the command what it will do:
# bytes on disk against a session-start baseline {path: [size, mtime, sha]},
# so git's own verbs, an interpreter's open() and a two-backtick Copy-Item all
# read the same as an Edit. Records and alerts; prevents nothing (the bytes
# have already changed). One consumed grant line in the day log covers exactly
# one difference on its path, and only while its grant is live (after
# this session's latest arm/revoke marker, under 8 h). Another
# session's live credit reads PEER-GRANTED, bytes equal to origin's default branch read
# MERGED, and a worktree mid-removal is one ROOT-REMOVED line; anything else is
# UNGRANTED.
#
# Cost: the matcher
# in settings.json keeps this process off every read call; here stat first,
# hash only what moved. Baseline is taken on startup/resume only, never on
# compact (re-baselining there would launder an earlier UNGRANTED change).
# Imports is_policy from policy-mutate.py the way policy-mutate
# imports shell-scope -- a classifier of a path, not a decision for a gate.
import importlib.util
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = (os.environ.get("HARNESS_ROOT") or os.environ.get("CLAUDE_PROJECT_DIR")
        or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
NROOT = os.path.normcase(os.path.realpath(ROOT))
LOG_DIR = os.path.join(ROOT, ".agent-log")
WRITERS = {"Bash", "PowerShell", "Write", "Edit", "NotebookEdit", "Agent", "Task"}
# Fixed roots (mechanism 2). `.git/refs` is not walked; the one ref every gate
# reads as "the default branch", origin/HEAD, is watched as a file (FILES).
DIRS = (".claude", ".codex", ".agents", "scripts", "templates", "skills",
        # The tracked pre-push hook sources (is_policy carries the rule)
        ".githooks", os.path.join("tools", "git-hooks"),
        # Role definitions and the grill and lane graphs (is_policy carries the rule)
        "roles", "graphs",
        os.path.join(".git", "hooks"), os.path.join(".git", "info"))
FILES = ("CLAUDE.md", "AGENTS.md", "AGENTS.override.md", "README.md", os.path.join(".git", "config"),
         # origin's default for pre-push, git-guard, review_order and on_master;
         # a symref is always a loose file, never packed
         os.path.join(".git", "refs", "remotes", "origin", "HEAD"))
SKIP = {"__pycache__", ".venv", "node_modules"}
# Runtime state a hook writes on every call, gitignored, policy-shaped by path
# only. Watching it made the file 73% of a managed day log.
SKIP_REL = {".claude/hooks/auto-compact/state.json"}

# A credit
# outlived its grant. policy-mutate writes one `unlock-consumed` line per
# allowed HIT, and a hit that changes no bytes (same-content Write, `sed -i`
# with no match, `printf '' >>`) leaves a line the compare never matches --
# which then covered a gate-blind change AFTER `revoke-policy`, as `granted`.
# Under one-shot grants each such spare cost a typed one-shot; under a task
# grant it was free. So a credit counts only while the grant that wrote it is
# live: it must follow this sid's latest MARKER -- a policy-prompt
# `unlock-armed (policy)` or `unlock-revoked (policy)` line carrying `sid=`
# (arming replaces the whole grant, so it ends the old one) -- and `now` must
# be inside GRANT_LIFE of that arm line's own stamp (the gate's cap runs from
# arming; a grant that merely aged out writes no marker). A credit with no
# arm marker for its sid in today's file (armed before midnight, or legacy)
# falls back to its own stamp + GRANT_LIFE. Another sid's marker voids
# nothing. Legacy one-shot credits get the same voiding; it only tightens.
MARKER_RE = re.compile(r"\[policy-prompt\] unlock-(?:armed|revoked) \(policy\): .*\bsid=(\S*)\s*$")
CREDIT_RE = re.compile(r"\[policy-mutate\] unlock-consumed: (.+?) sid=(\S*)\s*$")
STAMP_RE = re.compile(r"^- (\d\d:\d\d:\d\d) ")
GRANT_LIFE = 28800


def _is_policy():
    spec = importlib.util.spec_from_file_location(
        "policymutate", os.path.join(HERE, "policy-mutate.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m.is_policy


def log_line(msg):
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(os.path.join(LOG_DIR, time.strftime("%Y-%m-%d") + ".md"),
                  "a", encoding="utf-8") as f:
            f.write("- %s [policy-integrity] %s\n" % (time.strftime("%H:%M:%S"), msg))
    except Exception:
        pass


def safe(rel):
    # attacker-chosen text in a log line: printable only, capped
    rel = rel.replace("\\", "/")
    rel = "".join(c if 32 <= ord(c) < 127 else "?" for c in rel)
    return rel[:200]


def roots():
    out = [ROOT]
    wt = os.path.join(ROOT, "worktrees")
    try:
        for n in sorted(os.listdir(wt)):
            if os.path.isdir(os.path.join(wt, n)):
                out.append(os.path.join(wt, n))
    except OSError:
        pass
    return out


def candidates(root, deep):
    """Policy-shaped paths under one checkout root, absolute. `deep` adds the
    tracked CLAUDE.md/AGENTS.md at any depth (one git call, baseline only)."""
    for f in FILES:
        p = os.path.join(root, f)
        if os.path.isfile(p):
            yield p
    for d in DIRS:
        top = os.path.join(root, d)
        for dp, dn, fn in os.walk(top):
            dn[:] = [x for x in dn if x not in SKIP]
            for f in fn:
                yield os.path.join(dp, f)
    if deep:
        try:
            import subprocess   # baseline only; keeps the per-call import set small
            out = subprocess.run(
                ["git", "-C", root, "ls-files", "-z", "--", "*CLAUDE.md", "*AGENTS.md", "*AGENTS.override.md"],
                capture_output=True, timeout=10).stdout
            for rel in out.decode("utf-8", "replace").split("\0"):
                if rel and os.path.isfile(os.path.join(root, rel)):
                    yield os.path.join(root, rel)
        except Exception:
            pass


def sha(p):
    import hashlib   # only when a stat differs; the no-op path never pays it
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def snapshot(root, is_policy, deep, seen=None):
    """{relpath: [size, mtime_ns, sha]} for one root. `seen` (a previous
    snapshot) lets the stat-first path skip hashing unchanged files."""
    snap = {}
    # paths the deep baseline found (CLAUDE.md/AGENTS.md at depth) are re-stat'd
    # by name on every compare instead of re-walked: mechanism 2(b)
    extra = [os.path.join(root, r) for r in (seen or {})]
    for p in list(candidates(root, deep)) + extra:
        np = os.path.normcase(os.path.realpath(p))
        if not is_policy(np):
            continue
        rel = os.path.relpath(p, root).replace("\\", "/")
        if rel in snap or rel in SKIP_REL:
            continue
        try:
            st = os.stat(p)
        except OSError:
            continue
        old = (seen or {}).get(rel)
        if old and old[0] == st.st_size and old[1] == st.st_mtime_ns:
            snap[rel] = old
        else:
            try:
                snap[rel] = [st.st_size, st.st_mtime_ns, sha(p)]
            except OSError:
                continue
    return snap


def relroot(root):
    return "." if root == ROOT else os.path.relpath(root, ROOT).replace("\\", "/")


def _stamp(line, day):
    """The line's `- HH:MM:SS` on `day` as an epoch, or None."""
    st = STAMP_RE.match(line)
    try:
        return time.mktime(time.strptime(
            "%s %s" % (day, st.group(1)), "%Y-%m-%d %H:%M:%S"))
    except (AttributeError, ValueError, OverflowError):
        return None


def live_credits(now=None):
    """Today's LIVE `unlock-consumed: <path> sid=<sid>` lines from policy-mutate,
    as {sid: [(key, normalized path)]}. The day log is the ledger: it survives
    the grant file being replaced by the next auth-policy (mechanism 5) -- but a
    credit is void once its grant ends: every credit
    before its sid's latest marker is dropped, and every credit is dropped once
    GRANT_LIFE has passed since its sid's latest arm marker (no arm marker
    today: since the credit's own stamp). Each sid is voided only by its own
    markers. `now` is the compare moment; tests pin it."""
    day = time.strftime("%Y-%m-%d")
    now = time.time() if now is None else now
    out, deadline = {}, {}
    try:
        with open(os.path.join(LOG_DIR, day + ".md"), encoding="utf-8") as f:
            for i, line in enumerate(f):
                mk = MARKER_RE.search(line)
                if mk:
                    s = mk.group(1)
                    out[s] = []       # the grant that wrote every credit so far ended
                    armed = "unlock-armed" in line and _stamp(line, day)
                    deadline[s] = armed + GRANT_LIFE if armed else None
                    continue
                m = CREDIT_RE.search(line)
                if not m:
                    continue
                s, stamp = m.group(2), _stamp(line, day)
                if stamp is None:
                    continue          # unstamped or unparsable: no credit
                d = deadline.get(s)
                if now >= (d if d is not None else stamp + GRANT_LIFE):
                    continue
                p = m.group(1).strip()
                p = p if os.path.isabs(p) else os.path.join(ROOT, p)
                out.setdefault(s, []).append(
                    ("%s:%d" % (day, i), os.path.normcase(os.path.realpath(p))))
    except OSError:
        pass
    return out


def consumed_lines(sid, now=None):
    """This sid's live credits, as (key, normalized path)."""
    return live_credits(now).get(sid, [])


def origin_default(root):
    """refs/remotes/origin/<default>, read from refs/remotes/origin/HEAD; None
    when unset or dangling, and on_master then fails closed (UNGRANTED)."""
    import subprocess
    try:
        r = subprocess.run(["git", "-C", root, "symbolic-ref", "-q", "refs/remotes/origin/HEAD"],
                           capture_output=True, text=True, timeout=10)
        ref = r.stdout.strip()
        if r.returncode != 0 or not ref.startswith("refs/remotes/origin/"):
            return None
        v = subprocess.run(["git", "-C", root, "rev-parse", "-q", "--verify", ref + "^{commit}"],
                           capture_output=True, timeout=10)
        return ref if v.returncode == 0 else None
    except Exception:
        return None


def on_master(root, rel, digest):
    """True when the file's bytes (sha256
    `digest`) are exactly what a checkout of `<origin default>:<rel>` writes --
    content that already passed PR review and the operator's merge, so a pull
    or merge of it is not an incident. Not HEAD: an `edit && git commit` in one
    call would read as committed and launder. Checkout bytes, not the clean
    blob: `hash-object` normalises line endings, so a CRLF rewrite
    of an `eol=lf` pre-push hook -- which git then skips -- would match.
    Attributes come from the default branch's tree too: the working-tree
    `.gitattributes` is not watched, so an `eol=crlf` line appended there
    re-opened F1. `.git/info/attributes` and `.git/config` are watched.
    The default branch is origin/HEAD's target, never a guessed name.
    ponytail: trusts the local remote-tracking refs and the user- and
    system-level git config and attributes files outside the tree; a local write of
    refs/remotes/origin/HEAD's target, or of those, forges it. A move of origin/HEAD
    itself is recorded here (FILES) and denied by git-guard."""
    import hashlib, subprocess   # uncovered differences only; never on the no-op path
    ref = origin_default(root)
    if ref is None:
        return False
    try:
        r = subprocess.run(["git", "--attr-source=" + ref,
                            "-C", root, "cat-file", "--filters",
                            ref + ":" + rel],
                           capture_output=True, timeout=10)
        return r.returncode == 0 and hashlib.sha256(r.stdout).hexdigest() == digest
    except Exception:
        return False


def baseline_path(sid):
    # `-unlock-` in the name: policy-mutate's is_grant seal (a filename shape)
    # covers it without a second seal. Text-gate strength.
    return os.path.join(LOG_DIR, "policy-baseline-unlock-%s.json" % sid)


def write_baseline(path, data):
    os.makedirs(LOG_DIR, exist_ok=True)
    tmp = "%s.tmp.%d" % (path, os.getpid())
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def take_baseline(sid, is_policy, why):
    data = {"roots": {relroot(r): snapshot(r, is_policy, True) for r in roots()},
            "matched": []}
    write_baseline(baseline_path(sid), data)
    n = sum(len(v) for v in data["roots"].values())
    log_line("BASELINE %s: %d paths in %d root(s)" % (why, n, len(data["roots"])))
    return data


def claim_time(fp):
    """A claim's age is from the time stamped in its name; a legacy
    `.claim.<pid>` name (no stamp) falls back to its mtime as before."""
    tail = fp.rsplit(".claim.", 1)[-1].split(".")
    # ASCII digits only: the name is listed from an agent-writable directory,
    # and str.isdigit passes digits like '\u00b2' that int() rejects
    if len(tail) == 2 and re.fullmatch(r"[0-9]+", tail[1]):
        return int(tail[1])
    return os.stat(fp).st_mtime


def hand_back(claim, bp):
    """Return the claimed baseline by rename. False if the claim is gone:
    a peer recovered it after 30 s, or (Windows, unlock_consume.py:21-26) the
    claim rename reported success and moved nothing. Was an uncaught [Errno 2]
    logged as `hook error`."""
    try:
        os.replace(claim, bp)
        return True
    except FileNotFoundError:
        log_line("claim gone at hand-back; nothing to hand back")
        return False


def compare(sid, is_policy):
    bp = baseline_path(sid)
    # Claim by rename (unlock_consume.py's shape): two hooks from parallel tool
    # calls cannot both advance the baseline over each other's diff. A missing
    # file means a peer holds the claim, or no baseline exists yet.
    # The claim's own name carries its claim time. A rename keeps the
    # baseline's mtime -- the time of its last WRITE, often minutes back -- so
    # judging a claim's age by mtime made every live claim on an idle baseline
    # read as a crashed peer: a parallel call stole it, and when the thief
    # wrote last a second, ungranted write rode the first write's credit.
    claim = "%s.claim.%d.%d" % (bp, os.getpid(), int(time.time()))
    try:
        os.replace(bp, claim)
    except OSError:
        # No file to claim. Three states, told apart by the claim files present
        # (the loser of a race must never take a fresh baseline
        # over the winner's): a peer holds a fresh claim -> skip, the bytes are
        # still changed and the next call compares them; a claim older than
        # 30 s is a crashed peer -> recover it and compare; no claim at all and
        # no baseline -> this session was never baselined, take one late.
        try:
            claims = [os.path.join(LOG_DIR, n) for n in os.listdir(LOG_DIR)
                      if n.startswith(os.path.basename(bp) + ".claim.")]
        except OSError:
            claims = []
        for fp in claims:
            try:
                if time.time() - claim_time(fp) > 30:
                    os.replace(fp, bp)
                    return compare(sid, is_policy)
            except OSError:
                pass
        if claims or os.path.exists(bp):
            log_line("skipped: a peer call holds the baseline claim; the next "
                     "compare (any writer call, or resume) sees the same bytes")
            return
        take_baseline(sid, is_policy, "late (no baseline for this session)")
        return
    try:
        with open(claim, encoding="utf-8") as f:
            base = json.load(f)
        if not isinstance(base, dict) or not isinstance(base.get("roots"), dict):
            raise ValueError("baseline is not an object")
    except Exception:
        if hand_back(claim, bp):
            log_line("baseline unreadable for session %s; left as is" % sid)
        return

    credits = live_credits()
    ledger = credits.get(sid, [])
    # Another session's live credit covers one difference on its path
    # here, labelled with the peer's sid, not folded into this session's
    # `granted`. Ceiling: the credit
    # cannot say whose write it covers, so a peer's spare (a no-byte hit, 666)
    # covers one gate-blind write in each other session while its grant lives.
    # A credit with an empty sid is nobody's grant.
    peers = [(k, p, s) for s, l in credits.items() if s and s != sid for k, p in l]
    matched = set(base.get("matched") or [])
    ungranted, lines = 0, []
    now = {relroot(r): r for r in roots()}
    new_roots = {}
    for rr, root in now.items():
        old = base["roots"].get(rr)
        if old is None:
            new_roots[rr] = snapshot(root, is_policy, True)
            lines.append("NEW-ROOT %s %d paths" % (safe(rr), len(new_roots[rr])))
            continue
        cur = snapshot(root, is_policy, False, seen=old)
        if rr != "." and old and not cur:
            # A worktree mid-removal (every policy path gone, directory
            # still there) is one line, not one DELETED per file; GONE-ROOT
            # follows once the directory goes. Never the main tree.
            lines.append("ROOT-REMOVED %s (%d policy files)" % (safe(rr), len(old)))
            base["roots"][rr] = cur
            continue
        for rel in sorted(set(old) | set(cur)):
            o, c = old.get(rel), cur.get(rel)
            if o and c and o[2] == c[2]:
                continue
            if o and c:
                kind, detail = "CHANGED", "%s -> %s" % (o[2][:8], c[2][:8])
            elif c:
                kind, detail = "ADDED", c[2][:8]
            else:
                kind, detail = "DELETED", o[2][:8]
            shown = safe(rel if rr == "." else rr + "/" + rel)
            np = os.path.normcase(os.path.realpath(os.path.join(root, rel)))
            hit = next((k for k, p in ledger if p == np and k not in matched), None)
            peer = None if hit else next(
                ((k, s) for k, p, s in peers if p == np and k not in matched), None)
            if hit:
                matched.add(hit)
                lines.append("granted %s %s (%s)" % (kind, shown, detail))
            elif peer:
                matched.add(peer[0])
                lines.append("PEER-GRANTED %s %s (%s) sid=%s" % (kind, shown, detail, safe(peer[1])))
            elif c and on_master(root, rel, c[2]):
                lines.append("MERGED %s %s (%s)" % (kind, shown, detail))
            else:
                ungranted += 1
                lines.append("UNGRANTED %s %s %s" % (kind, shown, detail))
        base["roots"][rr] = cur
    for rr in list(base["roots"]):
        if rr not in now:
            del base["roots"][rr]
            lines.append("GONE-ROOT %s" % safe(rr))
    base["roots"].update(new_roots)
    base["matched"] = sorted(matched)
    if not lines:
        # nothing moved: hand the claim back by rename, no new file on disk
        # (a file create per call is what an on-access scanner charges for)
        hand_back(claim, bp)
        return
    if not os.path.exists(claim):
        # Held past the 30 s recovery line, and a peer recovered the claim
        # and compares from the same baseline. Writing the baseline here would
        # race the peer's and could spend a credit twice; dropping these lines
        # loses any difference the peer no longer sees.
        # So write no baseline and log every line. A credit matched here is not
        # recorded, so its line reads UNGRANTED: a duplicate, never a loss.
        lines = [re.sub(r"^(granted|PEER-GRANTED) (.*)$",
                        r"UNGRANTED \2 (claim lost; credit not recorded)", l)
                 for l in lines]
        ungranted = sum(1 for l in lines if l.startswith("UNGRANTED "))
        log_line("claim recovered by a peer after 30 s; baseline not written, "
                 "%d line(s) follow" % len(lines))
    else:
        try:
            write_baseline(bp, base)
        finally:
            try:
                os.unlink(claim)
            except OSError:
                pass
    for l in lines:
        log_line(l)
    if ungranted:
        print(json.dumps({"systemMessage":
            "policy-integrity: %d UNGRANTED policy-path change(s) recorded in "
            ".agent-log. The bytes already changed; nothing was "
            "prevented. If you did not authorize this, say so." % ungranted}))


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return
    sid = re.sub(r"[^A-Za-z0-9_-]", "", str(data.get("session_id") or ""))
    if not sid:
        return
    ev = data.get("hook_event_name") or ""
    src = data.get("source") or ""
    if ev == "SessionStart" or (not ev and src):
        if src not in ("startup", "resume"):
            return
        if os.path.exists(baseline_path(sid)):
            # review-02 F3: a resume (same session id) with a baseline already
            # on disk COMPARES instead of re-taking; re-taking would absorb any
            # change a skipped or crashed compare left unrecorded
            compare(sid, _is_policy())
        else:
            take_baseline(sid, _is_policy(), src)
        return
    if (data.get("tool_name") or "") not in WRITERS:
        return
    compare(sid, _is_policy())


if __name__ == "__main__":
    try:
        main()
    except Exception as e:      # PostToolUse: never block, never crash loud
        log_line("hook error: %s" % safe(str(e)))
    sys.exit(0)
