# policy-prompt — UserPromptSubmit. Arms the unlocks when the HUMAN types
# them in their own turn — the only channel that can arm. Agent text can
# reach this hook through a function-hook plugin's prompt, so a payload whose
# `source` says it did not come from the composer arms nothing (see
# main()). Four vocabularies:
#   auth-policy <path>  -> policy-unlock.json  (honoured by policy-mutate): a
#                          TASK grant covering the path for every mutation
#                          until a new session, revoke-policy, a new unlock, or 8 h
#   auth-policy-batch <p1>..<p8> -> the same file, one entry per path, the
#                          same task lifetime (never a blanket unlock)
#   revoke-policy       -> deletes this session's policy grant
#   auth-net <host>     -> net-unlock.json     (consumed by net-post, one-shot)
#   auth-env            -> env-unlock.json     (consumed by env-global, one-shot)
# Arm, revoke and consume all leave action-log lines. The POLICY arm line and
# every revoke line end in ` sid=<sid>`: policy-integrity reads them as this
# session's grant-end markers and voids every credit before the latest one.
# Net and env lines are unchanged.
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
LOGDIR = os.path.join(ROOT, ".agent-log")

try:
    _spec = importlib.util.spec_from_file_location(
        "unlockconsume", os.path.join(HERE, "unlock_consume.py"))
    uc = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(uc)
except Exception:
    uc = None      # absent = never cloud-off, stays live

TASK_LIFETIME = ("lasts until a new session, 'revoke-policy', a new unlock, "
                 "or 8 h from arming, whichever comes first")


def log_line(tag, msg, event="unlock-armed"):
    """One audit line. `event` defaults so every arming call stays byte-identical.

    A defect was found by counting `unlock-armed` lines against `unlock-consumed`
    lines in this log. Reformatting the armed line would quietly break the audit
    that caught the defect this file was repaired for, so the default is load
    bearing, not cosmetic. Task grants add ` sid=<sid>` at the END of the policy
    arm line's message; the prefix that count keys on is untouched.
    """
    try:
        os.makedirs(LOGDIR, exist_ok=True)
        with open(os.path.join(LOGDIR, time.strftime("%Y-%m-%d") + ".md"),
                  "a", encoding="utf-8") as f:
            f.write("- %s [policy-prompt] %s (%s): %s\n"
                    % (datetime.now().strftime("%H:%M:%S"), event, tag, msg))
    except Exception:
        pass


def policy_grant_name(sid):
    return os.path.join(LOGDIR, ("policy-unlock-%s.json" % sid) if sid
                        else "policy-unlock.json")


def arm(stem, sid, entry, tag, msg, event="unlock-armed", note=None):
    """Write the grant, named for the session that armed it when sid is given.

    One global slot opened "w" let a second session in this tree destroy the
    operator's grant 21 seconds after they typed it on 2026-08-24; and
    because the consuming side matched on path alone, two sessions touching one
    protected path could spend each other's grants. The filename carries the
    identity.

    sid is scrubbed to path-safe characters by the caller: it becomes a filename,
    which makes it a trust boundary however well-behaved the harness is.

    `event`/`note` let the browse window log and announce itself in its
    own words; no caller since 2026-09-21. The defaults keep every
    one-shot call byte-identical. The policy callers now pass
    `note`, because their grant is task-lived and the default text says one-shot.
    """
    os.makedirs(LOGDIR, exist_ok=True)
    entry.update(epoch=time.time(), used=False)
    fname = "%s-%s.json" % (stem, sid) if sid else stem + ".json"
    # F4: one grant slot per session is an established invariant, and
    # merging arms across messages would build exactly the accumulating blanket
    # unlock the contract forbids -- so truncating is RIGHT and stays. What was wrong was
    # the silence: arming any unlock after a batch discarded that batch's
    # unspent one-shots with no word to the operator, and the later denial reads
    # as an ordinary policy-path refusal rather than "your grant was replaced".

    # POLICY SLOT ONLY (D3). Read-before-truncate belongs in arm() -- it is the
    # same act at all four call sites, and the net/env slots are MORE exposed to
    # silent replacement, not less. The WORDING is what does not travel: it says
    # "one grant per session", and :140-144 keeps net and env deliberately
    # UNKEYED and shared across sessions; and it says "paths", and auth-env takes
    # none. Re-arming those two is an ordinary idempotent refresh. Only the
    # policy slot carries N paths that a replacement can quietly destroy.
    # A task grant's entries are never marked used, so `lost` is every
    # path the old grant still covered -- the count the operator needs either way.
    lost = 0
    if stem == "policy-unlock":
        try:
            with open(os.path.join(LOGDIR, fname), encoding="utf-8") as f:
                prior = json.load(f)
            old = prior.get("entries") if isinstance(prior, dict) else None
            if not isinstance(old, list):
                old = [prior] if isinstance(prior, dict) else []
            lost = sum(1 for e in old
                       if isinstance(e, dict) and not e.get("used"))
        except Exception:
            lost = 0      # absent or unreadable: nothing was there to lose
    with open(os.path.join(LOGDIR, fname), "w", encoding="utf-8") as f:
        json.dump(entry, f)
    log_line(tag, msg, event=event)
    print(note if note is not None else
          "policy-auth: one-shot %s unlock armed for %s (30 min)." % (tag, msg))
    if lost:
        log_line(tag, "replaced a grant that still covered %d path(s)" % lost,
                 event="unlock-replaced")
        print("policy-auth: this REPLACED an earlier grant that still covered "
              "%d path(s). One grant per session: re-submit any of those paths "
              "you still need." % lost)


