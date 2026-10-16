"""A tool call that errors fires PostToolUseFailure, not PostToolUse
(Claude Code 2.1.277). A record-keeping hook registered only for PostToolUse
misses exactly the calls that tried and failed -- an escape attempt, or a
policy-path write whose command then exited non-zero.

    python scripts/test_failure_hooks.py
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_policy_integrity as tpi  # noqa: E402  (module, so its Case is not collected here)

SETTINGS = tpi.ROOT / ".claude" / "settings.json"
# ponytail: advisory only -- a failed call skips one context sample (review
# finding R4). A new PostToolUse hook lands here with its reason,
# or under PostToolUseFailure too.
NOT_FOR_FAILURES = {'bash "$CLAUDE_PROJECT_DIR/.claude/hooks/auto-compact/check.sh"'}


def pairs(event):
    cfg = json.loads(SETTINGS.read_text(encoding="utf-8"))
    return {(g.get("matcher", ""), h["command"])
            for g in cfg["hooks"].get(event, []) for h in g["hooks"]}


class Registration(unittest.TestCase):
    def test_every_post_tool_use_hook_also_runs_on_failure(self):
        want = {p for p in pairs("PostToolUse") if p[1] not in NOT_FOR_FAILURES}
        self.assertTrue(want)
        self.assertEqual(set(), want - pairs("PostToolUseFailure"))


class FailurePayload(unittest.TestCase):
    setUp, tearDown = tpi.Case.setUp, tpi.Case.tearDown
    git, hook, start, log, lines = (tpi.Case.git, tpi.Case.hook, tpi.Case.start,
                                    tpi.Case.log, tpi.Case.lines)

    def test_policy_integrity_compares_on_a_failed_writer_call(self):
        self.start()
        (self.root / "CLAUDE.md").write_text("contract v2\n")
        # the shape 2.1.277 builds for PostToolUseFailure
        self.hook({"session_id": tpi.SID, "hook_event_name": "PostToolUseFailure",
                   "tool_name": "Bash", "tool_input": {"command": "sed -i s/1/2/ CLAUDE.md && false"},
                   "tool_use_id": "toolu_x", "error": "Exit code 1", "is_interrupt": False,
                   "cwd": str(self.root)})
        self.assertEqual(1, len(self.lines("UNGRANTED CHANGED CLAUDE.md")))


if __name__ == "__main__":
    unittest.main()
