# policy-mutate — PreToolUse Bash|PowerShell|Edit|Write|NotebookEdit.
# Single job: block MUTATIONS touching policy paths; read-only naming
# passes (the earlier version friction fix — `wc -c CLAUDE.md` walks free). Unlock is
# `auth-policy <path>` typed by the human in its own user turn (armed by
# policy-prompt.py, honoured here — every allowed mutation is logged). A
# grant with `mode: "task"` covers its named
# paths for every mutation until a new session, `revoke-policy`, a new
# unlock, or 8 h; a grant without `mode` is a legacy one-shot (30 min).
# Shares write_targets with shell-scope.py: one predicate, two gates.
# Codex mirror files (~/.codex/*) are out-of-tree — filetool/shell-scope
# already gate that boundary; the prose hard stop carries the rest.
import importlib.util
import json
import os
import re
import sys
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = (os.environ.get("HARNESS_ROOT") or os.environ.get("CLAUDE_PROJECT_DIR")
        or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
NROOT = os.path.normcase(os.path.realpath(ROOT))
UNLOCK = os.path.join(ROOT, ".agent-log", "policy-unlock.json")

try:
    _spec = importlib.util.spec_from_file_location(
        "shellscope", os.path.join(HERE, "shell-scope.py"))
    ss = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(ss)
except Exception:
    ss = None      # 66: fail closed at the call site, never crash open

try:
    _spec = importlib.util.spec_from_file_location(
        "unlockconsume", os.path.join(HERE, "unlock_consume.py"))
    uc = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(uc)
except Exception:
    uc = None      # absent = never cloud-off, stays live

S = os.sep
CL = ".claude" + S
G = ".git" + S


def is_policy(np):
    # The ROOT half of the compare has to fold with everything below it.
    # `np` is normcase'd, and normcase folds case on Windows ONLY -- on POSIX it
    # is the identity, which is the very checkout `rel` is folded for:
    # Claude Code on Linux over a bind mount of a case-insensitive host volume,
    # or macOS on APFS. There a differently-cased ROOT prefix names the same real
    # file, and this compare returned False before one rule below ever ran, so
    # the rule folding never got the chance to matter. Both sides lower together and
    # `rel` is sliced from the LOWERED string, so the slice stays aligned even
    # where lowering changes a string's length.
    low, nlow = np.lower(), NROOT.lower()
    if not (low == nlow or low.startswith(nlow + S)):
        return False
    # .lower() wholesale because `np` is normcase'd and normcase folds case
    # only on Windows -- on POSIX it is the identity. Every rule folds, not just the three uppercase basenames.
    # The bypass was live in exactly the checkout a gate must protect: Claude
    # Code on Linux over a bind mount of a case-insensitive host volume (or
    # macOS on APFS), where `.CLAUDE/hooks/x` IS the real file and the old
    # unfolded prefix compare let it through. On a case-sensitive tree the
    # other spelling is a different file nothing loads; over-gating it costs
    # one refused edit. The `Scripts/`-vs-`scripts/` distinction the old comment
    # defended survives on a CASE-SENSITIVE host only: that family is
    # existence-gated on the unfolded `np`, so there a spelling naming no file
    # returns False. On Windows `os.path.exists` folds too, so `Scripts/` at a
    # checkout root gates exactly like `scripts/` -- measured 2026-09-09, and
    # the reason the walk below is anchored instead of running every tail.
    rel = low[len(nlow) + 1:]
    if not rel:
        return False
    # Codex reads AGENTS.override.md in place of AGENTS.md.
    if os.path.basename(rel) in ("claude.md", "agents.md", "agents.override.md"):
        return True
    if rel == "readme.md":                       # root README only
        return True
    # Every rule below tests a path SHAPE, not a location, so each one
    # runs against every CHECKOUT ROOT in `rel` -- the tree root, and any
    # `worktrees/<n>/` under it -- plus `.claude/` inside one, which is where
    # this tree's skills actually live. Anchoring only at the tree root left the
    # same files ungated one directory down, in two ways that are
    # one defect. `worktrees/<lane>/.claude/**` mutated with no grant --
    # measured on a lane worktree, where an auth-policy-batch over 6
    # lane paths reported 4 one-shots still unspent when it was replaced while
    # all 6 files had been edited; only the two `CLAUDE.md` entries spent,
    # because the basename rule was the one rule already depth-independent.
    # The skills/scripts/templates family named a ROOT `skills/` and a root
    # `templates/` that have never existed in this tree -- the real skills are at
    # `.claude/skills/` -- so that clause protected no real file at all, while
    # CLAUDE.md §2 named it. One anchored walk closes both, because both are the
    # same shape failing to survive a different prefix or a different root.
    # ANCHORS, not every tail: walking EVERY
    # component-aligned tail gates every directory merely SPELLED `scripts`,
    # `skills` or `templates`, and since `os.path.exists` folds case on Windows
    # that included `projects/<bot>/.venv/Scripts/*` -- the runtime
    # of a project's own runtime -- at deny tier, one typed
    # one-shot per file. Measured over the ON-DISK tree (every path, the only
    # measurement that can see any of this; `git ls-files` lists tracked paths
    # only and shows 6 either way): every-tail newly gates 3,116, of which 111
    # are collateral outside any checkout; anchored newly gates 3,005 -- the
    # same 2,998 worktree files and 7 `.claude/skills/` files, and
    # zero collateral. Neither loses a path the pre-fix gate denied.
    # `readme.md` above stays root-only on purpose -- every other README.md in
    # the tree is ordinary prose.
    parts = rel.split(S)
    roots = [i for i in range(len(parts))
             if i == 0 or (i >= 2 and parts[i - 2] == "worktrees")]
    anchors = roots + [i + 1 for i in roots if parts[i] == ".claude"]
    for i in anchors:
        tail = S.join(parts[i:])
        if tail.startswith((CL + "hooks" + S, CL + "agents" + S, ".codex" + S)):
            return True
        # The tracked
        # pre-push hook sources. `.githooks/` IS the live hook -- the main
        # tree's core.hooksPath names it -- and `tools/git-hooks/` is the
        # dispatcher's source; neither was here, so both mutated ungranted and
        # a lane PR touching them would have auto-merged. Checkout ROOTS only,
        # not the `.claude/` anchor: git loads hooks from no path under it.
        if i in roots and tail.startswith((".githooks" + S,
                                           "tools" + S + "git-hooks" + S)):
            return True
        # Role definitions and the grill and lane graphs bind delegates and
        # the hub as much as an agent definition does. Checkout roots only.
        if i in roots and tail.startswith(("roles" + S, "graphs" + S)):
            return True
        if (tail.startswith(CL + "settings") and tail.endswith(".json")
                and S not in tail[len(CL):]):
            return True
        if tail == CL + "keybindings.json":
            return True
        # The goals file is the ONLY
        # counterweight to the tree's self-improvement drive -- the hub
        # reads it as its agenda -- and it sat in the freely-writable inner
        # core while claiming operator-only authorship. A session that wants
        # machinery work could rewrite the standard it is judged by, silently.
        # Gated by exact tail, not a `goals/` prefix: the directory also holds
        # ordinary machinery prose, and over-gating that costs refused edits
        # for no protection.
        # `rel` is case-folded above, so this tail is lowercase like every
        # other rule here -- spelled "OBJECTIVES.md" it silently never fires.
        if tail == "goals" + S + "objectives.md":
            return True
        if tail == G + "config" or tail.startswith(
                (G + "hooks" + S, G + "info" + S, G + "refs" + S)):
            return True
        for d in ("skills", "scripts", "templates"):
            # edits to EXISTING files only; creating new ones is normal Write
            if tail.startswith(d + S) and os.path.exists(np):
                return True
    return False


def is_grant(np):
    """The gate's own authorization state, by filename shape.

    This was an ENUMERATED stem regex, so every new unlock verb shipped
    FORGEABLE until someone remembered to hand-add its stem. A `browse` verb
    was added as the third; on 2026-09-08 a `use` verb shipped unsealed and a
    Write to `.agent-log/use-unlock-<sid>.json` passed. Twice in production is
    the argument for a shape instead of a list: any `*-unlock*.json` here is a
    grant, and the next ADR does not have to remember this file.

    The gate design rules out a shared stem module -- no
    dispatcher, no shared predicate between gates. It is not needed. The seal
    lives only in this hook, and a generic shape needs nothing from
    policy-prompt.py, so the forbidden coupling never has to exist.

    The directory compare folds for the ROOT-casing reason above, and here the stakes are worse
    than in is_policy: a grant the seal misses on casing is one `open()` the
    consumer finds on the same case-insensitive mount, which re-opens grant forgery by
    spelling alone.
    """
    return (os.path.dirname(np).lower()
            == os.path.join(NROOT, ".agent-log").lower()
            and re.fullmatch(r"[A-Za-z0-9_-]+-unlock(-[A-Za-z0-9_-]*)?\.json",
                             os.path.basename(np)) is not None)


def targets_from(data):
    tool = data.get("tool_name") or ""
    ti = data.get("tool_input") or {}
    if tool in ("Edit", "Write", "NotebookEdit"):
        p = ti.get("file_path") or ti.get("notebook_path")
        if not p:
            return []
        if not os.path.isabs(p):
            p = os.path.join(data.get("cwd") or "", p)
        return [(p, os.path.normcase(os.path.realpath(p)))]
    cmd = ti.get("command") or ""
    if not cmd:
        return []
    if ss is None:
        # The guard sits at the ONE call site that needs the sibling, so it
        # covers every tool name by construction -- a whitelist in main() misses
        # any third tool that carries a command and crashes open on None, which
        # is the failure this closes. The file-tool branch returned above, so a
        # broken shell-scope never locks the operator out of repairing it.
        deny("shell-scope predicate failed to load -- cannot verify whether "
             "this command touches a policy path; refusing rather than "
             "passing it ungated.")
    # Raw, newlines intact. write_targets strips heredoc bodies first and
    # flattens after; flattening here destroyed the introducer's line end and
    # made a markdown blockquote in a body read as a redirect, at deny tier.
    return ss.write_targets(cmd, data.get("cwd") or "")


def deny(reason):
    # The six deny sites recorded nothing. Measured 2026-09-20 over the whole
    # .agent-log: 233 `unlock-consumed` lines and ZERO denials, so the audit saw
    # every grant spent and no attempt ever turned away. NOT `unlock-refused` --
    # policy-prompt.py owns that name for a refused GRANT (160 lines); this is a
    # refused MUTATION, the record that an agent attempted a gated write.
    # Flattened and truncated: reasons run to several lines and a raw newline
    # would split one event across log lines (the \r lesson, log-escape.sh:34).
    log_line("mutation-denied: " + " ".join(reason.split())[:200])
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": "policy-mutate: " + reason,
    }}))
    sys.exit(0)


