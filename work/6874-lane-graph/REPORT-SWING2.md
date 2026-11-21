# Report, swing 2: lane 6874

Candidate: 25c7568, the round-1 repairs on c8c158e. The operator chose to apply both
round-1 repairs, with AR's option A.

## Repairs

- AR condition 1 (option A): `graphs/lane.md` step 3 now states precedence.
  - The in-round close and the wording-only close win where they fit.
  - Auto-repair takes only a BLOCK that is not a REFUSE and fits neither close.
  - The wording-only fallback names auto-repair.
  - The text is the grill's three replacements, verbatim.
- SE F1: `scripts/lane_overlap.py` refuses (exit 2, "PR file limit reached") when an open PR's
  file list reaches GitHub's 3000-file cap. `test_pr_file_limit_fails_closed` covers it: it
  passes on 25c7568 and fails on c8c158e's script.

## Corrections to the round-1 desk files

These files stay as committed; the corrections live here.

- **Builder:** the hub builds this lane by the operator's choice of the hub-builds option. The
  adaptations in `WORK-ORDER.md` are the hub's choices. That includes the budget ceiling
  raise to 15,100 bytes, which goes to the operator in the PR body.
- **Landing check:** the landing check sits in step 3 (`graphs/lane.md`, "The hub commits
  reviewer files into the lane"), not step 4.
- **Acceptance a:** the diff from c693f70 touches the 14 granted files plus this lane's desk
  and grills.
- **Policy paths:** `scripts/ci_policy_check.py --repo . --base c693f70` at 25c7568 prints
  these 14:
  - `.claude/agents/senior-engineer.md`, `.claude/skills/check-prs/SKILL.md`
  - `.github/CODEOWNERS`, `AGENTS.md`, `CLAUDE.md`
  - `graphs/lane.md`, `roles/senior-engineer.md`
  - `scripts/lane_overlap.py`, `scripts/lane_ready.py`
  - `scripts/test_claude_md_budget.py`, `scripts/test_codeowners.py`, `scripts/test_codex_support.py`
  - `scripts/test_lane_overlap.py`, `scripts/test_lane_ready.py`
- **Time bucket:** `1-4 h`.
- **Prior rulings:** `docs/adr/` holds two ADRs. 0001 is a hit, cited by the matcher
  paragraph. 0002 is a miss. Neither mentions round caps, auto-merge or overlap.
- **Overlap check:** it did not run for this lane, a departure from step 1. The open-PR list
  was read instead, and it was empty.

## Preflight at 25c7568

The suite passes, 46 of 46 suites.
