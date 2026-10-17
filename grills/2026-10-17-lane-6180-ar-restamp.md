STAMP: APPROVE
REVIEWER: adversarial-reviewer
REVISION: 13e228d3928b11d903fe7613a69f79c342b6aa57

VERDICT: ACCEPT

Re-stamp of a voided kind (`graphs/lane.md:202-204`). Graded at lane-6180 @ 13e228d3928b11d903fe7613a69f79c342b6aa57. Prior APPROVE: `grills/2026-10-17-lane-6180-ar-r1-resume.md` at 79921bcb66b0f0254f5931d9f4ff58dfdb5078b8. Scope: the `.md` diff 79921bc..13e228d only, against questions (a), (b) and (c). The code's correctness is out of scope; senior-engineer round 2 is grading it. This pass does not count as a round.

## The item

**(a) Touches ONBOARDING.md or prose outside `work/6180-marker/` and my own grill? NO.**
- I have no git. I rely on the hub's pasted `git diff --stat 79921bc 13e228d -- '*.md'`, which lists three files: `grills/2026-10-17-lane-6180-ar-r1-resume.md` (my own), `work/6180-marker/DID-SWING3.md` and `work/6180-marker/REPORT-SWING3.md`. The pasted `stamp_check.py --head lane-6180` output agrees: it names only the two `A` desk files as non-grills additions.
- Both desk files exist at the named paths. Neither says ONBOARDING.md was edited. REPORT-SWING3.md:5 says "ONBOARDING.md stays as approved".

**(b) Do the desk files misstate what they report? NO merge-blocking misstatement.** Details are under Fact audit. The one imprecise line (DID-SWING3.md:14, "the agent file") is a note, not a condition; see Notes 1.

**(c) Anything that should not be in a public template? NO.**
- I searched both `*SWING3.md` files, case-insensitive, for `/home|Users|@|gmail|token|key|secret|password|matyb|mtb`. Zero matches.
- The only identifiers are lane numbers, short shas, tool versions (DID-SWING3.md:13), uid 65534 (the standard `nobody`, DID-SWING3.md:8) and two quoted operator ruling labels (REPORT-SWING3.md:3,7). None of them is private.

## Injection surface

None introduced. The two desk files are inert prose that nothing in the diff parses. The hub's report quotes builder output (REPORT-SWING3.md:23-24) and attributes it with "Builder reports", which is the structural label.

## Fact audit

1. REPORT-SWING3.md:10-11 and DID-SWING3.md:2 say `GIT_OK` is set only when `git -C "$ROOT" rev-parse --git-dir` succeeds, via `&& GIT_OK=1 || true`. UPHELD by `.claude/hooks/session-start.sh:21-22`.
2. REPORT-SWING3.md:11 and DID-SWING3.md:2 say the three origin/HEAD branch lines gate on GIT_OK. UPHELD by session-start.sh:38-40, where each line begins `[ -n "$GIT_OK" ] &&`. The sub-claim "with working git, output is unchanged" is under Claims I could not check, because the 8a72bce hook was not opened.
3. REPORT-SWING3.md:12-14 and DID-SWING3.md:2 describe the MAIN comment and resolution. UPHELD. The comment is session-start.sh:50-55. The code is :66-73: MAIN defaults to ROOT; GCD is taken from inside ROOT with `|| true`; GABS is `cd "$ROOT" && cd "$GCD" && pwd`; `?*/.git` strips to the parent.
4. REPORT-SWING3.md:15-17 says the class is SessionStartNoOriginClaimWithoutGit: a non-git folder, plus a real linked worktree with origin/HEAD set, run with no git on PATH and with git linked to `false`, after a working-git control. UPHELD by `tests/test_session_start.py`:315, :370-374, :376-384 (`git worktree add`), :386-388 (control), :389-391 (the two variants) and :336-353 (`bin_dir`).
5. DID-SWING3.md:3 lists the PATH tools wc/tr/grep/tail/date/dirname. UPHELD by test_session_start.py:311. It says the test "skips with a reason if the PATH cannot be built": UPHELD by :345 and :350. It says the test asserts no claim line and that the LOGLINE-Z tail prints: UPHELD by :309 and :364-368. The control string is UPHELD by :388.
6. DID-SWING3.md:3 describes the relative test: ROOT = main/sub, marker only at main, cwd elsewhere/deep, no nudge. UPHELD by test_session_start.py:283-306. The test does not assert `../.git` literally. It skips only on an absolute answer (:295-297), and the docstring at :284 states the expectation. That is accurate enough for a DID.
7. DID-SWING3.md:3 says "Working-git-unset case kept: test_unknown_default_says_so". UPHELD by test_session_start.py:49-50.
8. DID-SWING3.md:10 and REPORT-SWING3.md:20 say 28 tests. UPHELD by count: test methods at test_session_start.py:37,44,49,52 (4); :97,101,107,113,117,121,125,129,133,143,151,158 (12); :217,223,227,232,239,245,258,267,274,283 (10); :370,376 (2). That totals 28, and it matches the hub rerun pasted in the order.
9. DID-SWING3.md:5 and REPORT-SWING3.md:22 say the 8a72bce hook gives FAILED (failures=3): both git-unusable subtests and test_plain_non_git_folder. UPHELD for the count by the hub's pasted scratch rerun. The attribution is consistent with the test structure: :374 plus the two subTests at :392-394, each counted separately.
10. DID-SWING3.md:7 says the GIT_OK-never-set mutant gives FAILED (failures=2, errors=4). Consistent, not reproduced. The four SessionStartBranchLine tests index `splitlines()[0]` on empty output (test_session_start.py:31), which raises IndexError and gives 4 errors. The control at :388 fails as an assertion. REPORT-SWING3.md:23 labels this "Builder reports", not a hub rerun. That is correctly attributed.
11. DID-SWING3.md:14 says "the agent file names `projects/inbox/roles/super-doer.md` and `projects/inbox/graphs/lane.md`; neither exists here". Absence UPHELD: a Glob for those paths plus `roles/super-doer.md`, `graphs/lane.md` and `.claude/agents/super-doer.md` returned only the last three. "The agent file names" is OVERTURNED if read as the in-tree `.claude/agents/super-doer.md`: that file names `roles/super-doer.md` (:8, :64) and `graphs/lane.md` (:32, :66), and a grep for `projects/inbox` returned zero matches. It is plausible if read as the definition the builder's session actually loaded. My own loaded definition carries `projects/inbox/grills/`, while the in-tree `.claude/agents/adversarial-reviewer.md:11` says `grills/`, so loaded definitions here differ from the in-tree files. Classed as a note (Notes 1): a reader acting on it would look for drift in a source that does have it, and nothing unsafe follows.
12. Spot-check of the order's `cite lines read: yes`: I checked the cited WARN line, DID-SWING3.md:14. The absence half is UPHELD. The "agent file" half is qualified as in item 11.

