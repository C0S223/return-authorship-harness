# Report: lane 6180, swing 3 (builder super-doer, heavy/opus; candidate 656dc7a; base 8a72bce)

**Authority.** Operator ruling "Second round (Recommended)": the builder fixes F1, adds the
proving test, corrects the separate-git-dir comment and pins relative-path resolution;
senior-engineer round 2 follows. Hook and test only; ONBOARDING.md stays as approved.
Tiers: builder=heavy/opus (swing 1 failed review), reviewer=heavy/opus, reason "top
declined" (operator ruling "Decline top, heavy (Recommended)").

**What changed (DID-SWING3.md, checked against the diff).**
- Hook: `GIT_OK` is set only when `git -C "$ROOT" rev-parse --git-dir` succeeds; the three
  origin/HEAD branch lines print only when it is set. With working git, output is unchanged.
- Hook comment: MAIN is the parent of the absolute common dir when that folder is `.git`
  (so a bare or separate git dir at `proj/.git` gives `proj`), otherwise ROOT, and ROOT when
  git fails; a relative answer is resolved with cd ROOT, cd, pwd.
- Tests: class SessionStartNoOriginClaimWithoutGit (non-git folder; a real linked worktree
  with origin/HEAD set, run with no git on PATH and with git linked to `false`, after a
  working-git control) and test_relative_common_dir_from_a_subfolder_resolves_against_root.

**Hub reruns at 656dc7a.** Tree clean; diff holds exactly the three scope paths.
- `tests/test_session_start.py`: 28 tests OK. `tests/test_log_escape.py`: OK (skipped=2).
  `scripts/run_tests.py`: 38/38.
- Red on the 8a72bce hook beside this test file (scratch copy): FAILED (failures=3).
- Builder reports M8 and M9 each red on the relative-path test, and a GIT_OK-never-set
  mutant red; a real dubious-ownership worktree printed only the log tail, rc 0.

**For the reviewer.** F1 closure, the new tests' power, and whether gating on `rev-parse
--git-dir` hides a real unset origin/HEAD in any state where git works. R2 (non-git folder
inside another repo) and R5 (TMPDIR inside a repo) are untouched. Still no real Git Bash
or macOS bash 3.2 run.

**What would falsify it.** The "unset or dangling" line in any state where git cannot run
in ROOT; that line missing where git runs and origin/HEAD is unset or dangling; a relative
common dir resolved against the wrong folder.
