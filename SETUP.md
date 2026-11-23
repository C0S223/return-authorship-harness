# SETUP.md: setting this repository up with a person

**Codex:** use `CODEX-SETUP.md` instead.

**Reader: the agent.** A person opened this repository in Claude Code and asked you to set
it up. They may not be technical. Walk them through the steps below **one at a time**, in
plain words. After each step, say in one or two sentences what happened and what it means
for them.

**STOP** marks a step only the person can do. Tell them exactly what to do, then wait for
their reply. Never do a STOP step for them, and never skip a step that failed: explain the
failure plainly and help them fix it. Everything here follows `CLAUDE.md`.

**Put what they must read last.** The Claude Code desktop app folds away text written
between tool calls, so the person may see only the last message of your turn. Every STOP
instruction, and each walkthrough below in full, goes in that last message, after your final
tool call.

## 1. Check the tools

Run `python3 --version`, then `python --version`, then `git --version`. On Linux or WSL2
also run `bwrap --version` and `socat -V`.

- **Python 3.11 or newer** runs the probe and the tests. Use the name that reports it
  wherever a step says `python3`.
- **`bubblewrap` and `socat`** are what Claude Code's sandbox is built on, on Linux and
  WSL2. With this kit's settings Claude Code is asked to refuse to start without them. If
  you are running and `bwrap` or `socat` is missing, the sandbox is not containing your
  shell: say so, and go on; step 4 shows it.
- **Native Windows** has no sandbox, and with this kit's settings Claude Code is asked not
  to start there. If you are running on native Windows all the same, say plainly that
  nothing contains your shell. The supported routes are WSL2 or a cloud session.
- **A cloud session** is expected to lack both tools. Install nothing there. Say that the
  shell is not contained in the container, and let step 4 show the result.

Anything else missing or too old: **STOP.** Name it and point them to its official install
page. Installing is theirs by default. If they explicitly ask you to install it, that
request is the yes for that one install: show the exact command first, and run only that.
Claude Code must then be restarted so it finds the new tool.

## 2. A private copy that the person owns

Run `git remote get-url origin` and show them the result. Then **STOP** and ask them to
check on GitHub:

- The repository is **Private**.
- It is owned by **their own account**.
- If the agent pushes with *their* login (the usual case when they cloned with their own
  account), tell them plainly: the ruleset in step 5 does not then decide who merges. That
  login can merge its own pull request and, as an owner or admin, change the ruleset. A
  separate collaborator login for the agent, never an owner or admin, is the stronger
  setup.

**A push hook left by an older copy.** Earlier versions of this kit had the person install
a push hook that this version no longer ships. Run:

    ls "$(git rev-parse --git-common-dir)/hooks/pre-push"
    git config --get core.hooksPath

On a fresh copy the first reports no such file and the second prints nothing: go on. If the
file exists and its text mentions `.githooks/pre-push`, or the second command prints
`.githooks`, **STOP.** With the file in place, every push from this clone is refused. With
only the setting, pushes go through, and any file later created at `.githooks/pre-push`
would run on each push. Removing either is theirs: the settings deny you that folder. Give
them the command that fits:

    rm "$(git rev-parse --git-common-dir)/hooks/pre-push"
    git config --unset core.hooksPath

Never create anything under `.githooks/` to make a push go through.

## 3. Run the tests

Run `python3 scripts/run_tests.py`. The last line should report no failures. If a suite
fails, show them its line and say what it checks. Never edit a test to make it pass.

## 4. See what this machine enforces

Explain first: the settings file asks Claude Code for a sandbox, and the probe tries each
forbidden act from your shell to see whether the machine really refuses it. Before you ask,
read them all four effects from step 1 of `.claude/skills/safety-probe/SKILL.md`:

- one empty file created in their home folder and removed at once;
- a listing of three key folders, with no file opened and no name printed;
- one empty request to `example.com` and, only if that is refused or not reached, one to
  `github.com`;
- each protected path opened for append and closed, with no byte written. Four of them
  sit outside this checkout.

**STOP** and ask their yes to run it. With it, follow the skill. Read the result with them,
row by row. On an act row, PASS means the machine refused the act, FAIL means it went
through or nothing was there to refuse it, and SKIP means it could not be told. A `config`
row tries nothing: its PASS shows only what the settings file says. Never describe this
machine as protected on the strength of the settings file alone: only a PASS on an act row
shows protection.

## 5. Protect the main branch on GitHub

Agents must not change repository settings, so the person makes these changes. **STOP**,
and give them this walkthrough, with their repository's link, in your last message:

1. On the repository's GitHub page, click **Settings** in the top bar. In the left
   sidebar, open **Rules**, then **Rulesets**.
2. Click **New ruleset**, then **New branch ruleset**.
3. Give it any name, for example `protect main`. Set **Enforcement status** to **Active**.
4. Under **Bypass list**: if the agent uses your own GitHub login, add nobody. Otherwise
   add only yourself, or nobody. Never the agent's login or a role it has: anyone on this
   list skips every rule.
5. Under **Target branches**, click **Add target**, then **Include default branch**.
6. Under **Branch protections**, tick **Require a pull request before merging**. Then
   tick **Require status checks to pass** and add the check named `gate`. On a fresh copy
   GitHub has never run `gate` and may not offer it: if it will not take the name, leave
   that second box unticked for now. Step 9 brings you back.
7. Click **Create** at the bottom.
8. If GitHub says the ruleset will not be enforced on this private repository, or that
   enforcement needs a paid plan, it is saved but not applied. Note it and go on.
9. After your first pull request has run `gate`, open this ruleset again and make sure
   `gate` is listed under **Require status checks to pass**.

Optional and stronger, only when the agent has its own login: put your own username in
`.github/CODEOWNERS` and, inside the pull-request rule, tick **Require review from Code
Owners**. A change to the safety files then waits for your approval. With one shared login
this cannot work: GitHub does not let you approve your own pull request.

Then tell me "saved", whether a not-enforced notice appeared, and who is on the bypass
list.

**Read it back yourself; do not rely on their report.** This needs GitHub's `gh` tool,
signed in. Without it, say that you could not read the ruleset back and that what follows
rests on their report. With it, run:

    gh api repos/<owner>/<repo>/rulesets
    gh api repos/<owner>/<repo>/rules/branches/<default-branch>

The first should list the ruleset with `enforcement` `active`. The second lists the rules
GitHub applies to the default branch: it should hold a `pull_request` rule and, once
added, a `required_status_checks` rule naming `gate`. If the ruleset is listed but the
second list is empty, GitHub is most likely not enforcing it: tell them plainly that
nothing then stops a push to the main branch. The bypass list needs admin access to read,
so that part is theirs to confirm.

Explain what this does: every change to the main branch arrives as a pull request and the
tests run on it. It does not decide who merges: any login that can write, the agent's
included, can merge once `gate` is green, and the pull request can change the tests it is
judged by. Merging is theirs by the contract, and nothing but the contract holds the agent
to that.

## 6. The board connector (optional)

Some workflows here can read and update a task board through a connector. Nothing needs
one. Tell them this, and that they can add a connector later if they want one.

## 7. Done

Summarize in a few lines what is now on, what is not, and anything left for them, using
the probe's rows and the README's safety section. Then suggest they read `CLAUDE.md` and
adjust it to their work; `AGENTS.md` must stay an exact copy of it.

Last, offer the short tour: saying **onboard me** starts it, and when they say it, follow
`ONBOARDING.md`.
