# SETUP.md: setting this repository up with a person

**Reader: the agent.** A person opened this repository in Claude Code and asked you to set
it up. They may not be technical. Walk them through the steps below **one at a time**, in
plain words. After each step, say in one or two sentences what happened and what it means
for them.

**STOP** marks a step only the person can do. Tell them exactly what to do, then wait for
their reply. Never do a STOP step for them, and never skip a step that failed: explain the
failure plainly and help them fix it. Everything here follows `CLAUDE.md`; where this file
seems to disagree with it, `CLAUDE.md` wins and you say so.

## 1. Check the tools

Run `python3 --version`, then `python --version`, then `git --version` and `jq --version`.

- Python 3 is needed under either name: the safety checks start through
  `.claude/hooks/run-python.sh`, which tries `python3` first, then `python`.
- Git and jq are needed too. The check that runs before every prompt
  (`.claude/hooks/preflight.sh`) refuses all prompts without jq.

Anything missing: **STOP.** Name what is missing, point them to python.org or git-scm.com
for those two (for jq, its official install page for their system), and ask them to
restart Claude Code once it is installed. Installing is theirs to do, not yours.

## 2. A private copy that the person owns

Run `git remote get-url origin` and show them the result. Then **STOP** and ask them to
check on GitHub:

- The repository is **Private**.
- It is owned by **their own account**.
- If an agent pushes with its own GitHub login, that login is only a **collaborator**: never
  the owner and never an admin. An owner or admin skips the branch protection set up in
  step 7, so an agent with that login could merge anything.

If the repository was created by the agents' login, ask them to create a new one from the
template under their own account, or transfer this one to it, before going on.

## 3. Arm the push guard

Explain first: the push guard is a Git hook that stops an agent pushing straight to the main
branch, force pushing, pushing tags, or pushing anywhere but this repository. It ships off
(`docs/enforcement/CLAUDE.md`, Setup per target).

Ask which they are setting up: their own computer (Windows, macOS or Linux), a managed
cloud environment, or a self-hosted runner.

**a. Unlock the files.** The guard's files are policy files, and only the person can unlock
them. On their own computer or a self-hosted runner, **STOP** and ask them to send this as a
message on its own, with nothing else in it:

    auth-policy-batch .githooks/pre-push .git/hooks/pre-push

Explain that it unlocks those two files for this session only. On a managed cloud
environment no unlock is needed: there the pull request is the approval, and they merge it.

**b. Set the address.** In `.githooks/pre-push`, set `APPROVED_ORIGIN_URL` to the URL from
step 2. Put the same URL in the `placeholder` line of `tests/test_prepush_policy.py`, or the
suite goes red.

**c. Install it.**

- **Windows:** copy `tools/git-hooks/pre-push-dispatcher` to `.git/hooks/pre-push`.
- **macOS or Linux:** copy it the same way, then run `chmod +x .git/hooks/pre-push`; Git
  skips a hook that is not executable.
- **Managed cloud:** **STOP.** Ask them to paste `scripts/cloud-setup.sh` into the
  environment's setup-script field, with `OWNER/REPO` in its `REPO_MATCH` line changed to
  their `owner/repo`. The script turns the guard on before each session starts.
- **Self-hosted runner:** **STOP.** The runner's image must copy the dispatcher to
  `.git/hooks/pre-push`; ask whoever builds the image to add that step.

On a computer or runner, check it with `python3 scripts/test_prepush_install.py
--require-installed` (or `python`). If a push is later refused because origin's default
branch is unknown, the person runs `git remote set-head origin --auto` in their own terminal.

**d. Lock again.** Ask them to send `revoke-policy` as a message on its own. Then commit the
changed files on a new branch and open a pull request; they merge it (step 7 says why its
`operator-merge` check is red).

## 4. Run the test suite

Run `python3 scripts/run_tests.py` (or `python`). The last line should report no failures.
If a suite fails, show them its line and say what it checks. Never edit a test to make it
pass.

## 5. Prove a safety check blocks

The checks are configured but unproven on this machine until one blocks for real. **STOP**
and ask permission to try one forbidden command on purpose. With their yes, run:

    git remote add setup-probe https://example.invalid/probe.git

Expected: a `git-guard` refusal. Tell them that refusal is the good result. If the command
went through instead, run `git remote remove setup-probe`, tell them plainly that the safety
checks are not running, and go back to step 1. Do not describe the setup as protected.

## 6. The board connector (optional)

Some workflows here can read and update a task board through a connector, a plug-in that
gives Claude Code access to another service. Nothing needs one. Without it, those steps are
skipped with one log line, and the work order files are the record. Tell them this, and that
they can add a connector later if they want one.

## 7. Protect the main branch on GitHub

Agents must not change repository settings, so this whole step is **STOP**: walk the
person through it on GitHub.

1. In the repository's **Settings**, open **Rules**, then **Rulesets**, and create a branch
   ruleset that targets the default branch and is active.
2. Turn on required status checks and add `gate` and `operator-merge`.
3. On the bypass list, put only the person's own account (or a role only they hold). Never
   the agents' login: anyone on that list skips the ruleset.
4. Save. In **Settings**, **General**, turn on **Allow auto-merge**.

Explain what this does. Every change arrives as a pull request. `gate` passes when the tests
pass and a reviewer approval file sits under `grills/` (`scripts/stamp_check.py`).
`operator-merge` turns red, on purpose, whenever a pull request changes a policy file such as
`CLAUDE.md` or `README.md` (full list: `docs/enforcement/CLAUDE.md`, Policy paths); the
person merges those through the bypass. Pull requests that touch no policy file can merge
themselves once both checks are green.

## 8. Done

Summarize in a few lines what is now on, what is not, and anything left for them. Then
suggest they read `CLAUDE.md` and adjust it to their work. Its roster and size budget are
pinned by tests (`scripts/test_contract_sync.py`, `scripts/test_claude_md_budget.py`), so
change those in the same commit as the text.
