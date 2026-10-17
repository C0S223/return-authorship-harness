# SETUP.md: setting this repository up with a person

**Codex:** use `CODEX-SETUP.md` instead. The steps below depend on Claude Code
registration and probe procedures. Codex has a separate adapter and activation guide.

**Reader: the agent.** A person opened this repository in Claude Code and asked you to set
it up. They may not be technical. Walk them through the steps below **one at a time**, in
plain words. After each step, say in one or two sentences what happened and what it means
for them.

**STOP** marks a step only the person can do. Tell them exactly what to do, then wait for
their reply. Never do a STOP step for them, and never skip a step that failed: explain the
failure plainly and help them fix it. Everything here follows `CLAUDE.md`; where this file
seems to disagree with it, `CLAUDE.md` wins and you say so.

**Put what they must read last.** The Claude Code desktop app folds away text written
between tool calls, so the person may see only the last message of your turn. Every STOP
instruction, and each walkthrough below in full, goes in that last message, after your final
tool call.

## 1. Check the tools

Run `python3 --version`, then `python --version`, then `git --version` and `jq --version`.

- **Python 3.11 or newer** is needed to complete setup and run the full repository suite,
  which includes the Codex tests. The Claude hook launcher, `.claude/hooks/run-python.sh`,
  separately accepts Python 3.10 or newer, trying `python3` before `python`. For the
  commands in this guide, choose an installed interpreter that reports 3.11 or newer
  and use its name wherever a step says `python3`. An older interpreter that can run
  the Claude hooks is not sufficient for step 4.
- Git and jq are needed too. The check that runs before every prompt
  (`.claude/hooks/preflight.sh`) refuses all prompts without jq.
- Bash needs no version check: the shell hooks keep to the bash 3.2 that macOS ships
  (`tests/test_log_escape.py` scans for later syntax).

Anything missing or too old: **STOP.** Name it, and point them to python.org or
git-scm.com for those two (for jq, its official install page for their system). Installing
is theirs by default. If they explicitly ask you to install it, that request authorizes
that one install (`CLAUDE.md` §2): show the exact command first, and run only that. On
Windows, `winget` and `choco` are refused until they send `auth-env` as a message on its
own, which allows one such command. Either way, Claude Code must then be restarted so it
finds the new tool: ask them to restart it, and run this step again.

## 2. A private copy that the person owns

Run `git remote get-url origin` and show them the result. Then **STOP** and ask them to
check on GitHub:

- The repository is **Private**.
- It is owned by **their own account**.
- If an agent pushes with its own GitHub login, that login is only a **collaborator**: never
  the owner and never an admin. An owner or admin skips the branch protection set up in
  step 7, so an agent with that login could merge anything.
- If the agent pushes with *their* login (the usual case when they cloned with their own
  account), tell them plainly: the ruleset in step 7 will not bind the agent, because that
  login is on its bypass list. Only this machine's safety checks stop the agent pushing to
  the main branch or merging past a red check. A separate collaborator login for the agent
  is the stronger setup.

If the repository was created by the agents' login, ask them to create a new one from the
template under their own account, or transfer this one to it, before going on.

## 3. Arm the push guard

Explain first: the push guard is a Git hook that stops an agent pushing straight to the main
branch, force pushing, pushing tags, or pushing anywhere but this repository. It ships off
(`docs/enforcement/CLAUDE.md`, Setup per target).

Ask which they are setting up: their own computer (Windows, macOS or Linux), a managed
cloud environment, or a self-hosted runner.

Partway through this step, a `session-close: stranded work` note may appear at the end of a
turn. It counts changed files and commits not yet on the main branch, which this step has
until its pull request is merged. Here it is expected: tell them it is not an error, do not offer `/closeout`, and repeat in full the STOP instruction you had just given (usually the `revoke-policy` request in d), because your earlier message is no longer the last one.

**a. Unlock the files.** The guard's files are policy files, and only the person can unlock
them. On their own computer or a self-hosted runner, **STOP** and ask them to send this as a
message on its own, with nothing else in it:

    auth-policy-batch .githooks/pre-push .git/hooks/pre-push

Explain that it unlocks those two files for this session only. On a managed cloud
environment no unlock is needed: there the pull request is the approval, and they merge it.

**b. Set the address.** In `.githooks/pre-push`, set `APPROVED_ORIGIN_URL` to the URL from
step 2. Put the same URL in the `placeholder` line of `tests/test_prepush_policy.py`, or the
suite goes red. If the URL has anything between `https://` and `@` (a name or a token), stop:
never copy it into a file. Ask them to set origin to the plain URL in their own terminal
(`git remote set-url origin https://github.com/<owner>/<repo>.git`), then run step 2 again.

**c. Install it.**

- **Windows:** copy `tools/git-hooks/pre-push-dispatcher` to `.git/hooks/pre-push`.
- **macOS or Linux:** copy it the same way, then run `chmod +x .git/hooks/pre-push`; Git
  skips a hook that is not executable.
- **Managed cloud:** **STOP.** Ask them to paste `scripts/cloud-setup.sh` into the
  environment's setup-script field, with `OWNER/REPO` in its `REPO_MATCH` line changed to
  their `owner/repo`. The script runs before a session starts, so the guard is on from the
  next session. In that session, run the check below; if it fails, the person types
  `auth-policy .git/config` alone, then you run `git config core.hooksPath .githooks` and
  check again.
- **Self-hosted runner:** **STOP.** The runner's image must copy the dispatcher to
  `.git/hooks/pre-push`; ask whoever builds the image to add that step.

On every target, check it with `python3 scripts/test_prepush_install.py
--require-installed` (with the Python name from step 1). If a push is later refused because
origin's default branch is unknown, the person runs `git remote set-head origin --auto` in
their own terminal.

