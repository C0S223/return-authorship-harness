# Report: lane 6177 (builder super-doer; candidate ae2b68b, base 759372b; two swings)

**Authority.**
- Operator: "Fix all 9 now (Recommended)". It covers log-escape.sh, run-python.sh,
  preflight.sh, SETUP.md, README.md and the test portability fixes under tests/.
- Widened by "Widen to log-escape-fast.sh (Recommended)", after the builder found bare
  `python` calls in the audit hooks.

**What changed (DID.md and DID-SWING2.md, checked against the diff).**
- log-escape.sh takes timestamps from `date`, so it is safe on bash 3.2. A test scans every
  hook for constructs newer than bash 3.2.
- run-python.sh and preflight.sh require Python 3.10 or newer, trying python3 then python.
- The audit hooks' three bare `python` calls now go through the launcher. A test runs with
  python3 only on PATH.
- Test portability:
  - sed without `-i`;
  - a case-fold expectation probed from the filesystem;
  - every file parses as Python 3.10.
- SETUP.md:
  - the 3.10 floor;
  - the install rule;
  - push without `-u`;
  - the stranded-work note;
  - click-by-click merge walkthrough (3e) and ruleset walkthrough (7);
  - the red "Failed" warning (5);
  - the agent reads the ruleset back;
  - the last-message rule.
- README names the floor.
- `759372b..ae2b68b`: the granted paths, plus tests/ and the desk files. Nothing else.

**Hub reruns at ae2b68b.**
- Tree clean.
- `run_tests.py`: "38 suites: 38 pass, 0 fail, 0 skip".
- preflight rc 0.
- Scrub on the tree, file names and `759372b..HEAD` history: clean.

**Hub repair (scrub).** Two test comments in the builder's first commit read
"board 6177, finding N", which matches a private scrub pattern. The commit had never been
pushed, so the hub reworded both to "item N" and amended it: 7d576dc became 4b23062. The
change is comment-only.

**GitHub UI facts for the reviewer.** The hub fetched GitHub Docs, "Creating rulesets for a
repository", on 2026-10-16:
- Settings, then in the sidebar under "Code, planning, and automation", Rules, then Rulesets;
- New ruleset, then New branch ruleset;
- Enforcement status: Active or Disabled, with Disabled the default;
- Bypass list: Add bypass, then Add Selected;
- Target branches: Add a target (the doc gives no exact default-branch label);
- Branch protections: the status-check rule, then the "Add selected status checks"
  control.

On the REST rules pages, the single-ruleset endpoint returns `bypass_actors` only to users
with write access to the ruleset. In the operator's fresh-user test, write access read
`/rulesets` and `/rules/branches/main`, but not the bypass list.

**Unverified by anyone.**
- No real macOS, bash 3.2 or APFS host was available. Fakes, scans and probes stand in.
- The PR merge-box bypass label.
- Whether `gh repo view --json autoMergeAllowed` works through GraphQL on the person's host.
  It should, since GraphQL is blocked only in these cloud sessions.

**What would falsify it.**
- A hook line that uses a construct newer than bash 3.2.
- A python3-only host that loses an audit line.
- The launcher picking a Python older than 3.10 while a newer one exists.
- A walkthrough step that names a GitHub label that does not exist.
