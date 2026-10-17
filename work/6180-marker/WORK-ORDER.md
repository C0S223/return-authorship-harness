# Work order: lane 6180, onboarding marker shared across worktrees (base 3083842)

**Goal.** R4 from PR #3: once the person ends or skips the tour, the first-run offer must not
come back in a lane worktree. Operator ruling "Main tree, shared"; grant "Through draft PR",
which covers this policy edit of the three files below for this purpose. Item 6180.
Prior art: PR #3's hook block (session-start.sh, "First-run nudge"); no other mechanism finds
the main checkout. Estimated human time: **15 min-1 h**.

**Acceptance check (before the build):**
1. `.claude/hooks/session-start.sh` finds the main checkout: `cd` into `$ROOT`, then into the
   output of `git rev-parse --git-common-dir` (relative or absolute), and take `pwd`. If that
   folder's name is `.git`, MAIN is its parent; otherwise (a bare or separate git dir), or if
   git fails, MAIN is `$ROOT`. The marker counts if `.agent-log/onboarded` exists in MAIN or in
   `$ROOT` (an old per-checkout marker still counts). No git failure may end the hook early
   (`set -e` plus the ERR trap would drop the log tail); it stays warn-only, fail-quiet, and
   bash-3.2-safe (no `--path-format`, which needs git 2.31). Update the block's comment.
2. `tests/test_session_start.py` adds cases, each red when its branch leaves the hook:
   - a linked worktree made with a real `git worktree add` (pre-push committed first), marker
     only in the main tree: no line;
   - the same worktree with no marker anywhere: one line;
   - marker only in the linked worktree: no line;
   - a non-git folder: marker present, no line; absent, one line;
   - a repo made with `git init --separate-git-dir`: marker in the work tree, no line.
   All existing tests stay green.
3. `ONBOARDING.md` lines 6 and 12 (and :105 if needed): the marker lives at the root of the
   main checkout, the folder that holds the `.git` folder named by
   `git rev-parse --git-common-dir`; else the current checkout's root. Say plainly that
   one marker covers every lane worktree, and a fresh clone may be offered the tour once.
4. `python3 scripts/run_tests.py`: all pass.

**Builder may edit only:** .claude/hooks/session-start.sh, tests/test_session_start.py,
ONBOARDING.md, work/6180-marker/DID.md. All else frozen.

**Blast radius:** tests/test_session_start.py, tests/test_log_escape.py (bash 3.2 scan), full suite.
**Reviewers:** `senior-engineer` for the hook and test (round 1 of 2); `adversarial-reviewer`
for ONBOARDING.md (round 1 of 1). **Routing:** builder=mid/sonnet, reviewers=heavy/opus;
reason: 15 min-1 h bucket, but a policy hook with git-path and Git Bash portability traps.

**Returns:** DID.md (20 lines at most) committed on lane-6180, each path named, with the
commands run and their output; tree clean; no push. graph-run: lane 6180.
