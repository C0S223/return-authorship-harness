"""Self-check for run_tests.py - the runner's own suite, discovered by its
`scripts/test_*.py` glob.

Run from `scripts/`:
    python test_run_tests.py

Covers the three defects the step-3 delta review proved, so each stays fixed:

  N1  the job handle created for a suite is closed even when
      AssignProcessToJobObject fails (the fallback path). Stubbed to fail, then
      the process handle count is measured across N suites.
  N2  RUN_TESTS_TIMEOUT that is non-positive or unparseable exits 2 (config
      error), never 1 (which reads as "suites failed").
  N3  a root where the python globs find nothing refuses even if the shell
      suite is present, and a run where every suite was skipped refuses too.

An earlier fix added concurrency, so four more:

  C1  RUN_TESTS_WORKERS=1 is one suite at a time and RUN_TESTS_WORKERS=4 is
      not, and the two agree line for line on verdicts and on the summary.
  C2  a RUN_TESTS_WORKERS that is non-positive or unparseable exits 2, never
      1 -- N2's rule, applied to the second knob.
  C3  a suite in SERIAL starts only after every pooled suite has ended.
  C4  a FAIL is still FAIL, named and dumped, in a run that really did
      overlap suites.

Fork 3 of the 2026-09-09 harness drain added one:

  W1  a suite inside a nested git checkout is not discovered, and the real
      suite beside it still is. Over-exclusion is the failure that hides
, so this asserts BOTH directions in one fixture.

An earlier fix added one:

  D1  the docstring's discovery list is the list discover() iterates. Nothing
      read it back, so it named two retired globs and omitted both live ones.

An earlier fix added one:

  P1  a suite whose directory is a package imports that package by name from
      the package's top, with the caller's PYTHONPATH prepended to rather than
      replaced; a suite outside any package sees its env untouched.

Fixture suites timestamp themselves into $MARKS, so overlap is measured from
the suites' own clocks rather than inferred from the runner's wall time.

Fixture roots are temp dirs holding a copy of the runner under `scripts/`, so
ROOT resolves to the fixture and no fixture run touches the real tree. The
runner under test is always this file's sibling, so running a copy of this
suite next to a different run_tests.py checks that one.
"""

import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
RUNNER = os.path.join(HERE, "run_tests.py")

sys.path.insert(0, HERE)
import run_tests  # noqa: E402  (sibling import, by design - see docstring)

TRIVIAL = "print('ok')\n"
SUITES = 10          # suites per handle-count sample
HANDLE_SLACK = 2     # tolerance for unrelated churn; the leak is 1 per suite


def make_root(tmp, py_suites=(), shell_suite=False, bodies=None):
    """Build a fixture root: scripts/run_tests.py plus the named suites.

    `bodies` maps a suite's relpath to its source; anything unnamed gets
    TRIVIAL, so every pre-229 caller is unchanged."""
    os.makedirs(os.path.join(tmp, "scripts"))
    shutil.copyfile(RUNNER, os.path.join(tmp, "scripts", "run_tests.py"))
    for relpath in py_suites:
        dest = os.path.join(tmp, relpath.replace("/", os.sep))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "w") as fh:
            fh.write((bodies or {}).get(relpath, TRIVIAL))
    if shell_suite:
        dest = os.path.join(tmp, "tests", "test_auto_compact.sh")
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "w") as fh:
            fh.write("exit 0\n")
    return os.path.join(tmp, "scripts", "run_tests.py")


def run_runner(runner, **env):
    proc = subprocess.run([sys.executable, runner], capture_output=True,
                          text=True, env={**os.environ, **env})
    return proc.returncode, proc.stdout + proc.stderr


def handle_count():
    # restype matters: GetCurrentProcess returns the pseudo-handle (HANDLE)-1,
    # and ctypes' default c_int truncates it on 64-bit, so the call fails.
    k32 = ctypes.windll.kernel32
    k32.GetCurrentProcess.restype = ctypes.c_void_p
    k32.GetProcessHandleCount.argtypes = [ctypes.c_void_p,
                                          ctypes.POINTER(ctypes.c_ulong)]
    n = ctypes.c_ulong(0)
    assert k32.GetProcessHandleCount(k32.GetCurrentProcess(), ctypes.byref(n)), \
        "GetProcessHandleCount failed"
    return n.value


class NoAssign:
    """kernel32 with AssignProcessToJobObject forced to fail (N1's trigger)."""

    def __init__(self, real):
        self._real = real

    def __getattr__(self, name):
        return getattr(self._real, name)

    def AssignProcessToJobObject(self, *args):
        return 0


