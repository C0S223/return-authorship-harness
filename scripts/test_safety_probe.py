#!/usr/bin/env python3
"""Tests for scripts/safety_probe.py: every check reads PASS, FAIL and SKIP on
the state that should produce it, the exit codes hold, and a run leaves nothing
behind. No test touches the real home folder or the network: each builds its
own folders and passes them in, the network code runs against a stubbed opener
or two servers on loopback, and every whole-run test fails if the probe opens,
lists or removes anything under the real home folder.
"""
import errno
import http.client
import http.server
import io
import json
import os
import shutil
import stat
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import safety_probe as sp  # noqa: E402

ROOT_USER = hasattr(os, "geteuid") and os.geteuid() == 0
POSIX = os.name != "nt"
REAL_HOME = os.path.realpath(os.path.expanduser("~"))


def results(rows):
    return [r["result"] for r in rows]


def under(folder, path):
    folder, path = os.path.realpath(folder), os.path.realpath(path)
    return path == folder or path.startswith(folder.rstrip(os.sep) + os.sep)


def refused(code):
    return OSError(code, os.strerror(code))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="safety-probe-test-")
        self.addCleanup(self._cleanup)
        self.home = os.path.join(self.tmp, "home")
        self.root = os.path.join(self.tmp, "repo")
        os.makedirs(self.home)
        os.makedirs(os.path.join(self.root, ".claude"))

    def _cleanup(self):
        for base, dirs, _files in os.walk(self.tmp):
            for d in dirs:
                os.chmod(os.path.join(base, d), stat.S_IRWXU)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, rel, text="x\n", base=None):
        path = os.path.join(base or self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def settings(self, **over):
        data = {"permissions": {"deny": ["Workflow"]},
                "sandbox": {"enabled": True,
                            "filesystem": {"denyRead": ["~/.ssh"], "denyWrite": ["./CLAUDE.md"]},
                            "network": {"allowedDomains": ["github.com"]}}}
        data.update(over)
        self.write(".claude/settings.json", json.dumps(data))
        return data

    def stub(self, name, error):
        """Make `os.<name>` raise `error` inside the probe for this test."""
        patch = mock.patch.object(sp.os, name, side_effect=error)
        patch.start()
        self.addCleanup(patch.stop)


class OutsideWrite(Base):
    def test_writable_home_fails_and_leaves_nothing(self):
        rows = sp.check_outside_write(self.home, "t1")
        self.assertEqual(results(rows), [sp.FAIL])
        self.assertIn("removed", rows[0]["detail"])
        self.assertEqual(os.listdir(self.home), [])

    @unittest.skipIf(ROOT_USER or not POSIX, "needs a user the OS can refuse")
    def test_read_only_home_passes(self):
        os.chmod(self.home, stat.S_IRUSR | stat.S_IXUSR)
        rows = sp.check_outside_write(self.home, "t2")
        self.assertEqual(results(rows), [sp.PASS])
        self.assertIn("refused", rows[0]["detail"])

    def test_each_refusal_passes_whoever_runs_the_suite(self):
        for code in sp.REFUSALS:
            with mock.patch.object(sp.os, "open", side_effect=refused(code)):
                rows = sp.check_outside_write(self.home, "t3")
            self.assertEqual(results(rows), [sp.PASS], errno.errorcode[code])
            self.assertIn(errno.errorcode[code], rows[0]["detail"])

    def test_the_refusals_are_these_three_errors_and_no_other(self):
        # Named here, not read from the probe: a wider or narrower set must fail.
        for code, want in ((errno.EACCES, sp.PASS), (errno.EPERM, sp.PASS), (errno.EROFS, sp.PASS),
                           (errno.ENOTDIR, sp.SKIP), (errno.EEXIST, sp.SKIP),
                           (errno.EBUSY, sp.SKIP), (errno.ELOOP, sp.SKIP)):
            with mock.patch.object(sp.os, "open", side_effect=refused(code)):
                rows = sp.check_outside_write(self.home, "t6")
            self.assertEqual(results(rows), [want], errno.errorcode[code])

    def test_missing_home_is_not_a_refusal(self):
        rows = sp.check_outside_write(os.path.join(self.tmp, "nowhere"), "t4")
        self.assertEqual(results(rows), [sp.SKIP])
        self.assertIn("ENOENT", rows[0]["detail"])

    def test_a_canary_that_cannot_be_removed_fails_and_says_so(self):
        self.stub("remove", refused(errno.EPERM))
        rows = sp.check_outside_write(self.home, "t5")
        self.assertEqual(results(rows), [sp.FAIL])
        self.assertIn("could NOT be removed", rows[0]["detail"])
        self.assertEqual(os.listdir(self.home), [".harness-safety-probe-t5"])


class KeyFolders(Base):
    def test_listable_folder_fails_without_naming_its_files(self):
        self.write(".ssh/id_secret", base=self.home)
        rows = sp.check_key_folders(["~/.ssh"], self.root, self.home)
        self.assertEqual(results(rows), [sp.FAIL])
        self.assertNotIn("id_secret", json.dumps(rows))

    def test_empty_listing_is_an_unknown_not_a_fail(self):
        # A sandbox may show an empty folder in place of a denied one.
        os.makedirs(os.path.join(self.home, ".ssh"))
        rows = sp.check_key_folders(["~/.ssh"], self.root, self.home)
        self.assertEqual(results(rows), [sp.SKIP])
        self.assertIn("empty", rows[0]["detail"])

    def test_absent_folder_skips(self):
        rows = sp.check_key_folders(["~/.aws"], self.root, self.home)
        self.assertEqual(results(rows), [sp.SKIP])

    @unittest.skipIf(ROOT_USER or not POSIX, "needs a user the OS can refuse")
    def test_unreadable_folder_passes(self):
        os.makedirs(os.path.join(self.home, ".gnupg"))
        os.chmod(os.path.join(self.home, ".gnupg"), 0)
        rows = sp.check_key_folders(["~/.gnupg"], self.root, self.home)
        self.assertEqual(results(rows), [sp.PASS])

    def test_each_refusal_passes_whoever_runs_the_suite(self):
        self.write(".ssh/id_secret", base=self.home)
        for code in sp.REFUSALS:
            with mock.patch.object(sp.os, "listdir", side_effect=refused(code)):
                rows = sp.check_key_folders(["~/.ssh"], self.root, self.home)
            self.assertEqual(results(rows), [sp.PASS], errno.errorcode[code])

    def test_an_error_that_is_not_a_refusal_skips(self):
        self.write(".ssh/id_secret", base=self.home)
        self.stub("listdir", refused(errno.EIO))
        rows = sp.check_key_folders(["~/.ssh"], self.root, self.home)
        self.assertEqual(results(rows), [sp.SKIP])
        self.assertIn("EIO", rows[0]["detail"])

    def test_a_readable_file_entry_never_passes(self):
        # `~/.netrc` on a denyRead list: the listing fails, but nothing refused a read.
        self.write(".netrc", "machine x login y\n", base=self.home)
        rows = sp.check_key_folders(["~/.netrc"], self.root, self.home)
        self.assertEqual(results(rows), [sp.SKIP])
        self.assertIn("not a folder", rows[0]["detail"])


class Head(unittest.TestCase):
    def answer(self, outcome):
        # urlopen and build_opener raise while these tests run, so a head()
        # that went back to either fails here instead of reaching the network.
        # A head() built on http.client or OpenerDirector directly is not
        # caught by this guard.
        built = mock.MagicMock()
        built.open.side_effect = outcome
        loose = AssertionError("head() opened a connection outside opener()")
        for patch in (mock.patch.object(sp, "opener", return_value=built),
                      mock.patch.object(sp.urllib.request, "urlopen", side_effect=loose),
                      mock.patch.object(sp.urllib.request, "build_opener", side_effect=loose)):
            patch.start()
            self.addCleanup(patch.stop)
        return built.open

    def test_a_redirect_is_an_answer_and_is_not_followed(self):
        for code in (300, 301, 302, 303, 307, 308):
            self.answer(self.http_error(code))
            self.assertEqual(sp.head("example.com"),
                             (True, "HTTP %d, redirect not followed" % code))

    def test_a_client_error_is_an_answer_and_not_a_redirect(self):
        for code in (400, 404):
            self.answer(self.http_error(code))
            self.assertEqual(sp.head("example.com"), (True, "HTTP %d" % code))

    def http_error(self, code):
        return urllib.error.HTTPError("https://example.com/", code, "x", {}, None)

    def test_an_answer_is_reached_and_the_request_carries_nothing(self):
        reply = mock.MagicMock()
        reply.__enter__.return_value.status = 200
        opener = self.answer([reply])
        self.assertEqual(sp.head("example.com"), (True, "HTTP 200"))
        request = opener.call_args[0][0]
        self.assertEqual(opener.call_args[1], {"timeout": sp.TIMEOUT})
        self.assertEqual((request.get_method(), request.full_url, request.data),
                         ("HEAD", "https://example.com/", None))
        self.assertEqual(request.header_items(), [])

    def test_a_proxy_refusal_is_not_reached(self):
        for code in (403, 407):
            self.answer(self.http_error(code))
            self.assertEqual(sp.head("example.com"), (False, "refused (HTTP %d)" % code))

    def test_any_other_status_came_from_the_host(self):
        self.answer(self.http_error(500))
        self.assertEqual(sp.head("example.com"), (True, "HTTP 500"))

    def test_no_connection_is_not_reached(self):
        self.answer(urllib.error.URLError("timed out"))
        self.assertEqual(sp.head("example.com"), (False, "no connection (timed out)"))
        self.answer(ConnectionResetError())
        self.assertFalse(sp.head("example.com")[0])

    def test_an_unreadable_answer_is_an_unknown(self):
        self.answer(http.client.BadStatusLine("junk"))
        reached, detail = sp.head("example.com")
        self.assertIsNone(reached)
        self.assertIn("BadStatusLine", detail)


class Redirect(unittest.TestCase):
    """The probe's opener against two servers on loopback: the first answers
    302 pointing at the second. Nothing leaves this machine."""

    def serve(self, code, location=None):
        hits = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_HEAD(self):
                hits.append(self.path)
                self.send_response(code)
                if location:
                    self.send_header("Location", location)
                self.send_header("Content-Length", "0")
                self.end_headers()

            # Before Python 3.13 urllib follows a redirected HEAD with a GET.
            do_GET = do_HEAD

            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return "http://127.0.0.1:%d/" % server.server_address[1], hits

    def setUp(self):
        patch = mock.patch.dict(os.environ, {"no_proxy": "*", "NO_PROXY": "*"})
        patch.start()
        self.addCleanup(patch.stop)
        self.second, self.second_hits = self.serve(200)
        self.first, self.first_hits = self.serve(302, self.second)

    def request(self):
        return urllib.request.Request(self.first, method="HEAD")

    def test_a_plain_opener_follows_so_the_fixture_can_tell(self):
        with urllib.request.build_opener().open(self.request(), timeout=5):
            pass
        self.assertEqual((len(self.first_hits), len(self.second_hits)), (1, 1))

    def test_the_probe_opener_stops_at_the_redirect(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            sp.opener().open(self.request(), timeout=5)
        caught.exception.close()
        self.assertEqual(caught.exception.code, 302)
        self.assertEqual((len(self.first_hits), len(self.second_hits)), (1, 0))


class Network(unittest.TestCase):
    def fetch(self, answers):
        calls = []

        def fake(host):
            calls.append(host)
            return answers[host]
        return fake, calls

    def test_unlisted_host_refused_while_control_answers_passes(self):
        fake, calls = self.fetch({"github.com": (True, "HTTP 200"),
                                  sp.UNLISTED_HOST: (False, "refused (HTTP 403)")})
        self.assertEqual(results(sp.check_network(["github.com"], fake)), [sp.PASS])
        self.assertEqual(calls, [sp.UNLISTED_HOST, "github.com"])

    def test_unlisted_host_answering_fails_and_no_control_is_sent(self):
        fake, calls = self.fetch({sp.UNLISTED_HOST: (True, "HTTP 200")})
        self.assertEqual(results(sp.check_network(["github.com"], fake)), [sp.FAIL])
        self.assertEqual(calls, [sp.UNLISTED_HOST])

    def test_an_open_network_fails_even_when_the_control_would_not_answer(self):
        fake, _ = self.fetch({"github.com": (False, "refused (HTTP 403)"),
                              sp.UNLISTED_HOST: (True, "HTTP 200")})
        self.assertEqual(results(sp.check_network(["github.com"], fake)), [sp.FAIL])

    def test_offline_machine_skips_and_never_reads_as_contained(self):
        fake, calls = self.fetch({"github.com": (False, "no connection (timed out)"),
                                  sp.UNLISTED_HOST: (False, "no connection (timed out)")})
        rows = sp.check_network(["github.com"], fake)
        self.assertEqual(results(rows), [sp.SKIP])
        self.assertIn("cannot tell contained from offline", rows[0]["detail"])
        self.assertEqual(calls, [sp.UNLISTED_HOST, "github.com"])

    def test_an_unreadable_answer_skips(self):
        fake, calls = self.fetch({sp.UNLISTED_HOST: (None, "an answer that could not be read (X)")})
        self.assertEqual(results(sp.check_network(["github.com"], fake)), [sp.SKIP])
        self.assertEqual(calls, [sp.UNLISTED_HOST])

    def test_a_control_that_cannot_be_read_is_not_an_answer(self):
        fake, calls = self.fetch({"github.com": (None, "an answer that could not be read (X)"),
                                  sp.UNLISTED_HOST: (False, "refused (HTTP 403)")})
        self.assertEqual(results(sp.check_network(["github.com"], fake)), [sp.SKIP])
        self.assertEqual(calls, [sp.UNLISTED_HOST, "github.com"])

    def test_a_wildcard_is_never_used_as_the_control(self):
        fake, calls = self.fetch({"github.com": (True, "HTTP 200"),
                                  sp.UNLISTED_HOST: (False, "refused (HTTP 403)")})
        self.assertEqual(results(sp.check_network(["*.github.com", "github.com"], fake)), [sp.PASS])
        self.assertEqual(calls, [sp.UNLISTED_HOST, "github.com"])
        fake, calls = self.fetch({sp.UNLISTED_HOST: (False, "refused (HTTP 403)")})
        self.assertEqual(results(sp.check_network(["*.github.com"], fake)), [sp.SKIP])

    def test_no_allow_list_skips_and_sends_nothing(self):
        fake, calls = self.fetch({})
        self.assertEqual(results(sp.check_network([], fake)), [sp.SKIP])
        self.assertEqual(calls, [])


class ProtectedWrites(Base):
    def test_writable_file_fails_and_is_not_changed(self):
        path = self.write("CLAUDE.md", "contract\n")
        before = (os.path.getsize(path), os.stat(path).st_mtime_ns)
        rows = sp.check_protected_writes(["./CLAUDE.md"], self.root, self.home)
        self.assertEqual(results(rows), [sp.FAIL])
        self.assertEqual((os.path.getsize(path), os.stat(path).st_mtime_ns), before)
        with open(path, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "contract\n")

    def test_folder_entry_tries_a_file_inside(self):
        self.write("roles/a.md")
        rows = sp.check_protected_writes(["./roles"], self.root, self.home)
        self.assertEqual(results(rows), [sp.FAIL])

    def test_absent_and_empty_entries_skip(self):
        os.makedirs(os.path.join(self.root, "graphs"))
        rows = sp.check_protected_writes(["./AGENTS.override.md", "./graphs"], self.root, self.home)
        self.assertEqual(results(rows), [sp.SKIP, sp.SKIP])

    def test_home_entry_resolves_under_home(self):
        self.write(".claude/settings.json", base=self.home)
        rows = sp.check_protected_writes(["~/.claude/settings.json"], self.root, self.home)
        self.assertEqual(results(rows), [sp.FAIL])

    @unittest.skipIf(ROOT_USER or not POSIX, "needs a user the OS can refuse")
    def test_read_only_file_passes(self):
        path = self.write("README.md")
        os.chmod(path, stat.S_IRUSR)
        rows = sp.check_protected_writes(["./README.md"], self.root, self.home)
        self.assertEqual(results(rows), [sp.PASS])

    def test_each_refusal_passes_whoever_runs_the_suite(self):
        self.write("README.md")
        for code in sp.REFUSALS:
            with mock.patch.object(sp.os, "open", side_effect=refused(code)):
                rows = sp.check_protected_writes(["./README.md"], self.root, self.home)
            self.assertEqual(results(rows), [sp.PASS], errno.errorcode[code])

    @unittest.skipIf(not POSIX, "needs a symlink")
    def test_a_dangling_link_never_passes(self):
        # Nothing refused the open: there was nothing to open. A write through
        # the link could still create its target, so this is an unknown.
        os.symlink(os.path.join(self.tmp, "gone"), os.path.join(self.root, "AGENTS.md"))
        rows = sp.check_protected_writes(["./AGENTS.md"], self.root, self.home)
        self.assertEqual(results(rows), [sp.SKIP])
        self.assertIn("ENOENT", rows[0]["detail"])
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "gone")))


