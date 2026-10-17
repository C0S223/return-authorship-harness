# ONBOARDING.md: a short tour after setup

**Reader: the agent.** Start this whenever the person says **onboard me**, at any time,
even after they have taken or skipped the tour before. A new session also offers it, in one
session-start line, only when all three hold: the push guard is armed (`APPROVED_ORIGIN_URL`
in `.githooks/pre-push` is no longer the `OWNER/REPO` placeholder), `.agent-log/onboarded`
does not exist, and the session is not a cloud session (managed cloud or a self-hosted
runner). A cloud session never shows that line, but **onboard me** works there too. If setup is not finished, say so and offer
`SETUP.md` instead.

**Ending or skipping.** At the end of step 7, or as soon as they say **skip** at any point,
create the empty file `.agent-log/onboarded` (and the folder, if it is missing), and tell them plainly: it only stops the
offer at the start of new sessions; it lives in a folder Git ignores, so nothing is
committed; and saying **onboard me** still starts the tour.

**How to run it.** One step per turn, one idea per message, in plain words. End each step
with a plain question and wait for the reply. Put each step's text in your last message,
after your final tool call: the desktop app folds away text written between tool calls
(`SETUP.md` says the same). This tour adds no rule. It points to the files that hold the
rules; where it seems to disagree with `CLAUDE.md` or a graph file, those win, and you say so.

## 1. What this is for

Say, in two sentences: this repository keeps them in charge of AI coding agents, with a
written rulebook (`CLAUDE.md`), safety checks that stop risky actions, and a review before
any change lands. It is mostly a control layer: from here the agent starts work sessions in
their other repositories, and this one changes rarely, each change needing their named
approval (`CLAUDE.md`, Purpose).

Ask: "Shall I show you how we make decisions together?"

## 2. The grill: deciding (`graphs/grill.md`)

Explain: when there are decisions to make, the agent asks **one question at a time**, each
as a small pop-out with two to four choices. They rule; the agent carries out each ruling
before the next question. The choice marked **(Recommended)** is the agent's own pick,
listed first. It is a suggestion, never a go: nothing happens until they choose, and nothing
is pushed unless the choice they picked says so. For a design question the agent may ask
for their own words first, with no choices offered.

Ask: "Any questions, or shall I show you how building works?"

## 3. The lane: building (`graphs/lane.md`)

Explain: when they approve a build, the agent makes a separate copy of the repository on a
branch named `lane-<number>` and writes a one-screen **work order** under
`work/<number>-<name>/`: the goal, the check that decides it is done, the only files
that may change, and a guess at how long a person would take, which helps pick the model.
A **builder** agent (`super-doer`) does the work and commits just those
files. Then a different agent reviews it, **by kind**: code goes to `senior-engineer`, which
runs the tests; writing that an agent will read later, or that goes public, goes to
`adversarial-reviewer`. Each saves its review under `grills/`; an approving review is a
**stamp** tied to the exact version it read (`scripts/stamp_check.py`).

Ask: "Does that make sense so far?"

## 4. The lane: landing

Explain: before it asks GitHub to take the change, the agent runs the same three checks
GitHub will run (`ci_policy_check`, `stamp_check`, `run_tests`; `graphs/lane.md` step 4).
It then opens a **draft** pull request: a proposed change, not yet merged. Who merges:

- No policy file changed and both checks green: the agent marks it ready and it merges itself.
- A policy file changed (the rulebook, `README.md`, the safety checks; full list in
  `docs/enforcement/CLAUDE.md`, Policy paths): the push and the pull request each need
  their yes, and **they** merge it on GitHub.

Ask: "Shall I say a word about which AI models do the work?"

## 5. Which models do the work

Explain: the session they are talking to now is the **hub**. It runs the grill and the lane
and hands work to helper agents. Run it on a mid-range, reasonably strong model at medium
effort, one good at coordinating work. They need not pick the helpers' models (a model they name for a job wins): the lane does,
starting builders on the lightest model that fits, running each reviewer one level above its
builder, and moving up a level when a review fails. The strongest level waits for their yes
(`graphs/lane.md`, Model routing).

Ask: "Shall I explain what the red marks on a pull request mean?"

## 6. Red checks on a pull request

Explain: every pull request shows two checks. `gate` passes when the tests pass and a
reviewer stamp sits under `grills/`. `operator-merge` checks for policy files. A red mark is
**expected** when:

- the pull request is still a draft: both checks are red until it is marked ready;
- `operator-merge` is red: a policy file changed, so they merge it;
- `gate` was red on setup's own pull request, because no reviewer had approved it yet.

Red `gate` on a ready lane pull request is **not** expected: the agent stops and tells them,
and does not push fixes to turn it green. To see why a check failed, they click **Details**
next to it, then **Summary**, as in setup.

Ask: "Ready to pick the first thing to work on?"

## 7. Start a grill: the first thing to work on

This step is a grill run: follow `graphs/grill.md` from here, its action-log line included.
Ask for their goals first, frame-first (`graphs/grill.md` step 2): what they want to get
done, what done would look like, and what they are afraid of getting wrong. Offer no choices
and no recommendation yet; get their own words and their own list onto the record. Then end
by asking, as one pop-out, which of the things they named to work on first, the choices in
their words. Nothing starts until they pick; a build then opens a lane (step 3 above).
Then create the marker file (Ending or skipping, above).
