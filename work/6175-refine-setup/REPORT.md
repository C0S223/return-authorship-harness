# Report: lane 6175 (builder super-doer; candidate 2fae948, base 1b6703b; two swings)

**Authority.**
- The operator granted "Approve as scoped (Recommended)": README.md, SETUP.md, run-python.sh,
  settings.json, test_settings_portable.py and the enforcement doc.
- Swing 1 came back BLOCKED: wiring needed two files outside the grant. The operator widened it
  with "Widen to both (Recommended)": `.claude/hooks/preflight.sh` and
  `scripts/test_contract_sync.py`.

**What changed (DID.md and DID-SWING2.md, checked against the diff):**
- Python hooks run through `.claude/hooks/run-python.sh`. It tries python3, then python,
  keeps the first that is really Python 3, and passes stdin, stdout and the exit code through.
- Every hook command first checks that its file exists, and exits 2 with a plain message if
  it is missing.
- preflight checks every quoted project path and that Python 3 exists. It still blocks on a
  missing jq.
- README.md is rewritten for newcomers (42 lines). SETUP.md is new (129 lines, the agent's
  setup walk). The enforcement doc points to SETUP.md, with plainer status wording.
- `1b6703b..2fae948 --name-status`: exactly the granted paths, plus the new
  `tests/test_run_python.py` and the desk files.

**Hub reruns at 2fae948:**
- `git status --porcelain`: empty.
- `run_tests.py`: "38 suites: 38 pass, 0 fail, 0 skip".
- `CLAUDE_PROJECT_DIR=<wt> bash .claude/hooks/preflight.sh`: rc 0.

**Hub repair (scrub).** The builder's DID.md line 8 quoted folder paths from another tree's
agent binding, and one of them matches the private scrub list. The branch had never been
pushed (`ls-remote` was empty), so the hub rewrote the unpushed history `1b6703b..HEAD` to
reword that one line. Tip b22f852 became 2fae948, and the diff between the two is that one line
only. The tree, file names and commit messages are now scrub-clean.

**Builder departures, accepted provisionally for review:**
- D1: the Stop hook exits 1, not 2, on a missing file. Exit 2 on Stop refuses the stop and would
  trap the session.
- D2: the PostToolUse `auto-compact/check.sh` command is unguarded, because
  `scripts/test_failure_hooks.py` (not granted) pins its string. PostToolUse cannot block, and
  preflight blocks every prompt if that file is gone.

**Root cause, restated.** The first-user fail-open came from a stale `CLAUDE_PROJECT_DIR`: a missing
script makes bash or python exit 127, which never blocks, and that skipped preflight itself.

**What would falsify it:**
- any hook command exiting 127, or 0, when its file is missing;
- a hook's own exit 1 being turned into a block;
- preflight passing with no Python 3;
- README or SETUP.md telling a newcomer something the tree does not do.
