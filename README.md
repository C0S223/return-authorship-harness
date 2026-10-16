# return-authorship-harness

A control layer for Claude Code: a written contract, the hooks that back it, a small roster
of delegate agents, and two workflows (a grill for decisions, a lane for builds) that keep a
human in charge of what an agent changes, pushes and merges.

This is a template snapshot of a harness one operator runs day to day. It ships the
mechanism, not the operator's records: no action logs, review history or handoffs.

## What is in it

| Path | What it holds |
|---|---|
| `CLAUDE.md` | The contract every session reads first: grounding, memory, permissions, git, audit, enforcement. |
| `.claude/settings.json`, `.claude/hooks/` | Hooks that gate policy-path edits, out-of-tree writes, git never-items (force push, new remotes, tags, default-branch push), off-roster spawns and non-loopback shell sends, and log escapes to `.agent-log/`. |
| `.claude/agents/`, `roles/` | The roster-bound delegates: `super-doer` builds, `senior-engineer` reviews code, `adversarial-reviewer` reviews prose, `recall` sweeps memory. `super-doer`, `senior-engineer` and `recall` take their full prompt from a role file; `adversarial-reviewer` carries its own; `roles/scribe.md` drafts PR bodies. |
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
   repository's URL, and put the same URL in the `placeholder` line of
   `tests/test_prepush_policy.py`, which anchors on that assignment; otherwise the suite goes red. Then follow **Setup per target** in `docs/enforcement/CLAUDE.md` for
   Windows, a managed cloud environment (`scripts/cloud-setup.sh`) or a self-hosted runner.
   Until you do, the hook is unarmed.
3. In your repository's settings, add a ruleset on the default branch that requires the
   `gate` and `operator-merge` checks, with your own account on its bypass list.
   `operator-merge` is red on every PR that touches a policy path, by design, and the ruleset
   also refuses a direct push to the default branch: you merge those PRs, and push the
   default branch, through that bypass. Give agents a login that is not on the list.
   The lane arms auto-merge on PRs that touch no policy path, so also enable
   **Allow auto-merge**.
4. Run the suite: `python scripts/run_tests.py`.
5. Read `CLAUDE.md`, then edit it to fit your work. It is written for this harness's
   operator: its PowerShell notes, its roster and its byte budget are starting points, but
   the suite pins the last two. A roster change also edits `.claude/agents/` and
   `.claude/hooks/spawn-roster.py` (`scripts/test_contract_sync.py`); a budget change raises
   `CEILING` in `scripts/test_claude_md_budget.py`, which also requires the numbered
   sections and the §6 pointer to itself. Change them in the same commit, or `gate` goes red.

`CLAUDE.md`, this `README.md` and the other paths listed under **Policy paths** in
`docs/enforcement/CLAUDE.md` are policy: a PR that changes one reads red on
`operator-merge`, and you merge it. For `gate` to pass, a PR also needs a reviewer's APPROVE
file under `grills/` for each kind it changes: `adversarial-reviewer` for Markdown,
`senior-engineer` for anything else (`scripts/stamp_check.py`). `grills/` ships absent, and
the lane's reviewers create it.

## Status, stated plainly

- Every Claude Code hook is **wired, not proven**; the pre-push hook is unarmed until step 2.
  The enforcement table in `docs/enforcement/CLAUDE.md` says which protections are
  cloud-off, and which are prose only, on each target. Rules bind as text whether or not a
  hook backs them.
- Cites in `docs/adr/0001-park-text-classifying-guards.md` point at review and handoff files
  that stay with the original operator and are not in this snapshot.
- `.agent-log/` and `worktrees/` are ignored. `handoffs/auto/` is tracked and ships
  empty: a session writes its auto-compact handoff there, and on a cloud closeout
  `session-close.sh` copies the day's audit lines there for commit.

## License

MIT. See `LICENSE`.
