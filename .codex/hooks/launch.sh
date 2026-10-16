#!/bin/sh
# Run from the session cwd; never depend on Claude installation or env markers.
root=$(git rev-parse --show-toplevel) || { echo 'codex-harness: cannot resolve checkout' >&2; exit 2; }
script="$root/.codex/hooks/dispatch.py"
[ -f "$script" ] || { echo 'codex-harness: required hook file missing; restore it before continuing' >&2; exit 2; }
for py in python3 python python3.14 python3.13 python3.12 python3.11; do
    command -v "$py" >/dev/null 2>&1 || continue
    if "$py" -c 'import sys; sys.exit(sys.version_info < (3, 11))' </dev/null >/dev/null 2>&1; then
        exec "$py" "$script"
    fi
done
echo 'codex-harness: Python 3.11+ not found; choose an installed supported interpreter on PATH before activating hooks' >&2
exit 2
