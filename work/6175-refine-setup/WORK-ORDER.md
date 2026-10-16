# Work order: lane 6175, agent-driven setup and a portable Python launcher (base 1b6703b)

**Goal.** Lay users can set up the public template: README says what it is and "hand this repo
to your agent"; SETUP.md tells the agent how to run setup with them; a launcher fixes two hook
bugs found by first-user testing (board 6174). Source: operator grant 2026-10-16 ("Approve as
scoped"); item 6175. 6174 findings: (1) hooks call `python`, absent on macOS, exit 127, which
never blocks, so every gate silently allows; (2) a missing hook file makes `python` exit 2,
blocking every tool unhelpfully; (3) no macOS/Linux pre-push steps; (4) arming pre-push edits
policy files and needs `auth-policy-batch`, unsaid; (6) a repo owned by the agents' login makes
it admin, so it bypasses the ruleset.

**Acceptance check (before the build):**
1. `.claude/settings.json` runs every Python hook via `.claude/hooks/run-python.sh`: tries
   `python3` then `python`; stdin, stdout and exit code pass through unchanged. No interpreter,
   or no such hook file: exit 2 and one plain stderr line naming the fix. A missing launcher
   must also block (exit 2, not 127): prove it. A crashing hook: state in DID.md what happens
   and why that is right.
2. Tests for each case with `python3` only, `python` only and neither on PATH;
   `scripts/test_settings_portable.py` updated to the new command shape.
3. README.md, about one screen, for a newcomer: what this is; what you need (Claude Code,
   Python 3, Git, GitHub); "Use this template (Private), open in Claude Code, say: read SETUP.md
   and set me up"; a plain status line that does not read as broken; MIT.
4. SETUP.md, written for the agent, walks the human one step at a time and stops wherever the
   human must act: check Python 3 and Git; repo private and owned by the human's account, agent
   login a collaborator, never owner (6); arm pre-push per platform, Windows, macOS/Linux and
   managed cloud (3); the human types the `auth-policy-batch` line alone (4); run the suite;
   prove one hook blocks; the optional board connector, plainly; ruleset steps, bypass and
   auto-merge included.
5. `docs/enforcement/CLAUDE.md`: setup detail moves to SETUP.md behind a pointer; status reads
   "working once Python is present; a live probe is a setup step". CLAUDE.md plus this doc are
   at 14,997 of 15,000 bytes: `scripts/test_claude_md_budget.py` must pass.
6. `python3 scripts/run_tests.py`: all suites pass.

**Builder may edit only:** README.md, SETUP.md (new), .claude/hooks/run-python.sh (new),
.claude/settings.json, scripts/test_settings_portable.py, docs/enforcement/CLAUDE.md, one new
launcher test under tests/, work/6175-refine-setup/DID.md. All else frozen, root CLAUDE.md too.

**Blast radius:** the full suite (test_settings_portable, test_gate_decisions, test_fail_closed,
test_claude_md_budget, test_contract_sync, test_graph_pointers).

**Reviewers:** `senior-engineer` for the launcher, settings and tests (round 1 of 2);
`adversarial-reviewer` for README, SETUP.md and the doc (round 1 of 1). **Returns:** DID.md
(20 lines at most) committed on lane-6175, each path named; tree clean; no push.
