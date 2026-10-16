# return-authorship-harness

A control layer for Claude Code: a written contract, the hooks that back it, a small roster
of delegate agents, and two workflows (a grill for decisions, a lane for builds) that keep a
human in charge of what an agent changes, pushes and merges.

This is a template snapshot of a harness one operator runs day to day. It ships the
mechanism, not the operator's records: no decision logs, reviews or handoffs.

## What is in it

| Path | What it holds |
|---|---|
| `CLAUDE.md` | The contract every session reads first: grounding, memory, permissions, git, audit, enforcement. |
| `.claude/settings.json`, `.claude/hooks/` | Hooks that gate policy-path edits, out-of-tree writes, git never-items (force push, new remotes, tags, default-branch push), off-roster spawns and network sends, and log escapes to `.agent-log/`. |
| `.claude/agents/`, `roles/` | The delegate roster: `super-doer` builds, `senior-engineer` reviews code, `adversarial-reviewer` reviews prose, `recall` sweeps memory. `super-doer`, `senior-engineer` and `recall` take their full prompt from a role file; `adversarial-reviewer` carries its own; `roles/scribe.md` drafts PR bodies. |
| `graphs/grill.md`, `graphs/lane.md` | The grill (one question per decision, the operator rules) and the build lane (work order, build, review by kind, preflight, land). |
| `.claude/skills/` | `claim`, `closeout`, `review-order`, `cite-check`, `check-prs`, `goal-prompt-generator`. |
| `scripts/`, `tests/` | The CI gates (`ci_policy_check.py`, `stamp_check.py`) and the test suite (`run_tests.py`). |
| `.github/workflows/ci.yml` | Two checks on every PR: `gate` (reviewer stamp plus suite) and `operator-merge` (red when a policy path changes, so a human merges it). |
| `.githooks/`, `tools/git-hooks/` | The pre-push hook and its dispatcher. |
| `docs/` | The enforcement reference, an ADR, the auto-compact runbook and the handoff convention. |

## Requirements

- Claude Code.
- Python 3 on `PATH` as `python`: the hooks in `.claude/settings.json` call `python`, not
  `python3`. CI runs 3.14.
- `bash`, `git` and `jq`. Without `jq`, the escape log degrades to raw lines.
- A board connector is optional. With none, the grill, the lane and the `claim`,
  `closeout` and `goal-prompt-generator` skills skip each board step, logging one line, and
  the work order and desk files are the record.

## Setup

1. Create your repository from this template.
2. Arm the pre-push hook. Set `APPROVED_ORIGIN_URL` in `.githooks/pre-push` to your
   repository's URL. Then follow **Setup per target** in `docs/enforcement/CLAUDE.md` for
   Windows, a managed cloud environment (`scripts/cloud-setup.sh`) or a self-hosted runner.
   Until you do, the hook is unarmed.
3. In your repository's settings, add a ruleset on the default branch that requires the
   `gate` and `operator-merge` checks.
4. Run the suite: `python scripts/run_tests.py`.
5. Read `CLAUDE.md`, then edit it to fit your work. It is written for this harness's
   operator: its PowerShell notes, its roster and its budget
   (`scripts/test_claude_md_budget.py`) are starting points, not requirements.

## Status, stated plainly

- Every hook is **wired, not proven**. The enforcement table in `docs/enforcement/CLAUDE.md`
  says which protections are cloud-off, and which are prose only, on each target. Rules
  bind as text whether or not a hook backs them.
- Cites in `docs/adr/0001-park-text-classifying-guards.md` point at review and handoff files
  that stay with the original operator and are not in this snapshot.
- `.agent-log/` and `worktrees/` are ignored. `handoffs/auto/` exists only for the
  auto-compact hook to write into.

## License

MIT. See `LICENSE`.
