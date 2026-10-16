#!/usr/bin/env python3
"""Check a prose artifact's line cites, path mentions, section cites, quotes, links and counts
against the tree before it lands; optionally count a phrase across files (--phrase).

Why this exists, measured on 2026-09-07: roughly thirty non-author REFUSE findings in one day,
and nearly all of them were one of four mechanical defects -- a `file:NNN` cite pointing at the
wrong line (the same five numbers wrong in three consecutive revisions, pasted forward each
time), a quotation that was not verbatim in its named source (one fabricated, one with a clause
cut by an ellipsis, one that swapped "kept" for "judged"), a claim of absence that a one-line
command refuted, and a count that was copied forward instead of measured. None of those is a
judgement call. A language model does them unreliably; a script does them exactly.
`scripts/test_graph_pointers.py` already does the link-and-section half, scoped to `graphs/`;
this is the same idea widened to any file and extended to line cites, quotes and counts.

What it checks, per file:

  cites   -- every `path:N` or `path:N-M` in backticks. The file must exist and the line must be
             inside it. The cited line is PRINTED so the author can see whether it says what the
             prose claims; the script cannot judge that and does not try. A bare `:N` resolves
             against the last file mentioned above it in the document.
  quotes  -- every quoted span of QUOTE_MIN_WORDS or more must appear verbatim, after
             normalising whitespace, emphasis marks and quote glyphs, in a file mentioned in the
             same paragraph. Found only in a file mentioned elsewhere in the document -> ANCHOR?.
             Found nowhere -> FAIL. No file mentioned anywhere -> UNANCHORED. Fenced code blocks
             are skipped: they are commands and transcripts, not claims about a source.
  mentions - a backticked path with no line that resolves nowhere -> WARN.
  sections - every `file.md` § Name, plain or as a link, that starts no heading in that file ->
             SECTION? (matcher: scripts/test_graph_pointers.py). A bare § is not checked.
  links   -- every [text](relative-path) must resolve from the file's own directory; the target
             is URL-decoded first and a leading `/` resolves against the repo root.
  counts  -- every bare "<number> lines|commits|files|..." is reported as MEASURED? -- the class
             of number that goes stale on the next edit.
  phrases -- with --phrase "text", counts occurrences across the given files. A correction that
             landed in one place while the retired claim survives elsewhere shows up here as a
             count greater than one.

Exit status is non-zero on any FAIL. Everything else is for the author's eyes.

Path resolution: repo root, the citing file's directory, then the bases this tree habitually
elides (`graphs/`, `roles/`, `.claude/hooks/`, `.claude/agents/`, `scripts/`). A bare filename found nowhere there is searched tree-wide; exactly one hit is used,
several is a FAIL telling the author to qualify the path -- an unqualified name that matches two
files is a cite nobody can follow.

Usage:
  python .claude/skills/cite-check/cite_check.py <file.md> [...] [--phrase "text"] [--quiet]
  python .claude/skills/cite-check/cite_check.py --selftest
"""
import argparse
import functools
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import test_graph_pointers as graph_pointers   # ponytail: one section matcher, owned by that suite

QUOTE_MIN_WORDS = 5
SKIP_DIRS = {".git", "node_modules", "__pycache__", "worktrees"}

