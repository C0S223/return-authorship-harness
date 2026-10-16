#!/usr/bin/env python
"""Run every test suite in the tree. One command, discovery-based, stdlib only.

Usage (PS 5.1 friendly):  python scripts\run_tests.py

Discovers, from the repo root (this file's parent's parent):
  tests/**/test*.py
  scripts/test_*.py
  .claude/skills/**/test*.py
  tests/test_auto_compact.sh  (via bash; loud SKIP if bash absent)

Excluded by design: mutate_auto_compact.sh (mutation battery, not a suite),
probe_*.py / measure_*.py (one-shot artifacts, not tests), and anything under
a nested git checkout (a worktree inside the tree is a second copy of every
suite, not more suites -- see in_nested_checkout).

Suites run concurrently: RUN_TESTS_WORKERS threads (default
2 per CPU this process may use, at most 8), each still its own subprocess with its own temp-file
capture and job-object kill. RUN_TESTS_WORKERS=1 is one suite at a time.
Suites that write fixed paths cannot overlap and run after the pool (SERIAL).

A suite whose directory is a package (holds __init__.py) runs with the
package's parent prepended to PYTHONPATH, so `import <package>.x` resolves
from the package's top.

Output: one line per suite (PASS/FAIL/SKIP name seconds) as each completes,
summary line.
Exit codes: 0 all green, 1 one or more suites FAILed, 2 runner internal
error or refusal - bad RUN_TESTS_TIMEOUT or RUN_TESTS_WORKERS, zero python
suites discovered, or a run where nothing executed. A root that discovers nothing, and a run that
skips everything, must never read as a green tree. Per-suite timeout kills
the suite's whole process tree so one hung suite (or a lingering grandchild)
cannot wedge the runner.

Self-check: scripts/test_run_tests.py (discovered by this runner's own glob).
"""
import concurrent.futures
import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

if os.name == "nt":
    import ctypes
    _K32 = ctypes.windll.kernel32

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Skip charter - three explicitly named categories:
#   1. cannot-run-headless (live network, armed instance, ...).
#   2. known-failing-parked: the suite pins a defect whose repair is
#      deliberately parked; skipping keeps the clean tree green without
#      pretending the suite passes. Retire the entry when the repair unparks.
#   3. wrong-interpreter: the suite imports dependencies that live in another
#      venv than the interpreter this runner runs under.
# Filing a suite under a category that does not describe it is how a skip
# charter stops meaning anything. Keys are repo-relative posix paths. A dict
# is single-entry-safe (a one-entry tuple-of-pairs without its trailing comma
# crashes dict()).
SKIP = {}

# Extra argv for suites that need it. Same key shape as SKIP. The pre-push
# gate is NOT armed in a fresh checkout of this tree, so the read-back runs
# without --require-installed and reports "not installed" loudly as WARN. The
# change that arms the gate adds
#     "scripts/test_prepush_install.py": ["--require-installed"],
# here in the same commit: the flag and the fact travel together, or "armed and
# since deleted" reads green from the one file whose job is noticing.
ARGS = {}

# Suites that write FIXED paths and therefore cannot overlap with anything,
# including a second copy of themselves. They run after the pool drains, one
# at a time. Each value names the fixed path that puts the suite here - that
# is the whole membership test.
SERIAL = {}

# Suites submitted to the pool FIRST, in this order, then everything else in
# path order. The pool starts suites in submit order, so a long suite that
# sorts late in the path order starts late and the run ends when it ends.
# Ordering only: every suite still runs, and a name here that no longer exists
# is simply never submitted. Longest first by one-at-a-time wall time.
FIRST = [
    "tests/test_auto_compact.sh",
    "scripts/test_policy_integrity.py",
    "scripts/test_run_tests.py",
    "tests/test_session_close.py",
    "scripts/test_stamp_check.py",
    "tests/test_policy_mutate.py",
    "tests/test_policy_batch.py",
    "tests/test_log_escape.py",
    "scripts/test_gate_decisions.py",
    "tests/test_prepush_pin.py",
]


