"""The shared hardened unlock consumption, driven through both
consuming hooks (net-post.py, env-global.py) as subprocesses -- the
test_policy_mutate.py:53-66 harness pattern. Each run points the hooks at a
fresh temporary root via HARNESS_ROOT and writes its own grant files there;
nothing touches the real tree.

HARNESS_HOOKS_DIR points the suite at a
COPY of the hooks, so the red run against pristine HEAD copies is possible.
Unset -- the normal case -- it resolves to this tree's live hooks.

Every string that looks like a send or an env mutation below is DATA piped
to the hook under test, never executed.
"""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOKS = Path(os.environ.get("HARNESS_HOOKS_DIR") or ROOT / ".claude" / "hooks")

# Trigger payloads. example.com / two.example.net are not loopback and not in
# net-post-config.json's allowlist (empty), so they always reach
# the consumption path.
SEND = 'curl -X POST -d @payload.json https://example.com/ingest'
SEND_TWO_HOSTS = ('curl -X POST -d @payload.json '
                  'https://example.com/a https://two.example.net/b')
SEND_SAME_HOST_TWICE = ('curl -X POST -d @payload.json '
                        'https://example.com/a https://example.com/b')
ENV_MUT = 'setx FOO bar'

DENY = '"permissionDecision": "deny"'


class HookCase(unittest.TestCase):
    """Plumbing shared by both hook subclasses. Subclasses set `hook`,
    `unlock_name`, `trigger`, and `valid_extra` (grant fields beyond
    epoch/used that make it consumable against `trigger`)."""
    hook = None
    unlock_name = None
    trigger = None
    valid_extra = {}

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="unlock-consume-"))
        (self.root / ".agent-log").mkdir()
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        f = self.unlock_file()
        try:
            if f.exists():
                os.chmod(f, stat.S_IWRITE | stat.S_IREAD)
        except OSError:
            pass
        shutil.rmtree(self.root, ignore_errors=True)

    def unlock_file(self):
        return self.root / ".agent-log" / self.unlock_name

    def write_grant(self, obj):
        """A dict is dumped; a string is written verbatim (malformed shapes)."""
        text = obj if isinstance(obj, str) else json.dumps(obj)
        self.unlock_file().write_text(text, encoding="utf-8")

    def grant(self, age=0, used=False, **extra):
        g = {"epoch": time.time() - age, "used": used}
        g.update(self.valid_extra)
        g.update(extra)
        return g

    def run_hook(self, cmd=None, hook_path=None):
        return subprocess.run(
            [sys.executable, str(hook_path or HOOKS / self.hook)],
            input=json.dumps({"tool_input": {"command": cmd or self.trigger}}),
            capture_output=True, text=True,
            env=dict(os.environ, HARNESS_ROOT=str(self.root)))

    def attempt(self, cmd=None, hook_path=None):
        """True if the gate allowed the act. Asserts a clean exit first: a
        PreToolUse hook exiting non-zero (other than 2) is NON-blocking, so a
        traceback here is precisely the fail-open under test."""
        r = self.run_hook(cmd, hook_path)
        self.assertEqual(r.returncode, 0,
                         "hook crashed -- and a crash is a FAIL-OPEN:\n"
                         + r.stderr)
        return DENY not in r.stdout

    def grant_on_disk(self):
        return json.loads(self.unlock_file().read_text(encoding="utf-8"))

    def hooks_dir_without_shared_module(self):
        """A copy of just the hook under test: HERE resolves there, so
        unlock_consume.py is absent and the import must fail closed."""
        hd = self.root / "hooks-copy"
        hd.mkdir()
        shutil.copy(str(HOOKS / self.hook), str(hd / self.hook))
        return hd / self.hook


