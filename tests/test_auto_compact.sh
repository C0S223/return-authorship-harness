#!/bin/bash
# Tests for the auto-compact hooks. Run: bash tests/test_auto_compact.sh
# Point at the drafts before they land:  AC_DIR=tmp/auto-compact bash ...
#
# Cases here exist because an adversarial review found the suite would stay
# green without them (2026-08-24): (a) an exit-status assertion, (b) a usage
# fixture spreading tokens across all three accounting fields, (c) escalate
# re-arm, (d) a jq -e assertion on the emitted hookEventName, (e) a
# source=startup case. Do not delete one without replacing what it proves.
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
D="${AC_DIR:-$ROOT/.claude/hooks/auto-compact}"
[ -d "$D" ] || { echo "no hook dir: $D"; exit 1; }
case "$D" in /*) ;; *) D="$ROOT/$D" ;; esac

T="$(mktemp -d)"; export AUTO_COMPACT_STATE_FILE="$T/state.json"
export CLAUDE_CODE_AUTO_COMPACT_WINDOW=350000  # EFFECTIVE 310000; nudge 248000, escalate 279000

# check.sh samples its expensive stage every AUTO_COMPACT_CHECK_EVERY calls
# (default 8). EVERY=1 turns sampling off, and every case in this file below
# assumes the pre-gate every-call behaviour -- so pinning it here is not a
# convenience, it is the regression seam: the whole suite becomes the proof
# that EVERY=1 reproduces the pre-gate script exactly. Flip this to 8 and the
# re-arm cases go red -- they call twice for one session and the second call is
# sampled out -- which is the check that this line is load-bearing. No count is
# written here on purpose: see the note at the foot of this file about counts in
# prose. The gate's own cases set EVERY explicitly, per case, at the bottom of
# the check.sh section.
export AUTO_COMPACT_CHECK_EVERY=1
FAIL=0

# (b) Spread the total across all three fields the design says are summed. A
# fixture that zeroes two of them lets any one term be deleted from check.sh
# with the suite still green — and cache_read is nearly the whole number in real
# transcripts, so that is the term most worth proving.
one_field() { # whole value in the named field, so dropping that term crosses the floor
  printf '{"isSidechain":false,"message":{"usage":{"%s":%s}}}\n' "$1" "$2"; }
usage() { printf '{"isSidechain":false,"message":{"usage":{"input_tokens":1000,"cache_creation_input_tokens":9000,"cache_read_input_tokens":%s}}}\n' "$(( $1 - 10000 ))"; }
chk()  { printf '{"session_id":"%s","transcript_path":"%s"%s}' "$1" "$T/t.jsonl" "${2:-}" | bash "$D/check.sh"; }
rsm()  { printf '{"session_id":"%s","source":"%s"%s}' "$1" "${2:-compact}" "${3:-}" | bash "$D/resume.sh"; }

N=0
ok()   { N=$(( N + 1 )); echo "ok   $1"; }
bad()  { echo "FAIL $1: $2"; FAIL=1; }
# chmod 444 proves nothing as uid 0 (root writes anyway; managed cloud runs as root),
# so the unwritable-state cases skip loudly there and run everywhere else.
# AC_TEST_UID is a test-only override to exercise the root branch from a non-root host.
skip() { echo "SKIP $1: $2"; }
ROOT_USER=0; [ "${AC_TEST_UID:-$(id -u)}" -eq 0 ] && ROOT_USER=1
ck()   { if [ -z "$2" ]; then [ -z "$3" ] && ok "$1" || bad "$1" "expected silence, got: $3"
         else case "$3" in *"$2"*) ok "$1";; *) bad "$1" "wanted '$2', got: $3";; esac; fi; }

usage 100000 > "$T/t.jsonl"
ck "below floor is silent" "" "$(chk s1)"
usage 250000 > "$T/t.jsonl"
ck "nudge band fires"      "run the auto-compact runbook" "$(chk s1)"
ck "nudge fires only once" "" "$(chk s1)"
usage 290000 > "$T/t.jsonl"
ck "escalate overrides nudged" "STOP at the next safe point" "$(chk s1)"
ck "escalate fires only once"  "" "$(chk s1)"
usage 100000 > "$T/t.jsonl"
ck "under floor re-arms silently" "" "$(chk s1)"
usage 250000 > "$T/t.jsonl"
ck "nudge fires again after re-arm" "run the auto-compact runbook" "$(chk s1)"

# (c) The re-arm must clear `escalated` too, or the backstop never fires again
# for the life of the session. Writing {escalated:true} without {nudged:true}
# passes every other case in this file.
usage 290000 > "$T/t.jsonl"
ck "escalate fires again after re-arm" "STOP at the next safe point" "$(chk s1)"

# (S4) The case above is masked: the nudge write is a wholesale assignment that
# drops `escalated` regardless of what the re-arm did, so it proves the nudge
# write overwrites, not that del() clears both flags. Go under the floor and
# back into the escalate band with no nudge-band call between — a realistic
# post-compaction jump.
usage 290000 > "$T/t.jsonl"; ck "escalate arms" "STOP" "$(chk s1e)"
usage 100000 > "$T/t.jsonl"; ck "escalate re-arm: under floor is silent" "" "$(chk s1e)"
usage 290000 > "$T/t.jsonl"
ck "re-arm clears escalated, not just nudged" "STOP at the next safe point" "$(chk s1e)"

usage 290000 > "$T/t.jsonl"
ck "delegate call is gated out" "" "$(chk s2 ',"agent_id":"a1","agent_type":"recall"')"

# (d) Substring matching cannot see a corrupted event name or malformed JSON —
# the host would silently discard the injection while the suite stayed green.
usage 250000 > "$T/t.jsonl"
printf '%s' "$(chk s9)" | jq -e '.hookSpecificOutput.hookEventName == "PostToolUse"' >/dev/null 2>&1 \
  && ok "check.sh emits a valid PostToolUse envelope" \
  || bad "check.sh emits a valid PostToolUse envelope" "bad or unparseable JSON"

# F20: asserting silence here cannot distinguish "read the post-boundary line,
# correctly below floor" from "read nothing at all". Put the post-boundary line
# in the nudge band instead, so the three outcomes are three different strings.
{ usage 690000; echo '{"subtype":"compact_boundary"}'; } > "$T/t.jsonl"
ck "no usage after boundary -> silent" "" "$(chk s3)"
{ usage 690000; echo '{"subtype":"compact_boundary"}'; usage 250000; } > "$T/t.jsonl"
ck "post-boundary usage is the one read" "run the auto-compact runbook" "$(chk s3)"

usage 250000 > "$T/t.jsonl"
ck "garbage ceiling falls back" "run the auto-compact runbook" \
   "$(CLAUDE_CODE_AUTO_COMPACT_WINDOW=350k chk s4)"
# The >= 100000 clamp is the entire justification for a fixed 40000 offset;
# without it a small ceiling drives both bands to 0 and fires on every call.
usage 100000 > "$T/t.jsonl"
ck "sub-minimum ceiling is clamped, not honoured" "" \
   "$(CLAUDE_CODE_AUTO_COMPACT_WINDOW=40000 chk s4b)"

echo '{"session_id":"s5"}' | bash "$D/check.sh" > "$T/o" 2>&1
ck "missing transcript is quiet" "" "$(cat "$T/o")"

# A malformed line must not kill the read: jq must not raise on it. Assert on
# stderr too — the first version of this case passed while jq was printing
# "Cannot index string with string" on every run, because a filter ran before
# the safe navigation. Silence on stderr is the only thing that proves the
# filter chain is actually total over transcript lines.
usage 250000 > "$T/t.jsonl"; echo '"a bare string"' >> "$T/t.jsonl"
echo '{"message":"not an object"}' >> "$T/t.jsonl"; echo 'not json at all' >> "$T/t.jsonl"
usage 250000 >> "$T/t.jsonl"
# (S5) Spreading the value was necessary but not sufficient: the fixture put
# 1000 in input_tokens while every band assertion carried 2000 of slack, so that
# term could be deleted from the sum with the suite green. One case per term,
# each carrying the whole value.
for f in input_tokens cache_creation_input_tokens cache_read_input_tokens; do
  one_field "$f" 250000 > "$T/t.jsonl"; echo '{}' > "$AUTO_COMPACT_STATE_FILE"
  ck "usage sum includes $f" "run the auto-compact runbook" "$(chk "sum-$f")"
done

# (S6) `//` is a null alternative, not a coercion: a string field returns the
# string and then raises on the add. The container guard does not reach fields.
usage 250000 > "$T/t.jsonl"
printf '{"isSidechain":false,"message":{"usage":{"input_tokens":"abc","cache_read_input_tokens":250000}}}\n' >> "$T/t.jsonl"
echo '{}' > "$AUTO_COMPACT_STATE_FILE"
ck "non-numeric usage field does not kill the read" "run the auto-compact runbook" "$(chk s6c 2>/dev/null)"
echo '{}' > "$AUTO_COMPACT_STATE_FILE"
ck "non-numeric usage field produces no stderr" "" "$(chk s6d 2>&1 >/dev/null)"

# (S7) num_or passes digit-only strings, but $(( )) reads a leading zero as base
# 8: 0350000 -> 118784 (wrong bands, no signal); 0389000 is not valid octal, so
# $(( )) errors and the hook dies. Both pass the digit test and the >= compare.
usage 250000 > "$T/t.jsonl"; echo '{}' > "$AUTO_COMPACT_STATE_FILE"
ck "leading-zero ceiling is read base 10, not octal" "run the auto-compact runbook" \
   "$(CLAUDE_CODE_AUTO_COMPACT_WINDOW=0350000 chk s7a)"
# At ceiling 389000 the floor is 279200, so this fixture must clear THAT, not the
# 350000 floor — the first version asserted against the wrong band. Without 10#
# this value errors inside $(( )) and the hook emits nothing at all.
usage 300000 > "$T/t.jsonl"; echo '{}' > "$AUTO_COMPACT_STATE_FILE"
ck "ceiling with 8 or 9 after a leading zero still works" "run the auto-compact runbook" \
   "$(CLAUDE_CODE_AUTO_COMPACT_WINDOW=0389000 chk s7b)"

# (S8) The sidechain guard is kept because what it prevents is silent and costs
# a session — and nothing covered it, so a future edit deletes it freely. The
# sidechain line is last and small: unfiltered it reads as newest and drops the
# parent under the floor.
usage 250000 > "$T/t.jsonl"
printf '{"isSidechain":true,"message":{"usage":{"input_tokens":5000}}}\n' >> "$T/t.jsonl"
echo '{}' > "$AUTO_COMPACT_STATE_FILE"
ck "a sidechain usage line does not become the measurement" "run the auto-compact runbook" "$(chk s8a)"

usage 250000 > "$T/t.jsonl"; echo '{}' > "$AUTO_COMPACT_STATE_FILE"
ck "malformed transcript lines are skipped" "run the auto-compact runbook" "$(chk s6 2>/dev/null)"
echo '{}' > "$AUTO_COMPACT_STATE_FILE"
err="$(chk s6b 2>&1 >/dev/null)"
ck "malformed lines produce no stderr noise" "" "$err"

# (F17) Corrupt state must re-arm, not brick. A zero-byte file that routed to
# exit 0 would disable the hook permanently and silently.
usage 250000 > "$T/t.jsonl"
: > "$AUTO_COMPACT_STATE_FILE"
ck "empty state file re-arms rather than bricking" "run the auto-compact runbook" "$(chk s7)"
echo '["not","an","object"]' > "$AUTO_COMPACT_STATE_FILE"
ck "non-object state re-arms rather than bricking" "run the auto-compact runbook" "$(chk s8)"
echo '{}' > "$AUTO_COMPACT_STATE_FILE"

# (a) The one non-negotiable constraint: a hook must never fail the tool call.
# Nothing else in this file asserts an exit status.
usage 290000 > "$T/t.jsonl"
( AUTO_COMPACT_STATE_FILE="$T/nodir/state.json" chk sA >/dev/null 2>&1 ); rc=$?
[ "$rc" -eq 0 ] && ok "unwritable state file still exits 0" \
                || bad "unwritable state file still exits 0" "exit $rc"
out="$(AUTO_COMPACT_STATE_FILE="$T/nodir/state.json" chk sA 2>/dev/null)"
ck "unwritable state file still emits the nudge" "STOP at the next safe point" "$out"

# (S1) The exit-status case above no longer reaches the ERR trap: save() ends
# `|| rm -f ... || true` and returns 0 unconditionally, by design (F2). And it
# only ever covered check.sh — rsm() is always used inside $( ), which discards
# the status. A malformed payload fails jq before any of that, so it reaches the
# trap in both legs. This is the one constraint the contract calls
# non-negotiable: a hook must never fail the tool call.
printf 'not json at all' | bash "$D/check.sh" >/dev/null 2>&1; rc=$?
[ "$rc" -eq 0 ] && ok "check.sh: malformed payload still exits 0" \
                || bad "check.sh: malformed payload still exits 0" "exit $rc"
printf 'not json at all' | bash "$D/resume.sh" >/dev/null 2>&1; rc=$?
[ "$rc" -eq 0 ] && ok "resume.sh: malformed payload still exits 0" \
                || bad "resume.sh: malformed payload still exits 0" "exit $rc"

# (S9) Full atomicity under real concurrency is NOT covered here and is not
# cheaply testable — stated rather than implied. What is covered: no temp file
# survives a run, which is what a missing `rm -f` leaves behind.
if ls "$AUTO_COMPACT_STATE_FILE".tmp.* >/dev/null 2>&1; then
  bad "no state temp files survive" "leftover $AUTO_COMPACT_STATE_FILE.tmp.*"
else ok "no state temp files survive"; fi

# (S10) The nudge hands the agent two paths and nothing related either to a real
# file — and F13 just moved the runbook, into the area where it is most likely
# to move again.
usage 250000 > "$T/t.jsonl"; echo '{}' > "$AUTO_COMPACT_STATE_FILE"
NUDGE="$(chk sPath | jq -r '.hookSpecificOutput.additionalContext')"
RB="$(printf '%s' "$NUDGE" | grep -o 'docs/[a-z-]*runbook\.md' | head -1)"
if [ -n "$RB" ] && [ -f "$ROOT/$RB" ]; then ok "the runbook path in the nudge resolves to a file"
else bad "the runbook path in the nudge resolves to a file" "no such file: ${RB:-<none found>}"; fi
HD="$(printf '%s' "$NUDGE" | grep -o 'handoffs/auto/[^`]*\.md' | head -1)"
if [ -n "$HD" ] && [ -d "$ROOT/$(dirname "$HD")" ]; then ok "the handoff directory in the nudge exists"
else bad "the handoff directory in the nudge exists" "no dir for: ${HD:-<none found>}"; fi

# ---- sample gate ----
# Everything above ran at EVERY=1. These cases turn sampling on, one call at a
# time, and assert on the tick rather than only on silence: silence is what a
# skip, a crash and a correct below-floor call all look like, which is the F20
# defect this file already names twice. The tick distinguishes them.
tick() { jq -r '."@ac-tick" // "none"' "$AUTO_COMPACT_STATE_FILE" 2>/dev/null; }

echo '{}' > "$AUTO_COMPACT_STATE_FILE"; usage 100000 > "$T/t.jsonl"
AUTO_COMPACT_CHECK_EVERY=8 chk sG1 >/dev/null
ck "gate: the first call does the work and seeds the tick" "sG1 0 100000" "$(tick)"

# The crossing happens while the gate is mid-window, which is the whole risk
# being taken. It must be missed now and caught within EVERY calls, below.
usage 250000 > "$T/t.jsonl"
ck "gate: a crossing inside the sample window is not seen yet" "" "$(AUTO_COMPACT_CHECK_EVERY=8 chk sG1)"
ck "gate: the skipped call only bumped the tick" "sG1 1 100000" "$(tick)"

i=0; out=""
while [ "$i" -lt 8 ]; do
  out="$(AUTO_COMPACT_CHECK_EVERY=8 chk sG1)"; i=$(( i + 1 ))
  [ -n "$out" ] && break
done
ck "gate: the crossing is caught within EVERY calls" "run the auto-compact runbook" "$out"
[ "$i" -le 8 ] && ok "gate: it took $i calls, not more than EVERY" \
               || bad "gate: it took $i calls, not more than EVERY" "took $i"

# Above the floor the gate must not sample at all: the escalate backstop has
# roughly 6600 tokens of runway before native compaction, under two calls at
# the measured p90 step. The nudge above left the tick holding 250000, which is
# over the floor, so this call must do the real work immediately.
ck "gate: the tick now holds a band figure, not a below-floor one" "sG1 0 250000" "$(tick)"
usage 290000 > "$T/t.jsonl"
ck "gate: in a band it checks every call, it does not sample" "STOP at the next safe point" \
   "$(AUTO_COMPACT_CHECK_EVERY=8 chk sG1)"

# Bad values take the config-error shape the ceiling takes at :74-76: fall back
# to the default and keep working, never fail the tool call. Asserting the tick
# advanced proves it fell back to 8 rather than to 0, to 1, or to a crash.
for badv in abc 0 -3 ''; do
  echo '{}' > "$AUTO_COMPACT_STATE_FILE"; usage 100000 > "$T/t.jsonl"
  AUTO_COMPACT_CHECK_EVERY="$badv" chk "sGB" >/dev/null 2>&1
  AUTO_COMPACT_CHECK_EVERY="$badv" chk "sGB" >/dev/null 2>&1
  ck "gate: interval '${badv:-<empty>}' falls back to the default" "sGB 1 100000" "$(tick)"
done

# (landmine 2) The malformed-payload guard is jq FAILING under pipefail plus the
# ERR trap. A gate that answered before that point would delete the guard while
# this file stayed green. The payload carries no session_id, so the gate can
# match no hint and must fall through to jq -- and the tick standing still is
# what proves it fell through rather than skipping.
echo '{}' > "$AUTO_COMPACT_STATE_FILE"; usage 100000 > "$T/t.jsonl"
AUTO_COMPACT_CHECK_EVERY=8 chk sG3 >/dev/null
printf 'not json at all' | AUTO_COMPACT_CHECK_EVERY=8 bash "$D/check.sh" >/dev/null 2>&1; rc=$?
[ "$rc" -eq 0 ] && ok "gate: malformed payload still exits 0 with sampling on" \
                || bad "gate: malformed payload still exits 0 with sampling on" "exit $rc"
ck "gate: malformed payload reached the jq guard, it was not skipped" "sG3 0 100000" "$(tick)"

# A tick the gate cannot trust must mean "do the work", never "stay quiet".
usage 250000 > "$T/t.jsonl"
printf '{"@ac-tick": "sG4 nonsense 100000"}\n' > "$AUTO_COMPACT_STATE_FILE"
ck "gate: an unparseable tick falls through to the real check" "run the auto-compact runbook" \
   "$(AUTO_COMPACT_CHECK_EVERY=8 chk sG4)"
printf '{"@ac-tick": "someone-else 1 100000"}\n' > "$AUTO_COMPACT_STATE_FILE"
ck "gate: another session's tick is not consumed" "run the auto-compact runbook" \
   "$(AUTO_COMPACT_CHECK_EVERY=8 chk sG5)"

# A tick the gate cannot PERSIST must also mean "do the work". The skip is only
# earned by a write that landed: under `set -e` a failed redirect would
# otherwise reach the ERR trap and exit 0, going silent for as long as the file
# stayed unwritable -- and the tick would never advance, so silent forever. The
# state file here is mid-window and below the floor, which is exactly the shape
# the gate wants to skip on.
usage 250000 > "$T/t.jsonl"
printf '{"@ac-tick": "sGW 1 100000"}\n' > "$AUTO_COMPACT_STATE_FILE"
if [ "$ROOT_USER" -eq 1 ]; then
  skip "gate: an unwritable tick falls through, it does not go silent" "uid 0 ignores chmod 444"
else
  chmod 444 "$AUTO_COMPACT_STATE_FILE"
  ck "gate: an unwritable tick falls through, it does not go silent" \
     "run the auto-compact runbook" "$(AUTO_COMPACT_CHECK_EVERY=8 chk sGW)"
  chmod 644 "$AUTO_COMPACT_STATE_FILE"
fi

# The gate hand-builds one JSON member, so it must not do that with an id it
# cannot trust. A quote in session_id would otherwise produce a broken file.
echo '{}' > "$AUTO_COMPACT_STATE_FILE"; usage 100000 > "$T/t.jsonl"
printf '{"session_id":"a\"b","transcript_path":"%s"}' "$T/t.jsonl" \
  | AUTO_COMPACT_CHECK_EVERY=8 bash "$D/check.sh" >/dev/null 2>&1
if jq -e 'type == "object"' "$AUTO_COMPACT_STATE_FILE" >/dev/null 2>&1; then
  ok "gate: a quote in session_id does not corrupt the state file"
else bad "gate: a quote in session_id does not corrupt the state file" "state is not parseable JSON"; fi

# F1 (round-2 review). A checkout with NO state file must still bootstrap. Both
# tick writers were guarded by `-s` and below the floor save() only fires for a
# session that already has an entry, so nothing ever created the file: the gate
# stayed false forever and a fresh checkout paid the expensive path for life.
# Every worktree is a fresh checkout -- state.json is gitignored -- so this was
# the whole win, absent exactly where most sessions run. Seeding `{}` here would
# hide the bug: that is the one shape that already bootstrapped.
rm -f "$AUTO_COMPACT_STATE_FILE"; usage 100000 > "$T/t.jsonl"
AUTO_COMPACT_CHECK_EVERY=8 chk sGF >/dev/null
ck "gate: a checkout with no state file seeds the tick on the first call" \
   "sGF 0 100000" "$(tick)"
AUTO_COMPACT_CHECK_EVERY=8 chk sGF >/dev/null
ck "gate: the second call on a fresh checkout is sampled out" "sGF 1 100000" "$(tick)"

# F2 (round-2 review). The hook declares itself fail-quiet. `>f 2>/dev/null`
# does not suppress a failed redirect: bash applies redirections left to right
# and reports the failure before the second one is in effect. This is the
# every-call path, so an unwritable state file leaked one shell error per tool
# call. The fix establishes the discard on the enclosing group.
usage 250000 > "$T/t.jsonl"
printf '{"@ac-tick": "sGE 1 100000"}\n' > "$AUTO_COMPACT_STATE_FILE"
if [ "$ROOT_USER" -eq 1 ]; then
  skip "gate: an unwritable tick falls through with no stderr noise" "uid 0 ignores chmod 444"
else
  chmod 444 "$AUTO_COMPACT_STATE_FILE"
  err="$(printf '{"session_id":"sGE","transcript_path":"%s"}' "$T/t.jsonl" \
          | AUTO_COMPACT_CHECK_EVERY=8 bash "$D/check.sh" 2>&1 >/dev/null)"
  chmod 644 "$AUTO_COMPACT_STATE_FILE"
  [ -z "$err" ] && ok "gate: an unwritable tick falls through with no stderr noise" \
                || bad "gate: an unwritable tick falls through with no stderr noise" "$err"
fi
echo '{}' > "$AUTO_COMPACT_STATE_FILE"

# ---- resume.sh ----
H="$T/tree/handoffs/auto"; mkdir -p "$H"; : > "$T/tree/CLAUDE.md"
export AUTO_COMPACT_ROOT="$T/tree"

echo '{"sX":{"nudged":true},"sY":{"nudged":true}}' > "$AUTO_COMPACT_STATE_FILE"
ck "resume: no handoff -> silent" "" "$(rsm sX)"
[ "$(jq -r 'has("sX")' "$AUTO_COMPACT_STATE_FILE")" = "false" ] \
  && ok "resume: re-arms own entry" || bad "resume: re-arms own entry" "entry survived"
jq -e '.sY.nudged' "$AUTO_COMPACT_STATE_FILE" >/dev/null \
  && ok "resume: leaves other sessions alone" || bad "resume: leaves other sessions alone" "clobbered sY"

: > "$H/2026-08-01-sX.md"; : > "$H/2026-08-24-sX.md"; : > "$H/2026-08-24-sOTHER.md"
ck "resume: newest dated handoff wins" "2026-08-24-sX.md" "$(rsm sX)"
ck "resume: names the verification owner" "docs/conventions/handoff-read-side.md" "$(rsm sX)"
ck "resume: ignores another session's file" "" "$(rsm sZ)"
ck "resume: finds handoff from a foreign cwd" "2026-08-24-sX.md" "$(cd "$T" && rsm sX)"
printf '%s' "$(rsm sX)" | jq -e '.hookSpecificOutput.hookEventName == "SessionStart"' >/dev/null 2>&1 \
  && ok "resume.sh emits a valid SessionStart envelope" \
  || bad "resume.sh emits a valid SessionStart envelope" "bad or unparseable JSON"

# The runbook's size bound writes `<date>-pt<NN>-<session>.md` parts and relies
# on the last glob match being the newest. Real session ids are hex and `p` sorts
# after every hex digit; `sX` sorts the other way, so this case needs a hex id.
# pt09 vs pt10 pins the two-digit rule (`pt10` < `pt2` in name order).
HEX=0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d
: > "$H/2026-08-24-$HEX.md"; : > "$H/2026-08-24-pt09-$HEX.md"; : > "$H/2026-08-24-pt10-$HEX.md"
ck "resume: newest pt<NN> part beats the base and earlier parts" "2026-08-24-pt10-$HEX.md" "$(rsm $HEX)"
rm -f "$H"/*-"$HEX".md

# (e) Without an in-script source guard this hook fires on every session start,
# deleting band state at high context and asserting a compaction that never
# happened. The settings matcher cannot be verified from inside the script.
echo '{"sX":{"nudged":true}}' > "$AUTO_COMPACT_STATE_FILE"
ck "resume: source=startup injects nothing" "" "$(rsm sX startup)"
jq -e '.sX.nudged' "$AUTO_COMPACT_STATE_FILE" >/dev/null \
  && ok "resume: source=startup leaves state alone" \
  || bad "resume: source=startup leaves state alone" "re-armed on a non-compact start"

rm -f "$H"/*-sX.md; : > "$H/sX.md"
ck "resume: legacy undated fallback" "auto/sX.md" "$(rsm sX)"

# (F21) Everything above sets AUTO_COMPACT_ROOT, so the payload-cwd and
# install-depth derivations — the actual mechanism — are never exercised.
unset AUTO_COMPACT_ROOT
ck "resume: derives root from payload cwd" "auto/sX.md" "$(rsm sX compact ",\"cwd\":\"$T/tree\"")"
FAKE="$T/tree/.claude/hooks/auto-compact"; mkdir -p "$FAKE"; cp "$D/resume.sh" "$FAKE/"
ck "resume: derives root from install depth" "auto/sX.md" \
   "$(cd / && printf '{"session_id":"sX","source":"compact"}' | bash "$FAKE/resume.sh")"
# (S3) Silence alone cannot distinguish "rejected the cwd" from "accepted it and
# found nothing there" — the F20 defect again. Plant a decoy at the bogus root so
# acceptance and rejection produce different strings.
mkdir -p "$T/handoffs/auto"; : > "$T/handoffs/auto/2026-08-24-sX.md"
ck "resume: rejects a cwd that is not this tree" "" "$(rsm sX compact ",\"cwd\":\"$T\"")"
ck "resume: rejects a bogus AUTO_COMPACT_ROOT too" "" "$(AUTO_COMPACT_ROOT="$T" rsm sX)"
export AUTO_COMPACT_ROOT="$T/tree"

# (F22) The legs must agree on the path: what check.sh tells the agent to write
# is what resume.sh looks for. Nothing above relates the two.
rm -f "$H"/*sX*.md
REL_EXPECT="handoffs/auto"
echo '{}' > "$AUTO_COMPACT_STATE_FILE"; usage 250000 > "$T/t.jsonl"
EMITTED="$(chk sX | jq -r '.hookSpecificOutput.additionalContext' | grep -o 'handoffs/auto/[^\`]*\.md')"
if [ -n "$EMITTED" ]; then
  mkdir -p "$(dirname "$T/tree/$EMITTED")"; : > "$T/tree/$EMITTED"
  # Assert the FULL relative path, not the basename: comparing basenames lets
  # resume.sh drop "$REL/" from the dated branch, which is F9 verbatim — the
  # very thing this case exists to prevent.
  ck "the path check.sh emits is the path resume.sh finds" "$EMITTED" "$(rsm sX)"
  rm -f "$H"/*sX*.md; : > "$H/sX.md"
  ck "the legacy branch emits a full path too" "$REL_EXPECT/sX.md" "$(rsm sX)"
else
  bad "the path check.sh emits is the path resume.sh finds" "no handoff path in the nudge"
fi

# (F24) Keep the fixtures when something failed — a failing run should not
# destroy its own evidence.
# Print the count rather than documenting one. A count written into prose is a
# state assertion over work that changes; this tree watched that drift six times
# in one day, including in this file's own header.
if [ "$FAIL" -eq 0 ]; then rm -rf "$T"; echo "PASS ($N checks)"
else echo "FAILURES ($N passed; fixtures kept: $T)"; exit 1; fi