# `path:N`, `path:N-M`. Path must contain a dot so `item 12` and `:85` alone are not swallowed.
CITE = re.compile(r"`([\w./\\-]+\.[\w]+):(\d+)(?:[-–](\d+))?`")
BARE_CITE = re.compile(r"`:(\d+)(?:[-–](\d+))?`")
FILE_MENTION = re.compile(r"`([\w./\\-]+\.(?:md|py|ps1|sh|txt|json|yml|yaml|toml|cs|swift|js|mjs|cjs|html|css|sql|Dockerfile|example|gitignore))(?::\d+(?:[-–]\d+)?)?`")
LINK = re.compile(r"\[[^\]]*\]\(([^)\s#]+)(?:#[^)]*)?\)")
LINKED_LABEL = re.compile(r"`[^`\n]*`\]\(([^)\s#]+)")     # [`label.md`](target) -- the target is the file
ITALIC_NAME = re.compile(r"\*([^*\n]+)\*")
# Straight or curly double quotes. Short quotes are matched too (and skipped by the word count
# later) so "kept" for "judged" keeps the pairing in step. Table-cell boundaries are rewritten to
# \x00 before matching so a quote never spans cells, while a `|` inside a prose quote stays legal
# -- excluding `|` outright desynced every later quote in a paragraph (round-2 F5).
QUOTE = re.compile("“([^”\x00]*?)”|\"([^\"\x00]*?)\"")     # curly outer may nest straight inner; "" pairs with itself
TABLE_ROW = re.compile(r"(?m)^[ \t]*\|.*$")
# A straight quote inside an inline code span (a regex class, a JSON fragment, a shell arg) or a
# backslash-escaped one is not a quotation mark; both are rewritten to \x01 before matching and
# restored in the quote text. Code spans may wrap across a line break.
CODE_SPAN = re.compile(r"`[^`]+`")
ESCAPED_QUOTE = re.compile(r'\\"')
ELLIPSIS = re.compile(r"\s*(?:…|\.\.\.)\s*")
SHA = re.compile(r"`?\b([0-9a-f]{7,40})\b`?")
LINE_PREFIX = re.compile(r"(?m)^[ \t]*(?:#+|>+|//)[ \t]?")     # comment and blockquote markers
FENCE = re.compile(r"```.*?```", re.S)
COUNT = re.compile(
    r"\b(\d{1,6})\s+(lines?|commits?|files?|insertions?|deletions?|ahead|behind|branches|refs)\b",
    re.I,
)
PARA_SPLIT = re.compile(r"\n\s*\n")


