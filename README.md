# return-authorship-harness

A starter kit that keeps you in charge of an AI coding agent. Claude Code and
local Codex use the same written contract, scoped work orders and independent
review before changes land.

For Codex, open your clone in the app or CLI and say **read CODEX-SETUP.md and
set me up**. The [Codex guide](CODEX-SETUP.md) explains native skills and agents,
shared guard checks, scoped approvals and local audit. Codex hooks ship disabled;
setup includes separate activation probes for each client. See the
[coverage matrix](docs/codex-enforcement.md) for tested transport behavior and
remaining limits. No live app or CLI activation is claimed by the template.

## What you need

- Claude Code or Codex (follow the matching setup guide).
- Python 3, named `python3` or `python` (3.11+ for Codex).
- Git and Bash; jq is additionally required for the Claude setup.
- A GitHub account.

## Get started with Claude Code

1. On GitHub, click **Use this template**, choose **Private**, and create the copy under
   your own account.
2. Clone your copy, open it in Claude Code, and say: **read SETUP.md and set me up**.
3. The agent walks you through the rest one step at a time, and stops whenever a step is
   yours to do.

If Claude Code answers with `PREFLIGHT BLOCK`, a tool from the list above is missing.
Install it, then restart Claude Code.

## Status

Each setup guide includes a local activation check. Codex ships with hooks disabled
until explicit setup approval; direct-envelope tests do not prove runtime activation.
The Git push guard remains unarmed until separately configured and installed.

## What is inside

- `CLAUDE.md`: the rules every session reads first.
- `.claude/`: shared safety-check programs and Claude registration, agents and skills.
- `.codex/`, `.agents/skills/`: native Codex registration, agents and discovered workflows.
- `graphs/`, `roles/`: two workflows, a grill for decisions and a lane for builds, and the
  helpers' full instructions.
- `scripts/`, `tests/`: the test suite and the checks GitHub runs on each pull request.
- `docs/`: which protection is backed by what, on each platform. Some references in
  `docs/adr/` point at files that stayed with the original author.

## License

MIT. See `LICENSE`.
