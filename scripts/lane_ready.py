#!/usr/bin/env python3
"""Mark a lane PR ready and arm auto-merge, only when it may merge on its own.

    python scripts/lane_ready.py <owner/repo> <pr-number> [--timeout SECONDS]

The one way an agent arms auto-merge (root CLAUDE.md §3).
Contract and policy files never auto-merge: the operator merges every one. It refuses,
arming nothing, unless all of these hold:

  1. The PR is open, its head is this repository's own `lane-<digits>` branch, and its
     base is the repository's default branch.
  2. No changed path (renames at both names) is a contract or policy file by name:
     CLAUDE.md, AGENTS.md or AGENTS.override.md at any depth, or anything under
     .claude/, .codex/, .agents/, .github/, .githooks/, or .mcp.json. This is the fast
     refusal; the repository's own `operator-merge` check, run from its default branch,
     is the authority, and step 4 reads it.
  3. Senior review cleared it: a flat grills/<name>.md the PR adds opens with
     `STAMP: APPROVE`, `REVIEWER: senior-engineer`, `REVISION: <40 hex>`; REVISION is
     an ancestor of the head; REVISION..head adds nothing but flat grills/<name>.md
     files. A substantive BLOCK still covering head cannot be cleared by a later
     APPROVE; a repaired BLOCK needs a strictly later APPROVE. Only an explicit
     fourth-line BLOCK-KIND: EXECUTION-REFUSAL can be resolved while still covering,
     by a same-kind covering APPROVE at a strict descendant revision containing a
     refusal file no lane commit holds at other bytes. Approvals superseded by any same-kind BLOCK
     cannot resolve refusals. Malformed metadata refuses. Fail-closed where
     scripts/stamp_check.py is lenient (a base merge after an APPROVE's REVISION or a
     BLOCK's refuses here). The `gate` check still runs stamp_check on every push.
  4. After the ready mark, a `gate` run and an `operator-merge` run started after it
     both concluded success, read from that run only, never a draft's, and the head
     did not move, and step 1 still holds, while waiting. On a PR already ready, "the ready mark" is its last
     ready_for_review event; a PR that never was a draft counts every run.
  5. Every other check-run on the head (a review Action, a Codex check) has completed
     with success, neutral or skipped.

Then it arms auto-merge, so GitHub merges once the ruleset's required checks pass.
Transport: in a cloud session the CCR routes (POST .../ccr/ready_for_review, PUT
.../ccr/auto_merge); where a CCR route answers 404 (GitHub itself, a host session),
`gh pr ready` and `gh pr merge --auto --merge --match-head-commit <head>`.

After the arm call it reads the PR back; if the head is no longer the one checked it
disables auto-merge (DELETE .../ccr/auto_merge, else `gh pr merge --disable-auto`) and
refuses naming the new head. Once the arm call was attempted, no exit says "not armed":
an error then prints "MAY BE ARMED" and the hand command `gh pr merge <n> -R <repo>
--disable-auto` (a failed disarm adds that it may be armed on an unchecked head).

Exit: 0 armed; 1 refused (a verdict, each reason printed: the PR waits for the
operator's merge); 2 a surprise to stop and report (usage, gh or the API failed, the
run did not conclude in time, the ready run's `gate` did not conclude success, a run
was cancelled, `operator-merge` failed without the checker's exit-1 verdict, the arm
did not take, or the head moved after the arm and the disarm failed). Exit 1 also covers
the head-moved-then-disarmed case.
Self-check: scripts/test_lane_ready.py.
"""

import argparse
import base64
import json
import re
import subprocess
import sys
import time
from urllib.parse import quote

from stamp_check import is_exempt_addition, looks_like_stamp_attempt, parse_stamp

LANE = re.compile(r"lane-[0-9]+")
FLAT_GRILL = re.compile(r"grills/[^/]+\.md")
CONTRACT_NAMES = {"claude.md", "agents.md", "agents.override.md"}
CONTRACT_DIRS = (".claude/", ".codex/", ".agents/", ".github/", ".githooks/")
CHECKS = ("gate", "operator-merge")
GREEN = ("success", "neutral", "skipped")


