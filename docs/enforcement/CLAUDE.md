# Enforcement reference

Supplement to root `CLAUDE.md` §8.

**Codex local app/CLI:** [coverage and probes](../codex-enforcement.md).
The adapter shares these predicates; Claude statuses below do not prove Codex activation.

## Coverage and verification
**`live` means wired and firing, not complete coverage.** Mark a cell live only in the policy edit that records the probe proving it on that target. Known bypasses are tracked as open items, not deferred protections.
**Three targets, per-target Status columns.** Words: **live** probed there · **wired** configured, not yet probed in this tree · **unarmed** ships a placeholder (`OWNER/REPO`); installed, it refuses every push, uninstalled nothing runs · **cloud-off** exits 0 under the boundary marker (`unlock_consume.cloud_boundary()`) · **unregistered** no tool name arrives · **prose** no mechanism, the rule binds as text. **Status: working once Python is present; a live probe is a setup step (`SETUP.md`). Until one lands, cells read wired or prose and `ask` rows are advisory (root §8).**
**Table and `scripts/test_gate_decisions.py` disagree → table is wrong.**
**Layer:** L0 root §2 **Denied** (settings deny) · L1 hook-gated, ask or deny per cell · L2 prose only · L3 root §5 charter · CI GitHub check on the PR, every target · — not a rule class.

| Rule class | Layer | Mechanism | Windows | Managed | Self-hosted |
|---|---|---|---|---|---|
| Persistence, desktop clipboard/teach/display, named Chrome inputs, browser batches, plugins, catchall spawn | L0 | settings deny · trigger-shape | wired (deny) | wired (deny) | wired (deny) |
| Policy-path mutation | L1 | policy-integrity (record) · policy-mutate + `auth-policy`(-batch) (text gate) | wired | cloud-off (the PR is the authorization; CI's `operator-merge` holds it for the operator) | cloud-off |
| File-tool writes outside tree | L1 | filetool-scope | wired (ask) | cloud-off (VM disposal) | cloud-off (container disposal) |
| Shell writes outside tree | L1 | shell-scope (`--log` is log-escape's trail) | wired (ask) | cloud-off (`--log` only; blind inside script bodies) | cloud-off |
| Spawn roster | L1 | spawn-roster + catchall deny | wired (deny) | wired | wired |
| Git never-items | L1 | git-guard · pre-push (refuses the default branch when `CLAUDECODE` is set) · repo ruleset (PR landing row) | git-guard wired; pre-push **unarmed** (`APPROVED_ORIGIN_URL`) until setup | git-guard wired; pre-push **unarmed** (`APPROVED_ORIGIN_URL`, `REPO_MATCH`) until setup | git-guard wired; pre-push **unarmed** (`APPROVED_ORIGIN_URL`) until setup |
| PR landing: `gate` = stamp + suite, `operator-merge` = policy path | CI | `ci.yml` (`pull_request_target`; the default branch's `stamp_check` and `ci_policy_check`, the PR's suite only for a head in this repository; actions pinned by sha); a ruleset the operator sets requires both jobs | wired; binds only identities the ruleset does not exempt, so an admin push bypasses it | same | same |
| Non-loopback shell sends | L1 | net-post + `auth-net` | wired (deny) | cloud-off (platform egress control) | cloud-off (sidecar allowlist) |
| Global env / installs | L1 | env-global + `auth-env` | wired (deny) | cloud-off (VM absorbs) | cloud-off (container absorbs) |
| Escape audit trail | L1 | log-escape | wired (records; needs `jq`) | wired | wired |
| Situation line | — | session-start | wired | wired | wired |
| Unlisted outside effects (root §2 residual ask), content bounds, background checks, web-tool sends | L2 | prose + present human | prose | prose | prose |
| Context management (advisory) | L2 | auto-compact check + resume | wired | wired | wired |
| Sanctioned infrastructure | L3 | per-row operator ruling | none chartered | none chartered | none chartered |

Session-close copies escape, grant, integrity and `peer-` lines into tracked `handoffs/auto/` only at a cloud closeout (flag `.agent-log/closeout-requested`, 2 h), never counting them as stranded; only committed lines survive.

## Setup per target
Placeholders ship unarmed (`APPROVED_ORIGIN_URL` in `.githooks/pre-push`; `REPO_MATCH` in `scripts/cloud-setup.sh` arms no checkout); arming each is a policy edit. Steps for Windows, macOS/Linux, managed cloud and self-hosted: `SETUP.md`.

## Policy paths
Paths, at every checkout root (the tree root and each `worktrees/<n>/`): `CLAUDE.md`, `AGENTS.md` and `AGENTS.override.md` at any depth, root `README.md`, `.claude/settings*.json`, `.claude/keybindings.json`, `.claude/hooks/**`, `.claude/agents/**`, `.codex/**`, `.agents/skills/**`, `.git/config|hooks|info|refs`, `.githooks/**` and `tools/git-hooks/**` (the pre-push hook's tracked sources), `roles/**` and `graphs/**`, edits to existing `skills/`/`scripts/`/`templates/` files, `.claude/` ones included, and `goals/OBJECTIVES.md` where a checkout carries one. Redirects/tee count. CI's `ci_policy_check` also gates `.github/**`, `CODEX-SETUP.md` and `docs/codex-enforcement.md`.
**Grant mechanism** (task-lived): `auth-policy <path>` or `auth-policy-batch <p1> ... <p8>`, typed as the whole of a new user turn, arms a grant for the named paths only, keyed to the session id; each allowed hit writes one `unlock-consumed` line, policy-integrity's credit for one difference until the grant ends. Only UNGRANTED differences alert. The grant ends at the first of: a new session, `revoke-policy` typed alone, a new unlock (either verb replaces all grants), or 8 h after arming. `auth-net` and `auth-env` stay one-shot.

## Roster maintenance
Binding requires three policy edits: `.claude/agents/` definition, root §2 roster, and `spawn-roster.py`'s `ROSTER`; only the frozenset gates, backed by the named catchall deny. `scripts/test_contract_sync.py` detects roster disagreement. Definitions resolve once per session: verify bindings in a fresh session.

## Enforcement changes
Put each rule at the lowest layer that can decide from tool name, arguments, path, or verb without judging intent. Record every layer move and the incident behind it in the change that makes it.
**The hook set is closed:** additions name an incident and retire a hook or raise the budget. Hooks whose hits are mostly legitimate traffic are candidates for demotion.
**Text matchers are parked:** hook editors and reviewers record a new gap as a residual, never a pattern patch (fixes trade false denies for bypasses); see `docs/adr/0001-park-text-classifying-guards.md`.
