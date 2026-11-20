#!/usr/bin/env python
"""session-close.sh: a child's own commands never run, and the cloud audit copy
covers every day the session spans.

Two concerns, one file:

  (a)   The stranded-work loop runs `git status` in each repos/* child. Status
        reads the work tree, so it ran the child's core.fsmonitor and its filter
        drivers (clean on a stat-dirty file, process). The hook now neutralizes
        both, the way policy-integrity.py's ls-files does (`-c core.fsmonitor=
        false`). The child must still be COUNTED: a guard that skips
        the child would also keep the marker absent.
  (b)   The cloud copy read only TODAY's day log, so a session that crossed
        midnight lost the earlier day's lines. It now
        copies every day file from the earliest present through today. The
        single-day survivor must read exactly as it always has.

tests/test_session_close.py is the long-standing reader of the same hook; this
file adds the two concerns' cases and leaves that one alone.

SESSION_CLOSE_HOOK=<path> asserts against that file instead of the shipped hook
(how these cases were proven red against the base hook).

WHAT THIS HARNESS SETS THAT THE LIVE ENVIRONMENT DOES NOT:
  1. ROOT= is rewritten to a temp dir and a COPY of the hook runs there, with
     scripts/log_filter.py planted beside it. Nothing touches this tree's
     .agent-log/ or handoffs/.
  2. HOME and XDG_CONFIG_HOME are temp dirs and GIT_CONFIG_NOSYSTEM=1, so the
     only filter drivers are the fixture's (a host's global git-lfs filter would
     otherwise be neutralized too, which is the hook's behaviour, not noise).
  3. CLAUDE_CODE_REMOTE, HARNESS_BOUNDARY, CLAUDE_PROJECT_DIR and any inherited
     GIT_CONFIG_* are scrubbed, then set per case. TZ=UTC is fixed, and the day
     names come from bash's `date` under that env, the clock the hook reads.
"""
import datetime
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SHIPPED_HOOK = REPO / ".claude" / "hooks" / "session-close.sh"
HOOK = Path(os.environ.get("SESSION_CLOSE_HOOK") or SHIPPED_HOOK)
LOG_FILTER = REPO / "scripts" / "log_filter.py"
MARK = ("<!-- end session-close generated region; content below is the "
        "session's and is preserved -->")

SCRUB = ("CLAUDE_CODE_REMOTE", "HARNESS_BOUNDARY", "CLAUDE_PROJECT_DIR",
         "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT", "GIT_DIR", "GIT_WORK_TREE")

