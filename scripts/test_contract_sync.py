"""CLAUDE.md restates, in prose, three lists that a machine file
owns -- the delegation roster, the section 8 hook/deny wiring, and the
section 8 probe's decision claims. Nothing checked them for agreement
before this file. Same class as test_claude_md_budget.py (size) and
test_discovery_coverage.py (runner vs disk): a test in the existing suite,
blocks nothing, goes red when the two copies drift.

Each check below is a thin unittest wrapper around a pure function that
takes the parsed prose/config as a PARAMETER rather than reading the file
itself. That is the seam the work order's proof requirement needs: a
deliberate break can be demonstrated by calling the function with a
modified COPY of the text/dict, never by editing CLAUDE.md or
settings.json on disk.
"""
import importlib.util
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLAUDE_MD = ROOT / "CLAUDE.md"
ENFORCEMENT_MD = ROOT / "docs/enforcement/CLAUDE.md"
SETTINGS = ROOT / ".claude" / "settings.json"
HOOKS_DIR = ROOT / ".claude" / "hooks"
SPAWN_ROSTER_HOOK = HOOKS_DIR / "spawn-roster.py"

# --- check 1: delegation roster (prose) vs ROSTER (frozenset) -------------

# Identifier-only: `.claude/agents/` and `spawn-roster.py` (paths, mentioned
# in the same row) do not match, only bare backticked names do.
TOKEN_RE = re.compile(r"`([A-Za-z][A-Za-z0-9-]*)`")

# Backticked names that legitimately appear on the roster prose row but are
# not Agent-tool subagent types the frozenset gates. A new name landing here
# without a reason is exactly the incident this check exists to catch
# (a notes file: super-doer landed in prose before the frozenset).
ROSTER_PROSE_ONLY = {
    "Bash":   "a tool grant named inside senior-engineer's parenthetical, "
              "not itself a subagent_type",
    "Write":  "a tool grant held by both reviewer rows from 2026-09-05, "
              "not itself a subagent_type. Its bound -- one file each, "
              "their own review under grills/ -- is prose in the two agent "
              "definitions, not something this frozenset can gate",
    "ROSTER": "the frozenset's own name, referenced in the sentence that "
              "explains the three-edit binding",
}