def timeout_secs():
    # ponytail: env knob exists so the runner's own timeout proof can run in
    # seconds instead of minutes; a bad value exits 2, not 1. Non-positive is
    # a bad value: 0 or -1 makes every proc.wait raise TimeoutExpired at once,
    # so every suite "times out" and the runner exits 1 - a misconfiguration
    # wearing a real-failure exit code, which is the class F3 closed (N2).
    raw = os.environ.get("RUN_TESTS_TIMEOUT", "120")
    secs = int(raw)
    if secs <= 0:
        raise ValueError("RUN_TESTS_TIMEOUT must be a positive integer, got %r" % raw)
    return secs


def usable_cpus():
    # The CPUs this process may run on, not the machine's: a CI container or a
    # taskset pins it to fewer than os.cpu_count() reports. sched_getaffinity
    # is absent on Windows and macOS, where cpu_count() is the best there is.
    if hasattr(os, "sched_getaffinity"):
        return len(os.sched_getaffinity(0)) or 1
    return os.cpu_count() or 1


def worker_count():
    # Same shape as timeout_secs(): a bad value is a CONFIG error (exit 2),
    # never exit 1, which reads as "suites failed" - that is N2's class.
    # Default: 2 per usable CPU. The suites spend much of their time asleep
    # or waiting on a child (a baseline run on 4 CPUs used ~90 of ~156
    # CPU-seconds), so one worker per CPU leaves the CPUs idle ~40% of the run;
    # 2 per CPU keeps them busy (3 and 4 per CPU measured slower: contention).
    # Sized to the CPUs this process may use, not the machine's (usable_cpus),
    # so a pinned CI runner gets its own count. Capped at 8: 32 workers on a 16-CPU Windows host won ~6% wall but stretched
    # test_auto_compact.sh from 65s to 80s of its 120s timeout. GitHub's 4
    # CPUs give 8 either way.
    raw = os.environ.get("RUN_TESTS_WORKERS", "")
    if not raw:
        return min(2 * usable_cpus(), 8)
    n = int(raw)
    if n <= 0:
        raise ValueError("RUN_TESTS_WORKERS must be a positive integer, got %r" % raw)
    return n


def in_nested_checkout(path):
    """True if path sits inside its own git checkout below ROOT.

    A worktree placed inside the tree instead of at CLAUDE.md s3's `worktrees/<n>`
    is a second copy of every suite, and the globs cannot tell a copy from a
    suite: measured 2026-09-09, three checkouts under worktrees/
    turned 72 suites into 270 and counted every main-tree failure three times --
    a tree whose own health number is wrong in the alarming direction. Keyed on
    the nested `.git` rather than on a directory name, because nothing reads s3's
    placement convention back, so the next misplaced checkout is excluded without
    anyone having to notice it was misplaced.

    Over-exclusion is the dangerous direction here (a suite that never
    runs is indistinguishable from one that passes), and it is already guarded --
    test_discovery_coverage.py compares discover() against `git ls-files`, and a
    second checkout contributes no tracked paths, so anything this drops that
    mattered turns that suite red.
    """
    d = os.path.dirname(path)
    # ponytail: dirname strictly shortens, and ROOT is a repo root rather than a
    # drive root, so the only fixed point is already shorter than ROOT.
    while len(d) > len(ROOT):
        if os.path.exists(os.path.join(d, ".git")):
            return True
        d = os.path.dirname(d)
    return False


def import_root(cwd):
    """The directory to prepend to PYTHONPATH so a suite living inside a package
    can import that package by name, or None when cwd holds no __init__.py.

    A suite that does `import pkg.x` and runs with cwd = the package itself
    puts the package's INSIDE on sys.path and never its name, so it fails on
    every run. The walk goes up while __init__.py
    exists so a nested package resolves from its top, not from the suite's own
    directory; the `!= d` conjunct stops at a filesystem root.
    """
    d = os.path.abspath(cwd)
    if not os.path.isfile(os.path.join(d, "__init__.py")):
        return None
    while (os.path.isfile(os.path.join(os.path.dirname(d), "__init__.py"))
           and os.path.dirname(d) != d):
        d = os.path.dirname(d)
    return os.path.dirname(d)


