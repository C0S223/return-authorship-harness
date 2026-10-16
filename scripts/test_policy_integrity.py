"""Acceptance table for .claude/hooks/policy-integrity.py. Each case builds a throwaway checkout under
HARNESS_ROOT, baselines it with a SessionStart payload, changes bytes through the
channel the table names, runs the hook with a PostToolUse payload and reads
the day log. Channels are byte changes to the hook, so git's own verbs and an
interpreter's open() are exercised for real; a shell paraphrase is not needed
because the hook never sees the command.

    python scripts/test_policy_integrity.py
    POLICY_INTEGRITY_HOOK=<path> to run a candidate hook file.
    POLICY_MUTATE_HOOK=<path>, POLICY_PROMPT_HOOK=<path> for the ledger writer
    and the arm/revoke marker writer the task-grant cases drive.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOK = Path(os.environ.get("POLICY_INTEGRITY_HOOK")
            or ROOT / ".claude" / "hooks" / "policy-integrity.py")
MUTATE = Path(os.environ.get("POLICY_MUTATE_HOOK")
              or ROOT / ".claude" / "hooks" / "policy-mutate.py")
PROMPT = Path(os.environ.get("POLICY_PROMPT_HOOK")
              or ROOT / ".claude" / "hooks" / "policy-prompt.py")
SID = "sess-A"
OTHER = "sess-B"


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="pi-"))
        self.root = self.tmp / "tree"
        (self.root / ".claude" / "hooks").mkdir(parents=True)
        (self.root / "scripts").mkdir()
        (self.root / ".agent-log").mkdir()
        (self.root / "CLAUDE.md").write_text("contract v1\n")
        (self.root / ".claude" / "hooks" / "x.py").write_text("print(1)\n")
        (self.root / "scripts" / "a.py").write_text("a = 1\n")
        (self.root / "notes.md").write_text("not policy\n")
        self.git("init", "-q")
        self.git("-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
        self.git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base")
        self.env = dict(os.environ, HARNESS_ROOT=str(self.root))
        self.env.pop("CLAUDE_PROJECT_DIR", None)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def git(self, *a):
        subprocess.run(["git", "-C", str(self.root), *a], check=True,
                       capture_output=True)

    def hook(self, payload):
        r = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                           capture_output=True, text=True, env=self.env, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def start(self, source="startup", sid=SID):
        return self.hook({"session_id": sid, "hook_event_name": "SessionStart",
                          "source": source, "cwd": str(self.root)})

    def call(self, tool="Bash", sid=SID):
        return self.hook({"session_id": sid, "hook_event_name": "PostToolUse",
                          "tool_name": tool, "tool_input": {}, "cwd": str(self.root)})

    def log(self):
        p = self.root / ".agent-log" / (time.strftime("%Y-%m-%d") + ".md")
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def lines(self, tag):
        return [l for l in self.log().splitlines() if "[policy-integrity] " + tag in l]

    def consumed(self, rel, sid=SID, stamp=None):
        # policy-mutate's ledger line, as it writes it -- stamped NOW. 666
        # S2-1: with no arm marker a credit 8 h or older by its own stamp
        # counts not, so a fixed "00:00:00" would silently void every case
        # here after 08:00 local.
        with open(self.root / ".agent-log" / (time.strftime("%Y-%m-%d") + ".md"),
                  "a", encoding="utf-8") as f:
            f.write("- %s [policy-mutate] unlock-consumed: %s sid=%s\n"
                    % (stamp or time.strftime("%H:%M:%S"), rel, sid))

    # --- the two writers the ledger depends on, run for real ---------
    def prompt(self, text, sid=SID):
        """The operator's own turn through the real policy-prompt: arm or revoke."""
        r = subprocess.run([sys.executable, str(PROMPT)],
                           input=json.dumps({"prompt": text, "session_id": sid}),
                           capture_output=True, text=True, env=self.env, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def mutate(self, tool, ti, sid=SID):
        """One tool call through the real policy-mutate; True if allowed. The
        gate decides before the tool runs, so the ledger line is minted here
        and the bytes are whatever the test then does to them."""
        r = subprocess.run([sys.executable, str(MUTATE)], input=json.dumps(
            {"session_id": sid, "tool_name": tool, "cwd": str(self.root),
             "tool_input": ti}),
            capture_output=True, text=True, env=self.env, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return '"permissionDecision": "deny"' not in r.stdout

    def edit_under_task_grant(self, rel, sid=SID):
        """Hold a task grant for `rel` (the file written directly, no arm
        line) and pass an Edit through the real policy-mutate."""
        norm = os.path.normcase(os.path.realpath(str(self.root / rel)))
        (self.root / ".agent-log" / ("policy-unlock-%s.json" % sid)).write_text(
            json.dumps({"mode": "task", "epoch": time.time(), "used": False,
                        "entries": [{"path": rel, "norm": norm, "used": False}]}))
        self.assertTrue(self.mutate("Edit", {"file_path": str(self.root / rel)}, sid))

    def noop_hit(self, rel="CLAUDE.md"):
        """An allowed hit that changes no bytes -- an identical-content
        Write. It mints a credit the compare can never match."""
        content = (self.root / rel).read_text()
        self.assertTrue(self.mutate("Write", {"file_path": str(self.root / rel),
                                              "content": content}))

    def test_auto_compact_state_file_is_never_watched(self):
        d = self.root / ".claude" / "hooks" / "auto-compact"
        d.mkdir()
        (d / "state.json").write_text("{}")
        (d / "check.sh").write_text("exit 0\n")
        self.start()
        (d / "state.json").write_text('{"tick": 1}')
        (d / "check.sh").write_text("exit 1\n")
        self.call()
        self.assertEqual(0, len(self.lines("state.json")))
        self.assertEqual(1, len(self.lines("UNGRANTED CHANGED .claude/hooks/auto-compact/check.sh")))

    # --- baseline ---------------------------------------------------------
    def test_baseline_on_startup_and_resume_never_on_compact(self):
        self.start("startup")
        self.assertEqual(1, len(self.lines("BASELINE")))
        bp = self.root / ".agent-log" / ("policy-baseline-unlock-%s.json" % SID)
        self.assertTrue(bp.exists())
        base = json.loads(bp.read_text())
        self.assertLessEqual({"CLAUDE.md", ".claude/hooks/x.py", "scripts/a.py",
                              ".git/config"}, set(base["roots"]["."]))
        self.assertNotIn("notes.md", base["roots"]["."])
        self.start("compact")
        self.assertEqual(1, len(self.lines("BASELINE")))
        # resume with a baseline on disk compares; a resume of a
        # session that has none takes one
        self.start("resume")
        self.assertEqual(1, len(self.lines("BASELINE")))
        self.start("resume", sid=OTHER)
        self.assertEqual(2, len(self.lines("BASELINE")))

    def test_operator_edit_before_start_is_in_baseline(self):
        (self.root / "CLAUDE.md").write_text("operator edited\n")
        self.start()
        self.call()
        self.assertEqual([], self.lines("UNGRANTED"))

    def test_read_call_and_no_byte_change_write_no_line(self):
        self.start()
        self.call("Read")
        (self.root / "notes.md").write_text("changed, not policy\n")
        self.call("Bash")
        self.assertEqual([], self.lines("UNGRANTED") + self.lines("granted"))

    # --- ungranted channels -------------------------------------------------
    def test_interpreter_open_on_scripts_file_is_ungranted(self):
        self.start()
        (self.root / "scripts" / "a.py").write_text("a = 2\n")
        out = self.call()
        self.assertEqual(1, len(self.lines("UNGRANTED CHANGED scripts/a.py")))
        self.assertIn("UNGRANTED", out)

    def test_git_checkout_of_a_rev_is_ungranted(self):
        (self.root / "CLAUDE.md").write_text("contract v2\n")
        self.git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qam", "v2")
        self.start()   # baseline holds v2; git brings v1 back with no tool write
        self.git("checkout", "-q", "HEAD~1", "--", "CLAUDE.md")
        self.call()
        self.assertEqual(1, len(self.lines("UNGRANTED CHANGED CLAUDE.md")))
        # HEAD is irrelevant: bytes now match the baseline again, no new line
        self.git("checkout", "-q", "HEAD", "--", "CLAUDE.md")
        self.call()
        self.assertEqual(2, len(self.lines("UNGRANTED CHANGED CLAUDE.md")))

    def test_copy_onto_hook_is_ungranted(self):
        self.start()
        shutil.copy(self.root / "notes.md", self.root / ".claude" / "hooks" / "x.py")
        self.call("PowerShell")
        self.assertEqual(1, len(self.lines("UNGRANTED CHANGED .claude/hooks/x.py")))

    def test_pre_push_hook_sources_are_watched(self):
        """`.githooks/` is the LIVE
        pre-push hook (core.hooksPath) and `tools/git-hooks/` its dispatcher
        source. Neither was in DIRS, so a byte change there was never
        recorded; a near-miss sibling under `tools/` still is not."""
        rels = (".githooks/pre-push", "tools/git-hooks/pre-push-dispatcher")
        for rel in rels + ("tools/other/x",):
            p = self.root.joinpath(*rel.split("/"))
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("#!/bin/sh\n")
        self.start()
        for rel in rels + ("tools/other/x",):
            self.root.joinpath(*rel.split("/")).write_text("#!/bin/sh\nexit 0\n")
        self.call()
        for rel in rels:
            self.assertEqual(1, len(self.lines("UNGRANTED CHANGED " + rel)), rel)
        self.assertEqual([], self.lines("tools/other/x"))

    def test_delete_and_add(self):
        self.start()
        (self.root / ".claude" / "hooks" / "x.py").unlink()
        (self.root / "scripts" / "new.py").write_text("n = 1\n")
        self.call()
        self.assertEqual(1, len(self.lines("UNGRANTED DELETED .claude/hooks/x.py")))
        self.assertEqual(1, len(self.lines("UNGRANTED ADDED scripts/new.py")))
        self.call()   # baseline advanced: no repeat
        self.assertEqual(2, len(self.lines("UNGRANTED")))

    def test_compact_after_ungranted_does_not_relaunder(self):
        self.start()
        (self.root / "CLAUDE.md").write_text("x\n")
        self.call()
        self.start("compact")
        (self.root / "CLAUDE.md").write_text("y\n")
        self.call()
        self.assertEqual(2, len(self.lines("UNGRANTED CHANGED CLAUDE.md")))

    # --- grants -------------------------------------------------------------
    def test_consumed_line_covers_exactly_one_difference(self):
        self.start()
        self.consumed("CLAUDE.md")
        (self.root / "CLAUDE.md").write_text("granted edit\n")
        self.call("Edit")
        self.assertEqual(1, len(self.lines("granted CHANGED CLAUDE.md")))
        self.assertEqual([], self.lines("UNGRANTED"))
        # review-02 M2: the same grant does not cover a second change
        self.git("checkout", "-q", "--", "CLAUDE.md")
        self.call()
        self.assertEqual(1, len(self.lines("UNGRANTED CHANGED CLAUDE.md")))

    def test_two_edits_under_one_task_grant_are_both_granted(self):
        # T8: a task grant is never spent, and
        # policy-mutate writes one consumed line per ALLOWED hit -- so N edits
        # leave N credits and each covers one difference.
        self.start()
        for text in ("task edit 1\n", "task edit 2\n"):
            self.edit_under_task_grant("CLAUDE.md")
            (self.root / "CLAUDE.md").write_text(text)
            self.call("Edit")
        self.assertEqual(2, len(self.lines("granted CHANGED CLAUDE.md")))
        self.assertEqual([], self.lines("UNGRANTED"))

    def test_a_credit_dies_with_revoke(self):
        # S2-1 (a), review finding: a hit that changed no bytes minted a credit, and
        # that credit covered a gate-blind change AFTER revoke-policy as
        # `granted`. The revoke line is this sid's marker; credits before it
        # stop counting.
        self.start()
        self.assertIn("task unlock armed", self.prompt("auth-policy CLAUDE.md"))
        self.noop_hit()
        self.call("Write")
        self.assertEqual([], self.lines("granted") + self.lines("UNGRANTED"))
        self.assertIn("revoked", self.prompt("revoke-policy"))
        (self.root / "CLAUDE.md").write_text("gate-blind write after revoke\n")
        self.call("Bash")
        self.assertEqual(1, len(self.lines("UNGRANTED CHANGED CLAUDE.md")))
        self.assertEqual([], self.lines("granted"))

    def test_a_rearm_voids_the_old_credit(self):
        # S2-1 (b): a new unlock replaces the whole grant, so the armed line
        # is a marker too; the new grant's own credits count from it on.
        self.start()
        self.prompt("auth-policy CLAUDE.md")
        self.noop_hit()
        self.assertIn("REPLACED", self.prompt("auth-policy AGENTS.md"))
        (self.root / "CLAUDE.md").write_text("gate-blind write after re-arm\n")
        self.call("Bash")
        self.assertEqual(1, len(self.lines("UNGRANTED CHANGED CLAUDE.md")))
        self.assertTrue(self.mutate("Write", {"file_path": str(self.root / "AGENTS.md"),
                                              "content": "agents\n"}))
        (self.root / "AGENTS.md").write_text("agents\n")
        self.call("Write")
        self.assertEqual(1, len(self.lines("granted ADDED AGENTS.md")))
        self.assertEqual(1, len(self.lines("UNGRANTED")))

    def test_another_sids_marker_voids_nothing(self):
        # S2-1 (c): the marker is keyed by sid, like the credit. Another
        # session's revoke (no grant there: "nothing to revoke") and another
        # session's arm both leave this session's live credit standing.
        self.start()
        self.prompt("auth-policy CLAUDE.md")
        self.noop_hit()
        self.assertIn("nothing to revoke", self.prompt("revoke-policy", sid=OTHER))
        self.prompt("auth-policy AGENTS.md", sid=OTHER)
        (self.root / "CLAUDE.md").write_text("changed under A's live credit\n")
        self.call("Bash")
        self.assertEqual(1, len(self.lines("granted CHANGED CLAUDE.md")))
        self.assertEqual([], self.lines("UNGRANTED"))

    def in_process(self):
        """The hook as a module rooted at this tree, for `consumed_lines(now=)`."""
        import importlib.util
        from unittest import mock
        with mock.patch.dict(os.environ, {"HARNESS_ROOT": str(self.root)}):
            spec = importlib.util.spec_from_file_location("pi", str(HOOK))
            pi = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(pi)
        return pi

    def at(self, hhmmss):
        return time.mktime(time.strptime(
            time.strftime("%Y-%m-%d ") + hhmmss, "%Y-%m-%d %H:%M:%S"))

    def test_a_credit_older_than_the_grant_cap_counts_not(self):
        # S2-1 (d), no arm marker today (armed before midnight, or legacy):
        # the cap is 28800 s from the line's own stamp. In-process with `now`
        # pinned to noon, so the case is the same at any hour: 04:00:00 is
        # exactly 28800 s old (void), 04:00:01 is 28799 s (counts), and a
        # line stamped now counts.
        pi, day = self.in_process(), time.strftime("%Y-%m-%d")
        self.consumed("CLAUDE.md", stamp="04:00:00")
        self.consumed("CLAUDE.md", stamp="04:00:01")
        self.consumed("CLAUDE.md", stamp="12:00:00")
        self.assertEqual([day + ":1", day + ":2"],
                         [k for k, _ in pi.consumed_lines(SID, now=self.at("12:00:00"))])

    def test_the_cap_runs_from_arming_not_from_the_credit(self):
        # Operator ruling: a grant ends 8 h after ARMING, so a credit minted
        # late in the grant dies with it -- armed 00:00:00, credit 07:59:59,
        # void at 08:00:00 (alive one second earlier). The same credit with
        # no arm marker would count until 15:59:59 (the case above).
        pi, day = self.in_process(), time.strftime("%Y-%m-%d")
        with open(self.root / ".agent-log" / (day + ".md"), "a", encoding="utf-8") as f:
            f.write("- 00:00:00 [policy-prompt] unlock-armed (policy): CLAUDE.md sid=%s\n" % SID)
        self.consumed("CLAUDE.md", stamp="07:59:59")
        self.assertEqual([day + ":1"],
                         [k for k, _ in pi.consumed_lines(SID, now=self.at("07:59:59"))])
        self.assertEqual([], pi.consumed_lines(SID, now=self.at("08:00:00")))

    def test_grant_for_another_session_reads_peer_granted_once(self):
        # A peer's live credit covers its
        # difference here too, labelled with the peer's sid and no alert --
        # still one difference per credit.
        self.start()
        self.consumed("CLAUDE.md", sid=OTHER)
        (self.root / "CLAUDE.md").write_text("other session's grant\n")
        out = self.call()
        self.assertEqual(1, len(self.lines("PEER-GRANTED CHANGED CLAUDE.md")), self.log())
        self.assertIn("sid=" + OTHER, self.lines("PEER-GRANTED")[0])
        self.assertEqual([], self.lines("UNGRANTED") + self.lines("granted"))
        self.assertNotIn("UNGRANTED", out)
        (self.root / "CLAUDE.md").write_text("second change, no credit\n")
        self.call()
        self.assertEqual(1, len(self.lines("UNGRANTED CHANGED CLAUDE.md")))

    def test_peer_spare_covers_a_gate_blind_write_here(self):
        # Review finding, a kept ceiling, stated: B's no-byte hit mints a spare; A, with no grant,
        # writes through open() and reads PEER-GRANTED sid=B, no alert.
        self.start()
        self.prompt("auth-policy CLAUDE.md", sid=OTHER)
        content = (self.root / "CLAUDE.md").read_text()
        self.assertTrue(self.mutate("Write", {"file_path": str(self.root / "CLAUDE.md"),
                                              "content": content}, sid=OTHER))
        (self.root / "CLAUDE.md").write_text("A's gate-blind write\n")
        out = self.call()
        self.assertEqual(1, len(self.lines("PEER-GRANTED CHANGED CLAUDE.md")), self.log())
        self.assertNotIn("UNGRANTED", out)

    def test_empty_sid_credit_is_nobodys_grant(self):
        self.start()
        self.consumed("CLAUDE.md", sid="")
        (self.root / "CLAUDE.md").write_text("under an empty-sid credit\n")
        self.call()
        self.assertEqual(1, len(self.lines("UNGRANTED CHANGED CLAUDE.md")), self.log())
        self.assertEqual([], self.lines("PEER-GRANTED"))

    def test_peer_credit_dies_with_the_peers_revoke(self):
        # the peer's own marker voids its credit here, as it does there
        self.start()
        self.prompt("auth-policy CLAUDE.md", sid=OTHER)
        self.consumed("CLAUDE.md", sid=OTHER)
        self.assertIn("revoked", self.prompt("revoke-policy", sid=OTHER))
        (self.root / "CLAUDE.md").write_text("after the peer's revoke\n")
        self.call()
        self.assertEqual(1, len(self.lines("UNGRANTED CHANGED CLAUDE.md")))
        self.assertEqual([], self.lines("PEER-GRANTED"))

    # --- merged --------------------
    def commit(self, msg):
        self.git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qam", msg)

    def set_default(self, name):
        # origin's default branch is origin/HEAD's target, as a clone records it.
        self.git("update-ref", "refs/remotes/origin/" + name, "HEAD")
        self.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/" + name)

    def test_pull_of_origin_master_reads_merged(self):
        (self.root / "CLAUDE.md").write_text("merged upstream\n")
        (self.root / ".claude" / "hooks" / "new.py").write_text("new\n")
        self.git("add", "-A")
        self.commit("upstream")
        self.set_default("master")
        self.git("reset", "-q", "--hard", "HEAD~1")
        self.start()
        self.git("merge", "-q", "--ff-only", "refs/remotes/origin/HEAD")
        out = self.call()
        self.assertEqual(1, len(self.lines("MERGED CHANGED CLAUDE.md")), self.log())
        self.assertEqual(1, len(self.lines("MERGED ADDED .claude/hooks/new.py")), self.log())
        self.assertEqual([], self.lines("UNGRANTED"))
        self.assertNotIn("UNGRANTED", out)

    def test_crlf_rewrite_of_an_eol_lf_file_is_not_merged(self):
        # Review finding: `hash-object` normalises line endings, so a CRLF rewrite of
        # an `eol=lf` pre-push hook (git then skips it) matched master's blob.
        # MERGED compares the bytes a checkout would write.
        (self.root / ".gitattributes").write_bytes(b"CLAUDE.md text eol=lf\n")
        (self.root / "CLAUDE.md").write_bytes(b"lf only\n")
        self.git("add", "-A")
        self.commit("lf")
        self.set_default("master")
        self.start()
        (self.root / "CLAUDE.md").write_bytes(b"lf only\r\n")
        self.call()
        self.assertEqual(1, len(self.lines("UNGRANTED CHANGED CLAUDE.md")), self.log())
        (self.root / "CLAUDE.md").write_bytes(b"lf only\n")
        self.call()
        self.assertEqual(1, len(self.lines("MERGED CHANGED CLAUDE.md")), self.log())
        # Review finding: flipping the rule in the (unwatched) working-tree
        # .gitattributes first must not make the CRLF rewrite read MERGED
        with open(self.root / ".gitattributes", "ab") as f:
            f.write(b"CLAUDE.md text eol=crlf\n")
        (self.root / "CLAUDE.md").write_bytes(b"lf only\r\n")
        self.call()
        self.assertEqual(2, len(self.lines("UNGRANTED CHANGED CLAUDE.md")), self.log())
        self.assertEqual(1, len(self.lines("MERGED")))

    def test_revert_to_master_bytes_reads_merged(self):
        # Review finding, accepted and documented: with the ref present, the gate design rows 58/63 read MERGED once the
        # bytes are master's again.
        self.set_default("master")
        self.start()
        self.consumed("CLAUDE.md")
        (self.root / "CLAUDE.md").write_text("granted edit\n")
        self.call("Edit")
        self.git("checkout", "-q", "--", "CLAUDE.md")
        self.call()
        self.assertEqual(1, len(self.lines("granted CHANGED CLAUDE.md")))
        self.assertEqual(1, len(self.lines("MERGED CHANGED CLAUDE.md")), self.log())
        self.assertEqual([], self.lines("UNGRANTED"))

    def test_same_call_commit_is_not_merged(self):
        # the laundering the ruling's re-ask named: bytes equal HEAD, not master
        self.set_default("master")
        self.start()
        (self.root / "CLAUDE.md").write_text("edited and committed in one call\n")
        self.commit("sneak")
        self.call()
        self.assertEqual(1, len(self.lines("UNGRANTED CHANGED CLAUDE.md")))
        self.assertEqual([], self.lines("MERGED"))

    def test_no_origin_master_ref_is_ungranted(self):
        self.start()
        (self.root / "scripts" / "a.py").write_text("a = 3\n")
        self.call()
        self.assertEqual(1, len(self.lines("UNGRANTED CHANGED scripts/a.py")))

    def test_default_branch_not_named_master_reads_merged(self):
        # (a): the default branch is whatever origin/HEAD names (build-1 today).
        (self.root / "CLAUDE.md").write_text("merged upstream\n")
        self.git("add", "-A")
        self.commit("upstream")
        self.set_default("build-1")
        self.git("reset", "-q", "--hard", "HEAD~1")
        self.start()
        self.git("merge", "-q", "--ff-only", "refs/remotes/origin/build-1")
        self.call()
        self.assertEqual(1, len(self.lines("MERGED CHANGED CLAUDE.md")), self.log())
        self.assertEqual([], self.lines("UNGRANTED"))

    def test_a_move_of_origin_head_is_recorded(self):
        # F16: every gate reads the default branch from origin/HEAD, so a
        # local retarget of it is a policy change on record, never silent.
        self.set_default("main")
        self.git("update-ref", "refs/remotes/origin/lane-1", "HEAD")
        self.start()
        self.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/lane-1")
        self.call()
        self.assertEqual(1, len(self.lines(
            "UNGRANTED CHANGED .git/refs/remotes/origin/HEAD")), self.log())

    def test_master_ref_without_origin_head_is_ungranted(self):
        # A master-named ref is not the default branch unless origin/HEAD says so.
        (self.root / "CLAUDE.md").write_text("merged upstream\n")
        self.git("add", "-A")
        self.commit("upstream")
        self.git("update-ref", "refs/remotes/origin/master", "HEAD")
        self.git("reset", "-q", "--hard", "HEAD~1")
        self.start()
        self.git("merge", "-q", "--ff-only", "refs/remotes/origin/master")
        self.call()
        self.assertEqual(1, len(self.lines("UNGRANTED CHANGED CLAUDE.md")), self.log())
        self.assertEqual([], self.lines("MERGED"))

    def test_ledger_outlives_the_grant_file_until_a_marker(self):
        # The ledger is the day log, not the grant file (mechanism 5): the
        # FILE going away or being overwritten voids nothing by itself. What
        # voids is a policy-prompt marker line for this sid (666 S2-1, the
        # re-arm case above); here the file is overwritten directly, no
        # marker, so the credit stands.
        self.start()
        self.consumed(".claude/hooks/new.py")
        (self.root / ".claude" / "hooks" / "new.py").write_text("n\n")
        (self.root / ".agent-log" / ("policy-unlock-%s.json" % SID)).write_text("{}")
        self.call("Write")
        self.assertEqual(1, len(self.lines("granted ADDED .claude/hooks/new.py")))

    def test_unspent_grant_covers_nothing(self):
        self.start()
        (self.root / ".agent-log" / ("policy-unlock-%s.json" % SID)).write_text(
            json.dumps({"path": "CLAUDE.md", "used": False}))
        (self.root / "CLAUDE.md").write_text("git restore, gate blind\n")
        self.call()
        self.assertEqual(1, len(self.lines("UNGRANTED CHANGED CLAUDE.md")))

    # --- roots --------------------------------------------------------------
    def test_worktree_present_at_baseline_reports_root_relative(self):
        wt = self.root / "worktrees" / "lane"
        (wt / ".claude" / "agents").mkdir(parents=True)
        (wt / ".claude" / "agents" / "r.md").write_text("role\n")
        (wt / "CLAUDE.md").write_text("wt contract\n")
        self.start()
        (wt / ".claude" / "agents" / "r.md").write_text("role changed\n")
        self.call()
        self.assertEqual(
            1, len(self.lines("UNGRANTED CHANGED worktrees/lane/.claude/agents/r.md")))

    def test_new_root_is_one_line_then_gone_root(self):
        self.start()
        wt = self.root / "worktrees" / "x"
        (wt / ".claude" / "hooks").mkdir(parents=True)
        for i in range(5):
            (wt / ".claude" / "hooks" / ("h%d.py" % i)).write_text("h\n")
        self.call()
        self.assertEqual(1, len(self.lines("NEW-ROOT worktrees/x 5 paths")))
        self.assertEqual([], self.lines("UNGRANTED"))
        (wt / ".claude" / "hooks" / "h1.py").write_text("changed\n")
        self.call()
        self.assertEqual(1, len(self.lines("UNGRANTED CHANGED worktrees/x/.claude/hooks/h1.py")))
        shutil.rmtree(wt)
        self.call()
        self.assertEqual(1, len(self.lines("GONE-ROOT worktrees/x")))

    def test_worktree_mid_removal_is_one_root_removed_line(self):
        # `git worktree remove` empties the tree before the directory
        # goes; a compare in between logged one DELETED per policy file.
        wt = self.root / "worktrees" / "x"
        (wt / ".claude" / "hooks").mkdir(parents=True)
        for i in range(5):
            (wt / ".claude" / "hooks" / ("h%d.py" % i)).write_text("h\n")
        self.start()
        shutil.rmtree(wt / ".claude")
        out = self.call()
        self.assertEqual(1, len(self.lines("ROOT-REMOVED worktrees/x (5 policy files)")), self.log())
        self.assertEqual([], self.lines("UNGRANTED"))
        self.assertNotIn("UNGRANTED", out)
        shutil.rmtree(wt)
        self.call()
        self.assertEqual(1, len(self.lines("GONE-ROOT worktrees/x")))
        self.assertEqual(1, len(self.lines("ROOT-REMOVED")))

    def test_partial_worktree_delete_and_main_tree_never_collapse(self):
        wt = self.root / "worktrees" / "x"
        (wt / ".claude" / "hooks").mkdir(parents=True)
        for i in range(2):
            (wt / ".claude" / "hooks" / ("h%d.py" % i)).write_text("h\n")
        # Review finding: git init's .git/hooks samples and info/exclude kept the
        # main tree non-empty, so the `rr != "."` guard was never tested
        for d in (".git/hooks", ".git/info"):
            for f in self.root.joinpath(*d.split("/")).iterdir():
                f.unlink()
        self.start()
        (wt / ".claude" / "hooks" / "h0.py").unlink()
        for rel in ("CLAUDE.md", ".claude/hooks/x.py", "scripts/a.py", ".git/config"):
            self.root.joinpath(*rel.split("/")).unlink()
        self.call()
        self.assertEqual(1, len(self.lines("UNGRANTED DELETED worktrees/x/.claude/hooks/h0.py")))
        self.assertEqual(4, len([l for l in self.lines("UNGRANTED DELETED ")
                                 if "worktrees/" not in l]), self.log())
        self.assertEqual([], self.lines("ROOT-REMOVED"))

    def test_tracked_nested_claude_md_is_seen_and_stays_seen(self):
        (self.root / "docs" / "e").mkdir(parents=True)
        (self.root / "docs" / "e" / "CLAUDE.md").write_text("nested\n")
        self.git("-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
        self.git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "nested")
        self.start()
        self.call()
        self.assertEqual([], self.lines("UNGRANTED"))   # not DELETED on compare
        (self.root / "docs" / "e" / "CLAUDE.md").write_text("nested changed\n")
        self.call()
        self.assertEqual(1, len(self.lines("UNGRANTED CHANGED docs/e/CLAUDE.md")))

    def test_commit_on_a_branch_writes_no_line(self):
        self.start()
        (self.root / "notes.md").write_text("commit fodder\n")
        self.git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qam", "n")
        self.call()
        self.assertEqual([], self.lines("UNGRANTED") + self.lines("granted"))

    def test_no_baseline_takes_a_late_one_instead_of_flooding(self):
        (self.root / "CLAUDE.md").write_text("pre-existing\n")
        self.call()
        self.assertEqual(1, len(self.lines("BASELINE late")))
        self.assertEqual([], self.lines("UNGRANTED"))

    def test_noop_compare_creates_no_file_and_keeps_baseline_bytes(self):
        self.start()
        bp = self.root / ".agent-log" / ("policy-baseline-unlock-%s.json" % SID)
        before, names = bp.read_bytes(), set(os.listdir(self.root / ".agent-log"))
        self.call()
        self.assertEqual(before, bp.read_bytes())
        self.assertEqual(names, set(os.listdir(self.root / ".agent-log")))

    def test_concurrent_calls_advance_once_and_never_rebaseline(self):
        # review-01 F1: the loser of the claim race must skip, not take a fresh
        # baseline over the winner's matched set
        self.start()
        self.consumed("CLAUDE.md")
        (self.root / "CLAUDE.md").write_text("raced\n")
        payload = json.dumps({"session_id": SID, "hook_event_name": "PostToolUse",
                              "tool_name": "Bash", "tool_input": {}, "cwd": str(self.root)})
        procs = [subprocess.Popen([sys.executable, str(HOOK)], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  env=self.env) for _ in range(6)]
        for p in procs:
            p.communicate(payload.encode(), timeout=60)
            self.assertEqual(0, p.returncode)
        self.assertEqual(1, len(self.lines("granted CHANGED CLAUDE.md")))
        self.assertEqual([], self.lines("UNGRANTED") + self.lines("BASELINE late"))
        bp = self.root / ".agent-log" / ("policy-baseline-unlock-%s.json" % SID)
        self.assertEqual(1, len(json.loads(bp.read_text())["matched"]))
        self.assertEqual([], [n for n in os.listdir(self.root / ".agent-log") if ".claim." in n])

    def test_skipped_compare_is_caught_on_resume_not_laundered(self):
        # review-02 F3: a fresh peer claim makes this call skip; if nothing
        # else fires before resume, resume must still record the change
        self.start()
        bp = self.root / ".agent-log" / ("policy-baseline-unlock-%s.json" % SID)
        claim = Path(str(bp) + ".claim.99999")
        bp.rename(claim)
        (self.root / "CLAUDE.md").write_text("raced then resumed\n")
        self.call()
        self.assertEqual(1, len(self.lines("skipped")))
        self.assertEqual([], self.lines("UNGRANTED"))
        claim.rename(bp)          # the peer finishes
        self.start("resume")
        self.assertEqual(1, len(self.lines("UNGRANTED CHANGED CLAUDE.md")))
        self.assertEqual(1, len(self.lines("BASELINE")))

    def _bp(self):
        return self.root / ".agent-log" / ("policy-baseline-unlock-%s.json" % SID)

    def _holder(self, claimed_ago=0):
        # The hook loaded in this process plays the holder H, so a test can
        # run a real peer call (a subprocess) while H is inside its compare.
        # claimed_ago backdates H's claim stamp, the first clock read in compare.
        # HARNESS_ROOT stays set for the test: compare imports policy-mutate late.
        import importlib.util
        from unittest import mock
        env = mock.patch.dict(os.environ, {"HARNESS_ROOT": str(self.root)})
        env.start()
        self.addCleanup(env.stop)
        spec = importlib.util.spec_from_file_location("pi_holder", str(HOOK))
        pi = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pi)
        real, first = pi.time, [claimed_ago]

        class Clock:
            def __getattr__(self, n):
                return getattr(real, n)

            def time(self):
                t, first[0] = real.time() - first[0], 0
                return t
        pi.time = Clock()
        return pi

    def _run_holder(self, pi):
        import contextlib, io
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            pi.compare(SID, pi._is_policy())
        return out.getvalue()

    def test_fresh_claim_on_an_idle_baseline_is_not_stolen(self):
        # A rename keeps the baseline's mtime (its last write), so a
        # claim taken now on a baseline written a minute ago read as a crashed
        # peer; the peer stole it and the holder's hand-back raised [Errno 2].
        # The holder is a real compare, so the claim name it writes is pinned.
        self.start()
        old = time.time() - 60
        os.utime(self._bp(), (old, old))
        (self.root / "CLAUDE.md").write_text("changed while held\n")
        pi, held = self._holder(), []
        live = pi.live_credits

        def peer_runs_now(*a, **k):
            self.call()
            held.append([n for n in os.listdir(self.root / ".agent-log")
                         if ".claim.%d." % os.getpid() in n])
            return live(*a, **k)
        pi.live_credits = peer_runs_now
        self._run_holder(pi)
        self.assertEqual(1, len(self.lines("skipped")))
        self.assertEqual(1, len(held[0]))
        self.assertEqual(1, len(self.lines("UNGRANTED CHANGED CLAUDE.md")))
        self.assertEqual([], self.lines("hook error") + self.lines("claim recovered"))

    def test_a_holder_past_30s_logs_its_lines_when_a_peer_recovers(self):
        # Review finding: H sees an ungranted write, then it is reverted and a peer
        # recovers H's claim and sees no difference. H must still log the write.
        self.start()
        before = (self.root / "CLAUDE.md").read_text()
        (self.root / "CLAUDE.md").write_text("written then reverted\n")
        pi = self._holder(claimed_ago=60)
        real = pi.on_master

        def revert_then_peer(*a, **k):
            (self.root / "CLAUDE.md").write_text(before)
            self.call()
            return real(*a, **k)
        pi.on_master = revert_then_peer
        self._run_holder(pi)
        self.assertEqual(1, len(self.lines("UNGRANTED CHANGED CLAUDE.md")))
        self.assertEqual(1, len(self.lines("claim recovered by a peer after 30 s; baseline not written")))
        self.call()
        self.assertEqual(1, len(self.lines("UNGRANTED")))

    def test_a_holder_past_30s_writes_no_baseline_over_the_peer(self):
        # Review finding, regrant: after H's snapshot a credit and a third write land
        # and the peer spends the credit. H writing its baseline after the
        # peer's would let that one credit match a second time on the next call.
        self.start()
        (self.root / "CLAUDE.md").write_text("first write\n")
        pi = self._holder(claimed_ago=60)
        real = pi.on_master

        def regrant_then_peer(*a, **k):
            self.consumed("CLAUDE.md")
            (self.root / "CLAUDE.md").write_text("third write\n")
            self.call()
            return real(*a, **k)
        pi.on_master = regrant_then_peer
        self._run_holder(pi)
        self.call()
        self.assertEqual(1, len(self.lines("granted CHANGED CLAUDE.md")))
        self.assertEqual(1, len(self.lines("UNGRANTED CHANGED CLAUDE.md")))

    def test_a_lost_holder_does_not_spend_a_credit_the_peer_spends(self):
        # a holder past 30 s matched a credit, then a peer recovered the claim
        # and matched the same one. The holder cannot record its match, so its
        # line reads UNGRANTED: one credit, one `granted` line.
        self.start()
        self.consumed("CLAUDE.md")
        (self.root / "CLAUDE.md").write_text("granted write\n")
        pi = self._holder(claimed_ago=60)
        real = pi.snapshot

        def peer_after_snapshot(*a, **k):
            out = real(*a, **k)
            self.call()
            return out
        pi.snapshot = peer_after_snapshot
        self._run_holder(pi)
        self.assertEqual(1, len(self.lines("granted CHANGED CLAUDE.md")))
        lost = self.lines("UNGRANTED CHANGED CLAUDE.md")
        self.assertEqual(1, len(lost))
        self.assertIn("(claim lost; credit not recorded)", lost[0])

    def test_a_lost_holder_does_not_spend_a_peer_credit_the_peer_spends(self):
        # Review finding: the same on the peer channel, and the holder's alert counts
        # the downgraded line
        self.start()
        self.consumed("CLAUDE.md", sid=OTHER)
        (self.root / "CLAUDE.md").write_text("peer-granted write\n")
        pi = self._holder(claimed_ago=60)
        real = pi.snapshot

        def peer_after_snapshot(*a, **k):
            out = real(*a, **k)
            self.call()
            return out
        pi.snapshot = peer_after_snapshot
        said = self._run_holder(pi)
        self.assertEqual(1, len(self.lines("PEER-GRANTED CHANGED CLAUDE.md")))
        self.assertEqual(1, len(self.lines("UNGRANTED CHANGED CLAUDE.md")))
        self.assertIn("1 UNGRANTED", said)

    def test_a_holder_with_nothing_to_hand_back_does_not_raise(self):
        # 844 fix 2: a peer recovered the claim of a no-op holder; the hand-back
        # finds no claim. Was an uncaught [Errno 2], logged as `hook error`.
        self.start()
        pi = self._holder(claimed_ago=60)
        live = pi.live_credits

        def peer_runs_now(*a, **k):
            self.call()
            return live(*a, **k)
        pi.live_credits = peer_runs_now
        self._run_holder(pi)
        self.assertEqual(1, len(self.lines("claim gone at hand-back")))
        self.assertTrue(self._bp().exists())

    def _recover(self, legacy):
        # the crashed-peer path still works, by the name's stamp and, for a
        # legacy `.claim.<pid>` name, by mtime
        self.start()
        bp, old = self._bp(), time.time() - 60
        name = "%s.claim.99999" % bp if legacy else "%s.claim.99999.%d" % (bp, int(old))
        bp.rename(name)
        os.utime(name, (old, old))
        (self.root / "CLAUDE.md").write_text("after a crash\n")
        self.call()
        self.assertEqual(1, len(self.lines("UNGRANTED CHANGED CLAUDE.md")))
        self.assertFalse(Path(name).exists())

    def test_a_stamped_claim_held_past_30s_is_recovered(self):
        self._recover(legacy=False)

    def test_a_legacy_claim_held_past_30s_is_recovered(self):
        self._recover(legacy=True)

    def test_a_planted_claim_name_never_raises(self):
        # Review finding, review finding: the stamp is parsed from a listed name. Junk, a
        # non-ASCII digit and a far-future stamp are not a crashed peer.
        self.start()
        bp = self._bp()
        for tail in ("1.junk", "1.\u00b2", "1.99999999999999999999"):
            name = "%s.claim.%s" % (bp, tail)
            bp.rename(name)
            self.call()
            Path(name).rename(bp)
        self.assertEqual(3, len(self.lines("skipped")))
        self.assertEqual([], self.lines("hook error"))

    def test_log_path_is_sanitised(self):
        self.start()
        (self.root / "scripts" / ("x" * 230 + ".py")).write_text("b\n")
        self.call()
        line = self.lines("UNGRANTED ADDED")[0]
        self.assertLess(len(line), 260)
        # control characters never reach the log, whatever the filesystem allows
        import importlib.util
        spec = importlib.util.spec_from_file_location("pi", str(HOOK))
        pi = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pi)
        self.assertEqual("a?b/c", pi.safe("a\x07b\\c"))


if __name__ == "__main__":
    unittest.main()
