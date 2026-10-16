"""Mechanical half of the pre-push review. Gathers and verifies; judges almost
nothing; pushes nothing, ever.

    python scripts/prepush_check.py

The flow this automates one step of: commit -> review -> verdict -> push.

  GATHERING and MECHANICAL VERIFICATION are automatable, and are the tedious
  part a reviewer otherwise redoes by hand every time. That is what this does.

  JUDGEMENT stays with the reviewing agent. In particular this script does NOT
  fail on a failing test: a red test committed ahead of its fix is correct and
  expected here. It reports outcomes and lets the reviewer decide what they
  mean. A script that judged that would just be a worse reviewer.

  THE PUSH stays with the human. A default-branch push is a never-item with no
  unlock (guard: git-guard). This script prints the command and stops. It has
  no push path, deliberately -- not as an oversight to be fixed later.

Checks are executed through the one suite runner (scripts/run_tests.py):
its run_one(), its SKIP charter and its ARGS table. That is a BEHAVIOUR
CHANGE, not a de-duplication -- this script had no charter and no arg table.
It now skips what the runner parks, passes the argv the runner passes, runs
each check from its own directory rather than from ROOT, and inherits the
runner's temp-file capture and job-object kill instead of a pipe.

Exit code is about THIS SCRIPT's mechanical checks only, never about the
review's outcome. The DEFAULT is what every existing caller gets and is
unchanged: it reports, and returns 0 whatever any check did.

`--strict` is the one mode where the exit code carries a verdict,
so a MACHINE can produce a red, because nothing else in this tree can. Its
two nonzero codes do NOT mean the same thing:

  exit 1 -- a check RAN and FAILED.
  exit 2 -- NO check could run (the suite runner would not load, or
            RUN_TESTS_TIMEOUT is unusable). Nothing is verified; nothing is
            red either. Same rule the runner states for its own config
            errors at run_tests.py:87-90,99-101 -- a misconfiguration must
            never wear exit 1, which reads as "suites failed". The earlier
            ban on importing the runner's exit semantics was about not
            failing on a red test, not a licence to collapse two states into
            one code.

The two are mutually exclusive by construction: nothing-could-run means the
loop records every check NOT RUN, so no result is ever FAIL.
"""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_is_policy(hook_path=None):
    """The one policy-path predicate is is_policy() in the live gate; load it
    rather than restate it. A tuple here drifted and missed this very file
. HARNESS_ROOT is pinned to ROOT for the exec because the hook reads
    it at import time and must answer against the tree THIS script inspects.
    Returns None on any failure; the caller fails closed."""
    hook = str(hook_path or ROOT / ".claude" / "hooks" / "policy-mutate.py")
    old = os.environ.get("HARNESS_ROOT")
    os.environ["HARNESS_ROOT"] = str(ROOT)
    try:
        spec = importlib.util.spec_from_file_location("policymutate", hook)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.is_policy
    except Exception as e:
        msg = ("!!! could not load the policy-path predicate from %s\n"
               "!!! (%s: %s)\n"
               "!!! failing closed: EVERY file below is flagged POLICY PATH."
               % (hook, type(e).__name__, e))
        # The exception text is hostile input: a SyntaxError can embed any
        # source character, and a narrow console codepage (cp1252) made this
        # print raise instead of warn (F1). ASCII + backslashreplace survives
        # every codepage.
        print(msg.encode("ascii", "backslashreplace").decode("ascii"))
        return None
    finally:
        if old is None:
            os.environ.pop("HARNESS_ROOT", None)
        else:
            os.environ["HARNESS_ROOT"] = old


def _load_runner(runner_path=None):
    """SKIP, ARGS and run_one come from the one runner rather than a second
    set of them here. Loaded from this file's own SIBLING, not from ROOT: the
    runner ships with this script, while ROOT is whatever tree is being
    inspected. Returns None on any failure; the caller then fails closed and
    runs NOTHING, because running a check differently from how the runner runs
    it is the drift this import exists to end.

    runner_path overrides the sibling, and exists for the same reason
    _load_is_policy's hook_path does: the load-FAILURE path -- banner, ASCII
    encode, None -- is only reachable in a test by pointing at a runner that
    cannot load. Stubbing this function out instead replaces the code the
    test claims to cover."""
    runner = (Path(runner_path) if runner_path
              else Path(__file__).resolve().parent / "run_tests.py")
    try:
        spec = importlib.util.spec_from_file_location("runtests", str(runner))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception as e:
        msg = ("!!! could not load the suite runner from %s\n"
               "!!! (%s: %s)\n"
               "!!! failing closed: NO check below was run."
               % (runner, type(e).__name__, e))
        # ASCII + backslashreplace for the same reason the banner above is:
        # the exception text is hostile input on a narrow console codepage.
        print(msg.encode("ascii", "backslashreplace").decode("ascii"))
        return None