class ApiError(Exception):
    def __init__(self, status, detail):
        super().__init__("HTTP %s: %s" % (status, detail))
        self.status = status


class Refused(Exception):
    """A verdict: this PR may not auto-merge."""


class Disarmed(Refused):
    """A verdict reached after the arm call; auto-merge was armed, then disabled."""


class MayBeArmed(Exception):
    """An error once the arm call was attempted: auto-merge may be set on this PR."""

    def __init__(self, cause, hand):
        super().__init__(cause)
        self.hand = hand


def gh_api(method, endpoint, fields=None):
    argv = ["gh", "api", "--method", method, endpoint]
    for key, value in (fields or {}).items():
        argv += ["-f", "%s=%s" % (key, value)]
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ApiError(0, str(exc)) from exc
    if done.returncode != 0:
        found = re.search(r"HTTP (\d{3})", done.stderr)
        raise ApiError(int(found.group(1)) if found else 0, done.stderr.strip())
    return json.loads(done.stdout) if done.stdout.strip() else {}


def gh_run(argv):
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, "", str(exc)
    return done.returncode, done.stdout, done.stderr


def is_contract(path):
    low = path.lower()
    return (low.rsplit("/", 1)[-1] in CONTRACT_NAMES or low == ".mcp.json"
            or low.startswith(CONTRACT_DIRS))


def read_review_bytes(api, root, path, sha):
    """Exact file bytes; an absent historical file cannot resolve a refusal."""
    try:
        blob = api("GET", "%s/contents/%s?ref=%s" % (root, quote(path, safe="/"), sha))
    except ApiError as exc:
        if exc.status == 404:
            return None
        raise
    try:
        if blob.get("encoding") != "base64":
            raise ValueError("expected base64 file content")
        return base64.b64decode("".join(blob["content"].split()), validate=True)
    except (KeyError, TypeError, ValueError):
        raise Refused("cannot decode review file %s at %s" % (path, sha[:8]))


def read_stamp(api, root, path, sha):
    """Use the gate's exact grammar; malformed candidates refuse, not disappear."""
    content = read_review_bytes(api, root, path, sha)
    if content is None:
        raise Refused("cannot read added review file %s at head" % path)
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise Refused("review file %s is not UTF-8" % path)
    if not looks_like_stamp_attempt(text):
        return None
    parsed, reason = parse_stamp(text)
    if parsed is None:
        raise Refused("%s: malformed stamp header (%s)" % (path, reason))
    return dict(parsed, path=path, content=content)


def compare(api, root, base, head):
    try:
        return api("GET", "%s/compare/%s...%s?per_page=100" % (root, base, head))
    except ApiError as exc:
        if exc.status == 404:  # unrelated or unknown revision: covers nothing
            return {"status": "unknown", "files": []}
        raise


def covers(api, root, revision, head):
    """REVISION is an ancestor of head and REVISION..head only adds flat grills files."""
    diff = compare(api, root, revision, head)
    files = diff.get("files", [])
    if diff.get("status") not in ("ahead", "identical") or len(files) >= 300:
        return False
    return all(FLAT_GRILL.fullmatch(f["filename"]) and f["status"] == "added" for f in files)


def strictly_older(api, root, older, newer):
    return compare(api, root, older, newer).get("status") == "ahead"


def unchanged_in_lane(api, root, base, head, path, content):
    """Every lane commit lacks the review or holds it at content, as the gate's walk.

    Commits, not path history: GitHub's path query simplifies merges, so it hides
    a copy that one parent held. A list it cannot return whole refuses.
    """
    diff = compare(api, root, base, head)
    commits = diff.get("commits", [])
    if (diff.get("status") not in ("ahead", "diverged")
            or diff.get("total_commits", len(commits)) > len(commits)):
        raise Refused("cannot read every lane commit for %s" % path)
    return all(read_review_bytes(api, root, path, c["sha"]) in (None, content) for c in commits)


