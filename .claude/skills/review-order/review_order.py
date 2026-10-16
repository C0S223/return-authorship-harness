#!/usr/bin/env python3
"""Print the header block of a review work order from live facts, never from memory.

Why: in one session the hub wrote a stale base sha into every
work order it issued (the base moved four times underneath it), told a reviewer with no Bash grant
to run git three times, and had six of seven reviews grade a revision the branch had already
moved past. Every one of those is a fact the tree can state exactly at the moment the order is
written. This prints them; the hub pastes the block verbatim at the top of the spawn prompt.

It does not fetch. A fetch is network, and whether the hub may fetch is the hub's call under the
contract, not this script's. The block states when the base was last seen so a stale
base is visible rather than silent. The base is origin's default branch, read from
refs/remotes/origin/HEAD whatever its name; when that is unset or dangling the script refuses
(`git remote set-head origin --auto` records it) rather than guess a name.

It refuses a dirty worktree: a work order over uncommitted changes names a revision that does
not exist.

Usage:
  python .claude/skills/review-order/review_order.py <reviewer> <worktree> [--artifact <path> ...]

  reviewer   a name under .claude/agents/ (adversarial-reviewer, senior-engineer, ...)
  worktree   the checkout under review; the branch and tip are read from it
  --artifact a file the reviewer is to grade, relative to the worktree; repeatable. Each is
             cite-checked and its last-touching commit named.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE.parent / "cite-check"))
import cite_check  # noqa: E402


def git(wt, *args):
    r = subprocess.run(["git", "-C", str(wt), *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode:
        sys.exit(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout.strip()


def default_base(wt):
    """`origin/<name>` from refs/remotes/origin/HEAD; None when unset or naming no commit."""
    r = subprocess.run(["git", "-C", str(wt), "symbolic-ref", "-q", "refs/remotes/origin/HEAD"],
                       capture_output=True, text=True)
    ref = r.stdout.strip()
    if r.returncode or not ref.startswith("refs/remotes/origin/"):
        return None
    v = subprocess.run(["git", "-C", str(wt), "rev-parse", "-q", "--verify", ref + "^{commit}"],
                       capture_output=True, text=True)
    return None if v.returncode else "origin/" + ref[len("refs/remotes/origin/"):]


def last_touched(wt, art):
    """A commit, or the reason there is none. An empty field reads as a missing lookup."""
    return git(wt, "log", "-1", "--format=%h", "--", art) or "untracked (not in git)"


def tool_grant(reviewer):
    f = ROOT / ".claude" / "agents" / f"{reviewer}.md"
    if not f.is_file():
        sys.exit(f"no such reviewer: {f}")
    head = f.read_text(encoding="utf-8").split("---")[1]
    m = re.search(r"^tools:\s*(.+)$", head, re.M)
    return [t.strip() for t in m.group(1).split(",")] if m else []


# The four defect kinds behind recurring prose blocks (counts and their source: SKILL.md,
# the AUTHOR CHECK row). The author answers each before
# dispatch, so the reviewer's pass is spent on what the author could not see.
AUTHOR_CHECK = (
    "SOURCED: every new fact, count, date or quote points at a line that carries it, not only a cite that resolves.",
    "THEIRS OR MINE: every ruling credited to the operator is their words on record; every default the author chose is marked as the author's.",
    "UNCHANGED TEXT: the edited files, and the files that cite them, were searched for lines the change now contradicts or leaves stale.",
    "REPAIRS: a repair adds no new claim, or each new claim passed 1-3.",
)


def author_check():
    print("AUTHOR CHECK -- answer each under this header before dispatch (`author check N: yes`, or what was fixed); "
          "an order without all four answers is not dispatched:")
    for i, q in enumerate(AUTHOR_CHECK, 1):
        print(f"  {i}. {q}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("reviewer")
    ap.add_argument("worktree")
    ap.add_argument("--artifact", action="append", default=[])
    a = ap.parse_args()
    wt = Path(a.worktree).resolve()

    dirty = git(wt, "status", "--porcelain")
    if dirty:
        sys.exit("REFUSED: worktree is dirty -- commit or discard first, a review needs a revision:\n" + dirty)

    branch = git(wt, "rev-parse", "--abbrev-ref", "HEAD")
    tip = git(wt, "rev-parse", "--short", "HEAD")
    tip_full = git(wt, "rev-parse", "HEAD")      # the pinned line: reviewers refuse a short sha
    tip_when = git(wt, "log", "-1", "--format=%cI", "HEAD")
    dflt = default_base(wt)
    if dflt is None:
        sys.exit("REFUSED: origin's default branch was not found (refs/remotes/origin/HEAD unset "
                 "or dangling); run `git remote set-head origin --auto` first")
    master = git(wt, "rev-parse", "--short", dflt)
    master_when = git(wt, "log", "-1", "--format=%cI", dflt)
    base = git(wt, "rev-parse", "--short", git(wt, "merge-base", "HEAD", dflt))
    ahead = git(wt, "rev-list", "--count", f"{dflt}..HEAD")
    tools = tool_grant(a.reviewer)

    print(f"REVISION UNDER REVIEW: {branch} @ {tip_full}  (committed {tip_when}; worktree {wt})")
    print(f"BASE: {dflt} (origin's default branch) = {master} as last fetched (committed {master_when}). "
          f"Run `git -C \"{wt}\" fetch origin` before dispatch if that may be stale.")
    print(f"MERGE-BASE: {base}; {ahead} commit(s) ahead of {dflt} at emission time.")
    print(f"FROZEN: {branch} does not move while this review runs. A commit after {tip} voids this order; "
          f"the reviewer grades {tip} and nothing else.")
    print(f"REVIEWER: {a.reviewer} -- tools: {', '.join(tools) or 'none declared'}.", end="")
    if "Bash" not in tools:
        print(" NO Bash: do not ask it to run anything; paste command outputs into the order.", end="")
    print()
    for art in a.artifact:
        p = (wt / art).resolve()
        if not p.is_file():
            print(f"ARTIFACT: {art} -- NOT FOUND in worktree")
            continue
        last = last_touched(wt, art)
        if p.suffix.lower() != ".md":           # the lint is for prose; code has its own reviewer
            print(f"ARTIFACT: {art} (last touched {last})")
            continue
        findings = []
        try:
            cite_check.check_file(p, wt, findings)
        except Exception as e:                  # a lint crash must not take the whole order down
            print(f"ARTIFACT: {art} (last touched {last}) -- cite-check CRASHED: {e!r}")
            continue
        kinds = ("FAIL", "WARN", "SECTION?", "ANCHOR?", "MEASURED?", "UNANCHORED")
        n = {k: sum(1 for x in findings if x[0] == k) for k in kinds}
        print(f"ARTIFACT: {art} (last touched {last}) -- cite-check: "
              + ", ".join(f"{n[k]} {k}" for k in kinds)
              + ("" if n["FAIL"] == 0 else "  <- fix before dispatch, or name each FAIL in the order"))
    author_check()
    return 0


if __name__ == "__main__":
    sys.exit(main())
