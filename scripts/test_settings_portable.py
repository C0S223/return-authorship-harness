"""settings.json names no host path; every hook command is
rooted at $CLAUDE_PROJECT_DIR so the same file runs on the Windows host, a
managed cloud VM and a self-hosted container. Fails on any drive
letter, home directory or backslash in a hook command.

Since lane 6175 every command also has one exact shape: a guard that exits 2
with a plain line when its file is missing (a bare `bash <missing>` exits 127,
which never blocks: the first-user fail-open), then `bash` on that file. A
Python hook's file is `run-python.sh`, which picks python3 or python and runs
the hook named after it. Two departures, each with its reason below."""
import json
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS = os.path.join(ROOT, ".claude", "settings.json")

MSG = ("Safety check file missing: $f. If this folder was moved or renamed, restart "
       "Claude Code from it; otherwise restore the file with git.")
# Stop exits 1, not 2: exit 2 on Stop refuses the stop, so a missing
# session-close.sh would keep the session from ever ending (session-close.sh's
# own stop_hook_active note names the same loop).
STOP_CODE = 1
# scripts/test_failure_hooks.py pins this exact string, and it was outside
# lane 6175's grant. On PostToolUse neither 127 nor 2 can block, so the cost is
# where a missing file's error shows; preflight still blocks every prompt on it.
LEGACY = {'bash "$CLAUDE_PROJECT_DIR/.claude/hooks/auto-compact/check.sh"'}


def shaped(script, py=None, code=2):
    c = ('f="$CLAUDE_PROJECT_DIR/.claude/hooks/%s"; [ -f "$f" ] || { echo "%s" >&2; exit %d; }; '
         'bash "$f"' % (script, MSG, code))
    if py:
        c += ' "$CLAUDE_PROJECT_DIR/.claude/hooks/%s"' % py
    return c


def commands():
    with open(SETTINGS, encoding="utf-8") as f:
        cfg = json.load(f)
    for event, groups in cfg.get("hooks", {}).items():
        for g in groups:
            for h in g.get("hooks", []):
                if h.get("type") == "command":
                    yield event, h["command"]


class SettingsPortable(unittest.TestCase):
    def test_no_host_path(self):
        raw = open(SETTINGS, encoding="utf-8").read()
        self.assertFalse(re.search(r"[A-Za-z]:[/\\]|/Users/|/home/", raw))

    def test_every_hook_has_the_guarded_shape(self):
        cmds = list(commands())
        self.assertTrue(cmds)
        python_hooks = 0
        for event, c in cmds:
            if c in LEGACY:
                continue
            paths = re.findall(r'"\$CLAUDE_PROJECT_DIR/\.claude/hooks/([^"\s]+)"', c)
            self.assertIn(len(paths), (1, 2), c)
            code = STOP_CODE if event == "Stop" else 2
            if paths[0] == "run-python.sh":
                self.assertEqual(len(paths), 2, c)
                self.assertTrue(paths[1].endswith(".py"), c)
                python_hooks += 1
            else:
                self.assertEqual(len(paths), 1, c)
                self.assertTrue(paths[0].endswith(".sh"), c)
            self.assertEqual(c, shaped(*paths, code=code))
        self.assertGreater(python_hooks, 0)

    def test_no_python_hook_bypasses_the_launcher(self):
        for _, c in commands():
            self.assertNotRegex(c, r"(^|[;&|]\s*)python3?\s", c)

    def test_legacy_rows_are_still_wired(self):
        # A LEGACY entry that matches nothing is a dead exception.
        cmds = {c for _, c in commands()}
        self.assertEqual(LEGACY - cmds, set())


if __name__ == "__main__":
    unittest.main()