def load_roster():
    """Import spawn-roster.py's ROSTER by path, not by regex over the
    source -- the comment block above the frozenset contains the literal
    string "codex", so a text search would misclassify it as a member.
    Mirrors tests/test_policy_mutate.py's HOOK-loading pattern:
    main() is gated by __name__, so exec_module runs no work."""
    spec = importlib.util.spec_from_file_location("spawn_roster_253", SPAWN_ROSTER_HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.ROSTER


def roster_row(claude_md_text):
    for line in claude_md_text.splitlines():
        if line.strip().startswith("**Delegation roster**"):
            return line
    return None


def check_roster(claude_md_text, roster):
    """Raises AssertionError on any disagreement. `roster` is passed in
    (not re-imported) so a break demo can hand it a modified frozenset too."""
    row = roster_row(claude_md_text)
    assert row is not None, "no line in CLAUDE.md starts '**Delegation roster**'"
    tokens = set(TOKEN_RE.findall(row))
    assert tokens, "the roster row matched but no backticked identifier was found in it"

    missing = sorted(roster - tokens)
    assert not missing, (
        "ROSTER member(s) not named in the CLAUDE.md roster row: %r -- the "
        "frozenset gates spawns, the prose is documentation; a member the "
        "prose forgot is real drift." % missing)

    unexplained = sorted(tokens - roster - set(ROSTER_PROSE_ONLY))
    assert not unexplained, (
        "backticked token(s) in the roster row that are neither ROSTER "
        "members nor in ROSTER_PROSE_ONLY: %r -- this is the super-doer "
        "incident (a notes file): a name landed in the prose before the "
        "frozenset. Either add the frozenset entry (a three-edit binding, "
        "CLAUDE.md S2) or explain the token in ROSTER_PROSE_ONLY."
        % unexplained)


class RosterSync(unittest.TestCase):
    def test_roster_prose_matches_frozenset(self):
        check_roster(CLAUDE_MD.read_text(encoding="utf-8"), load_roster())


# --- check 2: hooks wired in settings.json <-> hooks on disk --------------

# unlock_consume.py is a shared module imported by net-post.py and
# env-global.py, not independently wired -- correctly
# absent from settings.json's hooks tree. log-escape.py and log-escape-fast.sh
# are log-escape.sh's helpers, run by it, not by settings.json. run-python.sh
# is the launcher every Python hook's command starts (lane 6175): shared by
# all of them, so it is never the hook a command exists to run.
SHARED_HOOKS = {"unlock_consume.py", "log-escape.py", "log-escape-fast.sh", "run-python.sh"}
# The LAST quoted project path in a command is its hook: the guard's `f=` path
# for a shell hook, the .py after the launcher for a Python hook (lane 6175).
PROJECT_PATH_RE = re.compile(r'"\$\{?CLAUDE_PROJECT_DIR\}?/([^"]+)"')


def wired_basenames(settings):
    """Every `command` string's final path segment, by basename. Matching on
    basename (not full path) sidesteps settings.json's mixed path styles --
    a literal `$CLAUDE_PROJECT_DIR` prefix on one row, hardcoded absolute
    paths on the rest -- which is what WORK-ORDER.md's check 2 specifies
    ("match on basename")."""
    names = set()

    def walk(node):
        if isinstance(node, dict):
            cmd = node.get("command")
            if isinstance(cmd, str) and cmd.strip():
                paths = PROJECT_PATH_RE.findall(cmd)
                token = paths[-1] if paths else cmd.split()[-1].strip('"')
                names.add(Path(token.replace("\\", "/")).name)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(settings.get("hooks", {}))
    return names


def disk_hook_basenames(hooks_dir):
    return {p.name for p in hooks_dir.rglob("*")
            if p.is_file() and p.suffix in (".py", ".sh")}


def check_hooks_wired(settings, hooks_dir):
    wired = wired_basenames(settings)
    disk = disk_hook_basenames(hooks_dir)
    # Non-empty guards: an earlier fix's whole-layer variant (hooks dir and hooks
    # block both gone) would otherwise pass vacuously (review F2).
    assert wired, "settings.json wires no hooks at all"
    assert disk, "no hook files under .claude/hooks/"

    unwired = sorted(disk - wired - SHARED_HOOKS)
    assert not unwired, (
        "hook file(s) on disk that settings.json's hooks tree never "
        "references, so nothing runs them: %r (an earlier fix's class -- a "
        "checkout that removes a hook's wiring reports nothing)." % unwired)

    missing = sorted(wired - disk)
    assert not missing, (
        "settings.json wires a command whose basename matches no file "
        "under .claude/hooks/: %r -- the entry outlived the file it named."
        % missing)


class HooksWiredSync(unittest.TestCase):
    def test_settings_and_disk_agree(self):
        settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
        check_hooks_wired(settings, HOOKS_DIR)


# --- check 3: section 8 Mechanism column names name real hooks ------------

HYPHEN_TOKEN_RE = re.compile(r"[a-z]+(?:-[a-z]+)+")

# Vocabulary in the Mechanism column that names a concept, an unlock verb,
# or a behaviour -- never a hook file or a hooks/ subdirectory. This
# allowlist is what makes the check meaningful: without it, every token
# would need to independently prove itself a hook, but a token is only
# EXCUSED from that proof by landing here on purpose. Deleting a real hook
# leaves its token unmatched and red; a new descriptive phrase in the
# column is a deliberate addition here, not a weakening.
NOT_HOOKS = {
    "auth-policy":       "the one-shot unlock verb policy-mutate's row names",
    "auth-policy-batch": "the batch unlock verb, same row",
    # .githooks/pre-push is a git hook, not a
    # .claude/hooks/ file -- outside hook_vocabulary() by construction, and
    # named in the Git never-items row deliberately.
    "pre-push":          "git's own pre-push hook, .githooks/pre-push, not under .claude/hooks/",
    "permission-bypass": "the harness mode filetool-scope/shell-scope describe",
    # auto-approves: found during an earlier fix's build, missing from the work
    # order's original NOT_HOOKS -- both the filetool-scope and shell-scope
    # rows describe what permission-bypass mode does to an `ask` decision.
    # It is prose about a mode's effect, not a hook file; there is no
    # auto-approves.py. Added per the check's own documented remedy
    # (and the fix is to
    # add it to the allowlist deliberately").
    "auto-approves":     "describes what permission-bypass mode does to an ask row -- prose, not a file",
    "explicit-path":     "shell-scope's own scoping qualifier",
    "auth-net":          "net-post's unlock verb",
    "self-logging":      "describes what an interpreter's own HTTP call is not covered by",
    "auth-env":          "env-global's unlock verb",
    "append-only":       "describes log-escape's write mode",
    "tool-mediated":     "describes log-escape's coverage boundary",
    "per-row":           "describes the section 5 charter's per-instance ADR requirement",
}

# The single Status column became three (Windows /
# Managed / Self-hosted); Mechanism stays the 3rd data column (parts[3]),
# unaffected by how many Status columns follow it.
MECH_HEADER = "| Rule class | Layer | Mechanism | Windows | Managed | Self-hosted |"


def mechanism_cells(claude_md_text):
    lines = claude_md_text.splitlines()
    try:
        start = next(i for i, l in enumerate(lines) if l.strip() == MECH_HEADER)
    except StopIteration:
        raise AssertionError(
            "enforcement table header %r not found in docs/enforcement/CLAUDE.md" % MECH_HEADER)
    cells = []
    for line in lines[start + 1:]:
        if not line.startswith("|"):
            break
        if set(line.replace("|", "").strip()) <= {"-", " "}:
            continue  # the |---|---|---|---| separator row
        parts = [c.strip() for c in line.split("|")]
        cells.append(parts[3])  # [0] and [-1] are outside the bounding pipes
    assert cells, "section 8's table header matched but produced no data rows"
    return cells


def hook_vocabulary(hooks_dir):
    stems = {p.stem for p in hooks_dir.rglob("*")
             if p.is_file() and p.suffix in (".py", ".sh")}
    dirs = {p.name for p in hooks_dir.iterdir() if p.is_dir()}
    return stems | dirs


def check_mechanism_names(claude_md_text, hooks_dir, not_hooks=NOT_HOOKS):
    text = " ".join(mechanism_cells(claude_md_text))
    tokens = set(HYPHEN_TOKEN_RE.findall(text))
    assert tokens, "section 8 Mechanism column yielded no hyphenated tokens"
    remaining = tokens - set(not_hooks)
    assert remaining, "every Mechanism token is allowlisted -- nothing checked"
    vocab = hook_vocabulary(hooks_dir)
    assert vocab, "no hook files under .claude/hooks/"
    unmatched = sorted(remaining - vocab)
    assert not unmatched, (
        "section 8's Mechanism column names hyphenated token(s) that are "
        "neither a known non-hook word (NOT_HOOKS) nor a .py/.sh basename "
        "or subdirectory under .claude/hooks/: %r -- either a hook was "
        "deleted or this is a new non-hook word; if the latter, "
        "add it to NOT_HOOKS deliberately with a reason." % unmatched)


class MechanismNamesSync(unittest.TestCase):
    def test_section_8_mechanism_names_exist(self):
        self.assertIn("docs/enforcement/CLAUDE.md", CLAUDE_MD.read_text(encoding="utf-8"))
        check_mechanism_names(ENFORCEMENT_MD.read_text(encoding="utf-8"), HOOKS_DIR)


# --- check 4: section 2 L0 deny classes <-> permissions.deny entries ------

# One regex per denied capability, grouped under the S2 L0 class it belongs
# to, so dropping any single covered entry goes red. Grouping follows the
# hub's baseline reading of S2 L0 in WORK-ORDER.md; `Workflow` under
# persistence and `suggest_connectors` under plugins are HUB-AUTHORED
# placements, not ruled by the contract text itself -- marked here, not
# asserted as doctrine.
L0_DENY_REGEXES = {
    "persistence": [
        r"^CronCreate$", r"^CronDelete$", r"^ScheduleWakeup$",
        r"scheduled-tasks", r"spawn_task", r"^RemoteTrigger$",
        # The Routine surface's schedule/spawn forms, by name.
        # create_session left the deny for settings ask.
        r"claude-code-remote__send_later$",
        r"claude-code-remote__watch_url$", r"claude-code-remote__update_trigger$",
        # The September spelling stays denied beside the October one.
        r"Claude_Code_Remote__send_later$",
        r"Claude_Code_Remote__watch_url$", r"Claude_Code_Remote__update_trigger$",
        r"^Workflow$",  # hub-authored placement, not contract-ruled
    ],
    "desktop/Chrome MCPs": [r"computer-use", r"claude-in-chrome"],
    "plugins": [
        r"SuggestPluginInstall",
        r"^Bash\(claude plugin:\*\)$",
        r"suggest_connectors",  # hub-authored placement, not contract-ruled
    ],
    "catchall spawn": [r"general-purpose"],
}


def check_l0_deny_coverage(settings, regexes=L0_DENY_REGEXES):
    deny = settings.get("permissions", {}).get("deny", [])
    assert deny, "permissions.deny is empty -- nothing to check L0 prose against"
    unmatched = []
    for cls, patterns in regexes.items():
        for pat in patterns:
            if not any(re.search(pat, entry) for entry in deny):
                unmatched.append((cls, pat))
    assert not unmatched, (
        "L0 class/regex pair(s) with no matching permissions.deny entry: "
        "%r -- either the entry was removed from settings.json, "
        "or the class it belongs to changed and this table needs updating."
        % unmatched)


class L0DenyCoverage(unittest.TestCase):
    def test_every_l0_class_has_a_deny_entry(self):
        settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
        check_l0_deny_coverage(settings)


if __name__ == "__main__":
    unittest.main()