class Config(unittest.TestCase):
    def cfg(self, settings, platform="darwin", have=()):
        return sp.check_config(settings, platform=platform,
                               which=lambda tool: "/usr/bin/" + tool if tool in have else None)

    def test_tight_config_passes(self):
        rows = self.cfg({"sandbox": {"enabled": True}, "permissions": {"deny": ["x"]}})
        self.assertEqual(results(rows), [sp.PASS, sp.PASS, sp.PASS])

    def test_each_loosening_fails_its_own_row(self):
        rows = self.cfg({"sandbox": {"enabled": False},
                         "permissions": {"allow": ["Bash(*)"], "defaultMode": "bypassPermissions"}})
        self.assertEqual(results(rows), [sp.FAIL, sp.FAIL, sp.FAIL])

    def test_missing_blocks_fail_only_the_sandbox_row(self):
        self.assertEqual(results(self.cfg({})), [sp.FAIL, sp.PASS, sp.PASS])

    def test_linux_adds_a_sandbox_tools_row(self):
        tight = {"sandbox": {"enabled": True}}
        rows = self.cfg(tight, platform="linux", have=("bwrap", "socat"))
        self.assertEqual((rows[0]["target"], rows[0]["result"]), ("sandbox tools", sp.PASS))
        rows = self.cfg(tight, platform="linux", have=("bwrap",))
        self.assertEqual(rows[0]["result"], sp.FAIL)
        self.assertTrue(rows[0]["detail"].startswith("missing on PATH: socat ("), rows[0]["detail"])
        self.assertEqual(len(self.cfg(tight, platform="win32")), 3)


