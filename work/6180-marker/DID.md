# DID: lane 6180 (builder swing 1, sonnet)
Changed (no policy gate refused the edits; WebFetch not attempted, no outside fact needed):
- `.claude/hooks/session-start.sh`: MAIN = parent of the absolute `git rev-parse --git-common-dir` (cd+pwd, no --path-format) when that folder is named `.git`, else ROOT; nudge is silent if the marker is in MAIN or ROOT. Comment updated. Git calls end `|| true`.
- Extra fix, base bug: outside a git tree `git status | wc | tr` under pipefail tripped the ERR trap and ended the hook before the nudge and log tail; DIRTY now ends `|| true`.
- `tests/test_session_start.py`: class SessionStartSharedMarker, 9 tests (real `git worktree add` after committing pre-push, user.name/email set locally; non-git; `--separate-git-dir`).
- `ONBOARDING.md` (intro and Ending-or-skipping; :105 unchanged): marker at main checkout root, one marker covers all worktrees, a fresh clone may be offered once.
Red on base (base hook via `git show 3083842:...` into the scratchpad, same test file, tests/ copy beside it): 3 FAIL: linked_worktree_marker_only_in_main_no_line, non_git_folder_no_marker_one_line, non_git_folder_still_prints_the_log_tail. Green on mine: Ran 25, OK.
Tests that pass on base are guards of branches the base never had; shown red with mutants of my hook (scratchpad):
- parent of any git dir as MAIN: FAIL separate_git_dir_marker_beside_store_does_not_count.
- ROOT marker check dropped: FAIL linked_worktree_marker_only_in_linked_no_line.
- MAIN marker check dropped: FAIL linked_worktree_marker_only_in_main_no_line.
Commands:
- `python3 tests/test_session_start.py -v`: Ran 25 tests, OK.
- `python3 tests/test_log_escape.py`: Ran 40 tests, OK (skipped=2).
- `python3 scripts/run_tests.py`: 38 suites: 38 pass, 0 fail, 0 skip (9 tests skipped inside 4 passing suites).
Not done: hook not run under real Git Bash/macOS bash 3.2 (Linux bash only; log_escape bash-3.2 scan passed). No role-file overrides needed (role file is roles/super-doer.md, not projects/inbox/roles/).
