---
name: review-order
description: Print the header of a reviewer work order from live git facts — revision under review, origin's default branch (`refs/remotes/origin/HEAD`) as last seen, merge-base, a FREEZE line, and the reviewer's real tool grant read from .claude/agents/ — plus a cite-check of each artifact. Use every time before spawning adversarial-reviewer or senior-engineer; paste the block verbatim at the top of the spawn prompt. Invoke as /review-order <reviewer> <worktree> [--artifact <path> ...].
---

# review-order

```bash
python .claude/skills/review-order/review_order.py <reviewer> <worktree> [--artifact <path-in-worktree> ...]
```

**Paste what it prints, verbatim, at the top of the spawn prompt.** Never retype a sha, a
count, or a tool list into a work order.

## What it refuses

A dirty worktree. Commit or discard first; a review over uncommitted changes names a revision
that does not exist, and the reviewer will (correctly) refuse the order.

## What it does not do

**Fetch.** Network is the hub's call under `CLAUDE.md` §2, not a script's. The BASE line states
when origin's default branch was last seen; if that could be stale, run the fetch it prints and re-run
this.

## The lines, and why each exists

| Line | Failure it prevents |
|---|---|
| `REVISION UNDER REVIEW` | Reviewers refuse orders with no revision. |
| `BASE` | The default branch's sha (`refs/remotes/origin/HEAD`'s target) may be stale. |
| `MERGE-BASE` / ahead | Confirms the branch is based where the order claims. |
| `FROZEN` | A reviewer could grade a superseded revision. |
| `REVIEWER -- tools` | `adversarial-reviewer` has no Bash. |
| `ARTIFACT -- cite-check` | The mechanical defects the reviewer would otherwise spend its pass on. A clean count means the cites resolve, not that they say what the prose claims (`.claude/skills/cite-check/cite_check.py:17-18`). |
| `AUTHOR CHECK` | The author's own recurring defects: an unsourced claim, a default credited to the operator, a contradiction left in unchanged text, or a repair that added a claim. |

After the header, the order still needs the reviewer's task: the artifact's purpose, the read
set, and what verdict is being asked for. That part is judgement and stays hand-written. The
dispatcher also runs `python .claude/skills/cite-check/cite_check.py <artifact>` on each
artifact, reads every cited line or range against the prose that cites it, and writes
`cite lines read: yes` or `cite lines read: no -- <why>` under the header, for the reviewer
to weigh; an order carrying neither line is not dispatched.
Before dispatch the author also answers the four AUTHOR CHECK questions under the header, one
line each (`author check N: yes`, or what it found and fixed), re-run for every resume;
an order missing any of the four is not dispatched. The answers are the author's claim, for the
reviewer to weigh, not evidence.
