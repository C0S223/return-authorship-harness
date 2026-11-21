#!/usr/bin/env python3
"""`.github/CODEOWNERS` names the operator on the named policy paths.

WHY THIS EXISTS. CODEOWNERS is only a line of text until the ruleset requires
code-owner review, and a silent edit (a pattern dropped, an owner typo, `CLAUDE.md`
narrowed to the root) leaves the file looking fine while a policy path goes
unowned. GitHub resolves the file with "last matching line wins" and
gitignore-style anchoring, with one difference: a pattern ending in `*` matches
one level only (GitHub "About code owners": `docs/*` matches
`docs/getting-started.md` "but not further nested files like
`docs/build-app/troubleshooting.md`"). This test does the same: a small matcher
resolves sample paths to owners, instead of grepping for strings.

Not a hook and not a text classifier (ADR 0001): the file is path ownership that
GitHub enforces at review time; this only guards the file against drift.

# ponytail: a matcher for the subset the file uses (`*`, `**`, `?`, leading and
# trailing `/`), not a full gitignore engine. CODEOWNERS does not support `!`
# negation, `[ ]` ranges or `\\#` escaping, so `parse` rejects a pattern using them.
"""
import re
from pathlib import Path

CODEOWNERS = Path(__file__).resolve().parents[1] / ".github" / "CODEOWNERS"
OPERATOR = ["@OWNER"]

# (path, owned) -- every pattern has at least one sample here, and `owned` False
# rows pin the edges: nothing broader than the list is claimed.
SAMPLES = [
    # CLAUDE.md, AGENTS.md, AGENTS.override.md at any depth
    ("CLAUDE.md", True),
    ("worktrees/x/CLAUDE.md", True),
    ("docs/enforcement/CLAUDE.md", True),
    ("AGENTS.md", True),
    ("a/b/AGENTS.md", True),
    ("AGENTS.override.md", True),
    ("x/AGENTS.override.md", True),
    # directory trees, anchored at the root. Each tree has a direct child and a
    # file 2+ levels down, so narrowing `/X/**` to `/X/*` fails here.
    (".claude/settings.json", True),
    (".claude/skills/a/SKILL.md", True),
    (".agents/x.md", True),
    (".agents/skills/a/SKILL.md", True),
    (".codex/config.toml", True),
    (".codex/agents/Explore.toml", True),
    ("roles/super-doer.md", True),
    ("roles/a/b.md", True),
    ("graphs/lane.md", True),
    ("graphs/a/b.md", True),
    (".githooks/pre-push", True),
    (".githooks/a/b", True),
    ("tools/git-hooks/pre-push", True),
    ("tools/git-hooks/a/b", True),
    (".github/CODEOWNERS", True),
    (".github/workflows/ci.yml", True),
    # root README only, and the named scripts only
    ("README.md", True),
    ("docs/README.md", False),
    ("scripts/stamp_check.py", True),
    ("scripts/ci_policy_check.py", True),
    ("scripts/prepush_check.py", True),
    ("scripts/lane_ready.py", True),
    ("scripts/log_filter.py", True),      # the session-close hook runs it
    ("scripts/run_tests.py", True),       # CI's gate runs the PR's copy
    ("scripts/cloud-setup.sh", True),     # arms the pre-push gate
    # no owner
    ("scripts/test_codeowners.py", False),
    ("work/x/y.md", False),
    ("docs/adr/0001-park-text-classifying-guards.md", False),
    ("tools/other/x.py", False),
    ("githooks/pre-push", False),
    (".claude-other/x.md", False),
    ("x/.claude/y.md", False),
]


