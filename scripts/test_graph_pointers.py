#!/usr/bin/env python3
"""A graph is a set of instructions to a session that cannot ask a question. A pointer in it
that resolves nowhere is not a typo; it is a step the runner has to invent, and the invention
is unreviewed.

This is the reader the convention demands (CLAUDE.md section 6, "write implies read"). Until
now NOTHING read the graph files back -- not a test, not a hook -- while two governing graphs
sat there carrying pointers into a dozen other files.

The incident is F7 of the standard-workhorse first cold run: the graph told the hub
to file the verdict in "the ledger's current owner surface", a phrase appearing nowhere else in
the tree, so the runner had to guess the destination of the one artifact the run exists to
produce. The repair replaced it with a notes file section Verdicts -- and the repair's own
review checked that a notes file EXISTS, which is exactly the check that cannot catch a wrong
section name. Both halves of that near-miss are covered here.

Two families:

  links    -- every [text](target.md) must resolve. Anchors and URLs are skipped.
  sections -- every `<file>.md` section <Name> must name a real heading in that file.

Neither side of a section reference is delimited. The citation runs into the sentence
("section Verdicts and supplies the disposition"), and the heading runs past what anyone would
cite ("Review freezing -- the builder's commit is the unit"). So this compares LEADING WORDS in
both directions rather than demanding either be a prefix of the other. A first cut required the
heading to prefix the citation and reported eleven failures, every one of them a real pointer
into a real section -- a suite whose reds are all false teaches readers to discount reds, which
is the disease test_default_prompt.py was written to cure. Deliberately lenient: the defect
worth catching is a pointer that resolves NOWHERE, not a citation that abbreviates.

A bare section N (no filename) means CLAUDE.md, which is the only file with numbered sections.

# ponytail: regex over a markdown parser, matching the sibling suite test_default_prompt.py.
# Same reason: the convention is backticks and inline links, not arbitrary markdown.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GRAPHS = ROOT / "graphs"
TREE = ROOT

LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
# `file.md` or [`file.md`](...) then the section mark, then whatever prose follows.
SECTION = re.compile(r"`([^`\n]*\.md)`(?:\]\([^)]*\))?\s*§+\s*([^\n]*)")
BARE = re.compile(r"(?<![\w`])§\s*([0-9]+)")
MENTION = re.compile(r"`([^`\n]*\.md)`")
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.M)
# This tree marks subsections with a bolded lead-in as often as with a hash, especially in the
# role files. `roles/super-doer.md` section Deliver is real and is written that
# way; a checker that only knows hashes calls it a phantom and is wrong.
BOLDLEAD = re.compile(r"^\*\*(.+?)\.?\*\*", re.M)


def resolve(ref, src, bases=None):
    """Graph-relative first, then tree-relative: the tree writes both forms.

    F3: the TREE/ROOT fallback exists for the SECTION family, whose refs are bare
    names (a notes file) rather than paths. A markdown LINK is a path a reader
    follows from the graph's own directory, so it is resolved with bases=(src.parent,)
    and a link that is wrong relative to its graph now goes red. Measured: all link
    targets in the graphs already resolve graph-relative, so this costs no coverage."""
    ref = ref.split("#")[0]
    if not ref or ref.startswith(("http://", "https://", "mailto:")):
        return None
    for base in (bases or (src.parent, TREE, ROOT)):
        p = (base / ref).resolve()
        if p.exists():
            return p
    return False


PLACEHOLDER = re.compile(r"<|-NN[-.]|YYYY")


def words(s):
    """Backticks, dashes and punctuation are formatting, not identity."""
    return [w for w in re.split(r"[^a-z0-9]+", s.lower()) if w]


def headings(path):
    """F7: strict, matching how the graph itself is read. errors="replace" turned a
    mis-encoded target into U+FFFD, which splits in words() and can promote a different
    token to the front of a heading -- flipping a pointer's verdict with no signal.
    Measured: it manufactured a FAIL on a real pointer. None means undecodable."""
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None
    return [words(h) for h in HEADING.findall(text) + BOLDLEAD.findall(text)]


def names_a_section(probe, path):
    """F1: this compared h[0] == p[0] -- the FIRST WORD ONLY. A notes file yields 45
    accepted headings across 34 distinct first words (a, the, no, not, do, what...), so
    a citation beginning with any of them resolved to a real heading regardless of the
    rest -- including "the ledger's current owner surface", the phantom named in this
    file's own docstring as the reason it exists. Measured GREEN before this repair.

    The fix is what the docstring always described: compare leading word SEQUENCES, to
    the length of the shorter side. "Verdicts" still matches "Verdicts and supplies the
    disposition" (n=1, both start "verdicts"); a six-word heading no longer matches an
    unrelated six-word citation that happens to share one word."""
    p = words(probe)
    if not p:
        return False
    hs = headings(path)
    if hs is None:
        return None
    for h in hs:
        if not h:
            continue
        # CLAUDE.md's sections are numbered, and the tree cites them possessively --
        # "section 3's rule that main-tree git ops...". The number IS the name; the rest
        # is prose about it. Requiring the prose to match the heading's words made four
        # real pointers go red.
        # SCOPE, stated because the 2026-09-07 review measured it and called it a
        # defect: on this path the number alone decides, so `CLAUDE.md` section 3
        # "talks about wizards" measures GREEN. That is correct and is not fixable
        # here. A pointer lint resolves REFERENCES; section 3 exists, so the pointer
        # resolves. Whether the prose about section 3 is TRUE is a claim no lint can
        # check -- it needs a reader. Do not cite this suite as catching that class.
        if h[0].isdigit() and p[0] == h[0]:
            return True
        c = 0
        while c < min(len(h), len(p)) and h[c] == p[c]:
            c += 1
        # Two shared leading words, or a one-word heading fully matched. Full min-prefix
        # equality was too strict: "Review freezing. In short:" is a real citation of
        # "Review freezing -- the builder's commit is the unit", which the docstring
        # names as the case that must stay green.
        # Accept when the shared run is two or more words, or when one side is fully
        # consumed -- a citation that abbreviates ("section New") and a heading shorter
        # than its citation ("Verdicts" cited as "Verdicts and supplies the disposition")
        # are both real, and the docstring names them. What is now rejected, and was not
        # before, is a long citation sharing only ONE word with a long heading.
        if not (c >= 2 or c == len(p) or c == len(h)):
            continue
        # G2 (measured): two shared leading words are not identity when the target
        # repeats them. A notes file has FOUR headings starting "Since exercised" and
        # TWO starting "What reads" -- its own bold-lead template. A prefix that names
        # several headings names none of them.
        # G2-1 (round 2): round 1 hung this guard on the `c >= 2` branch ALONE, so the
        # untouched `c == len(h)` branch still accepted unconditionally -- and "Since
        # exercised" is a VERBATIM DUPLICATE two-word heading, which takes that branch
        # and never reaches the guard. Measured True where False was wanted. Uniqueness
        # now gates every accept path, however the prefix was reached. Verified not to
        # over-reject: the real tree stays green at 83 pointers.
        if sum(1 for o in hs if o[:c] == h[:c]) == 1:
            return True
    return False


def main():
    graphs = sorted(GRAPHS.glob("*.md"))
    if not graphs:
        print("FAIL: no graph files found -- this suite would pass on an empty directory.")
        return 1

    bad = []
    unmatched = []
    checked = 0
    per_graph = {}
    for g in graphs:
        before = checked
        covered = set()
        text = g.read_text(encoding="utf-8")

        for ref in LINK.findall(text):
            got = resolve(ref, g, (g.parent,))
            if got is None:
                continue
            covered.add(ref.partition("#")[0])
            checked += 1
            if got is False:
                bad.append(f"{g.name}: link target does not resolve from this graph: {ref}")
                continue
            # F6: resolve() strips the fragment, and the caller then counted the pointer
            # as checked -- so file.md#phantom sat inside the total with only its file
            # half tested. Bare #foo is still skipped (resolve returns None), which is
            # what the docstring describes; this is the case it did not describe.
            frag = ref.partition("#")[2]
            if frag:
                checked += 1
                hs = headings(got)
                if hs is None:
                    bad.append(f"{g.name}: link target is not valid UTF-8: {ref}")
                elif "-".join(words(frag)) not in {"-".join(h) for h in hs if h}:
                    bad.append(f"{g.name}: anchor names no heading in {ref}")

        for ref, tail in SECTION.findall(text):
            covered.add(ref)
            got = resolve(ref, g)
            if got is None or got is False:
                checked += 1
                bad.append(f"{g.name}: section reference into a file that does not exist: {ref}")
                continue
            checked += 1
            hit = names_a_section(tail, got)
            if hit is None:
                bad.append(f"{g.name}: section target is not valid UTF-8: {ref}")
            elif not hit:
                shown = " ".join(tail.split()[:4])
                bad.append(f"{g.name}: `{ref}` has no section matching \"{shown}...\"")

        # F5: 44 of the 88 backticked .md mentions matched neither family and were
        # never resolved at all -- a pointer lost coverage by being written slightly
        # differently, and the loss showed only as a smaller number nobody compared.
        # Skipping is the silent direction (test_machinery_verdict_keys.py:76-79).
        for ref in set(MENTION.findall(text)):
            if ref in covered:
                continue
            unmatched.append(f"{g.name}: {ref}")

        claude_md = ROOT / "CLAUDE.md"
        numbered = {re.match(r"^([0-9]+)\.", h).group(1)
                    for h in HEADING.findall(claude_md.read_text(encoding="utf-8"))
                    if re.match(r"^([0-9]+)\.", h)}
        for n in set(BARE.findall(text)):
            checked += 1
            if n not in numbered:
                bad.append(f"{g.name}: CLAUDE.md has no section {n}")

        # F4: main() already refused an empty graph DIRECTORY -- "this suite would
        # pass on an empty directory" -- but nothing refused an empty PARSE. A graph
        # reduced to a single heading dropped 14 pointers and still printed ok, exit 0.
        # Same guard, carried down one level. The sibling suite does this
        # (test_machinery_verdict_keys.py:118-121, test_parse_found_the_data).
        per_graph[g.name] = checked - before
        if per_graph[g.name] == 0:
            bad.append(f"{g.name}: no pointers parsed -- the checks above are vacuous here")

    for u in unmatched:
        ref = u.split(": ", 1)[1]
        # G3-1 (round 2): `"NN" in ref` is a case-sensitive SUBSTRING, so a real dead
        # path like work/x/PLANNING.md was silently exempted -- the exact silent blind
        # spot this check exists to close. NN must be a delimited token.
        if "/" not in ref or PLACEHOLDER.search(ref):
            continue  # a template or a bare KIND of file -- a mention, not a pointer
        if not (TREE / ref).exists():
            bad.append(f"{u}: path-shaped mention resolves to no file")
    for b in bad:
        print("  " + b)
    # F5, retuned twice. Round 1 made the skip "loud instead of fatal". The
    # 2026-09-07 review measured that and it was FALSE: run_tests.py prints a
    # suite's captured stdout only for FAILs (run_tests.py record() at :231-233,
    # dump at :281-285), so every one of these lines is swallowed on a pass. Loud
    # to a direct runner, silent to the only consumer -- a warning with no reader,
    # which section 6 says does not land.
    # The split the data actually supports: of the 15 unresolved mentions, 11 carry
    # a template placeholder (NN, <topic>, YYYY) or are a bare KIND of file with no
    # directory (REPORT.md, notes.md) -- mentions, not pointers, exactly as F5's
    # counter-case said. The other 4 are real repo-relative paths, and all 4 resolve
    # on disk today. So a path-shaped mention with no placeholder IS a pointer and
    # is now FATAL; it goes red the day one of those files moves. The rest stay a
    # printed count, and the docstring no longer claims anyone reads it.
    if unmatched:
        print(f"{len(unmatched)} backticked .md mention(s) matched no pointer family "
              f"and were NOT resolved (this line is swallowed by run_tests.py on a "
              f"pass -- see the comment above; the path-shaped ones fail instead):")
        for u in unmatched:
            print("    ~ " + u)
    print(f"{checked} pointers checked across {len(graphs)} graph file(s).")
    print("ok" if not bad else "FAIL")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
