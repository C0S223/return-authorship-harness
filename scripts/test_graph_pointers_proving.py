"""Proving tests for test_graph_pointers.py -- one fixture per finding of its
2026-09-05 review, each asserting the lint goes RED on the exact shape it was
green on before the repair.

Why this file exists: the lint is a test, and a test that cannot fail is a
document claiming a protection nothing reads back (F4 of its own
review). Every repair was verified by hand-run mutation; this pins those runs
so a revert of any one repair turns this suite red, not the auditor's memory.

Runs the real main() against a temp tree by rebinding the module's ROOT /
TREE / GRAPHS. No framework: assert-based, one process, stdlib only.
"""
import contextlib
import importlib.util
import io
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("gp", HERE / "test_graph_pointers.py")
gp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gp)

CLAUDE = "# CLAUDE.md\n\n## 1. One\n\n## 2. Two\n\n## 3. Three\n"
TARGET = "# target\n\n## Alpha beta gamma\n\n## Verdicts\n"


def run(graph, target=TARGET, extra=None):
    """Build a tree, point the lint at it, return (rc, stdout)."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "CLAUDE.md").write_text(CLAUDE, encoding="utf-8")
        tree = root
        graphs = tree / "graphs"
        graphs.mkdir(parents=True)
        (graphs / "g.md").write_text(graph, encoding="utf-8")
        t = tree / "target.md"  # sibling of graphs/, not inside it
        t.write_bytes(target if isinstance(target, bytes) else target.encode("utf-8"))
        for rel, body in (extra or {}).items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body, encoding="utf-8")
        gp.ROOT, gp.TREE, gp.GRAPHS = root, tree, graphs
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = gp.main()
        return rc, out.getvalue()


def red(graph, needle, **kw):
    rc, out = run(graph, **kw)
    assert rc == 1, f"expected FAIL, got ok:\n{out}"
    assert needle in out, f"expected {needle!r} in:\n{out}"


# Baseline: every family present and correct -> ok. Guards the fixtures, not the lint.
rc, out = run("# g\n[t](../target.md) and [a](../target.md#alpha-beta-gamma)\n"
              "`target.md` § Alpha beta\n`target.md` § Verdicts and supplies\nsee §2\n")
assert rc == 0 and "6 pointers checked" in out, out

# F1: shared FIRST WORD only, long citation vs long heading -> must be red.
red("# g\n`target.md` § Alpha zulu yankee\n", "has no section matching")

# F2: multi-digit section number validated against its first digit.
red("# g\nsee §12\n", "CLAUDE.md has no section 12")

# F3: link wrong relative to its own graph, right relative to TREE.
red("# g\n[x](other/t.md)\n", "does not resolve from this graph",
    extra={"other/t.md": "# t\n"})

# F4: a graph that parses to zero pointers is vacuous, not ok.
red("# g\n\nprose only\n", "no pointers parsed")

# F6: file half resolves, fragment names no heading.
red("# g\n[x](../target.md#phantom)\n", "anchor names no heading")

# F7: mis-encoded target is a red, not a silently-mangled heading list.
red("# g\n`target.md` § Alpha beta\n", "not valid UTF-8", target=b"# t\n\n## Alpha \xff beta\n")

# F5 (overturned): an unmatched mention is LOUD, not fatal, and not silent.
rc, out = run("# g\n[t](../target.md)\n`phantom.md` is a template name\n")
assert rc == 0 and "phantom.md" in out and "NOT resolved" in out, out

SEC = "§"

# --- 2026-09-07 review of the repair itself: G1, G2, G3. ---------------------

# G2: two shared leading words are not identity when the TARGET repeats them.
# Pre-fix this measured green on the `c >= 2` threshold alone; the citation's
# real words ("wizards dragons") were never compared to anything.
red("# g\n[t](../target.md)\n`target.md` " + SEC + " Since exercised wizards dragons\n",
    "has no section matching",
    target="# t\n\n## Since exercised\n\n## Since exercised\n")

# G2, the other side: the SAME two-word lead-in stays green when it is unique.
# Guards against the fix over-rejecting, which is how F5 went wrong.
rc, out = run("# g\n[t](../target.md)\n`target.md` " + SEC + " Since exercised wizards\n",
              target="# t\n\n## Since exercised one\n\n## Wholly other\n")
assert rc == 0, out

# G3: a path-shaped mention with no placeholder IS a pointer and is now FATAL.
# Pre-fix it printed a line that run_tests.py swallows on a pass -- invisible.
red("# g\n[t](../target.md)\n`work/nope/GONE.md` is cited here\n",
    "resolves to no file")

# G3, the other side: the same shape resolves -> green; and a template path with
# a placeholder is never fatal, which is what F5's counter-case was right about.
rc, out = run("# g\n[t](../target.md)\n`work/real/HERE.md` and `work/x/RECORD-NN.md`\n",
              extra={"work/real/HERE.md": "# h\n"})
assert rc == 0, out

# G3-1: a dead path whose NAME merely contains the letters NN is NOT a template.
# The round-1 substring test exempted work/x/PLANNING.md silently -- precisely the
# blind spot G3 existed to close.
red("# g\n[t](../target.md)\n`work/x/PLANNING.md` is cited here\n",
    "resolves to no file")

# G1: NOT a fix -- a pin on documented scope. The number alone decides a
# numbered-section citation, so false prose about section 3 measures GREEN. The
# lint resolves references; it cannot check whether a claim about one is true.
# This asserts the limit stays visible instead of being re-discovered.
rc, out = run("# g\n[t](../target.md)\n`target.md` " + SEC + " 3 which talks about wizards\n",
              target="# t\n\n## 1. One\n\n## 3. Three\n")
assert rc == 0, out

print("ok -- 14 proving cases (baseline, F1-F4/F6/F7 red, F5 loud, G2/G3/G3-1 red "
      "+ a green counter-case for each, G1 scope pinned)")