**d. Lock again.** Ask them to send `revoke-policy` as a message on its own. Then commit the
changed files on a new branch. **STOP:** ask their yes to push that branch and open one pull
request, naming both. With it, push with `git push origin <branch>`, never `git push -u`:
`-u` writes the branch's upstream into `.git/config`, a policy file, and sets off an
UNGRANTED policy-integrity alert. Then open the pull request and mark it ready for review (a
draft runs no checks).

**e. Merge the setup pull request.** Wait until both checks have finished
(`gh pr checks <number>`). Both will be red, on purpose: `operator-merge` because these are
policy files (step 7), and `gate` because no reviewer approval file exists yet. **STOP**,
and give them this walkthrough, with the pull request's link, in your last message:

1. Open the link. It shows the pull request on GitHub.
2. Click the **Files changed** tab. Only the two files from step b should be listed:
   `.githooks/pre-push` and `tests/test_prepush_policy.py`, each now holding the address of
   this repository. Anything else: stop and tell me.
3. Click the **Conversation** tab and scroll down to the checks. `gate` and
   `operator-merge` show a red cross. That is expected here: `operator-merge` is red
   whenever policy files change, so that only you can merge them, and `gate` is red because
   no reviewer has approved this change.
4. Next to `gate`, click **Details**. On the page that opens, click **Summary** (top left)
   and find the line `(c) suite: PASS`. PASS means every test passed on GitHub. If it says
   FAIL, stop and tell me.
5. Back on the pull request, scroll to the merge button. If there is a box about merging
   without waiting for requirements (bypass rules), tick it; until step 7 there is usually
   none. Click **Merge pull request**, then **Confirm merge**.
6. Click **Delete branch**. Its changes are now in the main branch.

Then tell me "merged", and whether the line read PASS.

When they report back, check it: `gh pr view <number> --json state` should say `MERGED`.
Then switch this checkout to the default branch and pull it, so the next steps run on the
merged files.

## 4. Run the test suite

Run `python3 scripts/run_tests.py` (with the Python name from step 1). The last line should
report no failures. If a suite fails, show them its line and say what it checks. Never edit
a test to make it pass.

## 5. Prove a safety check blocks

The checks are configured but unproven on this machine until one blocks for real. **STOP**
and ask permission to try one forbidden command on purpose. In the same message, warn them:
Claude Code will show the command as a red **Failed** tool call, and that red mark is the
pass, because the safety check refused it. With their yes, run:

    git remote set-url setup-probe https://example.invalid/probe.git

Expected: a `git-guard` refusal. Tell them that refusal is the good result. If git answered
instead (for example "No such remote"), nothing was changed, but the safety checks are not
running: tell them plainly and go back to step 1. Do not describe the setup as protected.

## 6. The board connector (optional)

Some workflows here can read and update a task board through a connector, a plug-in that
gives Claude Code access to another service. Nothing needs one. Without it, those steps are
skipped with one log line, and the work order files are the record. Tell them this, and that
they can add a connector later if they want one.

## 7. Protect the main branch on GitHub

Agents must not change repository settings, so the person makes these changes. **STOP**,
and give them this walkthrough, with their repository's link, in your last message:

1. On the repository's GitHub page, click **Settings** in the top bar. In the left
   sidebar, open **Rules**, then **Rulesets**.
2. Click **New ruleset**, then **New branch ruleset**.
3. Give it any name, for example `protect main`. Set **Enforcement status** to **Active**.
4. Under **Bypass list**, click **Add bypass**, tick only yourself, then click **Add Selected**: your own account, or a
   role only you hold (on a personal repository, **Repository admin**, if only you are an
   admin). Never the agent's login or a role it has: anyone on this list skips every rule. Check that the list now shows exactly that one entry.
5. Under **Target branches**, click **Add target**, then **Include default branch**.
6. Under **Branch protections**, leave the ones already ticked and tick **Require status checks to
   pass**. Click its button for adding checks (GitHub's help calls it **Add selected status checks**; on screen it may read **Add checks**), type `gate` and pick it, then do the same for
   `operator-merge`. They are offered only once GitHub has run them, which the setup pull
   request did in step 3.
7. Click **Create** at the bottom.
8. If GitHub says the ruleset will not be enforced on this private repository, or that
   enforcement needs a paid plan, it is saved but not applied. Note it and go on.
9. Back in **Settings**, on the **General** page, scroll to **Pull Requests** and tick
   **Allow auto-merge**. If there is no such box, note that too.

Then tell me "saved", whether a not-enforced notice appeared, and who is on the bypass
list.

**Read it back yourself; do not rely on their report.** Run:

    gh api repos/<owner>/<repo>/rulesets
    gh api repos/<owner>/<repo>/rules/branches/<default-branch>
    gh repo view <owner>/<repo> --json autoMergeAllowed

Write access is enough for these. The first should list the ruleset with `enforcement`
`active`. The second lists the rules GitHub applies to the default branch: it should hold a
`required_status_checks` rule naming `gate` and `operator-merge`. The third should show
`true`. If any of these is wrong, go back to the walkthrough step that sets it. If the
ruleset is listed but the second list has no such rule, GitHub is most likely not enforcing
it (a private repository on the free plan): tell them plainly that the main branch is then
protected only by this machine's safety checks, that auto-merge may be unavailable, and that
enforcement on a private repository needs a paid plan. The bypass list needs admin access to
read, so that part is theirs to confirm: repeat back who they said is on it and ask them to
confirm it is only them.

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

Last, offer the short tour: tell them that saying **onboard me** starts it, and when they
say it, follow `ONBOARDING.md`. On their own computer, a new session also offers it until they
finish or skip the tour; a managed cloud session or self-hosted runner does not offer it, but
**onboard me** works there too.
