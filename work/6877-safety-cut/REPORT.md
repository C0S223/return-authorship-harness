# Report: the safety cut, ported to this kit

## What this change does

This kit used to carry its own guards: hooks that read each command's text, a push hook,
review stamps checked in CI, and a numbered contract that leaned on all of them. The source
copy this kit is drawn from removed that layer and kept only what the platform enforces.
This change brings the kit to the same state.

- **Removed (78 files):** every hook under `.claude/hooks/` except `auto-compact/`, the Codex
  hooks, the push hook and its dispatcher, the stamp, policy, push-check and lane scripts
  with their tests, `docs/enforcement/CLAUDE.md`, `docs/codex-enforcement.md`, `graphs/lane.md`, and the
  `review-order`, `harness-lane` and `closeout` skills.
- **Replaced:** `CLAUDE.md` and `AGENTS.md` (one short contract, byte-identical),
  `.claude/settings.json`, `.github/workflows/ci.yml`, `.github/CODEOWNERS`, `README.md`,
  `SETUP.md`, `CODEX-SETUP.md`, `ONBOARDING.md` and `graphs/grill.md`.
- **Added:** `scripts/safety_probe.py`, its tests, the `safety-probe` skill and
  `scripts/test_safety_files.py`.
- **Edited to match:** the agent and role files, the remaining skills, `.codex/`,
  `scripts/run_tests.py`, `scripts/cloud-setup.sh` and five notes under `docs/`.

## Where this kit differs from the source copy

- **Settings.** The source copy protects two more paths that this kit does not have. Those
  entries are left out here, in the settings, in `README.md` and in
  `scripts/test_safety_files.py`.
- **`scripts/cloud-setup.sh`** now does one thing: it makes `python` resolve. Its first step
  existed to switch on the push hook, which is gone. `scripts/test_cloud_setup.py` shrank
  with it, from 13 tests to 2.
- **The `closeout` skill is removed**, in both `.claude/skills/` and `.agents/skills/`. It
  called a deleted hook, cited numbered contract sections that no longer exist, and
  pushed branches on a close request, which the new contract does not allow without a yes
  for the push.
- **`README.md`** says the macOS network setting rests on a trial whose record is not in
  this repository, and that the one cloud probe was run with the source copy. It gives no
  date for either.

## What changes for someone already using this kit

- **The sandbox is now asked for.** The old settings file had no `sandbox` block. With this
  one, Claude Code is asked to refuse to start where the sandbox cannot run: native Windows,
  and Linux or WSL2 without `bubblewrap` and `socat`.
- **Schedules ask instead of being refused.** `CronCreate` and the scheduled-task tools move
  from the deny list to the ask list. `CronDelete` and `ScheduleWakeup` are no longer
  listed at all.
- **The file tools are denied the protected paths.** The old settings had no `Edit(...)`
  deny rules; hooks did that work.
- **CI is one check, `gate`, which runs the tests.** The `operator-merge` check is gone. A
  ruleset that still requires it will block every merge until it is taken off the list.
- **An installed push hook must be removed by hand.** `SETUP.md` step 2 has the commands.

## What was checked

- `python3 scripts/run_tests.py` on Python 3.13.18:
  `11 suites: 11 pass, 0 fail, 0 skip (3 tests skipped inside 1 passing suites)`. The three
  skipped tests need a user the operating system can refuse; this run was as root.
- `CLAUDE.md` and `AGENTS.md` are byte-identical (2,732 bytes each).
- `.claude/settings.json` parses. `scripts/test_safety_files.py` pins its sandbox switches,
  the three unreadable folders, the denied and asked tools and the protected paths. It
  does not pin the extra write path, the macOS network setting or which hosts are listed.
- A search of every added line for private repository and account names, people, board and
  work ids, session ids and machine paths found none. That a private source copy exists is
  said on purpose, here and in `README.md`.
- The two action pins in `.github/workflows/ci.yml` match the tags their comments name.
- A search of the live files for the names of the removed files found two places: the two
  records under `docs/adr/`, which carry a note saying so, and `SETUP.md` step 2, which
  names the old push hook in order to have it removed.

## Review

`grills/2026-11-23-lane-6877-ar.md` is one independent read of the first revision of this
change, for leaks and for claims stronger than the files deliver. It refused that revision
on four points. The commit after it repairs those four and the smaller findings listed
below; the reviewer has not read the repairs.

The revision named in the review's header is not in this history. It differed from the
first commit here in one sentence of this report, which named two source-copy paths: the
review's first point. That sentence was reworded before anything was published, so the
review's line numbers still fit the first commit.

- Repaired: its conditions 1 to 4; new defects 1, 2, 3, 6, 8, 9, 11 and 12; notes 1, 4, 5
  and 10.
- Left as found: new defects 4, 5, 7 and 10, and notes 2, 3, 6, 7, 8 and 9. None is a leak
  or a protection claim.

## What was not checked

- **No probe run with these settings.** `scripts/safety_probe.py` was not run against this
  kit on any machine. `README.md` reports what the source copy's runs showed.
- **Python 3.14**, which CI uses, was not run here.
- **Codex.** Nothing here was run under Codex.
- **Stale comments.** A few code comments still cite numbered contract sections
  (`.claude/hooks/auto-compact/check.sh`, `scripts/run_tests.py`, `scripts/test_run_tests.py`,
  `scripts/test_graph_pointers.py`). They change no behaviour and match the source copy.
- **Older files under `work/`, `grills/` and `handoffs/`** described the removed machinery.
  A later change removed them; they remain in this repository's git history.

## For whoever merges this

- This pull request brings its own CI file. Its `gate` runs in the same concurrency group
  as the default branch's old checks and cancels them. The old `gate` and `operator-merge`
  results on this pull request are therefore not a read of this change.
- Before or right after merging, take `operator-merge` off the ruleset's required checks.
