# Codex local port candidate — 2026-10-16
Implemented `.codex/hooks/{dispatch.py,launch.sh}`, hooks registration and disabled-by-default config.
Shared predicate integration: policy/scope/Git/net/env/roster; no new shell text classifier.
Added full patch-target parsing, session-isolated grants/revokes, exact agent-control grants, audit/integrity.
Native discovery: six `.codex/agents/*.toml` bindings and five `.agents/skills/*/SKILL.md` wrappers.
Added `scripts/codex_review_order.py`, `scripts/codex_status.py` and setup/coverage documentation.
Extended shared policy/integrity to `.agents/skills/**`; CI also protects Codex operation docs.
Original `CLAUDE.md` unchanged; `AGENTS.md` byte-identical, checked against original 759372bd98a7e25381ee413a045ec81a927f994f.
Python 3.14: `tests/test_codex_hooks.py` — 20 tests pass; discovery/policy and 15,000-byte budget checks pass.
Full suite: 40 suites, 38 pass, 2 known baseline macOS failures; 14 internal skips. Receipt: `tmp/codex-full-suite.log`.
Failures: GNU-sed mutation anchors and policy-prefix case folding; neither repaired.
Baseline-red: all 20 transport tests fail on original base (transport absent).
Behavioral mutants killed: skipped policy gate, omitted move target, crash-open decision.
Proof receipts: `tmp/codex-proving-icf_cm2w/{results.json,baseline.log,skip-policy.log,omit-move-target.log,crash-open.log}`.
Changed-doc cite check: 0 FAIL, 4 absent-template WARN; official skill validator blocked by missing PyYAML (no install).
Hooks remain disabled; app/CLI trust, activation, native tool envelopes and runtime failure semantics require real probes.
Known limits: same-machine grant state writable, prompt provenance unspecified, hosted tools and frozen classifier gaps.
Unsupported mutation shapes/interactive continuation refuse; native agent controls require exact per-call approval.
No live sessions, installs, outside writes, publishing, pushes, merges or main-tree edits. Independent reviews pending.