print("session-close (child scan and day span) suite: hook=%s" % HOOK)


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sessclose-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.root = self.tmp / "root"
        self.home = self.tmp / "home"
        self.marker = self.tmp / "marker"
        for d in (self.root / ".agent-log", self.root / "scripts", self.home):
            d.mkdir(parents=True)
        src, n = re.subn(r"(?m)^ROOT=.*$", 'ROOT="%s"' % self.root.as_posix(),
                         HOOK.read_text(encoding="utf-8"))
        self.assertEqual(n, 1, "the hook no longer has exactly one ROOT= line")
        self.hook = self.root / "session-close.sh"
        self.hook.write_text(src, encoding="utf-8", newline="\n")
        shutil.copy(LOG_FILTER, self.root / "scripts" / "log_filter.py")
        self.env = {k: v for k, v in os.environ.items()
                    if k not in SCRUB and not k.startswith("GIT_CONFIG_")}
        self.env.update(HOME=str(self.home), XDG_CONFIG_HOME=str(self.home / ".config"),
                        GIT_CONFIG_NOSYSTEM="1", TZ="UTC")
        self.git(self.root, "init", "-q")
        self.git(self.root, "commit", "-q", "--allow-empty", "-m", "init")

    # -- harness ---------------------------------------------------------
    def git(self, where, *args):
        r = subprocess.run(["git", "-C", str(where),
                            "-c", "user.name=t", "-c", "user.email=t@t"] + list(args),
                           capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 0, "git %s: %s" % (args, r.stderr))
        return r.stdout

    def day(self, offset=0):
        r = subprocess.run(["bash", "-c", "date -d '%d day' +%%F 2>/dev/null || "
                            "date -v%+dd +%%F" % (offset, offset)],
                           capture_output=True, text=True, env=self.env)
        return r.stdout.strip()

    def run_hook(self, args=(), stdin="", cloud=False):
        env = dict(self.env)
        if cloud:
            env["CLAUDE_CODE_REMOTE"] = "true"
            (self.root / ".agent-log" / "closeout-requested").touch()
        r = subprocess.run(["bash", self.hook.as_posix()] + list(args), input=stdin,
                           capture_output=True, text=True, encoding="utf-8", env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def stop(self, cloud=False):
        return self.run_hook(stdin=json.dumps({"session_id": "sA",
                                               "stop_hook_active": False}),
                             cloud=cloud)

    def script(self, name, body):
        p = self.tmp / name
        p.write_text("#!/bin/sh\n" + body, encoding="utf-8", newline="\n")
        p.chmod(0o755)
        return p.as_posix()

    def marker_text(self):
        return self.marker.read_text(encoding="utf-8") if self.marker.exists() else ""

    def child(self, attributes, files, name="child"):
        c = self.root / "repos" / name
        c.mkdir(parents=True)
        self.git(c, "init", "-q")
        (c / ".gitattributes").write_text(attributes, encoding="utf-8")
        for f in files:
            (c / f).write_text("same\n", encoding="utf-8")
        self.git(c, "add", ".")
        self.git(c, "commit", "-q", "-m", "tracked")
        return c

    def stat_dirty(self, c, files):
        # Stat data that no longer matches the index makes status hash the
        # file, through its clean filter. One untracked file keeps the child
        # dirty, so the advisory names it only if status RAN on the child.
        for f in files:
            os.utime(c / f, (1_000_000_000, 1_000_000_000))
        (c / "untracked.txt").write_text("u\n", encoding="utf-8")

    def assert_child_counted(self, r, name="child"):
        self.assertIn("repos/%s: 1 dirty" % name, r.stdout,
                      "the child was not counted (status skipped or failed), so an "
                      "absent marker would prove nothing: %r %r" % (r.stdout, r.stderr))

    def submodule_with_filter(self, nested=False):
        leaf = self.tmp / "leaf-source"
        leaf.mkdir()
        self.git(leaf, "init", "-q")
        (leaf / ".gitattributes").write_text("data.txt filter=submark\n", encoding="utf-8")
        (leaf / "data.txt").write_text("original\n", encoding="utf-8")
        self.git(leaf, "add", ".")
        self.git(leaf, "commit", "-qm", "leaf")
        source = leaf
        if nested:
            source = self.tmp / "parent-source"
            source.mkdir()
            self.git(source, "init", "-q")
            self.git(source, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(leaf), "inner")
            self.git(source, "commit", "-qm", "parent")
        child = self.child("", [])
        self.git(child, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(source), "sub")
        self.git(child, "-c", "protocol.file.allow=always", "submodule", "update", "--init", "--recursive")
        self.git(child, "commit", "-qm", "add submodule")
        target = child / "sub" / ("inner" if nested else "")
        flt = self.script("sub-filter.sh", 'echo ran >> "%s"\ncat\n' % self.marker.as_posix())
        self.git(target, "config", "filter.submark.clean", flt)
        (target / "data.txt").write_text("modified\n", encoding="utf-8")
        os.utime(target / "data.txt", (1_000_000_000, 1_000_000_000))
        return child

    def test_submodule_filter_does_not_run_and_dirty_is_counted(self):
        self.submodule_with_filter()
        r = self.stop()
        self.assertEqual(self.marker_text(), "", "submodule clean filter ran")
        self.assert_child_counted(r)

    def test_nested_submodule_filter_does_not_run_and_dirty_is_counted(self):
        self.submodule_with_filter(nested=True)
        r = self.stop()
        self.assertEqual(self.marker_text(), "", "nested submodule clean filter ran")
        self.assert_child_counted(r)

    def test_required_submodule_process_filter_is_disabled(self):
        child = self.submodule_with_filter()
        sub = child / "sub"
        self.git(sub, "config", "--unset", "filter.submark.clean")
        process = self.script("sub-process.sh", 'echo ran >> "%s"\nexit 1\n' % self.marker.as_posix())
        self.git(sub, "config", "filter.submark.process", process)
        self.git(sub, "config", "filter.submark.required", "true")
        r = self.stop()
        self.assertEqual(self.marker_text(), "", "required submodule process filter ran")
        self.assert_child_counted(r)

    def test_unreadable_submodule_does_not_hide_healthy_sibling(self):
        child = self.submodule_with_filter()
        sub = child / "sub"
        index = Path(self.git(sub, "rev-parse", "--git-path", "index").strip())
        if not index.is_absolute():
            index = sub / index
        index.write_bytes(b"not a git index")
        sibling = self.root / "repos" / "healthy"
        sibling.mkdir()
        self.git(sibling, "init", "-q")
        self.git(sibling, "commit", "-q", "--allow-empty", "-m", "sibling")
        (sibling / "pending.txt").write_text("pending\n", encoding="utf-8")
        r = self.stop()
        self.assertEqual(self.marker_text(), "", "unreadable submodule ran a filter")
        self.assertIn("repos/child: unreadable", r.stdout)
        self.assertIn("repos/healthy: 1 dirty, 0 unpushed", r.stdout)

    def test_uninitialized_submodule_does_not_hide_child(self):
        child = self.submodule_with_filter()
        self.git(child, "submodule", "deinit", "-f", "sub")
        (child / "pending.txt").write_text("pending\n", encoding="utf-8")
        r = self.stop()
        self.assertEqual(self.marker_text(), "")
        self.assertIn("repos/child: 1 dirty, 0 unpushed", r.stdout)

    def test_failed_submodule_scan_says_status_may_not_have_run(self):
        (self.root / ".gitignore").write_text(".agent-log/\nrepos/\nscripts/\nsession-close.sh\n")
        self.git(self.root, "add", ".gitignore")
        self.git(self.root, "commit", "-qm", "ignore fixture files")
        child = self.submodule_with_filter()
        sub = child / "sub"
        index = Path(self.git(sub, "rev-parse", "--git-path", "index").strip())
        if not index.is_absolute():
            index = sub / index
        index.write_bytes(b"not a git index")
        r = self.stop()
        self.assertEqual(self.marker_text(), "")
        self.assertIn("repos/child", r.stdout)
        self.assertIn("was not run because its safe configuration scan failed", r.stdout)

    def test_submodule_symlink_cycle_is_reported_unreadable(self):
        child = self.submodule_with_filter()
        (child / "sub").rename(self.tmp / "saved-submodule")
        try:
            os.symlink(child, child / "sub", target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest("symlinks unavailable: %s" % exc)
        r = self.stop()
        self.assertEqual(self.marker_text(), "")
        self.assertIn("repos/child: unreadable", r.stdout)

    # -- (a): the child's own commands do not run ----------------------
    def test_child_fsmonitor_does_not_run(self):
        c = self.child("", ["a.txt"])
        fsm = self.script("fsmonitor.sh", 'echo "fsmonitor $*" >> "%s"\nexit 1\n'
                          % self.marker.as_posix())
        self.git(c, "config", "core.fsmonitor", fsm)
        self.stat_dirty(c, ["a.txt"])
        r = self.stop()
        self.assertEqual(self.marker_text(), "",
                         "session-close's child git status ran the child's core.fsmonitor")
        self.assert_child_counted(r)

    def test_child_clean_and_process_filters_do_not_run(self):
        flt = self.script("filter.sh", 'echo "filter $*" >> "%s"\ncat\n'
                          % self.marker.as_posix())
        c = self.child("a.txt filter=mark\nb.txt filter=proc\nc.txt filter=a=b\n",
                       ["a.txt", "b.txt", "c.txt"])
        # set AFTER the commit, so only the status under test can run them
        self.git(c, "config", "filter.mark.clean", flt + " clean")
        self.git(c, "config", "filter.mark.smudge", flt + " smudge")
        self.git(c, "config", "filter.proc.process", flt + " process")
        # a name holding '=', which `-c key=value` cannot express
        self.git(c, "config", "filter.a=b.clean", flt + " eq-clean")
        self.stat_dirty(c, ["a.txt", "b.txt", "c.txt"])
        r = self.stop()
        self.assertEqual(self.marker_text(), "",
                         "session-close's child git status ran a child filter driver")
        self.assert_child_counted(r)

    def test_a_required_child_filter_neither_runs_nor_hides_the_child(self):
        flt = self.script("filter.sh", 'echo "filter $*" >> "%s"\ncat\n'
                          % self.marker.as_posix())
        c = self.child("a.txt filter=req\n", ["a.txt"])
        self.git(c, "config", "filter.req.clean", flt + " clean")
        self.git(c, "config", "filter.req.required", "true")
        self.stat_dirty(c, ["a.txt"])
        r = self.stop()
        self.assertEqual(self.marker_text(), "",
                         "session-close's child git status ran a required child filter")
        # an emptied filter that stays required fails status, which skips the child
        self.assert_child_counted(r)

    def test_a_decoy_filter_name_does_not_shield_the_real_one(self):
        # a name-list dedupe skipped "mark" once it had
        # seen "x mark", so mark's clean ran
        flt = self.script("filter.sh", 'echo "filter $*" >> "%s"\ncat\n'
                          % self.marker.as_posix())
        c = self.child("a.txt filter=mark\n", ["a.txt"])
        self.git(c, "config", "filter.x mark.clean", "true")   # listed first
        self.git(c, "config", "filter.mark.clean", flt + " clean")
        self.stat_dirty(c, ["a.txt"])
        r = self.stop()
        self.assertEqual(self.marker_text(), "",
                         "a decoy filter name kept the child's real filter live")
        self.assert_child_counted(r)

    def test_each_filter_name_is_overridden_once_per_child_scan(self):
        # a global filter (git-lfs style) matched again in
        # every submodule appended its overrides again each time, so the count
        # handed to the child's status grew with the submodule count and each
        # status parsed the lot. Each distinct name must add 4 overrides once.
        # Names are literals: "[a]" must not shadow "a", "g*" must not shadow
        # "gx", and a name with a space and '=' is one name.
        names = ["shared", "[a]", "a", "g*", "gx", "sp ace=x"]
        for n in ("shared",):
            for v in ("clean", "smudge", "process"):
                self.git(self.root, "config", "--global", "filter.%s.%s" % (n, v), "true")
        src = self.tmp / "sub-source"
        src.mkdir()
        self.git(src, "init", "-q")
        (src / "f.txt").write_text("x\n", encoding="utf-8")
        self.git(src, "add", ".")
        self.git(src, "commit", "-qm", "src")
        child = self.child("", [])
        for i in range(4):
            self.git(child, "-c", "protocol.file.allow=always", "submodule", "add", "-q",
                     str(src), "sub%d" % i)
        self.git(child, "commit", "-qm", "add submodules")
        redefined = {1: ["shared", "[a]", "a"], 2: ["g*", "gx", "shared"], 3: ["sp ace=x"]}
        for i, subnames in redefined.items():
            for n in subnames:
                self.git(child / ("sub%d" % i), "config", "filter.%s.clean" % n, "true")
        (child / "untracked.txt").write_text("u\n", encoding="utf-8")
        # a git shim that records the override count handed to the hook's status
        log = self.tmp / "status-calls.log"
        real = shutil.which("git", path=self.env.get("PATH"))
        shim_dir = self.tmp / "shim"
        shim_dir.mkdir()
        shim = shim_dir / "git"
        shim.write_text('#!/bin/sh\necho "COUNT=${GIT_CONFIG_COUNT-unset} ARGS=$*" >> "%s"\n'
                        'exec "%s" "$@"\n' % (log.as_posix(), real),
                        encoding="utf-8", newline="\n")
        shim.chmod(0o755)
        self.env["PATH"] = str(shim_dir) + os.pathsep + self.env.get("PATH", "")
        r = self.stop()
        calls = [l for l in log.read_text(encoding="utf-8").splitlines()
                 if " status " in l and "repos/child/ status" in l]
        self.assertEqual(len(calls), 1, "expected one child status call: %r" % calls)
        count = int(calls[0].split()[0].split("=", 1)[1])
        self.assertEqual(count, 4 * len(names),
                         "child status got %d overrides, want 4 x %d distinct names"
                         % (count, len(names)))
        self.assert_child_counted(r)

    def test_a_glob_named_filter_is_not_shadowed_by_an_earlier_literal(self):
        # the dedup must compare names as literals. An
        # unquoted case pattern lets "*", "?" and "[a]" glob-match the names
        # "zzz" and "a" already seen, so those filters got no override and ran.
        # The glob names are configured AFTER the names they would match.
        flt = self.script("filter.sh", 'echo "filter $*" >> "%s"\ncat\n'
                          % self.marker.as_posix())
        files = {"x.dat": "*", "y.dat": "?", "z.dat": "[a]"}
        c = self.child("".join("%s filter=%s\n" % kv for kv in files.items()),
                       list(files))
        # config order is scan order: literals first, then the glob names
        for n in ("zzz", "a", "*", "?", "[a]"):
            self.git(c, "config", "filter.%s.clean" % n, flt + " clean")
        self.stat_dirty(c, list(files))
        r = self.stop()
        self.assertEqual(self.marker_text(), "",
                         "a glob-named filter was shadowed by an earlier literal name "
                         "and its clean driver ran")
        self.assert_child_counted(r)

    def test_a_global_filter_is_overridden_in_every_child(self):
        # FILTER_SEEN must reset per repos/* child. Reset
        # once above the child loop, a name seen in the first child (here a
        # global, git-lfs style filter) gets no override in the second, and
        # its clean driver runs during that child's status.
        flt = self.script("filter.sh", 'echo "filter $*" >> "%s"\ncat\n'
                          % self.marker.as_posix())
        self.git(self.root, "config", "--global", "filter.shared.clean", flt + " clean")
        names = ("c1", "c2")
        for n in names:
            c = self.child("a.txt filter=shared\n", ["a.txt"], name=n)
            self.stat_dirty(c, ["a.txt"])
        # the children's `git add` ran the global clean filter: start clean
        if self.marker.exists():
            self.marker.unlink()
        r = self.stop()
        self.assertEqual(self.marker_text(), "",
                         "a filter name shared by two children got no override in "
                         "the second child and its clean driver ran")
        for n in names:
            self.assert_child_counted(r, n)

    def test_a_prefix_named_filter_is_not_shadowed_by_a_longer_name(self):
        # the dedup must match a whole entry. Without the
        # trailing newline anchor, "a" matches the already-seen "axxb" as a
        # prefix, so filter "a" got no override and its clean driver ran.
        flt = self.script("filter.sh", 'echo "filter $*" >> "%s"\ncat\n'
                          % self.marker.as_posix())
        files = {"x.dat": "axxb", "y.dat": "a"}
        c = self.child("".join("%s filter=%s\n" % kv for kv in files.items()),
                       list(files))
        # config order is scan order: the longer name first, then its prefix
        for n in ("axxb", "a"):
            self.git(c, "config", "filter.%s.clean" % n, flt + " clean")
        self.stat_dirty(c, list(files))
        r = self.stop()
        self.assertEqual(self.marker_text(), "",
                         "a filter named by a proper prefix of an earlier name was "
                         "shadowed and its clean driver ran")
        self.assert_child_counted(r)

    def test_an_unreadable_first_child_does_not_leak_seen_names(self):
        # the unreadable branch leaves the child loop
        # through `continue`, so a FILTER_SEEN reset placed anywhere but before
        # the scan is skipped and the failed child's names carry into the next
        # child. c0 sorts first in the repos/* glob; its config scan succeeds
        # (it reads the global name) and its index read fails, so the scan
        # fails after FILTER_SEEN already holds "shared".
        flt = self.script("filter.sh", 'echo "filter $*" >> "%s"\ncat\n'
                          % self.marker.as_posix())
        self.git(self.root, "config", "--global", "filter.shared.clean", flt + " clean")
        names = ("c0", "c1", "c2")
        for n in names:
            c = self.child("a.txt filter=shared\n", ["a.txt"], name=n)
            self.stat_dirty(c, ["a.txt"])
        broken = self.root / "repos" / "c0"
        index = Path(self.git(broken, "rev-parse", "--git-path", "index").strip())
        if not index.is_absolute():
            index = broken / index
        index.write_bytes(b"not a git index")
        # the children's `git add` ran the global clean filter: start clean
        if self.marker.exists():
            self.marker.unlink()
        r = self.stop()
        self.assertEqual(self.marker_text(), "",
                         "a name seen in an unreadable first child got no override in "
                         "a later healthy child and its clean driver ran")
        self.assertIn("repos/c0: unreadable", r.stdout)
        # c0 was scanned first, so its names were in FILTER_SEEN before c1's scan
        self.assertLess(r.stdout.index("repos/c0: unreadable"),
                        r.stdout.index("repos/c1: 1 dirty"))
        for n in names[1:]:
            self.assert_child_counted(r, n)

    # (kind, long name, proper prefix): the character after the prefix in the
    # long name is the kind. Prefixes are distinct and none is a prefix of
    # another pair's long name.
    NEXT_CHAR_PAIRS = (
        ("space", "s b", "s"), ("tab", "t\tb", "t"), ("letter", "lyb", "l"),
        ("digit", "d1b", "d"), ("dash", "m-b", "m"), ("equals", "e=b", "e"),
        ("star", "a*b", "a"), ("qmark", "q?b", "q"), ("bracket", "b[b", "b"),
    )

    def test_a_prefix_name_is_not_shadowed_for_any_next_character(self):
        # the dedup must match a whole entry, whatever
        # character follows the prefix in the longer, earlier name. A trailing
        # check that rejects only some characters (whitespace, a letter, a
        # glob) passes a single-pair test. One child holds every pair; the
        # clean driver logs its kind, so the marker names the pair that ran.
        flt = self.script("filter.sh", 'echo "filter $*" >> "%s"\ncat\n'
                          % self.marker.as_posix())
        pairs = self.NEXT_CHAR_PAIRS
        files = ["%s.dat" % kind for kind, _, _ in pairs]
        c = self.child("".join("%s.dat filter=%s\n" % (kind, prefix)
                               for kind, _, prefix in pairs), files)
        # config order is scan order: every long name first, then each prefix
        for kind, longer, _ in pairs:
            self.git(c, "config", "filter.%s.clean" % longer, flt + " long-" + kind)
        for kind, _, prefix in pairs:
            self.git(c, "config", "filter.%s.clean" % prefix, flt + " " + kind)
        scanned = self.git(c, "config", "-z", "--name-only", "--get-regexp",
                           r"^filter\..*\.clean$").split("\0")
        self.assertEqual([k for k in scanned if k],
                         ["filter.%s.clean" % n for n in
                          [p[1] for p in pairs] + [p[2] for p in pairs]],
                         "the fixture's scan order is not long names, then prefixes")
        self.stat_dirty(c, files)
        r = self.stop()
        self.assertEqual(self.marker_text(), "",
                         "a filter named by a proper prefix of an earlier name was "
                         "shadowed and its clean driver ran (kinds in the marker)")
        self.assert_child_counted(r)

    def test_a_partial_clone_child_does_not_lazy_fetch(self):
        # a dangling origin/HEAD in a partial clone made
        # rev-parse --verify fetch from the promisor, running core.sshCommand
        c = self.child("", ["a.txt"])
        ssh = self.script("ssh.sh", 'echo "ssh $*" >> "%s"\nexit 1\n'
                          % self.marker.as_posix())
        for key, value in (("core.repositoryformatversion", "1"),
                           ("extensions.partialClone", "origin"),
                           ("remote.origin.url", "ssh://example.invalid/x"),
                           ("remote.origin.promisor", "true"),
                           ("core.sshCommand", ssh)):
            self.git(c, "config", key, value)
        refs = c / ".git" / "refs" / "remotes" / "origin"
        refs.mkdir(parents=True)
        (refs / "main").write_text("1" * 40 + "\n", encoding="utf-8")
        (refs / "HEAD").write_text("ref: refs/remotes/origin/main\n", encoding="utf-8")
        (c / "untracked.txt").write_text("u\n", encoding="utf-8")
        r = self.stop()
        self.assertEqual(self.marker_text(), "",
                         "a session-close child call lazy-fetched and ran core.sshCommand")
        self.assert_child_counted(r)

    def test_a_partial_clone_child_status_does_not_lazy_fetch(self):
        # with HEAD's root tree missing, status fetches it
        # from the promisor, running core.sshCommand. Status then fails and the
        # child goes uncounted, the hook's normal handling of a broken child.
        c = self.child("", ["a.txt"])
        ssh = self.script("ssh.sh", 'echo "ssh $*" >> "%s"\nexit 1\n'
                          % self.marker.as_posix())
        for key, value in (("core.repositoryformatversion", "1"),
                           ("extensions.partialClone", "origin"),
                           ("remote.origin.url", "ssh://example.invalid/x"),
                           ("remote.origin.promisor", "true"),
                           ("core.sshCommand", ssh)):
            self.git(c, "config", key, value)
        tree = self.git(c, "rev-parse", "HEAD^{tree}").strip()
        (c / ".git" / "objects" / tree[:2] / tree[2:]).unlink()
        (c / "untracked.txt").write_text("u\n", encoding="utf-8")
        self.stop()
        self.assertEqual(self.marker_text(), "",
                         "session-close's child status lazy-fetched and ran core.sshCommand")

    # -- (b): every day file the session spans --------------------------
    def write_day(self, day, line):
        (self.root / ".agent-log" / (day + ".md")).write_text(
            "- 23:59:00 [policy-integrity] %s\n- 00:00:01 [hub] not-a-copy-line %s\n"
            % (line, line), encoding="utf-8", newline="\n")

    def spanning_survivor(self, args, stdin):
        for _ in range(2):          # a run that straddles midnight is retried once
            today = self.day()
            self.write_day(self.day(-2), "day-minus-2")
            self.write_day(self.day(-1), "day-minus-1")
            self.write_day(today, "day-today")
            self.write_day(self.day(1), "day-plus-1")
            r = self.run_hook(args, stdin, cloud=True)
            if self.day() == today:
                break
        out = sorted((self.root / "handoffs" / "auto").glob("*-session-close-managed.md"))
        self.assertEqual(len(out), 1, "expected one survivor, got %r" % out)
        return today, out[0], out[0].read_text(encoding="utf-8"), r

    def assert_spans(self, today, path, text):
        for line in ("day-minus-2", "day-minus-1", "day-today"):
            self.assertIn("[policy-integrity] " + line, text,
                          "the copy dropped %s: a session spanning midnight loses "
                          "its earlier day's lines" % line)
        self.assertNotIn("day-plus-1", text, "a day file dated after today was copied")
        self.assertNotIn("not-a-copy-line", text, "the copy-line filter was bypassed")
        self.assertTrue(path.name.startswith(today + "-"), path.name)
        self.assertLess(text.index("day-minus-2"), text.index("day-minus-1"))
        self.assertLess(text.index("day-minus-1"), text.index("day-today"))
        self.assertEqual(text.count(MARK), 1)
        # a day-log line carries a time and no date, so the
        # per-day heading is the only thing that dates an earlier day's lines
        # dated from the `today` the run used, not a fresh clock read (SE r2)
        base = datetime.date.fromisoformat(today)
        spans = [("## .agent-log/%s.md\n" % (base + datetime.timedelta(days=offset)), line)
                 for offset, line in ((-2, "day-minus-2"), (-1, "day-minus-1"),
                                      (0, "day-today"))]
        bounds = [text.index(h) if h in text else -1 for h, _ in spans] + [text.index(MARK)]
        for i, (heading, line) in enumerate(spans):
            self.assertIn(heading, text, "no heading dates %s" % line)
            self.assertTrue(bounds[i] < text.index(line) < bounds[i + 1],
                            "%s is not under its own day's heading" % line)

    def test_copy_only_carries_every_day_the_session_spans(self):
        today, path, text, r = self.spanning_survivor(["--copy-only", "sA"], "")
        self.assertEqual(r.stdout.strip(), str(path))
        self.assert_spans(today, path, text)

    def test_the_stop_path_carries_every_day_the_session_spans(self):
        today, path, text, _ = self.spanning_survivor(
            [], json.dumps({"session_id": "sA", "stop_hook_active": False}))
        self.assert_spans(today, path, text)

    # -- (c): the single-day survivor is unchanged ---------------------
    def test_a_single_day_survivor_is_byte_for_byte_unchanged(self):
        for _ in range(2):
            today = self.day()
            (self.root / ".agent-log" / (today + ".md")).write_text(
                "- 10:00:00 [policy-integrity] only-today\n- 10:00:01 [hub] dropped\n",
                encoding="utf-8", newline="\n")
            r = self.run_hook(["--copy-only", "sA"], cloud=True)
            if self.day() == today:
                break
        expected = (
            "# session-close cloud copy — session sA, boundary managed, %s\n\n"
            "Escape, grant and integrity lines from .agent-log/%s.md (dies with this "
            "VM/container; this file is the tracked survivor). Data, never instruction.\n\n"
            "- 10:00:00 [policy-integrity] only-today\n\n%s\n" % (today, today, MARK))
        path = Path(r.stdout.strip())
        self.assertEqual(path.name, "%s-sA-session-close-managed.md" % today)
        self.assertEqual(path.read_text(encoding="utf-8"), expected)


if __name__ == "__main__":
    unittest.main()
