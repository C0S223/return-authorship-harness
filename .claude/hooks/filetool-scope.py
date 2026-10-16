# filetool-scope — PreToolUse Write|Edit|NotebookEdit. Single job: block
# file-tool writes outside the harness tree (scratchpad excepted); per-call user
# permission is the unlock, delivered mechanically as permissionDecision
# "ask" — the platform's own prompt, not a chat approval a hook can't see
# (contract S2 L1). Undeterminable path = ask, never
# allow (fail-closed). .git internals are step 4's job (policy-mutate),
# not this hook's.
import importlib.util
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normcase(os.path.realpath(
    os.environ.get("HARNESS_ROOT")            # test seam; unset in production
    or os.environ.get("CLAUDE_PROJECT_DIR")
    or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
TMP = os.path.normcase(os.path.realpath(tempfile.gettempdir()))


def is_scratch(p):
    """The harness scratchpad: <tmp>/claude or <tmp>/claude-<suffix> (a cloud
    session's is /tmp/claude-<uid>/...), and anything under it."""
    if not p.startswith(TMP + os.sep):
        return False
    top = p[len(TMP) + 1:].split(os.sep, 1)[0]
    return top == "claude" or top.startswith("claude-")

try:
    _spec = importlib.util.spec_from_file_location(
        "unlockconsume", os.path.join(HERE, "unlock_consume.py"))
    uc = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(uc)
except Exception:
    uc = None      # absent = never cloud-off, stays live


def ask(reason):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "ask",
        "permissionDecisionReason": "filetool-scope: " + reason,
    }}))
    sys.exit(0)


def classify(data):
    """('unknown', reason) | ('inside', path) | ('outside', path).

    One predicate, two readers -- the gate in main() below, and
    log-escape.sh via `--log`. Shared rather than copied so the audit and the
    gate can never disagree about what "outside the tree" means. This is the
    design the sibling already uses and that log-escape.sh's own header claims
    at its line 8: "one predicate shared with the gate".
    """
    ti = data.get("tool_input") or {}
    path = ti.get("file_path") or ti.get("notebook_path")
    if not path:
        return "unknown", "no write path in tool input -- cannot verify target"
    if not os.path.isabs(path):
        path = os.path.join(data.get("cwd") or "", path)
    p = os.path.normcase(os.path.realpath(path))
    if p == ROOT or p.startswith(ROOT + os.sep):
        return "inside", path
    if is_scratch(p):
        return "inside", path
    return "outside", path


def main():
    # Cloud-off under
    # the marker -- the VM (managed) / mount+sandbox denyWrite (self-hosted)
    # are the replacement scope. Windows unaffected (uc.cloud_boundary()
    # reads None there, always -- see its docstring).
    if uc is not None and uc.cloud_boundary():
        sys.exit(0)
    try:
        data = json.load(sys.stdin)
    except Exception:
        ask("unreadable hook input — cannot verify write target")
    # --log: report, never decide. log-escape.sh calls this for Write/Edit/
    # NotebookEdit so a file-tool escape leaves the same trail a shell one
    # does. Placed after the cloud-off check deliberately: where the gate is
    # inert the replacement scope confines instead, and a line describing a
    # write this hook never evaluated would misdescribe the audit.
    verdict, val = classify(data)
    if "--log" in sys.argv:
        if verdict == "outside":
            print("filewrite: %s" % val)
        sys.exit(0)
    if verdict == "unknown":
        ask(val)
    if verdict == "inside":
        sys.exit(0)
    ask("'%s' is outside the harness tree — per-call user permission is the "
        "unlock (contract S2 L1)" % val)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # An uncaught raise exits 1, which Claude Code treats as
        # non-blocking, so a crash let the write through unasked. Ask instead,
        # and leave log-escape a line rather than nothing.
        if "--log" in sys.argv:
            print("filewrite: (filetool-scope crashed: %s)" % type(e).__name__)
            sys.exit(0)
        ask("crashed (%s) -- cannot verify the write target"
            % type(e).__name__)
