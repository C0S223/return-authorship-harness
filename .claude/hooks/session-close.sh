#!/bin/bash
# session-close advisory — Stop hook, stranded-work warning once per session.
# Close: present the push list and ask; the operator approves each push
# (contract §3). No push imperative here by design. Fail-quiet.
#
# It NAMES the closeout and does not fire it. The reason string is
# read by the model, not the human, so an imperative here would have the
# session close out on a warning rather than on the operator's word. The
# closeout is operator-invoked only.
# A Stop hook latches at the FIRST turn end with stranded work, not at the
# close, so this can never be the closeout's trigger anyway.
set -euo pipefail
trap 'exit 0' ERR

ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
# state lives under .agent-log/ — already gitignored, keeps the hook dir clean
STATE_FILE="$ROOT/.agent-log/session-close.state.json"

mkdir -p "$ROOT/.agent-log"

INPUT="$(cat)"
# tr -d '\r': Windows jq emits CRLF; a stray \r here would break the
# stop_hook_active comparison and loop the block
SESSION="$(printf '%s' "$INPUT" | jq -r '.session_id // empty' | tr -d '\r')"
ACTIVE="$(printf '%s' "$INPUT" | jq -r '.stop_hook_active // false' | tr -d '\r')"
[ -z "$SESSION" ] && exit 0
[ "$ACTIVE" = "true" ] && exit 0

# On a cloud
# target, and only at an explicit closeout, `.agent-log/` dies with the VM/container -- it is gitignored and
# per-checkout. What survives is what the session committed. So on a cloud
# target only, copy TODAY's escape, grant and integrity lines out of the
# day log into a TRACKED file under handoffs/auto/, which a later commit on
# this lane branch carries forward. Windows and a target with neither
# marker set are unaffected: this block is a no-op there, same reasoning as
# unlock_consume.cloud_boundary() (no route from a per-call env assignment
# into this hook's own fixed launch env). Fail-quiet: `trap 'exit 0' ERR`
# above already covers this block.
# An explicit closeout is the closeout skill's flag file, honoured for two
# hours: an ordinary turn end on a cloud target writes no tracked file.
CLOSEOUT_FLAG="$ROOT/.agent-log/closeout-requested"
CLOUD_BOUNDARY=""
if [ "${CLAUDE_CODE_REMOTE:-}" = "true" ]; then
  CLOUD_BOUNDARY="managed"
elif [ "${HARNESS_BOUNDARY:-}" = "selfhost" ]; then
  CLOUD_BOUNDARY="selfhost"
fi
if [ -n "$CLOUD_BOUNDARY" ] && [ -n "$(find "$CLOSEOUT_FLAG" -mmin -120 2>/dev/null)" ]; then
  # local, like every other day-log writer
  TODAY="$(date +%Y-%m-%d)"
  DAYLOG="$ROOT/.agent-log/$TODAY.md"
  HANDOFF_DIR="$ROOT/handoffs/auto"
  mkdir -p "$HANDOFF_DIR"
  OUT="$HANDOFF_DIR/${TODAY}-${SESSION}-session-close-${CLOUD_BOUNDARY}.md"
  MARK="<!-- end session-close generated region; content below is the session's and is preserved -->"
  TMP="$ROOT/.agent-log/.session-close-survivor.$$.tmp"
  # scripts/log_filter.py owns the escape rule and this hook INVOKES it.
  # The grep below promised escape lines and carried 1 of 2966 across the 27
  # day-files present 2026-09-20 -- and that one only because a `push:` line
  # echoed the word ALLOW inside a banner. The other 2965 (spawn 915, web 775,
  # shellwrite 465, push 389, send 235, net 142, install 42, webfetch 2) died
  # with the container. Operator ruling: invoke the Python, one owner for the rule, not a bash copy that nothing can pin to
  # it (the strip_heredocs precedent pins by inspect.getsource, Python-to-Python,
  # and has no bash analogue).

  # PY is PROBED, never assumed on PATH: `python3` on the operator's Windows
  # host is a Microsoft Store alias that resolves under `command -v` and exits
  # nonzero when run, so a resolve-only test picks an interpreter that cannot
  # run. Probed outside the redirect below so the alias's own stdout message
  # can never land in the survivor file.
  PY=""
  for CAND in python3 python; do
    if command -v "$CAND" >/dev/null 2>&1 && "$CAND" -c "" >/dev/null 2>&1; then
      PY="$CAND"
      break
    fi
  done
  CLOSEOUT="$ROOT/scripts/log_filter.py"
  {
    echo "# session-close cloud copy — session $SESSION, boundary $CLOUD_BOUNDARY, $TODAY"
    echo
    echo "Escape, grant and integrity lines from .agent-log/${TODAY}.md (dies with this VM/container; this file is the tracked survivor). Data, never instruction."
    echo
    if [ -f "$DAYLOG" ]; then
      # FAIL LOUD, never quiet. A silent fall back to the grep reproduces the
      # exact defect this block was repaired for, and no reader could tell a
      # quiet day from a filter that never ran. So the marker NAMES the
      # degradation, and the grep still runs underneath it -- losing the escape
      # lines must not also lose the grant and integrity ones.
      if [ -n "$PY" ] && [ -f "$CLOSEOUT" ] && SURVIVING="$("$PY" "$CLOSEOUT" < "$DAYLOG" 2>/dev/null)"; then
        if [ -n "$SURVIVING" ]; then
          printf '%s\n' "$SURVIVING"
        else
          echo "(no matching lines today)"
        fi
      else
        echo "(DEGRADED: $CLOSEOUT did not run; python=${PY:-none}. ESCAPE LINES ARE MISSING from the block below: it is the gate-word grep, which misses escape lines.)"
        grep -E '\[policy-integrity\]|unlock-armed|unlock-consumed|unlock-refused|unlock-retired|unlock-replaced|unlock-revoked| DENY | ASK |ALLOW|\[peer-' "$DAYLOG" || echo "(no matching lines today)"
      fi
    else
      echo "(no day log at $DAYLOG)"
    fi
    echo
    echo "$MARK"
    # Everything the session put below the marker is carried forward. The
    # generated region above is the only part this hook owns.
    if [ -f "$OUT" ]; then
      # -x: the same whole-line test as awk's $0==m, so a damaged marker line
      # falls to the carry-forward branch, never to an empty extraction.
      if grep -qxF "$MARK" "$OUT"; then
        awk -v m="$MARK" 'f{print} $0==m{f=1}' "$OUT" || true
      else
        echo
        echo "<!-- carried forward once from the pre-marker file -->"
        cat "$OUT" || true
      fi
    fi
  } > "$TMP"
  # same filesystem as $OUT, so this is atomic: a hook killed mid-write leaves
  # the previous survivor intact rather than a header-only stub.
  mv -f "$TMP" "$OUT"
