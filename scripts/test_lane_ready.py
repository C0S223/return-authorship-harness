#!/usr/bin/env python3
"""Offline contract tests for scripts/lane_ready.py: no network, a fake GitHub.

The done check: a lane PR that passes this script and senior review has auto-merge armed,
so it merges on its own once the required checks pass; a PR touching a contract or policy file never has auto-merge armed and stays open
for the operator. Each refusal below must arm nothing.
"""

import base64
import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import unittest
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_stamp_check import ExecutionRefusalCases
import lane_ready


REPO = "acme/project"
R = "repos/" + REPO
HEAD = "a" * 40
STAMPED = "b" * 40
BLOCKED = "c" * 40


def stamp(verdict, reviewer, revision):
    text = "STAMP: %s\nREVIEWER: %s\nREVISION: %s\n\nbody\n" % (verdict, reviewer, revision)
    return {"content": base64.b64encode(text.encode()).decode(), "encoding": "base64"}


class FakeGitHub:
    """Endpoints answer from self.get; writes are recorded in self.writes."""

    def __init__(self):
        self.pr = {"number": 7, "state": "open", "draft": True, "merged": False,
                   "auto_merge": None,
                   "head": {"ref": "lane-42", "sha": HEAD, "repo": {"full_name": REPO}},
                   "base": {"ref": "main", "sha": "0" * 40,
                            "repo": {"full_name": REPO, "default_branch": "main"}}}
        self.files = [{"filename": "scripts/x.py", "status": "modified"},
                      {"filename": "grills/2026-10-29-lane-42-se.md", "status": "added"}]
        self.contents = {"grills/2026-10-29-lane-42-se.md": stamp("APPROVE", "senior-engineer", STAMPED)}
        self.compares = {(STAMPED, HEAD): {"status": "ahead", "files": [
            {"filename": "grills/2026-10-29-lane-42-se.md", "status": "added"}]}}
        # check runs before the ready mark (a draft's red), then the ready run
        self.runs_before = [{"id": 1, "name": "gate", "status": "completed", "conclusion": "failure",
                             "started_at": "2026-10-29T10:00:00Z"},
                            {"id": 2, "name": "operator-merge", "status": "completed", "conclusion": "failure",
                             "started_at": "2026-10-29T10:00:00Z"}]
        self.runs_after = [{"id": 3, "name": "gate", "status": "completed", "conclusion": "success",
                            "started_at": "2026-10-29T11:00:00Z"},
                           {"id": 4, "name": "operator-merge", "status": "completed", "conclusion": "success",
                            "started_at": "2026-10-29T11:00:00Z"}]
        self.others = []  # check runs other than gate and operator-merge
        self.events = []  # the PR's issue events
        self.annotations = {}  # check-run id -> annotation list
        self.ccr = True
        self.ready = False
        self.writes = []

    def api(self, method, endpoint, fields=None):
        mod = self.mod
        if method != "GET":
            self.writes.append((method, endpoint, fields))
            if "/ccr/" in endpoint and not self.ccr:
                raise mod.ApiError(404, "Not Found")
            if endpoint.endswith("/ccr/ready_for_review"):
                self.ready = True
                return {}
            if endpoint.endswith("/ccr/auto_merge"):
                self.pr["auto_merge"] = {"merge_method": "merge"} if method == "PUT" else None
                return {}
            raise AssertionError("unexpected write " + endpoint)
        if endpoint == R + "/pulls/7":
            return self.pr
        if endpoint.startswith(R + "/pulls/7/files"):
            return self.files if endpoint.endswith("page=1") else []
        if endpoint.startswith(R + "/contents/"):
            path = endpoint[len(R + "/contents/"):].split("?")[0]
            return self.contents[path]
        if endpoint.startswith(R + "/compare/"):
            a, b = endpoint[len(R + "/compare/"):].split("?")[0].split("...")
            if (a, b) not in self.compares:
                raise mod.ApiError(404, "No common ancestor")
            return self.compares[(a, b)]
        if endpoint.startswith(R + "/commits/%s/check-runs" % HEAD):
            return {"check_runs": self.runs_before + (self.runs_after if self.ready else []) + self.others}
        if endpoint.startswith(R + "/issues/7/events"):
            return self.events if endpoint.endswith("page=1") else []
        if endpoint.startswith(R + "/check-runs/") and endpoint.endswith("/annotations"):
            return self.annotations.get(int(endpoint.split("/")[-2]), [])
        raise AssertionError("unexpected read " + endpoint)

    def run(self, argv):
        self.writes.append(("RUN", " ".join(argv), None))
        if argv[:2] == ["gh", "pr"] and argv[2] == "ready":
            self.ready = True
        if argv[:3] == ["gh", "pr", "merge"]:
            self.pr["auto_merge"] = None if "--disable-auto" in argv else {"merge_method": "merge"}
        return 0, "", ""


class LaneReadyTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).with_name("lane_ready.py")
        spec = importlib.util.spec_from_file_location("lane_ready_under_test", path)
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)
        self.gh = FakeGitHub()
        self.gh.mod = self.mod
        self.clock = [0.0]

    def sleep(self, seconds):
        self.clock[0] += seconds

    def main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = self.mod.main(list(argv) or [REPO, "7"], api=self.gh.api, run=self.gh.run,
                                 sleep=self.sleep, clock=lambda: self.clock[0])
        return code, out.getvalue() + err.getvalue()

    def armed(self):
        return any(w[1].endswith("/ccr/auto_merge") or w[1].startswith("gh pr merge")
                   for w in self.gh.writes)

    def assertRefused(self, needle):
        code, out = self.main()
        self.assertEqual(code, 1, out)
        self.assertIn(needle, out)
        self.assertFalse(self.armed(), "a refusal armed auto-merge")
        return out

    # the merge half of the done check

    def test_reviewed_lane_pr_is_marked_ready_then_armed(self):
        code, out = self.main()
        self.assertEqual(code, 0, out)
        methods = [w[1] for w in self.gh.writes]
        self.assertEqual(methods, [R + "/pulls/7/ccr/ready_for_review", R + "/pulls/7/ccr/auto_merge"])
        self.assertIn("auto-merge armed", out)

    def test_already_ready_pr_uses_its_concluded_run(self):
        self.gh.pr["draft"] = False
        self.gh.ready = True
        self.gh.runs_before = []
        code, out = self.main()
        self.assertEqual(code, 0, out)
        self.assertEqual([w[1] for w in self.gh.writes], [R + "/pulls/7/ccr/auto_merge"])

    def test_already_ready_pr_skips_the_draft_runs_before_its_ready_event(self):
        # marked ready elsewhere (check-prs), draft reds still listed
        self.gh.pr["draft"] = False
        self.gh.ready = True
        self.gh.events = [{"event": "ready_for_review", "created_at": "2026-10-29T10:30:00Z"}]
        code, out = self.main()
        self.assertEqual(code, 0, out)
        self.assertEqual([w[1] for w in self.gh.writes], [R + "/pulls/7/ccr/auto_merge"])

    def test_already_ready_pr_waits_for_a_run_after_its_ready_event(self):
        self.gh.pr["draft"] = False
        self.gh.ready = True
        self.gh.runs_after = []
        self.gh.events = [{"event": "ready_for_review", "created_at": "2026-10-29T10:30:00Z"}]
        code, out = self.main()
        self.assertEqual(code, 2, out)
        self.assertIn("timed out", out)
        self.assertFalse(self.armed())

    def test_host_session_falls_back_to_gh_pr(self):
        self.gh.ccr = False
        code, out = self.main()
        self.assertEqual(code, 0, out)
        runs = [w[1] for w in self.gh.writes if w[0] == "RUN"]
        self.assertEqual(runs, ["gh pr ready 7 -R " + REPO,
                                "gh pr merge 7 -R %s --auto --merge --match-head-commit %s" % (REPO, HEAD)])

    # the stay-open half of the done check

    def test_contract_file_is_refused_before_anything_is_written(self):
        self.gh.files.append({"filename": "CLAUDE.md", "status": "modified"})
        self.assertRefused("contract or policy file: CLAUDE.md")
        self.assertEqual(self.gh.writes, [])

    def test_nested_contract_and_policy_dirs_are_refused(self):
        for path in ("docs/AGENTS.md", ".claude/settings.json", ".github/workflows/ci.yml", ".mcp.json"):
            with self.subTest(path=path):
                self.setUp()
                self.gh.files.append({"filename": path, "status": "modified"})
                self.assertRefused("contract or policy file: " + path)

    def test_renamed_from_a_contract_file_is_refused(self):
        self.gh.files.append({"filename": "notes.md", "previous_filename": "AGENTS.md", "status": "renamed"})
        self.assertRefused("contract or policy file: AGENTS.md")

    def test_red_operator_merge_after_ready_arms_nothing(self):
        self.gh.runs_after[1]["conclusion"] = "failure"
        self.gh.annotations[4] = [{"message": "Process completed with exit code 1."}]
        out = self.assertRefused("operator-merge")
        self.assertIn("the operator merges", out)

    def assertSurprise(self, needle):
        code, out = self.main()
        self.assertEqual(code, 2, out)
        self.assertIn(needle, out)
        self.assertFalse(self.armed(), "a surprise armed auto-merge")

    def test_operator_merge_without_its_verdict_is_a_surprise(self):
        # review F2: the checker could not run (exit 2), or no exit code at all
        for notes in ([{"message": "Process completed with exit code 2."}], []):
            with self.subTest(notes=notes):
                self.setUp()
                self.gh.runs_after[1]["conclusion"] = "failure"
                self.gh.annotations[4] = notes
                self.assertSurprise("without the checker's verdict")

    def test_cancelled_operator_merge_is_a_surprise(self):
        self.gh.runs_after[1]["conclusion"] = "cancelled"
        self.assertSurprise("operator-merge cancelled")

    def test_red_gate_after_ready_is_a_surprise(self):
        for conclusion in ("failure", "cancelled", "timed_out"):
            with self.subTest(conclusion=conclusion):
                self.setUp()
                self.gh.runs_after[0]["conclusion"] = conclusion
                self.assertSurprise("gate %s on a ready PR" % conclusion)

    def test_ready_run_that_never_completes_times_out(self):
        self.gh.runs_after[0]["status"] = "in_progress"
        self.gh.runs_after[0]["conclusion"] = None
        self.assertSurprise("timed out")

    # review F3: every other check-run counts

    def test_failed_other_check_arms_nothing(self):
        self.gh.others = [{"id": 9, "name": "codex-review", "status": "completed", "conclusion": "failure"}]
        self.assertRefused("check 'codex-review' concluded failure")

    def test_running_other_check_arms_nothing(self):
        self.gh.others = [{"id": 9, "name": "codex-review", "status": "in_progress", "conclusion": None}]
        self.assertRefused("check 'codex-review' is still running")

    def test_only_the_latest_other_run_counts_and_neutral_passes(self):
        self.gh.others = [{"id": 9, "name": "codex-review", "status": "completed", "conclusion": "failure"},
                          {"id": 10, "name": "codex-review", "status": "completed", "conclusion": "success"},
                          {"id": 11, "name": "lint", "status": "completed", "conclusion": "neutral"}]
        code, out = self.main()
        self.assertEqual(code, 0, out)

    def test_draft_run_is_never_read_as_the_verdict(self):
        # the ready run never starts: the old draft runs must not count
        self.gh.runs_after = []
        code, out = self.main()
        self.assertEqual(code, 2, out)
        self.assertIn("timed out", out)
        self.assertFalse(self.armed())

    # entry refusals

    def test_non_lane_head_is_refused(self):
        self.gh.pr["head"]["ref"] = "claude/feature"
        self.assertRefused("not a lane-<digits> branch")
        self.assertEqual(self.gh.writes, [])

    def test_lane_lookalike_heads_are_refused(self):
        for ref in ("lane-", "lane-42a", "lane-42/x", "xlane-42"):
            with self.subTest(ref=ref):
                self.setUp()
                self.gh.pr["head"]["ref"] = ref
                self.assertRefused("not a lane-<digits> branch")

    def test_fork_head_is_refused(self):
        self.gh.pr["head"]["repo"]["full_name"] = "someone/project"
        self.assertRefused("head is not this repository")

    def test_base_other_than_default_is_refused(self):
        self.gh.pr["base"]["ref"] = "lane-41"
        self.assertRefused("base 'lane-41' is not the default branch")

    def test_closed_pr_is_refused(self):
        self.gh.pr["state"] = "closed"
        self.assertRefused("not open")

    # senior review

    def test_no_senior_engineer_stamp_is_refused(self):
        self.gh.contents["grills/2026-10-29-lane-42-se.md"] = stamp("APPROVE", "adversarial-reviewer", STAMPED)
        self.assertRefused("no senior-engineer APPROVE covers the head")
        self.assertEqual(self.gh.writes, [])

    def test_stamp_followed_by_a_code_change_is_refused(self):
        self.gh.compares[(STAMPED, HEAD)]["files"].append({"filename": "scripts/x.py", "status": "modified"})
        self.assertRefused("no senior-engineer APPROVE covers the head")

    def test_stamp_not_an_ancestor_of_the_head_is_refused(self):
        self.gh.compares[(STAMPED, HEAD)]["status"] = "diverged"
        self.assertRefused("no senior-engineer APPROVE covers the head")

    def test_grills_file_modified_after_the_stamp_is_refused(self):
        self.gh.compares[(STAMPED, HEAD)]["files"][0]["status"] = "modified"
        self.assertRefused("no senior-engineer APPROVE covers the head")

    def test_stamp_file_already_on_the_base_does_not_count(self):
        self.gh.files[1]["status"] = "modified"
        self.assertRefused("no senior-engineer APPROVE covers the head")

    def test_nested_grills_file_does_not_count(self):
        self.gh.files[1]["filename"] = "grills/sub/se.md"
        self.gh.contents["grills/sub/se.md"] = self.gh.contents.pop("grills/2026-10-29-lane-42-se.md")
        self.assertRefused("no senior-engineer APPROVE covers the head")

    def test_unresolved_senior_block_is_refused(self):
        self.gh.files.append({"filename": "grills/2026-10-29-lane-42-se-r2.md", "status": "added"})
        self.gh.contents["grills/2026-10-29-lane-42-se-r2.md"] = stamp("BLOCK", "senior-engineer", BLOCKED)
        # the BLOCK came after the APPROVE: STAMPED...BLOCKED is ahead, BLOCKED...STAMPED is not
        self.gh.compares[(STAMPED, BLOCKED)] = {"status": "ahead", "files": []}
        self.gh.compares[(BLOCKED, STAMPED)] = {"status": "behind", "files": []}
        self.assertRefused("senior-engineer BLOCK")

    def test_repaired_block_with_later_approve_passes(self):
        self.gh.files.append({"filename": "grills/2026-10-29-lane-42-se-r1.md", "status": "added"})
        self.gh.contents["grills/2026-10-29-lane-42-se-r1.md"] = stamp("BLOCK", "senior-engineer", BLOCKED)
        self.gh.compares[(BLOCKED, STAMPED)] = {"status": "ahead", "files": []}
        self.gh.compares[(BLOCKED, HEAD)] = {"status": "ahead", "files": [
            {"filename": "scripts/x.py", "status": "modified"}]}
        code, out = self.main()
        self.assertEqual(code, 0, out)

    def test_unknown_or_truncated_block_coverage_is_not_a_repair(self):
        path = "grills/block.md"
        self.gh.files.append({"filename": path, "status": "added"})
        self.gh.contents[path] = stamp("BLOCK", "senior-engineer", BLOCKED)
        self.gh.compares[(BLOCKED, STAMPED)] = {"status": "ahead", "files": []}
        for diff in ({"status": "unknown", "files": []},
                     {"status": "ahead", "total_commits": 101, "commits": [], "files": []},
                     {"status": "ahead", "files": [
                         {"filename": "grills/%d.md" % n, "status": "added"} for n in range(300)]}):
            with self.subTest(status=diff["status"], count=len(diff["files"])):
                self.gh.compares[(BLOCKED, HEAD)] = diff
                self.assertRefused("cannot establish coverage")

    def test_malformed_stamp_header_does_not_count(self):
        self.gh.contents["grills/2026-10-29-lane-42-se.md"] = {
            "content": base64.b64encode(b"STAMP: APPROVE\nREVIEWER: senior-engineer\nREVISION: abc\n").decode(),
            "encoding": "base64"}
        self.assertRefused("malformed stamp header")

    # the head must not move under the verdict

    def test_head_moved_after_the_run_arms_nothing(self):
        original = self.gh.api

        def api(method, endpoint, fields=None):
            if endpoint == R + "/pulls/7" and self.gh.ready:
                moved = dict(self.gh.pr, head=dict(self.gh.pr["head"], sha="d" * 40))
                return moved
            return original(method, endpoint, fields)
        self.gh.api = api
        self.assertRefused("head moved")

    def test_base_retargeted_while_waiting_arms_nothing(self):
        original = self.gh.api

        def api(method, endpoint, fields=None):
            if endpoint == R + "/pulls/7" and self.gh.ready:
                return dict(self.gh.pr, base=dict(self.gh.pr["base"], ref="lane-41"))
            return original(method, endpoint, fields)
        self.gh.api = api
        self.assertRefused("base 'lane-41' is not the default branch")

    def test_arm_that_does_not_take_is_reported(self):
        original = self.gh.api

        def api(method, endpoint, fields=None):
            result = original(method, endpoint, fields)
            if endpoint.endswith("/ccr/auto_merge"):
                self.gh.pr["auto_merge"] = None
            return result
        self.gh.api = api
        code, out = self.main()
        self.assertEqual(code, 2, out)
        self.assertIn("auto_merge is not set", out)

    # the armed head is pinned, and no exit after the arm says "not armed"

    MOVED = "d" * 40
    HAND = "gh pr merge 7 -R %s --disable-auto" % REPO

    def wrap_api(self, reject=None, on_arm=None):
        """reject(method, endpoint) -> (status, detail) or None; on_arm() runs after the arm call."""
        original = self.gh.api

        def api(method, endpoint, fields=None):
            bad = reject(method, endpoint) if reject else None
            if bad:
                raise self.mod.ApiError(*bad)
            result = original(method, endpoint, fields)
            if on_arm and method == "PUT" and endpoint.endswith("/ccr/auto_merge"):
                on_arm()
            return result
        self.gh.api = api

    def move_head(self):
        self.gh.pr["head"]["sha"] = self.MOVED

    def test_head_moved_after_the_arm_is_disarmed_and_refused(self):
        self.wrap_api(on_arm=self.move_head)
        code, out = self.main()
        self.assertEqual(code, 1, out)
        self.assertIn(self.MOVED, out)
        self.assertNotIn("not armed", out)
        self.assertEqual([w[0] for w in self.gh.writes if w[1].endswith("/ccr/auto_merge")],
                         ["PUT", "DELETE"])
        self.assertIsNone(self.gh.pr["auto_merge"])

    def test_head_moved_after_the_arm_disarms_by_gh_on_a_host_session(self):
        self.gh.ccr = False
        original_run = self.gh.run

        def run(argv):
            result = original_run(argv)
            if "--auto" in argv:
                self.move_head()
            return result
        self.gh.run = run
        code, out = self.main()
        self.assertEqual(code, 1, out)
        runs = [w[1] for w in self.gh.writes if w[0] == "RUN"]
        self.assertEqual(runs[-1], self.HAND)
        self.assertIsNone(self.gh.pr["auto_merge"])

    def test_failed_disarm_is_exit_2_and_names_the_hand_command(self):
        self.wrap_api(reject=lambda m, e: (500, "boom") if m == "DELETE" else None, on_arm=self.move_head)
        code, out = self.main()
        self.assertEqual(code, 2, out)
        self.assertIn("disable it by hand", out)
        self.assertIn(self.HAND, out)
        self.assertIn("unchecked head", out)
        self.assertNotIn("not armed", out)

    def test_error_after_the_arm_call_says_may_be_armed(self):
        armed_readback = lambda m, e: ((502, "Bad Gateway")  # noqa: E731
                                       if m == "GET" and e == R + "/pulls/7" and self.gh.pr["auto_merge"]
                                       else None)
        failed_arm = lambda m, e: ((502, "Bad Gateway")  # noqa: E731
                                   if m == "PUT" and e.endswith("/ccr/auto_merge") else None)
        for label, reject in (("readback", armed_readback), ("arm call", failed_arm)):
            with self.subTest(label=label):
                self.setUp()
                self.wrap_api(reject=reject)
                code, out = self.main()
                self.assertEqual(code, 2, out)
                self.assertIn("MAY BE ARMED", out)
                self.assertIn(self.HAND, out)
                self.assertNotIn("not armed", out)

    def test_error_before_the_arm_still_says_not_armed(self):
        # a regression guard: it passes on the old script too, by construction
        self.wrap_api(reject=lambda m, e: (502, "Bad Gateway") if e.endswith("/ccr/ready_for_review") else None)
        code, out = self.main()
        self.assertEqual(code, 2, out)
        self.assertIn("not armed", out)
        self.assertNotIn("MAY BE ARMED", out)
        self.assertFalse(self.armed())

    # could-not-run

    def test_api_failure_is_exit_2(self):
        def api(method, endpoint, fields=None):
            raise self.mod.ApiError(502, "Bad Gateway")
        self.gh.api = api
        code, out = self.main()
        self.assertEqual(code, 2, out)
        self.assertFalse(self.armed())

    def test_usage_errors_are_exit_2(self):
        for argv in (["acme", "7"], [REPO, "x"], [REPO, "0"]):
            with self.subTest(argv=argv):
                with contextlib.redirect_stderr(io.StringIO()):
                    try:
                        code = self.mod.main(argv, api=self.gh.api, run=self.gh.run)
                    except SystemExit as exc:
                        code = exc.code
                self.assertEqual(code, 2)
        self.assertEqual(self.gh.writes, [])


