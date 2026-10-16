# return-authorship-harness

A starter kit that keeps you in charge of an AI coding agent. It gives Claude Code a written
rulebook (`CLAUDE.md`), safety checks that stop risky actions before they happen, and a
review step before any change lands in your project.

## What you need

- Claude Code.
- Python 3, named `python3` or `python`.
- Git, and jq (a small tool the safety checks use to read their settings).
- A GitHub account.

## Get started

1. On GitHub, click **Use this template**, choose **Private**, and create the copy under
   your own account.
2. Clone your copy, open it in Claude Code, and say: **read SETUP.md and set me up**.
3. The agent walks you through the rest one step at a time, and stops whenever a step is
   yours to do.

If Claude Code answers with `PREFLIGHT BLOCK`, a tool from the list above is missing.
Install it, then restart Claude Code.

## Status

The safety checks work once Python is present. Setup ends with a short test that proves one
of them blocks on your machine; the push guard stays off until setup turns it on.

## What is inside

- `CLAUDE.md`: the rules every session reads first.
- `.claude/`: the safety checks (hooks), settings, helper agents and skills.
- `graphs/`, `roles/`: two workflows, a grill for decisions and a lane for builds, and the
  helpers' full instructions.
- `scripts/`, `tests/`: the test suite and the checks GitHub runs on each pull request.
- `docs/`: which protection is backed by what, on each platform. Some references in
  `docs/adr/` point at files that stayed with the original author.

## License

MIT. See `LICENSE`.