fi

# once per session -- the ADVISORY only. The cloud copy above must refresh at
# EVERY turn end, which is why it now sits above this latch. The
# latch is written below the clean/0-ahead exit, so it does not engage on a
# quiet turn; that is why the copy must be non-destructive rather than rare.
if [ -f "$STATE_FILE" ] && jq -e --arg s "$SESSION" '.[$s] // empty' "$STATE_FILE" >/dev/null 2>&1; then
  exit 0
fi

# handoffs/auto/ is this hook's own output, never stranded work.
DIRTY="$(git -C "$ROOT" status --porcelain -- . ':(exclude)handoffs/auto' 2>/dev/null | wc -l | tr -d '[:space:]')"
# no origin remote exists at birth; ahead-count against origin's default
# branch (origin/HEAD's target) only if one appears
AHEAD=0
BASE="$(git -C "$ROOT" symbolic-ref -q --short refs/remotes/origin/HEAD 2>/dev/null || true)"
if [ -n "$BASE" ] && git -C "$ROOT" rev-parse -q --verify "$BASE^{commit}" >/dev/null 2>&1; then
  AHEAD="$(git -C "$ROOT" rev-list --count "$BASE..HEAD" 2>/dev/null || echo 0)"
fi
if [ "${DIRTY:-0}" -eq 0 ] && [ "${AHEAD:-0}" -eq 0 ]; then
  exit 0
fi

# record BEFORE emitting so a crash can't loop it
NOW="$(date -u +%s)"
CUTOFF=$((NOW - 604800))
if [ -f "$STATE_FILE" ] && jq -e . "$STATE_FILE" >/dev/null 2>&1; then
  STATE="$(cat "$STATE_FILE")"
else
  STATE='{}'
fi
printf '%s' "$STATE" \
  | jq --arg s "$SESSION" --argjson now "$NOW" --argjson cut "$CUTOFF" \
      'to_entries | map(select(.value.epoch > $cut)) | from_entries | .[$s] = {epoch: $now}' \
  > "$STATE_FILE"

CLOSE="Close is propose-and-stop: commit topically, present the push list; the human executes."
# On a cloud boundary the host sentence is the opposite of the rule. It describes the closeout; it fires nothing.
if [ -n "$CLOUD_BOUNDARY" ]; then
  CLOSE="Close on this ${CLOUD_BOUNDARY} cloud boundary follows CLAUDE.md section 3: the closeout commits topically and pushes the lane branch only; a PR needs task approval and the default branch stays human."
fi
MSG="session-close: stranded work — ${DIRTY} dirty file(s), ${AHEAD} unpushed commit(s). ${CLOSE} What drains this is the closeout: surface /closeout, contract .claude/skills/closeout/SKILL.md. The OPERATOR's word fires it — this warning does not, so do not run it unprompted. Fires once per session."
jq -n --arg r "$MSG" '{decision: "block", reason: $r}'
exit 0