class ConsumeContract(object):
    """The hardened semantics, identical for every consumer (earlier fixes
    ported from policy-mutate; the shapes are the ones probed 2026-08-24)."""

    def test_a_truthy_non_dict_grant_denies_cleanly(self):
        # 64's class. Valid JSON, wrong shape: pristine hooks raise
        # AttributeError on u.get(), exit 1, and the act PROCEEDS.
        for shape in ("[1, 2]", '"x"', "42"):
            with self.subTest(shape=shape):
                self.write_grant(shape)
                self.assertFalse(self.attempt(),
                                 "a %s grant was not refused" % shape)

    def test_a_future_grant_is_refused(self):
        # 69. Negative age passed the old upper-bound-only check forever.
        self.write_grant(self.grant(age=-36000))
        self.assertFalse(self.attempt(),
                         "a grant stamped ten hours ahead was spent")

    def test_an_expired_grant_is_refused_and_says_expired(self):
        # An aged-out grant read exactly like no grant. It must still be
        # refused (attempt() asserts the clean exit), and now say why.
        self.write_grant(self.grant(age=1800 + 600))
        self.assertFalse(self.attempt(), "an expired grant was spent")
        self.assertIn("EXPIRED 10 min ago", self.run_hook().stdout)

    def test_no_grant_gets_no_stale_clause(self):
        self.assertFalse(self.attempt())
        self.assertNotIn("EXPIRED", self.run_hook().stdout)

    def test_a_small_clock_skew_still_passes(self):
        # Lockout guard: the spec body's -60s slack (policy-mutate.py:214,
        # asserted elsewhere). Tighter would refuse real grants.
        self.write_grant(self.grant(age=-30))
        self.assertTrue(self.attempt(),
                        "a grant 30s ahead was refused; the lower bound is "
                        "tighter than the spec's slack")

    def test_a_junk_epoch_is_refused_without_raising(self):
        # 69's regressive-draft lesson: refuse, never arithmetic on it.
        self.write_grant(self.grant(epoch="soon"))
        self.assertFalse(self.attempt(),
                         "a grant with a non-numeric epoch was not refused")

    def test_a_null_epoch_is_refused(self):
        self.write_grant(self.grant(epoch=None))
        self.assertFalse(self.attempt(), "a grant with no stamp was spent")

    def test_an_expired_grant_is_refused(self):
        self.write_grant(self.grant(age=1801))
        self.assertFalse(self.attempt(), "the upper bound was lost")

    def test_a_spent_grant_is_refused(self):
        self.write_grant(self.grant(used=True))
        self.assertFalse(self.attempt(), "a spent one-shot was re-spent")

    def test_a_fresh_grant_is_consumed_exactly_once(self):
        self.write_grant(self.grant())
        self.assertTrue(self.attempt(), "the operator's own grant was refused")
        self.assertTrue(self.grant_on_disk()["used"],
                        "the grant was honoured but never marked spent")
        self.assertFalse(self.attempt(),
                         "the one-shot was consumable a second time")

    @unittest.skipUnless(sys.platform == "win32",
                         "open-handle rename blocker is Windows-only")
    def test_an_unwritable_spend_still_denies(self):
        # 65. If the spend cannot be persisted the one-shot stays re-usable,
        # so the act must be DENIED. Pristine hooks crash (exit 1) here and
        # the act proceeds with the grant unspent -- the worst of both.

        # Mechanism updated 2026-09-01 for the item-167 rename-based spend.
        # The old blocker -- chmod S_IREAD on the grant file --
        # no longer blocks persistence: Windows lets os.replace move a
        # read-only file (measured; that run spends the grant CORRECTLY, so it
        # is a pass of 65's invariant, not a breach). What still denies the
        # persist is an open handle in another process: the claim rename fails
        # WinError 32 (measured), consume() refuses, the grant stays armed.
        # The invariant under test is unchanged: failed persist = deny.
        self.write_grant(self.grant())
        with open(self.unlock_file(), encoding="utf-8"):
            self.assertFalse(self.attempt(),
                             "the act passed although the spend could not be persisted")
        self.assertFalse(self.grant_on_disk()["used"],
                         "the spend was persisted despite the blocked claim")

    def test_a_missing_shared_module_fails_closed(self):
        # The import guard sits at the call site. With
        # unlock_consume.py absent the unlock is treated as absent -- a valid
        # grant must NOT be spendable, and the grant stays untouched.
        hook = self.hooks_dir_without_shared_module()
        self.write_grant(self.grant())
        self.assertFalse(self.attempt(hook_path=hook),
                         "the hook honoured a grant it had no way to verify")
        self.assertFalse(self.grant_on_disk()["used"],
                         "a hook with no consumption module spent the grant")


