#!/usr/bin/env python3
"""Safety probe: try each forbidden act from this shell and report what happened.

Usage: python3 scripts/safety_probe.py [--root <checkout>] [--no-network] [--json]

An act row reads PASS (the OS refused the act), FAIL (it went
through, or nothing was there to refuse it) or SKIP (it could not be tried or
could not be told apart here, with the reason). A SKIP is an unknown, never a
pass. The `config` rows try nothing: they say what this checkout's settings
file reads, not what the session applies. The rows describe the shell that
runs this script. Run it through the agent's own shell tool to learn what the
agent can do; run by hand, it describes your terminal instead.

What it tries, and what it leaves behind (nothing, unless a row says so):
  outside-write    creates one uniquely named empty file in the home folder
                   and removes it at once
  key-folder-read  lists each `sandbox.filesystem.denyRead` folder; no file in
                   it is opened and no name is printed
  network          one HTTPS HEAD to an unlisted host; only if that does not
                   answer, one to a listed host as a control; the requests
                   carry nothing, and a redirect is never followed
  protected-write  opens each existing `sandbox.filesystem.denyWrite` file for
                   append and closes it (for a folder, one file inside it); no
                   byte is written
  config           reads `.claude/settings.json` and, on Linux, looks for the
                   two tools the sandbox needs; changes nothing
  github-ruleset   always SKIP in this version (it needs an authenticated read)

The file tools (Edit, Write) do not pass through a shell, so no script can test
their deny rules: `.claude/skills/safety-probe/SKILL.md` covers them.

Exit codes: 0 no FAIL row, 1 one or more FAIL rows, 2 the probe did not
finish or could not print its rows (no settings file, settings of the wrong
shape, output that cannot be written, bad arguments). On exit 2 the acts
before that point may already have happened.
Stdlib only; changes no file.
"""
import argparse
import errno
import http.client
import json
import os
import shutil
import sys
import urllib.error
import urllib.request

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"
UNLISTED_HOST = "example.com"   # reserved for documentation; never on an allow list
WIDE_MODES = ("bypassPermissions", "acceptEdits", "dontAsk", "auto")
REFUSALS = (errno.EACCES, errno.EPERM, errno.EROFS)   # the OS said no; any other error is not a refusal
TIMEOUT = 8


class ProbeError(Exception):
    """The probe itself could not run: exit code 2."""


def row(check, target, result, detail):
    return {"check": check, "target": target, "result": result, "detail": detail}


def errname(exc):
    """A short, stable name for an OS error: 'EACCES', 'EROFS', ..."""
    code = getattr(exc, "errno", None)
    return errno.errorcode.get(code, type(exc).__name__)


def refusal(check, target, exc):
    """PASS only when the OS refused the act. An error of any other kind (the
    wrong kind of object, nothing there) means the act was not tried: SKIP."""
    if getattr(exc, "errno", None) in REFUSALS:
        return row(check, target, PASS, "refused (%s)" % errname(exc))
    return row(check, target, SKIP, "could not be tried (%s)" % errname(exc))


def resolve(entry, root, home):
    """A settings path entry as an absolute path: `~/x` under home, the rest
    relative to the checkout root."""
    if entry == "~" or entry.startswith("~/"):
        return os.path.normpath(os.path.join(home, entry[2:]))
    return os.path.normpath(os.path.join(root, entry))


def check_outside_write(home, token):
    name = ".harness-safety-probe-%s" % token
    path = os.path.join(home, name)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError as exc:
        return [refusal("outside-write", "~/" + name, exc)]
    os.close(fd)
    try:
        os.remove(path)
    except OSError as exc:
        return [row("outside-write", "~/" + name, FAIL,
                    "created, and could NOT be removed (%s): delete it by hand" % errname(exc))]
    return [row("outside-write", "~/" + name, FAIL, "created, then removed")]


def check_key_folders(entries, root, home):
    rows = []
    for entry in entries:
        path = resolve(entry, root, home)
        if not os.path.lexists(path):
            rows.append(row("key-folder-read", entry, SKIP, "absent, or hidden from this shell"))
            continue
        if not os.path.isdir(path):
            rows.append(row("key-folder-read", entry, SKIP,
                            "not a folder: this version lists folders and opens no file"))
            continue
        try:
            names = os.listdir(path)
        except OSError as exc:
            rows.append(refusal("key-folder-read", entry, exc))
            continue
        if names:
            rows.append(row("key-folder-read", entry, FAIL, "listed, and not empty (no file opened)"))
        else:
            rows.append(row("key-folder-read", entry, SKIP,
                            "listed, but empty: an empty folder and a sandbox's empty stand-in "
                            "look the same from here"))
    return rows


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect: the 3xx comes back as an HTTPError, so one
    HEAD stays one request and the answer is the first host's own."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def opener():
    return urllib.request.build_opener(NoRedirect)


