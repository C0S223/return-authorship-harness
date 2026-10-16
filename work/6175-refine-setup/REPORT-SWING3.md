# Report: lane 6175, swing 3 (candidate 35cdaf0, base e63899f)

**Authority.** The grant is the same as before. Senior-engineer round 1 found F2 (C1), so a
second round is allowed. Adversarial-reviewer round 1 was ACCEPT with seven conditions, and
this swing is its in-round close.

**What changed (DID-SWING3.md, checked against the diff).**
- SE F2: tests with a fake Python 2, for both the launcher and preflight.
- SE F1: preflight checks the interpreter of every row again.
- SE M3: a test pins the "names no project file" block.
- The builder planted mutants M1, M2 and M3 and reverted F1; the tests catch all four.
- AR conditions 1-7 are applied to SETUP.md word for word.
- `e63899f..35cdaf0 --name-status`: preflight.sh, SETUP.md, tests/test_run_python.py and
  DID-SWING3.md. Nothing else.

**Hub reruns at 35cdaf0.**
- `git status --porcelain`: empty.
- `run_tests.py`: "38 suites: 38 pass, 0 fail, 0 skip".
- preflight on the tree: rc 0.
- Scrub on the tree, file names and `1b6703b..HEAD` history: clean.

**Hub fact check, AR C6.** GitHub's docs (about-rulesets) say: "Rulesets are available in
public repositories with GitHub Free and GitHub Free for organizations, and in public and
private repositories with GitHub Pro, GitHub Team, and GitHub Enterprise Cloud." The disclosure
the condition asks for is therefore correct.

**New fact for the AR resume (the builder's observation, unverified by the hub).** Both
git-guard and policy-mutate already allow `git config core.hooksPath .githooks`, on host and
cloud. If so, SETUP.md:78's instruction to have the person type `auth-policy .git/config` is
not what lets the step through.

**Builder's C3 probe.** git-guard refuses `git remote set-url setup-probe
https://example.invalid/probe.git` with CLAUDE_CODE_REMOTE both unset and set. Run with no
hook, it fails with "No such remote" and leaves the local config byte-identical.

**Departures, unchanged and judged sound by SE r1.** D1: the Stop hook exits 1 on a missing
file. D2: the auto-compact check.sh row is unguarded (pinned by test_failure_hooks.py).