class RefusalLandingTests(ExecutionRefusalCases, unittest.TestCase):
    """Translate real Git ancestry, diffs and blobs into read-only API responses.

    No network or ready/merge calls. This verifies the independent senior check,
    not GitHub activation, authentication, truncation or the live hook boundary.
    """

    def rows(self, older, newer):
        raw = self._git("diff", "--no-renames", "--name-status", "-z", older, newer)
        parts = raw.rstrip("\0").split("\0") if raw else []
        statuses = {"A": "added", "M": "modified", "D": "removed"}
        return [{"status": statuses[s], "filename": p}
                for s, p in zip(parts[::2], parts[1::2])]

    def api(self, method, endpoint, fields=None):
        self.assertEqual("GET", method, "test must never send")
        if "/compare/" in endpoint:
            older, newer = endpoint.split("/compare/", 1)[1].split("?", 1)[0].split("...")
            base = self._git("merge-base", older, newer)
            status = ("identical" if older == newer else "ahead" if base == older
                      else "behind" if base == newer else "diverged")
            listed = self._git("rev-list", "--parents", "%s..%s" % (base, newer)).splitlines()
            commits = [{"sha": row.split()[0], "parents": row.split()[1:]} for row in listed]
            return {"status": status, "files": self.rows(base, newer),
                    "commits": commits, "total_commits": len(commits)}
        if "/contents/" in endpoint:
            path, revision = endpoint.split("/contents/", 1)[1].split("?ref=", 1)
            path = unquote(path)
            # ls-tree establishes presence before show; no guessed fixture state.
            present = self._git("ls-tree", "--name-only", revision, "--", path)
            if present != path:
                raise lane_ready.ApiError(404, "file absent at " + revision)
            # Preserve trailing bytes: _git deliberately strips for other helpers.
            import subprocess
            blob = subprocess.run(["git", "-C", self.repo, "show", revision + ":" + path],
                                  capture_output=True, check=True, timeout=30).stdout
            return {"content": base64.b64encode(blob).decode(), "encoding": "base64"}
        raise AssertionError("unexpected endpoint " + endpoint)

    def check(self):
        head = self._git("rev-parse", "HEAD")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            try:
                lane_ready.check_senior(self.api, R, self.rows("master", head), "master", head)
            except lane_ready.Refused as exc:
                return 1, out.getvalue() + str(exc)
        return 0, out.getvalue()

    def test_main_resolves_refusal_before_arming_simulated_github(self):
        revision = self.subject()
        filed = self.refusal(revision)
        self.approve(filed)
        head = self._git("rev-parse", "HEAD")
        base = self._git("rev-parse", "master")
        fake = FakeGitHub()
        fake.mod = lane_ready
        fake.pr["head"]["sha"] = head
        fake.pr["base"]["sha"] = base
        fake.files = self.rows("master", head)
        clock = [0.0]

        def api(method, endpoint, fields=None):
            if method == "GET" and ("/compare/" in endpoint or "/contents/" in endpoint):
                return self.api(method, endpoint, fields)
            return fake.api(method, endpoint.replace("/commits/" + head + "/", "/commits/" + HEAD + "/"), fields)

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = lane_ready.main([REPO, "7"], api=api, run=fake.run,
                                   sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds),
                                   clock=lambda: clock[0])
        self.assertEqual(0, code, out.getvalue())
        self.assertIn("resolves EXECUTION-REFUSAL grills/refusal.md", out.getvalue())
        self.assertEqual([w[1] for w in fake.writes],
                         [R + "/pulls/7/ccr/ready_for_review", R + "/pulls/7/ccr/auto_merge"])

    def test_lane_commits_it_cannot_read_whole_refuse_landing(self):
        for diff in ({"status": "unknown"}, {"status": "ahead", "total_commits": 2, "commits": []}):
            with self.subTest(diff=diff):
                with self.assertRaisesRegex(lane_ready.Refused, "cannot read"):
                    lane_ready.unchanged_in_lane(lambda *a: diff, R, "b", "h", "grills/x.md", b"")

    def test_refusal_with_a_later_base_merge_refuses_landing(self):
        # Stricter than the gate, which keeps this approval.
        revision = self.subject()
        filed = self.refusal(revision)
        self.approve(filed)
        self.merge_base_branch()
        self.assertIn("no senior-engineer APPROVE covers", self.assert_gate(1))

    def test_repair_across_a_base_merge_refuses_landing(self):
        # Stricter than the gate: the merge hides whether the repair was real.
        revision = self.subject()
        self._commit(self.review("grills/block.md", "BLOCK", revision), "substantive block")
        self._commit({"foo.py": "x = 2\n"}, "repair")
        self.approve(self.merge_base_branch())
        self.assertIn("cannot establish coverage", self.assert_gate(1))


if __name__ == "__main__":
    unittest.main()
