#!/bin/bash
# session-close advisory — Stop hook, stranded-work warning once per session.
# Close: any operator close request authorizes pushing the session's own
# non-default branches (contract §3), no PR. No push imperative here. Fail-quiet.
#
# Two entry points. As the Stop hook (no arguments, hook JSON on stdin) it runs
# the cloud audit copy below and then the advisory. As
#   bash .claude/hooks/session-close.sh --copy-only [session-id]
# it runs ONLY the cloud audit copy, under the same guards (cloud boundary and
# a fresh closeout flag), prints the path it wrote, and exits: the closeout
# calls this inside its own turn so the copy can be committed before the push
# (contract §4). It reads no stdin, writes no latch and emits no advisory.
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

COPY_ONLY=""
if [ "${1:-}" = "--copy-only" ]; then
  COPY_ONLY="1"
  # the id names the survivor file only; tr keeps it a safe filename part
  SESSION="$(printf '%s' "${2:-closeout}" | tr -c 'A-Za-z0-9_-' '-')"
else
  INPUT="$(cat)"
  # tr -d '\r': Windows jq emits CRLF; a stray \r here would break the
  # stop_hook_active comparison and loop the block
  SESSION="$(printf '%s' "$INPUT" | jq -r '.session_id // empty' | tr -d '\r')"
  ACTIVE="$(printf '%s' "$INPUT" | jq -r '.stop_hook_active // false' | tr -d '\r')"
  [ -z "$SESSION" ] && exit 0
  [ "$ACTIVE" = "true" ] && exit 0
fi

