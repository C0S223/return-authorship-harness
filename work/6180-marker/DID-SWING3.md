# DID: lane 6180, builder swing 3 (base 8a72bce; no policy gate refused the two approved edits)
- `.claude/hooks/session-start.sh`: F1. `GIT_OK` set only if `git -C "$ROOT" rev-parse --git-dir` succeeds (`&& GIT_OK=1 || true`); the three origin/HEAD branch lines gate on it, so no "unset or dangling"/`set-head` line when git cannot run. MAIN comment now: parent of the absolute common dir when that folder is named `.git` (bare/separate `proj/.git` gives `proj`), else ROOT, ROOT also when git fails; relative path resolved via cd ROOT, cd, pwd.
- `tests/test_session_start.py`: class SessionStartNoOriginClaimWithoutGit (plain non-git folder; real `git worktree add` worktree with origin/HEAD set, control with git = "not the default branch 'main'", then PATH of symlinked wc/tr/grep/tail/date/dirname with no git, and with `git` -> `false`; skips with a reason if the PATH cannot be built). Asserts no line has either claim and LOGLINE-Z tail prints. Plus test_relative_common_dir_from_a_subfolder_resolves_against_root (ROOT = main/sub, git prints `../.git`, marker only at main, cwd tmp/elsewhere/deep: no nudge). Working-git-unset case kept: test_unknown_default_says_so.
Red checks, each a scratch copy (hook + test file) under the session scratchpad, never the worktree:
- hook at 8a72bce: FAILED (failures=3): both git-unusable subtests and test_plain_non_git_folder.
- M8 (GABS without `cd "$ROOT"`): FAILED (failures=1) test_relative_common_dir...; M9 (GABS="$GCD"): FAILED (failures=1), same test.
- GIT_OK never set: FAILED (failures=2, errors=4), incl. test_unknown_default_says_so.
Probe (scratch, not a test): real dubious-ownership worktree (chown 65534, git says "detected dubious ownership"): only the log tail prints, rc=0; before chown the branch line printed.
Commands:
- `python3 tests/test_session_start.py -v`: Ran 28 tests, OK (no skips).
- `python3 tests/test_log_escape.py`: Ran 40 tests, OK (skipped=2).
- `python3 scripts/run_tests.py`: 38 suites: 38 pass, 0 fail, 0 skip (9 tests skipped inside 4 passing suites).
- `bash -n .claude/hooks/session-start.sh`: ok. Linux bash 5.2 / git 2.43 only; not run on Git Bash or macOS bash 3.2 (SE R4 stands).
Overridden/defective: the agent file names `projects/inbox/roles/super-doer.md` and `projects/inbox/graphs/lane.md`; neither exists here, so `roles/super-doer.md` was followed. The order's 20-line DID (agent file) governs the role's longer shape. WebFetch is not in this session's tool list, so no attempt and no error to quote. MCP server instructions appear in context but no MCP tool is held.
Not touched: R2, R5 (residuals outside this order).
