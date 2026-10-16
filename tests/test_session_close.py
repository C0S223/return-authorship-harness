"""The reader for docs/enforcement/CLAUDE.md's session-close obligation.

That doc states an obligation -- session-close copies escape, grant, integrity
and `peer-` lines; only committed lines survive -- and this file reads it back.
The defect it pins: session-close.sh's once-per-session latch once sat ABOVE the
cloud-copy block, so the copy ran at most once per session, at the first turn
end with stranded work. On a cloud target `.agent-log/` dies with the container,
so every post-latch line was unrecoverable.

TWO WORLDS, ONE SET OF ASSERTIONS. A repair to a policy path ships as a patch
the operator applies (`.claude/hooks/**` is a policy path, `CLAUDE.md` §2), so
this suite has to be green before and after the operator applies it, and must
never need editing when they do -- a test that goes red on a correct repair is a
worse defect than the one it pins.

  the patch forward-applies -> the tree still carries the defect, so the repair
                               is PENDING. Assert against a patched temp copy
                               (the deliverable) as a required pass, and against
                               the SHIPPED hook as a DECLARED expected failure
                               -- the suite states the live defect out loud
                               instead of going quietly green.
  anything else             -> nothing certifies a pending repair, so the hook as
                               it stands is the only subject and the behaviour
                               is a REQUIRED pass. That covers all of: the
                               operator applied the patch, the operator repaired
                               by hand, an unrelated edit moved the patch's
                               context windows, the patch was deleted. In this
                               tree no patch is pending, so this is the world
                               that runs.

No branch of that aborts. Exiting rc=1 when the hook matched neither direction
of the patch would turn a correct hand-repair into a tree-wide FAIL; the case
`test_a_correct_repair_with_other_bytes_keeps_the_suite_green` builds exactly
that hook and pins the suite green against it. What changes when the operator
applies is the REPORTED STATE of `test_the_shipped_hook_refreshes_the_survivor`
-- "expected failure" while pending, "ok" after -- and not one byte of this file.

What the expected failure cannot tell you, stated because a declared red is the
easiest place in a suite to hide a second defect: while the repair is pending
that case would also look "expected" if the harness itself broke.
`test_the_pending_repair_refreshes_the_survivor` asserts the same behaviour
against the patched copy as a REQUIRED pass in that same world, which is what
keeps a harness break visible.

THE ESCAPE REPAIR is a second, independent pending/applied resolution. The cloud
block once named escape lines by a grep in its own header, and the grep carried
almost none of them. The repair has scripts/log_filter.py own the rule and the
hook INVOKE it (operator ruling: one owner). It gets its own resolution rather
than joining the first patch: folding them would make one case an unexpected
SUCCESS on the day only one of the two is applied, and unittest scores that as
a failure.

Overrides, all three for proving red against a pristine copy:
  SESSION_CLOSE_HOOK=<path>   assert against that file instead of the shipped one
  SESSION_CLOSE_PATCH=        (set but empty) skip reconciliation entirely and
                              assert the hook exactly as it stands
  SESSION_CLOSE_ESCAPE_PATCH=<path>   resolve the escape world against that file;
                              point it at a nonexistent path to see the escape
                              cases as REQUIRED passes against the unpatched hook

WHAT THIS HARNESS SETS THAT THE LIVE ENVIRONMENT DOES NOT (role contract: an
assumption baked into a test is the one nobody thinks to check):
  1. ROOT= is rewritten to a temp dir and a COPY is run -- the established
     technique from test_log_escape.py. Nothing here touches the real
     .agent-log/.
  2. CLAUDE_CODE_REMOTE, HARNESS_BOUNDARY and CLAUDE_PROJECT_DIR are scrubbed from
     the inherited environment and set per case. A cloud host really does carry
     CLAUDE_CODE_REMOTE=true, so without the scrub the non-cloud case would test
     nothing. The resolved ambient values are printed below, not assumed.
  3. The day log is written under yesterday's, today's and tomorrow's UTC date
     with identical content. The hook names it by LOCAL date, and every local
     date is within one day of UTC's, so a rollover between fixture write and
     hook run cannot flake the READ. The WRITE is rollover-safe too, but by a
     different means: session-close.sh puts that same date in the survivor's
     FILENAME, so a rollover between two turn ends writes a second file instead
     of refreshing the first, and survivor() therefore takes the newest and
     asserts nothing about the count.
  4. The temp ROOT is a fresh `git init` holding an untracked file, so the
     stranded-work branch is reachable at all -- the latch only records state
     when there IS stranded work, which is what made the defect intermittent.
  5. The class fixtures are DRIVEN out of the hooks that write them, into their
     own throwaway roots, and only their placement in the day log is this
     harness's doing: see 3.
"""
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HOOKS = REPO / ".claude" / "hooks"
SHIPPED_HOOK = HOOKS / "session-close.sh"
HOOK = Path(os.environ.get("SESSION_CLOSE_HOOK") or SHIPPED_HOOK)
HOOK_REL = ".claude/hooks/session-close.sh"
DEFAULT_PATCH = REPO / "work" / "session-close" / "latch.patch"
# The escape repair, resolved the same way and kept SEPARATE from the latch
# repair on purpose: the two are pending independently, and folding them into
# one DEFAULT_PATCH would make one case an unexpected SUCCESS the day only one
# of them is applied, which unittest reports as a failure.
DEFAULT_ESCAPE_PATCH = REPO / "work" / "session-close" / "escape.patch"
ESCAPE_PATCH = Path(os.environ.get("SESSION_CLOSE_ESCAPE_PATCH") or DEFAULT_ESCAPE_PATCH)
ENFORCEMENT = REPO / "docs" / "enforcement" / "CLAUDE.md"
# The `peer-` tags root CLAUDE.md §4 mandates as agent commentary (no hook writes them).
PEER_TAGS = ("[peer-mailbox]", "[peer-recv]", "[peer-send]")
CHILD = "SESSION_CLOSE_CHILD"      # recursion guard: the F2 case runs this suite

# The markers the hook reads out of its own launch environment, plus the one
# that would override ROOT= before the rewrite can take effect.
MARKERS = ("CLAUDE_CODE_REMOTE", "HARNESS_BOUNDARY", "CLAUDE_PROJECT_DIR")
CLEAN_ENV = {k: v for k, v in os.environ.items() if k not in MARKERS}

