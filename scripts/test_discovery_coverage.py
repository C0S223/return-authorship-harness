"""Earlier fixes: every tracked test file, and every test inside it, must run.

The runner refuses only on TOTAL discovery silence; losing a single directory
trips nothing. That is exactly how an earlier fix survived for the whole life of
projects/harness/ -- a suite that never runs is indistinguishable from one that
passes, and the runner's own contract test passed both before and after the
repair, so it could not have caught it. This is the guard that was missing.

Three families. The first two are the runner's two mechanisms, either of which
can lose a whole file; the third is the same failure one level down, inside a
file the runner does reach:

  *.py  -- matched by GLOB. Compared against discover() itself, never against a
           copy of its globs; a copy would drift exactly like the thing it
           guards.
  *.sh  -- matched by LITERAL PATH (run_tests.py builds one hardcoded path and
           runs it if it exists). So a second shell suite is invisible no matter
           where it sits. Checked by asking whether the runner's source mentions
           the file at all, which is drift-proof in the same way: it tests the
           real runner, not a restatement of what it is believed to do.
  main  -- a suite whose __main__ block HAND-LISTS its own test functions runs
           only the ones someone remembered. Measured 2026-08-30:
           test_launch.py listed 11 of its 12, the suite printed `ok`, and a
           mutant deleting the code under test survived. This assertion fails on
           the SHAPE rather than on missing coverage, so the next hand-listed
           runner cannot appear rather than being detected after it bites.

Scope is TRACKED files (git ls-files), deliberately: untracked test files are
work in progress and gitignored residue, neither of which should fail the tree.

Fail-closed: if git cannot be run or lists nothing, that is a loud failure, not
a skip. A guard that goes quiet on error is an earlier fix all over again.
"""
import importlib.util
import os
import re
import subprocess
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RUNNER = os.path.join(HERE, "run_tests.py")

# ponytail: importlib rather than sys.path + import -- it pins the sibling by
# absolute path, so nothing on sys.path can shadow it, and it gives the mutation
# probe a single string to retarget. run_tests.py's module body is defs and
# constants only, so importing it executes no work.
spec = importlib.util.spec_from_file_location("run_tests", RUNNER)
run_tests = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run_tests)

# Tracked files whose name looks like a suite but which are deliberately not one.
# EMPTY TODAY, and that is the point: it exists so that adding a helper named
# test*.py is a decision someone records here, rather than a guard failure they
# silence by weakening the filter. Add the repo-relative posix path plus a reason.
NOT_SUITES = frozenset()

MAIN_GUARD = 'if __name__ == "__main__":'
# A bare `test_name()` call on its own line. Deliberately narrow: it matches the
# hand-list shape and not `unittest.main()`, not a loop calling `_fn()`, and not
# a helper invoked with arguments.
BARE_TEST_CALL = re.compile(r"^\s+(test_\w+)\(\)\s*$", re.M)


def tracked_test_files(suffix):
    out = subprocess.run(["git", "-C", ROOT, "ls-files"],
                         capture_output=True, text=True)
    if out.returncode != 0:
        raise AssertionError("git ls-files failed: " + out.stderr)
    return [p for p in out.stdout.splitlines()
            if os.path.basename(p).startswith("test") and p.endswith(suffix)
            and p not in NOT_SUITES]


class TestDiscoveryCoverage(unittest.TestCase):
    def test_every_tracked_python_suite_is_discovered(self):
        tracked = tracked_test_files(".py")
        # A repo with zero tracked test files means this guard is measuring the
        # wrong tree, not that coverage is perfect.
        self.assertGreater(len(tracked), 0, "git ls-files returned no .py test files")

        discovered = {run_tests.rel(p) for p in run_tests.discover()}
        missed = sorted(t for t in tracked if t not in discovered)
        self.assertEqual(missed, [], (
            "tracked test file(s) invisible to run_tests.discover(); these suites "
            "will never run, and a suite that never runs is indistinguishable "
            "from one that passes: %r" % missed))

    def test_every_tracked_shell_suite_is_wired(self):
        """Shell suites are matched by literal path, so a new one is silently dropped.

        The runner has no glob for .sh: it constructs one hardcoded path and runs
        that file if it exists. Adding projects/<area>/test_x.sh therefore yields
        a tracked suite nothing executes -- 's class, in the one non-.py
        category the runner already supports. Asking whether the runner's source
        names the file catches that without restating the runner's logic here.
        """
        tracked = tracked_test_files(".sh")
        if not tracked:
            return  # no shell suites is a legitimate state; .py coverage is asserted above
        with open(RUNNER, encoding="utf-8") as f:
            src = f.read()
        unwired = sorted(t for t in tracked if os.path.basename(t) not in src)
        self.assertEqual(unwired, [], (
            "tracked shell suite(s) the runner never references, so nothing runs "
            "them: %r. run_tests.py matches .sh by literal path, not by pattern -- "
            "wire each one explicitly." % unwired))

    def test_no_suite_hand_lists_its_own_tests(self):
        """A __main__ block that enumerates its tests runs only those.

        Reaching a file is not running what is in it. Two suites here drove their
        own __main__ by hand; one had silently dropped a test, and the suite still
        printed `ok` while a mutant that deleted the code under test survived. The
        working idiom already in this tree is auto-discovery -- unittest.main(), or
        a sorted-globals loop -- so this asserts the shape rather than counting
        coverage: there is no list to fall out of if there is no list.

        Narrow by construction. The pattern matches a bare `test_name()` on its own
        line inside the __main__ block only, so unittest.main(), a discovery loop
        calling `_fn()`, and any helper taking arguments all pass untouched.
        """
        offenders = []
        for rel in tracked_test_files(".py"):
            with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
                head, sep, block = f.read().partition(MAIN_GUARD)
            if not sep:
                continue  # imported-only helper, or a suite the runner drives
            named = BARE_TEST_CALL.findall(block)
            if named:
                offenders.append((rel, sorted(named)))
        self.assertEqual(sorted(offenders), [], (
            "suite(s) hand-list their own tests in __main__, so any test not in "
            "the list never runs and the suite still reports success: "
            "%r. Replace the list with auto-discovery -- unittest.main(), or "
            "`for _n, _f in sorted(dict(globals()).items()): ...`."
            % sorted(offenders)))


if __name__ == "__main__":
    unittest.main()