def pr_files(api, root, number):
    files, page = [], 1
    while True:
        batch = api("GET", "%s/pulls/%d/files?per_page=100&page=%d" % (root, number, page))
        files += batch
        if len(batch) < 100:
            return files
        if len(files) >= 3000:  # GitHub's cap: a longer list cannot be read whole
            raise Refused("the PR changes 3000+ files; its list cannot be read whole")
        page += 1


def check_entry(pr, repo):
    head, base = pr["head"], pr["base"]
    if pr.get("state") != "open" or pr.get("merged"):
        raise Refused("the PR is not open")
    if not LANE.fullmatch(head["ref"]):
        raise Refused("head %r is not a lane-<digits> branch" % head["ref"])
    if (head.get("repo") or {}).get("full_name") != repo:
        raise Refused("head is not this repository's own branch")
    if base["ref"] != base["repo"]["default_branch"]:
        raise Refused("base %r is not the default branch" % base["ref"])


def check_senior(api, root, files, base, head):
    stamps = []
    for f in files:
        if f["status"] == "added" and FLAT_GRILL.fullmatch(f["filename"]):
            stamp = read_stamp(api, root, f["filename"], head)
            if stamp and stamp["reviewer"] == "senior-engineer":
                stamps.append(stamp)
    blocks = [s for s in stamps if s["stamp"] == "BLOCK"]
    approves = [s for s in stamps if s["stamp"] == "APPROVE"
                and covers(api, root, s["revision"], head)]
    # A BLOCK at/after an approval supersedes it, even if repair voided the
    # BLOCK's coverage. Never use that disqualified approval to resolve another.
    approves = [a for a in approves if not any(
        a["revision"] == b["revision"]
        or strictly_older(api, root, a["revision"], b["revision"]) for b in blocks)]
    if not approves:
        raise Refused("no senior-engineer APPROVE covers the head %s without a superseding senior-engineer BLOCK"
                      % head[:8])
    for block in blocks:
        revision = block["revision"]
        later = [a for a in approves if strictly_older(api, root, revision, a["revision"])]
        if not later:
            raise Refused("a senior-engineer BLOCK at %s is not cleared by a later APPROVE"
                          % revision[:8])
        diff = compare(api, root, revision, head)
        changes = diff.get("files", [])
        commits = diff.get("commits", [])
        # A merge's files look like a repair here, but the gate keeps a BLOCK
        # across a clean base merge: refuse rather than read one as the other.
        if (diff.get("status") not in ("ahead", "identical") or len(changes) >= 300
                or diff.get("total_commits", len(commits)) > len(commits)
                or any(len(c.get("parents", [])) > 1 for c in commits)):
            raise Refused("cannot establish coverage of senior-engineer BLOCK %s" % block["path"])
        if not all(is_exempt_addition("A" if f["status"] == "added" else "M", f["filename"])
                   for f in changes):
            continue  # repair plus fresh approval; preserve the stricter ancestry requirement
        resolver = None
        if (block["block_kind"] == "EXECUTION-REFUSAL"
                and unchanged_in_lane(api, root, base, head, block["path"], block["content"])):
            resolver = next((a for a in later if read_review_bytes(
                api, root, block["path"], a["revision"]) == block["content"]), None)
        if resolver is None:
            raise Refused("covering senior-engineer BLOCK %s remains unresolved" % block["path"])
        print("RESOLVED: senior-engineer APPROVE %s resolves EXECUTION-REFUSAL %s"
              % (resolver["path"], block["path"]))


def head_runs(api, root, head):
    runs, page = [], 1
    while True:
        data = api("GET", "%s/commits/%s/check-runs?filter=all&per_page=100&page=%d"
                   % (root, head, page))
        batch = data.get("check_runs", [])
        runs += batch
        if len(batch) < 100:
            return runs
        if len(runs) >= 1000:
            raise ApiError(0, "1000+ check runs on %s; cannot read them whole" % head[:8])
        page += 1