def check_n1_no_handle_leak():
    if os.name != "nt":
        print("SKIP n1: job objects are Windows-only")
        return
    with tempfile.TemporaryDirectory() as tmp:
        suite = os.path.join(tmp, "t.py")
        with open(suite, "w") as fh:
            fh.write(TRIVIAL)
        real = run_tests._K32
        run_tests._K32 = NoAssign(real)
        try:
            for _ in range(2):  # warm up: first spawns allocate their own handles
                run_tests.run_one([sys.executable, "t.py"], tmp)
            before = handle_count()
            for _ in range(SUITES):
                code, _secs, _out = run_tests.run_one([sys.executable, "t.py"], tmp)
                assert code == 0, "fixture suite should pass, got %r" % code
            after = handle_count()
        finally:
            run_tests._K32 = real
    delta = after - before
    assert delta <= HANDLE_SLACK, (
        "leaked %d handles across %d suites on the assignment-failure path; "
        "CreateJobObject's handle must be closed before the reference is "
        "dropped (N1)" % (delta, SUITES)
    )
    print("n1 ok: %d suites, handle delta %+d" % (SUITES, delta))


def check_n2_timeout_config():
    with tempfile.TemporaryDirectory() as tmp:
        runner = make_root(tmp, py_suites=["tests/test_ok.py"])
        for bad in ("0", "-1", "abc"):
            code, out = run_runner(runner, RUN_TESTS_TIMEOUT=bad)
            assert code == 2, (
                "RUN_TESTS_TIMEOUT=%r must exit 2 (config error), got %d - exit 1 "
                "is indistinguishable from real suite failures (N2)\n%s"
                % (bad, code, out)
            )
            assert "RUNNER ERROR" in out, "no RUNNER ERROR line for %r:\n%s" % (bad, out)
        code, out = run_runner(runner, RUN_TESTS_TIMEOUT="5")
        assert code == 0, "a sane timeout must still run green, got %d\n%s" % (code, out)
    print("n2 ok: 0/-1/abc exit 2, 5 exits 0")


def check_n3_nothing_ran():
    # shell suite present, python globs empty: the reorg/drift case
    with tempfile.TemporaryDirectory() as tmp:
        runner = make_root(tmp, shell_suite=True)
        code, out = run_runner(runner)
        assert code != 0, (
            "a root where only the shell suite exists must refuse, got exit 0 - "
            "16 python suites can go missing and still read green (N3)\n%s" % out
        )
    # every discovered suite is skipped: nothing actually executed. The live
    # SKIP table may be empty, so the fixture runner gets a one-entry table.
    skipped = "tests/test_fixture_skipped.py"
    with tempfile.TemporaryDirectory() as tmp:
        runner = make_root(tmp, py_suites=[skipped])
        with open(runner) as fh:
            src = fh.read()
        assert "\nSKIP = {}\n" in src, "runner's SKIP table moved; re-derive this check"
        with open(runner, "w") as fh:
            fh.write(src.replace("\nSKIP = {}\n",
                                 "\nSKIP = {%r: 'fixture'}\n" % skipped, 1))
        code, out = run_runner(runner)
        assert code != 0, (
            "an all-SKIP run must refuse, got exit 0 with nothing executed (N3)\n%s" % out
        )
    print("n3 ok: shell-only root and all-SKIP run both refuse")


# Concurrency ------------------------------------------------

def timed(name, sleep=0.0, exit_code=0, text="ok"):
    """A fixture suite that records its own [start, end] into $MARKS."""
    return ("import json, os, sys, time\n"
            "t0 = time.time()\n"
            "time.sleep(%r)\n"
            "with open(os.path.join(os.environ['MARKS'], %r), 'w') as fh:\n"
            "    json.dump([t0, time.time()], fh)\n"
            "print(%r)\n"
            "sys.exit(%d)\n" % (sleep, name + ".json", text, exit_code))


def spans(marks):
    """name -> [start, end], from what the fixture suites wrote."""
    out = {}
    for fn in os.listdir(marks):
        with open(os.path.join(marks, fn)) as fh:
            out[fn[:-5]] = json.load(fh)
    return out


def overlap_count(intervals):
    v = list(intervals)
    return sum(1 for i in range(len(v)) for j in range(i + 1, len(v))
               if v[i][0] < v[j][1] and v[j][0] < v[i][1])


def verdicts(out):
    """(status, name) per suite line -- seconds dropped, they are host noise."""
    return sorted(tuple(ln.split()[:2]) for ln in out.splitlines()
                  if ln[:5] in ("PASS ", "FAIL ", "SKIP "))


