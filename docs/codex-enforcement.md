# Local Codex enforcement and workflow

This port targets the Codex CLI and desktop app. It uses the original contract
verbatim in `AGENTS.md`, native project agents and skills, and one hook dispatcher
that calls the existing Claude guard programs. Claude Code itself is not required.
Python 3.11+, Git and a POSIX shell with Bash are required; Windows uses Git Bash
for the hook command. Native Windows command-shell activation is not yet qualified.

Project hooks ship **disabled** in `.codex/config.toml`. The files are configured,
but no live CLI or app probe has been recorded. Follow `CODEX-SETUP.md` before
relying on a gate. `python3 scripts/codex_status.py` reports checked-in configuration
and discovery files; it does not inspect effective client settings or mark them live.

The incident behind this addition is the Codex gap: the original hook registration,
Claude tool envelopes and Claude-only discovery paths did not reach Codex. The
transport budget is one ordered dispatcher and one launcher, registered for five
native events: SessionStart, UserPromptSubmit, PreToolUse, PostToolUse and Stop.
No shell text classifier or existing hook is replaced. The shared contract budget
remains 15,000 bytes; this detailed matrix is outside the always-loaded contract.

| Boundary | Implementation | Current status and limit |
|---|---|---|
| Instructions | Root `AGENTS.md` equals original `CLAUDE.md`; fallback finds nested Claude contracts | Files supplied; verify client discovery and overrides |
| Sandbox | workspace-write, on-request, network disabled in project config | Defaults only; client/system settings can override |
| Shell checks | Existing policy-mutate, shell-scope, git-guard, net-post and env-global | Direct-envelope tests; client activation unprobed; frozen text classifiers retain their gaps |
| Patch/file writes | Entire patch grammar parsed before scope and policy checks on every path, including move targets | Unknown shapes block; deletion patches block for operator recoverability review |
| Approval-required scope | Shared `ask` becomes explicit `deny` with explanation | No broad grant, sandbox change or automatic escalation; operator performs outside-scope action |
| Policy grants | Original prompt grammar and task lifetime, keyed by a hash of the Codex session id | Agent-writable local state; no hardened authorship proof |
| Net/env grants | Existing one-shot consumers rebound to session-keyed files | No cross-session consumption; global Claude grant files are not used |
| Roster | Existing roster predicate plus native `agent_type` and required custom TOML | Default/fallback agents refuse; bindings inherit parent permissions; ask before every spawn until roster probe is live |
| Denied tools | Shared tool-name deny patterns; unmapped local tools refuse | Hosted tools do not traverse this hook path; Claude Bash argument-pattern settings are not a Codex shell classifier |
| Audit | `.agent-log/YYYY-MM-DD.md`, local time; session-keyed allow/deny/start/stop lines | Commands and prompts omitted from adapter trail; original guards may record their established details |
| Integrity | Existing baseline/compare machinery at start, post-tool and stop | Observes bytes after effects, prevents nothing; compact/resume/clear/fork never overwrite an existing baseline |
| Git | Existing pre-tool git-guard; existing pre-push and CI | No new Codex shell marker asserted; pre-push ships unarmed and CLAUDECODE identifies Claude only |
| Workflow | Native skills route grill, lane, review-order, cite-check and operator closeout | No connector required for repository-only tracking; no automatic closeout or publication |

`PreToolUse` translates only established envelopes. Matching the hook alias `Agent`
does not turn native `agent_type` into Claude `subagent_type`; the adapter does that
explicitly after checking the native role file. Shell and patch bodies use
`tool_input.command`. Unknown tools or argument shapes fail closed with the tool
name and reason; do not rename a blocked tool or hide it in another tool. A missing
required tool is a capability gap to report, not permission to improvise an envelope.

The checked-in defaults turn off `unified_exec` and `unified_exec_tty` because
`write_stdin` does not repeat PreToolUse. The adapter rejects explicit unified exec,
stdin-continuation and interactive envelopes. A canonical `Bash` alias alone cannot
prove which execution backend generated it. **Verify that the client actually offers
only a noninteractive shell before relying on shell coverage.** If the client still
exposes a continuation-capable shell, stop shell work and keep this coverage unverified.
Disabling a configuration flag is not runtime proof. Background scripts, interpreter
I/O and content sent through otherwise permitted tools remain the original classifier
and sandbox limits; this port does not add a second shell language recognizer.
Claude settings entries that match Bash argument text (such as plugin CLI commands)
are not translated into new shell patterns here. The contract still prohibits them;
local tool-name denies must not be mistaken for complete shell-command coverage.

## Approval and recovery

Only an entire new user prompt arms a grant. Pasted logs, quoted instructions and
messages merely mentioning the verb do not. The same typed syntax works in Codex:

- `auth-policy relative/path` or `auth-policy-batch path1 path2` (up to eight paths):
  replace this session's policy grant; task-lived, eight-hour maximum.
