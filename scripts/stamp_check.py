#!/usr/bin/env python
"""Reviewer-stamp gate for a PR head; CI's `gate` job, step (b), runs the default branch's copy of this file against every PR branch, never the branch's own.

    python scripts/stamp_check.py [--base REF] [--head REF]

Defaults: --base is origin's default branch (refs/remotes/origin/HEAD; exit 2 when
unset: `git remote set-head origin --auto`), --head HEAD. Read-only git, no network.

Rule (minimum rewrite): each kind the
subject holds needs an APPROVE of that kind covering HEAD, and no BLOCK may cover it.

- Stamp: an ADDED flat grills/<name>.md with "STAMP:" in its first three lines (one
  leading BOM stripped) must open exactly
      STAMP: APPROVE | BLOCK
      REVIEWER: senior-engineer | adversarial-reviewer
      REVISION: <40 lowercase hex>
  or it FAILs, named. This stops drift, not forgery.
- Kind: prose is .md or .log (any case) and needs adversarial-reviewer; everything
  else is code and needs senior-engineer. Mixed needs both.
- Subject: merge-base(BASE, HEAD)..HEAD minus exempt additions (an added flat
  grills/<name>.md, or an added handoffs/auto/<date>-<session>-session-close-
  <managed|selfhost>.md audit copy) and, when --head is exactly
  lane-<id>, minus .md files below work/<id>-<slug>/ (own-desk exclusion; never a
  `..` path or a CLAUDE.md/AGENTS.md/AGENTS.override.md). Empty is a FAIL ("nothing
  to stamp"), except a desk-only lane, which passes unless a BLOCK covers it.
- Covers: REVISION is a commit and an ancestor of HEAD, and nothing but exempt
  additions changed after it, whatever the kind; for an APPROVE, own-desk prose is
  exempt too. A clean base merge changes nothing:
  a path the lane never changed is the base's, but a lane path the base moved counts.
  Once the base moved, REVISION must be on HEAD's first-parent chain and each later
  merge must have two parents and one merge-base.
- Supersession: an APPROVE whose REVISION is an ancestor of, or equal to, a same-kind
  BLOCK's REVISION does not count, whether or not that BLOCK covers.
- Execution refusal: only a senior-engineer BLOCK may carry the exact fourth
  line `BLOCK-KIND: EXECUTION-REFUSAL`; the field anywhere else in the header block, as
  a column-0 body line, or with any other value fails closed. A covering refusal is
  resolved when no lane commit holds its file at other bytes than HEAD's and a
  surviving covering senior-engineer APPROVE has a REVISION strictly descended from
  the refusal's that already holds the file. Each resolution prints both files.

Exit: 0 pass; 1 a check ran and failed (with RESULT:); 2 could not run, including ANY
git call failing, never read as "does not cover". Self-check: scripts/test_stamp_check.py.
"""
import argparse
import os
import re
import subprocess
import sys

GRILLS_PREFIX = "grills/"
AUDIT_PREFIX = "handoffs/auto/"
# ASCII classes and fullmatch: `\d` takes any Unicode digit and `$` matches before a
# final newline, which `git diff -z` keeps in a path.
AUDIT_NAME_RE = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}-[A-Za-z0-9_-]+-session-close-(managed|selfhost)\.md")
DESK_PREFIX = "work/"
LANE_HEAD_RE = re.compile(r"^lane-(\d+)$")
POLICY_BASENAMES = frozenset({"claude.md", "agents.md", "agents.override.md"})
PROSE_EXTS = frozenset({".md", ".log"})  # .txt stays code (requirements.txt)
STAMP_RE = re.compile(r"^STAMP: (APPROVE|BLOCK)$")
REVIEWER_RE = re.compile(r"^REVIEWER: (senior-engineer|adversarial-reviewer)$")
REVISION_RE = re.compile(r"^REVISION: ([0-9a-f]{40})$")
BLOCK_KIND_BODY_RE = re.compile(r"block-kind\s*:", re.IGNORECASE)
BOM = "﻿"
NO_DEFAULT = ("CONFIG: origin's default branch was not found (refs/remotes/origin/HEAD "
              "unset or dangling); run `git remote set-head origin --auto`, or pass --base")


class GitError(Exception):
    """A git call failed outright; run() turns every one into exit 2."""


def default_base(repo="."):
    """`origin/<name>` from refs/remotes/origin/HEAD, or None: never a guessed name."""
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