def summary(out):
    return next(ln for ln in out.splitlines() if " suites: " in ln)


def pooled_root(tmp, names, sleep, extra=None, bodies_extra=None):
    """Fixture root of `names` pooled suites under projects/app/, plus
    whatever `extra` relpaths the caller wants. Returns (runner, marks)."""
    rels = ["tests/test_%s.py" % n for n in names]
    bodies = {r: timed(n, sleep) for r, n in zip(rels, names)}
    bodies.update(bodies_extra or {})
    runner = make_root(tmp, py_suites=rels + list(extra or ()), bodies=bodies)
    marks = os.path.join(tmp, "marks")
    os.makedirs(marks)
    return runner, marks


def check_c1_workers_knob():
    """1 worker serialises, 4 do not, and both report the same verdicts."""
    seen = {}
    for workers in ("1", "4"):
        with tempfile.TemporaryDirectory() as tmp:
            runner, marks = pooled_root(tmp, ["p1", "p2", "p3", "p4"], 1.0)
            code, out = run_runner(runner, MARKS=marks,
                                   RUN_TESTS_WORKERS=workers)
            assert code == 0, "fixture root must run green, got %d\n%s" % (code, out)
            seen[workers] = (verdicts(out), summary(out),
                             overlap_count(spans(marks).values()), out)
    assert seen["1"][2] == 0, (
        "RUN_TESTS_WORKERS=1 must run one suite at a time; %d overlapping "
        "pair(s) measured from the suites' own clocks (C1)\n%s"
        % (seen["1"][2], seen["1"][3]))
    assert seen["4"][2] > 0, (
        "RUN_TESTS_WORKERS=4 ran four 1s suites with zero overlap, so the "
        "pool is not running them concurrently (C1)\n%s" % seen["4"][3])
    assert seen["1"][0] == seen["4"][0], (
        "verdicts differ between 1 and 4 workers:\n  1: %r\n  4: %r"
        % (seen["1"][0], seen["4"][0]))
    assert seen["1"][1] == seen["4"][1], (
        "summary differs between 1 and 4 workers:\n  1: %s\n  4: %s"
        % (seen["1"][1], seen["4"][1]))
    print("c1 ok: 1 worker 0 overlaps, 4 workers %d, same verdicts and summary"
          % seen["4"][2])


def check_c2_workers_config():
    with tempfile.TemporaryDirectory() as tmp:
        runner = make_root(tmp, py_suites=["tests/test_ok.py"])
        for bad in ("0", "-1", "abc"):
            code, out = run_runner(runner, RUN_TESTS_WORKERS=bad)
            assert code == 2, (
                "RUN_TESTS_WORKERS=%r must exit 2 (config error), got %d - "
                "exit 1 is indistinguishable from real suite failures, and "
                "exit 0 means the knob was ignored entirely (C2)\n%s"
                % (bad, code, out))
            assert "RUNNER ERROR" in out, "no RUNNER ERROR line for %r:\n%s" % (bad, out)
        code, out = run_runner(runner, RUN_TESTS_WORKERS="2")
        assert code == 0, "a sane worker count must still run green, got %d\n%s" % (code, out)
    print("c2 ok: 0/-1/abc exit 2, 2 exits 0")


def check_c5_default_worker_cap():
    # The default is 2 per usable CPU, capped at 8, so a
    # big Windows host does not eat the slow suites' timeout headroom.
    saved_env, saved_cpus = os.environ.pop("RUN_TESTS_WORKERS", None), run_tests.usable_cpus
    try:
        for cpus, want in ((1, 2), (4, 8), (16, 8)):
            run_tests.usable_cpus = lambda: cpus
            got = run_tests.worker_count()
            assert got == want, "usable_cpus()=%d gave %d workers, want %d (C5)" % (cpus, got, want)
    finally:
        run_tests.usable_cpus = saved_cpus
        if saved_env is not None:
            os.environ["RUN_TESTS_WORKERS"] = saved_env
    print("c5 ok: default workers 2/8/8 for 1/4/16 CPUs")