def log_line(msg):
    try:
        d = os.path.join(ROOT, ".agent-log")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, time.strftime("%Y-%m-%d") + ".md"),
                  "a", encoding="utf-8") as f:
            f.write("- %s [policy-mutate] %s\n"
                    % (datetime.now().strftime("%H:%M:%S"), msg))
    except Exception:
        pass


def main():
    # Cloud-off under the
    # marker -- the replacement is policy-integrity's own record (unaffected,
    # separate hook, still fires) plus an operator-merged PR as the real
    # authorization; on cloud every policy change reads UNGRANTED by
    # construction (policy-prompt.py says so). Windows unchanged
    # (uc.cloud_boundary() reads None there, always -- see its docstring).
    if uc is not None and uc.cloud_boundary():
        sys.exit(0)
    try:
        data = json.load(sys.stdin)
    except Exception:
        deny("unreadable hook input — cannot verify targets")
    targets = targets_from(data)

    # SEALED — no unlock exists, and none can. The gate's CODE was a policy path
    # while the gate's STATE was an ordinary in-tree file: the grant matched no
    # branch of is_policy() and filetool-scope allows anything under the root, so
    # an agent could write itself a well-formed grant and then mutate CLAUDE.md,
    # the settings, or these hooks with no human turn anywhere in the chain —
    # authorization forged by the party it authorizes.

    # An unlock here would be circular: the grant authorizing a write to the
    # grant is a grant. So this is a never-item, like the git operations that
    # have no unlock either. Both channels, because targets_from resolves file
    # tools and shell redirects alike — sealing one would leave the same effect
    # one tool over, which is this tree's twice-recorded failure shape.

    # LIMIT, stated because green tests must not imply more than they prove:
    # this gate sees tool calls. A python script that opens the file directly is
    # not a tool call, and writing to `.agent-log/` from code is sanctioned
    # (an in-tree tool may do it). The direct route is closed and auditable; the concept is
    # mitigated, not eliminated: grant forgery remains a residual.
    sealed = [t for t, np in targets if is_grant(np)]
    if sealed:
        deny("'%s' is the gate's own authorization state — sealed, with no "
             "unlock. A grant authorizing a write to the grant would be "
             "circular. If this was not deliberate, say so rather than routing "
             "around it." % sealed[0])

    hits = [(t, np) for t, np in targets if is_policy(np)]
    if not hits:
        sys.exit(0)
    # A grant belongs to the session that armed it. One global slot, opened "w",
    # let a second session in this tree destroy the operator's grant 21 seconds
    # after they typed it on 2026-08-24. The sharper half was that
    # consumption matched on normalized path alone with no session identity, so
    # two sessions touching one protected path could spend each other's grants.
    # The session-keyed FILENAME carries that identity: reading a grant named for
    # this session is proof this session armed it.

    # With a real session present, ONLY the session-keyed grant is read. The
    # unkeyed slot was a forger's landing pad -- a forger cannot name the keyed
    # file, so a slot that is never read leads nowhere however the file got
    # there -- and the transition the fallback guarded is complete, since
    # policy-prompt.py:91-98 keys every policy grant it arms.

    # session_id is a guaranteed field on this payload, confirmed against the
    # published hook documentation. It is scrubbed to path-safe characters
    # anyway: it reaches the filesystem as a filename, which makes it a trust
    # boundary regardless of how well-behaved the harness is.
    sid = re.sub(r"[^A-Za-z0-9_-]", "", data.get("session_id") or "")
    keyed = os.path.join(ROOT, ".agent-log", "policy-unlock-%s.json" % sid)
    # A broken grant is not an absent one (F3). `except Exception: continue`
    # collapsed absent / corrupt / unreadable into one state and answered all
    # three by reaching for the shared unkeyed slot — which is precisely the
    # cross-session grant-spending the session keying exists to prevent, and the
    # arming side's truncate-then-write window is what manufactures the partial
    # file. Fail-closed here matches `deny` on unreadable hook input twenty lines
    # above; the two had opposite defaults for the same class of failure.

    # Narrowing the `except` is NOT sufficient on its own. A grant that is valid
    # JSON but not an object, and truthy (`[1,2]`, `"x"`, `42`), made
    # `u.get("used")` raise: the hook exited 1, and a PreToolUse hook exiting
    # non-zero other than 2 is non-blocking, so the mutation PROCEEDED. The gate
    # crashed open. Probed 2026-08-24, all four shapes. `[]` and `null` are falsy
    # and deny safely, which is why a first probe using `[]` looked like a
    # refutation. Hence the explicit isinstance deny rather than a tighter catch.
    u, grant = None, None
    # The `else [UNLOCK]` arm fires only when sid scrubs to empty -- a payload
    # shape the comment above calls non-real -- and is kept because being wrong
    # there is unrecoverable: with no consumable grant, the edit repairing this
    # file needs a grant it cannot get. The arming side writes the unkeyed name
    # for that same shape, so the two stay consistent.
    for cand in ([keyed] if sid else [UNLOCK]):
        try:
            with open(cand, encoding="utf-8") as f:
                u = json.load(f)
        except FileNotFoundError:
            continue            # absent: the next name may still hold a grant
        except Exception:
            u = None            # present but unreadable: fail closed below
        if not isinstance(u, dict):
            deny("'%s' exists but is not a readable grant. A half-written grant "
                 "is not an absent one, and falling through to the shared slot "
                 "would spend another session's authorization. Delete it, then "
                 "submit 'auth-policy' again." % os.path.basename(cand))
        grant = cand
        break
    # A grant stamped in the FUTURE is forged, not fresh -- the old check
    # bounded only the upper side, so `now - epoch` going negative passed as
    # fresh and a grant dated any distance ahead never expired. Arming and
    # consuming run on the same host, so the 60s is slack for sub-second
    # ordering, not real tolerance. The isinstance conjunct is part of the same
    # chain, not a restructuring: a non-numeric epoch would otherwise raise
    # TypeError, and rc 1 is NON-blocking, so that crash would be a crash OPEN.
    # Both conjuncts sit inside the existing short-circuit, so a spent or absent
    # grant still denies at `not u.get("used")` without touching the arithmetic.

    # A grant is a LIST of one-shots. `auth-policy-batch` writes an `entries`
    # array; the flat single-path shape is that list with one element, so the
    # normalization below is the ONLY new concept and every branch is the old
    # behaviour at N=1. `entries` is read defensively for the same reason the
    # isinstance checks above exist: a malformed grant must refuse, never raise,
    # because rc 1 on a PreToolUse hook is a crash OPEN.

    # Grant lifetime (session id, revoke, 8h cap): a grant carrying `mode: "task"` is TASK-LIVED. Its entries are
    # never marked used -- every distinct hit still has to equal some entry's
    # norm, but the entry survives the mutation -- and its window is 8 h, not
    # 30 min. It ends when a new session starts (the sid is in the filename),
    # when the operator types `revoke-policy` (policy-prompt.py deletes the
    # file), when a new unlock replaces it, or at the cap. A grant WITHOUT
    # `mode` is a legacy one-shot and keeps every rule below unchanged, so a
    # grant armed before this hook landed reads as it was written. The pool
    # filter is the same for both: no writer marks a task entry used, so a
    # `used` task entry is a foreign shape and refusing it costs nothing
    # (S2-3, SE R1 -- the `task or` conjunct here was dead).

    # Hits are deduped by normalized path BEFORE matching. One mutation naming the
    # same protected file twice (two shell redirects, say) is one authorization,
    # which is exactly what the old `all(np == u.get("norm"))` granted; spending an
    # entry per raw hit instead would have silently narrowed the single-path verb.
    task = isinstance(u, dict) and u.get("mode") == "task"
    limit = 28800 if task else 1800
    ents = u.get("entries") if isinstance(u, dict) else None
    if not isinstance(ents, list):
        ents = [u] if isinstance(u, dict) else []
    pool = [e for e in ents if isinstance(e, dict) and not e.get("used")]
    spend, covered = [], True
    for np in dict.fromkeys(np for _, np in hits):
        i = next((j for j, e in enumerate(pool) if e.get("norm") == np), None)
        if i is None:
            covered = False
            break
        spend.append(pool.pop(i))
    if (u and covered and spend
            and isinstance(u.get("epoch"), (int, float))
            and -1e12 < u["epoch"] < 1e12   # A bigger int overflows the float math
            and -60 <= time.time() - u["epoch"] < limit):
        if not task:
            # LEGACY ONE-SHOT ONLY. Second spend site, atomic
            # rename by operator ruling: CLAIM the grant by rename, re-read and
            # compare by parsed value, write the spent copy beside it, swap it
            # in. The live path is never truncated, so a crash mid-spend never
            # leaves a partial grant, and two racing hooks cannot both roll
            # the `entries` array back over each other's spend. This is the
            # mechanism of unlock_consume.py:65-103, inlined rather than
            # imported because consume() spends a grant whole and a batch
            # grant is N one-shots. Same Windows caveat as there: a losing
            # os.replace can report success having moved nothing, so
            # exclusivity rests on the re-read, not the rename. A task grant
            # spends nothing, so it never enters here.
            claim = "%s.claim.%d" % (grant, os.getpid())
            spent = "%s.spent.%d" % (grant, os.getpid())
            try:
                os.replace(grant, claim)
                with open(claim, encoding="utf-8") as f:
                    if json.load(f) != u:
                        raise ValueError("grant changed between the checks and the claim")
                for e in spend:
                    e["used"] = True
                with open(spent, "w", encoding="utf-8") as f:
                    json.dump(u, f)
                os.replace(spent, grant)
            except Exception:
                try:
                    os.replace(claim, grant)   # 65: spend not persisted = re-armed
                except Exception:
                    pass
                # If the spend cannot be persisted the one-shot is unspent and
                # re-usable for the rest of the window, and rc 1 is non-blocking, so
                # crashing here would let the mutation through. Refuse instead.
                # Wording claims only what was checked: the
                # failure may sit at the claim, the compare, the write or the
                # swap, and the restore above may itself have failed -- so the
                # grant's presence is reported from disk, not assumed.
                state = ("is intact" if os.path.exists(grant)
                         else "is ABSENT -- an unspent copy may sit in '%s'"
                              % os.path.basename(claim))
                deny("the spend of '%s' could not be persisted -- refusing the "
                     "mutation rather than leaving a one-shot unspent. The grant "
                     "%s. Submit 'auth-policy' again."
                     % (os.path.basename(grant), state))
            try:
                os.unlink(claim)     # after the swap, in its own try: a failure here
            except Exception:        # must never restore the pristine grant over
                pass                 # the spent one -- that would BE the double-spend
        # ONE LINE PER DISTINCT HIT PER ALLOWED CALL. policy-prompt.py
        # declares the armed-vs-consumed line count load bearing (a defect was
        # found by comparing those counts), and a comma-joined line broke it by
        # logging one line for two spends. This gate decides before the tool
        # runs and cannot see bytes, so a HIT is what it can log: an allowed
        # call that then changes nothing (same-content Write, `sed -i` with no
        # match) leaves a spare line. policy-integrity reads each line as one
        # credit for one difference on that path, and voids it at grant end
        # (S2-1: a credit counts only after this sid's latest policy-prompt
        # arm/revoke marker and until 8 h from that arming), so a spare
        # cannot outlive the grant that minted it.
        for e in spend:
            log_line("unlock-consumed: %s sid=%s" % (e.get("path"), sid))
        sys.exit(0)
    rel = os.path.relpath(hits[0][1], NROOT)
    # An expired grant read exactly like no grant, so an aged-out batch
    # looked like a broken hook. Inline, as the spend above is: this hook does
    # not import unlock_consume. Guarded so nothing here can raise (rc 1 is a
    # crash OPEN): isinstance on the epoch, and the upper bound keeps int()
    # off an infinite age.
    note = ""
    if (isinstance(u, dict) and isinstance(u.get("epoch"), (int, float))
            and -1e12 < u["epoch"] < 1e12):   # review F1: 10**400 overflows
        age = time.time() - u["epoch"]
        if limit <= age < 10 ** 9:
            note = (" A grant exists but EXPIRED %d min ago (grants last %s); "
                    "the hook is working."
                    % (int((age - limit) // 60), "8 h" if task else "30 min"))
    deny("'%s' is a policy path. Submit 'auth-policy %s' as its own user "
         "message, then retry the mutation. That arms a task unlock for the "
         "named path: every mutation of it is allowed until a new session, "
         "'revoke-policy', a new unlock, or 8 h. For several paths at once: "
         "'auth-policy-batch <p1> ... <p8>', which covers the named paths "
         "only, never a blanket unlock." % (hits[0][0], rel) + note)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # The rc-1-is-a-crash-OPEN sites above were closed one at a time;
        # this closes the rest. A crash denies instead of passing the call.
        deny("crashed (%s) -- refusing rather than passing the call ungated" % type(e).__name__)