def head(host):
    """(True, detail) when `host` answered, (False, detail) when it was not
    reached, (None, detail) when something answered that cannot be read. A
    proxy refusal (403/407) counts as not reached; any other status came from
    the host or stands in for it. A redirect is the host's answer and is not
    followed."""
    req = urllib.request.Request("https://%s/" % host, method="HEAD")
    try:
        with opener().open(req, timeout=TIMEOUT) as resp:
            return True, "HTTP %s" % resp.status
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 407):
            return False, "refused (HTTP %s)" % exc.code
        if 300 <= exc.code < 400:
            return True, "HTTP %s, redirect not followed" % exc.code
        return True, "HTTP %s" % exc.code
    except (urllib.error.URLError, OSError) as exc:
        return False, "no connection (%s)" % (getattr(exc, "reason", None) or type(exc).__name__)
    except http.client.HTTPException as exc:
        return None, "an answer that could not be read (%s)" % type(exc).__name__


def check_network(allowed, fetch=head):
    """An unlisted host must not answer. If it answers, that is a FAIL whatever
    else is true. If it does not, a control request to a listed host tells a
    contained machine from an offline one, where nothing answers."""
    if not allowed:
        return [row("network", UNLISTED_HOST, SKIP, "no allowedDomains in settings to compare with")]
    reached, detail = fetch(UNLISTED_HOST)
    if reached:
        return [row("network", UNLISTED_HOST, FAIL, "answered (%s)" % detail)]
    if reached is None:
        return [row("network", UNLISTED_HOST, SKIP, "cannot tell: %s" % detail)]
    control = next((host for host in allowed if "*" not in host), None)
    if control is None:
        return [row("network", UNLISTED_HOST, SKIP,
                    "%s; no plain host in allowedDomains to use as a control" % detail)]
    control_ok, control_detail = fetch(control)
    if control_ok:
        return [row("network", UNLISTED_HOST, PASS, "%s; %s answered" % (detail, control))]
    return [row("network", UNLISTED_HOST, SKIP,
                "control host %s did not answer either (%s): cannot tell contained from offline"
                % (control, control_detail))]


def first_file(folder):
    """One regular file under `folder`, shallowest and alphabetical first."""
    for base, dirs, files in os.walk(folder):
        dirs.sort()
        for name in sorted(files):
            path = os.path.join(base, name)
            if os.path.isfile(path) and not os.path.islink(path):
                return path
    return None


def check_protected_writes(entries, root, home):
    rows = []
    for entry in entries:
        path = resolve(entry, root, home)
        if not os.path.lexists(path):
            rows.append(row("protected-write", entry, SKIP, "absent"))
            continue
        target = first_file(path) if os.path.isdir(path) else path
        if target is None:
            rows.append(row("protected-write", entry, SKIP, "no file inside to try"))
            continue
        try:
            fd = os.open(target, os.O_WRONLY | os.O_APPEND)
        except OSError as exc:
            rows.append(refusal("protected-write", entry, exc))
        else:
            os.close(fd)
            rows.append(row("protected-write", entry, FAIL, "opened for writing (no byte written)"))
    return rows


def check_config(settings, platform=sys.platform, which=shutil.which):
    sandbox = settings.get("sandbox") or {}
    perms = settings.get("permissions") or {}
    mode = perms.get("defaultMode")
    missing = [t for t in ("bwrap", "socat") if not which(t)] if platform.startswith("linux") else []
    tools = ([] if not platform.startswith("linux") else
             [row("config", "sandbox tools", FAIL if missing else PASS,
                  "missing on PATH: %s (the Linux sandbox cannot start without them)" % ", ".join(missing)
                  if missing else "bwrap and socat are on PATH")])
    return tools + [
        row("config", "sandbox.enabled", PASS if sandbox.get("enabled") is True else FAIL,
            "true" if sandbox.get("enabled") is True else "not true: shell commands are not contained"),
        row("config", "permissions.allow", FAIL if perms.get("allow") else PASS,
            "%d allow rule(s) widen the defaults" % len(perms["allow"]) if perms.get("allow")
            else "no allow rules"),
        row("config", "permissions.defaultMode", FAIL if mode in WIDE_MODES else PASS,
            "%s widens the default" % mode if mode in WIDE_MODES else "not widened (%s)" % (mode or "unset")),
    ]


def block(parent, key, where):
    """`parent[key]` as an object, {} when absent; a ProbeError when it is anything else."""
    value = parent.get(key)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ProbeError("`%s` in .claude/settings.json is not an object" % where)
    return value