- `revoke-policy`: end this session's policy grant immediately.
- `auth-net example.com`: one matching host send, thirty-minute maximum.
- `auth-env`: one existing global-environment predicate hit, thirty-minute maximum.
- `revoke-net` and `revoke-env`: spend this session's remaining corresponding grant.
- `auth-agent <sha256>`: one exact native `send_input`, `resume_agent` or `close_agent`
  call, after the agent displays the complete target and input for human review.
  The refusal supplies the digest; it binds the tool and every argument. A changed
  target/message needs a new grant. It expires after thirty minutes and replaces
  the previous control grant. `revoke-agent` spends it immediately.

The model explains the exact action and paths first; the human types the token.
A grant never authorizes an unrelated action, installs by itself, changes sandbox
permissions, overrides a never-item or authorizes a send containing private data.
The supported prompt payload documents `prompt` and `session_id`, not trustworthy
origin provenance. The adapter preserves absent `source` and rejects an explicit
non-user source; it never synthesizes `source=user`. This is an operational approval
convention, not protection against an agent forging hook input or rewriting local
state. Direct file-tool access to grant filenames is sealed by the shared predicate;
interpreter access and an agent-writable checkout remain known limits.

Adapter exceptions and unsupported decisions produce a valid pre-tool deny. The
launcher returns exit 2 when a required file or interpreter is missing. Missing
launchers, process termination, timeouts, malformed client handling and trust failures
still need real client probes: not every runtime hook failure is guaranteed to block.
Post-tool integrity alerts cannot undo an effect. No fixture test proves the runtime
will invoke or obey the hook. If a live probe proceeds unexpectedly, stop and report
that surface as unverified; do not compensate by adding a shell text pattern.

## Native workflow substitutions

The root contract and original graphs remain authoritative. Native bindings live in
`.codex/agents/<roster-name>.toml`; they declare `name`, `description` and
`developer_instructions`. They do not use old `config_file` role bindings or claim
per-agent sandbox overrides. Read-only and one-review-file constraints are prose;
the parent sandbox, approval policy and MCP servers are inherited. No role may use
unexpected tools as permission to exceed its work order.

`$harness-grill` follows `graphs/grill.md`, using an available question tool or one
plain question if it is unavailable. `$harness-lane` follows `graphs/lane.md`, with
native roster roles and an independent non-author review. Repository-only tracking
uses the original no-board exceptions: the work order and handoff retain the skipped
connector writes. A missing connected board is unknown, never empty.

For lane dispatches, the hub uses the Codex model/effort pairs in `graphs/lane.md`,
checks both against the current tool's advertised options, and supplies explicit
`model` and `reasoning_effort` overrides. With the native `spawn_agent` tool that
exposes `fork_turns`, overrides require `fork_turns="none"`: a full-history fork
inherits the parent model and effort and cannot implement the selected pair.
Supply the governing instructions, work order, pinned revision and required input
paths explicitly in the fresh agent's task. Keep the roster `agent_type` and all
existing dispatch approvals. If the tool cannot select both values, report the
capability gap before dispatch; a prompt instruction cannot set runtime effort.
The hub records the selected model and effort in the graph's dispatch receipt and
landing record. This mapping selects delegated agents; it does not change the
running parent session's model or effort. The CLI's session-level setting is
`model_reasoning_effort`; use the spelling the actual tool exposes.
The Haiku-specific wording in `roles/scribe.md` describes Claude Code; a native
Codex scribe uses the graph's Codex light model/effort pair.

`$review-order` runs `scripts/codex_review_order.py`, which reuses the original Git,
citation and author-check machinery while reporting the actual Codex binding. It
refuses dirty or unpinned review work. Reviewers preserve the existing stamp format,
verdicts and caps; the hub never authors their independent findings. `$cite-check`
uses the existing checker. `$closeout` is operator-invoked only and uses the local
host disposition and repository handoff; Stop records a turn end and never calls it.
Native `wait`/`wait_agent` can collect results. Continuing, resuming or closing a
child through `send_input`, `resume_agent` or `close_agent` uses the exact-call
approval above; there is no blanket permission to send followups. Unknown control
wrappers refuse: report the missing surface and obtain a supported client/tool
binding rather than inventing one. Local tools outside the explicit mappings,
including an unrecognized planning tool, remain unavailable; keep the plan in the
conversation instead. A review repair uses a newly pinned work order and the
original round limits. No cloud sessions, schedules, installs or publication are
implied by these skills.

Sources checked for this port: [Codex hooks](https://learn.chatgpt.com/docs/hooks),
[native agents](https://developers.openai.com/codex/subagents),
[skills](https://developers.openai.com/codex/skills) and
[instruction discovery](https://developers.openai.com/codex/guides/agents-md).
