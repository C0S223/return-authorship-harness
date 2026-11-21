# Work order: lane 6874, lane graph and reviewers (base c693f70)

Item: board 6874. Builder: hub. Policy lane: the operator granted the fourteen paths below for
this port, by name; push, PR and ready mark are per-target approvals; the operator merges.

**Lands** (proven in the source copy, ported generic): five-round caps with auto-repair (step 3,
Round caps); one up-front policy grant, ask before a matcher change, and `scripts/lane_overlap.py`
at dispatch (step 1); the wording-only close (step 3); the ship step, the stamp line and "agents
never merge" (step 4); senior-engineer deferred findings; `scripts/lane_ready.py`, the one way
an agent arms auto-merge, named in `CLAUDE.md` §3 (mirrored in `AGENTS.md`), `CODEOWNERS` and
`check-prs`. **Not in this lane:** the source copy's queue route, its §2 "attended" pointer
(contract v2, a later lane), and its paragraph on where harness changes land first.

**Files (the grant):** `graphs/lane.md`, `roles/senior-engineer.md`,
`.claude/agents/senior-engineer.md`, `CLAUDE.md`, `AGENTS.md`, `.github/CODEOWNERS`,
`.claude/skills/check-prs/SKILL.md`, `scripts/test_claude_md_budget.py`,
`scripts/test_codex_support.py`, `scripts/test_codeowners.py`, and four new scripts,
`scripts/lane_ready.py`, `scripts/lane_overlap.py`, `scripts/test_lane_ready.py`,
`scripts/test_lane_overlap.py` (a file under `scripts/` is policy once it exists,
`.claude/hooks/policy-mutate.py:151-155`). Desk: `work/6874-lane-graph/`. Reviews:
`grills/*-lane-6874-*`.

**Adaptations:** dated ruling quotes and private board or lane ids are dropped; the template's
cloud-audit exception (`handoffs/auto/`) in step 4's landing check and its "a human is present
in every session" line stay; `CODEOWNERS` keeps `@OWNER`; the budget ceiling goes from 15,000
to 15,100 bytes (15,050 after §3's clause); the contract pin in `scripts/test_codex_support.py`
moves to the new `CLAUDE.md` blob.

**Acceptance:**
a. `git diff c693f70 <candidate>` touches only the files above and this desk.
b. `graphs/lane.md` matches the source copy's except the three exclusions and the adaptations.
c. `cmp CLAUDE.md AGENTS.md` is clean; `python3 scripts/run_tests.py` passes.
d. The ported text names no private repository, person, board id but this lane's, or dated ruling.
e. Reviews: `adversarial-reviewer` on the prose, `senior-engineer` on the code.
