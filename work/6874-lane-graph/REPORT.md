# Report: lane 6874, lane graph and reviewers

Builder: hub. Candidate: 46492af on base c693f70.

## Acceptance

- a: `git diff c693f70 46492af` touches the 14 granted files and nothing else; this lane's
  `work/` is in the earlier work-order commit.
- b: `graphs/lane.md` differs from the source copy's in six places, and nowhere else:
  - the three excluded passages (the queue route, the "attended" pointer, and where harness
    changes land first);
  - the two dated ruling quotes, dropped;
  - the template's cloud-audit exception in step 4's landing check, kept.
- c: `cmp CLAUDE.md AGENTS.md` is clean. `python3 scripts/run_tests.py` gives 46 suites, 46
  pass, run in this worktree at 46492af.
- d: a scan of the candidate's diff finds no private repository name, person, board id other
  than this lane's, or dated ruling.
- e: reviews pending.

## Preflight at 46492af

- `scripts/ci_policy_check.py`: FAIL on 14 policy paths, as a policy lane expects.
- `scripts/stamp_check.py`: FAIL with no covering APPROVE (reviews pending).
- Suite: 46 of 46.

## Notes

- `scripts/lane_ready.py` and `scripts/lane_overlap.py` call `gh`. Their tests run offline
  against a fake, and they passed on the template unchanged before the port.
- The overlap check at dispatch is new in this lane, so it did not run for this lane. Instead,
  the open-PR list for the repository was read before building, and it was empty.
