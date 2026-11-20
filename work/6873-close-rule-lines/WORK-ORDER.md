# Work order: lane 6873, close-rule lines (base 431d110)

**Goal.** Five unchanged lines contradict this tree's close rule: `CLAUDE.md` §3 (an operator
close request is the yes to push the session's own non-default branches) and §4 (no handoff
file with board and memory connected). The source copy fixed the same lines first; this lane
brings the reviewed wording here. Board 6873, opened by operator ruling; comment and prose
only, no matcher change.

**Lines at base.**
- `graphs/grill.md:5`: "the handoff lists what remains" (no connector condition).
- `graphs/grill.md:59`: "add a handoff addendum every few rulings" (no connector condition).
- `docs/codex-enforcement.md:141`: `$closeout` "uses the local host disposition and repository
  handoff" (no connector condition).
- `.claude/agents/super-doer.md:65-66`: "Propose-and-stop still governs push: you present, the
  human executes."
- `.claude/hooks/git-guard.py:7-8` (comment): "propose-and-stop (S3) and log-escape's push line
  carry it."

`graphs/grill.md:74` already says `/closeout` writes a handoff file only in its no-connector
fallback, so it is not changed.

**Acceptance check, stated before the build.**
a. `git diff 431d110 <candidate>` touches only the five sites above and this lane's `work/`.
b. `git-guard.py`'s AST is unchanged against base (comment only).
c. `python3 scripts/run_tests.py` passes every suite; `cmp CLAUDE.md AGENTS.md` prints nothing.
d. A case-insensitive `git grep -n -i -E 'the handoff|handoff (file|addendum)|propose-and-stop'`
   outside grills, work, handoffs and vendor leaves no line asking for a handoff file with both
   connectors present, and no propose-and-stop push wording.
e. The diff adds no private repo name, operator name, downstream sha or board id other than
   this lane's own.
f. `senior-engineer` APPROVE on the `.py` comment; `adversarial-reviewer` APPROVE on the prose.

**Files the hub may edit.** The four files above and `work/6873-close-rule-lines/`.