def revoke(sid):
    """`revoke-policy` typed alone ends this session's task grant now.

    Deletes the session-keyed grant file -- the same file arm() writes and
    policy-mutate reads, so nothing else has to learn a new state. Counted
    before the unlink so the log says what was given up. Absent is not an
    error: the operator may revoke to be sure, and the line says so. Every
    line here ends in ` sid=<sid>` and is a grant-end marker for
    policy-integrity (S2-1): the credits before it stop counting, whichever
    branch ran -- voiding on a failed delete only tightens.
    """
    fname = policy_grant_name(sid)
    try:
        with open(fname, encoding="utf-8") as f:
            prior = json.load(f)
        ents = prior.get("entries") if isinstance(prior, dict) else None
        n = len(ents) if isinstance(ents, list) else 1
    except FileNotFoundError:
        log_line("policy", "nothing to revoke sid=%s" % sid, event="unlock-revoked")
        print("policy-auth: nothing to revoke -- this session holds no policy grant.")
        return
    except Exception:
        n = 0      # present but unreadable: delete it anyway, count unknown
    try:
        os.unlink(fname)
    except Exception as e:
        log_line("policy", "revoke FAILED: %s sid=%s"
                 % (" ".join(str(e).split())[:120], sid), event="unlock-revoked")
        print("policy-auth: could not delete the grant file (%s); it may still "
              "be live. Delete '%s' by hand." % (e, os.path.basename(fname)))
        return
    log_line("policy", "%d path(s) sid=%s" % (n, sid), event="unlock-revoked")
    print("policy-auth: task unlock revoked (%d path(s)); policy paths are "
          "gated again." % n)


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    prompt = data.get("prompt") or ""
    sid = re.sub(r"[^A-Za-z0-9_-]", "", data.get("session_id") or "")

    # On cloud a typed
    # auth-policy/auth-policy-batch grant arms NOTHING -- policy-mutate is
    # itself cloud-off there, so a grant would arm a gate nobody consumes;
    # on cloud every policy change reads UNGRANTED by construction, and the
    # operator-merged PR is the real authorization. The line says so, rather
    # than silently accepting and discarding the grant. Windows unaffected
    # (uc.cloud_boundary() reads None there, always). `revoke-policy`
    # takes the same exit -- there is no grant to revoke where none arms.
    cb = uc.cloud_boundary() if uc is not None else None
    if cb and re.match(r"\s*(auth-policy(-batch)?|revoke-policy)\b", prompt):
        log_line("policy", "typed grant arms nothing on %s -- policy paths "
                  "are UNGRANTED by construction; the merged PR is the "
                  "authorization" % cb,
                  event="unlock-refused")
        print("policy-auth: on this boundary (%s) a typed grant arms "
              "NOTHING, and there is nothing to revoke. Policy-path changes "
              "are never armed here -- every policy change reads UNGRANTED by "
              "construction; the operator-merged PR is the authorization." % cb)
        sys.exit(0)

    # Provenance: only the composer arms or revokes. Function-hook
    # plugins can put text on this channel -- `$.prompt.submit({ text,
    # asUser: true })` and a `prompt.submit` rewrite both run this hook -- so a
    # plugin the agent wrote could submit `auth-policy CLAUDE.md` itself. The
    # payload's `source` says who authored the prompt; anything but `user`
    # (sdk, system, wakeups, poll events) arms and revokes nothing. ABSENT
    # passes: the field is still rolling out, and refusing on absence would
    # lock the operator out of the gate that repairs this file. So this only
    # tightens where the harness reports provenance.
    src = data.get("source")
    if src is not None and src != "user" and re.search(
            r"(?:auth-(?:policy-batch|policy|net|env)|revoke-policy)(?![\w-])",
            prompt):
        shown = re.sub(r"[^\w-]", "", str(src))[:20]
        log_line("source", "prompt source %r is not the composer, armed nothing"
                 % shown, event="unlock-refused")
        print("policy-auth: armed nothing - this prompt did not come from the "
              "composer (source=%r). Unlocks and revokes must be typed by the "
              "human." % shown)
        sys.exit(0)

    # Occupancy: the message must BE the instruction, never merely contain it.
    # CLAUDE.md §2 already says "from a new user turn" and policy-mutate's own
    # denial says "as its own user message" — neither was enforced here. A search
    # anywhere in the message cannot tell the human INSTRUCTING an unlock from
    # text MENTIONING one. Arming is trusted because only the composer can arm
    # (non-composer sources are refused above), but the human's message routinely
    # carries text the human did not
    # author: pasted logs, diagnostic output, documentation. That is untrusted
    # text reaching the authorization layer through the trusted one.

    # The sharpest case was self-inflicted: the denial prints the exact path and
    # instructs the human to submit it, so pasting it back guaranteed a matching,
    # consumable grant. Confirmed by probe 2026-08-24 — a sentence
    # merely describing the syntax armed a grant whose normalized path pointed at
    # the real protected file, and a sentence FORBIDDING it armed one too.
    # FIXED by the occupancy rule above — the probe records a CLOSED hole, not
    # live behaviour: a message merely containing the verb arms nothing now.


    # Deliberately NOT added: a check that the captured path exists. A protected
    # path is protected before it exists, and requiring existence would have
    # blocked the 2026-08-24 unlock that named a hook file in order to create it.
    # Residuals are asserted in tests/test_policy_prompt.py, not left
    # silent: a lone placeholder still arms, and is unconsumable, which is noise.
    one_arg = r'\s*%s\s+[`\'"]?([^\s`\'"]+)[`\'"]?\s*'

    armed = False

    # Revocation obeys the same occupancy rule as arming -- the message
    # IS `revoke-policy`, or it revokes nothing (a pasted log naming the verb
    # must not end a live grant any more than it may start one). fullmatch,
    # not match: trailing prose is the vector that kills prefix-anchoring
    # (test_policy_prompt's outside-counsel case; review finding pins it for revoke).
    if re.fullmatch(r"\s*revoke-policy\s*", prompt):
        revoke(sid)
        sys.exit(0)

    # Batch is matched FIRST, and the order is the whole guard: `auth-policy-batch`
    # begins with the string `auth-policy`, so the single-path pattern below would
    # otherwise fail occupancy on the extra tokens and log a refusal for a message
    # that is in fact well formed. No negative lookahead does this job.

    # NOT a blanket unlock: each path becomes its own entry, and only the
    # named paths are ever covered. Eight paths is eight named files, not the tree.
    # NO re.S, deliberately (F2). With DOTALL the captured tail spanned line
    # breaks, so a message that named one path and then went on in ordinary
    # prose armed an entry for every word in it -- including any REAL policy
    # path mentioned in that prose, which then armed and was consumable.
    # Without DOTALL a tail carrying a line break cannot fullmatch at all and
    # falls through to the audible refusal below, which is the occupancy rule
    # at :69-88 behaving as written rather than as this branch first read it.
    m = re.fullmatch(r"\s*auth-policy-batch\s+(.+?)\s*", prompt)
    if m:
        # Quotes are stripped BEFORE validation (D1). The single verb's pattern
        # below accepts `CLAUDE.md`, 'CLAUDE.md' and "CLAUDE.md", and its test
        # calls that the form the operator types by hand many times a day.
        # Refusing it here punished a habit the sibling verb trains -- and the
        # refusal blamed traversal and globs, which a quoted path has neither of,
        # so the operator was told to fix something that was not wrong.
        toks = [t.strip("`'\"") for t in m.group(1).split()]
        # Syntax only, never existence -- a policy path is protected before it
        # exists, and the single verb deliberately allows unlocking a hook file in
        # order to create it. Coverage ("is this token even a policy path?") is
        # NOT checked: that needs is_policy() from policy-mutate.py, and the gate design
        # rules against sharing a module between these gates. An entry naming a
        # non-policy path is inert, never dangerous -- nothing ever matches it,
        # which is what the single verb already does with a bogus path.
        # EVERY token must look like a path, and one that does not refuses the
        # WHOLE message (F2). Accepting bare words as paths quietly re-admitted
        # the trailing-prose bypass the occupancy rule was written against, and
        # the harm is not the inert junk word -- it is the REAL policy path
        # sitting in the same prose, which arms and is spendable. Fail the
        # batch, never the token: a partial arm is the shape that surprises.
        # Every path in CLAUDE.md's policy list carries a dot or a separator,
        # so requiring one costs no legitimate unlock.
        pathish = re.compile(r"[A-Za-z0-9_.-]*[./\\\\][A-Za-z0-9_./\\\\-]*")
        bad = [t for t in toks
               if not t
               # ROOTED, not `os.path.isabs`. On Windows isabs is True only for
               # the drive-letter form -- which `pathish` already rejects, since
               # ":" is outside its class -- so `isabs` sat here as a DEAD clause
               # and the test naming it stayed green with it deleted. The form
               # isabs MISSES and `pathish` admits is the leading separator, and
               # `os.path.join` below resets to the drive root on exactly that,
               # so this clause is what actually enforces decision 5's
               # project-relative rule. Glob chars need no clause of their own:
               # "*?[]" are outside `pathish`'s character class already.
               or t[0] in "/\\"
               or ".." in t.replace("\\", "/").split("/")
               or not pathish.fullmatch(t)
               # A path ends in a name character; prose ends in punctuation.
               # `pathish` alone still admitted "thanks." "too." "e.g." "i.e."
               # -- each carries a dot -- so a single-line tail of dotted words
               # still armed, which is the partial arm this branch claims to
               # refuse. NARROWED, NOT CLOSED: a dotted word with no trailing
               # stop ("e.g") still reads as a path, and no shape test settles
               # that. Occupancy is the real guard; this is its floor.
               or not (t[-1].isalnum() or t[-1] == "_")]
        # `not toks` is load bearing (F1): the tail pattern can consume a lone
        # whitespace character, so a message of the verb plus a space and a
        # line break reached here with ZERO tokens, passed a bare length check,
        # and armed an empty grant -- truncating the live one and printing
        # success. Silent revocation reported as an arm, in the one file whose
        # refusals are audible by design.
        if not toks or len(toks) > 8 or bad:
            why = ("1-8 paths (got %d)" % len(toks)
                   if not toks or len(toks) > 8
                   else "project-relative paths with no traversal or glob")
            log_line("policy-batch", "malformed batch, %d token(s)" % len(toks),
                     event="unlock-refused")
            print("policy-auth: armed nothing - 'auth-policy-batch' takes %s." % why)
            sys.exit(0)
        entries = []
        for t in toks:
            # Unconditional join: validation above refuses both absolute forms
            # (drive-letter by `pathish`, leading separator by the rooted clause),
            # so an `isabs` branch here would be a second dead one.
            fp = os.path.join(ROOT, t)
            entries.append({"path": t,
                            "norm": os.path.normcase(os.path.realpath(fp)),
                            "used": False})
        arm("policy-unlock", sid, {"entries": entries, "mode": "task"}, "policy",
            "%d path(s): %s sid=%s" % (len(entries), " ".join(toks), sid),
            note="policy-auth: task unlock armed for %d path(s): %s -- %s."
                 % (len(entries), " ".join(toks), TASK_LIFETIME))
        sys.exit(0)

    m = re.fullmatch(one_arg % "auth-policy", prompt)
    if m:
        raw = m.group(1)
        p = raw if os.path.isabs(raw) else os.path.join(ROOT, raw)
        arm("policy-unlock", sid,
            {"path": raw, "norm": os.path.normcase(os.path.realpath(p)),
             "mode": "task"},
            "policy", "%s sid=%s" % (raw, sid),
            note="policy-auth: task unlock armed for 1 path(s): %s -- %s."
                 % (raw, TASK_LIFETIME))
        armed = True

    # net and env stay UNKEYED, and that is the ordering rule again, not an
    # oversight: net-post.py and env-global.py have not been taught to read a
    # session-keyed name. Keying these here would make their unlocks unfindable
    # and silently unusable. They key when their consumers can read them; until
    # then they still share one slot and are still clobberable across sessions.
    # Both stay ONE-SHOT by ruling; the task lifetime
    # is the policy slot's alone, and so is the ` sid=` marker suffix.
    m = re.fullmatch(one_arg % "auth-net", prompt)
    if m:
        arm("net-unlock", "", {"host": m.group(1).lower()},
            "net", m.group(1).lower())
        armed = True

    if re.fullmatch(r"\s*auth-env\s*", prompt):
        arm("env-unlock", "", {}, "env", "global env mutation")
        armed = True

    # A refusal must be audible (senior engineer F4). Occupancy is right, but it
    # made failure invisible: a verb that fails occupancy produced no grant, no
    # log line and no output, so "my unlock did not take" and "I typed nothing"
    # were one observation. That is worst precisely here, because the file that
    # would add this diagnostic is itself behind the gate — if arming ever breaks
    # wholesale, silence is the only symptom and there is no in-band way back.

    # It also returns a signal to §4 that §4 has already spent: a defect was found
    # by counting armed lines against consumed lines, and a refusal appeared in
    # neither.

    # The operator's text is NOT echoed back. Only the verb recognised and the
    # rule it failed — the message may be a paste of anything at all, and this
    # line goes into an append-only audit log.
    if not armed:
        # policy-batch is listed FIRST: the alternation is ordered, and
        # `policy` would otherwise match the prefix of `policy-batch` and
        # then fail the lookahead on the hyphen -- leaving a malformed batch
        # message silent, which is the exact F4 defect this block exists to
        # fix. Found by test_policy_batch.py before it ever shipped.
        # `revoke-policy` in the alternation, so a mention of it is
        # refused audibly too, under the same rule.
        v = re.search(r"(?:auth-(?:policy-batch|policy|net|env|browse|use)"
                      r"|revoke-policy)(?![\w-])", prompt)
        if v and prompt.strip() in ("auth-browse", "auth-use"):
            # Retired 2026-09-21: retyping one alone can never arm
            # it, so the occupancy refusal below would misdirect (grill F-E).
            # Bare only: a mixed message keeps that refusal.
            log_line(v.group(0), "retired 2026-09-21, arms nothing",
                     event="unlock-retired")
            print("policy-auth: '%s' was retired 2026-09-21 and arms nothing; "
                  "the pane, Chrome and the desktop need no verb."
                  % v.group(0))
        elif v:
            log_line(v.group(0), "message was not the instruction alone",
                     event="unlock-refused")
            print("policy-auth: saw '%s' but armed nothing — an unlock or "
                  "revoke must be the entire message, on its own, with nothing "
                  "before or after it." % v.group(0))

    sys.exit(0)


if __name__ == "__main__":
    main()
