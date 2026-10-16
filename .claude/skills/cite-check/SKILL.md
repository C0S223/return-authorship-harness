---
name: cite-check
description: Lint a prose artifact's line cites, path mentions, section cites, quotations, links and counts against the tree before it lands or goes to review. Use before committing any desk file, grill, ruling, ADR or handoff that cites `path:N`, quotes a file, or states a count; use again after every repair round. Invoke as /cite-check <file> [<file> ...].
---

# cite-check

**The tool is `cite_check.py` in this directory.** Run it, read every line it prints, fix the
artifact, run it again. It exits non-zero on any FAIL.

```bash
python .claude/skills/cite-check/cite_check.py <file.md> [<file.md> ...] [--quiet] [--phrase "text"] [--root <checkout>]
```

`--root` defaults to the tree this skill lives in; pass the worktree when linting a branch so
cites resolve against that checkout. `--quiet` hides the resolved-cite and MEASURED? rows.
`--selftest` is the tool's own check and must pass before the tool is trusted.

## What each row means

| Row | Meaning | What to do |
|---|---|---|
| `CITE` | The cite resolved; the cited line is printed after `->`. | **Read it.** The tool proves the line exists, not that it says what your prose claims. |
| `FAIL cite … file has N lines` | Line number past the end of the file. | Re-derive with `grep -n` **at the revision you are writing into**. |
| `FAIL cite … files match; qualify the path` | A bare filename matches several files tree-wide. | Write the path from the repo root. |
| `WARN mention … file not found` | A backticked path with no `:N` resolves nowhere. | Fix the path, or say plainly the file does not exist yet. |
| `WARN bare … with no file mentioned before it` | A bare `` `:N` `` with no live file above it (a dead or ambiguous mention resets it). | Name the file in the cite. |
| `WARN section cite into … qualify the path` | A § cite's filename matches several files. | Write the path, or link it: a link's target names the file. |
| `SECTION?` | `` `<file>.md` § Name `` (plain or as a link) starts no heading or bold lead-in in that file. | Open the target's headings: renamed means fix it; a heading whose words continue past the name (a date, a qualifier) is fine. A bare § that takes its file from the sentence is not checked. |
| `FAIL quote not verbatim in [...]` | No file named in that paragraph contains the quote. | Fix the quote, or name the actual source in the same paragraph. |
| `ANCHOR?` | Verbatim in a file this document names elsewhere, not in that paragraph. | Usually fine when the file is the document's subject; otherwise name it locally. |
| `UNANCHORED` | A quote in a document that names no file at all. | Name a source or use single quotes. |
| `MEASURED?` | A bare `N lines / commits / files / …`. | Either delete the number or state the revision it was measured at. |
| `PHRASE` | `--phrase` occurrence count across the given files. | `> 1` after a correction means the retired claim survives somewhere. |

## Conventions the tool assumes — write to them

- **Double quotes mean verbatim from a file in the tree or from a commit message.** The tool
  checks every double-quoted span of five or more words against the files (and 7+-hex shas)
  named in the same paragraph. Operator speech, board text, harness messages and your own
  earlier drafts go in **single quotes** — the tool skips those.
- **A quote with an inner quotation uses curly outer quotes** (`“ … "inner" … ”`). Straight
  inside straight breaks the pairing; the tool reports `quote pairing broken` as a FAIL when a
  closing straight quote is followed directly by a letter. A digit after a quote (a footnote mark) is
  not flagged.
- **Table cells are matched separately**; a quote never spans a `|` cell boundary. A `|` inside
  a prose quote is fine.
- **Elided quotes are fine**: `…` or `...` splits the quote and each fragment of two words or
  more is checked. A quote elided down to single words leaves nothing checkable, so it is
  matched whole — with the ellipsis in it — and fails: write one fragment out in full.
- **A bare `` `:N` `` binds to the nearest file mentioned before it**, on any earlier line.
- **Fenced code blocks are skipped entirely** — commands and transcripts, not claims.
- **`#`, `>` and `//` line prefixes are stripped from sources**, so a quote from a hook's
  comment block or a blockquote matches.
- **The tool lints the checkout, not the merge result.** A cite into a file that exists on
  the default branch but not on the lane branch reads `file not found`; verify it there with
  `git show origin/<default>:<path>` and leave it.

## What it cannot judge

Whether the printed line supports the sentence. Whether a self-quote of an earlier revision is
worth keeping (the mechanical test: keep an erratum only where the wrong claim escaped into another
artifact). Whether a count is stale — only that it exists. Those are the
reviewer's, still.
