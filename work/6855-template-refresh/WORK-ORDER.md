# Work order: lane 6855, template refresh slices 1 and 2: hook fixes, CI and stamps (base 541929d)

**Goal and source.** Bring the template up to date with generic fixes that landed first in the
operator's private downstream copy (direction: downstream first, the template gets the distilled
result). Board 6855. Operator rulings 2026-11-20 (grill, verbatim; two item ids redacted): "Waive, slices 1-2
(Recommended)"; "lane-6855, both slices"; "Fixes only, [item] later (Recommended)" (the
sandbox-and-CI hook redesign is not in this lane; the template keeps its hook guards);
"Include [item] (Recommended)" (the close-request push rule and audit copy come with the
session-close fixes). The per-file source map and the leak pattern travel in the dispatch only.

**Acceptance check, stated before the build.**
a. Each in-scope file differs from base only by the mapped hunks (reviewer checks against the map).
b. The base-to-HEAD diff adds no line matching the dispatch's leak pattern.
c. Red first: each ported test fails against the base's code and passes on the candidate.
d. `python3 scripts/run_tests.py` passes every suite.
e. `cmp CLAUDE.md AGENTS.md` prints nothing; `ci_policy_check` exit 1 (policy lane, by design).
f. `senior-engineer` NO-FINDINGS-CONFIRMED and `adversarial-reviewer` APPROVE (prose and leaks).

**Files the builder may edit.** Hooks: `.claude/hooks/{session-close.sh,policy-integrity.py,
session-start.sh,filetool-scope.py,shell-scope.py}`, `.codex/hooks.json`, `.codex/hooks/dispatch.py`.
Settings: `.claude/settings.json` (one env line). Contract pair and references: `CLAUDE.md`,
`AGENTS.md`, `docs/conventions/handoff-read-side.md`, `docs/enforcement/CLAUDE.md`,
`docs/codex-enforcement.md`, `CODEX-SETUP.md`, `graphs/lane.md` (stamp paragraphs only),
`.claude/agents/{senior-engineer,adversarial-reviewer}.md`, `roles/senior-engineer.md`.
CI: `.github/workflows/ci.yml`, `.github/CODEOWNERS` (new, placeholder owner), `.gitattributes`
(new), `.gitignore`. Scripts: `scripts/{stamp_check,ci_policy_check,prepush_check}.py`.
Tests: `scripts/test_{stamp_check,ci_policy_check,prepush_predicate,policy_integrity,codex_support,
contract_sync,claude_md_budget}.py` (the last two only where forced), new `scripts/test_{session_close,
codeowners,ci_merge_result}.py`, `tests/test_{session_close,session_start,filetool_scope,shell_scope,
codex_hooks,log_escape,mutation_anchors,prepush_policy,run_python}.py`, new
`tests/test_policy_integrity_child_fsmonitor.py`. Everything else is frozen.

**Builder:** `super-doer` (mid, sonnet): hunk selection needs judgement. **Time:** `1-4 h`. **Blast radius:** full suite.
**Reviewers:** `senior-engineer` (heavy, opus; code, running the suite), round 1 of 2.
`adversarial-reviewer` (heavy, opus; contract lines, enforcement and Codex docs, lane.md, agent
and role text, leak review of the whole diff), round 1 of 1.
**Outside effects:** push `lane-6855` and one draft PR into `main`, each on the operator's yes at
a reviewable result; `operator-merge` red, the operator merges. Deletes: none.
**Prior mechanisms searched:** lanes 6189 and 6404 (port desk shape, dispatch-only leak
pattern; hit). No scrub gate in this tree, so the leak check is check b plus the reviewer.
