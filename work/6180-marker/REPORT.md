# Report: lane 6180 (builder super-doer, mid/sonnet; candidate dc04f2b; base 72a7cc0)

**Authority.** Operator ruling "Main tree, shared" and grant "Through draft PR", which covers
this policy edit of session-start.sh, test_session_start.py and ONBOARDING.md for R4.

**What changed (DID.md, checked against the diff).**
- Hook: MAIN is the parent of the absolute `--git-common-dir` when that folder is `.git`,
  else ROOT; the nudge is silent if the marker is in MAIN or ROOT. Comment updated.
- Hook, beyond the order's text: `DIRTY=` now ends `|| true`. Outside a git work tree the
  base hook ended at that line (pipefail plus the ERR trap), before the nudge and the log
  tail, so the order's non-git cases could not pass without it. The hub accepts it as in scope.
- Tests: class SessionStartSharedMarker, 9 cases (real `git worktree add`, non-git folder,
  `--separate-git-dir`).
- ONBOARDING.md: intro and "Ending or skipping" name the main checkout's root; :105 unchanged.

**Hub reruns at dc04f2b.** Tree clean; diff holds exactly the four scope paths.
- `tests/test_session_start.py -v`: 25 tests OK, the 9 new ones named ok.
- Red on base (base hook from 3083842 beside this test file, in a scratch copy): 3 FAIL
  (linked_worktree_marker_only_in_main_no_line, non_git_folder_no_marker_one_line,
  non_git_folder_still_prints_the_log_tail). The other new cases guard branches the base
  never had; the builder shows them red under three mutants of the new hook.
- `tests/test_log_escape.py`: OK (skipped=2). `scripts/run_tests.py`: 38/38.

**For the reviewers.**
- A tour run from a lane worktree now writes the ignored marker into the main tree.
  graphs/lane.md says the action log is the hub's only main-tree write; the operator's
  ruling names this write. Judge whether the tour text says enough.
- Not run under real Git Bash or macOS bash 3.2 (Linux bash only; the text scan passed).

**What would falsify it.** The nudge showing in a linked worktree when the main tree holds
the marker; a git failure dropping the log tail; a submodule or separate git dir treating
some unrelated parent folder as the main checkout.
