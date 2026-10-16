# Work order: lane 6177, macOS fixes and novice setup walkthroughs (base 759372b)

**Goal.** Fix the nine findings of the second fresh-user test (board 6177; macOS, desktop
app). Grant 2026-10-16: "Fix all 9 now".

**Acceptance check (before the build):**
1. log-escape.sh logs on bash 3.2: no `printf '%(..)T'` (use `date`). Test proves it on a
   3.2-compatible path, or shows bash 3.2 syntax is all it needs. The `trap 'exit 0' ERR`
   stays, but a timestamp failure must not drop the line.
2. run-python.sh and preflight.sh pick the first interpreter that is Python >= 3.10, trying
   python3 then python, so Apple's 3.9 python3 is skipped when a newer `python` exists. Below
   3.10 everywhere: exit 2 with a plain message. Tests cover 3.9-first-then-3.14 and 3.9-only.
3. Tests pass on macOS defaults: tests/mutate_auto_compact.sh uses no GNU-only `sed -i`;
   test_policy_mutate's case-fold test does not assume a case-sensitive filesystem (detect,
   then skip or adapt); no test needs a Python newer than the 3.10 floor.
4. SETUP.md step 1 checks the Python floor (3.10) and says why. If any hook still needs bash
   >= 4.2 after item 1, check that too; prefer making hooks 3.2-safe.
5. Step 3d pushes without `-u` (or expects the `.git/config` alert) and says a mid-step
   "stranded work" note is expected. 6. An explicit request authorizes an agent install (§2).
7. Click-by-click walkthroughs, for someone with no GitHub experience, for: merging the
   setup PR (Files changed; expect red `gate` stamp and `operator-merge` and why; check the
   `(c) suite: PASS` line under gate Details; bypass merge box; confirm; branch) and the
   ruleset (Settings > Rules > Rulesets > New branch ruleset; Active; bypass: own account;
   default branch; Require status checks: gate, operator-merge, available after one CI run;
   Settings > General > Allow auto-merge; what Free-plan "not enforced" looks like). Each ends
   with what the person reports back. The agent shows each walkthrough in its final visible
   message of the turn (the desktop app collapses mid-turn prose).
8. Step 5 warns that the refused probe shows as a red "Failed" tool call: that is the pass.
9. Step 7: the agent reads the ruleset back (`gh api repos/<o>/<r>/rulesets` and
   `.../rules/branches/<default>`, readable with write access) and checks required checks
   and auto-merge itself; the person confirms only the bypass list (needs admin).
10. README names the Python floor. `python3 scripts/run_tests.py`: all pass (budget too).

**Builder may edit only:** .claude/hooks/log-escape.sh, .claude/hooks/run-python.sh,
.claude/hooks/preflight.sh, SETUP.md, README.md, files under tests/, and
work/6177-mac-setup/DID.md. All else frozen (root CLAUDE.md, settings.json, scripts/).

**Reviewers:** `senior-engineer` for hooks and tests (round 1 of 2); `adversarial-reviewer`
for SETUP.md and README.md (round 1 of 1). **Returns:** DID.md (20 lines at most) committed
on lane-6177, each path named; tree clean; no push.
