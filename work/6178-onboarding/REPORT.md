# Report: lane 6178 (builder super-doer; candidate after cf9cfca; base 7b54e93; four swings)

**Authority (operator, 2026-10-16/17).**
- "Approve as described": ONBOARDING.md, SETUP.md, README.md, session-start.sh and its test.
- Trigger fix: "Local marker, skip in cloud".
- Widened by "Onboarding + cascade rule" (graphs/lane.md), "Add it to PR3" (human-time
  bucket) and "yes, add the research notes to the PR" (docs/research/model-routing.md).

**Acceptance changes since WORK-ORDER.md.** These are recorded here, not in the order.
- Item 1's trigger is now: the pre-push guard is armed, `.agent-log/onboarded` is absent,
  and the session is not cloud (`CLAUDE_CODE_REMOTE=true` or `HARNESS_BOUNDARY=selfhost`).
  The grills/work condition is dropped: the template itself ships both folders, which the
  builder found.
- Added: the cascade model-routing rule in graphs/lane.md.
  - Tiers light, mid, heavy and top, with one mapping table.
  - The builder leans light, with a reason.
  - The reviewer runs one tier above, never below mid.
  - The builder escalates one tier per failed swing.
  - Top needs the person's yes; if they decline, the dispatch runs on heavy.
  - Receipt fields on every dispatch line, and a landing record.
- Added: a human-time bucket in the work order (SWE-bench buckets), cited by the tier reason.
- Added: a model-choice step in ONBOARDING.md (a mid-range hub at medium effort).
- Added: docs/research/model-routing.md. The hub wrote it from its research pass; it is
  reference, not rules.

**Hub reruns at cf9cfca.**
- Tree clean.
- `run_tests.py`: 38/38.
- The hook prints no nudge on this tree, because the placeholder is still in place.
- Scrub on the tree, file names and `7b54e93..HEAD` history: clean.

**Hub-authored defaults to grade.** The operator did not rule on these:
- the top tier needs the person's yes;
- a declined top dispatch runs on heavy;
- an unavailable tier means the next one up.

**Unverified.**
- The tour, and the marker it writes, have not been tried with a real person.
- GitHub and SWE-bench figures in the research doc come partly from secondary sources, as
  the doc says.

**What would falsify it.**
- The nudge firing in cloud, or with the placeholder still in place.
- The nudge never firing on a fresh local copy that has been set up.
- A cascade sentence that contradicts another lane.md rule.
- A research claim its own link does not support.