def _git(*args):
    """Read-only git in the cwd. core.longpaths stops a long Windows path reading as a
    git failure; a call that never ran raises GitError, never git's own "no" (1)."""
    try:
        done = subprocess.run(["git", "-c", "core.longpaths=true", *args],
                              capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        raise GitError("git %s failed to run: %s" % (" ".join(args), exc))
    return done.returncode, done.stdout, done.stderr


def _answer(code, err, what):
    """git's exit 0 = yes, 1 = no; anything else raises."""
    if code in (0, 1):
        return code == 0
    raise GitError("git %s failed (exit %d): %s" % (what, code, err.strip()))


def resolve_commit(ref):
    """The full sha of the commit ref names, or None."""
    code, out, err = _git("rev-parse", "--verify", "--quiet", ref + "^{commit}")
    return out.strip() if _answer(code, err, "rev-parse --verify %s" % ref) else None


def _is_ancestor(ancestor, descendant):
    code, _out, err = _git("merge-base", "--is-ancestor", ancestor, descendant)
    return _answer(code, err, "merge-base --is-ancestor %s %s" % (ancestor, descendant))


def _merge_base(a, b):
    """The merge-base, or None for unrelated histories."""
    code, out, err = _git("merge-base", a, b)
    return out.strip() if _answer(code, err, "merge-base %s %s" % (a, b)) else None


def name_status(a, b):
    """[(status-letter, path)] for a..b. `-z` never C-quotes a path, so a non-ASCII or
    quote-bearing name reaches the classifier unmangled. Raises GitError."""
    code, out, err = _git("diff", "-z", "--no-renames", "--name-status", a, b)
    if code != 0:
        raise GitError("git diff %s..%s failed: %s" % (a[:12], b[:12], err.strip()))
    parts = out.split("\0")
    if parts and parts[-1] == "":
        parts.pop()
    return [(parts[i][0], parts[i + 1]) for i in range(0, len(parts) - 1, 2)]


def is_prose(path):
    return os.path.splitext(path)[1].lower() in PROSE_EXTS


def is_flat_grills_md(path):
    rest = path[len(GRILLS_PREFIX):]
    return (path.startswith(GRILLS_PREFIX) and rest.endswith(".md")
            and "/" not in rest and rest != ".md")


def is_audit_copy_md(path):
    return (path.startswith(AUDIT_PREFIX)
            and AUDIT_NAME_RE.fullmatch(path[len(AUDIT_PREFIX):]) is not None)


def is_exempt_addition(status, path):
    """An added flat grills .md or audit copy; modified or deleted ones are subjects."""
    return status == "A" and (is_flat_grills_md(path) or is_audit_copy_md(path))


def lane_id_from_head(head):
    """The id when --head is exactly lane-<digits>; a sha or other ref excludes nothing."""
    m = LANE_HEAD_RE.match(head)
    return m.group(1) if m else None


def is_own_desk_prose(status, path, lane_id):
    """A/M/D .md below work/<lane_id>-<slug>/, never `..` or a policy basename."""
    prefix = "%s%s-" % (DESK_PREFIX, lane_id)
    return (status in ("A", "M", "D") and path.startswith(prefix)
            and ".." not in path.split("/")
            and os.path.basename(path).lower() not in POLICY_BASENAMES
            and "/" in path[len(prefix):] and os.path.splitext(path)[1].lower() == ".md")


def strip_bom(text):
    return text[len(BOM):] if text.startswith(BOM) else text


def looks_like_stamp_attempt(content):
    """"STAMP:" anywhere in the first three lines, so a stray prefix fails named."""
    return any("STAMP:" in line for line in strip_bom(content).splitlines()[:3])


def block_kind_lines(lines):
    """Lines using the reserved field: any mention in the header block (to the first
    blank line), or a column-0 field line in the body. A review may discuss it."""
    found, in_header = [], True
    for i, line in enumerate(lines):
        in_header = in_header and bool(line.strip())
        if BLOCK_KIND_BODY_RE.match(line) or (in_header and "BLOCK-KIND" in line.upper()):
            found.append(i)
    return found


def parse_stamp(text):
    """(dict, None) or (None, reason): the strict header and optional refusal line."""
    lines = strip_bom(text).splitlines()
    if len(lines) < 3:
        return None, "fewer than 3 lines"
    fields = []
    for n, regex in enumerate((STAMP_RE, REVIEWER_RE, REVISION_RE)):
        m = regex.match(lines[n])
        if not m:
            return None, "line %d %r" % (n + 1, lines[n])
        fields.append(m.group(1))
    stamp, reviewer, revision = fields
    block_kind = None
    if block_kind_lines(lines):
        if (block_kind_lines(lines) != [3] or lines[3] != "BLOCK-KIND: EXECUTION-REFUSAL"
                or stamp != "BLOCK" or reviewer != "senior-engineer"):
            return None, "invalid, duplicate, misplaced or contradictory BLOCK-KIND"
        block_kind = "EXECUTION-REFUSAL"
    return {"stamp": stamp, "reviewer": reviewer, "revision": revision,
            "block_kind": block_kind}, None


def review_blob(revision, path):
    """The exact path's blob id at revision, or None if absent."""
    code, out, err = _git("ls-tree", "-z", revision, "--", path)
    if code != 0:
        raise GitError("git ls-tree %s %s failed: %s" % (revision, path, err.strip()))
    for entry in filter(None, out.split("\0")):
        metadata, name = entry.split("\t", 1)
        _mode, kind, oid = metadata.split()
        if name == path and kind == "blob":
            return oid
    return None


def unchanged_in_lane(merge_base, head, path, head_blob):
    """Every lane commit, on any side of a merge, lacks path or holds head_blob."""
    code, out, err = _git("rev-list", "%s..%s" % (merge_base, head))
    if code != 0:
        raise GitError("git rev-list %s..%s failed: %s" % (merge_base, head, err.strip()))
    return all(review_blob(commit, path) in (None, head_blob) for commit in out.split())


def base_merge_shape(rev, head):
    """None, or why the base moved past REVISION by a shape this gate refuses: REVISION
    off HEAD's first-parent chain, or a later merge with other than two parents or
    other than one merge-base."""
    code, out, err = _git("rev-list", "--first-parent", "--parents", head, "^" + rev)
    if code != 0:
        raise GitError("git rev-list --first-parent %s ^%s failed: %s" % (head, rev, err.strip()))
    chain = [line.split() for line in out.splitlines() if line.strip()]
    if not chain or chain[-1][1:2] != [rev]:
        return "REVISION is not on HEAD's first-parent chain"
    for commit, *parents in chain:
        if len(parents) > 2:
            return "merge %s after REVISION has %d parents" % (commit[:12], len(parents))
        if len(parents) == 2:
            code, out, err = _git("merge-base", "--all", *parents)
            if code not in (0, 1):
                raise GitError("git merge-base --all failed: %s" % err.strip())
            if len(out.split()) != 1:
                return "merge %s after REVISION has %d merge-bases" % (commit[:12], len(out.split()))
    return None


def covers(candidate, base_commit, head_commit, lane_id=None):
    """(bool, reason): docstring, Covers. Raises GitError, never reads it as "no"."""
    # Own-desk prose is never a subject, so it never voids an APPROVE;
    # a BLOCK it still voids.
    desk_id = lane_id if candidate["stamp"] == "APPROVE" else None
    rev = candidate["revision"]
    if resolve_commit(rev) is None:
        return False, "REVISION does not resolve to a commit"
    if not _is_ancestor(rev, head_commit):
        return False, "REVISION is not an ancestor of HEAD"
    fork_rev = _merge_base(base_commit, rev)
    if fork_rev is None:
        return False, "REVISION shares no history with BASE"
    fork_head = _merge_base(base_commit, head_commit)
    lane = {p for fork, tip in ((fork_rev, rev), (fork_head, head_commit))
            for _s, p in name_status(fork, tip)}
    bad = {p for s, p in name_status(rev, head_commit)
           if not is_exempt_addition(s, p) and p in lane
           and not (desk_id and is_own_desk_prose(s, p, desk_id))}
    if fork_rev != fork_head:
        why = base_merge_shape(rev, head_commit)
        if why:
            return False, why
        bad |= {p for _s, p in name_status(fork_rev, fork_head) if p in lane}
    if bad:
        return False, "changed after REVISION: %r" % sorted(bad)[:3]
    return True, "covers"


def run(base, head):
    """(exit_code, [output lines]); importable for in-process tests."""
    lines, fail = [], False
    try:
        base_commit = resolve_commit(base)
        if base_commit is None:
            return 2, ["CONFIG: --base %r does not resolve to a commit" % base]
        head_commit = resolve_commit(head)
        if head_commit is None:
            return 2, ["CONFIG: --head %r does not resolve to a commit" % head]
        merge_base = _merge_base(base_commit, head_commit)
        if merge_base is None:
            return 2, ["CONFIG: no merge-base between %r and %r" % (base, head)]
        changed = name_status(merge_base, head_commit)
        lines.append("REFS: base=%s head=%s merge-base=%s"
                     % (base_commit[:12], head_commit[:12], merge_base[:12]))

        candidates = []
        for status, path in changed:
            if status != "A" or not is_flat_grills_md(path):
                continue
            code, content, err = _git("show", "%s:%s" % (head_commit, path))
            if code != 0:
                raise GitError("could not read blob %s at head (%s)" % (path, err.strip()))
            if not looks_like_stamp_attempt(content):
                continue
            parsed, reason = parse_stamp(content)
            if parsed is None:
                lines.append("FAIL candidate %s: malformed stamp header (%s)" % (path, reason))
                fail = True
            else:
                candidates.append(dict(parsed, path=path))

        audit = sum(1 for s, p in changed if s == "A" and is_audit_copy_md(p))
        if audit:
            lines.append("EXEMPT: %d added audit copy file(s) under %s" % (audit, AUDIT_PREFIX))
        lane_id = lane_id_from_head(head)
        subject = [(s, p) for s, p in changed if not is_exempt_addition(s, p)]
        kept = [(s, p) for s, p in subject
                if lane_id is None or not is_own_desk_prose(s, p, lane_id)]
        excluded = len(subject) - len(kept)
        subject = kept
        if excluded:
            lines.append("EXCLUDED: %d own-desk prose file(s) under %s%s-*/"
                         % (excluded, DESK_PREFIX, lane_id))
        if not subject and not excluded:
            lines.append('SUBJECT: FAIL ("nothing to stamp; operator\'s call")')
            lines.append("RESULT: FAIL")
            return 1, lines
        required = [r for r, present in (
            ("senior-engineer", any(not is_prose(p) for _s, p in subject)),
            ("adversarial-reviewer", any(is_prose(p) for _s, p in subject))) if present]
        lines.append("SUBJECT: %d file(s), required=%s" % (len(subject), required)
                     if subject else "SUBJECT: desk-only, nothing to stamp")

        approves = {"senior-engineer": [], "adversarial-reviewer": []}
        blocks = []
        for c in candidates:
            ok, why = covers(c, base_commit, head_commit, lane_id)
            lines.append("%s: %s stamp=%s revision=%s covers=%s (%s)"
                         % (c["reviewer"], c["path"], c["stamp"], c["revision"][:12],
                            "yes" if ok else "no", why))
            if ok:
                (blocks if c["stamp"] == "BLOCK" else approves[c["reviewer"]]).append(c)
        # Supersession, covering or not; a BLOCK that never resolved supersedes nothing.
        superseders = [c for c in candidates if c["stamp"] == "BLOCK"
                       and resolve_commit(c["revision"]) is not None]
        for reviewer in approves:
            kept = []
            for a in approves[reviewer]:
                later = next((b for b in superseders if b["reviewer"] == reviewer
                              and _is_ancestor(a["revision"], b["revision"])), None)
                if later is None:
                    kept.append(a)
                else:
                    lines.append("%s: %s superseded by BLOCK %s"
                                 % (reviewer, a["path"], later["path"]))
            approves[reviewer] = kept
        unresolved = []
        for b in blocks:
            resolver = None
            head_blob = review_blob(head_commit, b["path"])
            if (b["block_kind"] == "EXECUTION-REFUSAL" and head_blob is not None
                    and unchanged_in_lane(merge_base, head_commit, b["path"], head_blob)):
                resolver = next((a for a in approves[b["reviewer"]]
                                 if a["revision"] != b["revision"]
                                 and _is_ancestor(b["revision"], a["revision"])
                                 and review_blob(a["revision"], b["path"]) is not None), None)
            if resolver is None:
                unresolved.append(b)
            else:
                lines.append("RESOLVED: %s APPROVE %s resolves EXECUTION-REFUSAL %s"
                             % (b["reviewer"], resolver["path"], b["path"]))
    except GitError as exc:
        lines.append("CONFIG: %s" % exc)
        return 2, lines

    if unresolved:
        lines.append("BLOCK: FAIL - covering BLOCK (%s: %s)"
                     % (unresolved[0]["reviewer"], unresolved[0]["path"]))
        fail = True
    for reviewer in required:
        if approves[reviewer]:
            lines.append("%s: PASS - covering APPROVE (%s)"
                         % (reviewer, approves[reviewer][0]["path"]))
        else:
            lines.append("%s: FAIL - no covering APPROVE" % reviewer)
            fail = True
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
