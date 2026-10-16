#!/usr/bin/env python3
"""Runs cite_check's own --selftest in the suite. A review found no runner collected it, and
cite_check imports its section matcher from test_graph_pointers.py, so a change to those
helpers could pass CI and break cite_check unseen.

It runs a second time with TMPDIR inside a scratch `worktrees/` directory, the shape
every lane worktree's TEMP has, where the selftest's prune assertion once failed falsely. The
child's resolved temp dir is printed and checked, since tempfile silently falls back to another
directory when TMPDIR is unusable and the pin would then pass without testing anything."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

TOOL = Path(__file__).resolve().parent.parent / ".claude" / "skills" / "cite-check" / "cite_check.py"

r = subprocess.run([sys.executable, str(TOOL), "--selftest"], capture_output=True, text=True)
assert r.returncode == 0 and "selftest OK" in r.stdout, r.stdout + r.stderr
print("ok cite_check --selftest")

with tempfile.TemporaryDirectory() as d:
    wt = Path(d) / "worktrees" / "lane"
    wt.mkdir(parents=True)
    env = dict(os.environ, TMPDIR=str(wt))     # tempfile reads TMPDIR first on every platform
    got = subprocess.run([sys.executable, "-c", "import tempfile; print(tempfile.gettempdir())"],
                         capture_output=True, text=True, env=env).stdout.strip()
    assert "worktrees" in Path(got).parts, f"child temp dir resolved to {got!r}, not under worktrees/"
    r = subprocess.run([sys.executable, str(TOOL), "--selftest"], capture_output=True, text=True, env=env)
    assert r.returncode == 0 and "selftest OK" in r.stdout, r.stdout + r.stderr
    print(f"ok cite_check --selftest under a worktrees/ temp dir ({got})")

# The ambiguous half of the bare-cite reset. A plain mention matching two files must
# clear the current file, so a following bare `:N` WARNs instead of grading against `prev.md`.
with tempfile.TemporaryDirectory() as d:
    root = Path(d)
    (root / "prev.md").write_text("one\ntwo\nthree\n", encoding="utf-8")
    for sub in ("a", "b"):
        (root / sub).mkdir()
        (root / sub / "dup.md").write_text("x\n", encoding="utf-8")
    (root / "doc.md").write_text("`prev.md` then `dup.md` then bare `:2`.\n", encoding="utf-8")
    r = subprocess.run([sys.executable, str(TOOL), "--root", str(root), str(root / "doc.md")],
                       capture_output=True, text=True)
    assert "prev.md:2" not in r.stdout, "bare :2 graded against prev.md past an ambiguous mention:\n" + r.stdout + r.stderr
    assert "bare `:2` with no file mentioned before it" in r.stdout, r.stdout + r.stderr
    print("ok cite_check: an ambiguous mention resets the file a bare cite binds to")
