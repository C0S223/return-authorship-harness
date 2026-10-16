#!/usr/bin/env python
"""Reviewer-stamp gate for a PR head; CI's `gate` job, step (b), runs the default branch's copy of this file against every PR branch, never the branch's own.

    python scripts/stamp_check.py [--base REF] [--head REF]

Defaults: --base is origin's default branch, read from refs/remotes/origin/HEAD
(exit 2 when it cannot be found; `git remote set-head origin --auto` sets it),
--head HEAD. Read-only git; no fetch, no network — refs are read exactly as given.

Header spec and mapping, normative: a stamp candidate is an ADDED file at a flat
grills/<name>.md path whose first three lines (after
stripping one leading U+FEFF byte-order mark) contain "STAMP:" anywhere
 — looser than "line 1 starts STAMP:" on purpose,
so a stray character before STAMP: (a BOM, a leading space, a code fence)
still counts as an attempted stamp and fails named, rather than being
silently ignored as an ordinary grills file. Once a file is a candidate,
its first three lines must parse exactly:

    STAMP: APPROVE | BLOCK
    REVIEWER: senior-engineer | adversarial-reviewer
    REVISION: <40 lowercase hex>

A candidate that fails that parse is a FAIL, named — this stops drift and
sloppiness, not forgery: anyone who can write a grill can write a stamp.

Covers HEAD: a candidate's REVISION must resolve to a real commit, the
merge-base of BASE/HEAD must be its ancestor (or only base merges moved
it; see "Base merges" below), it must itself be an
ancestor of HEAD, and REVISION..HEAD must add nothing but flat
grills/<name>.md files — the same shape as a stamp
candidate (a nested path or non-.md file under
grills/ does NOT count, so it cannot ride past this check unreviewed). A
post-review commit touching a subject file, or adding anything under
grills/ that isn't a flat .md, invalidates the stamp; another reviewer's
flat .md file landing after it does not.

Per-kind voiding: for an APPROVE, only a post-review change of the reviewer's
own kind voids it -- a prose (.md) change voids an adversarial-reviewer
APPROVE, a code change (anything else, same classifier as the subject)
voids a senior-engineer APPROVE. Each required kind still needs an
APPROVE whose REVISION..HEAD leaves every file of its kind untouched, so
every subject file is reviewed at its HEAD content by its own kind. A
BLOCK is voided by any change, as before: a senior-engineer BLOCK on a
README clause must clear when the README is repaired, not wait on code.
So that voiding a BLOCK never revives an older APPROVE, an APPROVE whose
REVISION is an ancestor of, or equal to, a same-kind BLOCK's REVISION is
superseded and does not count, covering or not (an
own-desk REPORT commit voided an SE BLOCK on unchanged code and the
older SE APPROVE passed the gate). A BLOCK whose REVISION does not
resolve supersedes nothing; it never covered anything either.

Base merges (clean merges keep stamps):
merging the base into a lane after REVISION
moves the merge-base past REVISION, which used to void every stamp as a
stale base. Now, when that is the only reason, covers() walks HEAD's
first-parent chain back to REVISION. Each merge on it must have exactly
two parents, the second already an ancestor of the merge-base (a base
merge); the lane's own commits between merges are diffed as before, and
a base merge contributes, as modifications of their kind, every path it
did not take cleanly from one side (merge_resolution_paths(): a
hand-resolution, `checkout --ours` included, or a file the merge alone
added or removed; and, the hub's fail-closed default beyond the ruling's
"hand-resolved", a side kept wholesale by `-s ours` or a both-sides
auto-merge of different changes; an identical change on both sides is
taken unchanged and does not count). A merge that only takes each side's own changes therefore
voids nothing, and one that resolves voids the APPROVE of each kind it
touched. Fail closed: a REVISION that is itself on the base, off the
first-parent chain, or followed by any other merge or by a base merge
with more than one merge-base, or a stale base with no base merge after
REVISION at all, is still "stale base". A BLOCK is
not voided by a clean base merge, because nothing of the lane changed.

Subject files = the changed set (merge-base(BASE,HEAD)..HEAD) minus any
file ADDED at a flat grills/<name>.md path — same test as
a stamp candidate, so grills/x.py and grills/sub/x.md are ordinary
subjects, not exclusions. Classification is fail-closed: prose is an extension of .md only (case-insensitive) and
nothing else — .txt included — every other extension, unknown ones and no
extension at all, is code. Code requires a covering senior-engineer
APPROVE; prose requires a covering adversarial-reviewer APPROVE. Either
kind's covering BLOCK fails the gate outright, whether or not that
reviewer's kind was required by the subject set — a blocking finding is never silently discarded. An empty subject
set is a FAIL — "nothing to stamp" is the operator's call, not a silent
pass — except when own-desk exclusion (below) emptied it: a desk-only lane
requires no reviewer and passes unless a covering BLOCK exists.

Paths are read via `git diff -z`, never the default quoting form, so a
non-ASCII, quote- or backslash-bearing filename reaches the classifier and
the grills-candidate test unmangled.

Exit: 0 pass; 1 a check ran and failed; 2 could not run — a bad ref, no
merge-base, or ANY git call failing, including the ones inside the
covering test (closed for real by round 4
A git failure — a nonzero/non-one exit from git, or the
subprocess call itself raising (timeout, OSError) — is never reported as
"does not cover" or "could not read", only as exit 2. This is the same
fail-closed shape as scripts/prepush_check.py --strict (paraphrased, not
quoted, from its docstring: exit 1 means a check ran and failed, exit 2
means no check could run).

Self-check: scripts/test_stamp_check.py (discovered by run_tests.py's
scripts/test_*.py glob).

Own-desk exclusion: when --head matches ^lane-(\\d+)$ exactly (a sha, HEAD, or any
other ref excludes nothing -- fail closed), status A/M/D subject paths
under that lane's own work/<id>-*/ are dropped from the
subject, whoever wrote them, except two carve-outs: a path with
a `..` segment is never dropped (git does not emit one; this is a guard
at the gate's trust boundary, not a real case), and a path whose basename
(case-insensitive) is `claude.md`, `agents.md` or `agents.override.md` is
never dropped, because those are policy "at any depth"
(`docs/enforcement/CLAUDE.md:31`) and must keep their reviewer regardless
of which desk dir they sit under. Everything else that is `.md`
(case-insensitive) at least one directory level below the desk-item
prefix is dropped -- so a builder's `DID.md`, an operator ruling, or a
normative spec under the lane's own desk dir drops too, not only the
hub's own `WORK-ORDER.md`/`REPORT.md`; that is the ruling's own scope,
named here rather than assumed. Code under the same desk dir (a .py
fixture, say) still requires senior-engineer. A post-review edit to an
excluded file still voids a stamp it would void as a subject (per kind,
above), because covers() reads REVISION..HEAD directly, never the
subject list.
"""
import argparse
import os
import re
import subprocess
import sys

