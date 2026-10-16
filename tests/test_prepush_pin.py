"""The docstring pin in scripts/test_prepush_strict.py, mutated.

Companion to that suite, which is a policy path; these cases were written by a
lane that could not edit it. PREPUSH_SUITE points at a candidate
test_prepush_strict.py (the BROWSER_LOOPBACK_HOOK / POLICY_MUTATE_HOOK
convention); with it unset the live suite runs and M1/M2 below are expected to
SURVIVE, which is the defect itself.

The unit under test is a test, so the check is mutation, not a fixture: a pin
is only worth what it catches. Each mutation is applied to a throwaway copy of
scripts/, never to the tree.

M1 (F-1) deletes the docstring line describing exit 1. The bare-token pin
survives it because `exit 1` also occurs in the exit-2 paragraph, which quotes
the runner's warning that a config error must never wear exit 1.

M2 (F-2) adds a third strict exit code to main() with no docstring line and no
driving case. The observation-based pin cannot see it at all: it records codes
that some existing case returned, so a branch with no test contributes nothing.

M3 and M4 are the review's finding against the FIRST fix, not against the live
pin: a source scan that reads `^\\s+return (\\d+)` sees neither `return <name>`
nor `sys.exit(N)`, and the emptiness guard does not fire because the two real
literals keep the set non-empty. Both survived the first candidate. M4 is now
read as a literal; M3 cannot be resolved statically and is reported as an
unreadable exit instead, which is a red either way.

M5 is the mirror image and the reason a wider scan is not automatically a
better one. The first fix kept EVERYTHING after `def main(`, so a helper
defined below main() -- layout, not an invariant -- was pinned as a code main()
returns. M5 is green against the live pin and against this candidate, and was
RED against the first candidate; it exists so the fix for M2/M3/M4 cannot be
bought with a false red.

Not mutated: F-2's ordering half (the same new branch WITH a driving case,
placed after the pin loop). It has the same root as M2 -- reading observations
rather than the source -- and the source scan kills it because the scan reads
main()'s body wherever the cases sit. Note that this is a claim about the
CASES' position, not about the file: the scan is positional with respect to
main() itself, which is what M5 pins.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUITE = os.environ.get("PREPUSH_SUITE")

M1_LINE = "  exit 1 -- a check RAN and FAILED.\n"
M2_ANCHOR = """    if strict and failing:
"""
M2_BRANCH = """    if strict and os.environ.get("PIN_MUTATION_M2"):
        print("\\n=== STRICT: mutation branch, exit 3\\n")
        return 3
    if strict and failing:
"""
M3_BRANCH = """    if strict and os.environ.get("PIN_MUTATION_M3"):
        _rc = 3
        print("\\n=== STRICT: mutation branch, exit 3 via a name\\n")
        return _rc
    if strict and failing:
"""
M4_BRANCH = """    if strict and os.environ.get("PIN_MUTATION_M4"):
        print("\\n=== STRICT: mutation branch, exit 4\\n")
        sys.exit(4)
    if strict and failing:
