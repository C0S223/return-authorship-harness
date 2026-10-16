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
# settings.json wires every command as  <interp> "$CLAUDE_PROJECT_DIR/<script>"
# so a project path with a space still resolves. The commands are read with jq
# (session-close and log-escape need it too, so its absence blocks here), and
# the script is everything after the interpreter, quotes removed.
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
# Each hook "command" value: "<interp> <script>"; check interpreter + script file.
cmds="$(jq -r '.. | objects | select(has("command")) | .command | strings' "$SETTINGS" 2>/dev/null)" || {
  echo "PREFLIGHT BLOCK: jq could not read $SETTINGS — cannot verify the gate layer." >&2
  exit 2
}
while IFS= read -r cmd; do
  [ -n "$cmd" ] || continue
  # expand the project-dir variable literally (no eval — the value is our own config, but keep it safe)
  cmd="${cmd//\$\{CLAUDE_PROJECT_DIR\}/$ROOT}"
  cmd="${cmd//\$CLAUDE_PROJECT_DIR/$ROOT}"
  interp="${cmd%% *}"
  script=""
  [ "$interp" = "$cmd" ] || script="${cmd#* }"
  script="${script//\"/}"
  command -v "$interp" >/dev/null 2>&1 || fail="$fail\n  interpreter '$interp' not found  (for: $script)"
  [ -z "$script" ] || [ -f "$script" ] || fail="$fail\n  script missing: $script"
done <<< "$cmds"

if [ -n "$fail" ]; then
  printf 'PREFLIGHT BLOCK: the gate layer is not fully runnable, so CLAUDE.md §8 cannot be trusted as live. Refusing every prompt until fixed.%b\n' "$fail" >&2
  exit 2
fi
exit 0
