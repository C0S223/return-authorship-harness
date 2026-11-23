# ONBOARDING.md: a short tour after setup

**Reader: the agent.** Start this whenever the person says **onboard me**, at any time,
even after they have taken or skipped the tour before. Nothing offers it unasked. If setup
is not finished, say so and offer `SETUP.md` instead. If they say **skip**, stop.

**How to run it.** One step per turn, one idea per message, in plain words. End each step
with a plain question and wait for the reply. Put each step's text in your last message,
after your final tool call: the desktop app folds away text written between tool calls
(`SETUP.md` says the same). This tour adds no rule. It points to the files that hold the
rules; where it seems to disagree with `CLAUDE.md` or `README.md`, those win, and you say so.

## 1. What this is for

Say, in two sentences: this repository keeps them in charge of an AI coding agent, with a
short written contract (`CLAUDE.md`) and a settings file that turns on the protections
Claude Code and Codex already have. They decide; the agent proposes, builds and reports
honestly.

Ask: "Shall I show you what protects your files, and what does not?"

## 2. What protects them

Explain, from `README.md`'s safety section and their own probe result if they ran one: the
protection is the platform's sandbox and permission rules, plus the rule on their main
branch on GitHub. The contract is text: the agent is told to follow it, and nothing makes
it. Name plainly what is not protected on their machine. Never call a machine protected on
the strength of the settings file alone.

Ask: "Shall I show you how we make decisions together?"

## 3. Deciding (`graphs/grill.md`)

Explain: when there are decisions to make, the agent asks **one question at a time**, each
as a small pop-out with two to four choices. They rule; the agent carries out each ruling
before the next question. The choice marked **(Recommended)** is the agent's own pick,
listed first. It is a suggestion, never a go: nothing happens until they choose, and nothing
is pushed unless the choice they picked says so. For a design question the agent may ask
for their own words first, with no choices offered.

Ask: "Any questions, or shall I show you how building works?"

## 4. Building

Explain: the agent works on a branch, never on the main branch. When the work is ready it
runs the tests and asks them. On their yes it pushes the branch and opens a **draft** pull
request: a proposed change, not yet merged. They read it and they merge it. The agent asks
before it edits the contract, the settings or the GitHub workflow files, and a pull request
that changes one says so in the first line of its description (`CLAUDE.md`, Ask first and
Git).

Ask: "Shall I say what the check on a pull request means?"

## 5. The check on a pull request

Explain: every pull request shows one check, `gate`. It runs the tests
(`python3 scripts/run_tests.py`). Green means they passed. Red means one failed: they click
**Details** next to it to see which, and the agent says what that test checks. The agent
never edits a test to turn it green.

Ask: "Shall I tell you about the reviewers you can ask for?"

## 6. Reviewers, when they want one

Explain: their own read of the pull request is the review. When they want an independent
check they can ask for a reviewer agent: `senior-engineer` reads code and runs the tests,
`adversarial-reviewer` reads documents. Each writes its review as a file under `grills/`.
A reviewer never reviews its own work. The agent is told to ask before it starts one; no
setting makes it.

Ask: "Ready to pick the first thing to work on?"

## 7. The first thing to work on

Follow `graphs/grill.md` from here. Ask for their goals first, frame-first
(`graphs/grill.md` step 2): what they want to get done, what done would look like, and what
they are afraid of getting wrong. Offer no choices and no recommendation yet; get their own
words and their own list. Then end by asking, as one pop-out, which of the things they named
to work on first, the choices in their words. Nothing starts until they pick.
