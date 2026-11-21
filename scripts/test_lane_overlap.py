#!/usr/bin/env python3
"""Offline contract tests; LANE_OVERLAP_SCRIPT selects a baseline or mutant."""

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch


ROOT = "repos/acme/project"
PULLS = ROOT + "/pulls?state=open&per_page=100"
REFS = ROOT + "/git/matching-refs/heads/lane-?per_page=100"
COMPARE = ROOT + "/compare/main...lane-42?per_page=100"
PR_FILES = ROOT + "/pulls/7/files?per_page=100"


class OverlapTests(unittest.TestCase):
    def setUp(self):
        path = os.environ.get("LANE_OVERLAP_SCRIPT", str(Path(__file__).with_name("lane_overlap.py")))
        spec = importlib.util.spec_from_file_location("lane_overlap_under_test", path)
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)
        self.data = {ROOT: [{"default_branch": "main"}], PULLS: [[]], REFS: [[]]}
        self.calls = []

    def fetch(self, endpoint):
        self.calls.append(endpoint)
        value = self.data[endpoint]
        if isinstance(value, Exception):
            raise value
        return value

    def run_main(self, *paths):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = self.mod.main(["acme/project", *paths], fetcher=self.fetch)
        return code, out.getvalue(), err.getvalue()

    def pr(self, files):
        self.data[PULLS] = [[{"number": 7, "head": {"ref": "feature"}}]]
        self.data[PR_FILES] = [[{"filename": f} for f in files]]

    def branch(self, files):
        self.data[REFS] = [[{"ref": "refs/heads/lane-42"}]]
        self.data[COMPARE] = [{"files": [{"filename": f} for f in files]}]

    def test_pr_only_overlap(self):
        self.pr(["scripts/a.py"])
        self.assertEqual(self.run_main("scripts/a.py"), (1, "PR #7 feature: scripts/a.py\n", ""))

    def test_branch_only_overlap(self):
        self.branch(["scripts/a.py"])
        self.assertEqual(self.run_main("scripts/"), (1, "branch lane-42: scripts/a.py\n", ""))

    def check_rename(self, source, planned):
        entry = {"filename": "elsewhere/moved.py", "previous_filename": "scripts/a.py"}
        if source == "pr":
            self.pr([])
            self.data[PR_FILES] = [[entry]]
            label = "PR #7 feature"
        else:
            self.branch([])
            self.data[COMPARE] = [{"files": [entry]}]
            label = "branch lane-42"
        self.assertEqual(self.run_main(planned), (1, f"{label}: scripts/a.py\n", ""))

    def test_pr_rename_old_exact_path(self):
        self.check_rename("pr", "scripts/a.py")

    def test_pr_rename_out_of_directory(self):
        self.check_rename("pr", "scripts/")

    def test_branch_rename_old_exact_path(self):
        self.check_rename("branch", "scripts/a.py")

    def test_branch_rename_out_of_directory(self):
        self.check_rename("branch", "scripts/")

    def test_invalid_planned_paths_are_refused(self):
        self.pr(["scripts/a.py"])
        for path in ("./scripts/a.py", "/scripts/a.py", "scripts//",
                     "scripts\\a.py", "scripts/../scripts/a.py",
                     "scripts/./a.py", ".", "..", "scripts/.."):
            with self.subTest(path=path):
                code, out, err = self.run_main(path)
                self.assertEqual((code, out), (2, ""))
                self.assertIn("path", err)
        self.assertEqual(self.calls, [])

    def test_unexpected_fetcher_exception_is_reported(self):
        self.branch([])
        self.data[COMPARE] = RuntimeError("unexpected fetch failure")
        code, out, err = self.run_main("target")
        self.assertEqual((code, out), (2, ""))
        self.assertIn(COMPARE, err)
        self.assertIn("unexpected fetch failure", err)

    def test_gh_timeout_is_bounded_and_reported(self):
        with patch.object(self.mod.subprocess, "run",
                          side_effect=subprocess.TimeoutExpired(["gh"], 60)) as run:
            code, out, err = self.run_main_with_gh("target")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("timed out", err)
        self.assertIn(PULLS, err)
        self.assertGreater(run.call_args.kwargs["timeout"], 0)
        self.assertLessEqual(run.call_args.kwargs["timeout"], 60)

    def run_main_with_gh(self, *paths):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = self.mod.main(["acme/project", *paths])
        return code, out.getvalue(), err.getvalue()

    def test_exact_and_directory_boundaries(self):
        self.pr(["scripts/a.py.bak", "scripts/a.py/child", "scripts-old/a.py"])
        self.branch(["scripts-old/a.py", "scripts", "scriptstuff/a.py"])
        self.assertEqual(self.run_main("scripts/a.py", "scripts/"),
                         (1, "PR #7 feature: scripts/a.py.bak\nPR #7 feature: scripts/a.py/child\n", ""))
        self.assertEqual(self.run_main("scripts/a.py"), (0, "", ""))

    def test_both_sources_and_multiple_paths(self):
        self.pr(["a", "b", "unrelated"])
        self.branch(["b", "a"])
        self.assertEqual(self.run_main("a", "a", "b"),
                         (1, "PR #7 feature: a\nPR #7 feature: b\nbranch lane-42: b\nbranch lane-42: a\n", ""))

    def test_no_hits(self):
        self.pr(["elsewhere"])
        self.branch(["elsewhere"])
        self.assertEqual(self.run_main("target"), (0, "", ""))

    def test_all_sources_paginated(self):
        self.data[PULLS] = [[], [{"number": 7, "head": {"ref": "feature"}}]]
        self.data[PR_FILES] = [[{"filename": "unrelated"}], [{"filename": "target"}]]
        self.data[REFS] = [[], [{"ref": "refs/heads/lane-42"}]]
        self.data[COMPARE] = [{"files": [{"filename": "target"}]}, {"commits": []}]
        self.assertEqual(self.run_main("target"),
                         (1, "PR #7 feature: target\nbranch lane-42: target\n", ""))
        self.assertEqual(set(self.calls), set(self.data))

    def test_branch_compare_failure_reported(self):
        self.branch([])
        self.data[COMPARE] = self.mod.FetchError("comparison unavailable")
        code, out, err = self.run_main("target")
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("lane-42", err)
        self.assertIn("comparison unavailable", err)

    def test_each_fetch_failure_is_an_error_even_after_hits(self):
        for endpoint in (PULLS, PR_FILES, ROOT, REFS):
            with self.subTest(endpoint=endpoint):
                self.pr(["target"])
                self.data[ROOT] = [{"default_branch": "main"}]
                self.data[REFS] = [[]]
                self.data[endpoint] = self.mod.FetchError("offline")
                code, out, err = self.run_main("target")
                self.assertEqual((code, out), (2, ""))
                self.assertIn(endpoint, err)
                self.assertIn("offline", err)

    def test_default_branch_and_ref_are_url_encoded(self):
        self.data[ROOT] = [{"default_branch": "release/current"}]
        self.data[REFS] = [[{"ref": "refs/heads/lane-42/topic"}]]
        endpoint = ROOT + "/compare/release%2Fcurrent...lane-42%2Ftopic?per_page=100"
        self.data[endpoint] = [{"files": [{"filename": "target"}]}]
        self.assertEqual(self.run_main("target"), (1, "branch lane-42/topic: target\n", ""))

    def test_compare_limit_and_malformed_data_fail_closed(self):
        self.branch([])
        for response in ([{"files": [{"filename": "other"}] * 300}], [{"files": [{}]}], []):
            with self.subTest(response_size=len(response)):
                self.data[COMPARE] = response
                code, out, err = self.run_main("target")
                self.assertEqual((code, out), (2, ""))
                self.assertIn("fetch error", err)

    def test_pr_file_limit_fails_closed(self):
        self.pr([])
        self.data[PR_FILES] = [[{"filename": "other"}] * 100 for _ in range(30)]
        code, out, err = self.run_main("target")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("fetch error", err)
        self.assertIn("PR file limit reached", err)

    def test_gh_uses_only_get_and_pagination(self):
        pages = [[{"number": 7}], [{"number": 8}]]
        result = subprocess.CompletedProcess([], 0, stdout=json.dumps(pages))
        with patch.object(self.mod.subprocess, "run", return_value=result) as run:
            self.assertEqual(self.mod.gh_fetch(PULLS), pages)
        self.assertEqual(run.call_args.args[0],
                         ["gh", "api", "--method", "GET", "--paginate", "--slurp", PULLS])
        self.assertTrue(run.call_args.kwargs["check"])

    def test_gh_errors_are_reported(self):
        for exc in (FileNotFoundError("gh absent"),
                    subprocess.CalledProcessError(1, ["gh"], stderr="denied")):
            with self.subTest(error=str(exc)), patch.object(self.mod.subprocess, "run", side_effect=exc):
                with self.assertRaises(self.mod.FetchError):
                    self.mod.gh_fetch(PULLS)
        with patch.object(self.mod.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, stdout="bad json")):
            with self.assertRaises(self.mod.FetchError):
                self.mod.gh_fetch(PULLS)

    def test_usage_errors(self):
        for argv in ([], ["acme/project"], ["invalid", "a"], ["acme/project", ""]):
            with self.subTest(argv=argv), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as caught:
                    self.mod.main(argv, fetcher=self.fetch)
                self.assertEqual(caught.exception.code, 2)
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
