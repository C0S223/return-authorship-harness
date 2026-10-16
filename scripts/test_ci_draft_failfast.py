"""On a draft PR both required checks must read red, never passing.

Before this fix both jobs carried `if: !github.event.pull_request.draft`, and a
skipped required check reads as passing: in the seconds after "Ready for
review" the draft's stale skipped checks let a PR merge with no gate result
(25 merges measured).

- No job-level `if`: catches a job that is skipped (green) on a draft.
- First step fails drafts: catches a missing, misplaced or non-failing guard,
  a loose condition that never fires, and continue-on-error.
- Steps with any `if` (they may outlive a failure) run in head/, and
  no checkout carries an `if`: so after the guard fails the checkouts skip,
  head/ never exists, and (b)/(c) cannot run any code on a draft. P3 in
  test_ci_policy_check.py pins (b)/(c) to a bare `${{ !cancelled() }}`, which
  is why the guard works through the checkout and not through their `if`.
"""
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WORKFLOW = os.path.join(ROOT, ".github", "workflows", "ci.yml")
JOBS = ("gate", "operator-merge")

try:
    import yaml
except ImportError:  # the host and the runner both have it; skip loudly
    yaml = None


@unittest.skipUnless(yaml, "pyyaml not importable; the runner pip-installs it")
class TestDraftFailFast(unittest.TestCase):
    def setUp(self):
        with open(WORKFLOW, encoding="utf-8") as fh:
            self.jobs = yaml.safe_load(fh)["jobs"]

    def test_jobs_are_not_skipped(self):
        for name in JOBS:
            with self.subTest(job=name):
                self.assertNotIn("if", self.jobs[name])

    def test_first_step_fails_drafts(self):
        # Exact condition: a loose comparison such as `draft == 'true'` never
        # fires. No continue-on-error anywhere: it turns the
        # guard's failure into success and the draft green (F3 x2).
        for name in JOBS:
            with self.subTest(job=name):
                job = self.jobs[name]
                first = job["steps"][0]
                self.assertEqual(first.get("if"), "${{ github.event.pull_request.draft }}")
                self.assertRegex(first.get("run", "").rstrip(), r"(?:^|\n)\s*exit 1$")
                self.assertNotIn("continue-on-error", job)
                for step in job["steps"]:
                    self.assertNotIn("continue-on-error", step, step.get("name"))

    def test_nothing_runs_code_after_the_guard_on_a_draft(self):
        for name in JOBS:
            for step in self.jobs[name]["steps"][1:]:
                with self.subTest(job=name, step=step.get("name")):
                    cond = step.get("if", "")
                    if str(step.get("uses", "")).startswith("actions/checkout@"):
                        self.assertEqual(cond, "", "a checkout must skip after the guard fails")
                    # Any explicit condition may outlive the guard's failure
                    # (`!cancelled()`, `always()`, `failure()`, `success() ||
                    # failure()`: review finding), so it must need head/.
                    if cond:
                        self.assertEqual(step.get("working-directory"), "head",
                                         "a step that outlives the guard must need head/")


if __name__ == "__main__":
    unittest.main()
