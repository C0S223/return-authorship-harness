# Work order: lane 6178, first-run onboarding (base 7b54e93)

**Goal.** After setup works, the repo notices it is set up, runs a short onboarding that
teaches the grill, the lane and review, then starts a grill to find the first thing to work
on. Operator grant 2026-10-16: "Approve as described". Item 6178.

**Acceptance check (before the build):**
1. `.claude/hooks/session-start.sh` prints one plain line (for example "Setup is complete.
   Say 'onboard me' for a short tour.") only when both hold: `.githooks/pre-push` no longer
   holds the `OWNER/REPO` placeholder for `APPROVED_ORIGIN_URL`, and the checkout has no
   `grills/` and no `work/` directory. Otherwise it prints nothing new. It stays warn-only and
   fail-quiet, as the hook is today, and is bash-3.2-safe (the scan in
   tests/test_log_escape.py covers every hook).
2. `tests/test_session_start.py` covers placeholder present (no line), armed with `grills/`
   present (no line), armed with `work/` present (no line), and armed with neither (line).
   Each case fails if its condition is removed from the hook.
3. New `ONBOARDING.md`, written for the agent, runs a tour of a few short steps. One idea
   per message; each step ends with a plain question; the walk-through text goes in the
   agent's final visible message (the desktop app collapses mid-turn prose, as SETUP.md says).
   - what the harness is for, in two sentences;
   - the grill (graphs/grill.md): one question per decision, the person rules, pop-out
     answers, "(Recommended)" is the agent's pick, never a go on its own;
   - the lane (graphs/lane.md): work order, a builder, review by kind (senior-engineer for
     code, adversarial-reviewer for prose), stamps under grills/, preflight, a draft PR, who
     merges (policy paths: the person);
   - what the red checks on a PR mean, and when a red check is expected;
   - then it starts a grill: it asks the person's goals first, frame-first, per
     graphs/grill.md step 2, and ends by asking which first thing to work on.
   Every claim matches the tree. No new rule is invented here; it points to the graph files.
4. SETUP.md step 8 hands off to ONBOARDING.md. README.md says, in one line, that the tour
   follows setup and how to start it ("onboard me").
5. `python3 scripts/run_tests.py`: all pass, budget included.

**Builder may edit only:** ONBOARDING.md (new), SETUP.md, README.md,
.claude/hooks/session-start.sh, tests/test_session_start.py, work/6178-onboarding/DID.md.
All else is frozen, root CLAUDE.md included.

**Reviewers:** `senior-engineer` for the hook and test (round 1 of 2); `adversarial-reviewer`
for ONBOARDING.md, SETUP.md and README.md (round 1 of 1). **Returns:** DID.md (20 lines at
most) committed on lane-6178, each path named; tree clean; no push.
