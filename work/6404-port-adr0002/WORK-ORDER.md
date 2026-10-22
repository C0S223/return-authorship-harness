# Work order: lane 6404, port ADR 0002 rules pass and goal done-line rewrite to the template (base c26fb2d)

**Goal and source.** Bring the template up to date with two generic changes that landed first
in the operator's private downstream copy: ADR 0002's rules pass (lift the settings denies the
operator never ruled) and the goal-prompt-generator done-line rewrite. Board 6404. Operator
ruling 2026-10-21 (verbatim): "Yes: ADR 0002 should be the template default. Draft a port list
for the template repo covering bucket B (rules pass, goal done-line rewrite), and leave out the
instance-only items." The same day the operator directed that this port run as a cloud session
on this repository and approved its prompt, which names the repo, the branch, the push target
and the stop.

**Acceptance check, stated before the build.**
a. `git hash-object CLAUDE.md` prints f19559a78a499312d979e489a26a078ea54b254e; `cmp CLAUDE.md AGENTS.md` prints nothing.
b. `.claude/settings.json` `permissions.deny` has 18 entries.
c. The base-to-HEAD diff of the nine files adds no line matching the prompt's scrub pattern
   (board ids, downstream shas, the downstream repo's names, lane or board numbers).
d. `python3 scripts/run_tests.py` passes all suites.
e. The two reviews below stamp APPROVE.

**Files the builder may edit:** `.claude/settings.json`, `CLAUDE.md`, `AGENTS.md`,
`docs/enforcement/CLAUDE.md`, `.claude/agents/adversarial-reviewer.md`,
`scripts/test_contract_sync.py`, `scripts/test_codex_support.py`,
`.claude/skills/goal-prompt-generator/SKILL.md`, `docs/adr/0002-lift-unruled-settings-denies.md` (new).
Everything else is frozen.

**Builder:** the hub. It applies the given patch and ADR text only and authors nothing new.
**Estimated human time:** `<15 min`.

**Blast radius:** `scripts/run_tests.py` (full suite). Policy paths throughout, so this is a
policy lane: `operator-merge` is red by design and the operator merges.

**Reviewers:** `adversarial-reviewer` (mid, sonnet; prose and leaks: the contract pair, the
enforcement doc, the reviewer definition, the ADR, the skill), one round. `senior-engineer`
(mid, sonnet; settings and the two test scripts, running the suite), round cap per lane.md.

**Outside effects:** push `lane-6404` to origin; one draft PR into `main`, no auto-merge.
Both named in the approved prompt. Deletes: none.

**Prior mechanisms searched:** lane 6189's port desk (shape; hit). No scrub gate here, so the
leak check is the reviewer plus check c.
