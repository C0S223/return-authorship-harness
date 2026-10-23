tests/test_session_start.py: added bare-repository and .git subtests pinning the GIT_OK probe.
Each subtest proves --git-dir succeeds, --show-toplevel fails, and origin/HEAD is absent.
All four non-git fixtures now prove discovery fails with the ceiling environment used by the hook.
work/6182-git-ok-pin/REPORT.md: added this verification record.
The hook is unchanged; all baseline copies and mutations were made under /tmp.
Initial python3 tests/test_session_start.py: FAILED (errors=8), inherited SSH commit signing.
Subsequent checks used GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=commit.gpgsign GIT_CONFIG_VALUE_0=false.
PYTHONDONTWRITEBYTECODE=1 was also set for final suite commands.
python3 /tmp/lane-6182-_c748aoq/check.py: ALL EXPECTED RESULTS CONFIRMED.
  Copied baseline tests against scratch --show-toplevel mutant: Ran 28 tests; OK.
  New test against that mutant: Ran 1 test; FAILED (failures=2), one per root type.
  New test against copied original hook: Ran 1 test; OK.
  Copied baseline tests with TMPDIR inside a scratch Git checkout: FAILED (failures=2).
  Updated tests under the same nested TMPDIR: Ran 29 tests; OK.
python3 tests/test_session_start.py: Ran 29 tests; OK.
TMPDIR=/tmp/lane-6182-_c748aoq/containing-repo/tmp python3 tests/test_session_start.py: 29 tests; OK.
python3 scripts/run_tests.py: 40 suites: 40 pass, 0 fail, 0 skip (9 tests skipped inside 4 passing suites).
git diff --check: passed.
Changes remain uncommitted for the named senior-engineer review; no publishing performed.

Hub verify (outside the sandbox, no signing override): `python3 tests/test_session_start.py` -> `Ran 29 tests ... OK`;
with `TMPDIR` inside a fresh `git init` folder -> `OK`; scratch copy with `--show-toplevel` at hook :22 ->
`FAILED (failures=2)`.
