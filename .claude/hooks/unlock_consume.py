# unlock_consume — the one hardened one-shot grant consumption predicate,
# shared by net-post.py and env-global.py. The semantics are
# ported from policy-mutate.py:182-233, which is the spec:
#   - a grant that is valid JSON but not an object ([1,2], "x", 42) is
#     REFUSED, never crashed on: u.get() raising exits the hook 1, and a
#     PreToolUse exit 1 is NON-blocking, so a crash here is a crash OPEN;
#   - freshness is bounded on BOTH sides (-60 <= age < max_age): a
#     future-stamped grant has negative age and the old `age >= 1800` check
#     never expires it (69). Arming and consuming run on the same host, so
#     -60s is slack for sub-second ordering, not real tolerance. A
#     non-numeric epoch is refused via isinstance, never allowed to raise —
#     69's drafted fix was ruled regressive for exactly that crash;
#   - the spend-write is guarded (65): if the spend cannot be persisted the
#     one-shot stays unspent and re-usable, so a failed write means NOT
#     consumed and the gate still denies. The spend is an atomic rename (167,
#     an operator ruling), so the live grant path is never truncated and never
#     partial. Recovery is still re-arming: a kill between the claim and the
#     swap orphans `<grant>.claim.<pid>` holding an UNSPENT grant, and a failed
#     swap orphans `<grant>.spent.<pid>`; nothing reads either name;
#   - the spend CLAIMS the grant before writing it. MEASURED: no round of
#     7,500 racing rounds produced two winners. NOT ESTABLISHED: why. On Windows a
#     losing os.replace does not reliably raise -- it often reports SUCCESS
#     having moved nothing -- so exclusivity does NOT rest on the rename. It
#     rests on the re-read in consume(): a racer holding no file cannot open it,
#     and every failure there is a refusal. Do not restate this as "the loser's
#     rename raises"; that was measured false. Not a security property either --
#     that the grant file is agent-writable and forgeable, was CANCELLED and
#     stands.
#   - `spend=False` (a retired browse window; no caller
#     since 2026-09-21) runs every
#     check and returns the grant WITHOUT claiming it: a window was held open
#     for its lifetime, not spent by its first use. Its closer in
#     policy-prompt.py went with it, so a spend=False grant now lives until
#     `max_age` (default 1800s; that caller passed 300s).
# Consumers load this via the policy-mutate.py:22-28 importlib pattern and
# treat a load failure as "unlock absent" — fail closed at the call site,
# never crash open. This module never logs: each consumer
# writes its own unlock-consumed line under its own tag. The net/env slots
# stay UNKEYED — policy-prompt.py:100-104 owns that ordering rule; no
# session keying here.
import json
import os
import time


def cloud_boundary():
    """Which cloud boundary, if any, is
    observable in THIS hook process's own environment right now -- 'managed',
    'selfhost', or None. The marker is trusted only together with this read:
    on managed, CLAUDE_CODE_REMOTE is set by the platform outside any tool
    call's environment; on self-hosted, HARNESS_BOUNDARY comes from the
    container's own environment (the image's ENV, set before Claude
    launches). On Windows this always returns None: a
    transient `$env:X=` or `export X=` inside one tool call sets the
    variable in that tool's OWN subprocess only (env-global.py lets such
    per-call assignments pass BY DESIGN, which is exactly why they cannot
    reach here) -- hooks are spawned by the harness process, whose
    environment is fixed at launch. The only routes into the harness's own
    env are a persisted global change (setx/registry -- env-global's gated
    domain) or the `env` block of `.claude/settings.json` (a policy path).
    Shared here per unlock_consume's existing role (net-post.py, env-global.py
    already import it): a second predicate module would be the shared-module
    class the gate design rules out; this file is the one exception the tree already
    keeps, so the marker predicate rides it rather than opening a second one."""
    if os.environ.get("CLAUDE_CODE_REMOTE") == "true":
        return "managed"
    if os.environ.get("HARNESS_BOUNDARY") == "selfhost":
        return "selfhost"
    return None


