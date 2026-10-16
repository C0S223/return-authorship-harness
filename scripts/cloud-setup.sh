#!/bin/bash
# cloud-setup.sh -- managed cloud setup script
#
# Pasted verbatim into the managed cloud environment's setup-script field.
# Runs as root before Claude launches; must exit 0 within ~5 min; cached ~7
# days on success; idempotent.
#
# Step 1 arms the pre-push gate (core.hooksPath is set before Claude
# launches, never by a hook -- .git/config is a policy path). It does NOT
# assume the checkout is cwd: the script can run with cwd /home/user and no
# .git there. Three rules:
#   F2  an ancestor walk first -- cwd may be BELOW the checkout root.
#   F3  arm only a checkout whose origin matches this repo. Arming a
#       stranger's checkout is a silent mutation of someone else's config.
#   F1  never let a bad candidate kill the run: a dangling .git made
#       `git config` exit 128 and `set -e` took the environment down, which
#       is the very failure this script exists to stop.
# Finding no checkout is NOT fatal: the clone may post-date the setup step,
# so say the gate is unarmed, name the remedy, exit 0.
#
# Two operator UI steps this script cannot do: the environment's network
# level (None for boot 1, then Custom with exactly the hosts a failed probe
# names), and CLAUDE_CODE_REMOTE=true, which the platform sets itself.
set -euo pipefail

# Operator sets the default to this repository's owner/repo (Setup per target,
# docs/enforcement/CLAUDE.md). The placeholder matches no real checkout, so an
# unset value leaves the gate UNARMED.
REPO_MATCH="${CLOUD_SETUP_REPO_MATCH:-OWNER/REPO}"   # test seam

echo "[cloud-setup] step 1: locate this repo's checkout, then core.hooksPath=.githooks"

is_repo() { git -C "$1" rev-parse --git-dir >/dev/null 2>&1; }

# Identity, not substring: a substring match on `owner/repo` also matches
# `evil-owner/repo-mirror`, and arms it.
# Reduce the origin URL to owner/repo and compare it whole, case-folded:
# https://host/o/r.git, git@host:o/r and host/o/r/ all reduce to o/r.
# Ceiling: a LOCAL path ending .../o/r reduces the same way, so a directory
# layout can still spoof identity -- accepted, since anyone who can shape the
# filesystem here has already won, and the cost is one armed hooksPath.
repo_id() {
  u="$(git -C "$1" remote get-url origin 2>/dev/null || true)"
  [ -n "$u" ] || return 1
  u="${u%/}"; u="${u%.git}"
  u="$(printf '%s' "$u" | tr ':' '/' | tr '[:upper:]' '[:lower:]')"
  repo="${u##*/}"
  rest="${u%/*}"
  owner="${rest##*/}"
  [ -n "$repo" ] && [ -n "$owner" ] || return 1
  printf '%s/%s' "$owner" "$repo"
}
is_ours() {
  want="$(printf '%s' "$REPO_MATCH" | tr '[:upper:]' '[:lower:]')"
  [ "$(repo_id "$1" || true)" = "$want" ]
}

root=""
stranger=""
top="$(git rev-parse --show-toplevel 2>/dev/null || true)"     # F2: ancestor walk
for d in "$top" "${CLAUDE_PROJECT_DIR:-}" "$PWD" /workspace /repo /home/user/* /workspace/* /root/*; do
  [ -n "$d" ] && [ -d "$d" ] || continue
  is_repo "$d" || continue                                      # F1: real repo only
  if is_ours "$d"; then
    if [ -z "$root" ]; then
      root="$d"
    else
      echo "[cloud-setup] step 1: NOTE another candidate ignored: $d (armed $root)"
    fi
  else
    [ -n "$stranger" ] || stranger="$d"
  fi
done

if [ -n "$root" ] && git -C "$root" config core.hooksPath .githooks 2>/dev/null; then
  echo "[cloud-setup] step 1: OK ($root -> $(git -C "$root" config --get core.hooksPath))"
else
  [ -z "$root" ] || echo "[cloud-setup] step 1: found $root but could not write its config"
  [ -z "$stranger" ] || echo "[cloud-setup] step 1: skipped $stranger -- origin does not match $REPO_MATCH"
  echo "[cloud-setup] step 1: NO CHECKOUT ARMED -- cwd $(pwd); searched toplevel, CLAUDE_PROJECT_DIR, cwd, /workspace, /repo, /home/user/*, /root/*"
  echo "[cloud-setup] step 1: visible here: $(ls -A 2>/dev/null | tr '\n' ' ')"
  echo "[cloud-setup] step 1: the gate is UNARMED. First session turn: 'auth-policy .git/config', then git config core.hooksPath .githooks"
fi

# The gates read origin's default branch from refs/remotes/origin/HEAD and fail
# closed without it; a fresh clone may not record it. One network read, never fatal.
if [ -n "$root" ]; then
  if git -C "$root" remote set-head origin --auto >/dev/null 2>&1; then
    echo "[cloud-setup] step 1: origin/HEAD -> $(git -C "$root" symbolic-ref -q --short refs/remotes/origin/HEAD)"
  else
    echo "[cloud-setup] step 1: origin/HEAD unset -- the gates fail closed until: git remote set-head origin --auto"
  fi
fi

echo "[cloud-setup] step 2: make 'python' resolve to python3"
# ponytail: a symlink in an existing PATH dir needs no network; skip if a
# bare `python` already resolves.
if command -v python >/dev/null 2>&1; then
  echo "[cloud-setup] step 2: OK (python already resolves: $(command -v python))"
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
  echo "[cloud-setup] step 2: OK (symlinked $linkdir/python -> $target)"
else
  echo "[cloud-setup] FAIL: neither 'python' nor 'python3' found on PATH" >&2
  exit 1
fi

echo "[cloud-setup] done"
