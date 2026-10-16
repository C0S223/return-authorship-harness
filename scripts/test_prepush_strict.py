"""`--strict` must let a MACHINE produce a red, without changing the
default report at all.

Two things need proving, and the second is the one that matters:
  1. strict returns nonzero when a check fails;
  2. the DEFAULT still returns zero on the same input -- because this script's
     job is a reviewer's report, and a red test committed ahead of its fix is
     correct here. If strict ever became the default, that design is destroyed.

`main()` is driven directly with `git` stubbed, because the real thing needs an
upstream and an unpushed range. A live run exits at "nothing unpushed" long
before the strict branch, which is exactly how a green-but-hollow proof of this
flag would look.
"""

import importlib.util
import io
import os
import re
import shutil
import sys
import tempfile
import subprocess
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load():
    spec = importlib.util.spec_from_file_location(
        "prepush", str(HERE / "prepush_check.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_RET_RE = re.compile(r"^\s+(?:return\b\s*(.*)|sys\.exit\(\s*(.*?)\s*\)\s*)$")


def _main_body(src):
    """The lines of `main()`'s own body, and nothing else.

    This scan IS positional, and the earlier claim that "a scan
    has no position in the file" was wrong. Splitting on `def main(` and keeping
    the tail keeps every function defined BELOW main() as well as the `__main__`
    block, so `def _helper(): return 7` added after main() was pinned as a code
    main() returns -- a false red, measured. main() being the last definition in
    prepush_check.py is layout, not an invariant, so the scan stops at the next
    top-level statement instead of relying on it.
    """
    out, state = [], 0
    for line in src.splitlines():
        if state == 0:
            if line.startswith("def main("):
                state = 2 if line.rstrip().endswith(":") else 1
            continue
        if state == 1:                       # still inside a wrapped signature
            if line.rstrip().endswith(":"):
                state = 2
            continue
        if line.strip() and not line[:1].isspace():
            break                            # next top-level statement
        out.append(line)
    return out


def _declared_strict_codes():
    """Codes `main()` can hand back, and the exits this scan could not read.

    Source, not observation: the recorder below only sees a code
    when some existing case drives that branch, so a strict branch added with
    no test contributed nothing to the pin.

    A literal after `return` or inside `sys.exit()` resolves. `return <name>`
    and `sys.exit(<expr>)` do not, and they are reported rather than passed
    over: an exit the pin cannot see is the same silent green this row exists
    to close, and two such mutations survived the first fix.

    Returns (nonzero codes, unreadable source lines).
    """
    src = (HERE / "prepush_check.py").read_text(encoding="utf-8")
    codes, opaque = set(), []
    for line in _main_body(src):
        m = _RET_RE.match(line)
        if not m:
            continue
        arg = (m.group(1) if m.group(1) is not None else m.group(2)).strip()
        if arg == "" or arg.isdigit():
            codes.add(int(arg or "0"))
        else:
            opaque.append(line.strip())
    return codes - {0}, opaque


_TMPDIRS = []
# Every distinct NONZERO code --strict actually returned during this run. The
# docstring pin at the bottom reads this rather than a literal list, so a code
# added to main() without a docstring line goes red on its own.
_STRICT_RCS = set()


def drive(strict, exit_code, relpath="sub/test_stub.py", body=None,
          runner_path=None):
    """Run main() over a fake range holding one check that exits `exit_code`.

    `relpath` and `body` exist for an earlier fix: the check's repo-relative path is
    what run_tests.SKIP and run_tests.ARGS are keyed on, so proving prepush
    honours either one needs a fixture check sitting at a real key. Both
    default to the pre-229 fixture, so every existing case is unchanged.

    `runner_path` is an earlier fix: it reaches prepush's own loader seam, so the
    runner-load-failure path runs for real -- banner and all -- instead of
    being stubbed away by the test that claims to cover it."""
    mod = load()
    # Tracked and removed at exit rather than leaked: this runs four times per
    # suite, and the suite runs on every run_tests.py invocation.
    tmp = Path(tempfile.mkdtemp())
    _TMPDIRS.append(tmp)
    target = tmp / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body if body is not None
                      else "import sys; sys.exit(%d)\n" % exit_code,
                      encoding="utf-8")

    mod.ROOT = tmp
    responses = {
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"):
            "origin/master",
        ("log", "--oneline", "origin/master..HEAD"): "abc1234 stub commit",
        ("diff", "--name-only", "origin/master..HEAD"): relpath,
        ("status", "--porcelain"): "",
        ("rev-parse", "--abbrev-ref", "HEAD"): "stub-branch",
    }
    def stub_git(*a):
        # RAISES on anything unlisted rather than answering "". A permissive
        # stub means a git call added to main() later gets silently answered
        # with empty string, and this suite keeps passing while stubbing
        # nothing -- the test would go on "proving" a code path it no longer
        # covers. Failing loudly is what makes the stub honest as main() grows.
        if tuple(a) not in responses:
            raise AssertionError(
                "main() called an unstubbed git command: %r -- add it to "
                "`responses` and check whether this test still covers what it "
                "claims" % (a,))
        return responses[tuple(a)]

    mod.git = stub_git
    mod.policy_flagged = lambda files, hook_path=None: []

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = mod.main(strict, runner_path)
    if strict and rc:
        _STRICT_RCS.add(rc)
    return rc, buf.getvalue()


def main():
    failures = []

    # The load-bearing pair: same failing input, two exit codes.
    rc, out = drive(strict=True, exit_code=1)
    if rc != 1:
        failures.append("strict + failing check returned %r, want 1" % rc)
    if "STRICT" not in out:
        failures.append("strict mode did not say so in its output")

    rc, default_out = drive(strict=False, exit_code=1)
    if rc != 0:
        failures.append(
            "DEFAULT + failing check returned %r, want 0 -- strict is supposed "
            "to be additive, and this is the regression that would mean it is "
            "not" % rc)

    # Strict must be inert when nothing failed.
    rc, _ = drive(strict=True, exit_code=0)
    if rc != 0:
        failures.append("strict + passing check returned %r, want 0" % rc)

    # The report itself must not change. Everything the default prints has to
    # survive verbatim into strict's output; strict only appends.
    #
    # The FULL body, not a prefix of it. This assertion first read
    # `default_out.rstrip("\n")[:200]`, which proved 200 characters of a
    # 559-character report -- 36% of what its own comment claimed -- so a
    # strict-conditional line inserted anywhere past offset 200 left it green.
    # Found by a non-author reviewer who built exactly that mutation. Seventh
    # such defect in this tree's suites, and the first inside a test written
    # expressly to avoid them: truncating a reference string is how an
    # assertion silently narrows to nothing.
    _, strict_out = drive(strict=True, exit_code=1)
    if not strict_out.startswith(default_out.rstrip("\n")):
        failures.append("strict altered the report body instead of appending")

    # The docstring is read as authoritative by agents deciding what a nonzero
    # exit means, and it flatly denied that the exit code ever reflects check
    # outcomes. Under --strict it does. This tree has already shipped a defect
    # from a stale documentation copy trusted as current (the roster's
    # three-copies incident), so the doc claim is pinned rather than hoped for.
    doc = load().__doc__ or ""
    if "--strict" not in doc:
        failures.append("module docstring's exit-code contract does not name "
                        "the --strict exception, and is false without it")

    # A flag that fails open on a typo is worse than no flag: automation wired
    # with `--Strict` would believe it has a gate and have none.
    #
    # Assert on the MESSAGE, not the exit code. Checking `returncode != 0` was
    # hollow -- my own mutation probe caught it: this runs the script from a
    # directory that is not a git repo, so it exits 1 at "no upstream" whether
    # the flag was rejected or silently ignored, and the assertion passed in
    # both directions for a reason having nothing to do with flag parsing.
    for bad in ("--Strict", "-strict", "--strict=1", "--stict"):
        r = subprocess.run([sys.executable, str(HERE / "prepush_check.py"), bad],
                           capture_output=True, text=True)
        if "unrecognised argument" not in (r.stdout + r.stderr):
            failures.append("%r was not rejected by name -- a misspelled flag "
                            "must be a hard error, not a silent strict=False"
                            % bad)

    # The checks run through scripts/run_tests.py ---------
    #
    # Both of these were red before 229, and for the same root cause: this
    # script had no charter and no arg table, so it ran every check bare.

    # The SKIP charter. A parked suite is red by design; running it here made
    # --strict report a red the runner deliberately does not. The live SKIP
    # table may be empty, so a runner copy with a one-entry table stands in.
    parked = "tests/parked/test_parked_fixture.py"
    skip_dir = Path(tempfile.mkdtemp())
    _TMPDIRS.append(skip_dir)
    skip_runner = skip_dir / "run_tests.py"
    src = (HERE / "run_tests.py").read_text(encoding="utf-8")
    if "\nSKIP = {}\n" not in src:
        failures.append("run_tests.py's SKIP table moved; re-derive the SKIP-charter case")
    skip_runner.write_text(src.replace("\nSKIP = {}\n",
                                       "\nSKIP = {%r: 'fixture'}\n" % parked, 1),
                           encoding="utf-8")
    rc, out = drive(strict=True, exit_code=1, relpath=parked,
                    runner_path=skip_runner)
    if rc != 0:
        failures.append(
            "strict returned %r on the SKIP-charter suite %s -- prepush must "
            "honour run_tests.SKIP rather than re-run what the runner parks"
            % (rc, parked))
    if "[skip]" not in out:
        failures.append("the SKIP-charter suite was not reported as skipped:\n%s"
                        % out)

    # The ARGS table. scripts/test_prepush_install.py prints WARN and exits 0
    # without --require-installed, so a bare run of it passes over the very
    # absence it exists to notice. Once the gate is armed the runner passes the
    # flag, and so must this; the live ARGS table is empty until then, so a
    # runner copy carrying the armed entry stands in.
    install = "scripts/test_prepush_install.py"
    needs_flag = ("import sys\n"
                  "sys.exit(0 if '--require-installed' in sys.argv else 1)\n")
    args_runner = skip_dir / "run_tests_armed.py"
    if "\nARGS = {}\n" not in src:
        failures.append("run_tests.py's ARGS table moved; re-derive the ARGS case")
    args_runner.write_text(src.replace(
        "\nARGS = {}\n",
        "\nARGS = {%r: ['--require-installed']}\n" % install, 1), encoding="utf-8")
    rc, out = drive(strict=True, exit_code=0, relpath=install, body=needs_flag,
                    runner_path=args_runner)
    if rc != 0:
        failures.append(
            "strict returned %r for %s -- prepush ran it without the "
            "--require-installed entry that run_tests.ARGS carries" % (rc, install))
    if "[pass]" not in out:
        failures.append("%s did not report pass:\n%s" % (install, out))

    # A malformed timeout is config, not a crash --------
    #
    # 229 made this script import run_one, which calls timeout_secs(), which
    # raises on a non-numeric RUN_TESTS_TIMEOUT. Nothing between main()'s entry
    # and its return caught it, so `RUN_TESTS_TIMEOUT=abc` replaced the whole
    # report with a ValueError traceback and a nonzero exit -- the one thing
    # the default mode's contract at prepush_check.py:11-24 promises it never
    # does. Reproduced failing before the fix; this pins it.
    _old = os.environ.get("RUN_TESTS_TIMEOUT")
    os.environ["RUN_TESTS_TIMEOUT"] = "abc"
    try:
        rc, bad_out = drive(strict=False, exit_code=0)
        rc_strict, _ = drive(strict=True, exit_code=0)
    finally:
        if _old is None:
            os.environ.pop("RUN_TESTS_TIMEOUT", None)
        else:
            os.environ["RUN_TESTS_TIMEOUT"] = _old
    if rc != 0:
        failures.append(
            "DEFAULT + unusable RUN_TESTS_TIMEOUT returned %r, want 0 -- a bad "
            "env value must be reported, not raised through main()" % rc)
    if "RUN_TESTS_TIMEOUT" not in bad_out:
        failures.append("the report never names RUN_TESTS_TIMEOUT, so the "
                        "reader cannot act on it:\n%s" % bad_out)
    if "red test committed" in bad_out:
        failures.append("a check that never started was explained with the "
                        "red-ahead-of-its-fix sentence")
    if rc_strict != 2:
        failures.append("strict + unusable RUN_TESTS_TIMEOUT returned %r, want "
                        "2 -- nothing ran, so nothing is verified, and 1 would "
                        "be a misconfiguration wearing a test-failure code"
                        % rc_strict)

    # NOT RUN is not FAIL -------------------------------
    #
    # When the runner cannot load, every check is recorded NOT RUN -- and was
    # then folded into `failing` and explained by the red-ahead sentence, which
    # is advice about checks that RAN and went red. A reader skimming saw a
    # failure count with a reassuring explanation for it, and strict exited 1
    # in the vocabulary of a test failure. Driven through the real loader with
    # a path that cannot load, not by stubbing the loader out.
    gone = str(HERE / "no_such_runner_235.py")
    rc, out = drive(strict=False, exit_code=1, runner_path=gone)
    if rc != 0:
        failures.append("DEFAULT + unloadable runner returned %r, want 0" % rc)
    if "[NOT RUN]" not in out:
        failures.append("the unrun check was not reported NOT RUN:\n%s" % out)
    if "red test committed" in out:
        failures.append(
            "a check that never started was explained with the red-ahead-of-"
            "its-fix sentence, which is only ever about a check that ran")
    # The count line and the red-ahead sentence are one print, so asserting on
    # both proves one thing twice. This pins the other half instead: NOT RUN
    # has to survive into the summary carrying its REASON, which is the only
    # thing that tells a reviewer these checks are unverified rather than red.
    if "the suite runner did not load" not in out:
        failures.append("the reviewer summary does not say why the checks did "
                        "not run:\n%s" % out)
    rc_nothing_ran, strict_gone = drive(strict=True, exit_code=1,
                                        runner_path=gone)
    if rc_nothing_ran != 2:
        failures.append("strict + unloadable runner returned %r, want 2 -- "
                        "nothing ran, so nothing is verified" % rc_nothing_ran)
    if "never ran" not in strict_gone:
        failures.append("strict went red without saying the checks never ran, "
                        "so its red is indistinguishable from a test "
                        "failure:\n%s" % strict_gone)

    # --- an earlier fix ------------------------
    #
    # The whole point of the distinct code: strict is the mode built for a
    # MACHINE, and the exit code is the only channel a machine reads. Asserting
    # the two literals separately proves each number; this asserts the property
    # the ruling is actually about, and survives either number changing.
    rc_check_failed, _ = drive(strict=True, exit_code=1)
    if rc_check_failed == rc_nothing_ran:
        failures.append(
            "strict returns %r both when a check RAN AND FAILED and when NO "
            "check could run -- a machine cannot tell a red suite from a "
            "broken runner" % rc_check_failed)

    # The docstring must describe the codes -------------
    #
    # `doc` is the contract an agent reads to decide what a nonzero exit means,
    # and it went on saying a nonzero strict exit meant "a check failed" after
    # the code stopped being true. The pin above only asserts the word
    # "--strict" appears, which is why that drift passed. This pins the codes
    # OBSERVED above instead of a literal list: any code main() hands back that
    # the docstring does not name is a red.
    # Read the codes main() CAN return out of its source, not
    # only the ones some existing case happened to drive. Observation makes the
    # pin depend on where a case sits in this file and contributes nothing at
    # all for a new strict branch that has no test yet. The union keeps the
    # observed half as a cross-check, so a code the scan misses is still pinned
    # the moment a case returns it. The scan is not omniscient and does not
    # pretend to be: what it cannot read it reports (F-2), and it reads main()'s
    # body only, not everything below it (F-3).
    declared, unreadable = _declared_strict_codes()
    if unreadable:
        failures.append(
            "prepush_check.main() hands back an exit this pin cannot read: %s. "
            "The code set is derived from main()'s integer literals, so a code "
            "reached through a name or through sys.exit(<expr>) is invisible "
            "here and the docstring silently stops being checked for it. Return "
            "an integer literal from main(), or teach the scan to resolve this "
            "." % "; ".join(sorted(set(unreadable))))
    if not declared and not unreadable:
        failures.append(
            "the exit-code scan of prepush_check.main() found nothing -- the "
            "pin below has silently become a no-op for undriven codes; fix the "
            "scan rather than deleting it")
    for code in sorted(_STRICT_RCS | declared):
        # Match the LINE THAT DESCRIBES the code, not the bare
        # token. `exit 1` also occurs inside the exit-2 paragraph (quoting the
        # runner's warning that a config error must never wear it), so a bare
        # substring test stayed green when the line describing exit 1 was
        # deleted. `^  exit N -- ` is the docstring's own description form.
        if not re.search(r"^\s*exit %d\s+--\s+\S" % code, doc, re.M):
            failures.append(
                "--strict can return %d, but the module docstring has no "
                "`exit %d -- <description>` line -- the contract a reader "
                "trusts does not describe what the code does" % (code, code))

    # The notice must survive an empty check set --------
    #
    # Gating the runner-failure notice on `never_ran` dropped it whenever the
    # touched directories held no checks at all: never_ran is empty there
    # because nothing was DISCOVERED, not because everything ran. The reviewer
    # then saw "No checks in the touched directories" with no hint that this
    # run could not have run one anyway. A non-.py touched file is the shortest
    # route to zero discovered checks.
    rc, empty_out = drive(strict=False, exit_code=0, relpath="sub/notes.md",
                          body="not a check\n", runner_path=gone)
    if rc != 0:
        failures.append("DEFAULT + unloadable runner + no checks returned %r, "
                        "want 0" % rc)
    if "the suite runner did not load" not in empty_out:
        failures.append(
            "with no checks in the touched directories the summary never says "
            "the runner failed to load, so the one state where nothing COULD "
            "have run reads as the ordinary no-checks-here state:\n%s"
            % empty_out)

    for f in failures:
        print("FAIL: %s" % f)
    print("%s: 29 checks, %d failure(s)"
          % ("FAIL" if failures else "ok", len(failures)))
    return 1 if failures else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        for d in _TMPDIRS:
            shutil.rmtree(d, ignore_errors=True)
