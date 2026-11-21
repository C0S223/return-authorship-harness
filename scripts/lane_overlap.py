#!/usr/bin/env python3
"""List overlaps with open PRs and pushed lane-* branches (read-only).

Usage: python3 scripts/lane_overlap.py owner/repo path [path ...]
Paths are repository-relative; only a trailing slash selects a directory.
Absolute paths, backslashes, repeated slashes and dot segments are refused.
Renames are checked at both their current and previous paths.
Exit 0: clear, 1: overlaps, 2: fetch/usage error. No local git state is used.
"""

import argparse
import json
import subprocess
import sys
from urllib.parse import quote


class FetchError(Exception):
    """An API request could not be completed or returned invalid data."""


def gh_fetch(endpoint):
    """Return JSON pages. --slurp preserves page boundaries for all shapes."""
    try:
        result = subprocess.run(
            ["gh", "api", "--method", "GET", "--paginate", "--slurp", endpoint],
            check=True, capture_output=True, text=True, timeout=60,
        )
        pages = json.loads(result.stdout)
        if not isinstance(pages, list):
            raise ValueError("expected a list of pages")
        return pages
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        detail = exc.stderr.strip() if isinstance(exc, subprocess.CalledProcessError) else str(exc)
        raise FetchError(f"{endpoint}: {detail}") from exc


def matches(filename, paths):
    return any(filename.startswith(path) if path.endswith("/") else filename == path
               for path in paths)


def find_overlaps(repo, paths, fetcher=gh_fetch):
    """Return output lines; fetcher(endpoint) supplies a list of JSON pages.

    Any failed request aborts the scan: a partial scan cannot establish safety.
    """
    root = "repos/" + repo
    hits = []

    def pages(endpoint):
        try:
            value = fetcher(endpoint)
            if not isinstance(value, list) or not value:
                raise ValueError("expected nonempty list of pages")
            return value
        except Exception as exc:
            raise FetchError(f"{endpoint}: {exc}") from exc

    def items(endpoint):
        for page in pages(endpoint):
            if not isinstance(page, list):
                raise FetchError(f"{endpoint}: expected an array page")
            yield from page

    def add_files(label, files):
        for entry in files:
            filenames = [entry["filename"]]
            if "previous_filename" in entry:
                filenames.append(entry["previous_filename"])
            for filename in filenames:
                if matches(filename, paths):
                    line = f"{label}: {filename}"
                    if line not in hits:
                        hits.append(line)

    try:
        for pr in items(root + "/pulls?state=open&per_page=100"):
            number = pr["number"]
            endpoint = f"{root}/pulls/{number}/files?per_page=100"
            files = list(items(endpoint))
            # GitHub returns at most 3000 files for a PR, even with pagination.
            # Refuse to label a potentially incomplete scan clear.
            if len(files) >= 3000:
                raise FetchError(f"{endpoint}: PR file limit reached")
            add_files(f"PR #{number} {pr['head']['ref']}", files)

        metadata = pages(root)[0]
        default = quote(metadata["default_branch"], safe="")
        for ref in items(root + "/git/matching-refs/heads/lane-?per_page=100"):
            full_ref = ref["ref"]
            if not full_ref.startswith("refs/heads/lane-"):
                continue
            branch = full_ref[len("refs/heads/"):]
            endpoint = f"{root}/compare/{default}...{quote(branch, safe='')}?per_page=100"
            for page in pages(endpoint):
                files = page.get("files", [])
                # GitHub caps compare's file list at 300, even with pagination.
                # Refuse to label a potentially incomplete scan clear.
                if len(files) >= 300:
                    raise FetchError(f"{endpoint}: compare file limit reached")
                add_files(f"branch {branch}", files)
    except (KeyError, TypeError, AttributeError) as exc:
        raise FetchError(f"{root}: malformed API response ({exc})") from exc
    return hits


def main(argv=None, fetcher=gh_fetch):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", help="owner/repo")
    parser.add_argument("paths", nargs="+", help="exact file or directory ending /")
    args = parser.parse_args(argv)
    if len(args.repo.split("/")) != 2 or any(not part for part in args.repo.split("/")):
        parser.error("repo must be owner/repo")
    if any(not path for path in args.paths):
        parser.error("paths must not be empty")
    for path in args.paths:
        if (path.startswith("/") or "\\" in path or "//" in path
                or any(part in (".", "..") for part in path.split("/"))):
            print(f"path error: {path!r}: use a repository-relative path without "
                  "backslashes, repeated slashes or dot segments", file=sys.stderr)
            return 2
    try:
        hits = find_overlaps(args.repo, args.paths, fetcher)
    except FetchError as exc:
        print(f"fetch error: {exc}", file=sys.stderr)
        return 2
    for line in hits:
        print(line)
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
