#!/usr/bin/env python3
"""Runnable checks: the last-touched field (a real commit says so, an untracked path says so),
the REVISION line's full 40-hex sha, and the ARTIFACT line's WARN, SECTION? and UNANCHORED counts.

Run: python .claude/skills/review-order/test_review_order.py
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import review_order  # noqa: E402


def test_last_touched():
    with tempfile.TemporaryDirectory() as d:
        wt = Path(d)
        run = lambda *a: subprocess.run(["git", "-C", str(wt), *a], check=True,
                                        capture_output=True, text=True)
        run("init", "-q")
        run("config", "user.email", "t@t"); run("config", "user.name", "t")
        (wt / "tracked.md").write_text("x\n", encoding="utf-8")
        run("add", "tracked.md")
        run("commit", "-qm", "add tracked")
        (wt / "loose.md").write_text("y\n", encoding="utf-8")     # exists, never committed

        assert review_order.last_touched(wt, "tracked.md") == review_order.git(
            wt, "rev-parse", "--short", "HEAD"), "tracked artifact names its commit"
        assert review_order.last_touched(wt, "loose.md") == "untracked (not in git)", \
            "an untracked artifact says so instead of printing an empty field"


def _emit(files):
    """Run the real script on a throwaway clean repo whose origin/HEAD names build-1; return
    (stdout, full HEAD sha). The reviewer is a real definition under this tree's agents/."""
    with tempfile.TemporaryDirectory() as d:
        wt = Path(d)
        run = lambda *a: subprocess.run(["git", "-C", str(wt), *a], check=True,
                                        capture_output=True, text=True).stdout.strip()
        run("init", "-q")
        run("config", "user.email", "t@t"); run("config", "user.name", "t")
        for name, body in files.items():
            (wt / name).write_text(body, encoding="utf-8")
            run("add", name)
        run("commit", "-qm", "fixture")
        run("update-ref", "refs/remotes/origin/build-1", "HEAD")
        run("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/build-1")
        args = [a for name in files if name.endswith(".md") and name != "guide.md"
                for a in ("--artifact", name)]
        r = subprocess.run([sys.executable, str(Path(review_order.__file__)),
                            "senior-engineer", str(wt), *args],
                           capture_output=True, text=True, encoding="utf-8")
        assert r.returncode == 0, r.stderr
        return r.stdout, run("rev-parse", "HEAD")


def test_revision_line_is_full_sha():
    """Reviewers refuse a non-40-hex revision; the pinned line must carry the full sha."""
    out, full = _emit({"a.txt": "x\n"})
    line = next(l for l in out.splitlines() if l.startswith("REVISION UNDER REVIEW:"))
    m = re.search(r" @ (\S+)", line)
    assert m and re.fullmatch(r"[0-9a-f]{40}", m.group(1)), line
    assert m.group(1) == full, (line, full)


def test_base_is_origin_head_and_its_absence_refuses():
    """(a): the BASE line names origin/HEAD's target, whatever its name; with no
    origin/HEAD (a master-named ref alone is not the default) the script refuses."""
    out, _ = _emit({"a.txt": "x\n"})
    assert any(l.startswith("BASE: origin/build-1 ") for l in out.splitlines()), out
    with tempfile.TemporaryDirectory() as d:
        wt = Path(d)
        run = lambda *a: subprocess.run(["git", "-C", str(wt), *a], check=True,
                                        capture_output=True, text=True)
        run("init", "-q")
        run("config", "user.email", "t@t"); run("config", "user.name", "t")
        (wt / "a.txt").write_text("x\n", encoding="utf-8")
        run("add", "a.txt")
        run("commit", "-qm", "fixture")
        run("update-ref", "refs/remotes/origin/master", "HEAD")
        r = subprocess.run([sys.executable, str(Path(review_order.__file__)),
                            "senior-engineer", str(wt)],
                           capture_output=True, text=True, encoding="utf-8")
        assert r.returncode != 0 and "default branch was not found" in r.stderr, (r.returncode, r.stderr)


def test_artifact_counts_warn_and_section():
    """A dead mention (WARN) and a missed heading (SECTION?) must show
    in the ARTIFACT line, or an artifact with them prints the same line as a clean one."""
    out, _ = _emit({"guide.md": "# Real heading\n",
                    "art.md": "Gone: `ghost.md`.\n\n`guide.md` § *Imaginary heading* here.\n"})
    line = next(l for l in out.splitlines() if l.startswith("ARTIFACT: art.md"))
    assert "1 WARN" in line, line
    assert "1 SECTION?" in line, line
    assert "0 FAIL" in line, line



def test_artifact_counts_unanchored():
    """An artifact whose only finding is an unsourced quote (cite_check
    kind UNANCHORED) must not print the same ARTIFACT counts as a clean artifact."""
    out, _ = _emit({"clean.md": "Nothing quoted here.\n",
                    "unanch.md": 'He said "the quick brown fox jumps over" once.\n'})
    counts = {name: next(l for l in out.splitlines() if l.startswith(f"ARTIFACT: {name}"))
              .split("cite-check:", 1)[1] for name in ("clean.md", "unanch.md")}
    assert "1 UNANCHORED" in counts["unanch.md"], counts
    assert "0 UNANCHORED" in counts["clean.md"], counts
    assert counts["unanch.md"] != counts["clean.md"], counts


if __name__ == "__main__":
    # Auto-discover: a hand-listed call block silently skips any
    # test not added to it. Not unittest.main(): these are bare functions, so it
    # would run zero tests and still print OK.
    for _name, _fn in sorted(dict(globals()).items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
    print("selftest OK")
