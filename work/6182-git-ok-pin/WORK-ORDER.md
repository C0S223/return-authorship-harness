# Work order: lane 6182, pin the session-start GIT_OK probe (test lane)

**Source.** Board 6182 (follow-up from lane 6180 / PR #5; grill 10-17 1854d6fd: "Triage, lane later
(Recommended)"). `.claude/hooks/session-start.sh:22` sets GIT_OK with `git -C "$ROOT" rev-parse --git-dir`. No test
pins that probe: swapping it for `--show-toplevel` passes all 28 tests in `tests/test_session_start.py` (confirmed
at template main c26fb2d), yet `--show-toplevel` fails when ROOT is inside `.git` or a bare repository, which would
hide a real unset origin/HEAD there.
**Changes (tests only).**
1. Add a test that runs the hook with `CLAUDE_PROJECT_DIR` set to a git directory where `--git-dir` succeeds and
   `--show-toplevel` fails (a bare repository with no origin/HEAD, and/or a repo's `.git` folder), and asserts the
   hook's origin-unknown line ("origin's default branch is unknown") prints. It must fail with the probe swapped to
   `--show-toplevel` and pass at the current hook.
2. Fixture fragility (board note 2026-10-17): `test_non_git_folder_no_marker_one_line` (and every fixture that calls
   its folder "non-git") fails when TMPDIR is inside a git checkout. Make each such fixture prove its folder is
   outside any git tree: e.g. run the hook with `GIT_CEILING_DIRECTORIES` set to the fixture's temp root and assert
   `git -C <folder> rev-parse --git-dir` fails under the same environment before the hook runs. The fixtures must
   pass with `TMPDIR` set to a folder inside a git checkout.
**Acceptance.** `python3 tests/test_session_start.py` passes; the new test fails on a scratch copy of the hook
with `--show-toplevel` at :22 (mutation by hand in a temp copy, never in place); the non-git fixtures pass with
`TMPDIR=<a dir inside a git repo>`; `python3 scripts/run_tests.py` passes.
**May edit.** `tests/test_session_start.py`, `work/6182-git-ok-pin/REPORT.md` (new, at most 20 lines). Everything
else frozen; the hook itself does not change.
**Policy.** `tests/` is a policy path in this template: draft PR, the operator merges.
**Reviewer.** senior-engineer (code).