def check_c3_serial_set_runs_last():
    # The live SERIAL table may be empty, so the fixture runner gets a
    # one-entry table; this stays red against a runner that has no SERIAL
    # handling at all, because the fixture suite would then pool with the rest.
    key = "tests/test_serial_fixture.py"
    with tempfile.TemporaryDirectory() as tmp:
        runner, marks = pooled_root(
            tmp, ["p1", "p2", "p3"], 0.6, extra=[key],
            bodies_extra={key: timed("serial_suite", 0.0)})
        with open(runner) as fh:
            src = fh.read()
        assert "\nSERIAL = {}\n" in src, "runner's SERIAL table moved; re-derive this check"
        with open(runner, "w") as fh:
            fh.write(src.replace("\nSERIAL = {}\n",
                                 "\nSERIAL = {%r: 'fixture'}\n" % key, 1))
        code, out = run_runner(runner, MARKS=marks, RUN_TESTS_WORKERS="4")
        assert code == 0, "fixture root must run green, got %d\n%s" % (code, out)
        got = spans(marks)
    start = got.pop("serial_suite")[0]
    last_end = max(end for _s, end in got.values())
    assert start >= last_end, (
        "a suite in SERIAL started %.2fs BEFORE the last pooled suite ended; "
        "%s writes fixed paths and must run after the pool drains (C3)"
        % (last_end - start, key))
    print("c3 ok: serial suite started %.2fs after the pool drained"
          % (start - last_end))


def check_c4_fail_under_concurrency():
    marker = "deliberate-failure-marker-8f21"
    bad = "tests/test_zz_bad.py"
    with tempfile.TemporaryDirectory() as tmp:
        runner, marks = pooled_root(
            tmp, ["p1", "p2", "p3"], 0.8, extra=[bad],
            bodies_extra={bad: timed("bad", 0.8, exit_code=1, text=marker)})
        code, out = run_runner(runner, MARKS=marks, RUN_TESTS_WORKERS="4")
        overlaps = overlap_count(spans(marks).values())
    assert overlaps > 0, (
        "the fixture ran with zero overlap, so this proves nothing about a "
        "FAIL under concurrency (C4)\n%s" % out)
    assert code == 1, "a failing suite under 4 workers must exit 1, got %d\n%s" % (code, out)
    assert ("FAIL", bad) in verdicts(out), (
        "the failing suite is not named on a FAIL line (C4)\n%s" % out)
    assert marker in out, (
        "the failing suite's captured output was not dumped (C4)\n%s" % out)
    print("c4 ok: FAIL named and dumped across %d overlapping pair(s)" % overlaps)


def check_w1_nested_checkout_skipped():
    """A worktree inside the tree is a second copy of every suite, not more suites.

    CLAUDE.md s3 puts worktrees at `worktrees/<n>` and nothing reads that back,
    so three of them sat under projects/app/worktrees/ and the globs returned
    270 suites instead of 72 -- every main-tree failure counted three times. The
    exclusion keys on the nested `.git`, so the fixture makes one.
    """
    with tempfile.TemporaryDirectory() as tmp:
        nested = "tests/worktrees/w/tests/test_copy.py"
        runner = make_root(tmp, py_suites=["tests/test_real.py", nested])
        # a git worktree's marker is a FILE, not a directory - match reality
        with open(os.path.join(tmp, *nested.split("/")[:4], ".git"), "w") as fh:
            fh.write("gitdir: nowhere\n")
        code, out = run_runner(runner)
        assert nested not in out, (
            "suite inside a nested checkout was discovered; every suite in the "
            "tree gets counted once per misplaced worktree (W1)\n%s" % out)
        assert "tests/test_real.py" in out, (
            "the real suite beside the nested checkout went missing - "
            "over-exclusion is an earlier fix's class, worse than the bug\n%s" % out)
        assert code == 0, "fixture run should be green, got %d\n%s" % (code, out)
    print("w1 ok: nested checkout skipped, real sibling still discovered")


def check_d1_docstring_matches_discovery():
    """The runner's docstring lists the globs discover() actually uses.

    Nothing read that list back, so it survived an earlier fix widening
    `projects/app/` to `projects/**` and an earlier fix adding `.claude/skills/**`
    -- naming two globs that had not existed for weeks and omitting both live
    ones. CLAUDE.md s6: a write lands only when something reads it back. This
    is that reader, and it keys on the same PATTERNS list discover() iterates,
    so the two cannot drift without this going red.
    """
    doc = run_tests.__doc__
    marker = "Discovers, from the repo root"
    assert marker in doc, (
        "run_tests.py lost the '%s' block; D1 has nothing to compare and the "
        "list is unread again" % marker)
    block = doc.split(marker, 1)[1].split("\n\n", 1)[0]
    listed = [ln.strip().split()[0] for ln in block.splitlines()[1:] if ln.strip()]
    globs = [x for x in listed if not x.endswith(".sh")]
    shell = [x for x in listed if x.endswith(".sh")]
    assert globs == list(run_tests.PATTERNS), (
        "the docstring lists %s but discover() iterates %s -- one moved "
        "without the other, which is exactly an earlier fix (D1)"
        % (globs, list(run_tests.PATTERNS)))
    assert len(shell) == 1, (
        "expected exactly one shell suite in the docstring block, got %s" % shell)
    with open(RUNNER) as fh:
        src = fh.read()
    parts = ", ".join('"%s"' % part for part in shell[0].split("/"))
    assert parts in src, (
        "the docstring names shell suite %s, but the runner joins no such path "
        "(looked for %s)" % (shell[0], parts))
    print("d1 ok: %d glob(s) and 1 shell suite listed, all matching the code"
          % len(globs))