def stale_note(path, max_age=1800):
    """Why did the grant at `path` refuse? A clause to append to a refusal
    reason, or "" when there is nothing useful to add. An aged-out
    grant and no grant at all gave the identical string, and a session spent
    a diagnosis deciding the hook was broken.

    Read-only and advisory: callers run it only AFTER a refusal is decided,
    so it cannot turn a refusal into an allow, and it touches nothing
    consume() does. Never raises -- a raise in a PreToolUse hook is rc 1, a
    crash OPEN -- hence the outer except."""
    try:
        try:
            with open(path, encoding="utf-8") as f:
                u = json.load(f)
        except Exception:
            return ""                # absent: the caller's wording is right
        if not isinstance(u, dict) or not isinstance(u.get("epoch"), (int, float)):
            return " (a grant file exists but is malformed)"
        if u.get("used"):
            return " (the grant at that path was already spent)"
        age = time.time() - u["epoch"]
        if age >= max_age:
            return (" (a grant exists but EXPIRED %d min ago -- grants last %d min;"
                    " the hook is working, type the unlock again)"
                    % (int((age - max_age) // 60), int(max_age // 60)))
        if age < -60:
            return " (a grant exists but its epoch is in the future)"
        return ""                    # fresh and unspent: it failed `match`
    except Exception:
        return ""


def consume(path, match=None, spend=True, max_age=1800):
    """Try to spend the one-shot grant at `path`. Returns the grant dict if
    it was well-formed, unspent, fresh, matching, and its spend was
    persisted; else None. With spend=False the same checks run and the
    grant is returned untouched. Never raises: every failure shape is a
    refusal, because the callers are PreToolUse hooks where an uncaught
    exception is a fail-open."""
    try:
        with open(path, encoding="utf-8") as f:
            u = json.load(f)
    except Exception:
        return None          # absent or unreadable: no grant to spend
    if not isinstance(u, dict):
        return None          # 64's class: truthy non-dict must refuse
    if u.get("used"):
        return None
    if not isinstance(u.get("epoch"), (int, float)) or not -1e12 < u["epoch"] < 1e12:
        return None          # 69: junk epoch is refused, never arithmetic'd;
                             # An int too big for a float raises below
    if not (-60 <= time.time() - u["epoch"] < max_age):
        return None          # 69: bounded both sides
    if match is not None:
        try:
            if not match(u):
                return None
        except Exception:
            return None      # a predicate crashing on grant data is a refusal
    if not spend:
        return u             # A window is checked, never claimed
    # CLAIM the grant by an atomic rename, then verify that what was
    # claimed is still what was checked. BOTH halves are load-bearing, and the
    # obvious reading of this code is WRONG: on Windows a losing os.replace
    # frequently returns SUCCESS having moved nothing, so a claim that did not
    # raise is NOT proof of holding the grant. Exclusivity comes from the
    # re-read below -- a racer holding nothing cannot open it, and every failure
    # here is a refusal -- plus the comparison, which rejects the racer that
    # claims AFTER the winner swapped its spent copy back (without it, 3 of 8
    # racers still won). The comparison is by PARSED VALUE, not bytes: key
    # order and 1-vs-1.0 compare equal. The <=1 bound is measured and the
    # mechanism is only partly explained -- do not restate it as "the loser's
    # rename raises", which was measured false. Both temp names sit
    # in the grant's OWN directory: os.replace is atomic only within one volume.
    claim = "%s.claim.%d" % (path, os.getpid())
    try:
        os.replace(path, claim)
    except Exception:
        return None          # already claimed, absent, or locked: refuse
    spent = "%s.spent.%d" % (path, os.getpid())
    try:
        with open(claim, encoding="utf-8") as f:
            if json.load(f) != u:
                raise ValueError("grant changed between the checks and the claim")
        u["used"] = True
        with open(spent, "w", encoding="utf-8") as f:
            json.dump(u, f)
        os.replace(spent, path)      # the live grant path is never truncated
    except Exception:
        try:
            os.replace(claim, path)  # 65: spend not persisted = grant re-armed
        except Exception:
            pass
        return None
    try:
        os.unlink(claim)     # AFTER the spend, in its own try: a failure here
    except Exception:        # must never restore the pristine grant over the
        pass                 # spent one -- that would BE the double-spend
    return u
