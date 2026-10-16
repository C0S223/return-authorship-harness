# ADR 0001: Park the text-classifying guard layer

Status: Accepted, by operator ruling on 2026-10-15 ("Park it, revert F28"; ADR and binding:
"First lane after merge", "Yes, with the ADR"; scope, every text-classifying gate, not
only the origin-ref rows: "Whole layer"; lane: "Go"). The rulings are in that day's action log.
Decided by: the operator. The hub drafted the text: the order of the shapes and the
exceptions other than the FC-8 test are the hub's defaults, accepted by the operator's merge.
Precedent: the operator's earlier tree made the same decision in its ADR 0009. It is cited
for the idea only and does not govern here.

## Context

Several gates here decide by reading a shell command's text before it runs. Examples:
`git-guard.py`'s push and origin-ref rows, `policy-mutate.py`, `shell-scope.py` and
`net-post.py`. A text classifier has two failure modes, and they trade against each other:

- **False positive:** text that only mentions a target reads as performing it.
- **False negative:** the same act spelled another way is not seen. The shell and git offer
  endless spellings: option clusters, abbreviated long options, globs, brace lists, escapes,
  aliases, redirects, variables, operands fed through `xargs`.

Narrowing the matcher makes the second worse. Widening it makes the first worse. Each patch
is justified on its own, and the series does not converge.

Incident, build-1, 2026-10-15. Details are in `handoffs/2026-10-16-finish.md` section 8 and
the grills it cites.
- F21 widened the origin-ref rows to close three bypasses (SE-1).
- The final review found that the widening over-denied (FC-1: a `-m` message that names
  origin).
- F28 narrowed the rows. The re-review found that the narrowing let four origin-ref writes
  through (FC-2 to FC-5), and that abbreviated `--del` and `--std` had passed since F21 (FC-6).
- F28 was reverted. In the review of the revert, the live git-guard denied the reviewer's own
  scratch file of test cases, because a glob in the case text read as an origin-ref write.
- The last round, at the parked state, found one more spelling: operands supplied through
  `xargs` pass both origin-ref rows (FC-7, `grills/2026-10-16-last-code.md`). It also found
  that no test fails if F21's unescape-and-fold is removed (FC-8).
- Net: four review rounds after F21. Three found a new gap. In the other one, a false deny
  stopped the code reviewer. The matcher ended where it was before F28 (byte-identical to
  3d2fad5).

## Decision

1. **Stop the repair programme for text-classifying gates.** The hooks keep running
   unchanged. Nothing is disarmed.
2. **Park a new gap; don't patch it.** Record it as a residual: what passes, what it reaches,
   and what compensates. Then leave it.
3. **Repairing another matcher is not unparking.** It resumes the programme this ADR ends.
   Unparking a gap takes a change in the kind of control, ruled by the operator.
4. **Three replacement shapes, in order of preference:**
   - **Gate at the effect:** the server or OS refuses the act whatever its spelling. Example:
     a GitHub ruleset on `main` refuses a direct push. Agents are denied ruleset writes, so the
     operator sets it.
   - **Detect deterministically:** compare bytes or refs against a known baseline, with no
     false positives. Examples: `policy-integrity.py`'s session-start baseline, CI's
     `ci_policy_check` on the PR diff, and gates that read the default branch from a committed
     file instead of the local `refs/remotes/origin/HEAD`.
   - **Contain:** bound what a missed act can reach. Examples: disposable containers and
     scoped tokens.
5. **Exceptions:**
   - A fail-closed change that alters no pattern is allowed. Example: denying when the gate's
     own code raises.
   - A test that pins behaviour the gate already has is allowed, because it changes no
     pattern. Example: this change adds two FC-8 rows, one each for the unescape and the
     fold. A test that stays red until the matcher changes is a repair.
   - A matcher stopgap needs an operator ruling that names it, its cost, and the control that
     retires it.

## Consequences

- **"Parked" does not mean safe.** The finish report lists the parked residuals in section 8:
  - FC-1 fails closed.
  - FC-6 fails open: `update-ref --std` passes stdin updates to origin's refs through the
    rows.
  - This ADR also parks FC-7, which fails open: operands supplied through `xargs` retarget
    `origin/HEAD` or move `origin/main`.
- Either fail-open gap can make the push gates read the wrong default branch. Only the `main`
  ruleset covers that, by refusing a direct push to `main`, and only for identities it does
  not exempt (`docs/enforcement/CLAUDE.md:19`). The operator reported it set on 2026-10-15,
  with the admin role on its bypass list. So an admin push bypasses it, and an agent's push
  does too if the shared login it acts with holds admin (`.claude/hooks/git-guard.py:193`).
- Reviewers file a gap the base revision already has as a residual, not as a finding that
  blocks a merge. A change that allows what its base denied is a regression and still blocks.
- For parked classes, the protection is still a human being present. Unattended work stays
  denied (root `CLAUDE.md` §2).
- Follow-up lane: the gates stop trusting the local `origin/HEAD`.

## Binding

Same change, as a policy edit to `docs/enforcement/CLAUDE.md` under "Enforcement changes":

> **Text matchers are parked:** hook editors and reviewers record a new gap as a residual, never a pattern patch (fixes trade false denies for bypasses); see `docs/adr/0001-park-text-classifying-guards.md`.

The contract's byte budget (`scripts/test_claude_md_budget.py`) had 20 bytes free. The operator
answered "Look to condense the contract to find room" rather than raise the ceiling. So the
same edit tightens that file without changing its meaning or its line count:
- It drops its opening pointer to Roster maintenance, which root `CLAUDE.md` §2 already gives
  ("Before changing bindings, read roster maintenance").
- It states the setup's shared `APPROVED_ORIGIN_URL` step once instead of per target.
- It shortens the grant-expiry sentence.
