tests/test_session_start.py: bare-repository and `.git`-folder subtests pin the hook's GIT_OK probe (`--git-dir`).
Each subtest proves --git-dir succeeds, --show-toplevel fails and origin/HEAD is absent, then reads the hook's line.
The four non-git fixtures use `non_git_env` (GIT_CEILING_DIRECTORIES) and assert discovery fails.
The hook is unchanged. Builder's sandbox runs (copies under /tmp) confirmed the same results as the hub's below.
Hub, round 1 (cb38fff, outside the sandbox):
  python3 tests/test_session_start.py -> Ran 29 tests ... OK; with TMPDIR inside a fresh git checkout -> OK.
  Scratch copy with `--show-toplevel` at hook :22 -> FAILED (failures=2).
  python3 scripts/run_tests.py -> 40 suites: 40 pass, 0 fail, 0 skip.
SE r1 (grills/2026-10-23-6182-se-r1.md) BLOCK F1: with safe.bareRepository=explicit in the host's global
  config, the new test failed (failures=2) although the hook behaved as intended.
Round 2: the new test's environment pins safe.bareRepository=all (GIT_CONFIG_COUNT/KEY_0/VALUE_0),
  for both its probes and the hook it runs.
Hub, round 2:
  python3 -B tests/test_session_start.py -> OK; with GIT_CONFIG_GLOBAL at an explicit config -> OK.
  `--show-toplevel` mutant at :22 -> FAILED (failures=2), with and without the explicit config.
  TMPDIR inside a git checkout -> OK. python3 -B scripts/run_tests.py -> 40 suites: 40 pass, 0 fail, 0 skip.
