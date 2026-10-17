#!/bin/bash
# run-python.sh -- start a Python hook with a Python 3.10 or newer from this machine.
#
#   bash "$CLAUDE_PROJECT_DIR/.claude/hooks/run-python.sh" "$CLAUDE_PROJECT_DIR/.claude/hooks/<hook>.py" [args...]
#
# WHY. settings.json used to call `python` directly. macOS ships only `python3`,
# so every Python hook exited 127, which Claude Code treats as a non-blocking
# error: each gate silently allowed. And a missing hook file made `python` exit
# 2, which blocks every tool call with an unhelpful message.
#
# WHAT IT DOES. Tries `python3`, then `python`, and keeps the first that really
# is Python 3.10 or newer: the Windows Store alias, an old Python 2 `python` and
# Apple's Python 3.9 `python3` all fail the probe and are skipped, so a newer
# `python` behind them still runs. 3.10 is the floor the test suite needs, and one
# floor for hooks and tests means a machine that passes setup runs both. Then it
# execs the hook, so stdin, stdout and the exit code pass through unchanged. The
# probe reads no stdin and prints nothing. preflight.sh runs the same probe.
#
# WHEN IT CANNOT. No hook path, no such hook file, or no Python 3.10+: one plain
# line on stderr and exit 2, which Claude Code treats as a block and shows.
# A hook that crashes keeps its own exit code (1): the hooks answer a crash with
# their own fail-closed decision, and turning every rc 1 into a block would
# also block every prompt when a record-keeping hook breaks.
set -u

hook="${1-}"
if [ -z "$hook" ]; then
    echo "run-python: no hook file was named. Check this hook's line in .claude/settings.json." >&2
    exit 2
fi
if [ ! -f "$hook" ]; then
    echo "Safety check file missing: $hook. If this folder was moved or renamed, restart Claude Code from it; otherwise restore the file with git." >&2
    exit 2
fi
shift

for py in python3 python; do
    command -v "$py" >/dev/null 2>&1 || continue
    if "$py" -c 'import sys; sys.exit(sys.version_info < (3, 10))' </dev/null >/dev/null 2>&1; then
        exec "$py" "$hook" "$@"
    fi
done

echo "run-python: no Python 3.10 or newer found (tried python3, then python). Install Python 3.10 or newer, then restart Claude Code; until then this safety check blocks." >&2
exit 2