# Fixtures are produced by the writers, never read off the grep. Deriving them
# from the pattern -- "one per alternative" -- makes the expected set a function
# of the implementation, so the case can only restate it (review F4). It also
# put two shapes in this file that no writer in this tree emits, ' ASK ' and a
# bracketed 'peer-fire_trigger', and a hand-written ' DENY ' line standing in
# for six real writers. Each row is (class named at
# docs/enforcement/CLAUDE.md:27, argv, stdin, carried?, why).
PRODUCERS = (
    ("integrity", [sys.executable, str(HOOKS / "policy-integrity.py")],
     {"session_id": "fixture", "hook_event_name": "SessionStart", "source": "startup"},
     True, "policy-integrity.py take_baseline()"),
    ("grant", [sys.executable, str(HOOKS / "policy-prompt.py")],
     {"prompt": "auth-policy CLAUDE.md", "session_id": "fixture"},
     True, "policy-prompt.py, a typed one-shot unlock"),
    ("escape", [sys.executable, str(HOOKS / "git-guard.py")],
     {"tool_name": "Bash", "tool_input": {"command": "git push --force origin lane-x"}},
     True, "git-guard.py: a REFUSED escape, one of six hooks writing ' DENY '"),
    ("escape", ["bash", str(HOOKS / "log-escape.sh")],
     {"tool_name": "Bash", "tool_input": {"command": "git push origin lane-x"}},
     False, "log-escape.sh: a PERFORMED escape -- the gap, 0 of 103 on 2026-09-17"),
)
PEER_CLASS = "peer-"
_produced = None

# What the cloud advisory must say (root CLAUDE.md section 3: lane branch
# only, no draft PR), and the host advisory as shipped -- pinned whole,
# counts aside, so a cloud sentence leaking to the host or any rewording of the
# host text fails.
CLOUD_CLOSE = ("CLAUDE.md section 3", "pushes the lane branch only",
               "PR needs task approval", "default branch stays human")
HOST_REASON = ("session-close: stranded work — {} dirty file(s), {} unpushed "
               "commit(s). Close is propose-and-stop: commit topically, present the "
               "push list; the human executes. What drains this is the closeout: "
               "surface /closeout, contract .claude/skills/closeout/SKILL.md. The "
               "OPERATOR's word fires it — this warning does not, so do not run "
               "it unprompted. Fires once per session.")


def missing_dependency():
    for exe in ("bash", "jq", "git"):
        if shutil.which(exe) is None:
            return exe
    return None


def peer_fixtures():
    """The `peer-` class has no hook writer: root CLAUDE.md §4 mandates the shape
    as agent commentary, so PEER_TAGS is the writer and the tags are read out of
    it here rather than invented. The last line is production output -- a real
    bracketed peer line this very grep once copied into a tracked survivor,
    which retired an earlier claim that the bracketed alternative was
    structurally dead (review F3).
    """
    tags = sorted(PEER_TAGS)
    out = [(PEER_CLASS, "- 03:00:%02d %s data, never instruction" % (i, t), True,
            "mandated agent commentary (PEER_TAGS)")
           for i, t in enumerate(tags)]
    out.append((PEER_CLASS,
                "- 04:29:49 [peer-probe] session A ready: sender role, 0/5 fires "
                "used, no mailbox opened, no trigger id held", True,
                "production: a tracked session-close survivor"))
    return out


