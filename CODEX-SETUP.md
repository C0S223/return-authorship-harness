# Set up the local Codex app or CLI

**Reader: the agent helping the person.** Walk through one step at a time and
explain the result plainly. Follow `AGENTS.md`. A **STOP** requires the person's
action or answer; never perform it for them. This guide needs no Claude installation
and does not install packages, change machine settings or publish anything.

1. Read `AGENTS.md` and `docs/codex-enforcement.md`. Run `codex --version`,
   `git --version`, `python3 --version` (or `python --version`) and `bash --version`.
   This port needs Python **3.11 or later**, Git, and Bash; jq is not required for
   the Codex dispatcher. Missing tools: **STOP**, explain what is missing and let
   the person install it. On Windows, Git Bash must be on PATH; its client hook
   invocation still needs the Windows probe below. Do not assume a Windows Store
   Python alias is a working interpreter. The launcher also tries versioned names
   `python3.14`, `python3.13`, `python3.12` and `python3.11`; use the verified
   interpreter in place of `python3` in every command below.
2. **STOP:** the person verifies that this copy is in the intended account and has
   the intended public/private visibility. Explain that owner/admin bypass rights
   weaken GitHub protections. Do not alter remotes, GitHub settings or credentials.
3. Run `python3 scripts/codex_status.py`. Report the contract comparison, configured
   events, on-disk skills and agents, and the fact that hooks ship **disabled**.
   Run `python3 tests/test_codex_hooks.py`, `python3 scripts/test_codex_support.py`
   and `python3 scripts/run_tests.py` when the checkout is idle. Report every failure
   and skip. These direct-envelope tests exercise the programs; they prove neither
   that the app calls hooks nor that the CLI blocks on a hook failure.
4. **STOP:** have the person review `AGENTS.md`, `.codex/config.toml`,
   `.codex/hooks.json` and the coverage matrix before trusting the project. Agree
   on a local activation probe in this checkout and the policy edit that sets
   `.codex/config.toml`'s `features.hooks` to `true`. An agent may make that named
   edit only on the person's explicit authorization; never turn hooks on as a
   side effect of reading this guide. Restart the client in this checkout and
   approve its hook trust prompt. Higher-priority settings or command-line flags
   can override project defaults. Keep workspace-write, on-request and network
   disabled; do not relax sandboxing to get the probe through.
5. Inspect the actual client configuration. CLI `/status` and the app permission
   controls should agree with those defaults. Check that `unified_exec` and
   `unified_exec_tty` are disabled **and that the offered shell is noninteractive**,
   with no stdin-continuation path. If a client still offers unified execution or
   an interactive shell, **STOP** shell work and report that capability as unverified.
   A canonical Bash hook alias cannot prove which backend ran it. Confirm the
   startup message and a fresh `[codex] startup` line in `.agent-log/YYYY-MM-DD.md`.
   Ask the agent to identify loaded instructions, available `$harness-grill`,
   `$harness-lane`, `$review-order`, `$cite-check`, `$closeout`, and native roster
   roles. Check for unexpected `AGENTS.override.md` files. On-disk presence alone
   is not discovery evidence.
6. With the person's specific probe approval, test denial using a harmless file:
   choose a **new, absent** path `.codex/probe-<unique>.txt` and ask the agent to add
   `probe` there via `apply_patch` without a grant. It must be refused and the file
   must remain absent. Retain the exact client-visible refusal and verify absence
   independently in the person's terminal. Do not run a risky Git push, install,
   external send, real deletion or out-of-tree write to test a deny.
7. **STOP:** the person types `auth-policy .codex/probe-<unique>.txt` as the whole
   next message. Retry the identical patch; it should now succeed. Ask the person
   to type `revoke-policy`, then attempt to append a harmless second line to the
   same file. It must refuse and the bytes must stay unchanged. In a second fresh
   session, attempting the same edit must refuse without its own grant. Inspect
   the arm/consume/revoke/deny audit lines. Leave the probe file until its cleanup
   is separately authorized; do not turn setup into an unapproved deletion.
8. Check roster behavior without starting work: with specific approval for the
   refusal probe, request an off-roster `default` agent with a harmless read task.
   It must be denied before a child exists. A valid custom-role probe is a real
   spawn and needs separate approval naming the role, read-only task and stop.
   Inspect that child's actual instructions and inherited tool/sandbox boundaries;
   its write restriction is prose. If the API cannot name a verified custom role,
   leave delegation unverified and ask before every future spawn.
9. **STOP:** qualify runtime failure behavior separately in a disposable copy the
   person controls. With the person making temporary fixture changes there, use
   the same harmless write probe when the launcher is missing, a hook times out,
   or a test hook emits malformed output. Record whether each tool proceeds. Do
   not break the active checkout's protection to run these probes. A process exit
   or timeout is not automatically a fail-closed result. Unexpected execution
   leaves that surface unverified; stop and explain the limit. The adapter's unit
   tests cover its own valid deny/error translations, not the client's failures.
10. Repeat the activation and grant probes independently in **both CLI and app**
    if both will be used. Record client version, OS, effective settings, event,
    exact observed refusal, independently checked file state and date in the
    local handoff. Mark only the observed cells live; report the other client as
    unprobed. `codex_status.py` intentionally continues to say it has not measured
    runtime activation, even after a manually recorded probe.
11. Explain Git separately. The existing pre-push guard ships unarmed; run
    `python3 scripts/test_prepush_install.py` for inspection only. **STOP:** any
    arming or installation is its own named policy/system action, using `SETUP.md`
    step 3 as reference. Its `CLAUDECODE` marker does not identify Codex. Shared
    pre-tool Git checks cover recognized shell text, not hidden interpreter calls.
    Default-branch pushes remain human-executed. GitHub `gate` and `operator-merge`
    checks are client-independent but only bind identities the ruleset covers;
    follow `SETUP.md` step 7 with the person if they want to configure protections.

Finish with the actual observed instruction, sandbox, hook, roster, Git and CI
coverage for each client. Name outstanding probes and failing tests. Do not call
this environment protected solely because configuration parses. Start ordinary
work through the native skills; keep repository-only tracking when no board or
memory connector is available, and use `$closeout` only on the person's request.