def runs_by_name(api, root, head):
    return [r for r in head_runs(api, root, head) if r.get("name") in CHECKS]


def last_ready_at(api, root, number):
    """created_at of the PR's last ready_for_review event, or None if it never had one."""
    stamps, page = [], 1
    while True:
        batch = api("GET", "%s/issues/%d/events?per_page=100&page=%d" % (root, number, page))
        stamps += [e["created_at"] for e in batch if e.get("event") == "ready_for_review"]
        if len(batch) < 100 or page >= 30:
            return max(stamps) if stamps else None
        page += 1


def exit_code_of(api, root, run):
    """The step exit code GitHub annotated on a failed run, or None."""
    for note in api("GET", "%s/check-runs/%d/annotations" % (root, run["id"])) or []:
        found = re.search(r"exit code (\d+)", note.get("message") or "")
        if found:
            return int(found.group(1))
    return None


def check_others(api, root, head):
    latest = {}
    for r in head_runs(api, root, head):
        if r.get("name") not in CHECKS and r["id"] > latest.get(r.get("name"), {"id": -1})["id"]:
            latest[r.get("name")] = r
    for name, r in sorted(latest.items()):
        if r.get("status") != "completed":
            raise Refused("check %r is still running; re-run when it concludes" % name)
        if r.get("conclusion") not in GREEN:
            raise Refused("check %r concluded %s; the operator merges" % (name, r.get("conclusion")))


def wait_for_run(api, root, head, seen, timeout, sleep, clock):
    """The newest run of each check not in `seen`, once both have concluded."""
    deadline = clock() + timeout
    while True:
        latest = {}
        for r in runs_by_name(api, root, head):
            if r["id"] not in seen and r["id"] > latest.get(r["name"], {"id": -1})["id"]:
                latest[r["name"]] = r
        if len(latest) == len(CHECKS) and all(r["status"] == "completed" for r in latest.values()):
            return latest
        if clock() >= deadline:
            return None
        sleep(15)


def mark_ready(api, run, root, repo, number):
    try:
        api("POST", "%s/pulls/%d/ccr/ready_for_review" % (root, number))
    except ApiError as exc:
        if exc.status != 404:
            raise
        code, _, err = run(["gh", "pr", "ready", str(number), "-R", repo])
        if code:
            raise ApiError(0, "gh pr ready: " + err.strip())


def arm(api, run, root, repo, number, head):
    try:
        api("PUT", "%s/pulls/%d/ccr/auto_merge" % (root, number))
    except ApiError as exc:
        if exc.status != 404:
            raise
        code, _, err = run(["gh", "pr", "merge", str(number), "-R", repo, "--auto", "--merge",
                            "--match-head-commit", head])
        if code:
            raise ApiError(0, "gh pr merge --auto: " + err.strip())


def disarm(api, run, root, repo, number):
    try:
        api("DELETE", "%s/pulls/%d/ccr/auto_merge" % (root, number))
    except ApiError as exc:
        if exc.status != 404:
            raise
        code, _, err = run(["gh", "pr", "merge", str(number), "-R", repo, "--disable-auto"])
        if code:
            raise ApiError(0, "gh pr merge --disable-auto: " + err.strip())


def arm_and_confirm(api, run, root, repo, number, head):
    """Arm, then read the PR back; the arm call carries no head on the CCR route."""
    arm(api, run, root, repo, number, head)
    now = api("GET", "%s/pulls/%d" % (root, number))
    moved = now["head"]["sha"]
    if moved != head:
        try:
            disarm(api, run, root, repo, number)
        except ApiError as exc:
            raise ApiError(0, "head moved to %s after the arm call and the disarm failed (%s);"
                           " it may be armed on an unchecked head" % (moved, exc)) from exc
        raise Disarmed("head moved from %s to %s after the arm call; auto-merge disabled,"
                       " re-run on the new head" % (head, moved))
    if not now.get("auto_merge"):
        raise ApiError(0, "the arm call returned but auto_merge is not set (a repository with"
                       " no required check refuses it); the operator merges")


