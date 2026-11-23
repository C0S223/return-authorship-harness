#!/bin/bash
# cloud-setup.sh -- managed cloud setup script
#
# Pasted verbatim into the managed cloud environment's setup-script field.
# Runs as root before Claude launches; must exit 0 within ~5 min; cached ~7
# days on success; idempotent.
#
# One job: make a bare `python` resolve, because this kit's commands and
# tests are run as `python` in places. It needs no network and reads no
# repository.
set -euo pipefail

echo "[cloud-setup] make 'python' resolve to python3"
# ponytail: a symlink in an existing PATH dir needs no network; skip if a
# bare `python` already resolves.
if command -v python >/dev/null 2>&1; then
  echo "[cloud-setup] python: OK (python already resolves: $(command -v python))"
elif command -v python3 >/dev/null 2>&1; then
  target="$(command -v python3)"
  linkdir=""
  for d in /usr/local/bin /usr/bin; do
    if [ -w "$d" ]; then linkdir="$d"; break; fi
  done
  if [ -z "$linkdir" ]; then
    echo "[cloud-setup] FAIL: no writable PATH dir found for a python symlink" >&2
    exit 1
  fi
  ln -sf "$target" "$linkdir/python"
  echo "[cloud-setup] python: OK (symlinked $linkdir/python -> $target)"
else
  echo "[cloud-setup] FAIL: neither 'python' nor 'python3' found on PATH" >&2
  exit 1
fi

echo "[cloud-setup] done"
