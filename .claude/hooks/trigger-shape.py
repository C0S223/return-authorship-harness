# trigger-shape — PreToolUse on the Routine tools.
# Single job: the only Routine an agent may create is a MAILBOX — poke-only,
# self-bound, carrying the fixed peer header. It decides from the tool name
# and argument KEYS: a field-presence check in the grain of spawn-roster's
# membership test, never text classification.
#   update_trigger          -> deny always (delete and reopen instead)
#   create_trigger          -> deny if any schedule / spawn / cross-bind field
#                              carries a value; deny if the stored prompt is
#                              missing, blank, or lacks the peer header
#   anything else           -> pass silently (over-broad wiring degrades to
#                              pass-through, not false denies)
# The header rule is what keeps a fired turn from ever being the bare text of
# an unlock verb: policy-prompt.py arms a grant only on a whole-message match.
# Undeterminable = deny (fail-closed). Every denial logs; allows do not.
import json
import os
import sys
import time
from datetime import datetime

TREE_ROOT = (os.environ.get("HARNESS_ROOT") or os.environ.get("CLAUDE_PROJECT_DIR")
        or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
LOG_DIR_ENV = "TRIGGER_SHAPE_LOG_DIR"   # test seam; unset in production

# Both server spellings: Claude_Code_Remote was live on managed
# 2026-09-17, claude-code-remote on 2026-10-04.
PREFIXES = ("mcp__claude-code-remote__", "mcp__Claude_Code_Remote__")
CREATE = tuple(p + "create_trigger" for p in PREFIXES)
UPDATE = tuple(p + "update_trigger" for p in PREFIXES)
# A field counts as ABSENT only when it is missing, null, false, or "". Any
# other value denies, `0` and "0" included: over-deny is the safe side.
L0_FIELDS = ("cron_expression", "run_once_at", "create_new_session_on_fire",
             "persistent_session_id")
HEADER = "[peer-mailbox]"


def deny(reason):
    try:
        d = os.environ.get(LOG_DIR_ENV) or os.path.join(TREE_ROOT, ".agent-log")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, time.strftime("%Y-%m-%d") + ".md"),
                  "a", encoding="utf-8") as f:
            f.write("- %s [trigger-shape] DENY %s\n"
                    % (datetime.now().strftime("%H:%M:%S"), reason))
    except Exception:
        pass
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": "trigger-shape: " + reason,
    }}))
    sys.exit(0)


def absent(value):
    return value is None or value is False or value == ""


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        deny("unreadable hook input — cannot verify the Routine's shape")
    if not isinstance(data, dict):
        deny("hook input is not an object — cannot verify the Routine's shape")
    tool = data.get("tool_name")
    if tool in UPDATE:
        deny("update_trigger is never used on a mailbox: delete it and reopen "
             "on the operator's word")
    if tool not in CREATE:
        sys.exit(0)
    args = data.get("tool_input")
    if not isinstance(args, dict):
        deny("create_trigger with no readable arguments")
    for field in L0_FIELDS:
        if not absent(args.get(field)):
            deny("create_trigger carries '%s': a Routine with a schedule, a new "
                 "session, or another session's id is L0 (CLAUDE.md s2)" % field)
    prompt = args.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip().startswith(HEADER):
        deny("create_trigger's stored prompt must begin with the '%s' header; "
             "a mailbox with no header lets a fired turn pass as the operator" % HEADER)
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # An uncaught raise exits 1, which Claude Code treats as
        # non-blocking, so a crash let the call through. Fail closed instead.
        deny("crashed (%s) -- refusing rather than passing the call ungated" % type(e).__name__)