GRILLS_PREFIX = "grills/"


def default_base(repo="."):
    """origin's default branch as `origin/<name>`, from refs/remotes/origin/HEAD.
    None when that ref is unset or names no commit: the caller fails closed,
    never guesses a branch name."""
    try:
        r = subprocess.run(["git", "-C", repo, "symbolic-ref", "-q", "refs/remotes/origin/HEAD"],
                           capture_output=True, text=True, timeout=10)
        ref = r.stdout.strip()
        if r.returncode != 0 or not ref.startswith("refs/remotes/origin/"):
            return None
        v = subprocess.run(["git", "-C", repo, "rev-parse", "-q", "--verify", ref + "^{commit}"],
                           capture_output=True, text=True, timeout=10)
        return "origin/" + ref[len("refs/remotes/origin/"):] if v.returncode == 0 else None
    except Exception:
        return None


NO_DEFAULT = ("CONFIG: origin's default branch was not found (refs/remotes/origin/HEAD "
              "unset or dangling); run `git remote set-head origin --auto`, or pass --base")
DESK_PREFIX = "work/"
LANE_HEAD_RE = re.compile(r"^lane-(\d+)$")
# docs/enforcement/CLAUDE.md:31: these basenames are policy "at any depth",
# so is_own_desk_prose must never drop them regardless of which desk dir
# they sit under.
POLICY_BASENAMES = frozenset({"claude.md", "agents.md", "agents.override.md"})
# round 4 spec change 4: .txt dropped. A hub default, disclosed: the AR
# delta showed .txt-as-prose lets an AR-only APPROVE pass
# a project's requirements.txt or allowlist.txt.
PROSE_EXTS = frozenset({".md"})

