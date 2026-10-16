#!/bin/bash
# log-escape — PostToolUse '*'. Appends escape-relevant event lines to the
# action log; the hook, not the agent, is the log's integrity layer
# (§4 of the contract). Never blocks. Fail-quiet.
# Event classes: spawns, shell net sends (curl/wget/npx and every gh call),
# pushes (git with `push` as a token, at any distance from the binary),
# installs, web-tool calls, and explicit out-of-tree shell writes (shell-scope
# --log, one predicate shared with the gate — approved escapes leave a trail).
# Unlock consumptions log from the hooks that consume them (steps 4+).
set -euo pipefail
trap 'exit 0' ERR
FAST=""
ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
# `read -d ''`, not `$(cat)`: no fork (the reasoning check.sh records at its
# own read). tool_name is then matched from the raw payload with a builtin,
# anchored to the top-level object before any `{` so a nested key cannot shadow
# it. The match is a hint, never the decider: an empty match falls through to
# jq; only a positive non-logged class exits early. Measured
# 2026-09-10: this hook spent 155-170 ms on every Read/Grep/Edit call to learn
# it had nothing to log, and PostToolUse was p50 914 ms of a real Bash call.
# stamp: sets NOW (HH:MM:SS) and DAY (YYYY-MM-DD), local time, with `date`.
# Bash's own clock format in printf needs bash 4.2; macOS's /bin/bash is 3.2, the
# printf failed, the ERR trap above exited 0, and pushes, gh calls, spawns and
# web calls logged nothing. Bash 3.2 syntax is all this file may use
# (tests/test_log_escape.py scans for later syntax). A failed or odd `date`
# still logs, at a placeholder time in undated.md, rather than drop the line.
stamp() {
  local ts
  ts="$(date '+%Y-%m-%d %H:%M:%S' 2>/dev/null)" || ts=""
  case "$ts" in
    [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]\ [0-9][0-9]:[0-9][0-9]:[0-9][0-9])
      DAY="${ts%% *}"; NOW="${ts#* }" ;;
    *) DAY="undated"; NOW="??:??:??" ;;
  esac
}
fast() { :; }; [ -f "$ROOT/.claude/hooks/log-escape-fast.sh" ] && . "$ROOT/.claude/hooks/log-escape-fast.sh"
INPUT=""
IFS= read -r -d '' INPUT || true
TOOL=""
if [[ "$INPUT" =~ ^[[:space:]]*\{[^{]*\"tool_name\"[[:space:]]*:[[:space:]]*\"([^\"]+)\" ]]; then
  TOOL="${BASH_REMATCH[1]}"
fi
# With jq absent every pipeline below dies on the ERR trap, and the event left
# no line at all (finish-run probe P1: pushes, spawns and web calls, 0 lines).
# A missing jq now leaves one raw line for any class this hook might log, so
# the lost dependency shows in the log instead of as silence.
if ! hash jq 2>/dev/null; then
  case "$TOOL" in
    Agent|Task|Bash|PowerShell|WebFetch|WebSearch|Write|Edit|NotebookEdit|*_trigger|"")
      RAWL="${INPUT//[$'\r\n']/ }"
      # A real payload opens with session_id and transcript_path, so the first
      # 160 bytes held no command (review SE-5): start at the first tool_input.
      [[ "$RAWL" =~ \"tool_input\"[[:space:]]*:[[:space:]]*(.*)$ ]] && RAWL="${BASH_REMATCH[1]}"
      [ -d "$ROOT/.agent-log" ] || mkdir -p "$ROOT/.agent-log"; stamp
      printf -- '- %s [log-escape] UNPARSED (jq missing): %s %s\n' "$NOW" "${TOOL:-?}" "${RAWL:0:160}" >> "$ROOT/.agent-log/$DAY.md"
      ;;
  esac
  exit 0
fi
case "$TOOL" in
  Agent|Task|Bash|PowerShell|WebFetch|WebSearch) fast ;;
  Write|Edit|NotebookEdit) fast ;;
  mcp__claude-code-remote__create_trigger|mcp__claude-code-remote__fire_trigger|mcp__claude-code-remote__delete_trigger) fast ;;
  mcp__Claude_Code_Remote__create_trigger|mcp__Claude_Code_Remote__fire_trigger|mcp__Claude_Code_Remote__delete_trigger) fast ;;  # September spelling
  "") TOOL="$(printf '%s' "$INPUT" | jq -r '.tool_name // ""' | tr -d '\r')" ;;
  *) exit 0 ;;
esac
# tr -d '\r' everywhere: Windows jq emits CRLF and a stray \r splits log lines