# The globs the module docstring lists, module-level so something can read them
# back. When nothing did, the list drifted from the docstring through two
# edits, neither noticed. D1 in test_run_tests.py compares the two.
PATTERNS = [
    # Any tests/ tree, recursively: a suite that never runs is
    # indistinguishable from one that passes.
    "tests/**/test*.py",
    "scripts/test_*.py",
    # Skill self-tests live beside their skill.
    ".claude/skills/**/test*.py",
]


def discover():
    found = []
    for pat in PATTERNS:
        found.extend(glob.glob(os.path.join(ROOT, pat), recursive=True))
    # dedupe (overlapping patterns), drop second checkouts, stable order
    return sorted(set(os.path.normpath(p) for p in found
                      if not in_nested_checkout(p)))


def rel(path):
    return os.path.relpath(path, ROOT).replace(os.sep, "/")


SKIPPED_RE = re.compile(rb"^(?:OK|FAILED) \([^)\n]*?skipped=(\d+)", re.M)


def tests_skipped(out):
    """Tests unittest reports as skipped in a suite's output (its closing
    `OK (skipped=N)` / `FAILED (..., skipped=N)` lines), 0 when none."""
    return sum(int(n) for n in SKIPPED_RE.findall(out or b""))


def run_one(cmd, cwd):
    """Run one suite. Returns (returncode-or-None, seconds, output-bytes).

    stdout goes to a temp FILE, not a pipe: a grandchild inheriting the
    handle can then never block the runner (F1 - with a pipe, communicate()
    waits on every write-handle holder). On timeout the whole process tree
    is killed via a Windows job object: the suite is assigned to a job at
    spawn, and TerminateJobObject kills every process in it instantly.
    NOT taskkill /F /T: taskkill goes through WMI and was measured taking
    ~35s on this host even for a single child, which blows the wall-clock
    bound the timeout exists to hold. proc._handle is CPython's stable
    private process handle; there is no public accessor on Windows.
    """
    limit = timeout_secs()
    start = time.time()
    with tempfile.TemporaryFile() as out:
        # Gate suites describe the host column; under a cloud marker every gate
        # answers cloud-off and ten suites go red. Strip the
        # markers unless RUN_TESTS_TARGET asks for a cloud column.
        env = dict(os.environ)
        target = env.get("RUN_TESTS_TARGET", "host")
        if target == "host":
            env.pop("CLAUDE_CODE_REMOTE", None); env.pop("HARNESS_BOUNDARY", None)
        # A suite inside a package imports it by name; see import_root.
        # Prepended, never replaced, so a caller's PYTHONPATH survives. Here
        # rather than in main() because prepush_check.py runs checks through
        # this function and must run them the same way.
        root = import_root(cwd)
        if root:
            old = env.get("PYTHONPATH")
            env["PYTHONPATH"] = root + (os.pathsep + old if old else "")
        proc = subprocess.Popen(cmd, cwd=cwd, stdout=out, stderr=subprocess.STDOUT, env=env)
        job = None
        if os.name == "nt":
            h = _K32.CreateJobObjectW(None, None)
            if h:
                if _K32.AssignProcessToJobObject(h, int(proc._handle)):
                    job = h
                else:
                    # ponytail: assignment can fail on pre-Win8 nesting; degrade
                    # to proc.kill() (direct child only) - but close the handle
                    # we created first, or one kernel handle leaks per suite (N1).
                    _K32.CloseHandle(h)
        try:
            code = proc.wait(timeout=limit)
        except subprocess.TimeoutExpired:
            if job:
                _K32.TerminateJobObject(job, 1)
            else:
                proc.kill()
            proc.wait()
            code = None
        finally:
            if job:
                _K32.CloseHandle(job)
        out.seek(0)
        data = out.read()
    if code is None:
        data += b"\n[runner] TIMEOUT after %ds; process tree killed" % limit
    return code, time.time() - start, data


def refuse(why):
    print("RUNNER ERROR: %s under %s - refusing to report green" % (why, ROOT))
    return 2


