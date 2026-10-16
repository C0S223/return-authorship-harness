# env-global — PreToolUse Bash|PowerShell. Single job: block global
# environment mutation ($env:PATH assignment, persistent env writes,
# registry writes, global/system package installs); one-shot `auth-env`
# is the unlock. The SAME hook warns — never blocks, no unlock — on
# in-project package acquisition (systemMessage to the human; the
# contract's package-warn promise names this hook as its emitter).
# Quoted spans are stripped before matching so prose about setx cannot
# false-deny. Transient `$env:VAR = ...` assignments other than PATH
# pass: they die with the shell.
import importlib.util
import json
import os
import re
import sys
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = (os.environ.get("HARNESS_ROOT") or os.environ.get("CLAUDE_PROJECT_DIR")
        or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
UNLOCK = os.path.join(ROOT, ".agent-log", "env-unlock.json")

try:
    _spec = importlib.util.spec_from_file_location(
        "unlockconsume", os.path.join(HERE, "unlock_consume.py"))
    uc = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(uc)
except Exception:
    uc = None      # 66: fail closed at the call site, never crash open

BLOCKS = [
    (re.compile(r'(?i)\$env:path\s*\+?='), "PATH mutation"),
    (re.compile(r'(?i)\[Environment\]::SetEnvironmentVariable'),
     "persistent env write"),
    (re.compile(r'(?i)(?<![\w-])setx(?![\w-])'), "setx persistent env"),
    (re.compile(r'(?i)(?<![\w-])reg(\.exe)?\s+add(?![\w-])'),
     "registry write"),
    (re.compile(r'(?i)(Set-ItemProperty|New-ItemProperty)[^|;]*\sHK(LM|CU):'),
     "registry write"),
    (re.compile(r'(?i)(?<![\w-])(npm|pnpm|yarn)\b[^|;&]*(?:^|\s)'
                r'(-g|--global|global)(?=\s|$)'), "global package install"),
    (re.compile(r'(?i)(?<![\w-])(winget|choco)\s+(install|upgrade|uninstall)'
                r'(?![\w-])'), "system package manager"),
]
WARN = re.compile(
    r'(?i)(?<![\w-])(npm\s+(i|install|add)|pip\s+install|'
    r'uv\s+(pip\s+install|add)|pnpm\s+(add|install)|yarn\s+add|npx)(?![\w-])')


def strip_quoted(cmd):
    return re.sub(r'"[^"]*"|\'[^\']*\'', ' ', cmd)


def deny(reason, unlock=True):
    try:
        d = os.path.join(ROOT, ".agent-log")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, time.strftime("%Y-%m-%d") + ".md"),
                  "a", encoding="utf-8") as f:
            f.write("- %s [env-global] DENY %s\n"
                    % (datetime.now().strftime("%H:%M:%S"), reason))
    except Exception:
        pass
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason":
            ("env-global: %s. Submit 'auth-env' as its own user message, "
             "then retry exactly one mutation (one shot, 30 min)" if unlock
             else "env-global: %s") % reason,
    }}))
    sys.exit(0)


def consume_unlock():
    # Hardened consumption is shared: unlock_consume.py carries the semantics
    # ported from policy-mutate. If the module failed to
    # load, the unlock is treated as ABSENT (deny path), never as granted.
    # This hook's deny reason does NOT name the load failure;
    # net-post's does. The asymmetry is an open operator option.
    if uc is None:
        return False
    if uc.consume(UNLOCK) is None:
        return False
    try:
        d = os.path.join(ROOT, ".agent-log")
        with open(os.path.join(d, time.strftime("%Y-%m-%d") + ".md"),
                  "a", encoding="utf-8") as f:
            f.write("- %s [env-global] unlock-consumed: auth-env\n"
                    % datetime.now().strftime("%H:%M:%S"))
    except Exception:
        pass
    return True


def main():
    # Cloud-off under the
    # marker -- the VM/container absorb global env/installs, no host effect
    # reachable; Windows control is unchanged (uc.cloud_boundary() reads
    # None there, always -- see its docstring).
    if uc is not None and uc.cloud_boundary():
        sys.exit(0)
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)          # no command text = nothing to judge
    raw = (data.get("tool_input") or {}).get("command") or ""
    if not raw:
        sys.exit(0)
    cmd = strip_quoted(raw.replace("\n", " "))
    for rx, label in BLOCKS:
        if rx.search(cmd):
            if consume_unlock():
                sys.exit(0)
            deny(label + (uc.stale_note(UNLOCK) if uc is not None else ""))   # 365
    if WARN.search(cmd):
        print(json.dumps({"systemMessage":
                          "env-global: in-project package acquisition — "
                          "advisory only (contract S2); verify the dep is "
                          "asked-for or plan-named."}))
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # An uncaught raise exits 1, which Claude Code treats as
        # non-blocking, so a crash let the call through. Fail closed instead;
        # no auth-env grant can get past a crash, so none is offered.
        deny("crashed (%s) -- refusing rather than passing the call ungated" % type(e).__name__, unlock=False)
