# Report: lane 6855, swing 1 (super-doer, mid/sonnet), filed by the hub

Candidate 1e4c2d0 on base 541929d (work order e01d58f). Two builder commits: d60fddb (the
port, 43 files plus DID.md; 42 once the fixup reverted `.gitignore`) and 1e4c2d0 (a pre-review fixup the hub asked for). Builder detail
and red/green lines: `DID.md` in this desk.

**Hub verification, before freeze.** `git status --porcelain` empty; base-to-candidate paths
are the work order's list plus this desk; `CLAUDE.md`/`AGENTS.md` change only by the close
rule's two sentences (§3 close-request push, §4 audit copy) and `cmp` is silent;
`python3 scripts/run_tests.py` gives `44 suites: 44 pass, 0 fail, 0 skip (20 tests skipped inside 6 passing suites)`.

**Hub-found issues, repaired in 1e4c2d0 (hub request, builder's edit).** (1) `.gitignore`
had gained a line the operator ruled instance-only; reverted to base, and the one test that
pinned it was removed. (2) Test fixtures carried real session ids from the source copy;
replaced with synthetic ids of the same shape. (3) About ten added comment and prose lines
quoted dated operator rulings that have no record in this tree; reasons kept, dates and
quotes dropped. The leak pattern the hub first gave the builder missed (2) and (3).

**Leak checks on the candidate (check b).** Name pattern 0 hits; dated-ruling cite grep 0;
8-hex and uuid scan leaves only a synthetic fixture id and this tree's own `CLAUDE.md` blob pin.

**Hub follow-up 8430e0c (grant widened by the operator).** The new close rule left
`.claude/skills/closeout/SKILL.md` stale (audit copy "at this turn's end", push on a separate
yes). The source copy's own patch for that skill, made with the close rule, applied verbatim;
suite still 44/44. The Codex closeout port (`.agents/skills/closeout/SKILL.md`) stays as is:
it never pushes, which is narrower and allowed.

**For the reviewers.** Adaptations where a taken hunk met one not taken are listed in
`DID.md`. A `GITIGNORE` constant in `tests/test_session_close.py` is now unused (from fix 1).
Falsifier for the prose part, which admits no failing test: the adversarial review.
