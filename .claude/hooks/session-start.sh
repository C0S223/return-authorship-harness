#!/bin/bash
# session-start advisory — main-tree branch + dirty warning + today's action-log
# tail as the situation line ( run-header detection deleted, run mode
# dead). Warn-only; stdout is injected as context. Fail-quiet.
# Injection is best-effort (contract §4): doubt = read the full log.
#
# ROOT is this checkout (CLAUDE_PROJECT_DIR, else the tree above this file), so
# BRANCH is the branch of the checkout the session runs in (state is per
# checkout). An earlier version reported the SHARED tree; a
# session launched in the main tree still gets exactly that. The
# wording below says so, because "on 'x', not <default>" read as a statement about
# the session, which it never was.
set -euo pipefail
trap 'exit 0' ERR

ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"

BRANCH="$(git -C "$ROOT" branch --show-current 2>/dev/null || echo '?')"
DIRTY="$(git -C "$ROOT" status --porcelain 2>/dev/null | wc -l | tr -d '[:space:]')"
# Both arms use `[ ] && echo`: under `set -e` a command BEFORE the final && is
# exempt, so a false test does not trip the ERR trap and swallow the rest of the
# hook. Verified 2026-08-30 on both branches of this condition.
# The default branch is origin/HEAD's target, never a guessed name, and only
# when that target is under origin and names a commit: the gates treat any
# other state as unresolved, so this line does too.
REF="$(git -C "$ROOT" symbolic-ref -q refs/remotes/origin/HEAD 2>/dev/null || true)"
DEFAULT=""
case "$REF" in
  refs/remotes/origin/?*) git -C "$ROOT" rev-parse -q --verify "$REF^{commit}" >/dev/null 2>&1 && DEFAULT="${REF#refs/remotes/origin/}" || true ;;
esac
[ -z "$DEFAULT" ] && echo "session-start: this checkout is on '$BRANCH'; origin's default branch is unknown (refs/remotes/origin/HEAD unset or dangling), so the gates refuse pushes. The human runs: git remote set-head origin --auto"
[ -n "$DEFAULT" ] && [ "$BRANCH" != "$DEFAULT" ] && echo "session-start: this checkout is on '$BRANCH', not the default branch '$DEFAULT'."
[ -n "$DEFAULT" ] && [ "$BRANCH" = "$DEFAULT" ] && echo "session-start: this checkout is on the default branch '$DEFAULT'. §3 — in a shared tree on the default branch, a commit IS a push for gating purposes. Isolate before shared-file work: git worktree add --no-track worktrees/<n> -b <branch> origin/$DEFAULT. Advisory only; nothing enforces this."
if [ "${DIRTY:-0}" -gt 0 ]; then
  echo "session-start: $DIRTY dirty file(s) — another session may be working here. Never stage or commit files you did not create."
fi

LOG="$ROOT/.agent-log/$(date +%F).md"
if [ -f "$LOG" ]; then
  echo "session-start: today's action-log tail (best-effort injection — doubt an authorization = read the full log):"
  tail -n 15 "$LOG"
fi
exit 0
