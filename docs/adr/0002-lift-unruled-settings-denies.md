# ADR 0002: Lift the settings denies the operator never ruled or ruled against

Status: Accepted as the template default, by operator ruling on 2026-10-21. The same ruling
was made first in a downstream copy on 2026-10-20 and is ported here.
Decided by: the operator. Hub defaults, not ruled: both `javascript_tool` entries (Chrome's and
the built-in browser pane's) stay denied, and this text's wording.
Precedent: the operator's earlier tree is cited for provenance only and does not govern.

## Context

`.claude/settings.json` carried 38 deny entries. Tracing them back found no ruling behind
these classes:

| Entries | Ruling found |
|---|---|
| `spawn_task`, alongside the scheduling denies | None at tool level |
| Plugin suggestion cards (`SuggestPluginInstall`, `suggest_connectors`) | None; `scripts/test_contract_sync.py` marked `suggest_connectors` "hub-authored placement, not contract-ruled" |
| `Bash(claude plugin:*)` | None |
| Named Chrome inputs | None |
| Desktop clipboard, teach and display tools | None |
| Pane `javascript_tool` | None |

The denies the operator did rule on stand: both `browser_batch` entries,
`Agent(general-purpose)` and `Workflow`, and the `create_session` ask.

## Decision

Remove `spawn_task`, the six desktop clipboard/teach/display tools, eleven named Chrome inputs,
`SuggestPluginInstall` and `mcp__mcp-registry__suggest_connectors` from `permissions.deny`
(20 entries; 18 remain). The contract's §2 **Denied** line drops `spawn_task` and the input
classes and names browser `javascript_tool`; the **Cloud sessions** paragraph says queuing a
`spawn_task` card is allowed and logged, and the operator's click starts it. The L0 row in
`docs/enforcement/CLAUDE.md`, the L0 table in `scripts/test_contract_sync.py` and the
adversarial reviewer's persistence refusal follow.

## What still stands

- Scheduling denies (cron, wakeups, scheduled tasks, Routine triggers) wait for a later
  delegation design.
- `Bash(claude plugin:*)`, both `javascript_tool` entries, both `browser_batch` entries,
  `Agent(general-purpose)` and `Workflow`.
- Residual: in a multi-repo cloud session settings denies do not load, so the remaining
  denies bind there as prose only.
