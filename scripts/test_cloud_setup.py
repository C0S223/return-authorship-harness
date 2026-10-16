#!/usr/bin/env python
"""cloud-setup.sh must arm the pre-push gate wherever the platform puts the
checkout -- and must NOT fail the environment when there is no checkout yet.

Boot 2 (2026-09-16) is why this file exists: the script assumed its cwd was
the checkout, the managed platform ran it in `/home/user` with no `.git`
there, `set -e` took the FAIL branch, and the whole environment refused to
build. The cases below are the states that run observed or implied, plus the
three review-01 findings -- each of which reproduced that same build failure
or a silent mis-arming through a different door.
"""
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "cloud-setup.sh"
BASH = shutil.which("bash")
GIT = shutil.which("git")
# A fixture identity no real checkout can carry. The script searches past
# the fixtures -- the ancestor walk, then literal /home/user/*, /root/* and
# /workspace/* -- and arms the first checkout whose origin matches. With the
# real repository identity here, every case where no fixture matched would
# arm a REAL checkout's .git/config (a policy path).
# Random per run, so no clone anywhere matches; mixed case, so the
# case-variant case below still compares something.
OWNER, NAME = "Fixture-%s" % uuid.uuid4().hex[:12], "Harness-Cloud-Setup"
OURS = "%s/%s" % (OWNER, NAME)

# The identity stops a CORRECT script from arming a real checkout;
# a regressed one (seam ignored, F3 dropped) still would, and an after-check
# only sees the write once it has landed. So the script's `git` is this shim,
# first on its PATH: a `git config` write lands only in a repository under the
# fixture root (as the real git resolves it); any other write is refused
# unwritten and logged, and run_script fails the case. Reads and every other
# subcommand pass through. Unclassifiable config calls count as writes.
GUARD = r"""
: > "$mark"
g=()
while [ $# -gt 0 ]; do
  case $1 in
    -C|-c|--git-dir|--work-tree|--namespace|--config-env|--super-prefix)
      [ $# -ge 2 ] || break; g+=("$1" "$2"); shift 2 ;;
    -*) g+=("$1"); shift ;;
    *) break ;;
  esac
done
[ "${1-}" = config ] || exec "$real" "${g[@]}" "$@"
rd=0 sc=0 fl=0 pos=0 first=
for a in "${@:2}"; do
  case $a in
    --get|--get-all|--get-regexp|--get-urlmatch|--get-color|--get-colorbool|-l|--list) rd=1 ;;
    --global|--system|-f|--file|--file=*) sc=1 fl=1 ;;
    -*) fl=1 ;;
    *) pos=$((pos + 1)); [ -n "$first" ] || first=$a ;;
  esac
done
case $first in get|list) rd=1 ;; esac
[ "$pos" = 1 ] && [ "$fl" = 0 ] && rd=1
[ "$rd" = 1 ] && exec "$real" "${g[@]}" "$@"
r=$(cd -- "$root" 2>/dev/null && pwd -P) || r=
c=$("$real" "${g[@]}" rev-parse --path-format=absolute --git-common-dir 2>/dev/null) &&
  c=$(cd -- "$c" 2>/dev/null && pwd -P) || c=
if [ "$sc" = 0 ] && [ -n "$r" ] && [ -n "$c" ]; then
  case $c/ in "$r"/*) exec "$real" "${g[@]}" "$@" ;; esac
fi
echo "refused: git ${g[*]} $* -- repo ${c:-unresolved}, cwd $PWD" >> "$log"
echo "877 guard: refused a git config write outside $root" >&2
exit 1
"""


def write_guard(root, home):
    """Write the shim under `home` for fixture root `root`; return (bin, log, mark)."""
    (home / "bin").mkdir(parents=True)
    log, mark = home / "refused.log", home / "called"
    head = "#!/usr/bin/env bash\n" + "".join(
        "%s=%s\n" % (k, shlex.quote(Path(v).as_posix()))
        for k, v in (("real", GIT), ("root", root), ("log", log), ("mark", mark)))
    shim = home / "bin" / "git"
    shim.write_bytes((head + GUARD.lstrip("\n")).encode())  # LF even on Windows
    shim.chmod(0o755)
    return home / "bin", log, mark


def git(cwd, *a):
    subprocess.run(["git", "-C", str(cwd), *a], check=True, capture_output=True)


