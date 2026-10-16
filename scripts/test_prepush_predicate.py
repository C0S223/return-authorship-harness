"""Checks for prepush_check's policy-path predicate.

The predicate must be the live gate's is_policy(), not a restated list --
the shipped POLICY_PREFIXES tuple drifted and missed scripts/prepush_check.py
itself. The fallback branch in flags() keeps that red provable: if anyone
reverts to a tuple, the first assertion goes red again.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import prepush_check as pc  # noqa: E402


def flags(files):
    if hasattr(pc, "policy_flagged"):
        return set(pc.policy_flagged(files))
    # red baseline: the shipped tuple (the drift this suite exists to catch)
    return {f for f in files if f.startswith(pc.POLICY_PREFIXES)}


FLAGGED = [
    "scripts/prepush_check.py",   # existing file under scripts/ -- the drift case
    "CLAUDE.md",
    ".claude/hooks/x.py",
    ".claude/agents/x.md",
    ".git/config",
]
NOT_FLAGGED = [
    "projects/app/handler.py",
    "scripts/does_not_exist_zz.py",  # new file under scripts/: not a policy path
]

got = flags(FLAGGED + NOT_FLAGGED)
for f in FLAGGED:
    assert f in got, "not flagged: %s" % f
for f in NOT_FLAGGED:
    assert f not in got, "wrongly flagged: %s" % f

# Import-failure branch: gate module unreachable -> warn-all, never warn-none.
if hasattr(pc, "policy_flagged"):
    got = set(pc.policy_flagged(NOT_FLAGGED,
                                hook_path=os.path.join(HERE, "no_such_hook.py")))
    assert got == set(NOT_FLAGGED), "import failure must flag every path"

# F1: the warn-all banner must survive a hostile exception message on a
# narrow console codepage. A hook whose SyntaxError embeds U+2192 killed the
# print under cp1252 stdout: no banner, no flag list, traceback instead.
# Run in a subprocess with PYTHONIOENCODING=cp1252 to pin the codepage.
if hasattr(pc, "policy_flagged"):
    scratch = os.path.join(HERE, "scratch_bad_hook_f1.py")
    with open(scratch, "w", encoding="utf-8") as f:
        f.write("x = 1 → 2\n")
    try:
        code = ("import sys; sys.path.insert(0, %r); "
                "import prepush_check as pc; "
                "got = pc.policy_flagged(['a.py', 'b.py'], hook_path=%r); "
                "assert got == ['a.py', 'b.py'], got") % (HERE, scratch)
        env = dict(os.environ, PYTHONIOENCODING="cp1252")
        run = subprocess.run([sys.executable, "-c", code],
                             capture_output=True, text=True, env=env)
        assert run.returncode == 0, \
            "warn-all branch died under cp1252:\n%s" % run.stderr
        assert "!!!" in run.stdout, \
            "banner missing under cp1252:\n%s" % run.stdout
    finally:
        os.remove(scratch)

print("test_prepush_predicate: all checks pass")
