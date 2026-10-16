# spawn-roster — PreToolUse Agent|Task. Single job: block subagent spawns
# whose declared subagent_type is off the delegation roster; roster members
# pass silently; undeterminable = deny, never allow (fail-closed). Off-roster
# is deny, not ask: the unlock is a declared roster addition (policy edit),
# not per-call permission — improvised delegation is what the contract
# forbids. Self-guards tool_name, so over-broad wiring degrades to
# pass-through, not false denies. Every denial logs via deny(); allows do
# not — log-escape already records every executed spawn.
# codex is not in
# ROSTER (supervisor launch ONLY — an Agent-tool spawn typed codex is
# exactly what this hook must refuse). Residuals: docs/enforcement/CLAUDE.md, Roster maintenance.
import json
import os
import sys
import time
from datetime import datetime

TREE_ROOT = (os.environ.get("HARNESS_ROOT") or os.environ.get("CLAUDE_PROJECT_DIR")
        or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
LOG_DIR_ENV = "SPAWN_ROSTER_LOG_DIR"   # test seam; unset in production
LOG_DIR_NAME = ".agent-log"

# The delegation roster, from the contract's delegation clause (S2): six
# types. A roles/ persona is NOT an entry: it is read by
# its agent file, and this hook gates the type and nothing else. A persona
# earns its own type only by promotion — validated by kept runs recorded in
# the operator's ruling — and the promotion is this policy edit. That
# asymmetry is the point: a role costs a file, an entry here costs an unlock.
# "claude", "Plan", "codex" are retired, so the Agent-tool channel refuses them.
ROSTER = frozenset([
    "Explore",
    "claude-code-guide",
    "adversarial-reviewer",   # read-only
    "senior-engineer",        # promoted 2026-08-27; code change-sets. Bash IS
                              # in its grant, because its verdict enum requires
                              # execution — so it is write-less by PROMISE, not
                              # by grant, unlike recall below. Read that
                              # asymmetry before widening any grant here.

                              # A binding is THREE policy edits, not one:
                              # .claude/agents/<name>.md, CLAUDE.md's S2 roster
                              # clause, and this frozenset. ONLY THIS ONE GATES;
                              # the other two are documentation. On 2026-08-27
                              # both of those landed first and every spawn was
                              # still denied, because the rule lives in three
                              # hand-maintained copies and each one reads as
                              # authoritative from wherever you opened it.
    "recall",                 # promoted 2026-08-24; read-only memory sweep,
                              # write-less by tool grant, not by promise
    "super-doer",             # promoted 2026-09-09; operator ruled
                              # BIND 2026-09-02. One stalled board row to a
                              # finished artifact under work/<id>-<slug>/;
                              # commits its own scope on a lane branch, closes
                              # nothing. Holds Bash/Write/Edit, so it is
                              # write-bounded by PROMISE like senior-engineer,
                              # not by grant like recall. The definition had
                              # sat in .claude/agents/ since 2026-09-01 with
                              # no entry here: test_contract_sync compares
                              # prose to THIS frozenset and never reads the
                              # agents dir, so both omitted it, both agreed,
                              # and the suite stayed green for 8 days.
])

# Tools whose execution spawns a subagent. Extend the day a new
# spawn-capable tool appears — or L0-deny that tool. Never leave a
# spawn channel neither gated nor denied.
SPAWN_TOOLS = frozenset(["Agent", "Task"])


def deny(reason):
    # Single choke point: every denial is logged before it is emitted, so
    # "every denial leaves a trace" is structural, not remembered. The log
    # is observability, never enforcement — a failed write must not change
    # the decision.
    try:
        d = os.environ.get(LOG_DIR_ENV) or os.path.join(TREE_ROOT, LOG_DIR_NAME)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, time.strftime("%Y-%m-%d") + ".md"),
                  "a", encoding="utf-8") as f:
            f.write("- %s [spawn-roster] DENY %s\n"
                    % (datetime.now().strftime("%H:%M:%S"), reason))
    except Exception:
        pass
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": "spawn-roster: " + reason,
    }}))
    sys.exit(0)


def verdict(declared):
    # Harness-neutral predicate: declared subagent type -> "allow" | "deny".
    # Importable and testable without the hook envelope.
    if not isinstance(declared, str):
        return "deny"
    return "allow" if declared.strip() in ROSTER else "deny"


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        deny("unreadable hook input — cannot verify declared type")
    if not isinstance(data, dict):
        deny("hook input is not an object — cannot verify declared type")
    tool = data.get("tool_name")
    if not isinstance(tool, str) or not tool:
        deny("no tool name in hook input — cannot classify the call")
    if tool not in SPAWN_TOOLS:
        sys.exit(0)          # not a spawn; pass through untouched
    ti = data.get("tool_input")
    if ti is None:
        deny("no tool input — cannot read declared subagent type")
    if not isinstance(ti, dict):
        deny("tool input is not an object — cannot read declared type")
    declared = ti.get("subagent_type")
    if verdict(declared) == "allow":
        sys.exit(0)
    if declared is None:
        deny("no subagent_type declared — cannot verify against roster")
    if not isinstance(declared, str):
        deny("subagent_type is not a string (%r)" % (declared,))
    deny("'%s' is not on the delegation roster — additions are declared "
         "policy edits, not improvised spawns" % declared)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # An uncaught raise exits 1, which Claude Code treats as
        # non-blocking, so a crash let the call through. Fail closed instead.
        deny("crashed (%s) -- refusing rather than passing the call ungated" % type(e).__name__)