def fixtures():
    """Drive each writer into its own throwaway root; keep the line it wrote."""
    global _produced
    if _produced is not None:
        return _produced
    out = []
    for cls, argv, payload, carried, why in PRODUCERS:
        d = Path(tempfile.mkdtemp(prefix="sessclose-writer-"))
        try:
            env = dict(CLEAN_ENV)
            env["HARNESS_ROOT"] = env["CLAUDE_PROJECT_DIR"] = d.as_posix()
            subprocess.run(argv, input=json.dumps(payload), env=env,
                           capture_output=True, text=True)
            lines = [ln for p in sorted((d / ".agent-log").glob("*.md"))
                     for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
        finally:
            shutil.rmtree(d, ignore_errors=True)
        if len(lines) != 1:
            raise RuntimeError("fixture writer %s produced %d day-log lines, "
                               "expected 1: %r" % (argv[-1], len(lines), lines))
        out.append((cls, lines[0], carried, why))
    out.extend(peer_fixtures())
    _produced = out
    return out


def classes_in_the_enforcement_doc():
    """Read the obligation this suite exists to check, as prose.

    Review residual risk 3: every assertion here read the hook or the grep, so
    editing that sentence's class list changed no test. This one reads it.
    """
    m = re.search(r"(?m)^Session-close copies (.+?) lines\b",
                  ENFORCEMENT.read_text(encoding="utf-8"))
    if not m:
        raise RuntimeError("%s no longer carries the session-close obligation "
                           "sentence this suite is the reader for" % ENFORCEMENT)
    return sorted(w.strip().strip("`") for w in re.split(r",| and ", m.group(1))
                  if w.strip())


def _apply(work, patch, *flags):
    # git apply works outside a repository; cwd supplies the -p1 root.
    return subprocess.run(["git", "apply", *flags, str(patch)], cwd=str(work),
                          capture_output=True, text=True)


def _tree_with(src):
    work = Path(tempfile.mkdtemp(prefix="sessclose-world-"))
    target = work / HOOK_REL
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(src, encoding="utf-8", newline="\n")
    return work, target


def patched(src, patch):
    """`src` with `patch` applied, or None if the patch does not apply to it."""
    work, target = _tree_with(src)
    try:
        if _apply(work, patch, "--check").returncode != 0:
            return None
        r = _apply(work, patch)
        if r.returncode != 0:
            raise RuntimeError("%s passed --check but failed to apply: %s"
                               % (patch, r.stderr))
        return target.read_text(encoding="utf-8")
    finally:
        shutil.rmtree(work, ignore_errors=True)


def reconciles(src, patch):
    """True if `patch` applies to `src` in either direction."""
    work, _ = _tree_with(src)
    try:
        return (_apply(work, patch, "--check").returncode == 0
                or _apply(work, patch, "--check", "-R").returncode == 0)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def a_correct_repair_with_other_bytes():
    """A correct repair of the tree's hook that the latch patch did not write.

    Two perturbations, one per half of review F2: the latch keeps its ORIGINAL
    one-line comment (the hand-applied block move, measured as W2), and an
    ordinary comment lands inside the patch's second context window (the future
    maintenance edit). Behaviour is untouched; both directions of `git apply
    --check` stop reconciling, which is precisely the state the old code aborted
    on. Built from the tree's own hook, never from SESSION_CLOSE_HOOK, so a
    mutant under test cannot reach it.
    """
    src = SHIPPED_HOOK.read_text(encoding="utf-8")
    if DEFAULT_PATCH.is_file():
        src = patched(src, DEFAULT_PATCH) or src
    src, n = re.subn(r'(?m)^# once per session[^\n]*\n(?:#[^\n]*\n)*'
                     r'(?=if \[ -f "\$STATE_FILE" \])', "# once per session\n", src)
    if n != 1:
        raise RuntimeError("could not find the latch's comment block in %s"
                           % SHIPPED_HOOK)
    marker = "# hand-repaired: an ordinary edit inside the patch's context window\n"
    src, n = re.subn(r'(?m)^(?=DIRTY=)', marker, src)
    if n != 1:
        raise RuntimeError("could not find the DIRTY= line in %s" % SHIPPED_HOOK)
    return src


def resolve_world():
    """Return (source asserting the fixed behaviour, repair_pending, world line).

    `repair_pending` is true only while the latch patch forward-applies -- the one
    state in which a red on the latch behaviour is already known and recorded.
    Every other state demands the real behaviour of the hook as it stands, which
    is why no correct repair can make this suite exit non-zero (F2).
    """
    shipped = HOOK.read_text(encoding="utf-8")
    if os.environ.get("SESSION_CLOSE_PATCH") == "":
        return shipped, False, ("reconciliation DISABLED -- the hook as it stands "
                                "is the only subject")
    patch = Path(os.environ.get("SESSION_CLOSE_PATCH") or DEFAULT_PATCH)
    if not patch.is_file():
        return shipped, False, ("no patch at %s, so nothing certifies a pending "
                                "repair -- the hook as it stands is the only "
                                "subject and the latch behaviour is a REQUIRED "
                                "pass" % patch)
    fixed = patched(shipped, patch)
    if fixed is None:
        return shipped, False, ("%s does not apply to %s, so no repair is pending "
                                "-- the hook as it stands is the only subject and "
                                "the latch behaviour is a REQUIRED pass"
                                % (patch.name, HOOK))
    return fixed, True, ("repair PENDING -- %s still applies, so the hook carries "
                         "the defect: asserting the patched copy, and the live "
                         "hook as a declared expected failure" % patch.name)


def world_slice(knobs, case):
    """What can differ in a run whose environment differs in `knobs`.

    Read off this file's syntax tree on every call, never from a typed list
    (review finding: a hand list of flag names silently shrank the F2 case's
    child to tests that all skip). Returns (world, reads):
      world -- every module-level name or function whose binding reads a knob
               (as a string constant) or an earlier world name: HOOK,
               SHIPPED_SRC, resolve_world and all it binds, the escape products,
               both decorators -- so a rename or a new flag bound from them
               joins by itself;
      reads -- per method of `case`, the world names its decorators and body
               read, following the self.* methods it reaches (setUp is reached
               by no test; the caller deals with it).
    Blind to a read made by lookup (globals(), getattr) or through the
    environment a test hands a subprocess.
    """
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))

    def names(node):
        return {n.id if isinstance(n, ast.Name) else n.value for n in ast.walk(node)
                if isinstance(n, ast.Name)
                or (isinstance(n, ast.Constant) and n.value in knobs)}

    bound = {}
    for st in tree.body:
        if isinstance(st, ast.FunctionDef):
            bound[st.name] = names(st)
        elif isinstance(st, ast.Assign):
            for target in st.targets:
                for n in ast.walk(target):
                    if isinstance(n, ast.Name):
                        bound.setdefault(n.id, set()).update(names(st.value))
    world = set(knobs)
    while True:
        more = {n for n, read in bound.items() if read & world} - world
        if not more:
            break
        world |= more
    world -= set(knobs)
    cls = next(st for st in tree.body
               if isinstance(st, ast.ClassDef) and st.name == case.__name__)
    methods = {f.name: f for f in cls.body if isinstance(f, ast.FunctionDef)}

    def reach(name, seen):
        out = names(methods[name])
        for n in ast.walk(methods[name]):
            if (isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
                    and n.value.id == "self" and n.attr in methods
                    and n.attr not in seen):
                out |= reach(n.attr, seen | {n.attr})
        return out

    return world, {name: reach(name, {name}) & world for name in methods}


_dep = missing_dependency()
if _dep:
    # scripts/run_tests.py:308 reads this. Chartered for a missing dependency
    # only -- never for "the patch is unapplied", which is a world this suite
    # asserts in, not a reason to stop asserting.
    print("SKIP: %s is not on PATH; session-close.sh is a bash script that "
          "shells out to jq, and the harness needs git." % _dep)
    raise SystemExit(0)

SHIPPED_SRC = HOOK.read_text(encoding="utf-8")
HOOK_SRC, REPAIR_PENDING, WORLD = resolve_world()
expected_failure_while_pending = (unittest.expectedFailure if REPAIR_PENDING
                                  else (lambda f: f))
# The escape repair's world, by the same three-state rule and with no branch that aborts:
# the patch forward-applies -> the escape gap is live and already recorded, so
# the shipped hook is a DECLARED expected failure and the patched copy carries
# the required pass. Anything else -- applied, hand-repaired, context moved,
# patch deleted -- and the shipped hook is the only subject and a required pass.
ESCAPE_FIXED = patched(SHIPPED_SRC, ESCAPE_PATCH) if ESCAPE_PATCH.is_file() else None
ESCAPE_PENDING = ESCAPE_FIXED is not None
expected_failure_while_escape_pending = (unittest.expectedFailure if ESCAPE_PENDING
                                         else (lambda f: f))
print("session-close suite: hook=%s" % HOOK)
print("  world: %s" % WORLD)
print("  escape: %s (%s)"
      % ("escape repair PENDING -- asserting the patched copy, and the live hook "
         "as a declared expected failure" if ESCAPE_PENDING else
         "no escape repair pending -- the hook as it stands is the only subject",
         ESCAPE_PATCH))
print("  ambient %s; all scrubbed, then set per case"
      % " ".join("%s=%s" % (k, os.environ.get(k, "<unset>")) for k in MARKERS))


class SessionCloseCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="sessclose-root-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.hook = self.root / "session-close.sh"
        self.install(HOOK_SRC)
        (self.root / ".agent-log").mkdir(parents=True, exist_ok=True)
        # Harness note 6: the hook runs $ROOT/scripts/log_filter.py and ROOT=
        # is this temp dir, so the production path is planted here.
        planted = self.root / "scripts"
        planted.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / "scripts" / "log_filter.py", planted / "log_filter.py")
        subprocess.run(["git", "init", "-q", self.root.as_posix()],
                       capture_output=True, check=True)
        # stranded work, so the advisory branch -- the only branch that records
        # the latch state -- is reachable.
        (self.root / "stranded.txt").write_text("uncommitted\n", encoding="utf-8")
        self.session = "sess-latch-" + self.id().rsplit(".", 1)[-1]

    # -- harness ---------------------------------------------------------
    def install(self, src):
        src, n = re.subn(r"(?m)^ROOT=.*$",
                         'ROOT="%s"' % self.root.as_posix(), src)
        self.assertEqual(n, 1, "session-close.sh no longer has exactly one ROOT= line")
        self.hook.write_text(src, encoding="utf-8", newline="\n")

    def write_daylog(self, lines):
        text = "".join(s.rstrip("\n") + "\n" for s in lines)
        now = datetime.now(timezone.utc)
        for day in (now - timedelta(days=1), now, now + timedelta(days=1)):
            (self.root / ".agent-log" / (day.strftime("%Y-%m-%d") + ".md")
             ).write_text(text, encoding="utf-8", newline="\n")

    def run_hook(self, payload, markers=None):
        env = dict(CLEAN_ENV)
        env.update(markers if markers is not None else {"CLAUDE_CODE_REMOTE": "true"})
        # utf-8, not the locale: the reason carries an em dash, and cp1252
        # decoding on Windows turned it into mojibake (host pin).
        r = subprocess.run(["bash", self.hook.as_posix()], input=payload,
                           capture_output=True, text=True, encoding="utf-8",
                           env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def turn_end(self, markers=None, active=False, closeout=True):
        # The cloud copy runs only at an explicit closeout: the closeout
        # skill's flag. Most cases here test the copy, so they set it.
        flag = self.root / ".agent-log" / "closeout-requested"
        if closeout:
            flag.touch()
        elif flag.exists():
            flag.unlink()
        return self.run_hook(json.dumps({"session_id": self.session,
                                         "stop_hook_active": active}), markers)

    def survivor_paths(self):
        d = self.root / "handoffs" / "auto"
        return sorted(d.glob("*-session-close-*.md")) if d.is_dir() else []

    def survivors(self):
        return [p.name for p in self.survivor_paths()]

    def survivor_path(self):
        paths = self.survivor_paths()
        self.assertTrue(paths, "no survivor was written")
        # session-close.sh puts its day-log date in the filename, so a rollover
        # between two turn ends writes a SECOND file rather than refreshing the
        # first. Take the newest; assert nothing about the count.
        return max(paths, key=lambda p: (p.stat().st_mtime, p.name))

    def survivor(self):
        return self.survivor_path().read_text(encoding="utf-8")

    def latched(self):
        return (self.root / ".agent-log" / "session-close.state.json").is_file()

    def assert_the_survivor_refreshes(self):
        self.write_daylog(["- 10:00:00 [policy-integrity] first"])
        self.turn_end()
        self.assertIn("first", self.survivor())
        # The precondition that made this defect real: turn 1 latched. Without
        # this the case could pass by the latch never engaging at all.
        self.assertTrue(self.latched(), "turn 1 did not record the latch state, so "
                                        "turn 2 is not actually testing the latch")
        self.write_daylog(["- 10:00:00 [policy-integrity] first",
                           "- 21:00:00 [policy-integrity] second"])
        self.turn_end()
        text = self.survivor()
        self.assertIn("second", text,
                      "the survivor did not refresh on the second turn end: the "
                      "once-per-session latch is short-circuiting the cloud copy "
                      ". On a cloud target these lines are unrecoverable.")
        self.assertIn("first", text, "the refresh dropped the earlier lines")

    # -- the defect, in both worlds ---------------------------------------
    @expected_failure_while_pending
    def test_the_shipped_hook_refreshes_the_survivor(self):
        """The latch defect against the hook AS IT STANDS on disk, not against
        the reconciled copy -- review F1, which measured that the suite's green was
        caused by the reconciliation and could not say so.

        While the latch patch still applies this is a DECLARED expected failure: the
        defect is live, unrepaired and already recorded, so the suite says so
        without going red. The day the operator applies, the same case becomes a
        required pass and the reported state changes from "expected failure" to
        "ok" -- with no edit to this file.
        """
        self.install(SHIPPED_SRC)
        self.assert_the_survivor_refreshes()

    def test_the_pending_repair_refreshes_the_survivor(self):
        """The deliverable itself: the latch patch's own text, as a required pass.

        Skipped once no repair is pending -- then the shipped hook IS the
        subject and the case above owns it. That keeps one live assertion per
        subject, so a hook mutant kills exactly one case.
        """
        if not REPAIR_PENDING:
            self.skipTest("no repair pending; test_the_shipped_hook_refreshes_"
                          "the_survivor is the live subject")
        self.assert_the_survivor_refreshes()

    def test_the_stranded_work_advisory_still_fires_exactly_once(self):
        """The regression this repair most plausibly introduces. The latch
        exists for the advisory; moving the copy above it must not turn the
        warning into a per-turn nag."""
        self.write_daylog(["- 10:00:00 [policy-integrity] first"])
        first = self.turn_end().stdout
        self.assertEqual(json.loads(first)["decision"], "block")
        self.assertIn("stranded work", json.loads(first)["reason"])
        for turn in (2, 3):
            self.assertEqual(self.turn_end().stdout.strip(), "",
                             "the advisory fired again on turn %d" % turn)

    # -- the copy is closeout-only, and never its own stranded work ------
    def test_an_ordinary_cloud_turn_end_writes_no_survivor(self):
        self.write_daylog(["- 10:00:00 [policy-integrity] first"])
        self.turn_end(closeout=False)
        self.assertEqual(self.survivors(), [],
                         "a turn end with no closeout flag wrote a tracked file")

    def test_a_stale_closeout_flag_writes_no_survivor(self):
        self.write_daylog(["- 10:00:00 [policy-integrity] first"])
        flag = self.root / ".agent-log" / "closeout-requested"
        flag.touch()
        old = datetime.now().timestamp() - 3 * 3600
        os.utime(flag, (old, old))
        self.run_hook(json.dumps({"session_id": self.session,
                                  "stop_hook_active": False}))
        self.assertEqual(self.survivors(), [], "a three-hour-old flag still fired the copy")

    def test_its_own_survivor_is_not_stranded_work(self):
        (self.root / "stranded.txt").unlink()
        (self.root / ".gitignore").write_text(".agent-log/\n", encoding="utf-8")
        g = ["git", "-C", self.root.as_posix(), "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run(g + ["add", "-A"], capture_output=True, check=True)
        subprocess.run(g + ["commit", "-qm", "base"], capture_output=True, check=True)
        self.write_daylog(["- 10:00:00 [policy-integrity] first"])
        out = self.turn_end().stdout
        self.assertTrue(self.survivors(), "the closeout wrote no survivor")
        self.assertNotIn("stranded work", out,
                         "the hook counted its own handoffs/auto output as stranded work")

    def test_unpushed_counts_against_origin_head_not_master(self):
        """The ahead-count base is origin's default branch as origin/HEAD names
        it. Here that is main and no master exists, so a master-keyed base
        would count 0, see a clean tree, and stay silent."""
        (self.root / "stranded.txt").unlink()
        (self.root / ".gitignore").write_text(".agent-log/\n", encoding="utf-8")
        g = ["git", "-C", self.root.as_posix(), "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run(g + ["add", "-A"], capture_output=True, check=True)
        subprocess.run(g + ["commit", "-qm", "base"], capture_output=True, check=True)
        subprocess.run(g + ["update-ref", "refs/remotes/origin/main", "HEAD"],
                       capture_output=True, check=True)
        subprocess.run(g + ["symbolic-ref", "refs/remotes/origin/HEAD",
                            "refs/remotes/origin/main"], capture_output=True, check=True)
        subprocess.run(g + ["commit", "-q", "--allow-empty", "-m", "ahead"],
                       capture_output=True, check=True)
        out = self.turn_end(markers={}).stdout
        self.assertTrue(out.strip(), "one commit ahead of origin/main raised no advisory")
        self.assertIn("0 dirty file(s), 1 unpushed commit(s)", json.loads(out)["reason"])

    # -- the block is cloud-only -----------------------------------------
    def test_a_non_cloud_target_writes_no_survivor(self):
        r = self.turn_end(markers={})
        self.assertEqual(self.survivors(), [],
                         "a target with neither marker set must write no survivor")
        # Proves the hook ran to the bottom rather than dying before the block:
        # an empty handoff dir means nothing on its own.
        self.assertEqual(json.loads(r.stdout)["decision"], "block")

    def test_the_selfhost_marker_also_writes_a_survivor(self):
        self.write_daylog(["- 10:00:00 [policy-integrity] first"])
        self.turn_end(markers={"HARNESS_BOUNDARY": "selfhost"})
        names = self.survivors()
        self.assertTrue(names, "the selfhost branch of the cloud guard wrote no "
                               "survivor at all")
        self.assertTrue(names[0].endswith("-session-close-selfhost.md"), names)

    # -- local date, close rule, F2 marker predicate -----------------------
    def test_the_cloud_copy_reads_the_local_date_day_log(self):
        """CLAUDE.md §4 has every day-log writer name its file by
        LOCAL date (log-escape.sh: `date +%F`), so the copy must read that one.
        TZ is forced so local and UTC name different days and the day log
        exists ONLY under the local name -- the one case here that is not
        indifferent to which date the hook reads (harness note 3). Dates come
        from bash, which the hook runs under, not from Python."""
        for tz in ("XXX+23", "XXX-23"):       # POSIX sign: XXX+23 is UTC-23
            local, utc = subprocess.run(
                ["bash", "-c", "date +%F; date -u +%F"], env=dict(CLEAN_ENV, TZ=tz),
                capture_output=True, text=True).stdout.split()
            if local != utc:
                break
        else:
            self.fail("neither TZ put the local date on a different day from UTC")
        (self.root / ".agent-log" / (local + ".md")).write_text(
            "- 23:30:00 [policy-integrity] local-only\n", encoding="utf-8", newline="\n")
        self.turn_end(markers={"CLAUDE_CODE_REMOTE": "true", "TZ": tz})
        self.assertIn("local-only", self.survivor(),
                      "TZ=%s (local %s, utc %s): the copy did not read the "
                      "local-date day log" % (tz, local, utc))

    def test_a_cloud_boundary_states_the_adr_0027_close_rule(self):
        """On managed and selfhost the host sentence "the human
        executes" is the opposite of the rule the gate design set."""
        for name, markers in (("managed", {"CLAUDE_CODE_REMOTE": "true"}),
                              ("selfhost", {"HARNESS_BOUNDARY": "selfhost"})):
            with self.subTest(boundary=name):
                self.session = "sess-close-" + name    # one latch per boundary
                reason = json.loads(self.turn_end(markers=markers).stdout)["reason"]
                for phrase in CLOUD_CLOSE:
                    self.assertIn(phrase, reason)
                self.assertNotIn("the human executes", reason)
                self.assertNotIn("opens a draft PR", reason)

    def test_the_host_advisory_is_the_shipped_text(self):
        """The other half of the close rule: the host keeps propose-and-stop, byte for
        byte apart from the two counts."""
        reason = json.loads(self.turn_end(markers={}).stdout)["reason"]
        m = re.match(r"session-close: stranded work — (\d+) dirty file\(s\), "
                     r"(\d+) unpushed", reason)
        self.assertTrue(m, reason)
        self.assertEqual(reason, HOST_REASON.format(*m.groups()))

    def test_a_damaged_marker_falls_through_to_carry_forward(self):
        """Review F2: detection and extraction must be one predicate. With
        a substring grep, a marker line carrying one trailing byte counted as
        present, awk's exact `$0==m` then extracted nothing, and the session's
        section was lost.

        Review round 2 F4: turn 3 must show the fallback fired only once. The
        section count cannot: a hook whose detection never matches re-fires
        the fallback at every turn end and still keeps the section once. So
        turn 3 must also equal turn 2 on four counts: header, region-marker
        line, carried day-log line, and the "carried forward once" line the
        fallback writes each time it fires. Measured: the shipped
        hook gives (2, 1, 2, 1) at both turns, because turn 3's grep matches
        turn 2's fresh marker. With detection forced false, the fallback's
        own line grows at every turn end. The other three grow only when the
        fallback copies the whole old file.
        """
        self.write_daylog(["- 10:00:00 [policy-integrity] first"])
        self.turn_end()
        path = self.survivor_path()
        text = path.read_text(encoding="utf-8")
        marks = re.findall(r"(?m)^<!-- end session-close generated region.*-->$", text)
        self.assertEqual(len(marks), 1, "turn 1 did not write one region marker line")
        text = (text.replace(marks[0] + "\n", marks[0] + " \n")
                + "\n## SESSION SECTION\nkept\n")
        path.write_text(text, encoding="utf-8", newline="\n")
        counts = {}
        for turn in (2, 3):
            self.turn_end()
            survivor = self.survivor()
            self.assertEqual(survivor.count("## SESSION SECTION"), 1,
                             "turn %d: the section below a damaged marker was lost "
                             "or duplicated" % turn)
            counts[turn] = (
                len(re.findall(r"(?m)^# session-close cloud copy", survivor)),
                len(re.findall(r"(?m)^<!-- end session-close generated region.*-->$",
                               survivor)),
                survivor.count("- 10:00:00 [policy-integrity] first"),
                survivor.count("<!-- carried forward once from the pre-marker file -->"))
        self.assertEqual(counts[3], counts[2],
                         "turn 3: header, region marker, carried day-log line or "
                         "carried-forward line changed (turn 2 %r -> turn 3 %r) -- "
                         "the fallback re-fired instead of detection matching "
                         "turn 2's fresh marker" % (counts[2], counts[3]))

    @expected_failure_while_pending
    def test_a_markerless_survivor_falls_through_to_carry_forward(self):
        """A senior-engineer review (order check (3), RESIDUAL-RISKS 1):
        every survivor fixture in this suite leaves a
        DAMAGED marker line, never an ABSENT one -- the case above always
        appends a trailing byte, it never removes the line. A fallback whose
        extraction only needs the marker's own bytes at the START of a line,
        rather than the shipped exact whole-line test, passes the whole suite
        unnoticed: `m-tolerant.sh` (:116's `cat "$OUT" || true` swapped for
        `awk -v m="$MARK" 'f{print} index($0,m)==1{f=1}' "$OUT" || true`)
        measured `OK (skipped=4)` against the suite before this case.

        This plants the marker-less survivor directly: after turn 1 the
        region-marker line is removed ENTIRELY, so `grep -qxF` correctly finds
        no marker and the carry-forward branch fires. On the shipped hook that
        branch's `cat "$OUT"` still carries the session's appended section
        forward whole. On `m-tolerant.sh` no line in a marker-less file starts
        with the marker, so its `awk` finds nothing to carry and the section is
        lost -- this case must fail there. The survivor must also end with the
        whole old file byte for byte, since a fallback keeping only a trailing
        slice (`tail -n 4 "$OUT"`, review F1) passes both counts.
        """
        self.install(SHIPPED_SRC)
        self.write_daylog(["- 10:00:00 [policy-integrity] first"])
        self.turn_end()
        path = self.survivor_path()
        text = path.read_text(encoding="utf-8")
        marks = re.findall(r"(?m)^<!-- end session-close generated region.*-->$", text)
        self.assertEqual(len(marks), 1, "turn 1 did not write one region marker line")
        text = text.replace(marks[0] + "\n", "")
        self.assertNotIn("end session-close generated region", text,
                         "markerless case: the region-marker line was not removed entirely")
        text += "\n## SESSION SECTION\nkept\n"
        path.write_text(text, encoding="utf-8", newline="\n")
        self.turn_end()
        survivor = self.survivor()
        self.assertEqual(survivor.count("## SESSION SECTION"), 1,
                         "markerless case: a marker-less survivor's section was lost or "
                         "duplicated by the carry-forward fallback")
        self.assertEqual(
            survivor.count("<!-- carried forward once from the pre-marker file -->"),
            1, "markerless case: the fallback's own line did not fire exactly once")
        self.assertTrue(survivor.endswith(text),
                        "markerless case: the survivor does not end with the whole "
                        "marker-less file -- the carry-forward fallback kept only "
                        "part of it")

    # -- the short-circuits ahead of everything ---------------------------
    def test_stop_hook_active_still_short_circuits(self):
        self.write_daylog(["- 10:00:00 [policy-integrity] first"])
        r = self.turn_end(active=True)
        self.assertEqual(r.stdout.strip(), "")
        self.assertEqual(self.survivors(), [])

    def test_a_missing_session_id_still_exits_zero(self):
        self.write_daylog(["- 10:00:00 [policy-integrity] first"])
        r = self.run_hook(json.dumps({"stop_hook_active": False}))
        self.assertEqual(r.stdout.strip(), "")
        self.assertEqual(self.survivors(), [])

    # -- what the copy actually captures ----------------------------------
    def test_the_copy_carries_the_classes_whose_writers_it_matches(self):
        """Every fixture is a line a real writer produced: policy-integrity's
        baseline, policy-prompt's unlock, git-guard's DENY, and root CLAUDE.md §4's
        mandated `[peer-*]` commentary.

        CORRECTION, 2026-09-17 (review F3): an earlier revision of this file
        recorded the bracketed `peer-` alternative as structurally dead, on a
        measurement scoped to two gitignored day logs. It is live. A tracked
        session-close survivor held a `[peer-probe]` line that no other alternative in the pattern
        matches, and root CLAUDE.md §4 mandates exactly that shape.
        """
        rows = fixtures()
        self.write_daylog([line for _, line, _, _ in rows])
        self.turn_end()
        text = self.survivor()
        for cls, line, carried, why in rows:
            if carried:
                self.assertIn(line, text, "%s class dropped (%s): %r"
                              % (cls, why, line))

    # -- the escape gap, in both worlds ----------------------------------
    # RETIRED HERE: test_the_copy_does_not_carry_a_performed_escape, which
    # asserted the gap as measured and said so in its own docstring -- "the day
    # a ruling widens the pattern the case goes red on purpose and the reader is
    # updated with it". That ruling is the operator's of 2026-09-20. Its two
    # standing assertions survive inverted below: a PERFORMED escape
    # is carried alongside the REFUSED one, and the block is still proven to
    # have run rather than passing on an empty file.

    # The PRODUCERS row for the performed escape keeps `carried=False`. That
    # field is read only by test_the_copy_carries_the_classes_whose_writers_it_
    # matches -- "whose writers IT MATCHES", the grep -- and it stays a true
    # statement about the grep in the degraded branch. These two cases own the
    # performed escape in both worlds, so no world leaves it unasserted.
    def assert_the_copy_carries_a_performed_escape(self):
        rows = [r for r in fixtures() if r[0] == "escape"]
        self.assertEqual(2, len(rows), "expected both escape fixtures -- git-guard's "
                                       "REFUSED one and log-escape's PERFORMED one; "
                                       "got %d" % len(rows))
        self.write_daylog([line for _, line, _, _ in rows])
        self.turn_end()
        text = self.survivor()
        for cls, line, _, why in rows:
            self.assertIn(line, text, "%s (%s) was dropped: %r" % (cls, why, line))
        # The block ran and produced lines, rather than the survivor being empty
        # or the filter silently degrading -- both of which reproduce the defect.
        self.assertNotIn("(no matching lines today)", text)
        self.assertNotIn("DEGRADED", text)

    @expected_failure_while_escape_pending
    def test_the_shipped_hook_carries_a_performed_escape(self):
        """The escape repair against the hook AS IT STANDS on disk.

        While the escape patch still forward-applies this is a DECLARED
        expected failure: the grep carries almost no escape lines, the repair is
        written and unapplied, and the suite says so instead of going quietly
        green. The day the operator applies it, this becomes a required pass and
        the reported state changes from "expected failure" to "ok" with no edit
        to this file -- the same contract the latch pair above holds.
        """
        self.install(SHIPPED_SRC)
        self.assert_the_copy_carries_a_performed_escape()

    def test_the_pending_escape_repair_carries_a_performed_escape(self):
        """The deliverable: the escape patch's own text, as a required pass.

        This is the cross-language pin -- a bash hook asserted to
        agree with log_filter.py's classifier by RUNNING it, which is the only
        agreement available once the rule has one owner. Skipped once the repair
        is no longer pending, so exactly one case is live per subject and a hook
        mutant kills exactly one.
        """
        if not ESCAPE_PENDING:
            self.skipTest("no escape repair pending; test_the_shipped_hook_carries_"
                          "a_performed_escape is the live subject")
        self.install(ESCAPE_FIXED)
        self.assert_the_copy_carries_a_performed_escape()

    def test_the_pending_escape_repair_fails_loud_not_quiet(self):
        """The failure mode, chosen deliberately: a filter that cannot run says
        so IN the survivor and the grep still runs underneath it.

        Silence is the one unacceptable answer here -- a quiet fall back to the
        grep reproduces the exact defect this repair closes, and an empty block
        reads as a clean day. Both arms of the branch are the same `else`; this
        drives the `[ -f "$CLOSEOUT" ]` arm by removing the planted copy, which
        is also what an unapplied checkout looks like on a cloud target.
        """
        if not ESCAPE_PENDING:
            self.skipTest("no escape repair pending")
        self.install(ESCAPE_FIXED)
        (self.root / "scripts" / "log_filter.py").unlink()
        grant = "- 10:00:00 [policy-integrity] baseline taken"
        escape = "- 10:00:01 [log-escape] push: git push origin lane-1"
        self.write_daylog([grant, escape])
        self.turn_end()
        text = self.survivor()
        self.assertIn("DEGRADED", text, "the filter could not run and the survivor "
                                        "said nothing about it")
        self.assertIn("ESCAPE LINES ARE MISSING", text)
        self.assertIn(grant, text, "the degraded fallback lost the grant lines too")
        self.assertNotIn(escape, text, "the fallback is the old grep; if it now "
                                       "carries escapes this marker is a lie")

    def test_the_pending_escape_repair_still_carries_the_grant_classes(self):
        """Union, not replacement: the regression the repair could most
        plausibly introduce is trading the grep's classes for the filter's. The
        block's header promises all three of escape, grant and integrity."""
        if not ESCAPE_PENDING:
            self.skipTest("no escape repair pending; test_the_copy_carries_the_"
                          "classes_whose_writers_it_matches is the live subject")
        self.install(ESCAPE_FIXED)
        rows = fixtures()
        self.write_daylog([line for _, line, _, _ in rows])
        self.turn_end()
        text = self.survivor()
        for cls, line, carried, why in rows:
            if carried:
                self.assertIn(line, text, "%s class dropped by the repair (%s): %r"
                              % (cls, why, line))

    def test_the_enforcement_doc_names_exactly_the_classes_this_suite_pins(self):
        """The prose reader. docs/enforcement/CLAUDE.md:27 is the obligation
        this suite was filed against, and until now nothing read its text:
        editing its class list changed no test (review residual risk 3). Adding
        or removing a class there now fails here until the fixtures follow."""
        self.assertEqual(classes_in_the_enforcement_doc(),
                         sorted({cls for cls, _, _, _ in fixtures()}),
                         "docs/enforcement/CLAUDE.md:27's class list and this "
                         "suite's fixtures disagree; the obligation moved and "
                         "its reader did not")

    def test_the_pending_repair_patch_is_checked_out_lf(self):
        for patch in (DEFAULT_PATCH, ESCAPE_PATCH):
            if patch.is_file():
                self.assertNotIn(b"\r\n", patch.read_bytes(), patch)

    # -- the suite's own contract -----------------------------------------
    def test_the_resolved_world_is_the_hook_under_test(self):
        """What the module-level resolution hands the
        other tests -- HOOK_SRC above all, which setUp installs for every test
        that reads the world nowhere else. A repair is pending exactly when its
        patch forward-applies to the hook; the subject is then the patched copy,
        otherwise the hook byte for byte. No bash, so the F2 case's child runs it,
        and a resolution that hands those tests other bytes goes red there too."""
        self.assertTrue(SHIPPED_SRC == HOOK.read_text(encoding="utf-8"),
                        "SHIPPED_SRC is not the text of the hook under test %s" % HOOK)
        override = os.environ.get("SESSION_CLOSE_PATCH")
        patch = None if override == "" else Path(override or DEFAULT_PATCH)
        fixed = patched(SHIPPED_SRC, patch) if patch and patch.is_file() else None
        self.assertEqual(REPAIR_PENDING, fixed is not None, WORLD)
        self.assertTrue(HOOK_SRC == (SHIPPED_SRC if fixed is None else fixed),
                        "resolve_world() handed setUp bytes that are neither the hook "
                        "under test nor its patched copy (%s)" % WORLD)
        escape = patched(SHIPPED_SRC, ESCAPE_PATCH) if ESCAPE_PATCH.is_file() else None
        self.assertEqual(ESCAPE_PENDING, escape is not None)
        self.assertTrue(ESCAPE_FIXED == escape, "ESCAPE_FIXED is not %s applied to "
                                                "the hook under test" % ESCAPE_PATCH)

    def world_keyed_tests(self, knobs):
        """The F2 case's child run: (names, how many of them may skip).

        Every test (this case excepted) that reads a world name per world_slice().
        setUp's reads are followed by no test, so they must be ones the identity
        case above also reads -- it is what pins them -- or this fails loud.
        May skip: a test other than that pin which reads a world flag (a world
        name bound to a bool), however its gate is spelt. Which of them skip is
        not predicted (review finding: a count read off the gates' spelling went
        red on a behaviour-preserving respelling); the pin checks the flags.
        """
        world, reads = world_slice(knobs, type(self))
        tests = sorted(n for n in reads if n.startswith("test"))
        self.assertEqual(tests, sorted(unittest.TestLoader().getTestCaseNames(type(self))),
                         "this class runs tests its own body does not define (inherited?);"
                         " world_slice() cannot read them")
        pin = self.test_the_resolved_world_is_the_hook_under_test.__name__
        self.assertLessEqual(reads["setUp"], reads[pin],
                             "setUp reads world names %r that %s does not pin"
                             % (sorted(reads["setUp"] - reads[pin]), pin))
        names = [n for n in tests if n != self._testMethodName and reads[n]]
        self.assertIn(pin, names, "%s pins setUp's world and must run in the child" % pin)
        flags = {n for n in world if isinstance(globals().get(n), bool)}
        return names, sum(bool(reads[n] & flags) for n in names if n != pin)

    def test_a_correct_repair_with_other_bytes_keeps_the_suite_green(self):
        """Review F2, the red-when-correct defect: the previous revision exited
        rc=1 -- which scripts/run_tests.py buckets as a tree-wide FAIL -- on any
        correct repair whose text was not the latch patch's, including an ordinary
        maintenance edit inside the patch's context windows.

        This builds such a hook and runs, against it, the tests whose verdict can
        differ from this process's (not the whole file -- that re-ran
        every hook case twice and was over run_tests' 120 s limit on Windows).
        WHICH: world_keyed_tests(), computed from this file's syntax tree by
        world_slice(), not listed. WHY they decide it: (1) the resolution runs at
        import, so an abort is rc=1 whatever is selected; (2) a misclassified
        world shows only in a test that reads a flag -- the pin re-derives both
        flags, an expectedFailure goes unexpected-success -- and every such test
        is selected; (3) the rest read the world only through setUp's HOOK_SRC,
        which test_the_resolved_world_is_the_hook_under_test pins, in the child,
        to the variant's own bytes. They would run the variant, which is this
        process's subject plus two comment edits. That equivalence is by
        construction, not asserted: a variant that
        changed behaviour would need them back.

        rc 0 from a child that ran only skips is a pass for nothing, so the child
        must run exactly the names given and skip no more than the ones that read
        a world flag, the pin not counted -- so at least one executes. Which of
        those skip is not predicted here; that the child's flags match its hook
        is the pin's check, in the child.

        It asserts a property of THIS FILE, not of the hook, so no hook mutant
        can reach it; falsify it by restoring the abort branch in resolve_world(),
        which turns this green into rc=1.
        """
        if os.environ.get(CHILD):
            self.skipTest("child run: this case launches the suite and must not recurse")
        variant = a_correct_repair_with_other_bytes()
        self.assertNotEqual(variant, SHIPPED_HOOK.read_text(encoding="utf-8"),
                            "the variant is byte-identical to the shipped hook, "
                            "so it proves nothing about textual difference")
        if DEFAULT_PATCH.is_file():
            self.assertFalse(reconciles(variant, DEFAULT_PATCH),
                             "the variant still reconciles against the latch patch, so "
                             "it is not the shape that used to abort the suite")
        path = self.root / "variant-session-close.sh"
        path.write_text(variant, encoding="utf-8", newline="\n")
        # The child differs from this process in these knobs alone (CHILD aside,
        # which only this case reads), and they seed world_slice(). The two patch
        # overrides exist to prove a red in THIS process; leaking one into the
        # child turns its deliberate red into a second, meaningless failure here.
        knobs = {"SESSION_CLOSE_HOOK": path.as_posix(),
                 "SESSION_CLOSE_PATCH": None, "SESSION_CLOSE_ESCAPE_PATCH": None}
        env = {k: v for k, v in os.environ.items() if k not in knobs}
        env.update({k: v for k, v in knobs.items() if v is not None})
        env[CHILD] = "1"
        names, may_skip = self.world_keyed_tests(set(knobs))
        r = subprocess.run([sys.executable, str(Path(__file__).resolve())]
                           + [type(self).__name__ + "." + n for n in names],
                           env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0,
                         "the suite is not green against a correct repair that is "
                         "not the latch patch's bytes:\n" + r.stdout + r.stderr)
        self.assertIn("hook=%s\n" % path, r.stdout, "the child did not resolve the variant")
        ran = re.search(r"(?m)^Ran (\d+) tests?\b", r.stderr)
        ok = re.search(r"(?m)^OK(?: \((.*)\))?$", r.stderr)
        skipped = re.search(r"\bskipped=(\d+)", (ok and ok.group(1)) or "")
        self.assertEqual(ran and int(ran.group(1)), len(names),
                         "the child was handed the %d world-keyed tests %r and did "
                         "not run them all:\n%s" % (len(names), names, r.stderr))
        self.assertLessEqual(
            int(skipped.group(1)) if skipped else 0, may_skip,
            "the child skipped more tests than the %d that read a world flag (the "
            "pin aside). Either a test skipped on something other than the world, "
            "which proves nothing about the variant, or one skips on a world name "
            "that is not a bool, which this bound does not count:\n%s"
            % (may_skip, r.stderr))


if __name__ == "__main__":
    unittest.main(verbosity=2)
