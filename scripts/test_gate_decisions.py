"""The section 8 Status column's ask/deny claims were never
checked against the real hooks. A probe script prints what each PreToolUse gate decides on
a synthetic payload -- but scripts/run_tests.py discovers test_*.py only,
so the probe has never run in the suite. This file is the probe's CASES,
executed under isolation, asserted against section 8.

ISOLATION IS MANDATORY -- READ BEFORE TOUCHING THIS FILE.

Every hook this file runs resolves its tree root from HARNESS_ROOT (default:
the real main tree). That root decides what is
"inside" vs "outside", where a grant lives, and which .agent-log/ a hook
appends its deny (or unlock-consumed) lines to. spawn-roster and
trigger-shape also take a log-dir seam (SPAWN_ROSTER_LOG_DIR,
TRIGGER_SHAPE_LOG_DIR) that overrides the root for their log only. This
list is deliberately not per-hook: read the hook, not this docstring.

Every invocation below sets HARNESS_ROOT and SPAWN_ROSTER_LOG_DIR to a fresh
tempdir, every time. Never run these
hooks unisolated, not even to demonstrate the hazard -- state it from
source, as done above (an earlier grill, which struck
exactly that instruction from the plan before this file was built).

2026-09-21: browser-loopback was removed by the operator; its cases, its
log-seam test and its env var are gone from this file.

2026-09-23: GitGuardItem702 pins git-guard's new gh never-items
(`gh pr merge --admin`, `gh api` writes to the ruleset / branch protection /
repo settings, `gh repo edit`) and the landings that must stay allowed. The
full matcher suite with its differential half lives outside this
tree; these are the acceptance cases.
2026-09-24: F1-F4, F7 and hub defaults R1, R2, R4 added below,
plus three the first round-2 draft allowed (every method counts, lines
split, gh's bundled -i).
2026-09-24: F9 (heredoc prose and non-query fields
allow), F10 (a heredoc query and a multi-line `$(` endpoint deny), R10
(`)` and the backtick end a token) and the operator's four doors (refs,
merges, contents, `gh alias set/import`), each decided wrongly before the fix.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = ROOT / ".claude" / "hooks"
# filetool-scope/shell-scope allow writes under the scratchpad prefix on
# purpose; a builder whose TEMP resolves under it would see OUT land inside
# the allowed prefix and both "ask" cases would go red for the wrong reason.
SCRATCHPAD = Path("C:\\") / "Users" / "operator" / "AppData" / "Local" / "Temp" / "claude"

SESSION_ID = "probe-test"

# section 8's Status column, as this order's baseline table states it.
EXPECTED = {
    "filetool-scope": "ask",
    "shell-scope": "ask",
    "git-guard": "deny",
    "net-post": "deny",
    "env-global": "deny",
    "spawn-roster": "deny",
    "trigger-shape": "deny",
    "policy-mutate": "deny",
}


def build_cases(T, out):
    """The probe's CASES, substituting: cwd -> T (was the main tree), the
    policy-mutate target -> T/CLAUDE.md (was the real CLAUDE.md, which is
    NOT a policy path under this tempdir's HARNESS_ROOT), and the out-of-tree
    target -> `out` (was a hardcoded C:/tmp path)."""
    return {
        "filetool-scope": {"tool_name": "Write", "cwd": str(T),
                            "tool_input": {"file_path": out, "content": "x"}},
        "shell-scope": {"tool_name": "Bash", "cwd": str(T),
                        "tool_input": {"command": "echo hi > " + out}},
        "git-guard": {"tool_name": "Bash", "cwd": str(T),
                      "tool_input": {"command": "git push --force origin master"}},
        "net-post": {"tool_name": "Bash", "cwd": str(T),
                     "tool_input": {"command":
                                    "curl -X POST https://example.com -d k=v"}},
        "env-global": {"tool_name": "Bash", "cwd": str(T),
                       "tool_input": {"command": "npm install -g leftpad"}},
        "spawn-roster": {"tool_name": "Agent", "cwd": str(T),
                         "tool_input": {"subagent_type": "general-purpose",
                                        "prompt": "x"}},
        # A Routine with a schedule is L0; the hook reads fields only.
        "trigger-shape": {"tool_name": "mcp__claude-code-remote__create_trigger",
                          "cwd": str(T),
                          "tool_input": {"prompt": "[peer-mailbox] x",
                                         "cron_expression": "0 9 * * *"}},
        "policy-mutate": {"tool_name": "Write", "cwd": str(T),
                          "tool_input": {"file_path": str(T / "CLAUDE.md"),
                                         "content": "x"}},
    }


def run_hook(name, payload, env):
    """Runs one real hook from ROOT/.claude/hooks/ against `env` (which MUST
    carry HARNESS_ROOT and SPAWN_ROSTER_LOG_DIR --
    callers pass the isolated env built in setUp, never os.environ directly)."""
    p = subprocess.run(
        [sys.executable, str(HOOKS_DIR / (name.replace("-desk", "") + ".py"))],
        input=json.dumps(dict(payload, session_id=SESSION_ID)),
        capture_output=True, text=True, env=env)
    out = (p.stdout or "").strip()
    if not out:
        return "allow"  # a PreToolUse hook with no opinion prints nothing
    try:
        return json.loads(out)["hookSpecificOutput"]["permissionDecision"]
    except Exception:
        raise AssertionError("%s: unparseable hook output (rc=%s): %r"
                              % (name, p.returncode, out))


class GateDecisionsMatchSection8(unittest.TestCase):
    def setUp(self):
        self.T = Path(tempfile.mkdtemp(prefix="gate-decisions-test-"))
        self.addCleanup(shutil.rmtree, self.T, ignore_errors=True)
        (self.T / "CLAUDE.md").write_text("stub contract\n", encoding="utf-8")
        (self.T / ".agent-log").mkdir()

        self.out = Path(tempfile.gettempdir()).anchor + "harness-probe-target.txt"
        self._assert_out_is_really_outside(self.out)

        self.env = dict(os.environ, HARNESS_ROOT=str(self.T),
                        SPAWN_ROSTER_LOG_DIR=str(self.T / ".agent-log"))
        self.cases = build_cases(self.T, self.out)

    def _assert_out_is_really_outside(self, out):
        out_norm = os.path.normcase(os.path.realpath(out))
        for guard, label in ((ROOT, "ROOT"), (self.T, "the tempdir T"),
                              (SCRATCHPAD, "the scratchpad")):
            guard_norm = os.path.normcase(os.path.realpath(str(guard))) + os.sep
            self.assertFalse(out_norm.startswith(guard_norm),
                "OUT (%r) falls under %s -- filetool-scope/shell-scope allow "
                "writes there, and both 'ask' cases would go red for the "
                "wrong reason." % (out, label))

    def test_each_gate_decision_matches_section_8(self):
        mismatches = []
        for name, expected in EXPECTED.items():
            got = run_hook(name, self.cases[name], self.env)
            if got != expected:
                mismatches.append((name, "expected=%s" % expected, "got=%s" % got))
        self.assertEqual(mismatches, [], (
            "gate decision(s) that disagree with section 8's Status "
            "column: %r -- section 8 itself states the rule: 'probe and "
            "table disagree -> the table is wrong'." % mismatches))

    def test_spawn_roster_denial_landed_in_the_isolated_log_not_the_real_one(self):
        # Pins that the SPAWN_ROSTER_LOG_DIR seam actually took. Without
        # this, a silently-ignored env var would mean every run of this
        # suite -- from every worktree -- appends a DENY line to the real
        # main tree's .agent-log/, which is exactly the hazard the first grill
        # found in the plan.
        # The seam must point somewhere the HARNESS_ROOT fallback
        # (T/.agent-log) is not, or an ignored seam and a working one write
        # the same file and this test cannot tell them apart.
        seam = self.T / "seam-log"
        env = dict(self.env, SPAWN_ROSTER_LOG_DIR=str(seam))
        run_hook("spawn-roster", self.cases["spawn-roster"], env)
        day = time.strftime("%Y-%m-%d") + ".md"
        log, fallback = seam / day, self.T / ".agent-log" / day
        self.assertTrue(log.is_file(), "%s was never written -- the log seam did not take" % log)
        self.assertIn("[spawn-roster] DENY", log.read_text(encoding="utf-8"))
        self.assertFalse(
            fallback.is_file() and "[spawn-roster] DENY" in fallback.read_text(encoding="utf-8"),
            "%s got the DENY line -- the hook used the HARNESS_ROOT fallback, not the seam" % fallback)


# The six hooks that read
# unlock_consume.cloud_boundary() -- policy-mutate, filetool-scope,
# shell-scope, net-post, env-global -- go cloud-off under the marker;
# git-guard, spawn-roster stay live/deny (status "ported", unaffected by
# the marker); policy-mutate is table-EXPECTED above too, so it is asserted
# by BOTH classes here (no marker -> deny, either marker -> allow).
CLOUD_OFF = ("filetool-scope", "shell-scope", "net-post", "env-global", "policy-mutate")
MARKERS = {"managed": {"CLAUDE_CODE_REMOTE": "true"},
           "selfhost": {"HARNESS_BOUNDARY": "selfhost"}}


class GateDecisionsUnderCloudMarker(unittest.TestCase):
    """Isolation rules are identical to GateDecisionsMatchSection8 above --
    read that class docstring first. Every hook here still reads HARNESS_ROOT
    from the isolated env; only the marker var changes per sub-test."""

    def setUp(self):
        self.T = Path(tempfile.mkdtemp(prefix="gate-decisions-cloud-test-"))
        self.addCleanup(shutil.rmtree, self.T, ignore_errors=True)
        (self.T / "CLAUDE.md").write_text("stub contract\n", encoding="utf-8")
        (self.T / ".agent-log").mkdir()
        self.out = Path(tempfile.gettempdir()).anchor + "harness-probe-target.txt"
        self.base_env = dict(os.environ, HARNESS_ROOT=str(self.T),
                              SPAWN_ROSTER_LOG_DIR=str(self.T / ".agent-log"))
        # a stray marker in the REAL parent environment must never leak into
        # a case that is supposed to test the no-marker (Windows) shape
        for k in ("CLAUDE_CODE_REMOTE", "HARNESS_BOUNDARY"):
            self.base_env.pop(k, None)
        self.cases = build_cases(self.T, self.out)

    def test_windows_control_no_marker_still_gates(self):
        # The control every marker sub-test below is measured against: with
        # NEITHER var set, cloud-off hooks must behave exactly as section 8
        # states (unchanged from GateDecisionsMatchSection8).
        for name in CLOUD_OFF:
            got = run_hook(name, self.cases[name], self.base_env)
            self.assertEqual(got, EXPECTED[name],
                "%s: no marker set, expected %s (Windows-shape), got %s"
                % (name, EXPECTED[name], got))

    def test_marker_plus_boundary_exits_0_on_every_cloud_off_hook(self):
        for boundary, extra in MARKERS.items():
            env = dict(self.base_env, **extra)
            for name in CLOUD_OFF:
                got = run_hook(name, self.cases[name], env)
                self.assertEqual(got, "allow",
                    "%s under %s marker: expected allow (cloud-off), got %s"
                    % (name, boundary, got))

    def test_marker_without_the_env_var_the_hook_itself_reads_still_gates(self):
        # DESIGN §1: the marker is trusted only together with the read. A
        # managed hook checks CLAUDE_CODE_REMOTE, not HARNESS_BOUNDARY, and vice
        # versa -- setting the WRONG one must not disarm either family.
        wrong_pairs = [({"CLAUDE_CODE_REMOTE": "1"}, "truthy-looking, not the exact string 'true'"),
                       ({"HARNESS_BOUNDARY": "prod"}, "set but not the exact string 'selfhost'"),
                       ({"CLAUDE_CODE_REMOTE": "false"}, "explicitly false")]
        for extra, label in wrong_pairs:
            env = dict(self.base_env, **extra)
            for name in CLOUD_OFF:
                got = run_hook(name, self.cases[name], env)
                self.assertEqual(got, EXPECTED[name],
                    "%s (%s): expected %s (still gated), got %s"
                    % (name, label, EXPECTED[name], got))

    def test_shell_scope_log_mode_survives_cloud_off(self):
        # shell-scope's --log branch is log-escape's audit trail (status
        # "ported", stays live on cloud) -- only the GATING call goes
        # cloud-off. --log must still print under the marker.
        payload = self.cases["shell-scope"]
        for boundary, extra in MARKERS.items():
            env = dict(self.base_env, **extra)
            p = subprocess.run(
                [sys.executable, str(HOOKS_DIR / "shell-scope.py"), "--log"],
                input=json.dumps(dict(payload, session_id=SESSION_ID)),
                capture_output=True, text=True, env=env)
            self.assertIn("shellwrite:", p.stdout,
                "shell-scope --log under %s marker printed nothing -- the "
                "audit trail must survive cloud-off (log-escape status "
                "'ported')" % boundary)


# An admin
# identity bypasses the default-branch ruleset on master, so git-guard
# denies the shapes that skip or rewrite the CI gate. Must-allow is the other
# half: the sanctioned landing, the reads one token
# away from each deny, and never-items QUOTED as prose in a commit message or
# PR body must not false-deny, or the lane cannot land.
# Review finding (2026-09-24) rows are labelled F/R, each decided wrongly before the fix.
# The last three deny rows guard round-2 rewrite: the first round-2 draft
# allowed all three (the earlier matcher denied two of them and allowed bundled -i).
GIT_GUARD_702_DENY = [
    "gh pr merge 12 --admin",
    "gh api -X PATCH repos/o/r/rulesets/12345 -f enforcement=disabled",
    "gh api repos/o/r/rulesets --method POST --input body.json",
    "gh api -X PUT repos/o/r/branches/master/protection --input p.json",
    "gh api -X PATCH repos/o/r -f default_branch=x",
    "gh api repos/o/r -F allow_auto_merge=true",
    "gh repo edit --default-branch main",
    "gh pr merge 12 --admin=true",                                      # F1
    "gh pr merge 12 --admin; git pull",                                 # F2
    "gh api -X DELETE \"repos/o/r/rulesets/12345\"",                 # F3
    "gh api repos/o/r/rulesets --input body.json",                      # F7
    "gh api -X PUT repos/o/r/pulls/12/merge",                           # R2
    "gh api graphql -f query='mutation { mergePullRequest(input: {pullRequestId: \"x\"}) { clientMutationId } }'",  # R1
    "gh api -X PATCH repos/o/r/ -f default_branch=x",                   # R4
    "gh api -X GET -X DELETE repos/o/r/rulesets/12345",              # gh keeps the last -X
    "gh api repos/o/r/rulesets -X GET\ngh api repos/o/r/rulesets -f x=y",  # a GET line excuses nothing
    "gh api -iX DELETE repos/o/r/rulesets/12345",                    # bundled -i
    "gh api graphql -F query=@- <<'EOF'\nmutation { mergePullRequest(input: {pullRequestId: \"x\"}) { clientMutationId } }\nEOF",  # F10
    "gh api -X DELETE $(\necho repos/o/r/rulesets/1\n)",                # F10
    "out=$(gh pr merge 12 --admin)",                                    # R10
    "`gh pr merge 12 --admin`",                                         # R10
    "$(gh api --input r.json -X PUT repos/o/r/branches/master/protection)",  # R10
    "gh api -X PATCH repos/o/r/git/refs/heads/master -F force=true",    # door 1
    "gh api repos/o/r/merges -f base=master -f head=lane-1",          # door 2
    "gh api -X PUT repos/o/r/contents/README.md -f message=x -f content=eA==",  # door 3
    "gh alias set m 'pr merge --admin'",                                # door 4
    "git commit -m x\\<<EOF\ngh pr merge 12 --admin\nEOF",              # F11
    "gh api graphql -F query=@- <<EOF\nmuta\\\ntion { x }\nEOF",       # F12
    "git commit -F - <<'EOF'\nround 2\n\nF3: gh api -X DELETE \"repos/o/r/rulesets/1\" denies.\nEOF",  # F9's cost, ruled
]
GIT_GUARD_702_ALLOW = [
    "gh pr merge 12 --auto --merge",
    "gh pr merge 12 --merge",
    "gh api repos/o/r/rulesets",
    "gh api repos/o/r/pulls/1",
    "gh api -X PATCH repos/o/r/pulls/1 -f title=x",
    "gh pr create --base master --head lane-1 --fill",
    "gh api repos/o/r/rulesets -X GET -F includes_parents=false",       # F4
    "gh api -X GET repos/o/r/branches/master/protection -f per_page=1", # F4
    "git commit -m \"gh api -X DELETE repos/o/r/rulesets/1\"",          # F3, the lesson
    "gh pr create --body \"never gh pr merge --admin\"",                # F3, the lesson
    "gh api graphql -f query='{ viewer { login } }'",                   # R1
    "gh api repos/o/r/pulls/12/merge",                                  # R2, the is-merged read
    "gh api -i repos/o/r/rulesets",                                     # bundled -i, a read
    "gh api repos/o/r/issues/12/comments -f body=\"R1: a graphql mutation now denies\"",  # F9
    "x=$(gh api repos/o/r/rulesets -X GET)",                            # R10, a read
    "gh api repos/o/r/git/refs/heads/master",                           # door 1, a read
    "gh api repos/o/r/contents/README.md",                              # door 3, a read
    "gh alias list",                                                    # door 4, a read
]


class GitGuardItem702(unittest.TestCase):
    """Isolation as in GateDecisionsMatchSection8: HARNESS_ROOT is a fresh tempdir,
    so a DENY here lands in no real .agent-log."""

    def setUp(self):
        self.T = Path(tempfile.mkdtemp(prefix="gate-decisions-702-"))
        self.addCleanup(shutil.rmtree, self.T, ignore_errors=True)
        (self.T / ".agent-log").mkdir()
        self.env = dict(os.environ, HARNESS_ROOT=str(self.T),
                        SPAWN_ROSTER_LOG_DIR=str(self.T / ".agent-log"))

    def decide(self, cmd):
        return run_hook("git-guard", {"tool_name": "Bash", "cwd": str(self.T),
                                      "tool_input": {"command": cmd}}, self.env)

    def test_admin_merge_and_gate_writes_deny(self):
        missed = [c for c in GIT_GUARD_702_DENY if self.decide(c) != "deny"]
        self.assertEqual(missed, [], "git-guard ALLOWED these never-items")

    def test_plain_merge_auto_merge_and_reads_allow(self):
        denied = [c for c in GIT_GUARD_702_ALLOW if self.decide(c) == "deny"]
        self.assertEqual(denied, [], "git-guard false-denied the sanctioned landing")


if __name__ == "__main__":
    unittest.main()