def policy_flagged(files, hook_path=None):
    """Repo-relative POSIX paths -> the subset the live gate calls policy.
    A flagged commit is not wrong, but it needed a typed one-shot grant, so
    the reviewer must see it called out rather than buried in a diffstat.
    Known boundary, inherited from the gate: under skills/scripts/templates
    only EXISTING files flag, so a path this range DELETED will not."""
    checker = _load_is_policy(hook_path)
    if checker is None:
        return list(files)
    return [f for f in files
            if checker(os.path.normcase(os.path.realpath(
                os.path.join(str(ROOT), f))))]


def git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args],
                          capture_output=True, text=True).stdout.strip()


def main(strict=False, runner_path=None):
    upstream = git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    if not upstream:
        print("no upstream for this branch — nothing to compare against")
        return 1
    rng = f"{upstream}..HEAD"

    commits = [ln for ln in git("log", "--oneline", rng).splitlines() if ln]
    if not commits:
        print(f"nothing unpushed against {upstream}")
        return 0

    files = [f for f in git("diff", "--name-only", rng).splitlines() if f]
    dirty = {ln[3:].strip() for ln in git("status", "--porcelain").splitlines()}

    print(f"=== {len(commits)} unpushed commits against {upstream}\n")
    for c in commits:
        print("  " + c)

    print(f"\n=== {len(files)} files touched\n")
    policy = policy_flagged(files)
    for f in files:
        marks = []
        if f in policy:
            marks.append("POLICY PATH — required a typed grant")
        if f in dirty:
            marks.append("ALSO DIRTY — a peer session may hold this file")
        print(f"  {f}" + ("   <-- " + "; ".join(marks) if marks else ""))

    # Every check living under a directory this range touched. Committing a
    # change beside a check and not running it is the thing worth catching.

    # This tree has no single name for a check: test_*.py, mutation_check.py
    # and snapshot.py are all checks. So anything unmatched is LISTED rather
    # than guessed at. The gap is a missing convention, not a missing pattern,
    # and §6 says a convention names what reads the artifact back or it does
    # not land. Found by this script silently skipping two repaired checks in
    # the very range it was first run against.
    dirs = {str(Path(f).parent) for f in files}
    # Excluding itself is not defensive tidiness: this file ends in
    # `_check.py`, so once a commit touches scripts/ it discovers and runs
    # ITSELF, and each nested run does it again. Found by running it.
    candidates = {p for d in dirs for p in (ROOT / d).glob("*.py")
                  if p.is_file() and p.resolve() != Path(__file__).resolve()}
    tests = sorted(p for p in candidates
                   if p.name.startswith("test_") or p.name.endswith("_check.py"))
    unmatched = sorted(p for p in candidates
                       if p not in tests and p.name in {f.rsplit("/", 1)[-1]
                                                        for f in files})

    print(f"\n=== {len(tests)} checks in touched directories\n")
    results = []
    runner = _load_runner(runner_path)
    # Two different reasons nothing can run, reported as the same thing: NOT
    # RUN. RUN_TESTS_TIMEOUT is validated HERE, once, as run_tests.main does
    # it -- run_one() calls timeout_secs() per suite, and letting that
    # ValueError out of main() replaced the whole report with a traceback and
    # a nonzero exit, breaking the default contract at :11-24 (F1). The
    # runner's exit semantics stay unimported: this is a report line.
    not_run = None
    if runner is None:
        not_run = "the suite runner did not load"
    else:
        try:
            runner.timeout_secs()
        except ValueError as e:
            not_run = "RUN_TESTS_TIMEOUT is unusable (%s)" % e
            print("!!! %s\n!!! failing closed: NO check below was run."
                  % not_run)
            runner = None
    for t in tests:
        r = t.relative_to(ROOT).as_posix()
        if runner is None:
            results.append((t, "NOT RUN"))
            print(f"  [NOT RUN] {r}")
            continue
        if r in runner.SKIP:
            print(f"  [skip] {r}")
            print(f"         {runner.SKIP[r][:110]}")
            continue
        # cwd is the check's OWN directory, as the runner does it: desk suites
        # carry local shims and imports that assume it. run_one returns None
        # for the code on timeout, which is a FAIL.
        code, _secs, out = runner.run_one(
            [sys.executable, t.name] + runner.ARGS.get(r, []), str(t.parent))
        tail = out.decode("utf-8", "replace").strip().splitlines()
        verdict = "pass" if code == 0 else "FAIL"
        results.append((t, verdict))
        print(f"  [{verdict}] {r}")
        if tail:
            print(f"         {tail[-1][:110]}")

    if unmatched:
        print(f"\n=== {len(unmatched)} touched .py files matching no check "
              f"convention — NOT RUN\n")
        for p in unmatched:
            print(f"  {p.relative_to(ROOT)}")
        print("\n  Named neither test_*.py nor *_check.py. If any of these is a "
              "check,\n  it was committed without being run here — say so, or "
              "rename it.")

    print("\n=== for the reviewer\n")
    if policy:
        print(f"  {len(policy)} policy-path file(s) in this range — verify each "
              "change is within what the grant covered.")
    # `v != "pass"` folded NOT RUN into FAIL, so checks that never started
    # were counted as failures and explained by the red-ahead sentence below
    # -- which is only ever about a check that RAN and went red (F2).
    failing = [t for t, v in results if v == "FAIL"]
    never_ran = [t for t, v in results if v == "NOT RUN"]
    if never_ran:
        print("  %d check(s) above did NOT RUN -- %s. Every one is unverified, "
              "not green,\n     and none of them is a failing check."
              % (len(never_ran), not_run))
    elif not_run:
        # never_ran is empty here because there were no checks AT ALL, not
        # because everything ran. Gating this notice on never_ran dropped it
        # from the summary in exactly that state, leaving the reviewer with
        # "no checks here, confirm that is right" and no hint that this run
        # could not have run one anyway (F3). The baseline printed it in both.
        print("  Note: %s. No check in this range could have run regardless."
              % not_run)
    if failing:
        print(f"  {len(failing)} failing check(s). NOT automatically a problem: a "
              "red test committed\n     ahead of its fix is correct. Confirm each "
              "fails for the reason it claims.")
    if not tests:
        print("  No checks in the touched directories. Confirm that is right.")

    print("\n=== push\n")
    print(f"  git push {upstream.split('/')[0]} {git('rev-parse', '--abbrev-ref', 'HEAD')}")
    print("\n  This script has no push path. Default branch: the human types "
          "the push,\n  always — a never-item with no unlock. Feature branch: "
          "the agent may push on\n  the human's go; "
          "landing stays with the operator.")

    # ADDITIVE, and that is the whole point. The default stays 0 no
    # matter what failed: this script's job is a reviewer's REPORT, and a red
    # test committed ahead of its fix is correct here. `--strict` is the one
    # named condition under which the strict mode reopens -- it exists so a MACHINE can
    # produce a red. Written when there was no CI and every "green" here was an
    # agent asserting it; now CI's `gate` job runs the suite on every
    # PR to the default branch, and only the tests call --strict. Strict mode
    # adds a caller who can disbelieve that assertion; it does not change what
    # the report says, and nothing in the default path reads this flag.
    # 2, not 1: nothing ran, so nothing is verified AND nothing is red. Exit 1
    # here is a misconfiguration wearing a real-failure code -- the class the
    # runner names for itself at run_tests.py:87-90,99-101 and handles the same
    # way. The earlier ban was on failing this script when a TEST goes red, not
    # on giving two states two codes.
    if strict and never_ran:
        print(f"\n=== STRICT: {len(never_ran)} check(s) never ran -- "
              f"{not_run}, exit 2\n")
        return 2
    if strict and failing:
        print(f"\n=== STRICT: {len(failing)} failing check(s), exit 1\n")
        return 1
    return 0


if __name__ == "__main__":
    # Unknown arguments are a HARD ERROR, not ignored. `"--strict" in argv` on
    # its own fails open: `--Strict`, `-strict` and `--strict=1` all yield
    # strict=False and exit 0, so automation wired with a typo believes it has
    # a gate and has none -- which is the exact condition strict mode exists to
    # end. A flag whose misspelling silently disarms it is worse than no flag.
    _args = sys.argv[1:]
    _bad = [a for a in _args if a != "--strict"]
    if _bad:
        sys.exit("prepush_check: unrecognised argument(s): %s\n"
                 "                the only accepted flag is --strict"
                 % " ".join(_bad))
    sys.exit(main("--strict" in _args))