class NetPostConsume(ConsumeContract, HookCase):
    hook = "net-post.py"
    unlock_name = "net-unlock.json"
    trigger = SEND
    valid_extra = {"host": "example.com"}

    def test_a_mismatched_host_grant_is_refused(self):
        self.write_grant(self.grant(host="other.com"))
        self.assertFalse(self.attempt(),
                         "a grant for one host unlocked a send to another")

    def test_two_different_hosts_cannot_be_unlocked(self):
        # The single-host rule the deny message documents: every matched host
        # must equal the one granted host.
        self.write_grant(self.grant())
        self.assertFalse(self.attempt(cmd=SEND_TWO_HOSTS),
                         "a single-host grant covered a two-host send")

    def test_the_same_host_twice_still_consumes(self):
        # Lockout guard: two URLs on the granted host are one destination.
        self.write_grant(self.grant())
        self.assertTrue(self.attempt(cmd=SEND_SAME_HOST_TWICE),
                        "a repeated granted host was refused")

    def test_a_grant_missing_its_host_is_refused(self):
        g = self.grant()
        del g["host"]
        self.write_grant(g)
        self.assertFalse(self.attempt(), "a hostless grant unlocked a send")

    def test_a_non_string_host_is_refused_without_raising(self):
        # The fourth pristine shape, surfaced by this build: a truthy
        # non-string host made u["host"].lower() raise -> exit 1 -> fail-open.
        self.write_grant(self.grant(host=5))
        self.assertFalse(self.attempt(),
                         "a grant with a numeric host was not refused")

    def test_the_deny_names_a_load_failure(self):
        # net-post only: env-global's note was classifier-blocked mid-build
        # and ruled cosmetic/out of scope (its fail-closed behaviour is the
        # shared test above; only the wording differs).
        hook = self.hooks_dir_without_shared_module()
        self.write_grant(self.grant())
        r = self.run_hook(hook_path=hook)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(DENY, r.stdout)
        self.assertIn("unlock_consume", r.stdout,
                      "the deny hides that no unlock can consume this session")


class EnvGlobalConsume(ConsumeContract, HookCase):
    hook = "env-global.py"
    unlock_name = "env-unlock.json"
    trigger = ENV_MUT
    valid_extra = {}


