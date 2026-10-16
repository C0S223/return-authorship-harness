"""Reads back the item-191 pre-push installation. Run it from anywhere in the tree.

The installed dispatcher at the common hooks dir is UNVERSIONED by necessity --
git does not activate repository-supplied hooks, so the bootstrap copy cannot be
carried by the tree. That makes drift invisible, which is what this file exists
to fix (contract SS6: a convention names what reads the artifact back).

Checks, in order of what actually bites:
  1. The tracked policy and the dispatcher source exist, start with an absolute
     shebang, and have NO CR bytes. A CRLF shebang is not a valid interpreter
     path -- the hook would be dead.
  2. If a dispatcher IS installed, it matches the tracked source byte for byte
     AND is executable. Git silently ignores a non-executable hook, so mode is
     a total fail-open that byte-comparison cannot see. POSIX only; Windows
     executable semantics need their own probe and do not have one here.
  3. under() rejects lexical `..` escapes and name-prefix siblings.
  4. End to end in a scratch repo: the dispatcher blocks a checkout with no
     policy -- from main AND from a linked worktree -- and when a policy is
     present, hands it the exact argv and the exact ref records, and propagates
     its exit status. Every assertion in 2-4 that could silently hold is paired
     with a mutant that makes it fail, so the oracle proves it can lose.

Not installed yet is NOT a failure -- landing the tracked half deliberately
precedes arming the gate -- but it is reported loudly rather than passed over.
It does mean check 2 is unproven until the operator arms the hook.

RUN WITH --require-installed ONCE THE GATE IS ARMED, and wire it into the suite
in the same change that arms it. Without the flag this file cannot tell "not
armed yet" from "armed, then deleted" -- both take the WARN branch and exit 0,
so a gate that was armed and later lost reports GREEN while every push sails
past it. The flag is the whole difference between a read-back and a formality.

DISCLOSURE: check 4 performs real `git push` calls, one of which DELETES a branch
-- a deletion record is a shape the policy has a specific rule about, and it
cannot be produced without deleting something. All of them go to a bare repo this
script creates in a temp dir and deletes, on throwaway branch names, never forced,
never a tag, never the default branch -- there is no other way to prove a hook
fires, since a hook only runs on a real push. A command-text gate cannot see an
interpreter's own subprocess, so this notice is the disclosure (contract SS2).

RESIDUAL, stated because the equivalent tag gap was stated and this one was not:
the fixture never pushes a TAG and never deletes a DEFAULT BRANCH, so a mutant
that tampers with only those two ref shapes would survive. Both are exactly the
records the policy's sharpest rules ride on -- and both are L1 never-items with
no unlock, which an interpreter's own push does not exempt. So the gap is closed
where it can be, in the policy's own 53 fixtures (stdin, no push), and left open
here by rule rather than by oversight. What this file proves is that the
dispatcher relays records faithfully; what shape they are is the policy's test.

Exit 0 = consistent. Exit 1 = drift, corruption, or a broken decision path.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

FAILURES = []


def check(label, ok, detail=""):
    # detail explains a FAILURE; printing it on a pass reads as a contradiction
    print("  %-4s %s%s" % ("OK" if ok else "FAIL", label,
                           ("  -- " + detail) if (detail and not ok) else ""))
    if not ok:
        FAILURES.append(label)
    return ok


def git(*a, cwd=None, stdin=None, check_rc=True):
    r = subprocess.run(["git", *a], cwd=str(cwd) if cwd else None,
                       capture_output=True, text=True, input=stdin)
    if check_rc and r.returncode != 0:
        raise SystemExit("git %s failed:\n%s\n%s" % (" ".join(a), r.stdout, r.stderr))
    return r


def toplevel():
    return Path(git("rev-parse", "--show-toplevel").stdout.strip())


def common_hooks_dir():
    """The hooks dir git will actually consult -- honouring core.hooksPath if set."""
    hp = git("config", "--get", "core.hooksPath", check_rc=False).stdout.strip()
    if hp:
        return Path(hp) if os.path.isabs(hp) else toplevel() / hp, True
    common = Path(git("rev-parse", "--path-format=absolute",
                      "--git-common-dir").stdout.strip())
    return common / "hooks", False


def lf_clean(path, label):
    # existence FIRST: reading before the check made the reporting path below
    # unreachable, so a missing artifact crashed instead of being named
    if not check("%s exists" % label, path.is_file()):
        return None
    raw = path.read_bytes()
    check("%s has no CR bytes" % label, b"\r" not in raw,
          "%d CR found -- a CRLF shebang is not an interpreter" % raw.count(b"\r"))
    # `startswith(b"#!")` accepted a bare `#!` -- a claim stronger than its
    # predicate, which is the same defect shape as a mislabelled assertion.
    first = raw.split(b"\n", 1)[0].rstrip()
    check("%s names an absolute interpreter" % label,
          first.startswith(b"#!/") and len(first) > 3 and b" " not in first[2:3],
          first[:40].decode("utf-8", "replace"))
    return raw


def onerr(func, path, exc):
    os.chmod(path, 0o700)
    func(path)


# A policy that RECORDS what it was handed, rather than merely announcing it ran.
# Reaching the policy is not the contract; being reached with the right argv and an
# INTACT stdin is. The real policy reads its ref records from stdin, so a dispatcher
# that swallows even one line leaves the `while read` loop with nothing -- and the
# policy then exits 0 and allows every push. Measured: `printf '' | sh .githooks/pre-push
# origin <approved-url>` exits 0. An oracle that cannot see stdin cannot see that.
RECORDER = (
    b"#!/bin/sh\n"
    b"{\n"
    b"  printf 'POLICY=%s\\n' \"$0\"\n"
    b"  printf 'ARGC=%s\\n' \"$#\"\n"
    b"  printf 'ARG1=%s\\n' \"${1-}\"\n"
    b"  printf 'ARG2=%s\\n' \"${2-}\"\n"
    b"  while IFS= read -r l; do printf 'REF=%s\\n' \"$l\"; done\n"
    b"} > .prepush-record\n"
    b"exit 1\n"
)

# Each mutates the dispatcher in a way that STILL REACHES the policy -- which is
# exactly why the old oracle passed all three. The installed copy is mutated too,
# so the byte-drift check does not fire: this is the realistic case of someone
# editing the source and re-running the install.
ZERO = "0" * 40

MUTANTS = [
    ("consumes a line of stdin", "single",
     lambda s: s.replace(b'exec /bin/sh "$policy" "$@"',
                         b'read -r _swallowed\nexec /bin/sh "$policy" "$@"')),
    ("drops argv", "single",
     lambda s: s.replace(b'exec /bin/sh "$policy" "$@"',
                         b'exec /bin/sh "$policy"')),
    # LINKED-ONLY, and the reason is a result rather than a convenience: this
    # mutant sets top to <common-git-dir>/.., which FROM THE MAIN WORKTREE
    # resolves to the main worktree itself. It is benign there by construction,
    # so requiring it to die from main would assert a falsehood. The boundary
    # weakness it was proposed to demonstrate is real and is tested directly,
    # against under(), rather than through a fixture that cannot show it.
    ("resolves the policy outside the pushing worktree", "linked-only",
     lambda s: s.replace(b'top=$(git rev-parse --show-toplevel 2>/dev/null)',
                         b'top=$(git rev-parse --path-format=absolute'
                         b' --git-common-dir 2>/dev/null)/..')),
    # The class a single-ref oracle is structurally blind to, and the one that
    # would hurt most: the policy's sharpest rules -- default-branch DELETION and
    # tag denial -- ride on record shapes an ordinary branch update never produces.
    # A dispatcher that forwards updates faithfully and silently drops deletions
    # disables exactly those rules while every single-ref check still passes.
    ("drops deletion records", "mixed",
     lambda s: s.replace(b'exec /bin/sh "$policy" "$@"',
                         b'grep -v "^(delete) " | /bin/sh "$policy" "$@"\nexit $?')),
    # The dimension no earlier mutant probed, and therefore the one no assertion
    # covered: the dispatcher runs the policy faithfully and then DISCARDS ITS
    # VERDICT. Same total fail-open as a starved stdin, from the other end.
    # NOTE: this is the only mutant whose push SUCCEEDS, so it mutates the scratch
    # remote -- it must never be given a refspec the later assertions depend on.
    ("discards the policy's exit status", "single",
     lambda s: s.replace(b'exec /bin/sh "$policy" "$@"',
                         b'/bin/sh "$policy" "$@"\nexit 0')),
    # Forwards every record, drops none, and ALTERS one field: zeroing the remote
    # OID presents an ordinary update to the policy as a CREATION, which is how a
    # non-fast-forward walks past a rule that only fires on real ancestry. Counting
    # shapes could not see this; exact tuples can. It exists to prove they do.
    ("rewrites the remote OID field", "mixed",
     lambda s: s.replace(
         b'exec /bin/sh "$policy" "$@"',
         b'awk \'{$4="' + ZERO.encode() + b'"; print}\''
         b' | /bin/sh "$policy" "$@"\nexit $?')),
]


def mixed_violations(record, rc, expect_n, expected):
    """A mixed update/create/delete push must arrive INTACT, all shapes present."""
    if record is None:
        return ["the policy was never reached"]
    got = sorted(tuple(r.split()) for r in record.get("REF", []))
    bad = []
    if rc == 0:
        bad.append("the policy's refusal was NOT propagated (push rc=0)")
    # EXACT tuples, not shape counts. Counting shapes let a dispatcher rewrite a
    # field and pass: zeroing every remote OID turns an ordinary update into an
    # apparent CREATION, which is how you walk a non-fast-forward past the policy,
    # and rewriting a remote ref hides which branch is being deleted. "Arrives
    # intact" has to mean intact, or the label is the defect.
    if got != sorted(expected):
        bad.append("records were ALTERED in transit; got %r, expected %r"
                   % (got, sorted(expected)))
    if len(got) != expect_n:
        bad.append("stdin carried %d record(s), expected %d" % (len(got), expect_n))
    if not any(f[0] == "(delete)" and f[1] == ZERO for f in got if len(f) == 4):
        bad.append("no DELETION record reached the policy (zero local OID)")
    if not any(f[3] == ZERO for f in got if len(f) == 4):
        bad.append("no CREATION record reached the policy (zero remote OID)")
    return bad


def under(path, root):
    """Containment. NOT a string prefix test, and not merely a bounded one.

    A bare startswith lets `<root>/.git/..` and a sibling named `main-2` pass.
    Adding a separator fixes those and still leaves the real hole: a LEXICAL
    compare accepts `/w/main/../other/x` as inside `/w/main`, which is exactly
    how a dispatcher would spell another worktree's policy while appearing to
    stay home. It was also case-sensitive, which is wrong on Windows. So:
    canonicalise both sides first, then compare whole path components."""
    try:
        p = os.path.normcase(os.path.realpath(str(path)))
        r = os.path.normcase(os.path.realpath(str(root)))
    except (OSError, ValueError):
        return False
    try:
        return os.path.commonpath([p, r]) == r
    except ValueError:          # different drives / mixed absolute-relative
        return False


def contract_violations(record, rc, worktree, remote_name, remote_url, head):
    """What the dispatcher OWES the policy. Empty list = contract honoured."""
    bad = []
    if record is None:
        return ["the policy was never reached"]
    # The recording policy always exits 1. A dispatcher that runs it and returns 0
    # anyway allows every push the policy denies -- the same total fail-open as a
    # starved stdin, reached by discarding the verdict instead of the input.
    if rc == 0:
        bad.append("the policy's refusal was NOT propagated (push rc=0)")
    if not under(record.get("POLICY", ""), worktree):
        bad.append("policy resolved outside the pushing worktree: %s"
                   % record.get("POLICY"))
    if record.get("ARGC") != "2":
        bad.append("argv not forwarded (ARGC=%s)" % record.get("ARGC"))
    elif record.get("ARG1") != remote_name or record.get("ARG2") != remote_url:
        bad.append("wrong argv: %s / %s" % (record.get("ARG1"), record.get("ARG2")))
    refs = record.get("REF", [])
    if len(refs) != 1:
        bad.append("stdin carried %d ref record(s), expected 1" % len(refs))
    elif len(refs[0].split()) != 4:
        bad.append("malformed ref record: %r" % refs[0])
    elif refs[0].split()[1] != head:
        bad.append("ref record names %s, expected %s" % (refs[0].split()[1], head))
    return bad


def observe(disp_bytes, worktree, hooks_dir, remote_name, refspecs):
    """Install this dispatcher, push once, and read back what the policy received."""
    if isinstance(refspecs, str):
        refspecs = ["HEAD:refs/heads/" + refspecs]
    hook = hooks_dir / "pre-push"
    hook.write_bytes(disp_bytes)
    os.chmod(hook, 0o755)
    rec = worktree / ".prepush-record"
    if rec.exists():
        rec.unlink()
    r = git("push", remote_name, *refspecs, cwd=worktree, check_rc=False)
    if not rec.exists():
        return None, r.returncode
    out = {"REF": []}
    for line in rec.read_text().splitlines():
        k, _, v = line.partition("=")
        out["REF"].append(v) if k == "REF" else out.setdefault(k, v)
    return out, r.returncode


def end_to_end(dispatcher_src, policy_src):
    """Blocks when absent; and when present, honours the contract it owes."""
    tmp = Path(tempfile.mkdtemp(prefix="prepush-install-"))
    try:
        remote, main = tmp / "origin.git", tmp / "main"
        linked = tmp / "linked"
        git("init", "--bare", "-q", str(remote))
        git("init", "-q", "-b", "trunk", str(main))
        git("config", "user.email", "t@t", cwd=main)
        git("config", "user.name", "t", cwd=main)
        git("remote", "add", "origin", str(remote), cwd=main)
        (main / "f.txt").write_text("a\n")
        git("add", "-A", cwd=main)
        git("commit", "-q", "-m", "c1", cwd=main)

        c1 = git("rev-parse", "HEAD", cwd=main).stdout.strip()

        # Seed the remote BEFORE any hook exists, so a later push can genuinely
        # update one ref and delete another. Deleting a ref you never created is
        # not a deletion record, and a deletion record is the shape that matters.
        git("push", "-q", "origin", "HEAD:refs/heads/seed-update",
            "HEAD:refs/heads/seed-delete", cwd=main)

        hooks_dir = main / ".git" / "hooks"
        hook = hooks_dir / "pre-push"
        hook.write_bytes(dispatcher_src)
        os.chmod(hook, 0o755)

        r = git("push", "origin", "HEAD:refs/heads/probe", cwd=main, check_rc=False)
        check("blocks a checkout with no tracked policy",
              r.returncode != 0 and "BLOCKED" in r.stderr, "rc=%d" % r.returncode)

        # Land the recording policy, then take a LINKED worktree from it -- the
        # per-worktree resolution claim is what a linked worktree is for, and the
        # previous version of this test never created one.
        (main / ".githooks").mkdir()
        (main / ".githooks" / "pre-push").write_bytes(RECORDER)
        git("add", "-A", cwd=main)
        git("commit", "-q", "-m", "policy", cwd=main)
        git("worktree", "add", "-q", str(linked), "-b", "other", cwd=main)
        url = git("remote", "get-url", "origin", cwd=main).stdout.strip()

        for label, wt in (("main worktree", main), ("linked worktree", linked)):
            head = git("rev-parse", "HEAD", cwd=wt).stdout.strip()
            rec, rc = observe(dispatcher_src, wt, hooks_dir, "origin",
                              "probe-" + wt.name)
            bad = contract_violations(rec, rc, wt, "origin", url, head)
            check("dispatcher honours its contract from the %s" % label,
                  not bad, "; ".join(bad))
            # This used to assert `rec is not None` under a label claiming the push
            # was aborted -- a label stating a proposition the code did not test.
            check("a policy refusal aborts the push from the %s" % label,
                  rc != 0, "push rc=0 -- the refusal was swallowed")

        # A mixed push: one ref UPDATED, one CREATED, one DELETED. A single-ref
        # oracle cannot see a dispatcher that mishandles a shape it never produces,
        # and the policy's sharpest rules live on exactly those shapes.
        (linked / "g.txt").write_text("b\n")
        # `git add g.txt`, not `-A`: the recording policy drops .prepush-record in
        # the worktree top, and -A committed it into this fixture commit. Harmless
        # today, but state coupling that makes a later assertion mean something
        # other than its label is how fixtures rot.
        git("add", "g.txt", cwd=linked)
        git("commit", "-q", "-m", "c2", cwd=linked)
        h2 = git("rev-parse", "HEAD", cwd=linked).stdout.strip()
        MIXED = ["HEAD:refs/heads/seed-update", "HEAD:refs/heads/created",
                 ":refs/heads/seed-delete"]
        EXPECT = [("(delete)", ZERO, "refs/heads/seed-delete", c1),
                  ("HEAD", h2, "refs/heads/seed-update", c1),
                  ("HEAD", h2, "refs/heads/created", ZERO)]
        rec, rc = observe(dispatcher_src, linked, hooks_dir, "origin", MIXED)
        bad = mixed_violations(rec, rc, 3, EXPECT)
        check("a mixed update/create/delete push arrives intact", not bad,
              "; ".join(bad))

        # The absence case from a LINKED worktree, which was never tested: the
        # only missing-policy probe ran from main before `linked` existed. A
        # dispatcher that exits 0 when it finds no policy in a linked worktree
        # therefore passed -- and that is EXACTLY the production scenario this
        # design exists for, a worktree whose branch predates the policy.
        stash = (linked / ".githooks" / "pre-push").read_bytes()
        (linked / ".githooks" / "pre-push").unlink()
        r = git("push", "origin", "HEAD:refs/heads/absent-probe", cwd=linked,
                check_rc=False)
        check("blocks a LINKED worktree whose policy is missing",
              r.returncode != 0 and "BLOCKED" in r.stderr, "rc=%d" % r.returncode)

        # ...and the proof that the check above can fail. A dispatcher that lets
        # a missing policy pass is the whole defect, so install one while the
        # policy is still gone: it must push CLEANLY, which is what the previous
        # check would then have caught. Without this, that check asserts a
        # property no fixture has ever shown it can lose.
        blind = dispatcher_src.replace(b'fail "this checkout lacks',
                                       b'exit 0 # "this checkout lacks')
        assert blind != dispatcher_src, "the absence-mutant anchor moved"
        _, rc = observe(blind, linked, hooks_dir, "origin", "absent-mutant")
        check("caught: a dispatcher that ignores a missing policy", rc == 0,
              "the mutant was blocked anyway -- the absence check is not what stopped it")

        (linked / ".githooks" / "pre-push").write_bytes(stash)

        # The point of the rewrite: every mutant still REACHES the policy, so the
        # old oracle passed all of them. The contract checks must now catch them.
        for i, (label, mode, mutate) in enumerate(MUTANTS):
            mutated = mutate(dispatcher_src)
            if mutated == dispatcher_src:
                check("mutant %d applied (%s)" % (i, label), False,
                      "the anchor text moved -- this check is no longer wired")
                continue
            if mode == "mixed":
                rec, rc = observe(mutated, linked, hooks_dir, "origin", MIXED)
                bad = mixed_violations(rec, rc, 3, EXPECT)
                check("caught: a dispatcher that %s" % label, bool(bad),
                      "SURVIVED -- the oracle cannot see this defect")
                continue
            # From BOTH worktrees. The wrong-worktree mutant died only because it
            # was judged from `linked`, whose name is not a prefix of the path it
            # wrongly resolved -- an accident of the fixture, not a property of
            # the check. Per-worktree refspecs because the exit-status mutant's
            # push SUCCEEDS, and git emits no record at all for an up-to-date ref.
            for wt in ((linked,) if mode == "linked-only" else (main, linked)):
                head = git("rev-parse", "HEAD", cwd=wt).stdout.strip()
                rec, rc = observe(mutated, wt, hooks_dir, "origin",
                                  "m%d-%s" % (i, wt.name))
                bad = contract_violations(rec, rc, wt, "origin", url, head)
                check("caught from %-6s: a dispatcher that %s" % (wt.name, label),
                      bool(bad), "SURVIVED -- the oracle cannot see this defect")

        hook.write_bytes(dispatcher_src)  # leave the real one in place
        os.chmod(hook, 0o755)

        # And the real policy must at least parse under sh.
        (main / ".githooks" / "pre-push").write_bytes(policy_src)
        r = subprocess.run(["sh", "-n", str(main / ".githooks" / "pre-push")],
                           capture_output=True, text=True)
        check("the real tracked policy is syntactically valid sh",
              r.returncode == 0, r.stderr.strip()[:120])
    finally:
        shutil.rmtree(tmp, onerror=onerr)


def main():
    require_installed = "--require-installed" in sys.argv[1:]
    top = toplevel()
    print("tree:", top)

    print("\n[1] tracked artifacts")
    policy_src = lf_clean(top / ".githooks" / "pre-push", ".githooks/pre-push")
    disp_src = lf_clean(top / "tools" / "git-hooks" / "pre-push-dispatcher",
                        "tools/git-hooks/pre-push-dispatcher")
    if policy_src is None or disp_src is None:
        print("\nRESULT: FAIL -- tracked artifacts missing")
        return 1

    print("\n[2] installed dispatcher")
    hooks_dir, via_hookspath = common_hooks_dir()
    print("  hooks dir:", hooks_dir, "(core.hooksPath)" if via_hookspath else "(common git dir)")
    # On the managed and self-hosted cloud
    # targets, core.hooksPath is set to .githooks BEFORE Claude launches (the
    # setup script / container entrypoint), and .githooks/pre-push IS the
    # tracked policy -- there is no separate dispatcher to install, because
    # the unversioned-hooks-dir problem this dispatcher exists for
    # does not arise when hooksPath points straight at a tracked directory.
    # Comparing hooks_dir/pre-push against the DISPATCHER source is therefore
    # the wrong oracle under core.hooksPath: it reports DRIFT against a file
    # that was never supposed to be the dispatcher. Only fail "unset" -- and
    # only run the dispatcher-match check -- when hooksPath is NOT in play.
    if via_hookspath:
        check("hooks_dir/pre-push matches the tracked POLICY (core.hooksPath target)",
              hooks_dir.joinpath("pre-push").is_file()
              and hooks_dir.joinpath("pre-push").read_bytes() == policy_src,
              "DRIFT -- the hooksPath target is not the reviewed policy")
        installed = None
    else:
        # review-01 F2: no "hooksPath is unset" check here -- this branch IS that
        # fact, so the check could never fail; the DRIFT check above is the detector.
        installed = hooks_dir / "pre-push"
    if installed is None:
        pass  # already checked above under via_hookspath
    elif not installed.is_file():
        # WARN, not FAIL, only because arming has not happened yet. The moment it
        # has, this branch stops being "expected" and becomes the loudest failure
        # in the file: a gate that was armed and then LOST -- deleted, clobbered
        # by a reinstall, or absent in a fresh clone -- is indistinguishable here
        # from one never armed, and would report green while every push sails
        # past. --require-installed is what tells the two apart, and the arming
        # change wires it into the suite so the default flips with the fact.
        check("installed dispatcher is present", not require_installed,
              "REQUIRED but ABSENT -- the gate was armed and is now gone")
        if not require_installed:
            print("  WARN not installed -- the gate is NOT armed in this repository.")
            print("       Expected until the operator arms it; landing precedes arming by design.")
            print("       After arming, run with --require-installed so absence FAILS.")
    else:
        check("installed dispatcher matches the tracked source",
              installed.read_bytes() == disp_src,
              "DRIFT -- the running gate is not the reviewed one")
        # Byte-identical is not enough. Git SKIPS a non-executable hook -- it
        # prints a hint and the push proceeds -- so a `chmod 0644` on the
        # installed copy is a total fail-open that a content check cannot see.
        # POSIX only: Windows has no dependable executable bit, which is why the
        # dispatcher runs the policy via `/bin/sh` rather than executing it.
        if os.name != "nt":
            check("installed dispatcher is executable",
                  os.access(str(installed), os.X_OK),
                  "git ignores a non-executable hook and allows the push")

    print("\n[3] containment has a path boundary")
    # A bare startswith is not containment. `main-2` is not inside `main`, and no
    # push fixture in this file can show that -- the mutant that resolves outside
    # the pushing worktree is benign from main by construction. So assert it here.
    check("a lexical .. escape is NOT contained",
          not under("/w/main/../other/.githooks/pre-push", "/w/main"),
          "realpath must collapse .. before the comparison")
    check("a sibling sharing the root's name is NOT contained",
          not under("/w/main-2/.githooks/pre-push", "/w/main"),
          "prefix match with no separator: main-2 read as inside main")
    check("a genuine child IS contained",
          under("/w/main/.githooks/pre-push", "/w/main"))
    check("the root itself is contained", under("/w/main", "/w/main/"))
    check("an unrelated sibling is not contained",
          not under("/w/other/.githooks/pre-push", "/w/main"))

    print("\n[4] end to end, in a scratch repo")
    end_to_end(disp_src, policy_src)

    print()
    if FAILURES:
        print("RESULT: FAIL (%d) -- %s" % (len(FAILURES), "; ".join(FAILURES)))
        return 1
    print("RESULT: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