def strings(parent, key, where):
    """`parent[key]` as a list of strings, [] when absent; a ProbeError when it is anything else."""
    value = parent.get(key)
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ProbeError("`%s` in .claude/settings.json is not a list of strings" % where)
    return value


def read_settings(root):
    """The settings object and the three lists the probe tests. A ProbeError
    names what is wrong when the file is missing, unreadable or the wrong shape."""
    try:
        with open(os.path.join(root, ".claude", "settings.json"), encoding="utf-8") as fh:
            settings = json.load(fh)
    except (OSError, ValueError) as exc:
        raise ProbeError("cannot read .claude/settings.json under --root: %s" % exc)
    if not isinstance(settings, dict):
        raise ProbeError("`.claude/settings.json` under --root is not an object")
    sandbox = block(settings, "sandbox", "sandbox")
    files = block(sandbox, "filesystem", "sandbox.filesystem")
    net = block(sandbox, "network", "sandbox.network")
    strings(block(settings, "permissions", "permissions"), "allow", "permissions.allow")
    return (settings,
            strings(files, "denyRead", "sandbox.filesystem.denyRead"),
            strings(files, "denyWrite", "sandbox.filesystem.denyWrite"),
            strings(net, "allowedDomains", "sandbox.network.allowedDomains"))


def probe(root, home, token, network=True, fetch=head):
    """Every row, in a fixed order. Raises ProbeError when the probe cannot
    run: the caller turns that into exit 2."""
    settings, deny_read, deny_write, allowed = read_settings(root)
    rows = check_outside_write(home, token)
    rows += check_key_folders(deny_read, root, home)
    rows += (check_network(allowed, fetch) if network
             else [row("network", UNLISTED_HOST, SKIP, "skipped by --no-network")])
    rows += check_protected_writes(deny_write, root, home)
    rows += check_config(settings)
    rows.append(row("github-ruleset", "default branch", SKIP,
                    "not probed in this version: check the repository's rulesets by hand"))
    return rows


def render(rows, agent_shell):
    lines = []
    if not agent_shell:
        lines.append("note: CLAUDECODE is not set, so this is not an agent shell. "
                     "These rows describe your own terminal, not what the agent can do.")
    width = max(len(r["check"]) for r in rows)
    for r in rows:
        lines.append("%-4s  %-*s  %s: %s" % (r["result"], width, r["check"], r["target"], r["detail"]))
    asked = any(r["target"] == "sandbox.enabled" and r["result"] == PASS for r in rows)
    open_shell = any(r["check"] == "outside-write" and r["result"] == FAIL for r in rows)
    if asked and open_shell:
        lines.append("note: the settings ask for the sandbox, but this shell wrote outside the "
                     "project. The sandbox is not containing this shell.")
    counts = {k: sum(1 for r in rows if r["result"] == k) for k in (PASS, FAIL, SKIP)}
    lines.append("-- %d PASS, %d FAIL, %d SKIP" % (counts[PASS], counts[FAIL], counts[SKIP]))
    return "\n".join(lines)


def show(text, stream):
    """Print on a stream that may not be able to show every character: what it
    cannot show is escaped, never dropped."""
    encoding = getattr(stream, "encoding", None)
    if encoding:
        text = text.encode(encoding, "backslashreplace").decode(encoding)
    print(text, file=stream)


def unfinished(message):
    try:
        show(message, sys.stderr)
    except Exception:   # nowhere left to say it; the exit code still does
        pass
    return 2


def main(argv=None, home=None):
    """`home` is for the tests, which must never touch the real home folder."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ap = argparse.ArgumentParser(description="Try each forbidden act and report what happened.")
    ap.add_argument("--root", default=here, help="the checkout to probe (default: this one)")
    ap.add_argument("--no-network", action="store_true", help="skip the HTTPS requests")
    ap.add_argument("--json", action="store_true", help="print the rows as JSON")
    args = ap.parse_args(argv)
    token = "%d-%s" % (os.getpid(), os.urandom(4).hex())
    try:
        rows = probe(os.path.abspath(args.root), home or os.path.expanduser("~"), token,
                     network=not args.no_network)
        agent_shell = bool(os.environ.get("CLAUDECODE"))
        if args.json:
            text = json.dumps({"agent_shell": agent_shell, "platform": sys.platform, "rows": rows},
                              indent=1)
        else:
            text = render(rows, agent_shell)
        show(text, sys.stdout)
        sys.stdout.flush()
    except ProbeError as exc:
        return unfinished("probe error: %s" % exc)
    except Exception as exc:   # an unfinished probe must never exit 1, the FAIL-rows code
        return unfinished("probe error: unexpected %s: %s" % (type(exc).__name__, exc))
    return 1 if any(r["result"] == FAIL for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
