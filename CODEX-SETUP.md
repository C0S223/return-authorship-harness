# Set up the local Codex app or CLI

**Reader: the agent helping the person.** Walk through one step at a time and explain the
result plainly. Follow `AGENTS.md`. A **STOP** requires the person's action or answer;
never perform it for them. This guide installs nothing and changes no machine setting.

What protects the person here is Codex's own sandbox and approval prompts. This kit ships
no Codex hooks and has not probed Codex: say so, and do not call the setup protected
because the configuration parses.

1. Run `codex --version`, `git --version` and `python3 --version` (or `python --version`).
   Missing tools: **STOP**, say what is missing and let the person install it.
2. **STOP:** the person checks that this copy is in their own account and is private. Do
   not alter remotes, GitHub settings or credentials.
3. **STOP:** have the person read `AGENTS.md` and `.codex/config.toml` before trusting the
   project. The config asks for `approval_policy = "on-request"`,
   `sandbox_mode = "workspace-write"` and no network. Settings with a higher priority, or
   command-line flags, can override a project's defaults.
4. After they trust the project and restart the client, check the effective settings with
   them: CLI `/status`, or the app's permission controls, should show the same three
   values. If they differ, **STOP** and say which one.
5. Run `python3 scripts/run_tests.py` and report every failure and skip. Codex's sandbox
   turns the network off: if a test fails for that reason, say so. Do not open the
   network to make it pass.
6. For the GitHub ruleset on the main branch, follow `SETUP.md` step 5 with the person.

Finish with what was actually observed: the effective sandbox mode, approval policy and
network setting, and the test result. Name anything not checked.
