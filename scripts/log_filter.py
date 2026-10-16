#!/usr/bin/env python
"""Print the day-log lines a cloud session's close must carry.

Reads a `.agent-log/YYYY-MM-DD.md` day log on stdin and prints, in file order,
every escape, grant, integrity and `peer-` line. `.claude/hooks/session-close.sh`
runs this under a cloud boundary and writes the result into a tracked handoff,
because the day log itself dies with the VM or container.

    python scripts/log_filter.py < .agent-log/2026-01-01.md

One owner for the rule: the hook invokes this file rather than keeping a grep
copy, so the two cannot drift. A grep that selected only gate words once carried
1 of ~3000 escape lines, because escape lines are recognized by their verb, not
by a fixed word.
"""
import re
import sys

# Anchor on the marker, but capture it instead of hardcoding one. Bounded on
# purpose: no spaces, 32 chars max. A log line is untrusted text.
MARKER = r"[A-Za-z0-9_-]{1,32}"
LINE_RE = re.compile(rf"^- (\d\d:\d\d:\d\d) \[({MARKER})\] (.*)$")

# A line records transit when its VERB does, not when its marker is on a list.
# Two writers, two spellings of the same acts: log-escape.sh writes the first
# group; a tool or agent whose send no hook saw writes `SEND`. `web:` and
# `WebFetch` are one act, which is why the egress tool names sit here.
ESCAPE_VERBS = frozenset({
    "spawn", "push", "net", "install", "web", "shellwrite",   # log-escape.sh
    "filewrite",
    "send",
    "webfetch", "websearch",
})

# The grant half: integrity lines, the unlock verbs, the gate decision words,
# and bracketed `peer-` markers, as a substring search over the whole line,
# because its writers agree on no prefix.
GRANT_RE = re.compile(r"\[policy-integrity\]|unlock-armed|unlock-consumed|unlock-refused|unlock-retired|unlock-replaced|unlock-revoked"
                      r"| DENY | ASK |ALLOW|\[peer-")


def _verb(text):
    """The line's first token, lowercased, minus the punctuation writers vary
    on. `?` collapses onto the base verb deliberately: log-escape.sh writes it
    when its quote-blanker may have swallowed a real act."""
    head = text.split(None, 1)
    return head[0].rstrip(":?").lower() if head else ""


def _is_escape(verb):
    """`peer-` matches by prefix: log-escape.sh interpolates the trigger verb,
    so enumerating today's would miss the next one."""
    return verb in ESCAPE_VERBS or verb.startswith("peer-")


def is_survivor(line):
    """True when the cloud copy must carry this day-log line: the union of the
    grant half and the escape half, never one replacing the other."""
    match = LINE_RE.match(line)
    return bool(GRANT_RE.search(line)) or (
        match is not None and _is_escape(_verb(match.group(3))))


def main():
    for stream in (sys.stdin, sys.stdout):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    for line in sys.stdin:
        line = line.rstrip("\n")
        if is_survivor(line):
            print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
