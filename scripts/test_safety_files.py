#!/usr/bin/env python
"""The safety files still say what README.md says they say.

README.md's safety section describes `.claude/settings.json` and
`.codex/config.toml`; SETUP.md describes `.github/CODEOWNERS`. No other suite reads those
three files, so without this one any of them could be emptied with the tests
still green. It reads the files' text only: what a machine enforces is the
probe's question (`scripts/safety_probe.py`), not this suite's.
Reader: whoever edits one of the three files, or README.md's safety section.

    python scripts/test_safety_files.py
"""
import json
import re
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = (ROOT / ".claude" / "settings.json").read_text(encoding="utf-8")
SETTINGS = json.loads(RAW)

# Tools README.md says are denied outright.
DENIED = [
    "RemoteTrigger",
    "mcp__claude-code-remote__send_later",
    "mcp__claude-code-remote__watch_url",
    "mcp__claude-code-remote__update_trigger",
    "mcp__Claude_Code_Remote__send_later",
    "mcp__Claude_Code_Remote__watch_url",
    "mcp__Claude_Code_Remote__update_trigger",
    "mcp__claude-in-chrome__javascript_tool",
    "mcp__Claude_Browser__javascript_tool",
    "mcp__Claude_Browser__browser_batch",
    "mcp__claude-in-chrome__browser_batch",
    "Bash(claude plugin:*)",
    "Agent(general-purpose)",
    "Workflow",
]
# Tools README.md says ask first: another session, or a schedule.
ASKED = [
    "CronCreate",
    "mcp__scheduled-tasks__create_scheduled_task",
    "mcp__claude-code-remote__create_trigger",
    "mcp__Claude_Code_Remote__create_trigger",
    "mcp__claude-code-remote__create_session",
    "mcp__Claude_Code_Remote__create_session",
]
# The protected paths README.md lists: (file-tool deny rule, sandbox denyWrite entry).
PROTECTED = [
    ("Edit(**/CLAUDE.md)", "./CLAUDE.md"),
    ("Edit(**/AGENTS.md)", "./AGENTS.md"),
    ("Edit(/README.md)", "./README.md"),
    ("Edit(/.claude/**)", "./.claude"),
    ("Edit(/.codex/**)", "./.codex"),
    ("Edit(/.agents/**)", "./.agents"),
    ("Edit(/roles/**)", "./roles"),
    ("Edit(/graphs/**)", "./graphs"),
    ("Edit(/.githooks/**)", "./.githooks"),
    ("Edit(/.github/**)", "./.github"),
    ("Edit(/.git/config)", "./.git/config"),
    ("Edit(/.git/hooks/**)", "./.git/hooks"),
]
# The safety files CLAUDE.md names, as CODEOWNERS patterns.
OWNED = ["CLAUDE.md", "AGENTS.md", "/.claude/settings.json", "/.codex/config.toml", "/.github/**"]


class ClaudeSettings(unittest.TestCase):
    def test_the_sandbox_is_asked_for(self):
        sb = SETTINGS["sandbox"]
        self.assertIs(sb["enabled"], True)
        self.assertIs(sb["failIfUnavailable"], True)
        self.assertIs(sb["allowUnsandboxedCommands"], False)
        self.assertEqual(["~/.ssh", "~/.aws", "~/.gnupg"], sb["filesystem"]["denyRead"])
        hosts = sb["network"]["allowedDomains"]
        self.assertTrue(hosts)
        self.assertFalse([h for h in hosts if "*" in h], "a wildcard host")

    def test_the_denied_tools_are_denied(self):
        deny = SETTINGS["permissions"]["deny"]
        self.assertEqual([], [t for t in DENIED if t not in deny])

    def test_sessions_and_schedules_ask(self):
        ask = SETTINGS["permissions"]["ask"]
        self.assertEqual([], [t for t in ASKED if t not in ask])

    def test_each_protected_path_is_closed_to_file_tools_and_shell(self):
        deny = SETTINGS["permissions"]["deny"]
        deny_write = SETTINGS["sandbox"]["filesystem"]["denyWrite"]
        for rule, entry in PROTECTED:
            self.assertIn(rule, deny)
            self.assertIn(entry, deny_write)

    def test_hook_commands_name_files_in_this_checkout(self):
        self.assertIsNone(re.search(r"[A-Za-z]:[/\\]|/Users/|/home/", RAW), "a host path")
        cmds = [h["command"] for groups in SETTINGS.get("hooks", {}).values()
                for g in groups for h in g.get("hooks", []) if h.get("type") == "command"]
        self.assertTrue(cmds)
        for c in cmds:
            paths = re.findall(r'\$CLAUDE_PROJECT_DIR/([^"\s]+)', c)
            self.assertTrue(paths, c)
            for p in paths:
                self.assertTrue(p.startswith(".claude/hooks/"), c)
                self.assertTrue((ROOT / p).is_file(), "%s: no such file" % p)


class CodexConfig(unittest.TestCase):
    def test_the_codex_sandbox_is_asked_for(self):
        cfg = tomllib.loads((ROOT / ".codex" / "config.toml").read_text(encoding="utf-8"))
        self.assertEqual("on-request", cfg["approval_policy"])
        self.assertEqual("workspace-write", cfg["sandbox_mode"])
        self.assertIs(cfg["sandbox_workspace_write"]["network_access"], False)
        self.assertEqual(["CLAUDE.md"], cfg["project_doc_fallback_filenames"])


class Codeowners(unittest.TestCase):
    def test_every_safety_file_has_the_one_owner(self):
        rules = {}
        for ln in (ROOT / ".github" / "CODEOWNERS").read_text(encoding="utf-8").splitlines():
            ln = ln.split("#", 1)[0].split()
            if ln:
                rules[ln[0]] = ln[1:]
        self.assertEqual([], [p for p in OWNED if p not in rules])
        owners = {tuple(v) for v in rules.values()}
        self.assertEqual(1, len(owners), "more than one owner set: %r" % sorted(owners))
        self.assertEqual(1, len(next(iter(owners))), "each rule names exactly one owner")


if __name__ == "__main__":
    unittest.main()