class WindowCheckNeverSpends(unittest.TestCase):
    """Browser-loopback called consume(spend=False, max_age=300) on
    the browse window. The same refusals as a one-shot; no claim, no rename,
    no `used` flip -- a window was held for its lifetime, then removed by
    policy-prompt. Direct unit of the module, not of a hook. No caller since
    2026-09-21, and the closer went with it: a spend=False grant
    now lives until max_age. The parameter stays, so this still pins it."""

    def setUp(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("uc", HOOKS / "unlock_consume.py")
        self.uc = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.uc)
        self.root = Path(tempfile.mkdtemp(prefix="unlock-window-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.path = self.root / "browse-unlock-s.json"

    def put(self, obj):
        text = obj if isinstance(obj, str) else json.dumps(obj)
        self.path.write_text(text, encoding="utf-8")
        return text

    def test_a_fresh_window_is_returned_and_left_untouched(self):
        before = self.put({"epoch": time.time(), "used": False})
        for _ in range(3):
            self.assertIsNotNone(self.uc.consume(str(self.path), spend=False, max_age=300))
        self.assertEqual(self.path.read_text(encoding="utf-8"), before,
                         "the window check mutated the grant")
        self.assertEqual([p.name for p in self.root.iterdir()], [self.path.name],
                         "the window check left a claim/spent sibling behind")

    def test_the_window_refuses_what_a_one_shot_refuses(self):
        for bad in [{"epoch": time.time() - 301, "used": False},
                    {"epoch": time.time() + 120, "used": False},
                    {"epoch": time.time(), "used": True},
                    {"epoch": "x", "used": False}, [1], "junk"]:
            self.put(bad)
            self.assertIsNone(self.uc.consume(str(self.path), spend=False, max_age=300), bad)

    def test_max_age_is_the_callers_bound_not_the_default(self):
        self.put({"epoch": time.time() - 301, "used": False})
        self.assertIsNone(self.uc.consume(str(self.path), spend=False, max_age=300))
        self.assertIsNotNone(self.uc.consume(str(self.path), spend=False))

    def test_spend_true_is_unchanged(self):
        self.put({"epoch": time.time(), "used": False})
        self.assertIsNotNone(self.uc.consume(str(self.path)))
        self.assertTrue(json.loads(self.path.read_text(encoding="utf-8"))["used"])
        self.assertIsNone(self.uc.consume(str(self.path)))


class StaleNote(unittest.TestCase):
    """Stale_note() explains a refusal after the fact. It is
    advisory, runs only once consume() has refused, and must never raise."""

    def setUp(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("uc", HOOKS / "unlock_consume.py")
        self.uc = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.uc)
        self.root = Path(tempfile.mkdtemp(prefix="unlock-stale-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.path = self.root / "unlock.json"

    def note(self, obj=None, **kw):
        if obj is not None:
            self.path.write_text(obj if isinstance(obj, str) else json.dumps(obj),
                                 encoding="utf-8")
        return self.uc.stale_note(str(self.path), **kw)

    def test_expired_is_named_and_consume_is_unchanged(self):
        g = {"epoch": time.time() - 1800 - 125, "used": False}
        self.assertIn("EXPIRED 2 min ago", self.note(g))
        self.assertIsNone(self.uc.consume(str(self.path)))   # behaviour unchanged

    def test_window_bound_is_the_callers(self):
        self.assertIn("grants last 5 min",
                      self.note({"epoch": time.time() - 400, "used": False}, max_age=300))

    def test_each_shape(self):
        self.assertEqual(self.note(), "")                        # absent
        self.assertIn("malformed", self.note("[1, 2]"))
        self.assertIn("malformed", self.note({"epoch": "x"}))
        self.assertIn("already spent", self.note({"epoch": time.time(), "used": True}))
        self.assertIn("future", self.note({"epoch": time.time() + 3600, "used": False}))
        self.assertEqual(self.note({"epoch": time.time(), "used": False}), "")

    def test_never_raises(self):
        for epoch in (float("inf"), float("-inf"), float("nan"), 10 ** 400):
            with self.subTest(epoch=epoch):
                self.path.write_text('{"epoch": %s, "used": false}' % (
                    "1e999" if epoch == float("inf") else "-1e999" if epoch == float("-inf")
                    else "NaN" if epoch != epoch else str(epoch)), encoding="utf-8")
                self.assertIsInstance(self.uc.stale_note(str(self.path)), str)

    def test_consume_refuses_an_epoch_too_big_for_a_float(self):
        # 365 review Q1: `time.time() - 10**400` raises OverflowError, and a
        # raise in a PreToolUse hook is a fail-OPEN. Refuse, never arithmetic.
        self.path.write_text('{"epoch": %d, "used": false}' % 10 ** 400, encoding="utf-8")
        self.assertIsNone(self.uc.consume(str(self.path)))

    def test_consume_refuses_a_negative_epoch_too_big_for_a_float(self):
        # 365 review F4: the LOWER half of the bound at unlock_consume.py:92.
        # test_never_raises' -1e999 parses to float -inf and fails `< max_age`
        # on its own, so nothing above decides that conjunct. -10**400 does:
        # drop `-1e12 <` and `time.time() - epoch` at :95 raises OverflowError,
        # which in a PreToolUse hook is rc 1 -- a fail-OPEN.
        self.path.write_text('{"epoch": %d, "used": false}' % -10 ** 400, encoding="utf-8")
        self.assertIsNone(self.uc.consume(str(self.path)))


if __name__ == "__main__":
    unittest.main(verbosity=1)
