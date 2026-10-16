#!/bin/bash
# auto-compact resume — SessionStart. Two jobs: re-arm the bands for the
# post-compact window, and inject a pointer to this session's handoff if one
# exists. Fail-quiet: any failure -> silent exit 0.
#
# Why it does not read the context size here: the earlier version found (2026-07-02, ~4.7MB late)
# that the compaction summary and continuation payload append to the transcript
# AFTER this hook fires, so a size read here undercounts the new zero.
# check.sh's first call reads the true size instead.
#
# The source guard is IN THE SCRIPT, not only in the settings matcher. The earlier version relies
# on a matcher alone; this tree's existing SessionStart registration carries no
# matcher, so a hook appended to that block would fire on startup/resume/clear
# too — deleting band state at high context (spurious re-arm, duplicate nudge)
# and injecting the literal falsehood "resumed from compaction". Correctness
# should not live in a file this script cannot see. Register with the matcher
# AND keep this check.
set -euo pipefail
trap 'exit 0' ERR

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
STATE_FILE="${AUTO_COMPACT_STATE_FILE:-$SCRIPT_DIR/state.json}"
REL="handoffs/auto"          # must match check.sh's REL

INPUT="$(cat)"
SESSION="$(printf '%s' "$INPUT" | jq -r '.session_id // empty')"
[ -n "$SESSION" ] || exit 0
SOURCE="$(printf '%s' "$INPUT" | jq -r '.source // empty')"
[ "$SOURCE" = "compact" ] || exit 0

# Root resolution. check.sh hands the agent a path relative to the agent's cwd,
# which is the tree root; this leg must search that same place. The earlier version globs a bare
# relative path and so silently finds nothing whenever the hook's cwd is not the
# root — a silent failure of the one thing this leg is for. Anchoring to
# SCRIPT_DIR alone only re-keys that bug from cwd to install depth. So: take the
# payload's cwd (three installed hooks in this tree already trust it), fall back
# to install depth, and accept a candidate only if it actually looks like this
# tree. test_auto_compact.sh pins that the path check.sh emits is the path found
# here.
# The test override goes through the SAME validation as the other two, or the
# comment above is false for one branch and the suite exercises a code path the
# hook does not have.
ROOT=""
for c in "${AUTO_COMPACT_ROOT:-}" "$(printf '%s' "$INPUT" | jq -r '.cwd // empty')" "$SCRIPT_DIR/../../.."; do
  if [ -n "$c" ] && [ -f "$c/CLAUDE.md" ]; then
    ROOT="$(cd "$c" && pwd -P)"
    break
  fi
done

# Re-arm first, but never let its failure suppress the injection below — the earlier version's
# own header states that priority and then codes the opposite order.
#
# Divergence from the earlier version, deliberate: the earlier version assigns {pending: true}; its own sibling
# comments record that flag becoming write-only and needing a GC pass to collect
# flags nothing read. The load-bearing effect was the assignment dropping stale
# band flags, not the flag. Deleting the entry is identical for every reader and
# leaves no dead schema. Known cost: this leg now leaves no trace it ran, so
# "fired and found nothing" looks like "not installed". Accepted — the action
# log's one job is escape audit, not per-session liveness.
if [ -e "$STATE_FILE" ]; then
  RAW="$(cat "$STATE_FILE" 2>/dev/null || true)"
  printf '%s' "$RAW" | jq -e 'type == "object"' >/dev/null 2>&1 || RAW='{}'
else
  RAW='{}'
fi
printf '%s' "$RAW" | jq --arg s "$SESSION" 'del(.[$s])' > "$STATE_FILE.tmp.$$" \
  && mv -f "$STATE_FILE.tmp.$$" "$STATE_FILE" || rm -f "$STATE_FILE.tmp.$$" || true

[ -n "$ROOT" ] || exit 0

# Match this session's handoff. Prefer the NEWEST dated file (check.sh emits
# <date>-<session>.md, one per compacting day; dated names sort chronologically,
# so the last glob match is newest), else fall back to a legacy undated
# <session>.md. The dated glob requires a '-' immediately before <session>,
# which the legacy name lacks, so the two schemes stay disjoint and a blind [0]
# cannot pick a stale older file. session_id is a full UUID, so neither form can
# suffix-match another session's file. Strictly session-keyed, never a
# newest-file-in-directory heuristic: pointing a resumed session at some other
# session's handoff is worse than pointing it at nothing.
shopt -s nullglob
DATED=("$ROOT/$REL/"*"-${SESSION}.md")
shopt -u nullglob
HANDOFF=""
if [ "${#DATED[@]}" -gt 0 ]; then
  HANDOFF="$REL/$(basename "${DATED[${#DATED[@]}-1]}")"
elif [ -f "$ROOT/$REL/${SESSION}.md" ]; then
  HANDOFF="$REL/${SESSION}.md"
fi

# The convention owns verification; this hook identifies the session handoff.
if [ -n "$HANDOFF" ]; then
  jq -n --arg ctx "Session resumed from compaction. Read \`$HANDOFF\` — that exact file, no directory scan — before acting. Treat it as state and intent, not as fact. Read \`docs/conventions/handoff-read-side.md\` and apply its verification rules before relying on any claim. Work done between the handoff write and the compaction is not in it; the compaction summary covers that." \
    '{hookSpecificOutput:{hookEventName:"SessionStart",additionalContext:$ctx}}'
fi
exit 0
