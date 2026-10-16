#!/usr/bin/env python
"""The mutation battery's text anchors still bite.

Nothing in the tree ran mutate_auto_compact.sh, so a
text-coupled edit to check.sh or resume.sh silently stopped its sed anchors
from matching and disarmed the guards invisibly.

This suite closes the discovery half. It is discovered by run_tests.py's own
projects/**/test*.py glob, so scripts/run_tests.py needs no edit -- which
matters, because that file is a policy path a lane cannot mutate.

It runs the battery in MUTATE_ANCHORS_ONLY mode: every mutation is applied to
the scratch copy and checked for a real change, but the auto-compact suite is
not run. That is deliberate. The full battery runs the ~38s suite once per
mutation (~10 minutes), well past the runner's 120s per-suite timeout, and the
half that goes stale on its own is the anchors -- whether a removed guard still
turns the suite red changes only when the suite changes. Run the full battery
(`bash projects/app/mutate_auto_compact.sh`) when the suite or the guards
move; it now exits non-zero on a missed anchor or a surviving mutant.

If bash is absent the subprocess raises and this suite FAILs by name. There is
deliberately no skip path: a battery guard that returns 0 when it did not run
is the exact defect an earlier fix is about.
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BATTERY = os.path.join(ROOT, "tests", "mutate_auto_compact.sh")

proc = subprocess.run(
    ["bash", BATTERY],
    cwd=ROOT,
    env=dict(os.environ, MUTATE_ANCHORS_ONLY="1"),
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
)
out = proc.stdout.decode("utf-8", "replace")
print(out, end="")
if proc.returncode != 0:
    sys.exit("FAIL: a mutation anchor missed -- the battery is disarmed "
             "(MISS lines above name which). rc=%d" % proc.returncode)
# A battery with no mutations left in it exits 0 and would read as green here,
# which is run_tests.py's own zero-discovery refusal (N3) one level down.
checked = sum(1 for ln in out.splitlines() if ln.startswith("anchor "))
if checked == 0:
    sys.exit("FAIL: the battery checked zero anchors -- it exited 0 without "
             "testing anything")
print("PASS %d mutation anchors still match" % checked)