def _regex(pattern):
    """Translate one CODEOWNERS pattern to a regex over a repo-relative path."""
    dir_only = pattern.endswith("/")
    body = pattern.strip("/")
    # A slash at the start or in the middle anchors to the root; otherwise any depth.
    anchored = pattern.startswith("/") or "/" in body
    out = []
    i = 0
    while i < len(body):
        c = body[i]
        if body.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif body.startswith("**", i):
            out.append(".*")
            i += 2
        elif c == "*":
            out.append("[^/]*")
            i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(c))
            i += 1
    prefix = "" if anchored else "(?:.*/)?"
    # A pattern naming a directory owns everything under it, but a pattern ending in
    # `*` does not: GitHub's `docs/*` owns `docs/getting-started.md` "but not further
    # nested files like `docs/build-app/troubleshooting.md`" (gitignore would).
    if dir_only:
        tail = "/.*"
    elif body.endswith("*"):
        tail = ""
    else:
        tail = "(?:/.*)?"
    return re.compile("^" + prefix + "".join(out) + tail + "$")


def parse(text):
    """-> list of (pattern, owners) in file order; blank and comment lines skipped."""
    rules = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        pattern, *owners = line.split()
        if pattern.startswith("!") or any(c in pattern for c in "[]\\"):
            raise ValueError(f"CODEOWNERS does not support {pattern!r} (! [ ] \\)")
        rules.append((pattern, owners))
    return rules


def owners_of(rules, path):
    """Last matching line wins, as on GitHub. No match -> no owner."""
    found = []
    for pattern, owners in rules:
        if _regex(pattern).match(path):
            found = owners
    return found


def test_matcher_follows_codeowners_semantics():
    rules = parse("*.md @a\n/docs/ @b\n/docs/keep.md\nsrc/*.py @c\n/top/** @d\n")
    assert owners_of(rules, "x/y/z.md") == ["@a"]            # no slash: any depth
    assert owners_of(rules, "docs/q.txt") == ["@b"]          # dir pattern owns its contents
    assert owners_of(rules, "docs/q.md") == ["@b"]           # last match beats the earlier *.md
    assert owners_of(rules, "docs/keep.md") == []            # a later owner-less line un-owns
    assert owners_of(rules, "src/a.py") == ["@c"]            # inner slash anchors to the root
    assert owners_of(rules, "x/src/a.py") == []              # ...so not at depth
    assert owners_of(rules, "src/deep/a.py") == []           # `*` does not cross `/`
    assert owners_of(rules, "top/a/b") == ["@d"]
    assert owners_of(rules, "top") == []                     # `/top/**` is the contents only
    assert owners_of(rules, "elsewhere/top/a") == []         # leading slash anchors


def test_trailing_star_matches_one_level_only():
    # GitHub "About code owners": `docs/*` matches `docs/getting-started.md` "but not
    # further nested files like `docs/build-app/troubleshooting.md`".
    rules = parse("docs/* @a")
    assert owners_of(rules, "docs/getting-started.md") == ["@a"]
    assert owners_of(rules, "docs/build-app/troubleshooting.md") == []


def test_parser_rejects_syntax_codeowners_does_not_support():
    for line in ("!docs/x.md @a", "docs/[ab].md @a", "\\#notes.md @a"):
        try:
            parse(line)
        except ValueError:
            continue
        assert False, f"parse accepted unsupported syntax: {line!r}"
    assert parse("docs/x.md @org/team") == [("docs/x.md", ["@org/team"])]


def test_every_owner_in_the_file_is_the_operator():
    text = CODEOWNERS.read_text(encoding="utf-8")
    rules = parse(text)
    assert rules, f"{CODEOWNERS} has no rules"
    for pattern, owners in rules:
        assert owners == OPERATOR, f"{pattern!r} is owned by {owners}, not {OPERATOR}"


def test_policy_paths_have_the_operator_as_owner_and_others_have_none():
    rules = parse(CODEOWNERS.read_text(encoding="utf-8"))
    bad = []
    for path, owned in SAMPLES:
        got = owners_of(rules, path)
        want = OPERATOR if owned else []
        if got != want:
            bad.append(f"{path}: owners {got}, expected {want}")
    assert not bad, "CODEOWNERS resolves wrongly:\n  " + "\n  ".join(bad)


if __name__ == "__main__":
    for _name, _fn in sorted(dict(globals()).items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
    print("ok")