def norm(text):
    """Collapse whitespace and strip the marks that legitimately differ between prose and source."""
    text = text.replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'")
    text = LINE_PREFIX.sub("", text)
    text = re.sub(r"[*_`]+", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip().lower()


def blank_fences(text):
    """Replace fenced blocks with newlines of equal count so line numbers survive."""
    return FENCE.sub(lambda m: "\n" * m.group(0).count("\n"), text)


@functools.lru_cache(maxsize=None)   # ponytail: one walk per bare name per process; the tree does not change mid-run
def resolve(path_text, citing_file, root):
    """A Path, None, or the string 'ambiguous:<n>'."""
    p = path_text.replace("\\", "/")
    bases = (root, citing_file.parent, root / "graphs", root / "roles",
             root / ".claude" / "hooks", root / ".claude" / "agents", root / "scripts")
    for base in bases:
        cand = (base / p).resolve()
        if cand.is_file():
            return cand
    if "/" in p:
        return None
    hits, _ = find_named(root, p)
    if len(hits) == 1:
        return hits[0]
    return f"ambiguous:{len(hits)}" if hits else None


def find_named(root, name):
    """Tree-wide search for a bare filename. Returns (hits, directories visited) -- the visited
    list is what lets the selftest prove SKIP_DIRS are pruned before descent, not filtered after."""
    hits, visited = [], []
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
        visited.append(Path(d))
        if name in files:
            hits.append(Path(d) / name)
    return hits, visited


def read_lines(p):
    """splitlines(): a newline-terminated file has no phantom empty last line."""
    return p.read_text(encoding="utf-8", errors="replace").splitlines()


def check_file(md, root, findings):
    text = md.read_text(encoding="utf-8", errors="replace")
    prose = blank_fences(text)          # fences are commands and transcripts, not claims
    lines = prose.split("\n")
    rel = md.relative_to(root) if md.is_relative_to(root) else md

    def add(kind, lineno, msg):
        findings.append((kind, rel, lineno, msg))

    # -- cites -------------------------------------------------------------------------------
    # Tokens resolve in document order: a bare `:N` binds to the nearest file mention BEFORE it,
    # so `file.md:9` later on the same line must not capture the bare cites ahead of it.
    last_file = None
    for lineno, line in enumerate(lines, 1):
        tokens = sorted([(m.start(), "mention", m) for m in FILE_MENTION.finditer(line)]
                        + [(m.start(), "bare", m) for m in BARE_CITE.finditer(line)])
        for _, kind, m in tokens:
            if kind == "mention":
                path_text = m.group(1)
                target = resolve(path_text, md, root)
                cm = CITE.fullmatch(m.group(0))
                if cm is None:                                   # plain mention, no line
                    # a dead or ambiguous mention must not leave the earlier file current for bare cites
                    last_file = target if isinstance(target, Path) else None
                    if target is None and not graph_pointers.PLACEHOLDER.search(path_text):
                        # A dead pointer used to pass silently here
                        add("WARN", lineno, f"mention `{path_text}` -- file not found")
                    continue
                a, b = int(cm.group(2)), cm.group(3)
                if not isinstance(target, Path):
                    last_file = None        # bare cites after a dead cite must not inherit the earlier file
                    why = f"{target.split(':')[1]} files match; qualify the path" if target else "file not found"
                    add("FAIL", lineno, f"cite `{path_text}:{a}` -- {why}")
                    continue
                last_file = target
                label = path_text
            else:
                a, b = int(m.group(1)), m.group(2)
                if last_file is None:
                    add("WARN", lineno, f"bare `:{a}` with no file mentioned before it")
                    continue
                target, label = last_file, last_file.name
            tlines = read_lines(target)
            b = int(b) if b else a
            span = f"{a}" if b == a else f"{a}-{b}"
            if b < a:
                add("FAIL", lineno, f"cite `{label}:{span}` -- inverted range")
                continue
            if a < 1 or b > len(tlines):
                add("FAIL", lineno, f"cite `{label}:{span}` -- file has {len(tlines)} lines")
                continue
            add("CITE", lineno, f"`{label}:{span}` -> {tlines[a - 1].strip()[:110]}")

    # -- sections ------------------------------------------------------------------
    # `file.md` § Name, plain or as a link. Matcher shared with test_graph_pointers.py. A review
    # row, not a FAIL: neither end of a § cite is delimited in prose, and measured over this tree
    # 2 of 3 sampled mismatches were real headings ("## STATUS, 2026-09-22" cited as "§ STATUS
    # records that"). Each mention starts its own segment, so a second § on a line is checked; a
    # link's target, not its label, names the file. An italic *Name* equal to a heading passes
    # before the shared matcher's uniqueness guard can reject it for a longer sibling heading.
    # A dead file is the mention pass's WARN. A bare § (file from the sentence) is not checked.
    for lineno, line in enumerate(lines, 1):
        starts = [m.start() for m in FILE_MENTION.finditer(line)] + [len(line)]
        for s, e in zip(starts, starts[1:]):
            sm = graph_pointers.SECTION.match(line, s, e)
            if not sm:
                continue
            ref, tail = sm.groups()
            lm = LINKED_LABEL.match(line, s, e)
            target = (md.parent / unquote(lm.group(1))).resolve() if lm else resolve(ref, md, root)
            if isinstance(target, str):
                add("WARN", lineno, f"section cite into `{ref}` -- {target.split(':')[1]} files match; qualify the path")
                continue
            if not (isinstance(target, Path) and target.is_file()):
                continue
            it = ITALIC_NAME.match(tail.strip())
            hs = graph_pointers.headings(target)
            if it and hs and graph_pointers.words(it.group(1)) in hs:
                continue
            if graph_pointers.names_a_section(tail, target) is False:
                add("SECTION?", lineno, f"`{ref}` § {' '.join(tail.split()[:4])} -- no heading starts this way")

    # -- links -------------------------------------------------------------------------------
    for lineno, line in enumerate(lines, 1):
        for m in LINK.finditer(line):
            target = m.group(1)
            if "://" in target or target.startswith("mailto:"):
                continue
            # %20 and friends are how a path with a space is written in a link; a leading `/`
            # is repo-root-relative, not filesystem-root-relative. A literal `%` in a real
            # filename must still resolve, so the target is tried as written first.
            def dest(t):
                return (root / t.lstrip("/")) if t.startswith("/") else (md.parent / t)
            if not (dest(target).exists() or dest(unquote(target)).exists()):
                add("FAIL", lineno, f"link ({target}) does not resolve")

    # -- quotes, per paragraph ---------------------------------------------------------------
    doc_files = {}
    for x in FILE_MENTION.findall(prose):
        t = resolve(x, md, root)
        if isinstance(t, Path):
            doc_files[t] = None
    bodies = {}

    def body(p):
        """Normalised text of a file, or of a commit message when `p` is a sha."""
        if p not in bodies:
            if isinstance(p, Path):
                bodies[p] = norm(p.read_text(encoding="utf-8", errors="replace"))
            else:
                r = subprocess.run(["git", "-C", str(root), "log", "-1", "--format=%B", p],
                                   capture_output=True, text=True, encoding="utf-8", errors="replace")
                bodies[p] = norm(r.stdout) if r.returncode == 0 else ""
        return bodies[p]

    def is_sha(s):
        return not re.fullmatch(r"\d+", s) and body(s) != ""

    bounds, pos = [], 0
    for sep in PARA_SPLIT.finditer(prose):
        bounds.append((pos, sep.start())); pos = sep.end()
    bounds.append((pos, len(prose)))
    for start, end in bounds:
        para = prose[start:end]
        para_line = prose[:start].count("\n") + 1
        mentions = [resolve(x, md, root) for x in FILE_MENTION.findall(para)]
        mentions = [x for x in mentions if isinstance(x, Path)]
        mentions += [s for s in SHA.findall(para) if is_sha(s)]    # a commit message is a source too
        cells = TABLE_ROW.sub(lambda m: m.group(0).replace("|", "\x00"), para)   # same length as para
        cells = CODE_SPAN.sub(lambda m: m.group(0).replace('"', "\x01"), cells)  # still same length
        cells = ESCAPED_QUOTE.sub("\\\x01", cells)                                 # \" -> \ + sentinel
        pos = 0
        while (q := QUOTE.search(cells, pos)) is not None:
            pos = q.end()
            quote = (q.group(1) if q.group(1) is not None else q.group(2)).replace("\x01", '"')
            qline = para_line + cells[:q.start()].count("\n")
            # A closing straight quote followed directly by a LETTER means the pairing is off --
            # an inner straight quote inside a straight-quoted span. The span cannot be checked,
            # and a fabricated clause could hide in the pieces, so this fails rather than warns.
            # A digit after the quote is a footnote mark, not a pairing break (round-2 F5).
            # RESYNC: the "closing" quote was really an opener, so the next search starts on it;
            # one stray quote costs one report, not every quote after it in the paragraph (round-3 F8).
            nxt = cells[q.end():q.end() + 1]
            if q.group(2) is not None and nxt.isalpha():
                add("FAIL", qline, f'quote pairing broken at "{quote[:40]}" -- inner straight quote? use curly outer quotes')
                pos = q.end() - 1
                continue
            if len(quote.split()) < QUOTE_MIN_WORDS:
                continue
            # An elided quote is checked fragment by fragment; each fragment must be verbatim.
            # All fragments one word -> nothing to check, and all([]) passed every such quote
            # vacuously. Fall back to the whole quote: an unverifiable elision fails honestly.
            frags = [norm(f) for f in ELLIPSIS.split(quote) if len(f.split()) >= 2] or [norm(quote)]
            found_in = lambda p: all(f in body(p) for f in frags)
            if any(found_in(src) for src in mentions):
                continue
            elsewhere = [p.name for p in doc_files if p not in mentions and found_in(p)]
            if elsewhere:
                add("ANCHOR?", qline, f'"{quote[:70]}" -- verbatim in {", ".join(elsewhere)}, not named in this paragraph')
            elif not mentions and not doc_files:
                add("UNANCHORED", qline, f'"{quote[:70]}..." -- no file named in document')
            else:
                names = ", ".join(x.name if isinstance(x, Path) else x[:7] for x in mentions) or "any file this document names"
                # How far does it match before diverging? Points at a wrong word or an inner quote.
                words, best, where = frags[-1].split() if frags else [], 0, ""
                for src in list(mentions) + [p for p in doc_files if p not in mentions]:
                    k = next((i for i in range(len(words), 0, -1) if " ".join(words[:i]) in body(src)), 0)
                    if k > best:
                        best, where = k, (src.name if isinstance(src, Path) else src[:7])
                hint = (f"  (last fragment: first {best} of {len(words)} words match in {where})"
                        if 0 < best < len(words) else "")
                add("FAIL", qline, f'quote not verbatim in [{names}]: "{quote[:90]}"{hint}')

    # -- counts ------------------------------------------------------------------------------
    for lineno, line in enumerate(lines, 1):
        for m in COUNT.finditer(line):
            add("MEASURED?", lineno, m.group(0))


def check_phrase(files, phrase, findings):
    n = 0
    for md in files:
        c = norm(md.read_text(encoding="utf-8", errors="replace")).count(norm(phrase))
        if c:
            findings.append(("PHRASE", md.name, 0, f'{c}x "{phrase[:60]}"'))
        n += c
    findings.append(("PHRASE", "total", 0,
                     f'{n}x "{phrase[:60]}"' + ("  <- appears in more than one place" if n > 1 else "")))


def selftest():
    """One runnable check: each defect class present once, each non-defect absent."""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "src.md").write_text("alpha\nbeta gamma delta epsilon zeta eta\ntheta\n"
                                     "pipe | inside a quote is fine\n", encoding="utf-8")
        (root / "a").mkdir(); (root / "b").mkdir()
        (root / "a" / "dup.md").write_text("x\n", encoding="utf-8")
        (root / "b" / "dup.md").write_text("x\n", encoding="utf-8")
        (root / "a" / "only.md").write_text("one\ntwo\nthree\nfour\n", encoding="utf-8")
        (root / "spaced name.md").write_text("s\n", encoding="utf-8")
        (root / "50%20off.md").write_text("literal percent\n", encoding="utf-8")
        (root / "worktrees").mkdir()
        (root / "worktrees" / "hidden.md").write_text("h\n", encoding="utf-8")     # pruned dir
        doc = root / "doc.md"
        doc.write_text(
            "See `src.md:2` and `src.md:9` and `nope.md:1` and `dup.md:1` and `only.md:4`.\n\n"
            "Edge cites: `src.md:5` (phantom trailing line) and `src.md:3-1` (inverted).\n\n"
            "Nested: `src.md` says \"beta gamma delta \"epsilon\" FORGED zeta eta\" here.\n\n"
            "Pruned: `hidden.md:1` must not resolve through worktrees/.\n\n"
            "Footnote: `src.md` says \"beta gamma delta epsilon zeta eta\"2 and that is fine.\n\n"
            "| `src.md` | \"beta gamma delta epsilon zeta eta\" | \"beta gamma delta epsilon CELLFAKE eta\" |\n\n"
            "Prose pipe: `src.md` has \"pipe | inside a quote is fine\" and then \"beta gamma delta epsilon PIPEFAKE eta\".\n\n"
            "Code: `re.compile(\"[a-z]\")` then `src.md` says \"beta gamma delta epsilon CODEFAKE eta\" ok.\n\n"
            "Stray: `src.md` wrote \"oops unclosed here and then \"beta gamma delta epsilon zeta eta\" and \"beta gamma delta epsilon RESYNCFAKE eta\" after.\n\n"
            "Escaped: `src.md` has \"beta gamma delta epsilon ESCFAKE eta\" near a \\\"quoted\\\" arg and `x\n\"y\"` too.\n\n"
            "`src.md` says *\"beta gamma delta epsilon zeta eta\"* and also \"beta gamma delta epsilon FAKE eta\".\n\n"
            "Mention `only.md` then bare `:3` and `:7`.\n\n"
            "Elsewhere: \"beta gamma delta epsilon zeta eta\" with no file here.\n\n"
            "```\n\"quoted text inside a fence is skipped\" `:99`\n```\n\n"
            "| cell \"one two | three four five six\" |\n\n"
            "Vacuous: `src.md` says \"beta \u2026 gamma \u2026 delta \u2026 VACUOUS \u2026 zeta\" here.\n\n"
            "[ok](src.md) [bad](missing.md) [enc](spaced%20name.md) [lit](50%20off.md) [abs](/a/only.md) and 12 lines of it.\n",
            encoding="utf-8",
        )
        f = []
        check_file(doc, root, f)
        kinds = [(k, m) for k, _, _, m in f]
        has = lambda k, s: any(k == kk and s in m for kk, m in kinds)
        assert has("CITE", "beta gamma"), kinds
        assert has("FAIL", "src.md:9"), kinds
        assert has("FAIL", "nope.md"), kinds
        assert has("FAIL", "src.md:5") and has("FAIL", "file has 4 lines"), kinds   # no phantom line
        assert has("FAIL", "inverted range"), kinds
        assert has("FAIL", "pairing broken"), kinds
        assert sum(1 for k, m in kinds if k == "FAIL" and "pairing broken" in m) == 2, kinds   # nested + stray; footnote digit is not one
        assert has("FAIL", "RESYNCFAKE"), kinds          # pairing resynced after the stray quote
        assert has("FAIL", "ESCFAKE"), kinds             # \" escapes and a wrapped code span do not desync
        assert has("FAIL", "hidden.md") and has("FAIL", "file not found"), kinds             # SKIP_DIRS pruned
        assert has("FAIL", "CELLFAKE"), kinds                                                 # cells checked separately
        assert not any("zeta eta\" | \"" in m for _, m in kinds), kinds                       # and never joined
        assert has("FAIL", "PIPEFAKE"), kinds            # a `|` in a prose quote does not desync the next quote
        assert has("FAIL", "CODEFAKE"), kinds            # a `"` inside inline code does not desync either
        hits, visited = find_named(root, "hidden.md")
        # Judge parts relative to the fixture root -- a TEMP under any `worktrees/`
        # ancestor (every lane worktree) put that ancestor in every absolute path visited.
        rels = [v.relative_to(root) for v in visited]
        assert {Path("."), Path("a"), Path("b")} <= set(rels), visited                      # the walk ran
        assert hits == [] and not any("worktrees" in r.parts for r in rels), visited         # pruned, not filtered
        # line numbers: the fixture's table row and the pairing line each report their own line
        src_lines = doc.read_text(encoding="utf-8").split("\n")
        for k, _, ln, m in f:
            if "CELLFAKE" in m or "FORGED" in m:
                assert "CELLFAKE" in src_lines[ln - 1] or "FORGED" in src_lines[ln - 1], (ln, m)
        assert has("FAIL", "dup.md:1") and has("FAIL", "qualify"), kinds
        assert has("CITE", "only.md:4") and has("CITE", "only.md:3"), kinds        # rglob + bare after mention
        assert has("FAIL", "only.md:7"), kinds
        assert not has("CITE", ":99") and not has("FAIL", ":99"), kinds            # fence skipped
        assert has("FAIL", "FAKE"), kinds
        assert not any(k == "FAIL" and "zeta eta\"" in m and "FAKE" not in m for k, m in kinds), kinds
        assert has("ANCHOR?", "beta gamma"), kinds
        assert not has("FAIL", "inside a fence"), kinds
        assert not any("three four five" in m for _, m in kinds), kinds           # table cell not a quote
        assert has("FAIL", "VACUOUS"), kinds                # all-one-word fragments do not pass on all([])
        assert has("FAIL", "missing.md"), kinds
        assert not has("FAIL", "spaced%20name.md"), kinds   # URL-decoded before the existence check
        assert not has("FAIL", "50%20off.md"), kinds        # a literal % in a real filename still resolves
        assert not has("FAIL", "/a/only.md"), kinds         # leading / is repo-root-relative
        assert has("MEASURED?", "12 lines"), kinds
        f2 = []
        check_phrase([doc], "beta gamma delta", f2)
        assert f2[-1][3].startswith("12x"), f2     # 9 + two on the stray line + one on the escaped line
        # Code files, .sql/.Dockerfile/.example and a path-qualified .gitignore are
        # mentions too. A cite past EOF must FAIL for every one (it was silently uncounted), and a
        # quote sourced only from a .cs file resolves. The list is written out, not read from
        # FILE_MENTION, so dropping any extension there fails here.
        exts = ("cs", "swift", "js", "mjs", "cjs", "html", "css", "sql", "Dockerfile", "example")
        for e in exts:
            (root / f"probe.{e}").write_text("public void Run() { return; }\nint b;\n", encoding="utf-8")
        (root / "sub").mkdir(); (root / "sub" / ".gitignore").write_text("tmp/\n", encoding="utf-8")
        doc2 = root / "doc2.md"
        doc2.write_text(" ".join(f"`probe.{e}:2` `probe.{e}:9`" for e in exts)
                        + " `sub/.gitignore:1` `sub/.gitignore:5`.\n\n"
                        "`probe.cs` says \"public void Run() { return; }\" and \"public void WALKFAKE() { return; }\".\n",
                        encoding="utf-8")
        f3 = []
        check_file(doc2, root, f3)
        k3 = [(k, m) for k, _, _, m in f3]
        for p in [f"probe.{e}" for e in exts] + ["sub/.gitignore"]:
            last = 5 if p.endswith(".gitignore") else 9
            assert any(k == "CITE" and f"{p}:" in m for k, m in k3), (p, k3)
            assert any(k == "FAIL" and f"{p}:{last}" in m for k, m in k3), (p, k3)
        assert any(k == "FAIL" and "WALKFAKE" in m for k, m in k3), k3
        assert not any(k == "FAIL" and "Run()" in m for k, m in k3), k3
        # A dead plain mention WARNs; a § cite that starts no heading (hash or bold
        # lead-in) is a SECTION? row. One case per line, so no case can hide behind another.
        (root / "runbook.md").write_text("# Runbook\n\n## The contract\n\n## What closeout is\n\n"
                                         "## What closeout is not\n\n**Not a delegate.** x\n", encoding="utf-8")
        (root / "c").mkdir(); (root / "d").mkdir()
        (root / "c" / "guide.md").write_text("## Setup\n", encoding="utf-8")
        (root / "d" / "guide.md").write_text("## Other\n", encoding="utf-8")
        doc3 = root / "doc3.md"
        doc3.write_text("Gone: `ghost.md` and `a/ghost.py`; placeholder `.agent-log/YYYY-MM-DD.md`.\n\n"
                        "`runbook.md` then `ghost2.md` then `:1` binds to nothing.\n\n"
                        "`runbook.md` § *The contract* is plain.\n\n"
                        "[`guide.md`](c/guide.md) § *Setup* is pinned by its link target.\n\n"
                        "[`guide.md`](c/guide.md) § *Gone* is a renamed heading, link form.\n\n"
                        "`runbook.md` § *Not a delegate* is a bold lead-in.\n\n"
                        "`runbook.md` § *What closeout is* has a longer sibling heading.\n\n"
                        "`runbook.md` § *The contract* and `runbook.md` § *The agreement* share a line.\n\n"
                        "`guide.md` § *Setup* is ambiguous.\n", encoding="utf-8")
        f4 = []
        check_file(doc3, root, f4)
        k4 = [(k, m) for k, _, _, m in f4]
        assert ("WARN", "mention `ghost.md` -- file not found") in k4, k4
        assert ("WARN", "mention `a/ghost.py` -- file not found") in k4, k4
        assert not any("YYYY" in m for _, m in k4), k4                                 # placeholder skipped
        assert any(k == "WARN" and "bare `:1`" in m for k, m in k4), k4                 # dead mention reset last_file
        assert not any(k == "CITE" and "runbook.md:1" in m for k, m in k4), k4
        sec = [m for k, m in k4 if k == "SECTION?"]
        assert len(sec) == 2 and "The agreement" in sec[1], k4                          # second § on a line checked
        assert "guide.md" in sec[0] and "Gone" in sec[0], k4                            # link form checked, not just parsed
        amb = [m for k, m in k4 if k == "WARN" and "guide.md" in m]
        assert len(amb) == 1 and "qualify" in amb[0], k4                                # link target pins the file
    print("selftest OK")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("files", nargs="*")
    ap.add_argument("--phrase", action="append", default=[])
    ap.add_argument("--root", default=None)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--quiet", action="store_true", help="suppress CITE and MEASURED? rows")
    a = ap.parse_args()
    if a.selftest:
        selftest()
        return 0
    if not a.files:
        ap.error("no files")
    root = Path(a.root).resolve() if a.root else Path(__file__).resolve().parents[3]
    files = [Path(x).resolve() for x in a.files]
    findings = []
    for md in files:
        if not md.is_file():
            findings.append(("FAIL", md, 0, "file not found"))
            continue
        check_file(md, root, findings)
    for ph in a.phrase:
        check_phrase([x for x in files if x.is_file()], ph, findings)

    fails = 0
    for kind, f, ln, msg in findings:
        if a.quiet and kind in ("CITE", "MEASURED?"):
            continue
        fails += kind == "FAIL"
        loc = f"{f}:{ln}" if ln else str(f)
        print(f"{kind:10} {loc}  {msg}")
    keys = ("FAIL", "WARN", "ANCHOR?", "UNANCHORED", "MEASURED?", "SECTION?", "CITE")
    n = {k: sum(1 for x in findings if x[0] == k) for k in keys}
    print("-- " + ", ".join(f"{n[k]} {k}" for k in keys[:-1]) + f", {n['CITE']} cites exist (content unchecked)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
