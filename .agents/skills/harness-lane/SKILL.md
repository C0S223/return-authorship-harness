---
name: harness-lane
description: Carry an explicitly authorized scoped build through independent review and local verification.
---

Read graphs/lane.md, docs/codex-enforcement.md and the named work order. Preserve its acceptance check, isolated worktree, disjoint scopes, independent non-author reviewers, round limits, stamps and exact-path commits. Native agent_type names are in .codex/agents; read the chosen binding before dispatch. Use $review-order for native review headers. Never substitute a default/fallback agent. The parent sandbox and approvals are inherited; role confinement is prose. If no independent reviewer is available, stop the lane. With no board use the graph's repository-only record; missing connectors never imply an empty board. A local build approval authorizes no publishing. Present the tested result before target-specific push/PR approval; policy merges remain human-executed.

Collect native results with `wait`. Native `send_input`, `resume_agent` and `close_agent` require a one-shot `auth-agent` grant after showing the exact call to the operator; see docs/codex-enforcement.md. Never treat a repair round as standing permission to send. Unknown control wrappers are unavailable, not a reason to switch to a shell-spawned agent.