"""
M5_HELPER = '''

def _helper_added_after_main():
    """A helper below main(). Its return is not an exit code of main()."""
    return 7
'''

_BRANCHES = {"M2": M2_BRANCH, "M3": M3_BRANCH, "M4": M4_BRANCH}


def _stage(mutation):
    """A throwaway copy of scripts/ with one mutation applied."""
    tmp = Path(tempfile.mkdtemp(prefix="prepush-pin-"))
    dst = tmp / "scripts"
    shutil.copytree(ROOT / "scripts", dst)
    if SUITE:
        shutil.copyfile(SUITE, dst / "test_prepush_strict.py")
    check = dst / "prepush_check.py"
    src = check.read_text(encoding="utf-8")

    if mutation == "M1":
        assert M1_LINE in src, "docstring line describing exit 1 not found"
        src = src.replace(M1_LINE, "", 1)
        # The pin must still fail for the RIGHT reason: `exit 1` survives.
        assert "exit 1" in src, "M1 removed every occurrence -- mutation is not the one 244 names"
    elif mutation in _BRANCHES:
        assert M2_ANCHOR in src, "strict failing branch not found"
        src = src.replace(M2_ANCHOR, _BRANCHES[mutation], 1)
    elif mutation == "M5":
        assert 'if __name__ == "__main__":' in src, "__main__ block not found"
        src = src.rstrip("\n") + "\n" + M5_HELPER
    else:
        raise AssertionError(mutation)

    check.write_text(src, encoding="utf-8", newline="\n")
    return tmp, dst


def _run(dst):
    r = subprocess.run([sys.executable, "test_prepush_strict.py"],
                       cwd=str(dst), capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def _check(mutation):
    tmp, dst = _stage(mutation)
    try:
        rc, out = _run(dst)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return rc, out


def test_m1_missing_exit1_description_is_caught():
    rc, out = _check("M1")
    assert rc != 0, (
        "M1 SURVIVED: the line describing `exit 1` was deleted and the suite "
        "stayed green, because the pin tests token presence rather than a "
        "described line.\n" + out[-800:])
    assert "exit 1 -- <description>" in out, out[-800:]


def test_m2_undescribed_new_code_is_caught():
    rc, out = _check("M2")
    assert rc != 0, (
        "M2 SURVIVED: a third strict exit code was added to main() with no "
        "docstring line, and the suite stayed green, because the pin reads "
        "codes it OBSERVED rather than codes main() can return (an earlier fix "
        "F-2).\n" + out[-800:])
    assert "--strict can return 3" in out, out[-800:]


def test_m3_code_returned_through_a_name_is_caught():
    rc, out = _check("M3")
    assert rc != 0, (
        "M3 SURVIVED: main() returns a new code through a local name, and the "
        "suite stayed green. A scan for `return <literal>` cannot see it and "
        "the emptiness guard does not fire, because the two real literals keep "
        "the set non-empty (review of the first 244 fix).\n" + out[-800:])
    assert "cannot read" in out, out[-800:]


def test_m4_code_reached_through_sys_exit_is_caught():
    rc, out = _check("M4")
    assert rc != 0, (
        "M4 SURVIVED: main() leaves through sys.exit(4) with no docstring "
        "line, and the suite stayed green -- same blind spot as M3, different "
        "spelling (review of the first 244 fix).\n" + out[-800:])
    assert "--strict can return 4" in out, out[-800:]


def test_m5_helper_below_main_is_not_a_false_red():
    # The mirror of M3/M4. Widening the scan must not be paid for with a false
    # positive: a `return <int>` in a function defined BELOW main() is not an
    # exit code of main(), and main() being the last def in prepush_check.py is
    # layout rather than an invariant.
    rc, out = _check("M5")
    assert rc == 0, (
        "M5 FALSE RED: a helper defined below main() returning 7 made the pin "
        "demand `exit 7 -- <description>` from the docstring. The scan keeps "
        "everything after `def main(` instead of main()'s own body (an earlier fix "
        "F-3).\n" + out[-800:])


def test_unmutated_tree_is_green():
    # The pin must not cost a false positive: pristine scripts/ stays green.
    tmp = Path(tempfile.mkdtemp(prefix="prepush-pin-"))
    try:
        dst = tmp / "scripts"
        shutil.copytree(ROOT / "scripts", dst)
        if SUITE:
            shutil.copyfile(SUITE, dst / "test_prepush_strict.py")
        rc, out = _run(dst)
        assert rc == 0, "unmutated suite is not green:\n" + out[-800:]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    bad = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_"):
            continue
        try:
            fn()
            print("ok", name)
        except AssertionError as e:
            bad += 1
            print("FAIL", name, "--", str(e).split("\n")[0])
    print("%s: %d failure(s)" % ("FAIL" if bad else "ok", bad))
    sys.exit(1 if bad else 0)
