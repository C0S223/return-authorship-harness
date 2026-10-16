# Report: lane 6177, swing 4 (candidate 36b9aea, base a35cc51)

**Authority.** Operator, after SE round 2 hit the cap with F3 open: "One more round
(Recommended)". This grants senior-engineer round 3 for F3 only.

**What changed (DID-SWING4.md, checked against the diff).**
- `tests/test_log_escape.py` only. The nine F3 lines are now must-not-match lookalikes,
  28 in all.
- Four rows are narrower: negative length, negative index, quoted-span blanking for `;&`,
  `|&` and `&>>`, and the shopt option position.
- Two must-catch spellings were added, for 67 in all.
- `a35cc51..36b9aea`: tests/test_log_escape.py and DID-SWING4.md. Hooks and SETUP.md are
  untouched.

**Hub reruns at 36b9aea.**
- Tree clean.
- `run_tests.py`: "38 suites: 38 pass, 0 fail, 0 skip".
- Scrub on the tree and history: clean.

**Builder's added residuals.** These are left unflagged because only a parser could tell
them apart:
- a `;&`, `|&` or `&>>` that the quote blanker hides (an escaped quote, or a quote that spans
  lines);
- a negative index inside `$(( ))` or a quoted `unset`;
- a quoted shopt name.