## Operator gates

- None created by this diff. The policy-lane landing path from my resume grill still stands (Notes for the PR body 3 there): push and PR take per-target approval, and the operator merges.

## New defects

None in the `.md` diff.

## Claims I could not check

- The diff itself, and that ONBOARDING.md is byte-identical to 79921bc: I have no git, so I took the hub's pasted `git diff --stat` and `stamp_check` outputs as given.
- "With working git, output is unchanged" (REPORT-SWING3.md:11): this needs the 8a72bce hook, which I did not open.
- The operator ruling quotes (REPORT-SWING3.md:3,7): no transcript or decision record was in the read set.
- The tiers and "swing 1 failed review" (REPORT-SWING3.md:6); "no policy gate refused" (DID-SWING3.md:1); "Ran 40 tests" for `tests/test_log_escape.py` (DID-SWING3.md:11; the hub paste shows only "OK (skipped=2)", and I did not open the file); `bash -n` and the M8/M9 and dubious-ownership probes (DID-SWING3.md:6,8,13).
- My role file: `roles/` holds `recall.md`, `scribe.md`, `senior-engineer.md` and `super-doer.md` (Glob `roles/*`). There is no `adversarial-reviewer.md`, so I worked from my loaded definition and `CLAUDE.md`.
- Outside the order's named files, I opened `.claude/agents/super-doer.md` and `.claude/agents/adversarial-reviewer.md` (grep only) and `graphs/lane.md` (grep only), solely to check DID-SWING3.md:14 and the re-stamp rule. I did not open the main tree, `scripts/stamp_check.py`, or the 8a72bce hook.

## Notes for polish

1. DID-SWING3.md:14: "the agent file" is ambiguous. The in-tree `.claude/agents/super-doer.md` already names the right paths. Suggested wording: "the agent definition this session loaded (not the in-tree `.claude/agents/super-doer.md`, which names `roles/super-doer.md` and `graphs/lane.md`) names `projects/inbox/...`". The source of that loaded definition is outside this checkout. Fixing it is an operator matter and may be a policy edit.
2. REPORT-SWING3.md:19 "the three scope paths" does not name them. Suggested: "(the hook, the test, DID-SWING3.md)", if that is what is meant.

## Final disposition

- Merge-blocking: none.
- Notes: Notes 1-2 above, non-blocking.
- Build gate: this APPROVE covers the `.md` kind at 13e228d only. Any later commit voids it under `covers()` (`graphs/lane.md:202-204`). It does not stamp the hook or the test; senior-engineer round 2 owns that.

## Recommendation

Approve as written. Optionally apply Notes 1 before the next commit, or carry it to the PR body. Applying it after this stamp voids the stamp again.
