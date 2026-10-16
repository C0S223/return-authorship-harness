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
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BATTERY = os.path.join(ROOT, "tests", "mutate_auto_compact.sh")

# macOS's BSD sed has no GNU `sed -i 'x' f` and no `addr,+N`, and the battery
# used both, so it failed there while CI stayed green (board 6177). Where this
# host's sed is GNU sed, a second run puts a sed first on PATH that refuses
# in-place editing and runs GNU sed with --posix, which rejects GNU-only syntax.
# Elsewhere (macOS) the host's own sed is the check, and the first run made it.
#
# The shim reads options as GNU getopt does. `-i` is refused in any short-option
# cluster (-Ei, -ni, -i.bak, -si) and anywhere before `--` (getopt permutes, so
# `sed 's/x/y/' -i f` edits in place too); `--in-place` with or without =SUFFIX,
# and any abbreviation of it (no other sed long option starts with `--i`).
# -e, -f and -l take an argument: the rest of the cluster, or the next word.
# SE r1 F2: the first shim matched only a word starting with -i, and passed -Ei.
STRICT_SED = r"""#!/bin/sh
refuse() { echo "strict sed: in-place editing is not portable: $1" >&2; exit 2; }
skip=""
for a in "$@"; do
  if [ -n "$skip" ]; then skip=""; continue; fi
  case "$a" in
    --) break ;;
    --i*) refuse "$a" ;;
    --*) ;;
    -?*)
      rest="${a#-}"
      while [ -n "$rest" ]; do
        c="${rest%"${rest#?}"}"
        rest="${rest#?}"
        case "$c" in
          i) refuse "$a" ;;
          e|f|l) [ -n "$rest" ] || skip=1; break ;;
        esac
      done ;;
  esac
done
exec "@SED@" --posix "$@"
"""

# Argument lists placed before the file. Each IN_PLACE one must be refused with
# the file unchanged. Each NOT_IN_PLACE one must reach GNU sed (no refusal) and
# leave the file unchanged; sed may still reject a script such as `i`.
IN_PLACE = [
    ["-i", "s/x/y/"], ["-Ei", "s/x/y/"], ["-ni", "p"], ["-i.bak", "s/x/y/"],
    ["-si", "s/x/y/"], ["-Ei.bak", "s/x/y/"], ["-E", "-i", "s/x/y/"],
    ["-n", "-i", "p"], ["--in-place", "s/x/y/"], ["--in-place=.bak", "s/x/y/"],
    ["--in-pl", "s/x/y/"], ["s/x/y/", "-i"], ["-e", "s/x/y/", "-i"],
]
NOT_IN_PLACE = [
    ["-n", "p"], ["-E", "s/q/y/"], ["-e", "s/i/y/"], ["-ei"], ["-l", "5", "p"],
    ["--posix", "p"], ["-ne", "p"], ["-e", "-i"],
]

PLANT_OLD = """run "S1 trap in check.sh"   edit "/^trap 'exit 0' ERR$/d" "$M"/check.sh"""
PLANT_NEW = """run "S1 trap in check.sh"   sed -Ei "/^trap 'exit 0' ERR$/d" "$M"/check.sh"""


def battery(label, path=None, script=BATTERY, cwd=ROOT, check=True):
    env = dict(os.environ, MUTATE_ANCHORS_ONLY="1")
    if path:
        env["PATH"] = path + os.pathsep + env.get("PATH", "")
    if script != BATTERY:
        env["AC_SRC"] = os.path.join(ROOT, ".claude", "hooks", "auto-compact")
    proc = subprocess.run(
        ["bash", script],
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    out = proc.stdout.decode("utf-8", "replace")
    if not check:
        return proc.returncode, out
    print(out, end="")
    if proc.returncode != 0:
        sys.exit("FAIL (%s): a mutation anchor missed -- the battery is disarmed "
                 "(MISS lines above name which). rc=%d" % (label, proc.returncode))
    # A battery with no mutations left in it exits 0 and would read as green here,
    # which is run_tests.py's own zero-discovery refusal (N3) one level down.
    checked = sum(1 for ln in out.splitlines() if ln.startswith("anchor "))
    if checked == 0:
        sys.exit("FAIL (%s): the battery checked zero anchors -- it exited 0 "
                 "without testing anything" % label)
    print("PASS %d mutation anchors still match (%s)" % (checked, label))
    return proc.returncode, out


def check_shim(shim, work):
    """The shim refuses every in-place spelling and passes the others."""
    f = os.path.join(work, "f")
    bad = []
    for refused, cases in ((True, IN_PLACE), (False, NOT_IN_PLACE)):
        for args in cases:
            with open(f, "w", encoding="utf-8", newline="\n") as fh:
                fh.write("x\n")
            r = subprocess.run([os.path.join(shim, "sed")] + args + [f],
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            was_refused = r.returncode == 2 and b"strict sed:" in r.stderr
            with open(f, encoding="utf-8") as fh:
                changed = fh.read() != "x\n"
            if changed or was_refused != refused:
                bad.append("sed %s: rc=%d, file changed=%s, want %s"
                           % (" ".join(args), r.returncode, changed,
                              "refused" if refused else "not refused"))
    if bad:
        sys.exit("FAIL (strict sed shim):\n  " + "\n  ".join(bad))
    print("PASS strict sed shim refuses %d in-place spellings and runs %d others"
          % (len(IN_PLACE), len(NOT_IN_PLACE)))


def check_planted_battery(shim, work):
    """A copy of the battery with `sed -Ei` planted fails the POSIX-only run."""
    with open(BATTERY, encoding="utf-8") as fh:
        src = fh.read()
    if src.count(PLANT_OLD) != 1:
        sys.exit("FAIL (planted battery): the line to plant over is gone; update PLANT_OLD")
    os.makedirs(os.path.join(work, "tests"))
    planted = os.path.join(work, "tests", "mutate_auto_compact.sh")
    with open(planted, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(src.replace(PLANT_OLD, PLANT_NEW))
    rc, out = battery("planted", shim, script=planted, cwd=work, check=False)
    if rc == 0 or "MISS  S1 trap in check.sh" not in out:
        sys.exit("FAIL (planted battery): `sed -Ei` passed the POSIX-only run "
                 "(rc=%d):\n%s" % (rc, out))
    print("PASS a planted `sed -Ei` fails the POSIX-only run")


battery("host sed")
real_sed = shutil.which("sed")
gnu = real_sed and subprocess.run([real_sed, "--posix", "-n", "p"], input=b"",
                                  stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL).returncode == 0
if gnu:
    shim = tempfile.mkdtemp(prefix="strict-sed-")
    work = tempfile.mkdtemp(prefix="strict-sed-work-")
    try:
        with open(os.path.join(shim, "sed"), "w", encoding="utf-8", newline="\n") as f:
            f.write(STRICT_SED.replace("@SED@", real_sed))
        os.chmod(os.path.join(shim, "sed"), 0o755)
        check_shim(shim, work)
        check_planted_battery(shim, work)
        battery("POSIX-only sed", shim)
    finally:
        shutil.rmtree(shim, ignore_errors=True)
        shutil.rmtree(work, ignore_errors=True)
else:
    print("no GNU sed here: the host sed run above is the portability check")