LINE=""
case "$TOOL" in
  Agent|Task)
    if [ -z "$FAST" ]; then KIND="$(printf '%s' "$INPUT" | jq -r '.tool_input.subagent_type // "unnamed"' | tr -d '\r')"; fi
    if [ -z "$FAST" ]; then DESC="$(printf '%s' "$INPUT" | jq -r '.tool_input.description // ""' | tr -d '\r')"; fi
    LINE="spawn: $KIND — $DESC"
    ;;
  Bash|PowerShell)
    if [ -z "$FAST" ]; then RAW="$(printf '%s' "$INPUT" | jq -r '.tool_input.command // empty' | tr -d '\r')"; fi
    CMD="${RAW//$'\n'/ }"
    # `*"git push"*` was a SUBSTRING test, so it saw only the two
    # words adjacent: every `git -C <abs> push` -- the form §3 mandates for
    # main-tree ops -- logged nothing, and `gh` matched no class at
    # all, so PR sends logged nothing either. Matching
    # runs on SCAN, the command with quoted spans blanked, because the same
    # substring filed three printf log appends on 2026-09-14 as pushes:
    # discussing an escape is not performing one.

    # READ git-guard.py's header before narrowing these. Anchors constrain a
    # token already matched; an enumeration of git's global options lists the
    # world and fails OPEN on everything unmodelled -- that attempt opened six
    # holes. `gh` is matched as a bare token rather than by subcommand for the
    # same reason: gh is a network client, so every invocation is egress, and
    # a verb list would miss the next verb.
    # The --log helpers below start through run-python.sh, never a bare `python`:
    # a host with only `python3` logged no shellwrite or filewrite line (lane 6177).
    NL=$'\n'
    SCAN_SRC="${RAW//\\$NL/ }"
    SCAN_SRC="${SCAN_SRC//$NL/;}"
    if [ -z "$FAST" ]; then SCAN="$(printf '%s' "$SCAN_SRC" | sed -E "s/'[^']*'|\"[^\"]*\"/ /g")"; fi
    if [ -z "$SCAN" ] && [ -n "$CMD" ]; then SCAN="$SCAN_SRC"; fi
    RE_PUSH='(^|[^-[:alnum:]_])git[^|;&]*[^-[:alnum:]_]push([^-[:alnum:]_]|$)'
    RE_GH='(^|[^-[:alnum:]_.])gh([^-[:alnum:]_/.]|$)'
    # classify <text>: sets CLASS to the escape class the text matches, or nothing.
    classify() {
      if [[ "$1" =~ $RE_PUSH ]]; then CLASS=push
      elif [[ "$1" =~ $RE_GH ]]; then CLASS=net
      else CLASS=""
        case "$1" in
          # npx is a runner whose traffic is a send (e.g. `npx wrangler deploy`), not an
          # install; filed under install: it hid from a `net:` audit.
          *curl*|*wget*|*Invoke-WebRequest*|*Invoke-RestMethod*|*"Start-BitsTransfer"*|*npx*)
                                       CLASS=net ;;
          *"npm install"*|*"npm i "*|*"pip install"*|*"uv add"*|*"uv pip"*|*"pnpm add"*|*"pnpm install"*|*winget*|*choco*)
                                       CLASS=install ;;
        esac
      fi
    }
    # Reviews 04 F1 / 05 F1, F2. The sed blanker knows nothing of heredocs, comments
    # or escapes, so one upstream apostrophe could swallow a real push, curl or
    # install whole and log NOTHING. Every class therefore falls back to the raw
    # text, marked `<class>?:`. The marker means "matched only where the blanker
    # saw a quoted span": EITHER a mention OR a real act the blanker swallowed --
    # the hook cannot tell which, so an auditor reads `?` lines, never skips them.
    # Reader: test_log_escape.py pins which shapes get the bare and the `?` marker.
    classify "$SCAN"; KIND="$CLASS"
    if [ -z "$KIND" ]; then
      classify "$SCAN_SRC"; KIND="$CLASS"
      [ -n "$KIND" ] && KIND="$KIND?"
    fi
    [ -n "$KIND" ] && LINE="$KIND: ${CMD:0:200}"
    if [ -z "$LINE" ]; then
      if [ -n "$FAST" ]; then LINE="$SS_LINE"; else LINE="$(printf '%s' "$INPUT" | bash "$ROOT/.claude/hooks/run-python.sh" "$ROOT/.claude/hooks/shell-scope.py" --log 2>/dev/null | tr -d '\r' || true)"; fi
    fi
    ;;
  Write|Edit|NotebookEdit)
    # File-tool writes outside the tree logged NOTHING, while the same
    # escape through Bash reached shell-scope --log at :96 -- one class of
    # approved escape left a trail and its twin did not. Measured 2026-09-20.
    # Read and Grep keep the fast exit above, so the 155-170 ms this header
    # records lands on writes only, not on every call.
    if [ -n "$FAST" ]; then LINE="$FT_LINE"; else LINE="$(printf '%s' "$INPUT" | bash "$ROOT/.claude/hooks/run-python.sh" "$ROOT/.claude/hooks/filetool-scope.py" --log 2>/dev/null | tr -d '
' || true)"; fi
    ;;
  mcp__claude-code-remote__*|mcp__Claude_Code_Remote__*)
    # Ids and sizes only, never the message text.
    if [ -z "$FAST" ]; then TID="$(printf '%s' "$INPUT" | jq -r '.tool_input.trigger_id // .tool_input.name // ""' | tr -d '\r')"; fi
    if [ -z "$FAST" ]; then LEN="$(printf '%s' "$INPUT" | jq -r '(.tool_input.text // "") | length' | tr -d '\r')"; fi
    LINE="peer-${TOOL##*__}: ${TID:0:80} bytes=$LEN"
    ;;
  WebFetch|WebSearch)
    if [ -z "$FAST" ]; then Q="$(printf '%s' "$INPUT" | jq -r '.tool_input.url // .tool_input.query // ""' | tr -d '\r')"; fi
    LINE="web: $TOOL ${Q:0:160}"
    ;;
esac
[ -z "$LINE" ] && exit 0

[ -d "$ROOT/.agent-log" ] || mkdir -p "$ROOT/.agent-log"; stamp
printf -- '- %s [log-escape] %s\n' "$NOW" "$LINE" >> "$ROOT/.agent-log/$DAY.md"
exit 0