# On a cloud
# target, and only at an explicit closeout, `.agent-log/` dies with the VM/container -- it is gitignored and
# per-checkout. What survives is what the session committed. So on a cloud
# target only, copy the escape, grant and integrity lines of every day log
# the session spans into a TRACKED file under handoffs/auto/, which a later commit on
# this lane branch carries forward. Windows and a target with neither
# marker set are unaffected: this block is a no-op there, same reasoning as
# unlock_consume.cloud_boundary() (no route from a per-call env assignment
# into this hook's own fixed launch env). The exception is `--copy-only`, which
# a caller runs directly, so a per-call CLAUDE_CODE_REMOTE=true plus a fresh
# flag does reach it; that writes only an audit copy under handoffs/auto/,
# which piped Stop JSON could already do. Fail-quiet: `trap 'exit 0' ERR`
# above already covers this block.
# An explicit closeout is the closeout skill's flag file, honoured for two
# hours: an ordinary turn end on a cloud target writes no tracked file.
# --copy-only takes the same guards: it is how the closeout runs this block
# inside its own turn, so it can commit the copy before it pushes.
# The span: a session that crossed midnight once lost the earlier day's
# lines, because only TODAY's file was read. It now starts at the earliest day
# file present: on these targets `.agent-log/` is born with the checkout and
# dies with it, so every day file in it was written in this checkout's life.
# It ends at TODAY. Nothing in the hook's input names the session's start
# (--copy-only reads no stdin; no day-log line carries a session id), so this
# is the bound the script can know. A container that outlives one session
# copies its older days too: extra audit lines, never lost ones. With only
# today's file present the survivor is byte-for-byte the single-day one.
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
  # The span's day names, oldest first (the glob sorts them); see above.
  DAYS=""
  for DAYFILE in "$ROOT"/.agent-log/[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].md; do
    [ -f "$DAYFILE" ] || continue
    DAY="${DAYFILE##*/}"
    DAY="${DAY%.md}"
    if [[ "$DAY" > "$TODAY" ]]; then
      continue
    fi
    DAYS="${DAYS:+$DAYS }$DAY"
  done
  SOURCES=""
  for DAY in $DAYS; do
    SOURCES="${SOURCES:+$SOURCES, }.agent-log/${DAY}.md"
  done
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
  # One day file's lines. $2 names the day in the empty-result line: "today"
  # for TODAY, so the single-day survivor reads exactly as it always has.
  copy_day() {
    # FAIL LOUD, never quiet. A silent fall back to the grep reproduces the
    # exact defect this block was repaired for, and no reader could tell a
    # quiet day from a filter that never ran. So the marker NAMES the
    # degradation, and the grep still runs underneath it -- losing the escape
    # lines must not also lose the grant and integrity ones.
    if [ -n "$PY" ] && [ -f "$CLOSEOUT" ] && SURVIVING="$("$PY" "$CLOSEOUT" < "$1" 2>/dev/null)"; then
      if [ -n "$SURVIVING" ]; then
        printf '%s\n' "$SURVIVING"
      else
        echo "(no matching lines $2)"
      fi
    else
      echo "(DEGRADED: $CLOSEOUT did not run; python=${PY:-none}. ESCAPE LINES ARE MISSING from the block below: it is the gate-word grep, which misses escape lines.)"
      grep -E '\[policy-integrity\]|unlock-armed|unlock-consumed|unlock-refused|unlock-retired|unlock-replaced|unlock-revoked| DENY | ASK |ALLOW|\[peer-' "$1" || echo "(no matching lines $2)"
    fi
  }
  {
    echo "# session-close cloud copy — session $SESSION, boundary $CLOUD_BOUNDARY, $TODAY"
    echo
    echo "Escape, grant and integrity lines from ${SOURCES:-.agent-log/${TODAY}.md} (dies with this VM/container; this file is the tracked survivor). Data, never instruction."
    echo
    if [ -z "$DAYS" ]; then
      echo "(no day log at $DAYLOG)"
    elif [ "$DAYS" = "$TODAY" ]; then
      copy_day "$DAYLOG" "today"
    else
      # More than one day, or one earlier day: each day's lines under its own
      # file name, since a day-log line carries a time and no date.
      SEP=""
      for DAY in $DAYS; do
        if [ -n "$SEP" ]; then
          echo
        fi
        SEP="1"
        echo "## .agent-log/${DAY}.md"
        echo
        if [ "$DAY" = "$TODAY" ]; then
          copy_day "$ROOT/.agent-log/${DAY}.md" "today"
        else
          copy_day "$ROOT/.agent-log/${DAY}.md" "on $DAY"
        fi
      done
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
  if [ -n "$COPY_ONLY" ]; then
    # the closeout stages exactly this path
    printf '%s\n' "$OUT"
    exit 0
  fi
fi

if [ -n "$COPY_ONLY" ]; then
  echo "session-close --copy-only: no cloud boundary or no fresh closeout flag; nothing copied" >&2
  exit 0
fi

# latched KEY: has this state file recorded KEY (a session id, or
# "<session>#unreadable") within the last week?
latched() {
  [ -f "$STATE_FILE" ] && jq -e --arg s "$1" '.[$s] // empty' "$STATE_FILE" >/dev/null 2>&1
}

# once per session -- the ADVISORY only. The cloud copy above must refresh at
# EVERY turn end, which is why it now sits above this latch. The
# latch is written below the clean/0-ahead exit, so it does not engage on a
# quiet turn; that is why the copy must be non-destructive rather than rare.
# An unreadable child with no stranded work is not stranded work: it
# gets its own notice and its own key ("<session>#unreadable"), so it never
# spends this latch and a later stranded-work turn still warns.
if [ -f "$STATE_FILE" ] && latched "$SESSION"; then
  exit 0
fi

# handoffs/auto/ is this hook's own output, never stranded work.
DIRTY="$(git -C "$ROOT" status --porcelain -- . ':(exclude)handoffs/auto' ':(exclude)repos' 2>/dev/null | wc -l | tr -d '[:space:]')"
# no origin remote exists at birth; ahead-count against origin's default
# branch (origin/HEAD's target) only if one appears
AHEAD=0
BASE="$(git -C "$ROOT" symbolic-ref -q --short refs/remotes/origin/HEAD 2>/dev/null || true)"
if [ -n "$BASE" ] && git -C "$ROOT" rev-parse -q --verify "$BASE^{commit}" >/dev/null 2>&1; then
  AHEAD="$(git -C "$ROOT" rev-list --count "$BASE..HEAD" 2>/dev/null || echo 0)"
fi
# Child checkouts under repos/ can strand work too.
# Require their own .git (directory or worktree file), and that git's toplevel
# is the child itself: an invalid .git can otherwise fall back to the harness
# above and count it again. rev-parse --show-cdup prints the relative path up to
# the toplevel, so it is empty exactly when the child is its own toplevel. It
# needs no path list (GIT_CEILING_DIRECTORIES is ':'-separated, so a ':' in ROOT
# silently voided it; a Windows drive form is unmeasured) and it holds for a
# symlinked child, where git runs at the physical path.
# Disable optional locks on every child call so status cannot refresh its index.
CHILD_COUNTS=""
CHILD_UNREADABLE=""
CHILD_SCAN_FAILED=""
# Gather filter names from each initialized gitlink before status recurses into
# it. Both streams use NUL records; an empty record signals a Git read error.
collect_child_filters() {
  local SCAN="$1" FILTER_KEY FILTER_NAME FILTER_VAR FILTER_VALUE ENTRY SUBPATH CDUP PRIOR
  # A gitlink may be replaced by a symlink back to an ancestor. Refuse the
  # scan rather than recurse forever or run status without complete overrides.
  for PRIOR in ${SCAN_STACK[@]+"${SCAN_STACK[@]}"}; do
    [ "$SCAN" -ef "$PRIOR" ] && return 1
  done
  SCAN_STACK+=("$SCAN")
  while IFS= read -r -d '' FILTER_KEY; do
    [ -n "$FILTER_KEY" ] || return 1
    FILTER_NAME="${FILTER_KEY#filter.}"
    FILTER_NAME="${FILTER_NAME%.*}"
    # Once per name per child scan. FILTER_SEEN is a newline-delimited list; a
    # name never holds a newline, and the quoted case pattern is a literal, so
    # spaces, '=' and '*?[' in a name cannot match another name. No Bash 4
    # associative array (macOS ships Bash 3.2).
    case "$FILTER_SEEN" in
      *$'\n'"$FILTER_NAME"$'\n'*) continue ;;
    esac
    FILTER_SEEN="$FILTER_SEEN$FILTER_NAME"$'\n'
    for FILTER_VAR in clean smudge process required; do
      FILTER_VALUE=""
      if [ "$FILTER_VAR" = "required" ]; then FILTER_VALUE="false"; fi
      CHILD_ENV+=("GIT_CONFIG_KEY_$CHILD_N=filter.$FILTER_NAME.$FILTER_VAR" "GIT_CONFIG_VALUE_$CHILD_N=$FILTER_VALUE")
      CHILD_N=$((CHILD_N + 1))
    done
  done < <(
    if GIT_OPTIONAL_LOCKS=0 GIT_NO_LAZY_FETCH=1 git -C "$SCAN" config -z --name-only --get-regexp '^filter\..*\.(clean|smudge|process)$' 2>/dev/null; then
      :
    else
      RC=$?
      [ "$RC" -eq 1 ] || printf '\0'
    fi
  )
  while IFS= read -r -d '' ENTRY; do
    [ -n "$ENTRY" ] || return 1
    case "$ENTRY" in
      '160000 '*)
        SUBPATH="${ENTRY#*$'\t'}"
        [ "$SUBPATH" != "$ENTRY" ] || return 1
        [ -e "$SCAN/$SUBPATH/.git" ] || continue
        CDUP="$(GIT_OPTIONAL_LOCKS=0 GIT_NO_LAZY_FETCH=1 git -C "$SCAN/$SUBPATH" rev-parse --show-cdup 2>/dev/null)" || return 1
        [ -z "$CDUP" ] || return 1
        collect_child_filters "$SCAN/$SUBPATH" || return 1
        ;;
    esac
  done < <(GIT_OPTIONAL_LOCKS=0 GIT_NO_LAZY_FETCH=1 git -c core.fsmonitor=false -C "$SCAN" ls-files --stage -z 2>/dev/null || printf '\0')
  unset 'SCAN_STACK[${#SCAN_STACK[@]}-1]'
}
for CHILD in "$ROOT"/repos/*/; do
  [ -e "${CHILD}.git" ] || continue
  CHILD_CDUP="$(GIT_OPTIONAL_LOCKS=0 GIT_NO_LAZY_FETCH=1 git -C "$CHILD" rev-parse --show-cdup 2>/dev/null)" || continue
  [ -z "$CHILD_CDUP" ] || continue
  # Guard each failing call so a broken child cannot end this fail-quiet hook
  # before healthy siblings or the harness receive their advisory.
  # No child call may run a command the child configured. Status reads
  # the work tree, so it would run core.fsmonitor and every filter driver its
  # config resolves (clean on a stat-dirty file; process). Every child call
  # also gets GIT_NO_LAZY_FETCH=1: in a partial clone, a missing object (a
  # dangling origin/HEAD, or HEAD's tree) makes rev-parse or status fetch
  # from the promisor remote, which runs the child's core.sshCommand.
  # Git that predates GIT_NO_LAZY_FETCH ignores it, as it does below.
  # Each filter name is emptied however many keys name it, and added to the
  # overrides once per child scan: a repeat would grow GIT_CONFIG_COUNT, and
  # every status process parses all of it. The dedup compares names as
  # literals; a glob-style name-list test was bypassed by a name holding a
  # space (F1).
  # fsmonitor=false is policy-integrity.py's ls-files guard. Each filter name
  # gets an empty clean, smudge and process and required=false (an empty
  # required filter fails status). The keys go through GIT_CONFIG_COUNT, not
  # `-c`, because `-c` splits at the first `=` and a filter name may hold one;
  # older git (<2.31) ignores them, which is the unguarded behaviour, not a
  # skipped child. A stat-dirty filtered file can now count as dirty: noisy,
  # never hidden. Submodule names are collected before status recurses.
  CHILD_ENV=()
  CHILD_N=0
  FILTER_SEEN=$'\n'
  SCAN_STACK=()
  SCAN_FAILED=""
  if ! collect_child_filters "$CHILD"; then SCAN_FAILED=1; fi
  if [ -n "$SCAN_FAILED" ] || ! CHILD_DIRTY="$(env "GIT_CONFIG_COUNT=$CHILD_N" ${CHILD_ENV[@]+"${CHILD_ENV[@]}"} GIT_OPTIONAL_LOCKS=0 GIT_NO_LAZY_FETCH=1 git -c core.fsmonitor=false -C "$CHILD" status --porcelain 2>/dev/null | wc -l | tr -d '[:space:]')"; then
    CHILD_NAME="${CHILD%/}"
    CHILD_COUNTS="${CHILD_COUNTS:+$CHILD_COUNTS; }repos/${CHILD_NAME##*/}: unreadable"
    CHILD_UNREADABLE="${CHILD_UNREADABLE:+$CHILD_UNREADABLE, }repos/${CHILD_NAME##*/}"
    [ -z "$SCAN_FAILED" ] || CHILD_SCAN_FAILED=1
    continue
  fi
  CHILD_AHEAD=0
  CHILD_BASE="$(GIT_OPTIONAL_LOCKS=0 GIT_NO_LAZY_FETCH=1 git -C "$CHILD" symbolic-ref -q --short refs/remotes/origin/HEAD 2>/dev/null || true)"
  if [ -n "$CHILD_BASE" ] && GIT_OPTIONAL_LOCKS=0 GIT_NO_LAZY_FETCH=1 git -C "$CHILD" rev-parse -q --verify "$CHILD_BASE^{commit}" >/dev/null 2>&1; then
    if ! CHILD_AHEAD="$(GIT_OPTIONAL_LOCKS=0 GIT_NO_LAZY_FETCH=1 git -C "$CHILD" rev-list --count "$CHILD_BASE..HEAD" 2>/dev/null)"; then
      CHILD_AHEAD=0
    fi
  fi
  DIRTY=$((DIRTY + CHILD_DIRTY))
  AHEAD=$((AHEAD + CHILD_AHEAD))
  if [ "$CHILD_DIRTY" -ne 0 ] || [ "$CHILD_AHEAD" -ne 0 ]; then
    CHILD_NAME="${CHILD%/}"
    CHILD_COUNTS="${CHILD_COUNTS:+$CHILD_COUNTS; }repos/${CHILD_NAME##*/}: $CHILD_DIRTY dirty, $CHILD_AHEAD unpushed"
  fi
