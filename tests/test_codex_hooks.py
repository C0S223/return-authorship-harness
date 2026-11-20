"""Executable transport proofs, not live Codex activation.

Each fixture copies the candidate into an isolated in-tree checkout, sets a real
Git default ref, and sends documented JSON envelopes directly to the dispatcher.
The client trust/runtime itself is deliberately not simulated or called proven.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


class CodexHooks(unittest.TestCase):
    def setUp(self):
        self.assertTrue((ROOT / '.codex/hooks/dispatch.py').is_file(),
                        'baseline lacks the Codex transport')
        (ROOT / 'tmp').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='codex-proof-', dir=ROOT / 'tmp')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ('.claude/hooks', '.codex'):
            shutil.copytree(ROOT / name, self.root / name, ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copy2(ROOT / '.claude/settings.json', self.root / '.claude/settings.json')
        (self.root / 'CLAUDE.md').write_text('fixture contract\n')
        (self.root / '.gitignore').write_text('.agent-log/\n')
        self.git('init', '-b', 'main')
        self.git('add', 'CLAUDE.md')
        self.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@invalid',
                 'commit', '-m', 'fixture')
        self.git('update-ref', 'refs/remotes/origin/main', 'HEAD')
        self.git('symbolic-ref', 'refs/remotes/origin/HEAD', 'refs/remotes/origin/main')
        self.script = self.root / '.codex/hooks/dispatch.py'
        self.sid = 'fixture-session'

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.root), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def envelope(self, event='PreToolUse', **values):
        return dict({'hook_event_name': event, 'session_id': self.sid,
                     'cwd': str(self.root)}, **values)

    def invoke(self, data):
        proc = subprocess.run([sys.executable, str(self.script)], input=json.dumps(data),
                              capture_output=True, text=True, cwd=self.root, timeout=15)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout) if proc.stdout.strip() else {}

    def pre(self, name='Bash', args=None, sid=None):
        data = self.envelope(tool_name=name, tool_input=args or {'command': 'pwd'})
        if sid is not None:
            data['session_id'] = sid
        return self.invoke(data)

    def prompt(self, text, **kwargs):
        return self.invoke(self.envelope('UserPromptSubmit', prompt=text, **kwargs))

    def decision(self, output):
        return output.get('hookSpecificOutput', {}).get('permissionDecision', 'allow')

    def denied(self, output):
        self.assertEqual(self.decision(output), 'deny', output)
        return output['hookSpecificOutput']['permissionDecisionReason']

    def allowed(self, output):
        self.assertEqual(self.decision(output), 'allow', output)

    def patch(self, path, body='value'):
        return {'command': '*** Begin Patch\n*** Add File: %s\n+%s\n*** End Patch' % (path, body)}

    def test_shared_shell_decisions_and_ask_translation(self):
        cases = [('git-guard', 'git push --force origin topic'),
                 ('git-guard', 'git push origin main'),
                 ('git-guard', 'git remote add other https://example.invalid/repo'),
                 ('env-global', 'npm install -g package'),
                 ('net-post', 'curl -X POST https://example.invalid'),
                 ('shell-scope', 'printf x > /outside-codex-proof.txt')]
        for guard, command in cases:
            with self.subTest(guard=guard, command=command):
                data = self.envelope(tool_name='Bash', tool_input={'command': command})
                env = dict(os.environ, HARNESS_ROOT=str(self.root), CLAUDE_PROJECT_DIR=str(self.root))
                env.pop('CLAUDE_CODE_REMOTE', None); env.pop('HARNESS_BOUNDARY', None)
                proc = subprocess.run([sys.executable, str(self.root / '.claude/hooks' / (guard + '.py'))],
                                      input=json.dumps(data), text=True, capture_output=True, env=env)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                original = json.loads(proc.stdout)['hookSpecificOutput']['permissionDecision']
                self.assertIn(original, ('deny', 'ask'))
                reason = self.denied(self.invoke(data))
                if original == 'ask':
                    self.assertIn('cannot translate ask', reason)
        self.allowed(self.pre(args={'command': 'git status --short'}))

    def test_deny_precedes_effect_in_caller_harness(self):
        target = self.root / 'CLAUDE.md'
        command = 'printf corrupted > CLAUDE.md'
        answer = self.pre(args={'command': command})
        if self.decision(answer) == 'allow':
            subprocess.run(command, shell=True, cwd=self.root, check=True)
        self.denied(answer)
        self.assertEqual(target.read_text(), 'fixture contract\n')

    def test_policy_grant_revoke_replacement_and_session_isolation(self):
        args = self.patch('CLAUDE.md')
        self.denied(self.pre('apply_patch', args))
        self.prompt('auth-policy CLAUDE.md')
        self.allowed(self.pre('apply_patch', args))
        self.allowed(self.pre('apply_patch', args))
        self.denied(self.pre('apply_patch', args, sid='another-session'))
        self.prompt('auth-policy .codex/config.toml')
        self.denied(self.pre('apply_patch', args))
        self.prompt('auth-policy CLAUDE.md')
        self.prompt('revoke-policy')
        self.denied(self.pre('apply_patch', args))

    def test_policy_batch_and_no_prompt_injection(self):
        self.prompt('Please do not run auth-policy CLAUDE.md')
        self.denied(self.pre('apply_patch', self.patch('CLAUDE.md')))
        self.prompt('auth-policy CLAUDE.md', source='sdk')
        self.denied(self.pre('apply_patch', self.patch('CLAUDE.md')))
        self.prompt('auth-policy-batch CLAUDE.md .codex/config.toml')
        self.allowed(self.pre('apply_patch', self.patch('CLAUDE.md')))
        self.allowed(self.pre('apply_patch', self.patch('.codex/config.toml')))

    def test_session_identity_has_no_scrubbing_collisions(self):
        self.sid = 'a/b'
        self.prompt('auth-policy CLAUDE.md')
        self.denied(self.pre('apply_patch', self.patch('CLAUDE.md'), sid='ab'))

    def test_expired_and_malformed_grants_fail_closed(self):
        self.prompt('auth-policy CLAUDE.md')
        state = next((self.root / '.agent-log').glob('policy-unlock-*.json'))
        original = json.loads(state.read_text())
        original['epoch'] = time.time() - 29000
        state.write_text(json.dumps(original))
        self.denied(self.pre('apply_patch', self.patch('CLAUDE.md')))
        state.write_text('[1,2,3]')
        self.denied(self.pre('apply_patch', self.patch('CLAUDE.md')))

    def test_net_and_env_grants_are_one_shot_and_session_scoped(self):
        for token, command in [('auth-net example.invalid', 'curl -X POST https://example.invalid'),
                               ('auth-env', 'npm install -g package')]:
            with self.subTest(token=token):
                self.denied(self.pre(args={'command': command}))
                self.prompt(token)
                self.denied(self.pre(args={'command': command}, sid='other'))
                self.allowed(self.pre(args={'command': command}))
                self.denied(self.pre(args={'command': command}))
                self.prompt(token)
                self.prompt('revoke-net' if token.startswith('auth-net') else 'revoke-env')
                self.denied(self.pre(args={'command': command}))

    def test_patch_targets_are_complete_and_scope_is_checked(self):
        self.allowed(self.pre('apply_patch', self.patch('notes.txt')))
        for command in [
                '*** Begin Patch\n*** Update File: notes.txt\n*** Move to: CLAUDE.md\n@@\n-old\n+new\n*** End Patch',
                '*** Begin Patch\n*** Add File: notes.txt\n+x\n*** Add File: CLAUDE.md\n+x\n*** End Patch']:
            self.denied(self.pre('apply_patch', {'command': command}))
        self.denied(self.pre('apply_patch', self.patch('../outside.txt')))
        self.denied(self.pre('apply_patch', self.patch('.agents/skills/new/SKILL.md')))
        # Last, and alone in its subTest: where Windows refuses symlinks
        # (WinError 1314, Developer Mode off) only this check skips.
        with self.subTest('a symlink out of the root'):
            try:
                (self.root / 'link').symlink_to(self.root.parent, target_is_directory=True)
            except OSError as exc:
                self.skipTest('cannot create symlinks here: %s' % exc)
            self.denied(self.pre('apply_patch', self.patch('link/outside.txt')))

    def test_patch_headers_inside_content_are_data(self):
        self.allowed(self.pre('apply_patch', self.patch('notes.txt', '*** Update File: CLAUDE.md')))

    def test_malformed_patch_never_passes(self):
        for command in ['', '*** Begin Patch\n*** End Patch',
                        '*** Begin Patch\n*** Update File: notes.txt\n@@\n*** End Patch',
                        '*** Begin Patch\n*** Add File: notes.txt\nx\n*** End Patch',
                        '*** Begin Patch\n*** Delete File: notes.txt\n*** End Patch',
                        '*** Begin Patch\n*** Add File: notes.txt\n+x\n*** End Patch\ntrailer',
                        '*** Begin Patch\n*** Add File: notes.txt\n+x\n*** Add File: notes.txt\n+y\n*** End Patch']:
            with self.subTest(command=command):
                self.denied(self.pre('apply_patch', {'command': command}))

    def test_roster_uses_native_agent_type_and_existing_binding(self):
        for args in ({}, {'subagent_type': 'recall'}, {'agent_type': 'default'}, {'agent_type': 'worker'}):
            self.denied(self.pre('spawn_agent', args))
        self.allowed(self.pre('spawn_agent', {'agent_type': 'recall', 'message': 'Read only'}))
        self.allowed(self.pre('Agent', {'agent_type': 'senior-engineer', 'message': 'Review'}))
        (self.root / '.codex/agents/recall.toml').write_text('name = "wrong"\n')
        self.denied(self.pre('spawn_agent', {'agent_type': 'recall', 'message': 'Read'}))

    def test_native_agent_followup_requires_exact_one_shot_user_approval(self):
        args = {'id': 'child-123', 'message': 'Review the bounded repair.', 'interrupt': False}
        reason = self.denied(self.pre('send_input', args))
        digest = reason.rsplit('auth-agent ', 1)[1]
        self.assertEqual(len(digest), 64)
        self.prompt('auth-agent ' + digest, source='sdk')
        self.denied(self.pre('send_input', args))
        self.prompt('auth-agent ' + digest)
        self.denied(self.pre('send_input', args, sid='other'))
        self.denied(self.pre('send_input', dict(args, message='Different scope')))
        self.allowed(self.pre('send_input', args))
        self.denied(self.pre('send_input', args))
        self.prompt('auth-agent ' + digest)
        self.prompt('revoke-agent')
        self.denied(self.pre('send_input', args))
        for tool in ('resume_agent', 'close_agent'):
            reason = self.denied(self.pre(tool, {'id': 'child-123'}))
            self.prompt('auth-agent ' + reason.rsplit('auth-agent ', 1)[1])
            self.allowed(self.pre(tool, {'id': 'child-123'}))
        self.allowed(self.pre('wait', {'ids': ['child-123']}))
        self.denied(self.pre('send_input', dict(args, unknown='mutation')))

    def test_advisory_is_preserved_without_inventing_a_deny(self):
        result = self.pre(args={'command': 'pip install package'})
        self.allowed(result)
        self.assertIn('advisory only', result['hookSpecificOutput']['additionalContext'])

    def test_unknown_mutation_and_interactive_channels_refuse(self):
        for tool, args in [('write_stdin', {'session_id': 1, 'chars': 'touch x'}),
                           ('exec_command', {'cmd': 'pwd'}),
                           ('Bash', {'command': 'sh', 'tty': True}),
                           ('functions.exec', {'code': 'tools.exec_command(...)'}),
                           ('mcp__unknown__write', {'path': 'CLAUDE.md'}),
                           ('CronCreate', {'prompt': 'later'}),
                           ('SuggestPluginInstall', {'name': 'x'}),
                           ('Bash', {'cmd': 'pwd'}),
                           ('Bash', {'command': 'pwd', 'script': 'unknown mutation'}),
                           ('apply_patch', {'command': '*** Begin Patch\n*** Add File: a\n+x\n*** End Patch', 'extra': True})]:
            self.denied(self.pre(tool, args))

    def test_malformed_envelopes_and_missing_guard_fail_closed(self):
        for data in ([], {}, self.envelope(tool_name='Bash', tool_input='pwd'),
                     dict(self.envelope(tool_name='Bash', tool_input={'command': 'pwd'}), session_id='')):
            self.denied(self.invoke(data))
        (self.root / '.claude/hooks/git-guard.py').write_text('raise RuntimeError("broken fixture")\n')
        self.denied(self.pre())

    def test_unknown_guard_decision_and_crash_fail_closed(self):
        (self.root / '.claude/hooks/git-guard.py').write_text('def main():\n print(\'{"hookSpecificOutput":{"permissionDecision":"surprise"}}\')\n')
        self.denied(self.pre())

    def test_grant_state_is_sealed_even_with_policy_grant(self):
        target = '.agent-log/net-unlock-codex-anything.json'
        self.prompt('auth-policy ' + target)
        self.denied(self.pre('apply_patch', self.patch(target)))

    def test_integrity_audit_and_resume_do_not_launder_changes(self):
        for source in ('startup', 'clear', 'fork'):
            self.invoke(self.envelope('SessionStart', source=source))
        (self.root / 'CLAUDE.md').write_text('ungranted change\n')
        response = self.invoke(self.envelope('SessionStart', source='resume'))
        self.assertIn('UNGRANTED', json.dumps(response))
        self.prompt('auth-policy CLAUDE.md')
        self.allowed(self.pre('apply_patch', self.patch('CLAUDE.md')))
        (self.root / 'CLAUDE.md').write_text('granted change\n')
        self.invoke(self.envelope('PostToolUse', tool_name='apply_patch', tool_input=self.patch('CLAUDE.md')))
        self.invoke(self.envelope('Stop'))
        log = ''.join(p.read_text() for p in (self.root / '.agent-log').glob('*.md'))
        self.assertIn('UNGRANTED CHANGED CLAUDE.md', log)
        self.assertIn('granted CHANGED CLAUDE.md', log)
        self.assertIn('[codex] allow', log)
        self.assertIn('[codex] stop', log)
        self.assertNotIn('granted change', log)

    def test_native_review_header_reuses_git_pin_and_refuses_dirty_tree(self):
        for relative in ('scripts/codex_review_order.py', 'scripts/test_graph_pointers.py',
                         '.claude/skills/review-order/review_order.py',
                         '.claude/skills/cite-check/cite_check.py'):
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, target)
        (self.root / '.gitignore').write_text('.agent-log/\n.claude/\n.codex/\nscripts/\n')
        self.git('add', '.gitignore')
        self.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@invalid', 'commit', '-m', 'ignore fixtures')
        command = [sys.executable, str(self.root / 'scripts/codex_review_order.py'),
                   'senior-engineer', str(self.root)]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(self.git('rev-parse', 'HEAD'), result.stdout)
        self.assertIn('parent sandbox/approvals/MCP inherited', result.stdout)
        self.assertNotIn('NO Bash', result.stdout)
        self.assertIn('AUTHOR CHECK', result.stdout)
        (self.root / 'CLAUDE.md').write_text('dirty fixture')
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('dirty', result.stderr)

    # Compaction ends grants.
    # Adapter proofs only: the client's own compaction behaviour is unprobed.
    NET = ('auth-net example.invalid', {'command': 'curl -X POST https://example.invalid'})
    ENV = ('auth-env', {'command': 'npm install -g package'})
    AGENT_ARGS = {'id': 'child-123', 'message': 'Review the bounded repair.', 'interrupt': False}

    def log(self):
        return ''.join(p.read_text() for p in sorted((self.root / '.agent-log').glob('*.md')))

    def grant_file(self, stem, sid=None):
        hashed = 'codex-' + hashlib.sha256((sid or self.sid).encode()).hexdigest()
        return self.root / '.agent-log' / ('%s-unlock-%s.json' % (stem, hashed))

    def compact(self, sid=None):
        data = self.envelope('SessionStart', source='compact')
        if sid is not None:
            data['session_id'] = sid
        return self.invoke(data)

    def precompact(self, sid=None, trigger='manual'):
        data = self.envelope('PreCompact', trigger=trigger, turn_id='t1')
        if sid is not None:
            data['session_id'] = sid
        proc = subprocess.run([sys.executable, str(self.script)], input=json.dumps(data),
                              capture_output=True, text=True, cwd=self.root, timeout=15)
        return proc

    def arm_agent(self):
        reason = self.denied(self.pre('send_input', self.AGENT_ARGS))
        self.prompt('auth-agent ' + reason.rsplit('auth-agent ', 1)[1])

    def arm_all(self, sid=None):
        old, self.sid = self.sid, sid or self.sid
        try:
            self.prompt('auth-policy CLAUDE.md')
            self.prompt(self.NET[0])
            self.prompt(self.ENV[0])
            self.arm_agent()
        finally:
            self.sid = old

    def assert_all_refused(self, sid=None):
        self.denied(self.pre('apply_patch', self.patch('CLAUDE.md'), sid=sid))
        self.denied(self.pre(args=self.NET[1], sid=sid))
        self.denied(self.pre(args=self.ENV[1], sid=sid))
        self.denied(self.pre('send_input', self.AGENT_ARGS, sid=sid))

    def lock_grants(self):
        """(f1) shape: unlink and overwrite fail, appending to the day log works."""
        if os.geteuid() == 0:
            self.skipTest('running as root: chmod does not bind, so revocation failure cannot be staged')
        logdir = self.root / '.agent-log'
        day = logdir / (time.strftime('%Y-%m-%d') + '.md')
        day.touch()
        os.chmod(day, 0o600)
        files = [p for p in logdir.iterdir() if p.name.endswith('.json')]
        for p in files:
            os.chmod(p, 0o400)
        os.chmod(logdir, 0o500)
        def restore():
            os.chmod(logdir, 0o700)
            for p in files:
                os.chmod(p, 0o600)
        self.addCleanup(restore)
        return restore

    def test_compact_revokes_this_sessions_policy_grant(self):          # (a)
        self.prompt('auth-policy CLAUDE.md')
        self.allowed(self.pre('apply_patch', self.patch('CLAUDE.md')))
        self.compact()
        self.assertFalse(self.grant_file('policy').exists())
        hashed = self.grant_file('policy').name[len('policy-unlock-'):-len('.json')]
        self.assertRegex(self.log(), r'unlock-revoked \(policy\): 1 path\(s\) sid=' + hashed)
        self.assertIn('unlock-revoked sid=%s policy compaction' % hashed, self.log())
        self.denied(self.pre('apply_patch', self.patch('CLAUDE.md')))

    def test_compact_leaves_other_sessions_grants(self):                # (b)
        self.arm_all(sid='session-b')
        self.compact()
        self.allowed(self.pre('apply_patch', self.patch('CLAUDE.md'), sid='session-b'))
        self.allowed(self.pre(args=self.NET[1], sid='session-b'))

    def test_other_session_start_sources_leave_grants(self):            # (c)
        self.prompt('auth-policy CLAUDE.md')
        for source in ('startup', 'resume', 'clear', 'fork'):
            with self.subTest(source=source):
                self.invoke(self.envelope('SessionStart', source=source))
                self.allowed(self.pre('apply_patch', self.patch('CLAUDE.md')))
        self.assertNotIn('unlock-revoked', self.log())

    def test_compact_spends_net_env_and_agent_grants(self):             # (d)
        self.arm_all()
        self.compact()
        for stem in ('net', 'env', 'agent'):
            self.assertEqual(json.loads(self.grant_file(stem).read_text()), {'used': True}, stem)
        self.assert_all_refused()

    def test_compact_without_grants_writes_no_revoke_line(self):        # (e)
        self.compact()
        self.assertIn('startup sid=', self.log())
        self.assertNotIn('unlock-revoke', self.log())

    def test_failed_revoke_is_still_refused_at_use(self):               # (f1)
        self.prompt('auth-policy CLAUDE.md')
        self.lock_grants()
        proc = subprocess.run([sys.executable, str(self.script)],
                              input=json.dumps(self.envelope('SessionStart', source='compact')),
                              capture_output=True, text=True, cwd=self.root, timeout=15)
        self.assertIn('unlock-revoke-failed', self.log())
        self.assertRegex(self.log(), r'\[codex\] startup sid=\S+ compact epoch:\d+\.\d+\n')
        self.assertTrue(self.grant_file('policy').exists(), 'fixture failed to stage a failed unlink')
        self.assertIn('revoke-policy', proc.stdout + proc.stderr)
        self.denied(self.pre('apply_patch', self.patch('CLAUDE.md')))

    def test_no_revival_after_permissions_recover(self):                # (f2)
        self.prompt('auth-policy CLAUDE.md')
        restore = self.lock_grants()
        subprocess.run([sys.executable, str(self.script)],
                       input=json.dumps(self.envelope('SessionStart', source='compact')),
                       capture_output=True, text=True, cwd=self.root, timeout=15)
        restore()
        grant = json.loads(self.grant_file('policy').read_text())
        self.assertFalse(grant.get('used'), 'old grant must be intact for this proof')
        self.denied(self.pre('apply_patch', self.patch('CLAUDE.md')))
        time.sleep(1.1)   # a grant armed in the compaction's own second counts as before it
        self.prompt('auth-policy CLAUDE.md')
        self.allowed(self.pre('apply_patch', self.patch('CLAUDE.md')))

    def test_failed_revoke_of_net_env_agent_stays_refused(self):        # (f3)
        self.arm_all()
        restore = self.lock_grants()
        subprocess.run([sys.executable, str(self.script)],
                       input=json.dumps(self.envelope('SessionStart', source='compact')),
                       capture_output=True, text=True, cwd=self.root, timeout=15)
        for stem in ('net', 'env', 'agent'):
            self.assertIn('unlock-revoke-failed sid=', self.log())
            self.assertFalse(json.loads(self.grant_file(stem).read_text()).get('used'), stem)
        self.assert_all_refused()
        restore()
        self.assert_all_refused()

    def test_missing_compact_source_is_still_refused(self):             # (g)
        proc = subprocess.run([sys.executable, str(self.script)],
                              input=json.dumps(self.envelope('SessionStart')),
                              capture_output=True, text=True, cwd=self.root, timeout=15)
        self.assertEqual(proc.returncode, 2)
        self.assertIn('unknown session-start source', proc.stderr)

    def test_precompact_revokes_and_does_not_block(self):               # (h1)
        self.arm_all()
        self.arm_all(sid='session-b')
        proc = self.precompact()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn('"continue"', proc.stdout)
        self.assertFalse(self.grant_file('policy').exists())
        for stem in ('net', 'env', 'agent'):
            self.assertEqual(json.loads(self.grant_file(stem).read_text()), {'used': True}, stem)
            self.assertIn('%s pre-compact' % stem, self.log())
        self.assert_all_refused()
        self.assertTrue(self.grant_file('policy', 'session-b').exists())
        self.allowed(self.pre('apply_patch', self.patch('CLAUDE.md'), sid='session-b'))

    def test_precompact_refuses_when_revocation_fails(self):            # (h2)
        self.prompt('auth-policy CLAUDE.md')
        self.lock_grants()
        proc = self.precompact()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)['continue'], False)
        self.assertIn('compaction refused', json.loads(proc.stdout)['stopReason'])

    def test_precompact_refuses_when_only_the_tombstone_fails(self):    # (h2, integrity healthy)
        # Under (f1) permissions policy-integrity itself fails first; this
        # case reaches the revocation step with integrity working.
        if os.geteuid() == 0:
            self.skipTest('running as root: chmod does not bind')
        self.prompt(self.NET[0])
        os.chmod(self.grant_file('net'), 0o400)
        self.addCleanup(os.chmod, self.grant_file('net'), 0o600)
        proc = self.precompact()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)['continue'], False)
        self.assertIn('unlock-revoke-failed sid=', self.log())
        self.assertIn('[codex] precompact sid=', self.log())

    def test_precompact_unexpected_exception_refuses(self):             # (h3)
        self.prompt('auth-policy CLAUDE.md')
        (self.root / '.claude/hooks/policy-integrity.py').write_text('raise RuntimeError("injected")\n')
        proc = self.precompact(trigger='auto')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout), {'continue': False, 'stopReason':
                         'codex-harness: grant revocation could not be recorded; compaction refused'})

    def test_precompact_without_grants_only_audits(self):               # (h4)
        proc = self.precompact()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), '')
        self.assertRegex(self.log(), r'\[codex\] precompact sid=\S+ manual')
        self.assertNotIn('unlock-revoke', self.log())

    # Repair round 1: the cutoff comes from the record's epoch, not wall-clock text.
    def dispatcher(self):
        """The candidate dispatcher imported in-process, with env and TZ restored."""
        saved_env = dict(os.environ)
        def restore():
            os.environ.clear(); os.environ.update(saved_env)
            if hasattr(time, 'tzset'):
                time.tzset()
        self.addCleanup(restore)
        spec = importlib.util.spec_from_file_location('codex_dispatch_fixture', self.script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def tz(self, name):
        if not hasattr(time, 'tzset'):
            self.skipTest('time.tzset is unavailable on this platform')
        os.environ['TZ'] = name
        time.tzset()

    def at(self, module, epoch, tz=None):
        if tz is not None:
            self.tz(tz)
        return mock.patch.object(module.time, 'time', return_value=epoch)

    def write_grant(self, module, stem, epoch, sid=None):
        hashed = 'codex-' + hashlib.sha256((sid or self.sid).encode()).hexdigest()
        path = module.grant_path(stem, hashed)
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps({'epoch': epoch, 'used': False}))
        return hashed

    def test_dst_fall_back_hour_cutoff_is_not_an_hour_early(self):
        d = self.dispatcher()
        second_0130 = 1793514600.0   # 2026-11-01 06:30:00Z = 01:30 EST, the SECOND 01:30 in New York
        hashed = self.write_grant(d, 'policy', second_0130 - 1200)   # armed 20 min earlier
        with self.at(d, second_0130, 'America/New_York'):
            self.assertEqual(time.strftime('%H:%M %Z', time.localtime(second_0130)), '01:30 EST')
            # The record a failed revoke leaves (f1 shape): only the line, the grant file intact.
            d.audit(hashed, 'startup', 'compact', stamp=True)
        with self.at(d, second_0130 + 60):
            self.assertEqual(d.stale_grants(hashed), {'policy'})
        self.write_grant(d, 'policy', second_0130 + 5)
        with self.at(d, second_0130 + 60):
            self.assertEqual(d.stale_grants(hashed), set(), 'a grant armed after the compaction is fresh')

    def test_tz_change_between_record_and_use(self):
        d = self.dispatcher()
        compacted = 1793995200.0     # 2026-11-06 20:00Z: Tokyo 11-07, New York 11-06
        hashed = self.write_grant(d, 'net', compacted - 600)
        with self.at(d, compacted, 'Asia/Tokyo'):
            d.audit(hashed, 'startup', 'compact', stamp=True)
        self.assertTrue((self.root / '.agent-log' / '2026-11-07.md').exists())
        with self.at(d, compacted + 60, 'America/New_York'):
            self.assertEqual(d.stale_grants(hashed), {'net'})
            self.write_grant(d, 'net', compacted + 5)
            self.assertEqual(d.stale_grants(hashed), set())

    def test_record_in_yesterdays_log_still_counts(self):
        d = self.dispatcher()
        compacted = 1793853000.0     # 2026-11-04 23:30 EST (04:30Z on 11-05)
        hashed = self.write_grant(d, 'env', compacted - 600)
        with self.at(d, compacted, 'America/New_York'):
            d.audit(hashed, 'startup', 'compact', stamp=True)
        self.assertTrue((self.root / '.agent-log' / '2026-11-04.md').exists())
        with self.at(d, compacted + 3600):  # 00:30 on 11-05
            self.assertEqual(time.strftime('%Y-%m-%d', time.localtime(compacted + 3600)), '2026-11-05')
            self.assertEqual(d.stale_grants(hashed), {'env'})

    def test_audit_takes_day_and_time_from_one_clock_read(self):
        d = self.dispatcher()
        reads = iter([1793854799.9, 1793854800.1])   # 23:59:59.9 then 00:00:00.1 on 11-04/05 New York
        self.tz('America/New_York')
        with mock.patch.object(d.time, 'time', side_effect=lambda: next(reads)):
            d.audit('codex-x', 'startup', 'compact', stamp=True)
        line = (self.root / '.agent-log' / '2026-11-04.md').read_text()
        self.assertIn('- 23:59:59 [codex] startup sid=codex-x compact epoch:1793854799.9', line)

    def test_unreadable_log_refuses_every_sessions_grants(self):
        if os.geteuid() == 0:
            self.skipTest('running as root: chmod does not bind')
        d = self.dispatcher()
        now = time.time()
        mine = self.write_grant(d, 'policy', now)
        other = self.write_grant(d, 'policy', now, sid='never-compacted')
        day = self.root / '.agent-log' / (time.strftime('%Y-%m-%d') + '.md')
        day.write_text('')
        os.chmod(day, 0o000)
        self.addCleanup(os.chmod, day, 0o600)
        self.assertEqual(d.stale_grants(mine), {'policy'})
        self.assertEqual(d.stale_grants(other), {'policy'})

    def test_legacy_record_without_epoch_refuses_conservatively(self):
        d = self.dispatcher()
        now = time.time()
        hashed = self.write_grant(d, 'policy', now + 5)
        day = self.root / '.agent-log' / (time.strftime('%Y-%m-%d') + '.md')
        day.write_text('- %s [codex] startup sid=%s compact\n' % (time.strftime('%H:%M:%S'), hashed))
        self.assertEqual(d.stale_grants(hashed), {'policy'}, 'even a fresh grant is refused')

    # Repair round 2: the 26 h offset spread (UTC-12 .. UTC+14).
    def test_utc_plus_14_record_seen_from_utc_minus_12_midnight(self):
        d = self.dispatcher()
        consumer = 1793881800.0      # 2026-11-05 12:30Z = 00:30 on 11-05 at UTC-12
        recorded = consumer - 600    # 12:20Z = 02:20 on 11-06 at UTC+14
        hashed = self.write_grant(d, 'policy', recorded - 600)
        with self.at(d, recorded, 'Pacific/Kiritimati'):
            d.audit(hashed, 'startup', 'compact', stamp=True)
        self.assertTrue((self.root / '.agent-log' / '2026-11-06.md').exists())
        with self.at(d, consumer, 'Etc/GMT+12'):   # POSIX sign: Etc/GMT+12 is UTC-12
            self.assertEqual(time.strftime('%Y-%m-%d %H:%M', time.localtime(consumer)), '2026-11-05 00:30')
            self.assertEqual(d.stale_grants(hashed), {'policy'})

    def test_utc_minus_12_legacy_record_seen_from_utc_plus_14(self):
        d = self.dispatcher()
        consumer = 1793881800.0
        recorded = consumer - 7 * 3600   # seven hours old
        self.tz('Etc/GMT+12')
        local = time.localtime(recorded)
        hashed = self.write_grant(d, 'policy', consumer - 60)
        (self.root / '.agent-log' / (time.strftime('%Y-%m-%d', local) + '.md')).write_text(
            '- %s [codex] startup sid=%s compact\n' % (time.strftime('%H:%M:%S', local), hashed))
        with self.at(d, consumer, 'Pacific/Kiritimati'):
            self.assertEqual(d.stale_grants(hashed), {'policy'}, 'legacy record could be in the window')

    def test_forty_hour_old_legacy_record_does_not_block_a_fresh_grant(self):
        d = self.dispatcher()
        now = time.time()
        old = time.localtime(now - 40 * 3600)
        hashed = self.write_grant(d, 'policy', now)
        (self.root / '.agent-log' / (time.strftime('%Y-%m-%d', old) + '.md')).write_text(
            '- %s [codex] startup sid=%s compact\n' % (time.strftime('%H:%M:%S', old), hashed))
        self.assertEqual(d.stale_grants(hashed), set())

    def test_record_and_unlink_both_fail_says_revocation_not_assured(self):
        if os.geteuid() == 0:
            self.skipTest('running as root: chmod does not bind')
        d = self.dispatcher()
        hashed = self.write_grant(d, 'policy', time.time())
        logdir = self.root / '.agent-log'
        os.chmod(d.grant_path('policy', hashed), 0o400)
        os.chmod(logdir, 0o500)
        self.addCleanup(os.chmod, logdir, 0o700)
        with mock.patch.object(d, 'audit', side_effect=OSError('day log unwritable')):
            text = d.compaction_tidy(hashed)
        self.assertTrue(d.grant_path('policy', hashed).exists(), 'fixture must fail the unlink')
        self.assertIn('revocation is not assured', text)
        self.assertNotIn('still refused at use', text)

    def test_non_finite_grant_epoch_is_stale(self):
        d = self.dispatcher()
        now = time.time()
        hashed = 'codex-' + hashlib.sha256(self.sid.encode()).hexdigest()
        d.audit(hashed, 'startup', 'compact', stamp=True)
        d.grant_path('policy', hashed).write_text('{"epoch": Infinity, "used": false}')
        self.assertEqual(d.stale_grants(hashed), {'policy'})

    def test_missing_launcher_target_exits_two(self):
        launcher = self.root / '.codex/hooks/launch.sh'
        self.script.rename(self.script.with_suffix('.absent'))
        proc = subprocess.run(['sh', str(launcher)], cwd=self.root, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2)
        self.assertIn('required hook file missing', proc.stderr)


if __name__ == '__main__':
    unittest.main()
