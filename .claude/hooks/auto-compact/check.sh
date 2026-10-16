#!/bin/bash
# auto-compact check — PostToolUse, matcher '*'. Advisory context-size nudge.
# Fail-quiet by design: any failure -> silent exit 0. A hook that blocks a tool
# call because it could not parse a transcript is worse than no hook.
#
# INCIDENT (contract S8: an added hook names its incident). 2026-08-24, this
# tree. This tree registered five hook events and neither auto-compact leg, and
# settings.json carried no `env` block at all — so CLAUDE_CODE_AUTO_COMPACT_WINDOW
# was unset and native compaction fired at the model default. One session reached
# ~700k of context, roughly three times the predecessor tree's ceiling, and
# compacted zero times. The operator noticed from the token spend, not from any
# signal this tree produced.
#
# Recreated from an earlier version of this hook, not copied: the earlier version's runbook and resume leg both
# instruct the agent to run `handoff` / `resume-handoff` SKILLS, and this tree has
# no skills directory, so a paste would have emitted instructions naming machinery
# that does not exist here.
#
# Size source = the newest assistant turn's `usage` in the transcript
# (input + cache_creation + cache_read) — the exact number the context indicator
# shows. Compaction-aware for free: after a compact the next turn's cache_read
# drops to the compacted size, so no baseline bookkeeping is needed. The earlier version records
# that the obvious proxy — transcript bytes / 4 over the append-only .jsonl —
# read ~10x high (969k reported against 101k real). Do not reintroduce it.
set -euo pipefail
trap 'exit 0' ERR

# Resolved only when the caller did not name a state file. `dirname` is a
# process, and on this host a process is ~45 ms of this hook's whole budget.
# The `pwd -P` fork stays: a state file that silently moves because a path was
# never canonicalised re-arms the hook invisibly, which is the exact failure
# class this script exists to prevent, and 16 ms does not buy that risk.
STATE_FILE="${AUTO_COMPACT_STATE_FILE:-}"
if [ -z "$STATE_FILE" ]; then
  SCRIPT_DIR="${BASH_SOURCE[0]%/*}"
  case "$SCRIPT_DIR" in "${BASH_SOURCE[0]}") SCRIPT_DIR="." ;; esac
  STATE_FILE="$(cd "$SCRIPT_DIR" && pwd -P)/state.json"
fi

# Where the agent is told to write the handoff. resume.sh globs this same
# constant under the tree root; test_auto_compact.sh pins that the path emitted
# here is the path found there. Keep the two in step or the legs miss silently.
REL="handoffs/auto"

# Bands derive from the native compaction ceiling so the two cannot drift.
# The ordering they buy is the whole point: nudge (write the handoff) ->
# escalate (backstop) -> native compaction. Handoff before compaction, always;
# the other order loses the information the handoff exists to carry.
#
# CLAUDE_CODE_AUTO_COMPACT_WINDOW is the single source of truth and is set in
# settings.json `env`. The default below MUST equal that value: the earlier version defaults to
# 250000 in code while its settings set 350000, and that mismatch is exactly
# what made this tree's own ceiling misread earlier today. If the env block is
# ever removed, this default is what runs.
#
# The ceiling is NOT the point compaction fires at. Compaction reserves headroom
# for the next turn's output and triggers below it. The earlier version measured this on
# 2026-08-05 across 7 sessions at a 250000 ceiling: real trigger 204,003-229,342,
# a 20.7k-46.0k gap. Bands off the raw ceiling put escalate ABOVE the real
# trigger — it never fired in 1 of those 7 — and left the nudge one or two tool
# calls of runway. So bands come off EFFECTIVE.
#
# 40000 is a fixed offset, deliberately, over the objection that a low ceiling
# drives bands to zero: the >= 100000 clamp bounds the worst case at
# EFFECTIVE=60000, giving 48000 and 54000 — positive and ordered. A proportional
# model is not distinguishable from an absolute one when all 7 data points sit at
# one ceiling. 40000 is measured, not documented. Re-check it if an observed
# trigger ever falls below 0.80 of the ceiling.
#
# The numeric guards are load-bearing, not decoration: bare $(( )) on a garbage
# value fails under `set -e`, hits the ERR trap, and silently disables the whole
# hook — a typo'd env var would remove the nudge with no symptom at all. The
# guard protects the hook, not the config: the host reads "350k" as 350 and
# clamps to its own minimum, so a typo still breaks the real ceiling.
num_or() { case "${1:-}" in ''|*[!0-9]*) printf '%s' "$2" ;; *) printf '%s' "$1" ;; esac; }