class WholeRun(Base):
    def setUp(self):
        super().setUp()
        self.touched = []
        for name in ("open", "listdir", "remove"):
            patch = mock.patch.object(sp.os, name, self.spy(getattr(os, name)))
            patch.start()
            self.addCleanup(patch.stop)

    def spy(self, real):
        def recorded(path, *args, **kwargs):
            self.touched.append(path)
            return real(path, *args, **kwargs)
        return recorded

    def tearDown(self):
        # The guard: whatever a whole run opened, listed or removed, none of it
        # may sit under the real home folder (the test's own folders excepted).
        strays = [p for p in self.touched
                  if isinstance(p, str) and under(REAL_HOME, p) and not under(self.tmp, p)]
        self.assertEqual(strays, [], "a whole-run test touched the real home folder")

    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = sp.main(["--root", self.root, "--no-network"] + list(argv), home=self.home)
        return code, out.getvalue(), err.getvalue()

    def test_missing_settings_is_exit_2(self):
        os.remove(self.write(".claude/settings.json"))
        code, out, err = self.run_main()
        self.assertEqual(code, 2)
        self.assertIn("probe error: cannot read .claude/settings.json", err)
        self.assertEqual(out, "")

    def test_invalid_settings_is_exit_2(self):
        self.write(".claude/settings.json", "{not json")
        self.assertEqual(self.run_main()[0], 2)
        self.write(".claude/settings.json", "[]")
        code, _, err = self.run_main()
        self.assertEqual(code, 2)
        self.assertIn("is not an object", err)

    def test_settings_of_the_wrong_shape_are_exit_2_and_name_the_key(self):
        cases = [({"sandbox": "on"}, "`sandbox`"),
                 ({"sandbox": {"filesystem": {"denyRead": [1]}}}, "`sandbox.filesystem.denyRead`"),
                 ({"sandbox": {"filesystem": {"denyWrite": "./x"}}}, "`sandbox.filesystem.denyWrite`"),
                 ({"sandbox": {"network": {"allowedDomains": [None]}}}, "`sandbox.network.allowedDomains`"),
                 ({"sandbox": {"network": []}}, "`sandbox.network`"),
                 ({"permissions": {"allow": True}}, "`permissions.allow`"),
                 ({"permissions": 3}, "`permissions`")]
        for over, key in cases:
            self.settings(**over)
            code, out, err = self.run_main()
            self.assertEqual((code, out), (2, ""), key)
            self.assertIn("probe error: " + key, err)

    def test_an_unexpected_error_is_exit_2_never_1(self):
        self.settings()
        with mock.patch.object(sp, "check_config", side_effect=RuntimeError("boom")):
            code, out, err = self.run_main()
        self.assertEqual((code, out), (2, ""))
        self.assertIn("unexpected RuntimeError: boom", err)

    def test_a_row_the_terminal_cannot_show_is_escaped_and_the_exit_follows_the_rows(self):
        odd = [sp.row("key-folder-read", "~/.ss\u00e9", sp.SKIP, "absent")]
        raw = io.BytesIO()
        out = io.TextIOWrapper(raw, encoding="ascii")
        with mock.patch.object(sp, "probe", return_value=odd), redirect_stdout(out), \
                redirect_stderr(io.StringIO()):
            code = sp.main(["--root", self.root, "--no-network"], home=self.home)
        out.flush()
        self.assertEqual(code, 0)
        self.assertIn(b"~/.ss\\xe9", raw.getvalue())
        self.assertIn(b"-- 0 PASS, 0 FAIL, 1 SKIP", raw.getvalue())

    def test_output_that_cannot_be_written_is_exit_2_never_1(self):
        class Shut(io.StringIO):
            def write(self, _text):
                raise OSError(errno.EIO, "closed")
        failing = [sp.row("outside-write", "x", sp.FAIL, "d")]
        err = io.StringIO()
        with mock.patch.object(sp, "probe", return_value=failing), redirect_stdout(Shut()), \
                redirect_stderr(err):
            code = sp.main(["--root", self.root, "--no-network"], home=self.home)
        self.assertEqual(code, 2)
        self.assertIn("probe error: unexpected OSError", err.getvalue())

    def test_no_network_skips_the_row_and_sends_nothing(self):
        self.settings()

        def never(_host):
            raise AssertionError("a request was sent")
        rows = sp.probe(self.root, self.home, "t8", network=False, fetch=never)
        net = [r for r in rows if r["check"] == "network"]
        self.assertEqual(results(net), [sp.SKIP])

    def test_rows_cover_every_check_in_order(self):
        self.settings()
        self.write("CLAUDE.md")
        rows = sp.probe(self.root, self.home, "t9", network=False)
        seen = []
        for r in rows:
            if r["check"] not in seen:
                seen.append(r["check"])
        self.assertEqual(seen, ["outside-write", "key-folder-read", "network", "protected-write",
                                "config", "github-ruleset"])
        self.assertEqual((rows[-1]["check"], rows[-1]["result"]), ("github-ruleset", sp.SKIP))
        self.assertEqual(os.listdir(self.home), [])

    def test_any_fail_row_is_exit_1_and_json_carries_the_rows(self):
        self.settings()
        self.write("CLAUDE.md")
        code, out, _ = self.run_main("--json")
        data = json.loads(out)
        self.assertEqual(code, 1)
        self.assertIn(sp.FAIL, [r["result"] for r in data["rows"]])
        self.assertEqual(set(data), {"agent_shell", "platform", "rows"})
        self.assertEqual(os.listdir(self.home), [])
        self.assertTrue(any(isinstance(p, str) and under(self.home, p) for p in self.touched))

    def test_exit_0_needs_no_fail_row(self):
        clean = [sp.row("config", "x", sp.PASS, "d"), sp.row("network", "y", sp.SKIP, "d")]
        with mock.patch.object(sp, "probe", return_value=clean):
            code, out, _ = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn("-- 1 PASS, 0 FAIL, 1 SKIP", out)

    def test_render_names_a_sandbox_that_is_asked_for_but_absent(self):
        asked = sp.row("config", "sandbox.enabled", sp.PASS, "true")
        wrote = sp.row("outside-write", "~/x", sp.FAIL, "created, then removed")
        held = sp.row("outside-write", "~/x", sp.PASS, "refused (EPERM)")
        self.assertIn("not containing this shell", sp.render([wrote, asked], True))
        self.assertNotIn("not containing this shell", sp.render([held, asked], True))
        off = sp.row("config", "sandbox.enabled", sp.FAIL, "not true")
        self.assertNotIn("not containing this shell", sp.render([wrote, off], True))

    def test_render_warns_outside_an_agent_shell(self):
        rows = [sp.row("config", "x", sp.PASS, "d")]
        self.assertIn("not an agent shell", sp.render(rows, agent_shell=False))
        self.assertNotIn("not an agent shell", sp.render(rows, agent_shell=True))


if __name__ == "__main__":
    unittest.main()
