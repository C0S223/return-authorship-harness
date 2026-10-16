# Verified product references
Checked 2026-10-16 by the hub; reference data, not authorization.

[Codex hooks](https://learn.chatgpt.com/docs/hooks): project hooks can live beside
config in hooks.json. They need user trust. Local function calls, shell, MCP and
apply_patch support pre/post hooks; spawn_agent matches Agent. Bash and patch
input use command. Pre-tool deny is supported; ask is unsupported and can let
the tool proceed after an error. Convert approval-required outcomes to explicit
blocks. Hosted tools are outside this hook path; write_stdin does not repeat
the pre-hook. SubagentStart cannot prevent a spawn. Post-hooks cannot undo
effects. Prompt hooks receive prompt and session_id. Non-managed hooks and
agent instructions are not an unbypassable security boundary. Cloud orchestration
is outside this port. Verify missing-script, timeout and malformed-output behavior.

[Codex subagents](https://developers.openai.com/codex/subagents): project custom
agents are standalone TOML files under .codex/agents. Each requires name,
description and developer_instructions. Model and model_reasoning_effort may
be set. Supported feature switches can reduce shell/apps/plugins/memories and
request-permissions capabilities. Custom agents inherit parent sandbox,
approval policy, provider and MCP servers; agent-file sandbox overrides do not
give separate read-only isolation. Do not claim Claude tool-grant equivalence.

[Codex skills](https://developers.openai.com/codex/skills): repository discovery
uses .agents/skills between working directory and repository root. A skill has
name and description frontmatter and its SKILL.md instructions. Symlinked skill
folders are supported. Explicit CLI invocation uses the dollar-prefixed name.

[Instruction discovery](https://developers.openai.com/codex/guides/agents-md):
AGENTS.override.md precedes AGENTS.md, then configured fallback filenames, one
per directory. Root AGENTS carries the original contract. CLAUDE fallback keeps
nested references discoverable. Project trust and effective client settings
must be verified; checked-in defaults alone are not enforcement evidence.

Local baseline command: /opt/homebrew/bin/python3.14 scripts/run_tests.py.
Observed in main tree before lane: 39 suites, 37 pass, 2 fail; both reproduced
against HEAD. Failure logs remain ignored at main tmp/codex-tests.log,
tmp/baseline-policy.log and tmp/baseline-mutation.log. No live Codex hook probe.
