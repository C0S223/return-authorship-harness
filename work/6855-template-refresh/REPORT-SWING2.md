# Report: lane 6855, swing 2, filed by the hub

Candidate d9c3914 on base 541929d (work order 5131731). The history was rebuilt before the
first push, on the operator's ruling "Squash, keep r1 reviews (Recommended)": earlier commits
carried source-copy text that later commits removed. The lane now holds the work order, one
candidate commit, the desk files and the round-1 reviews, the reviews byte for byte. The shas
in `REPORT.md`, `DID.md`, `DID-SWING2.md` and both round-1 reviews name pre-squash commits that
were never pushed. Round 1 graded the pre-squash candidate; d9c3914 differs from it only by the
repairs below.

**Operator rulings this swing (verbatim):** "Full repair, exclude repos (Recommended)";
"Verify + extra AR pass"; "Squash, keep r1 reviews (Recommended)".

**Repairs since round 1.** The hub applied adversarial-reviewer conditions 1-4, 6 and 7 as stated;
the builder applied condition 5. Polish notes 1-5 and 8 are applied. Note 6 is a contract
edit outside this lane. Note 7 is answered here: the contract pair changes by one §3 sentence
added, one removed and a parenthetical narrowed, and by one §4 sentence replaced.
senior-engineer findings: F1, by the builder: the harness's own dirty count now excludes `repos/`. `.gitignore`
is unchanged; an earlier operator ruling keeps the `repos/` ignore line instance-only. F2, by the builder:
comments only. F3 is condition 1. Red/green lines: `DID-SWING2.md`.

**Hub verification pass** (read-only, six agents: two leak sweeps, path resolution,
contradictions, acceptance check a, completeness critic). Fixed before freeze: two stray
periods left by the scrub (a `scripts/prepush_check.py` docstring, a
`.claude/hooks/session-close.sh` comment), a host-specific article in
`tests/test_filetool_scope.py`, two decision labels with no record in this tree in
`scripts/test_stamp_check.py`, and two overlong `graphs/lane.md` lines. Acceptance check a
held for the eight files round 1 did not rebuild and for the prose files.

**Checks on d9c3914.** `python3 scripts/run_tests.py` gives `44 suites: 44 pass, 0 fail, 0 skip
(20 tests skipped inside 6 passing suites)`; `cmp CLAUDE.md AGENTS.md` prints nothing;
`ci_policy_check --base 541929d --head d9c3914` gives `RESULT: FAIL (32 policy path(s))`, exit 1
(policy lane, by design).

**Open, not fixed here.** Unchanged lines in tension with the new close rule (§3 close-request
push, §4 no handoff file with board and memory connected):
- `.claude/skills/claim/SKILL.md:77-79`
- `graphs/lane.md:5` and `:289-292`
- `graphs/grill.md:5` and `:38-43`
- `ONBOARDING.md:75-77`

`.claude/skills/check-prs/SKILL.md:70-72` still cites the old stamp-voiding rule. The source copy carries the same lines. Put to the operator.

**Residuals.** The two uid-scratchpad cases in each of `tests/test_filetool_scope.py` and
`tests/test_shell_scope.py` skip where the temp directory is `/tmp`, as on Linux CI, so CI does
not prove them; they ran red, then green, with `TMPDIR` set elsewhere. `scripts/test_claude_md_budget.py`
has 9 bytes of headroom. `PYTHONUTF8` in `.claude/settings.json` has no recorded reason in this
tree. Every commit carries the session attribution trailer, as on base.
