#!/usr/bin/env python
"""CI half of the policy-path gate: a PR whose diff touches a
policy path fails the check, so auto-merge never fires and the PR waits for
the operator.

    python scripts/ci_policy_check.py [--repo DIR] [--base REF] [--head REF]

--base defaults to origin's default branch in DIR (refs/remotes/origin/HEAD);
exit 2 when it cannot be found.

Classifies every path in `git -C DIR diff --name-only BASE...HEAD` (merge-base
to HEAD; renames split into delete+add) with the live gate's is_policy(),
loaded exactly as scripts/prepush_check.py loads it -- so "an existing file
under scripts/, skills/ or templates/" means existing in THIS script's own
checkout, which in the workflow is the default branch's at base/, never the PR's -- plus
rules the hook does not carry: .github/, CODEX-SETUP.md and
docs/codex-enforcement.md configure CI or instruct Codex operation.

Read-only: no network, no fetch, no writes.

Exit: 0 no policy path in the diff; 1 one or more, each listed; 2 could not
run -- the predicate did not load, or git failed -- the same fail-closed shape
as stamp_check.py and prepush_check.py --strict, and a red job either way.

Self-check: scripts/test_ci_policy_check.py (discovered by run_tests.py's
scripts/test_*.py glob).
"""
import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import prepush_check as pc  # noqa: E402  (sibling: its loader and its ROOT are the point)
from stamp_check import default_base, NO_DEFAULT  # noqa: E402


# roles/** and graphs/** reach this check through is_policy(), like every
# other tracked policy path; CI also protects its workflow and Codex instructions.
def is_github(path):
    """Workflow policy paths. Folded like every rule in is_policy()."""
    return path.lower().startswith(".github/")


def flagged(paths, checker):
    """Repo-relative POSIX paths -> CI/instruction additions or the
    live gate's is_policy() resolved against pc.ROOT, this script's checkout."""
    return [p for p in paths
            if p.lower() in ("codex-setup.md", "docs/codex-enforcement.md") or is_github(p) or checker(os.path.normcase(os.path.realpath(
                os.path.join(str(pc.ROOT), p))))]


def changed_paths(repo, base, head):
    """Paths in BASE...HEAD, or (None, stderr) when git fails. `-z` so a
    non-ASCII name is not C-quoted; `--no-renames` so a renamed policy file
    appears under both its names."""
    done = subprocess.run(
        ["git", "-C", repo, "diff", "-z", "--no-renames", "--name-only",
         "%s...%s" % (base, head)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if done.returncode != 0:
        return None, done.stderr
    return [p for p in done.stdout.split("\0") if p], None


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--repo", default=".", help="checkout whose diff is classified")
    p.add_argument("--base", default=None, help="default: origin's default branch")
    p.add_argument("--head", default="HEAD")
    args = p.parse_args(argv)
    args.base = args.base or default_base(args.repo)
    if args.base is None:
        print(NO_DEFAULT)
        return 2
    checker = pc._load_is_policy()
    if checker is None:
        print("CONFIG: the policy predicate did not load (banner above)")
        return 2
    paths, err = changed_paths(args.repo, args.base, args.head)
    if paths is None:
        print("CONFIG: git diff %s...%s in %s failed: %s"
              % (args.base, args.head, args.repo, err.strip()))
        return 2
    hits = flagged(paths, checker)
    print("DIFF: %d path(s); existence judged against %s" % (len(paths), pc.ROOT))
    for h in hits:
        print("POLICY: %s" % h)
    print("RESULT: %s" % ("FAIL (%d policy path(s))" % len(hits) if hits else "PASS"))
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