@unittest.skipUnless(BASH and GIT, "no bash or git on PATH")
class CloudSetup(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cs-"))
        self.gbin, self.glog, self.gmark = write_guard(self.tmp, self.tmp / ".guard")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_script(self, cwd, project_dir=None):
        env = dict(os.environ)
        env.pop("CLAUDE_PROJECT_DIR", None)
        env["CLOUD_SETUP_REPO_MATCH"] = OURS
        env["PATH"] = str(self.gbin) + os.pathsep + env.get("PATH", "")
        # The F2 ancestor walk stops at the fixture root, so a TEMP inside
        # a real checkout (the Codex host, 2026-09-30) is never discovered.
        env["GIT_CEILING_DIRECTORIES"] = str(self.tmp)
        if project_dir:
            env["CLAUDE_PROJECT_DIR"] = str(project_dir)
        before = self.real_configs()
        if self.gmark.exists():
            self.gmark.unlink()
        r = subprocess.run([BASH, str(SCRIPT)], cwd=str(cwd), env=env,
                           capture_output=True, text=True, timeout=120)
        refused = self.glog.read_text() if self.glog.exists() else ""
        self.assertEqual("", refused, "877: cloud-setup.sh tried to write a config "
                         "outside the fixture root (refused, not written):\n" + refused)
        self.assertTrue(self.gmark.exists(), "877: cloud-setup.sh's git bypassed the guard")
        self.assertEqual(before, self.real_configs(),
                         "877: cloud-setup.sh changed a real checkout's config")
        return r

    def real_configs(self):
        # 877 after-check, behind the shim (catches a write that bypasses it):
        # the local config of each real checkout an upward walk can reach --
        # this file's own, and whichever encloses the temp root (None where
        # there is none). branch.* is left out: sibling lanes write it into the
        # shared config concurrently.
        snap = {}
        for d in (HERE, self.tmp.parent):
            out = subprocess.run(["git", "-C", str(d), "config", "--list", "--local"],
                                 capture_output=True, text=True)
            snap[str(d)] = ([ln for ln in out.stdout.splitlines()
                             if not ln.startswith("branch.")]
                            if out.returncode == 0 else None)
        return snap

    def checkout(self, name="proj", origin="https://github.com/%s.git" % OURS):
        d = self.tmp / name
        d.mkdir()
        git(d, "init", "-q")
        if origin:
            git(d, "remote", "add", "origin", origin)
        return d

    def hooks_path(self, d):
        out = subprocess.run(["git", "-C", str(d), "config", "--get", "core.hooksPath"],
                             capture_output=True, text=True)
        return out.stdout.strip()

    def test_checkout_at_cwd_is_armed(self):
        d = self.checkout()
        r = self.run_script(d)
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("step 1: OK", r.stdout)
        self.assertEqual(".githooks", self.hooks_path(d))

    def test_checkout_found_via_claude_project_dir_from_elsewhere(self):
        d = self.checkout()
        away = self.tmp / "away"
        away.mkdir()
        r = self.run_script(away, project_dir=d)
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual(".githooks", self.hooks_path(d))

    def test_no_checkout_anywhere_exits_zero_and_says_unarmed(self):
        # The boot-2 failure, inverted: the environment must still build, and
        # the log must name what the operator has to do in the first turn.
        empty = self.tmp / "empty"
        empty.mkdir()
        r = self.run_script(empty)
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("NO CHECKOUT ARMED", r.stdout)
        self.assertIn("UNARMED", r.stdout)
        self.assertIn("auth-policy .git/config", r.stdout)

    def test_second_run_is_idempotent(self):
        d = self.checkout()
        self.assertEqual(0, self.run_script(d).returncode)
        r = self.run_script(d)
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("step 1: OK", r.stdout)
        self.assertIn("step 2: OK", r.stdout)

    # --- review-01 findings ------------------------------------------------
    def test_cwd_below_the_checkout_root_still_arms_it(self):
        # F2: the platform may drop the session in a subdirectory.
        d = self.checkout()
        sub = d / "a" / "b"
        sub.mkdir(parents=True)
        r = self.run_script(sub)
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual(".githooks", self.hooks_path(d))

    def test_a_stranger_repo_is_never_armed(self):
        # F3: arming someone else's checkout is a silent mutation of their
        # config, and leaves this repo's own gate unarmed with no diagnostic.
        theirs = self.checkout("theirs", origin="https://github.com/someone/else.git")
        ours = self.checkout("ours")
        r = self.run_script(ours, project_dir=theirs)
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual("", self.hooks_path(theirs))
        self.assertEqual(".githooks", self.hooks_path(ours))

    def test_a_dangling_gitdir_does_not_kill_the_run(self):
        # F1: `.git` present but broken made `git config` exit 128, and set -e
        # took the environment down -- boot 2's failure through a new door.
        broken = self.tmp / "broken"
        broken.mkdir()
        (broken / ".git").write_text("gitdir: /nonexistent/elsewhere\n")
        r = self.run_script(broken, project_dir=broken)
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("UNARMED", r.stdout)

    def test_a_lookalike_origin_is_never_armed(self):
        # Substring matching would arm `evil-owner/repo-mirror`.
        for bad in ("https://github.com/evil-%s/%s-mirror.git" % (OWNER, NAME),
                    "https://github.com/not%s/%s.git" % (OWNER, NAME),
                    "https://github.com/%s/%s-fork.git" % (OWNER, NAME)):
            with self.subTest(origin=bad):
                d = self.checkout("x" + str(abs(hash(bad)) % 10000), origin=bad)
                r = self.run_script(d)
                self.assertEqual(0, r.returncode, r.stderr)
                self.assertEqual("", self.hooks_path(d))

    def test_ssh_and_case_variant_origins_are_ours(self):
        for good in ("git@github.com:%s.git" % OURS,
                     "https://github.com/%s" % OURS.lower(),
                     "https://github.com/%s.git/" % OURS):
            with self.subTest(origin=good):
                d = self.checkout("y" + str(abs(hash(good)) % 10000), origin=good)
                r = self.run_script(d)
                self.assertEqual(0, r.returncode, r.stderr)
                self.assertEqual(".githooks", self.hooks_path(d))

    def test_a_checkout_with_no_origin_is_never_armed(self):
        d = self.checkout("noorigin", origin=None)
        r = self.run_script(d)
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual("", self.hooks_path(d))

    def test_a_linked_worktree_is_a_valid_checkout(self):
        # This repo's own deployment shape: `.git` is a FILE, not a directory.
        d = self.checkout()
        (d / "f.txt").write_text("x\n")
        git(d, "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
        git(d, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base")
        wt = self.tmp / "wt"
        git(d, "worktree", "add", "-q", "-b", "lane", str(wt))
        self.assertTrue((wt / ".git").is_file())
        r = self.run_script(wt)
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("step 1: OK", r.stdout)

    def test_origin_head_is_recorded_from_the_remote(self):
        # The gates read the default branch from refs/remotes/origin/HEAD and
        # fail closed without it, so the setup step must record it. Origin is a
        # local bare repo whose path reduces to OURS (the cloud-setup.sh ceiling
        # note), with HEAD on main: no network, and no master anywhere.
        src = self.tmp / "src"
        src.mkdir()
        git(src, "init", "-q", "-b", "main")
        (src / "f.txt").write_text("x\n")
        git(src, "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
        git(src, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base")
        bare = self.tmp / "srv" / OWNER / NAME
        git(self.tmp, "clone", "-q", "--bare", str(src), str(bare))
        d = self.checkout(origin=bare.as_posix())
        git(d, "fetch", "-q", "origin")
        r = self.run_script(d)
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("step 1: OK", r.stdout)
        self.assertIn("origin/HEAD -> origin/main", r.stdout)
        out = subprocess.run(["git", "-C", str(d), "symbolic-ref", "-q",
                              "refs/remotes/origin/HEAD"], capture_output=True, text=True)
        self.assertEqual("refs/remotes/origin/main", out.stdout.strip())

    # --- 877: the guard must be able to fail --------------------------------
    def test_the_guard_refuses_a_config_write_outside_its_root(self):
        # A second guard rooted at one fixture makes its sibling "outside", so
        # a refusal is provable without any repo beyond self.tmp.
        inside, outside = self.checkout("inside"), self.checkout("outside")
        gbin, log, mark = write_guard(inside, self.tmp / ".guard2")
        env = dict(os.environ, PATH=str(gbin) + os.pathsep + os.environ.get("PATH", ""))

        def sh(cwd, *args):
            return subprocess.run([BASH, "-c", 'git "$@"', "git", *args], cwd=str(cwd),
                                  env=env, capture_output=True, text=True)
        for how in (("-C", str(outside)), ()):  # -C, then cwd
            with self.subTest(how=how or "cwd"):
                self.assertNotEqual(0, sh(outside, *how, "config", "core.hooksPath",
                                          ".githooks").returncode)
                self.assertEqual("", self.hooks_path(outside))
        refused = log.read_text() if log.exists() else ""
        self.assertEqual(2, refused.count("refused: git"), refused)
        rd = sh(self.tmp, "-C", str(outside), "config", "--get", "remote.origin.url")
        self.assertEqual(0, rd.returncode, rd.stderr)
        self.assertIn(OURS, rd.stdout)
        self.assertEqual(0, sh(self.tmp, "-C", str(inside), "config", "core.hooksPath",
                               ".githooks").returncode)
        self.assertEqual(".githooks", self.hooks_path(inside))
        self.assertTrue(mark.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2 if "-v" in sys.argv else 1)
