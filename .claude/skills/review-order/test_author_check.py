#!/usr/bin/env python3
"""Runnable check: every work order header ends with the four-question AUTHOR CHECK block.

Run: python .claude/skills/review-order/test_author_check.py
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import review_order  # noqa: E402


def test_author_check_block_is_printed_last():
    with tempfile.TemporaryDirectory() as d:
        wt = Path(d)
        run = lambda *a: subprocess.run(["git", "-C", str(wt), *a], check=True,
                                        capture_output=True, text=True)
        run("init", "-q")
        run("config", "user.email", "t@t"); run("config", "user.name", "t")
        (wt / "a.md").write_text("x\n", encoding="utf-8")
        run("add", "a.md")
        run("commit", "-qm", "fixture")
        run("update-ref", "refs/remotes/origin/build-1", "HEAD")
        run("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/build-1")
        r = subprocess.run([sys.executable, str(Path(review_order.__file__)),
                            "adversarial-reviewer", str(wt), "--artifact", "a.md"],
                           capture_output=True, text=True, encoding="utf-8")
        assert r.returncode == 0, r.stderr
        lines = r.stdout.splitlines()
        head = next(i for i, l in enumerate(lines) if l.startswith("AUTHOR CHECK"))
        assert head > next(i for i, l in enumerate(lines) if l.startswith("ARTIFACT: a.md")), \
            "the check follows the artifact lines"
        items = lines[head + 1:]
        assert [re.match(r"  (\d)\. ", l).group(1) for l in items] == ["1", "2", "3", "4"], items
        assert len(review_order.AUTHOR_CHECK) == 4


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
    print("OK")