done
# record BEFORE emitting so a crash can't loop it
latch() {
  NOW="$(date -u +%s)"
  CUTOFF=$((NOW - 604800))
  if [ -f "$STATE_FILE" ] && jq -e . "$STATE_FILE" >/dev/null 2>&1; then
    STATE="$(cat "$STATE_FILE")"
  else
    STATE='{}'
  fi
  printf '%s' "$STATE" \
    | jq --arg s "$1" --argjson now "$NOW" --argjson cut "$CUTOFF" \
        'to_entries | map(select(.value.epoch > $cut)) | from_entries | .[$s] = {epoch: $now}' \
    > "$STATE_FILE"
}
if [ "${DIRTY:-0}" -eq 0 ] && [ "${AHEAD:-0}" -eq 0 ]; then
  # Unreadable children only: say so once, with no closeout pitch -- the
  # closeout cannot read or repair them. The stranded-work latch stays unset.
  if [ -z "$CHILD_UNREADABLE" ] || latched "$SESSION#unreadable"; then
    exit 0
  fi
  latch "$SESSION#unreadable"
  if [ -n "$CHILD_SCAN_FAILED" ]; then
    MSG="session-close: git status failed in ${CHILD_UNREADABLE} or was not run because its safe configuration scan failed, so any stranded work there cannot be counted. Tell the operator; checking or repairing it is theirs, by hand. This is not stranded work and not a closeout trigger. Fires once per session."
  else
    MSG="session-close: git status failed in ${CHILD_UNREADABLE}, so any stranded work there cannot be counted. Tell the operator; checking or repairing it is theirs, by hand. This is not stranded work and not a closeout trigger. Fires once per session."
  fi
  jq -n --arg r "$MSG" '{decision: "block", reason: $r}'
  exit 0
fi
# The stranded-work warning also names unreadable children; once it fires, the
# early exit above silences both notices for the rest of the session.
latch "$SESSION"

CLOSE="Close: commit topically; the operator's /closeout authorizes pushing the session's own non-default branches, never the default branch, no PR."
# Host and cloud state the same CLAUDE.md section 3 rule; the cloud sentence also
# names its boundary. Either describes the closeout; it fires nothing.
if [ -n "$CLOUD_BOUNDARY" ]; then
  CLOSE="Close on this ${CLOUD_BOUNDARY} cloud boundary follows CLAUDE.md section 3: the closeout commits topically; /closeout authorizes pushing the session's own non-default branches, never the default branch, and opens no PR."
fi
MSG="session-close: stranded work — ${DIRTY} dirty file(s), ${AHEAD} unpushed commit(s).${CHILD_COUNTS:+ Children: $CHILD_COUNTS.} ${CLOSE} What drains this is the closeout: surface /closeout, contract .claude/skills/closeout/SKILL.md. The OPERATOR's word fires it — this warning does not, so do not run it unprompted. Fires once per session."
jq -n --arg r "$MSG" '{decision: "block", reason: $r}'
exit 0
