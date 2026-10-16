#!/bin/bash
# preflight — verify every configured hook command is runnable BEFORE the session
# trusts the gate layer. Wired FIRST on UserPromptSubmit and invoked
# through $CLAUDE_PROJECT_DIR so THIS check runs even when the other commands'
# hardcoded Windows paths are wrong on a Linux port. If any gate's interpreter is
# unresolvable or its script is missing, exit 2 — which UserPromptSubmit treats as
# blocking — so a session with dead gates fails LOUD instead of running while
# CLAUDE.md §8 still reads 'live' over silently-absent enforcement.
# Fail-closed: any uncertainty blocks. bash-present is assumed (the other .sh hooks
# already assume it); a bash-absent box is a deeper break this cannot cover.
#
# settings.json wires every command as a guard plus a run (lane 6175):
#   f="$CLAUDE_PROJECT_DIR/.claude/hooks/<x>.sh"; [ -f "$f" ] || { echo ... >&2; exit 2; }; bash "$f"
# and a Python hook as the same guard on run-python.sh, then
#   bash "$f" "$CLAUDE_PROJECT_DIR/.claude/hooks/<x>.py"
# Every quoted "$CLAUDE_PROJECT_DIR/..." path in a command must be a file; a
# command naming none is unreadable and blocks. Any command using run-python.sh
# needs a python3 or python that really is Python 3, probed as the launcher
# does. Every command's interpreter must also resolve, as before lane 6175:
# the first word after the guard, or the first word of an unguarded command,
# so a bare `python "..."` row on a machine without `python` still blocks.
# The commands are read with jq (session-close and log-escape need it too, so
# its absence blocks here).
set -u

ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
SETTINGS="$ROOT/.claude/settings.json"

if [ ! -f "$SETTINGS" ]; then
  echo "PREFLIGHT BLOCK: settings.json not found at $SETTINGS — cannot verify the gate layer; gates may be dead." >&2
  exit 2
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "PREFLIGHT BLOCK: jq not found — session-close and log-escape need it, and this check reads settings.json with it. Install jq." >&2
  exit 2
fi

fail=""
cmds="$(jq -r '.. | objects | select(has("command")) | .command | strings' "$SETTINGS" 2>/dev/null)" || {
  echo "PREFLIGHT BLOCK: jq could not read $SETTINGS — cannot verify the gate layer." >&2
  exit 2
}
command -v bash >/dev/null 2>&1 || fail="$fail\n  interpreter 'bash' not found"
need_python=""
path_re='"[$][{]?CLAUDE_PROJECT_DIR[}]?/([^"]+)"'
guard_re='^f="[^"]*"; \[ -f "[$]f" \] [|][|] [{] [^}]*[}]; (.*)$'
while IFS= read -r cmd; do
  cmd="${cmd%$'\r'}"
  [ -n "$cmd" ] || continue
  run="$cmd"
  [[ "$cmd" =~ $guard_re ]] && run="${BASH_REMATCH[1]}"
  interp="${run%% *}"
  command -v "$interp" >/dev/null 2>&1 || fail="$fail\n  interpreter '$interp' not found  (for: ${cmd:0:80})"
  rest="$cmd"
  found=""
  while [[ "$rest" =~ $path_re ]]; do
    found=1
    rel="${BASH_REMATCH[1]}"
    rest="${rest#*"${BASH_REMATCH[0]}"}"
    [ -f "$ROOT/$rel" ] || fail="$fail\n  script missing: $ROOT/$rel"
    case "$rel" in */run-python.sh) need_python=1 ;; esac
  done
  [ -n "$found" ] || fail="$fail\n  hook command names no project file, so it cannot be checked: ${cmd:0:80}"
done <<< "$cmds"

if [ -n "$need_python" ]; then
  py_ok=""
  for py in python3 python; do
    command -v "$py" >/dev/null 2>&1 || continue
    if "$py" -c 'import sys; sys.exit(sys.version_info[0] != 3)' </dev/null >/dev/null 2>&1; then
      py_ok=1
      break
    fi
  done
  [ -n "$py_ok" ] || fail="$fail\n  no Python 3 found (tried python3, then python): install Python 3, then restart Claude Code"
fi

if [ -n "$fail" ]; then
  printf 'PREFLIGHT BLOCK: the gate layer is not fully runnable, so CLAUDE.md §8 cannot be trusted as live. Refusing every prompt until fixed.%b\n' "$fail" >&2
  exit 2
fi
exit 0