# 10# is not decoration either: num_or passes digit-only strings, but $(( ))
# reads a leading zero as BASE 8. `0350000` becomes 118784 — bands of 63k/70k
# instead of 248k/279k, wrong on every session with no signal at all — and
# `0389000` is not valid octal, so $(( )) errors, the ERR trap fires, and the
# hook is dead for the life of that value. Both pass the digit test and the
# >= 100000 comparison, which is base 10. Force base 10 once, here.
CEILING="$(num_or "${CLAUDE_CODE_AUTO_COMPACT_WINDOW:-}" 350000)"
CEILING=$(( 10#$CEILING ))
[ "$CEILING" -ge 100000 ] || CEILING=350000
EFFECTIVE=$(( CEILING - 40000 ))
NUDGE_TOKENS="$(num_or "${AUTO_COMPACT_NUDGE_TOKENS:-}" $(( EFFECTIVE * 80 / 100 )))"
ESCALATE_TOKENS="$(num_or "${AUTO_COMPACT_ESCALATE_TOKENS:-}" $(( EFFECTIVE * 90 / 100 )))"
NUDGE_TOKENS=$(( 10#$NUDGE_TOKENS ))
ESCALATE_TOKENS=$(( 10#$ESCALATE_TOKENS ))

# Sample interval, and it takes the same config-error shape as CEILING above: a
# garbage, negative or zero value falls back to the default and the hook keeps
# working. It never fails the tool call. EVERY=1 disables sampling and
# reproduces the pre-gate behaviour exactly -- that is the regression seam, and
# test_auto_compact.sh pins the whole suite to it.
#
# Default 8, derived rather than picked (all figures measured 2026-09-02 on
# this host, from this tree's own transcripts):
#   nudge floor              248000   (at the 350000 ceiling)
#   earliest real compaction ~285600  (0.8160 of ceiling -- the earlier version minimum
#                                      recorded at :49, 204003/250000)
#   runway between them       37600 tokens
#   window step per usage record: median 1123, p90 3426 (n=5294, 6 sessions)
# Being late by EVERY-1 = 7 calls costs at most 7*3426 = 23982 tokens of that
# 37600 at the p90 step, and 7861 at the median, so the nudge still lands well
# before compaction. EVERY=12 would spend 37686 -- the entire runway. 8 sits on
# the safe side of that cliff with margin, which is why it is 8 and not 10.
EVERY="$(num_or "${AUTO_COMPACT_CHECK_EVERY:-}" 8)"
EVERY=$(( 10#$EVERY ))
[ "$EVERY" -ge 1 ] || EVERY=8

# `read -d ''` rather than `$(cat)`: that fork+exec cost ~45 ms on every tool
# call to move a few hundred bytes bash can read itself. It returns 1 at EOF
# without finding the delimiter, which under `set -e` would hit the ERR trap, so
# the status is discarded deliberately -- an empty INPUT still fails jq below,
# which is where the malformed-payload guard lives.
INPUT=""
IFS= read -r -d '' INPUT || true

# ---- sample gate ----------------------------------------------------------
# Why this exists. This hook is PostToolUse with matcher '*', so it runs on
# every tool call in every session. Measured on this host 2026-09-02: 280 ms
# with no transcript, 560 ms with one, of which ~9 binary spawns at ~45 ms each
# are essentially the entire bill. It re-answers "how big is the window now?" at
# the fastest rate the harness offers, for a quantity that moves ~1.1k tokens
# per call against bands 31k apart.
#
# Everything from here to the closing `fi` is builtin-only: no fork, no exec.
# That is the whole point. An early exit that still spawns `jq` to read a
# counter buys nothing, because the spawn IS the cost. Measured on this host,
# fresh bash per call: floor 65 ms, `read` +3, `$(<file)` +4, regex +1,
# redirect +2 -- against +51 for a single `jq`. So the gate must parse nothing.
#
# It only ever skips while the LAST measurement was below the nudge floor, so
# inside the bands the behaviour is identical to EVERY=1, deliberately: the
# escalate backstop has only ~6600 tokens of runway before native compaction
# (285600 - 279000), which is under two calls at the p90 step. Sampling cannot
# be afforded there. Below the floor is where a session spends most of its
# calls and where lateness is provably cheap -- see the derivation at EVERY.
#
# The tick rides in the existing state file as ONE fixed-size top-level member,
# "@ac-tick": "<session> <n> <lastTokens>". One member, not one per session, so
# the file cannot grow without bound: a second concurrent session just resets
# it, which costs extra CHECKS, never fewer. jq reads it as an ordinary key and
# every existing filter ignores it -- a session id never collides with the
# literal "@ac-tick", and `del(.[$s])` cannot reach it.
#
# EVERY failure mode here falls through to the expensive path: no state file, no
# tick, a different session, an unparseable value, a last measurement at or
# above the floor. Falling through means "do the real work", so a broken gate
# degrades to today's behaviour rather than to silence. That direction is not
# negotiable -- a missing nudge is invisible, a duplicate one is noisy (:188).
#
# The gate sits ABOVE the delegate gate at :98, so a delegate's tool call bumps
# the tick: delegate payloads carry the PARENT's session_id. Stated rather than
# fixed. A delegate can consume one of the parent's samples, and a sample that
# lands on a delegate call does the expensive read and then exits at :98 anyway.
# Moving the gate below :98 would cost the very jq spawn it exists to avoid.
#
# SESSION here is a HINT, matched out of the raw payload text, and is used for
# nothing but comparing the tick against itself. The authoritative parse stays
# with jq below, because the malformed-payload guard IS jq failing under
# pipefail: a payload with no extractable session_id -- `not json at all` among
# them -- matches nothing here and falls straight through to that guard intact.
if [ "$EVERY" -gt 1 ] && [ -s "$STATE_FILE" ]; then
  HINT=""
  if [[ "$INPUT" =~ \"session_id\"[[:space:]]*:[[:space:]]*\"([^\"]+)\" ]]; then
    HINT="${BASH_REMATCH[1]}"
  fi
  if [ -n "$HINT" ]; then
    RAW0="$(<"$STATE_FILE")"          # `$(<f)` is bash-internal: no fork
    if [[ "$RAW0" =~ (\"@ac-tick\"[[:space:]]*:[[:space:]]*\")([^\"]*)(\") ]]; then
      OLD="${BASH_REMATCH[0]}"
      set -- ${BASH_REMATCH[2]}       # <session> <n> <lastTokens>, word-split
      if [ "$#" -eq 3 ] && [ "$1" = "$HINT" ]; then
        case "$2$3" in
          ''|*[!0-9]*) ;;             # garbage -> fall through, do the work
          *)
            # 10# for the reason given at :75 -- a leading zero would make these
            # octal, and `08` is not even valid octal: the arithmetic would
            # error, hit the ERR trap, and skip the check with no symptom at all.
            N0=$(( 10#$2 )); T0=$(( 10#$3 ))
            if [ "$T0" -lt "$NUDGE_TOKENS" ] && [ $(( N0 + 1 )) -lt "$EVERY" ]; then
              # The write is the `if` condition on purpose. A redirection
              # failure returns non-zero without running the command, and under
              # `set -e` anywhere else that reaches the ERR trap and exits 0 --
              # skipping the check with no symptom, forever, for as long as the
              # file stays unwritable. As a condition it is exempt, so a failed
              # write falls through to the real work instead. Only a tick that
              # actually landed is allowed to buy a skip.
              if { printf '%s' "${RAW0/"$OLD"/"${BASH_REMATCH[1]}$1 $(( N0 + 1 )) $T0\""}" \
                   > "$STATE_FILE"; } 2>/dev/null; then
                exit 0
              fi
            fi ;;
        esac
      fi
    fi
  fi
fi

SESSION="$(printf '%s' "$INPUT" | jq -r '.session_id // empty')"
TRANSCRIPT="$(printf '%s' "$INPUT" | jq -r '.transcript_path // empty')"
if [ -z "$SESSION" ] || [ -z "$TRANSCRIPT" ] || [ ! -r "$TRANSCRIPT" ]; then
  exit 0
fi

# Delegate tool calls. PostToolUse fires inside dispatched roster workers too,
# and the nudge is a WRITE instruction — unsatisfiable by a read-only delegate's
# tool grant, and computed from the wrong context besides. A delegate's payload
# carries `agent_id`; the parent's never does. Its `session_id` and
# `transcript_path` are the PARENT's, identical strings, so neither
# discriminates. This matters more here than in the earlier version, where the norm is not
# parallel delegation: without the gate, a delegate crossing the threshold
# consumes the parent's only nudge and leaves the parent silent for the band.
if printf '%s' "$INPUT" | jq -e 'has("agent_id")' >/dev/null 2>&1; then
  exit 0
fi

# Newest usage record = live context size. tail bounds cost on a multi-MB
# transcript; the newest turn's events are always within the last lines.
#
# compact_boundary drop: after a compact the stale pre-compact usage line stays
# "newest" until the first post-compact turn *completes*. The awk stage discards
# every line up to and including the last boundary marker, leaving only usage
# lines strictly after it; none yet -> empty -> fail-quiet, which is the correct
# "do not nudge mid-first-turn" behaviour. The marker cannot be spoofed from
# conversation content: inside a JSON string the quotes are escaped and no
# longer match this literal. It IS whitespace-exact, so a host that emits
# `"subtype": "compact_boundary"` would silently disable the filter.
#
# `.message?.usage?` not `.message.usage`: the `?` on fromjson only guards the
# parse. A line that parses to a scalar, or whose `message` is a string, makes
# the path raise, jq exits nonzero, pipefail propagates, the ERR trap fires and
# the nudge is dead for as long as that line stays in the window.
#
# map(numbers) not `// 0` on each field: `//` is a null/false alternative, not a
# type coercion, so a usage field carrying a string returns the string and then
# raises on the add — the same silent death by a different door, while printing
# a jq error on every tool call. `numbers` drops anything non-numeric; `add // 0`
# covers the empty case. The container guard above does not reach the fields.
#
# select(.isSidechain != true): probed on a live transcript 2026-08-24 —
# 1790 lines carried "isSidechain":false and zero carried true, across a session
# that ran many delegates, so delegate turns do NOT reach the parent transcript
# on this host and the filter is a no-op today. It stays because the failure it
# guards is silent and costs a whole session: were the host to start writing
# sidechain turns here, a small delegate usage line would read as the newest and
# drop the parent under the floor. Note this is NOT the earlier version's stated reason — the earlier version calls
# the flag dead code because session_id and transcript_path are the parent's,
# which is a non sequitur: isSidechain is a per-line transcript field, not a
# payload key. The conclusion happened to hold; the argument never did.
TOKENS="$(tail -n 200 "$TRANSCRIPT" 2>/dev/null \
  | awk '/"subtype":"compact_boundary"/ { keep=""; next } { keep = keep $0 ORS } END { printf "%s", keep }' \
  | jq -R 'fromjson? | select(type == "object") | select(.isSidechain != true)
           | .message?.usage? | select(type == "object")
           | [.input_tokens, .cache_creation_input_tokens, .cache_read_input_tokens]
           | map(numbers) | add // 0' \
  | tail -n 1)"
case "$TOKENS" in ''|*[!0-9]*) exit 0 ;; esac   # no usable usage -> fail-quiet

# Refresh the sample tick on EVERY expensive call, not only on the ones that
# reach a save(). The paths that exit early -- already nudged, already
# escalated -- are the frequent ones in a long session, and a tick left holding
# a stale below-floor number would let the gate keep skipping INSIDE the bands,
# which is the one place it must not. Writing it here means the stored figure is
# >= NUDGE_TOKENS for as long as a session sits in a band, so the gate falls
# through on every one of those calls and band behaviour matches EVERY=1.
#
# Builtin-only, so it adds nothing to a path already paying for jq. It runs
# BEFORE the state read below so that any later save() re-serialises this value
# instead of the one it replaced. Creation and update are the same write.
#
# A failed write here must never suppress the message it was recording -- the
# same rule save() states at :159. Hence `|| true`: a stale tick costs one
# missed optimisation, a suppressed nudge costs a session.
#
# Not temp+mv, unlike save(): this is a sub-kilobyte redirect, and the race it
# can lose to a concurrent session is the lost update already accepted at :148 --
# worst case one duplicate nudge, never a missing one. A lock still costs more
# than that bug. The ceiling: if this file ever grows past one atomic write, or
# a second writer appears that is not this hook, this needs temp+mv like save().
#
# The id guard is a trust boundary, not decoration. SESSION comes off the
# payload, and a value carrying a quote or a backslash would turn a hand-built
# member into malformed JSON. Anything but a plain id writes nothing, which
# costs a skipped optimisation and no correctness.
case "$SESSION" in
  ''|*[!A-Za-z0-9_.-]*) ;;
  *)
    TICK="\"@ac-tick\": \"$SESSION 0 $TOKENS\""
    if [ -s "$STATE_FILE" ]; then
      RAW0="$(<"$STATE_FILE")"
      if [[ "$RAW0" =~ \"@ac-tick\"[[:space:]]*:[[:space:]]*\"[^\"]*\" ]]; then
        { printf '%s' "${RAW0/"${BASH_REMATCH[0]}"/"$TICK"}" > "$STATE_FILE"; } 2>/dev/null || true
      else
        # Insertion, not parsing: valid JSON in gives valid JSON out. Anything
        # that is not an object is left alone for jq to reject below.
        case "${RAW0//[[:space:]]/}" in
          '{}') { printf '{%s}' "$TICK" > "$STATE_FILE"; } 2>/dev/null || true ;;
          '{'*) { printf '{%s,%s' "$TICK" "${RAW0#*\{}" > "$STATE_FILE"; } 2>/dev/null || true ;;
        esac
      fi
    else
      # No state file at all. Both tick writers are guarded by `-s`, and below
      # the floor save() only fires for a session that ALREADY has an entry --
      # so nothing on that path ever creates the file, the gate at :166 stays
      # false forever, and a fresh checkout pays the expensive path for its
      # whole life. Every worktree is a fresh checkout (state.json is
      # gitignored), and per CLAUDE.md section 3 a worktree per session is the
      # normal shape, so without this the win is unreachable where most
      # sessions run. What this writes is exactly what the '{}' case above
      # would have written one call later.
      { printf '{%s}' "$TICK" > "$STATE_FILE"; } 2>/dev/null || true
    fi ;;
esac

# Invalid state must re-arm, never brick. `>` truncates before jq runs, so a
# single jq failure can leave a zero-byte file; if that then routed to `exit 0`
# the hook would be silently dead for the life of the tree — the exact class of
# invisible absence this whole artifact exists to prevent. Every write goes via
# temp + mv so a reader never sees the truncated window, which also bounds the
# read-modify-write race between two sessions sharing this file to a lost
# update: at worst one duplicate nudge. A lock costs more than that bug.
STATE='{}'
if [ -e "$STATE_FILE" ]; then
  RAW="$(cat "$STATE_FILE" 2>/dev/null || true)"
  if printf '%s' "$RAW" | jq -e 'type == "object"' >/dev/null 2>&1; then
    STATE="$RAW"
  fi
fi

save() {  # never let a failed write suppress the message it was recording
  printf '%s' "$STATE" | jq "$@" > "$STATE_FILE.tmp.$$" \
    && mv -f "$STATE_FILE.tmp.$$" "$STATE_FILE" || rm -f "$STATE_FILE.tmp.$$" || true
}

# Under the nudge floor: re-arm (drop any flags) and stay quiet. A post-compact
# window lands here and re-arms with zero bookkeeping. del() drops escalated
# alongside nudged, so the backstop re-arms for free.
if [ "$TOKENS" -lt "$NUDGE_TOKENS" ]; then
  if [ "$(printf '%s' "$STATE" | jq -r --arg s "$SESSION" '.[$s] // empty')" != "" ]; then
    save --arg s "$SESSION" 'del(.[$s])'
  fi
  exit 0
fi

HANDOFF="$REL/$(date +%F)-${SESSION}.md"
RUNBOOK="docs/auto-compact-runbook.md"
K=$(( TOKENS / 1000 ))

emit() {
  jq -n --arg ctx "$1" \
    '{hookSpecificOutput:{hookEventName:"PostToolUse",additionalContext:$ctx}}'
}

# Escalate backstop fires ONCE, not every call. Injecting on every tool result
# past the band burns the context it exists to protect and derails the run
# continuously — the earlier version records this band previously fighting its own purpose.
#
# Emit BEFORE persisting, in both bands. If the state write fails, the failure
# direction should be a duplicate nudge (noisy, self-reporting) and never a
# missing one (invisible) — see the incident above.
if [ "$TOKENS" -ge "$ESCALATE_TOKENS" ]; then
  if [ "$(printf '%s' "$STATE" | jq -r --arg s "$SESSION" '.[$s].escalated // empty')" = "true" ]; then
    exit 0
  fi
  emit "Context ≈${K}k tokens — STOP at the next safe point and run the auto-compact runbook (\`$RUNBOOK\`) now. Write the handoff to \`$HANDOFF\`, then keep working. Do NOT ask the operator to compact; compaction fires on its own at the ceiling."
  save --arg s "$SESSION" '.[$s] = {nudged: true, escalated: true}'
  exit 0
fi

# Nudge band: once, until tokens fall back under the floor (a compact re-arms).
if [ "$(printf '%s' "$STATE" | jq -r --arg s "$SESSION" '.[$s].nudged // empty')" = "true" ]; then
  exit 0
fi
emit "Context ≈${K}k tokens — run the auto-compact runbook (\`$RUNBOOK\`) at the next stopping point. Write the handoff to \`$HANDOFF\`, then keep working; compaction fires on its own at the ceiling."
save --arg s "$SESSION" '.[$s] = {nudged: true}'
exit 0