def lane_ready(repo, number, api, run, sleep, clock, timeout):
    root = "repos/" + repo
    pr = api("GET", "%s/pulls/%d" % (root, number))
    check_entry(pr, repo)
    head = pr["head"]["sha"]
    files = pr_files(api, root, number)
    named = [p for f in files for p in (f["filename"], f.get("previous_filename")) if p and is_contract(p)]
    if named:
        raise Refused("contract or policy file: %s; the operator merges" % ", ".join(named))
    check_senior(api, root, files, pr["base"]["sha"], head)

    seen = set()
    if pr.get("draft"):
        seen = {r["id"] for r in runs_by_name(api, root, head)}
        mark_ready(api, run, root, repo, number)
        print("marked ready: #%d at %s" % (number, head[:8]))
    else:
        ready_at = last_ready_at(api, root, number)
        if ready_at:
            seen = {r["id"] for r in runs_by_name(api, root, head)
                    if (r.get("started_at") or "") < ready_at}
    run_ = wait_for_run(api, root, head, seen, timeout, sleep, clock)
    if run_ is None:
        raise ApiError(0, "timed out after %ds waiting for the ready run of %s"
                       % (timeout, " and ".join(CHECKS)))
    if run_["gate"]["conclusion"] != "success":
        raise ApiError(0, "gate %s on a ready PR: a surprise, stop and report"
                       % run_["gate"]["conclusion"])
    policy = run_["operator-merge"]
    if policy["conclusion"] != "success":
        if policy["conclusion"] == "failure" and exit_code_of(api, root, policy) == 1:
            raise Refused("operator-merge failure: a contract or policy path; the operator merges")
        raise ApiError(0, "operator-merge %s without the checker's verdict: a surprise, stop"
                       " and report" % policy["conclusion"])
    check_others(api, root, head)
    now = api("GET", "%s/pulls/%d" % (root, number))
    if now["head"]["sha"] != head:
        raise Refused("head moved while waiting; re-run on the new head")
    check_entry(now, repo)  # closed or retargeted while waiting

    try:
        arm_and_confirm(api, run, root, repo, number, head)
    except Refused:
        raise
    except (ApiError, KeyError, TypeError, ValueError) as exc:
        raise MayBeArmed(exc, "gh pr merge %d -R %s --disable-auto" % (number, repo)) from exc
    print("auto-merge armed: #%d at %s; GitHub merges once the required checks pass"
          % (number, head[:8]))


def main(argv=None, api=gh_api, run=gh_run, sleep=time.sleep, clock=time.monotonic):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("repo", help="owner/repo")
    parser.add_argument("number", help="PR number")
    parser.add_argument("--timeout", type=int, default=1800, help="seconds to wait for CI")
    args = parser.parse_args(argv)
    parts = args.repo.split("/")
    if len(parts) != 2 or not all(re.fullmatch(r"[A-Za-z0-9_.-]+", p) for p in parts):
        print("usage error: repo must be owner/repo", file=sys.stderr)
        return 2
    if not re.fullmatch(r"[1-9][0-9]*", args.number):
        print("usage error: PR number must be a positive integer", file=sys.stderr)
        return 2
    try:
        lane_ready(args.repo, int(args.number), api, run, sleep, clock, args.timeout)
    except Disarmed as exc:
        print("REFUSED: %s." % exc)
        return 1
    except Refused as exc:
        print("REFUSED: %s. Auto-merge not armed." % exc)
        return 1
    except MayBeArmed as exc:
        print("COULD NOT RUN: %s. Auto-merge MAY BE ARMED; disable it by hand: %s"
              % (exc, exc.hand), file=sys.stderr)
        return 2
    except (ApiError, KeyError, TypeError, ValueError) as exc:
        print("COULD NOT RUN: %s. Auto-merge not armed." % exc, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
