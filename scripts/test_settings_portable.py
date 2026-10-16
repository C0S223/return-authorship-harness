"""settings.json names no host path; every hook command is
rooted at $CLAUDE_PROJECT_DIR so the same file runs on the Windows host, a
managed cloud VM and a self-hosted container. Fails on any drive
letter, home directory or backslash in a hook command."""
import json
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS = os.path.join(ROOT, ".claude", "settings.json")


def commands():
    with open(SETTINGS, encoding="utf-8") as f:
        cfg = json.load(f)
    for groups in cfg.get("hooks", {}).values():
        for g in groups:
            for h in g.get("hooks", []):
                if h.get("type") == "command":
                    yield h["command"]


class SettingsPortable(unittest.TestCase):
    def test_no_host_path(self):
        raw = open(SETTINGS, encoding="utf-8").read()
        self.assertFalse(re.search(r"[A-Za-z]:[/\\]|/Users/|/home/", raw))

    def test_every_hook_rooted_at_project_dir(self):
        cmds = list(commands())
        self.assertTrue(cmds)
        for c in cmds:
            # The quoted `"$CLAUDE_PROJECT_DIR/..."` is the only accepted form:
            # a project path with a space must still resolve (preflight reads it).
            self.assertRegex(c, r'^(python|bash) "\$CLAUDE_PROJECT_DIR/\.claude/hooks/[^"\s]+"$', c)


if __name__ == "__main__":
    unittest.main()
