#!/bin/bash
# run-python.sh -- start a Python hook with whichever Python 3 this machine has.
#
#   bash "$CLAUDE_PROJECT_DIR/.claude/hooks/run-python.sh" "$CLAUDE_PROJECT_DIR/.claude/hooks/<hook>.py" [args...]
#
# WHY. settings.json used to call `python` directly. macOS ships only `python3`,
# so every Python hook exited 127, which Claude Code treats as a non-blocking
# error: each gate silently allowed. And a missing hook file made `python` exit
# 2, which blocks every tool call with an unhelpful message.
#
# WHAT IT DOES. Tries `python3`, then `python`, and keeps the first that really
# is Python 3: the Windows Store alias and an old Python 2 `python` both fail
# the probe and are skipped. Then it execs the hook, so stdin, stdout and the
# exit code pass through unchanged. The probe reads no stdin and prints nothing.
#
# WHEN IT CANNOT. No hook path, no such hook file, or no Python 3: one plain
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
    echo "run-python: hook file not found: $hook. Restore it (git checkout -- <that path>) or fix its line in .claude/settings.json." >&2
    exit 2
fi
shift

for py in python3 python; do
    command -v "$py" >/dev/null 2>&1 || continue
    if "$py" -c 'import sys; sys.exit(sys.version_info[0] != 3)' </dev/null >/dev/null 2>&1; then
        exec "$py" "$hook" "$@"
    fi
done

echo "run-python: no Python 3 found (tried python3, then python). Install Python 3, then restart Claude Code; until then this safety check blocks." >&2
exit 2