def check_p1_package_suite_import_root():
    """A suite inside a package imports that package by name, from its top.

    BotV3's seven suites do `import botV3.x`, and each ran with cwd =
    the package itself, so nothing on sys.path ever resolved the name -- 7 FAIL
    on every run since they landed. The fixture nests two packages so that the
    one-level fix (parent of cwd) is a mutant this catches: `import
    pkg.sub.helper` needs pkg's PARENT on the path. The same suite imports a
    module from a pre-existing PYTHONPATH entry, so a runner that replaces the
    variable instead of prepending to it fails too. A sibling suite outside any
    package asserts its PYTHONPATH arrived untouched.
    """
    pkg = "tests/pkg/sub/test_in_pkg.py"
    plain = "tests/plain/test_plain.py"
    bodies = {
        pkg: "import pkg.sub.helper, extra_mod\nprint('ok')\n",
        plain: ("import os\n"
                "got, want = os.environ.get('PYTHONPATH'), os.environ['EXTRA']\n"
                "assert got == want, 'PYTHONPATH changed outside a package: %r' % got\n"
                "print('ok')\n"),
    }
    with tempfile.TemporaryDirectory() as tmp:
        runner = make_root(tmp, py_suites=[pkg, plain], bodies=bodies)
        for rel in ("tests/pkg/__init__.py", "tests/pkg/sub/__init__.py",
                    "tests/pkg/sub/helper.py", "extra/extra_mod.py"):
            dest = os.path.join(tmp, *rel.split("/"))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            open(dest, "w").close()
        sub = os.path.join(tmp, "tests", "pkg", "sub")
        got = run_tests.import_root(sub)
        assert got == os.path.join(tmp, "tests"), (
            "import_root must walk to the package's TOP and return its parent; "
            "got %r for %r (P1)" % (got, sub))
        assert run_tests.import_root(os.path.join(tmp, "tests")) is None, (
            "a directory with no __init__.py is not a package (P1)")
        extra = os.path.join(tmp, "extra")
        code, out = run_runner(runner, PYTHONPATH=extra, EXTRA=extra)
    assert code == 0, (
        "a suite inside a nested package must import it by name from the "
        "package's top, with the caller's PYTHONPATH kept (P1)\n%s" % out)
    print("p1 ok: nested package imported by name, PYTHONPATH prepended not replaced")


def check_s1_inner_skips_are_named():
    """A passing suite whose unittest run skipped tests is still PASS, but the
    count shows on its line and in the summary (finish-run probe P2)."""
    with tempfile.TemporaryDirectory() as tmp:
        runner, marks = pooled_root(tmp, ["s1", "s2"], 0.0, bodies_extra={
            "tests/test_s1.py": timed("s1", text="OK (skipped=3)")})
        code, out = run_runner(runner, MARKS=marks)
    assert code == 0, "skips inside a passing suite are not a failure\n%s" % out
    line = next(ln for ln in out.splitlines() if "tests/test_s1.py" in ln)
    assert line.startswith("PASS ") and line.endswith("(3 tests skipped)"), line
    assert summary(out).endswith(
        "0 skip (3 tests skipped inside 1 passing suites)"), summary(out)
    print("s1 ok: unittest skips inside a passing suite are counted and named")


def main():
    check_s1_inner_skips_are_named()
    check_n1_no_handle_leak()
    check_n2_timeout_config()
    check_n3_nothing_ran()
    check_c1_workers_knob()
    check_c2_workers_config()
    check_c5_default_worker_cap()
    check_c3_serial_set_runs_last()
    check_c4_fail_under_concurrency()
    check_w1_nested_checkout_skipped()
    check_d1_docstring_matches_discovery()
    check_p1_package_suite_import_root()
    print("PASS")


if __name__ == "__main__":
    main()