def main():
    timeout_secs()  # fail fast (exit 2) on bad config, before any suite runs
    workers = worker_count()
    suites = discover()
    sh = os.path.join(ROOT, "tests", "test_auto_compact.sh")

    # N3, branch 1 (pre-flight): empty python discovery refuses on its own,
    # whether or not the shell suite exists. The globs going quiet IS the
    # reorg/drift failure this guard is for, and test_auto_compact.sh sitting
    # there says nothing about whether the other 16 still resolve. The old
    # guard was conjunctive, so a shell-suite-only root reported green.
    if not suites:
        return refuse("zero python suites discovered")

    results = []  # (status, relpath, seconds, output)

    def record(status, r, secs, out):
        # A suite counts whole, but unittest's own skips inside it are named:
        # without pyyaml the workflow-shape tests skip and the suite still
        # passes, and a summary reading "0 skip" hid that (finish-run probe P2).
        n = tests_skipped(out)
        print("%s %-60s %6.1fs%s" % (status, r, secs,
                                     "  (%d tests skipped)" % n if n else ""))
        results.append((status, r, secs, out))

    pooled = []  # (relpath, cmd, cwd) - submit order
    serial = []  # same shape, drained one at a time after the pool

    # The shell suite is submitted FIRST, not run last: at ~45s it is the
    # longest single suite in the tree, so a pool that starts it last finishes
    # when it finishes. Not python, run via bash when available, never dropped
    # silently.
    if os.path.exists(sh):
        r = rel(sh)
        bash = shutil.which("bash")
        if bash is None:
            print("SKIP %-60s (bash not on PATH; run it manually)" % r)
            results.append(("SKIP", r, 0.0, b""))
        else:
            pooled.append((r, [bash, os.path.basename(sh)], os.path.dirname(sh)))

    for path in suites:
        r = rel(path)
        if r in SKIP:
            print("SKIP %-60s (%s)" % (r, SKIP[r]))
            results.append(("SKIP", r, 0.0, b""))
            continue
        job = (r, [sys.executable, os.path.basename(path)] + ARGS.get(r, []),
               os.path.dirname(path))
        (serial if r in SERIAL else pooled).append(job)

    # FIRST (which leads with the shell suite) in its order, then path order;
    # the sort is stable, so the rest keep path order.
    rank = {r: i for i, r in enumerate(FIRST)}
    pooled.sort(key=lambda j: rank.get(j[0], len(FIRST)))

    def run_job(job):
        r, cmd, cwd = job
        code, secs, out = run_one(cmd, cwd)
        # A suite whose first line is "SKIP:" declares a missing
        # third-party dependency (per-file guard) and is not a pass.
        if code == 0 and out.lstrip().startswith(b"SKIP:"):
            return "SKIP", r, secs, out
        return ("PASS" if code == 0 else "FAIL"), r, secs, out

    # record() is only ever called from this thread - the pool returns results,
    # it does not print them - so results and stdout need no lock.
    if pooled:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(run_job, j) for j in pooled]
            for fut in concurrent.futures.as_completed(futures):
                record(*fut.result())
    for job in serial:
        record(*run_job(job))

    # The live lines report completion order (that is the responsiveness the
    # pool exists for); the failure dump and the summary read back in path
    # order, so two runs of the same tree still diff cleanly.
    results.sort(key=lambda x: x[1])

    fails = [x for x in results if x[0] == "FAIL"]
    for status, r, secs, out in fails:
        print("\n--- output: %s ---" % r)
        sys.stdout.flush()
        sys.stdout.buffer.write(out)
        print("\n--- end ---")
    counts = {s: sum(1 for x in results if x[0] == s) for s in ("PASS", "FAIL", "SKIP")}
    inner = [(r, tests_skipped(out)) for status, r, secs, out in results if status == "PASS"]
    inner = [(r, n) for r, n in inner if n]
    print("\n%d suites: %d pass, %d fail, %d skip%s"
          % (len(results), counts["PASS"], counts["FAIL"], counts["SKIP"],
             " (%d tests skipped inside %d passing suites)"
             % (sum(n for _, n in inner), len(inner)) if inner else ""))
    # N3, branch 2 (post-flight): a run where nothing actually executed is not
    # a green run - all-SKIP must refuse, not report success.
    if counts["PASS"] + counts["FAIL"] == 0:
        return refuse("no suite actually executed (all skipped)")
    return 1 if fails else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # runner defect, never a suite verdict
        print("RUNNER ERROR: %s: %s" % (type(e).__name__, e))
        sys.exit(2)