STAMP_RE = re.compile(r"^STAMP: (APPROVE|BLOCK)$")
REVIEWER_RE = re.compile(r"^REVIEWER: (senior-engineer|adversarial-reviewer)$")
REVISION_RE = re.compile(r"^REVISION: ([0-9a-f]{40})$")

BOM = "﻿"


class GitError(Exception):
    """A git call failed outright (bad object, timeout, I/O error) instead
    of giving a real yes/no answer. Every raise here becomes exit 2 in
    run() — a git failure must never read as "does not cover" or "could
    not read" (this also closes the gap where _git itself swallowed a
    subprocess-level failure as git's own "no" exit code)."""


def _git(*args):
    """Read-only git against the process cwd — the repo whose HEAD is being
    checked. Never pinned to a fixed root: this runs from whatever cwd it
    is invoked in, and the test suite exploits the same thing to point a
    real copy of this script at a throwaway fixture repo without ever
    touching this repo's own history. `-c core.longpaths=true` on every
    call: without it, `git show <sha>:<path>`
    (used to read a candidate's blob) also stats the argument as a
    working-tree path, and on Windows a resolved length >= 260 with
    longpaths unset makes git exit 128 ("Filename too long") on an
    otherwise-valid lane -- this call cannot tell that apart from a real
    git failure, so it must not happen for path length alone.

    A subprocess-level failure (timeout, OSError -- never got a real git
    exit code at all) raises GitError directly here, instead of being
    coerced into returncode 1. Returncode 1 is git's own "no" answer for
    several of this module's calls (rev-parse --verify, merge-base
    --is-ancestor); collapsing a call that never ran into that same code
    made a covering BLOCK silently vanish as "does not cover". Every caller of
    _git must be prepared for GitError to propagate out of this call."""
    try:
        done = subprocess.run(
            ["git", "-c", "core.longpaths=true", *args],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise GitError("git %s failed to run: %s" % (" ".join(args), exc))
    return done.returncode, done.stdout, done.stderr


def resolve_commit(ref):
    """The full sha ref resolves to, or None — never an abbreviation, never
    a non-commit object (a tag or blob that merely shares 40 hex chars).
    git's own exit codes for `rev-parse --verify --quiet REF^{commit}`
    are a real answer only at 0 (resolves) or 1 (does not resolve, a bad
    or unknown ref -- verified: a well-formed but nonexistent 40-hex
    object also exits 1, not 128); anything else (a call that could not
    even ask the question) raises GitError rather than reading as "no"."""
    code, out, err = _git("rev-parse", "--verify", "--quiet", ref + "^{commit}")
    if code == 0:
        return out.strip()
    if code == 1:
        return None
    raise GitError("git rev-parse --verify --quiet %s^{commit} failed "
                    "(exit %d): %s" % (ref, code, err.strip()))


def _is_ancestor(ancestor, descendant):
    """True/False per git's own exit-code contract for `merge-base
    --is-ancestor`: 0 = yes, 1 = no (a real answer, including two commits
    with no shared history at all — probed), anything else = the call
    itself failed (bad object, timeout). Only the last case raises."""
    code, _out, err = _git("merge-base", "--is-ancestor", ancestor, descendant)
    if code == 0:
        return True
    if code == 1:
        return False
    raise GitError("git merge-base --is-ancestor %s %s failed (exit %d): %s"
                    % (ancestor, descendant, code, err.strip()))


def name_status(a, b):
    """[(status-letter, path), ...] for a..b, or (None, stderr) on git
    error. `-z` NUL-terminates every field and never C-quotes a path, so a
    non-ASCII, quoted, or otherwise special filename reaches callers as the
    real path — probed against a naïve.py
    fixture: plain --name-status renders it '"na\\303\\257ve.py"' (quoted,
    octal-escaped, extension '.py"'); -z renders it 'na\xefve.py' (correct,
    extension '.py')."""
    code, out, err = _git("diff", "-z", "--no-renames", "--name-status", a, b)
    if code != 0:
        return None, err
    parts = out.split("\0")
    if parts and parts[-1] == "":
        parts.pop()
    rows = []
    for i in range(0, len(parts) - 1, 2):
        rows.append((parts[i][0], parts[i + 1]))
    return rows, None


def is_prose(path):
    """The subject classifier's own test: .md (case-insensitive) is prose,
    everything else is code (fail closed)."""
    return os.path.splitext(path)[1].lower() in PROSE_EXTS


def is_flat_grills_md(path):
    """The one grills/-membership test, used everywhere a file must count as
    a reviewed-artifact addition rather than an ordinary subject: status A,
    grills/<name>.md, no further slash. A prefix-only test here let grills/x.py or grills/sub/x.md ride past
    both the subject exclusion and the post-review-commit check unreviewed;
    there is deliberately no looser sibling of this function."""
    if not path.startswith(GRILLS_PREFIX):
        return False
    rest = path[len(GRILLS_PREFIX):]
    return rest.endswith(".md") and "/" not in rest and rest != ".md"


def lane_id_from_head(head):
    """The lane id if --head is exactly `lane-<digits>`, else None -- fail
    closed: a sha, HEAD, or any other ref shape excludes
    nothing. Matched against the raw --head string as given, never a
    resolved commit -- a lane's own desk dir is named after the item, not
    after whatever a sha happens to be."""
    m = LANE_HEAD_RE.match(head)
    return m.group(1) if m else None


def is_own_desk_prose(status, path, lane_id):
    """True iff this subject row is the lane's own desk .md, dropped from
    the subject regardless of who wrote it, except two carve-outs added in
    round 2 -- spec 2 plus S2-1/S2-2:
    - status A/M/D, path starts with work/<lane_id>-,
      at least one further "/" after that prefix (so the desk item's own
      dir, not a same-prefixed sibling id, and never a bare file directly
      under work/), and splitext(path)[1].lower() == ".md".
    - S2-2: any "/"-separated segment of `path` equal to ".." returns
      False. git does not emit such a path; this is a guard at the
      gate's trust boundary, not a reachable case under real git.
    - S2-1: `os.path.basename(path).lower()` in POLICY_BASENAMES (i.e.
      claude.md, agents.md, agents.override.md) returns False, because
      those basenames are policy "at any depth"
      (docs/enforcement/CLAUDE.md:31) and must keep their reviewer no
      matter which desk dir they land under.
    Code under the same desk dir (a .py fixture, say) is deliberately not
    excluded -- only .md is (a disclosed narrowing)."""
    if status not in ("A", "M", "D"):
        return False
    prefix = "%s%s-" % (DESK_PREFIX, lane_id)
    if not path.startswith(prefix):
        return False
    if ".." in path.split("/"):
        return False
    if os.path.basename(path).lower() in POLICY_BASENAMES:
        return False
    rest = path[len(prefix):]
    return "/" in rest and os.path.splitext(path)[1].lower() == ".md"


def strip_bom(text):
    """One leading U+FEFF, if present — never more, never mid-file."""
    if text.startswith(BOM):
        return text[len(BOM):]
    return text


def looks_like_stamp_attempt(content):
    """True iff "STAMP:" occurs anywhere in the first three lines (after a
    leading BOM is stripped) — round 3 spec change 5 candidacy test.
    Looser than a strict line-1 match on purpose: a stray character before
    STAMP: (BOM, leading space, code fence) must still surface as a named
    FAIL, not vanish as an ordinary, unrelated grills file."""
    lines = strip_bom(content).splitlines()[:3]
    return any("STAMP:" in line for line in lines)


def parse_stamp(text):
    """First three lines, strict, after stripping one leading BOM. Returns
    (dict, None) or (None, reason)."""
    lines = strip_bom(text).splitlines()
    if len(lines) < 3:
        return None, "fewer than 3 lines"
    m1 = STAMP_RE.match(lines[0])
    if not m1:
        return None, "line 1 %r" % lines[0]
    m2 = REVIEWER_RE.match(lines[1])
    if not m2:
        return None, "line 2 %r" % lines[1]
    m3 = REVISION_RE.match(lines[2])
    if not m3:
        return None, "line 3 %r" % lines[2]
    return ({"stamp": m1.group(1), "reviewer": m2.group(1),
              "revision": m3.group(1)}, None)


STALE_BASE = "merge-base is not an ancestor of REVISION (stale base)"


def _paths(a, b):
    """The set of paths that differ between a and b. Raises GitError."""
    rows, err = name_status(a, b)
    if rows is None:
        raise GitError("git diff %s..%s failed: %s" % (a[:12], b[:12], err.strip()))
    return set(p for _s, p in rows)


def merge_resolution_paths(merge, lane, base):
    """(paths, None) or (None, reason): the paths a two-parent MERGE did not
    take cleanly from one side. A path counts unless the merge kept the
    lane's version of a path only the lane changed, or the base's version
    of a path only the base changed (both since their merge-base). So a
    hand-resolution, a both-sides auto-merge of different changes (an
    identical change on both sides does not count), a side kept by `-s ours` or
    `checkout --ours`, and a file the merge alone added or removed all
    count (fail closed). A merge with more than one merge-base is refused.
    Raises GitError on any git failure."""
    code, out, err = _git("merge-base", "--all", lane, base)
    if code != 0:
        raise GitError("git merge-base --all %s %s failed (exit %d): %s"
                        % (lane[:12], base[:12], code, err.strip()))
    bases = out.split()
    if len(bases) != 1:
        return None, (STALE_BASE + "; merge %s has %d merge-bases"
                      % (merge[:12], len(bases)))
    lane_changed = _paths(bases[0], lane)
    base_changed = _paths(bases[0], base)
    not_lane = _paths(lane, merge)
    not_base = _paths(base, merge)
    return sorted(p for p in not_lane | not_base
                  if not (p not in not_lane and p not in base_changed)
                  and not (p not in not_base and p not in lane_changed)), None


def rows_across_base_merges(rev, base_commit, head_commit):
    """(rows, None) or (None, reason) for a REVISION the merge-base has
    moved past: the lane's own changes since REVISION, with each base merge
    after it contributing only merge_resolution_paths() (docstring, "Base
    merges"). Only called once REVISION is known to be an ancestor of
    HEAD. Raises GitError on any git failure."""
    if _is_ancestor(rev, base_commit):
        return None, STALE_BASE
    code, out, err = _git("rev-list", "--first-parent", "--parents",
                          head_commit, "^" + rev)
    if code != 0:
        raise GitError("git rev-list --first-parent %s ^%s failed (exit %d): %s"
                        % (head_commit, rev, code, err.strip()))
    chain = [line.split() for line in out.splitlines() if line.strip()]
    chain.reverse()
    if not chain or len(chain[0]) < 2 or chain[0][1] != rev:
        return None, STALE_BASE + "; REVISION is not on HEAD's first-parent chain"
    rows = []
    start = rev
    merges = 0
    for entry in chain:
        commit, parents = entry[0], entry[1:]
        if len(parents) < 2:
            continue
        if len(parents) > 2 or not _is_ancestor(parents[1], base_commit):
            return None, (STALE_BASE + "; merge %s after REVISION is not a "
                          "base merge" % commit[:12])
        seg, err = name_status(start, parents[0])
        if seg is None:
            raise GitError("git diff %s..%s failed: %s"
                            % (start[:12], parents[0][:12], err.strip()))
        rows.extend(seg)
        resolved, why = merge_resolution_paths(commit, parents[0], parents[1])
        if resolved is None:
            return None, why
        rows.extend(("M", p) for p in resolved)
        start = commit
        merges += 1
    if not merges:
        return None, STALE_BASE
    seg, err = name_status(start, head_commit)
    if seg is None:
        raise GitError("git diff %s..%s failed: %s"
                        % (start[:12], head_commit[:12], err.strip()))
    rows.extend(seg)
    return rows, None


def covers(candidate, base_commit, head_commit):
    """(bool, reason) — the four-part "covers HEAD" test. Raises
    GitError (never returns) if a git call inside here fails outright
    rather than giving a real answer."""
    rev = candidate["revision"]
    if resolve_commit(rev) is None:
        return False, "REVISION does not resolve to a commit"
    if _is_ancestor(base_commit, rev):
        if not _is_ancestor(rev, head_commit):
            return False, "REVISION is not an ancestor of HEAD"
        rows, err = name_status(rev, head_commit)
        if rows is None:
            raise GitError("git diff REVISION..HEAD failed: %s" % err.strip())
    else:
        if not _is_ancestor(rev, head_commit):
            return False, STALE_BASE
        rows, why = rows_across_base_merges(rev, base_commit, head_commit)
        if rows is None:
            return False, why
    bad = [(s, p) for s, p in rows if s != "A" or not is_flat_grills_md(p)]
    if candidate["stamp"] == "APPROVE":
        # Per-kind voiding: an APPROVE ignores changes of the other kind.
        own_kind_is_prose = candidate["reviewer"] == "adversarial-reviewer"
        bad = [(s, p) for s, p in bad if is_prose(p) == own_kind_is_prose]
    if bad:
        return False, ("REVISION..HEAD adds or changes non-grills-addition(s): %r"
                        % bad[:3])
    return True, "covers"


def run(base, head):
    """The whole checker. Returns (exit_code, [output lines]); importable
    for in-process tests and driven as __main__ for real use.

    Every git-touching step below -- ref resolution, the merge-base call,
    the top-level diff, and the per-candidate covers() checks -- sits
    inside one try/except GitError, so a git call that fails outright
    (a bad-ref-shaped code from rev-parse, or the subprocess itself
    raising) always reaches exit 2 through the same path, never a
    business-logic "does not cover"/"could not read" line."""
    lines = []

    try:
        base_commit = resolve_commit(base)
        if base_commit is None:
            lines.append("CONFIG: --base %r does not resolve to a commit" % base)
            return 2, lines
        head_commit = resolve_commit(head)
        if head_commit is None:
            lines.append("CONFIG: --head %r does not resolve to a commit" % head)
            return 2, lines

        code, mb_out, mb_err = _git("merge-base", base_commit, head_commit)
        if code != 0 or not mb_out.strip():
            lines.append("CONFIG: no merge-base between %r and %r: %s"
                          % (base, head, mb_err.strip()))
            return 2, lines
        merge_base = mb_out.strip()

        changed, err = name_status(merge_base, head_commit)
        if changed is None:
            lines.append("CONFIG: git diff %s..%s failed: %s"
                          % (merge_base[:12], head_commit[:12], err.strip()))
            return 2, lines

        lines.append("REFS: base=%s head=%s merge-base=%s"
                      % (base_commit[:12], head_commit[:12], merge_base[:12]))

        fail = False
        candidates = []
        for status, path in changed:
            if status != "A" or not is_flat_grills_md(path):
                continue
            code, content, err = _git("show", "%s:%s" % (head_commit, path))
            if code != 0:
                raise GitError("could not read blob %s at head (%s)"
                                % (path, err.strip()))
            if not looks_like_stamp_attempt(content):
                continue  # not a candidate; other grills files are ignored
            parsed, reason = parse_stamp(content)
            if parsed is None:
                lines.append("FAIL candidate %s: malformed stamp header (%s)"
                              % (path, reason))
                fail = True
                continue
            candidates.append(dict(parsed, path=path))

        added_grills = {path for status, path in changed
                         if status == "A" and is_flat_grills_md(path)}
        subject = [(status, path) for status, path in changed
                   if path not in added_grills]

        lane_id = lane_id_from_head(head)
        excluded_count = 0
        if lane_id is not None:
            kept = []
            for status, path in subject:
                if is_own_desk_prose(status, path, lane_id):
                    excluded_count += 1
                else:
                    kept.append((status, path))
            subject = kept
        if excluded_count:
            lines.append("EXCLUDED: %d own-desk prose file(s) under %s%s-*/"
                          % (excluded_count, DESK_PREFIX, lane_id))

        if not subject and not excluded_count:
            lines.append('SUBJECT: FAIL ("nothing to stamp; operator\'s call")')
            lines.append("RESULT: FAIL")    # every verdict (rc 0/1) carries RESULT; CONFIG exits (rc 2) do not
            return 1, lines

        prose_present = any(is_prose(p) for _s, p in subject)
        code_present = any(not is_prose(p) for _s, p in subject)
        required = []
        if code_present:
            required.append("senior-engineer")
        if prose_present:
            required.append("adversarial-reviewer")
        if subject:
            lines.append("SUBJECT: %d file(s), code=%s prose=%s required=%s"
                          % (len(subject), code_present, prose_present, required))
        else:
            lines.append("SUBJECT: desk-only, nothing to stamp")

        # Every candidate is evaluated, not only the required reviewer's --
        # a covering BLOCK fails the gate from any reviewer, required or
        # not.
        by_reviewer = {"senior-engineer": {"approves": [], "blocks": []},
                       "adversarial-reviewer": {"approves": [], "blocks": []}}
        covering_blocks = []
        for c in candidates:
            ok, why = covers(c, merge_base, head_commit)
            lines.append("%s: %s stamp=%s revision=%s covers=%s (%s)"
                          % (c["reviewer"], c["path"], c["stamp"],
                             c["revision"][:12], "yes" if ok else "no", why))
            if not ok:
                continue
            bucket = by_reviewer[c["reviewer"]]
            if c["stamp"] == "BLOCK":
                bucket["blocks"].append(c)
                covering_blocks.append(c)
            else:
                bucket["approves"].append(c)
        # A same-kind BLOCK at or after an APPROVE's REVISION supersedes it,
        # whether or not that BLOCK still covers HEAD (docstring).
        for reviewer, bucket in by_reviewer.items():
            blocks = [c for c in candidates
                      if c["reviewer"] == reviewer and c["stamp"] == "BLOCK"
                      and resolve_commit(c["revision"]) is not None]
            kept = []
            for a in bucket["approves"]:
                later = next((b for b in blocks
                              if _is_ancestor(a["revision"], b["revision"])), None)
                if later is None:
                    kept.append(a)
                else:
                    lines.append("%s: %s superseded by BLOCK %s"
                                  % (reviewer, a["path"], later["path"]))
            bucket["approves"] = kept
    except GitError as exc:
        lines.append("CONFIG: %s" % exc)
        return 2, lines

    if covering_blocks:
        lines.append("BLOCK: FAIL - covering BLOCK (%s: %s)"
                      % (covering_blocks[0]["reviewer"], covering_blocks[0]["path"]))
        fail = True

    for reviewer in required:
        approves = by_reviewer[reviewer]["approves"]
        if not approves:
            lines.append("%s: FAIL - no covering APPROVE" % reviewer)
            fail = True
        else:
            lines.append("%s: PASS - covering APPROVE (%s)"
                          % (reviewer, approves[0]["path"]))

    lines.append("RESULT: %s" % ("FAIL" if fail else "PASS"))
    return (1 if fail else 0), lines


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--base", default=None, help="default: origin's default branch")
    p.add_argument("--head", default="HEAD")
    args = p.parse_args(sys.argv[1:] if argv is None else argv)
    base = args.base or default_base()
    if base is None:
        print(NO_DEFAULT)
        print("RESULT: FAIL")
        return 2
    code, lines = run(base, args.head)
    for line in lines:
        print(line)
    return code


if __name__ == "__main__":
    sys.exit(main())
