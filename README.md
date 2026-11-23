# return-authorship-harness

A starter kit that keeps you in charge of an AI coding agent. It is a short written
contract (`CLAUDE.md`), a settings file that turns on the protections Claude Code and
Codex already have, and a probe that shows what those protections do on your machine.

## What protects you, and what does not

This kit adds no guard of its own. It switches on the platform's, and says where there is
none. `.claude/settings.json` asks Claude Code for the following; `python3
scripts/safety_probe.py`, run through the agent's own shell, shows what your machine
enforces. A setting is a request. Only a PASS on one of the probe's act rows shows that an
act was refused.

| Where the agent runs | Shell commands | What to know |
|---|---|---|
| macOS, Linux, WSL2 | Claude Code's sandbox: writes only inside the project and one git folder two levels up (the main checkout's, when this copy is a worktree), no writes to the protected paths below, no reads of `~/.ssh`, `~/.aws` or `~/.gnupg`, network only to the hosts listed in the settings | Linux and WSL2 need `bubblewrap` and `socat` installed. The settings ask Claude Code to refuse to start if the sandbox cannot. Starting proves nothing: only the probe's act rows do. On macOS the settings also turn on `enableWeakerNetworkIsolation`, which lets sandboxed commands reach the system's certificate service. It is on because a trial of these settings on a Mac, in the private copy this kit is drawn from, found `gh` failing certificate checks inside the sandbox without it and working with it. The record of that trial is not in this repository. The cost: Claude Code's settings reference says this "reduces security by opening a potential data exfiltration path through the trust service". |
| Native Windows | No sandbox exists | The settings ask Claude Code to refuse to start. Its sandboxing guide says that with this setting "Claude Code exits at startup on those machines". This kit has no run on Windows on record. Use WSL2 or a cloud session. |
| A cloud session | Not contained inside the container | Claude Code's settings reference says a session in an Anthropic-hosted environment "can start anyway, with a warning, and doesn't enforce your `sandbox.filesystem` or `sandbox.network` rules". The one cloud session probed, with the private copy this kit is drawn from in November 2026, had a shell that wrote outside the project, opened the protected paths for writing and reached the network. Your own files are not there, and that is the protection. Treat anything you put in the container as readable by the agent. |

Asked for wherever Claude Code loads these settings (the probe script does not test
these):

- **File tools.** Deny rules stop the agent's Edit and Write tools changing the protected
  paths: `CLAUDE.md`, `AGENTS.md`, `README.md`, `.claude/`, `.codex/`, `.agents/`, `roles/`,
  `graphs/`, `.githooks/`, `.github/`, `.git/config` and `.git/hooks`. The
  `safety-probe` skill has a hand check for these. The same paths are on the sandbox's
  no-write list, so where the sandbox runs, a shell command that would change a file under
  one of them, a git command included, should be refused; the probe's `protected-write`
  rows test that. A pull request can still change `.github/`: your read of the diff guards
  the test workflow.
- **Prompts.** Starting another session or a schedule asks you first, through Claude Code's
  own tools, unless you run in a mode that skips prompts. A session or schedule started
  from a shell command is not caught. Remote triggers, browser scripting and the catch-all
  agent are denied.
- **Your main branch.** A GitHub ruleset, which you set up in `SETUP.md`, makes every
  change to the main branch arrive as a pull request with the tests run on it. It does not
  decide who merges: an agent using your GitHub login can merge its own pull request,
  change the ruleset, and change the test workflow in that same pull request. Only the
  contract tells it not to. An account on the ruleset's bypass list skips it, and GitHub
  may not enforce rulesets on a private repository on a free plan.

Not protected anywhere:

- **Connectors.** Mail, drives and other services the agent reaches through a connector
  are outside the sandbox. Only the permission prompt stands there.
- **Everything else the shell can read.** Only three folders are closed to reading. Any
  other file on the machine can be read, and sent to the allowed hosts.
- **The agent's web tools.** They are not the shell and are not held to that host list.
- **Uncommitted work.** If a shell command destroys work you have not committed, nothing
  here brings it back. Claude Code's rewind restores only edits made with its file tools.
- **The contract.** `CLAUDE.md` is text. The agent is told to follow it; nothing makes it.

### Codex: asked for, not probed

`.codex/config.toml` asks for Codex's own sandbox: writes inside the workspace, network
off, approval on request. This kit has not probed it, and the probe script does not reach
it.

## What you need

- Claude Code or Codex.
- Git and Bash, and a GitHub account.
- Python 3.11 or newer, named `python3` or `python`, for the probe and the tests.
- On Linux or WSL2: `bubblewrap` and `socat`, for the sandbox.
- `jq`, for the context-size reminder (`.claude/hooks/auto-compact/`). Without it the
  reminder stays silent and nothing else changes.

## Get started

1. On GitHub, click **Use this template**, choose **Private**, and create the copy under
   your own account.
2. Clone your copy, open it in Claude Code, and say: **read SETUP.md and set me up**. For
   Codex, say **read CODEX-SETUP.md and set me up**.
3. The agent walks you through the rest one step at a time, and stops whenever a step is
   yours to do.
4. After setup, say **onboard me** for a short tour.

## What is inside

- `CLAUDE.md` and `AGENTS.md`: the same contract under the two names the agents read.
  `AGENTS.md` is an exact copy, so its first line also reads `# CLAUDE.md`.
- `.claude/settings.json`, `.codex/config.toml`: the platform protections this kit turns on.
- `scripts/safety_probe.py`: tries each forbidden act from the agent's shell and reports
  PASS, FAIL or SKIP.
- `.claude/agents/`, `roles/`: two reviewers and two helpers you can ask for.
- `.claude/skills/`, `graphs/grill.md`: optional workflows.
- `scripts/run_tests.py`: runs the tests; GitHub runs it on each pull request.
- `scripts/cloud-setup.sh`: for a cloud environment's setup script, if you choose to use
  it. It makes `python` resolve to `python3` and does nothing else.
- `docs/`: notes and past decisions. Some describe machinery this kit no longer has.

## License

MIT. See `LICENSE`.
