# Work order: lane 6189, port lane 6187's Codex routing to the template (base 775d4b8)

**Goal and source.** Bring the template up to date with the generic part of lane 6187.
That lane landed first in the operator's private downstream copy. It
should have landed here first and cascaded down. Board 6189; operator ruling 2026-10-17
(grill F3, verbatim): "Port lane, leak review (Recommended)". The same grill reaffirmed
board 6169's direction: the template is upstream and changes cascade down.

**Acceptance check, stated before the build.**
1. `git diff 775d4b8 <candidate> -- graphs/lane.md docs/codex-enforcement.md` is byte-identical
   to the downstream copy's merged diff of the same paths from the same base sha (measured off-tree).
2. An adversarial-reviewer leak review stamps APPROVE: nothing in the two files names the
   operator, their accounts, private repos or other personal specifics, and the text is
   correct for a template user.

**Files the builder may edit:** `graphs/lane.md`, `docs/codex-enforcement.md`. Everything
else is frozen. The copy's lane-6187 records (`grills/`, `work/6187-*`) do not move.

**Builder:** the hub (the ruled option says so). It applies the diff only and authors nothing new.

**Estimated human time:** `<15 min`.

**Blast radius:** `scripts/run_tests.py` (full suite; covers the graph/doc budget and
reference tests). Policy paths: `graphs/**` and CI-gated `docs/codex-enforcement.md`, so
this is a policy lane. `operator-merge` is red by design and the operator merges.

**Reviewer:** `adversarial-reviewer` (prose, public), one round. No code, so no `senior-engineer`.

**Outside effects:** push `lane-6189` to origin C0S223/return-authorship-harness; one draft
PR into `main`. Both are approved by the ruled option. Deletes: none.

**Prior mechanisms searched:** board 6169 (upstream model; hit), 6164 scrub gate (parked;
not reachable from this session, so the leak check is the reviewer plus a grep).
