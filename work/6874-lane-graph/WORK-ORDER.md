# Work order: lane 6874, lane graph and reviewers (base c693f70)

Item: board 6874. Builder: hub. Policy lane: the operator granted the ten policy paths below for
this port, by name; the push, the PR and its ready mark are per-target approvals, and the
operator merges.

## What lands

Mechanism changes proven in the source copy, ported generic:

- Review round caps: up to five rounds for prose and for code, with auto-repair when a BLOCK
  states an exact repair for every condition (`graphs/lane.md`, step 3, Round caps).
- One up-front policy grant per lane, and asking before a matcher change (`graphs/lane.md`,
  step 1).
- The ship step: the stamp line, the ready mark at lane end, waiting for the ready run, and
  "agents never merge" (`graphs/lane.md`, step 4).
- The wording-only close for prose lanes (`graphs/lane.md`, step 3).
- `scripts/lane_overlap.py`, run at dispatch (step 1), with its tests.
- Senior-engineer findings the operator deferred (`roles/senior-engineer.md`,
  `.claude/agents/senior-engineer.md`).
- `scripts/lane_ready.py`, the one way an agent arms auto-merge, with its tests, named in
  `CLAUDE.md` §3 (mirrored in `AGENTS.md`), `.github/CODEOWNERS` and the `check-prs` skill.

Not in this lane: the source copy's queue route, its §2 "attended" pointer (contract v2, a
later lane), and its paragraph on where harness changes land first.

## Files

Policy (the grant): `graphs/lane.md`, `roles/senior-engineer.md`,
`.claude/agents/senior-engineer.md`, `CLAUDE.md`, `AGENTS.md`, `.github/CODEOWNERS`,
`.claude/skills/check-prs/SKILL.md`, `scripts/test_claude_md_budget.py`,
`scripts/test_codex_support.py`, `scripts/test_codeowners.py`.

New, not policy: `scripts/lane_ready.py`, `scripts/lane_overlap.py`,
`scripts/test_lane_ready.py`, `scripts/test_lane_overlap.py`.

Desk: `work/6874-lane-graph/`. Reviews: `grills/*-lane-6874-*`.

## Adaptations

- Dated ruling quotes and private board or lane ids are dropped from the ported text.
- The template's cloud-audit exception (`handoffs/auto/`) in step 4's landing check, and its
  "a human is present in every session" line, stay as they are.
- `CODEOWNERS` keeps the `@OWNER` placeholder.
- The budget ceiling goes from 15,000 to 15,100 bytes (total 15,050 after §3's clause), and
  the contract pin in `scripts/test_codex_support.py` moves to the new `CLAUDE.md` blob.

## Acceptance

a. `git diff c693f70 <candidate>` touches only the files above.
b. `graphs/lane.md` matches the source copy's version except for the three excluded passages
   and the adaptations above.
c. `cmp CLAUDE.md AGENTS.md` is clean, and `python3 scripts/run_tests.py` passes.
d. The ported text names no private repository, person, board id other than this lane's, or
   dated ruling.
e. Reviews: `adversarial-reviewer` on the prose, `senior-engineer` on the code.
