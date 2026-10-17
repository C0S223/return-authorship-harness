"""Executable transport proofs, not live Codex activation.

Each fixture copies the candidate into an isolated in-tree checkout, sets a real
Git default ref, and sends documented JSON envelopes directly to the dispatcher.
The client trust/runtime itself is deliberately not simulated or called proven.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

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
        (self.root / 'link').symlink_to(self.root.parent, target_is_directory=True)
        self.denied(self.pre('apply_patch', self.patch('link/outside.txt')))
        self.denied(self.pre('apply_patch', self.patch('.agents/skills/new/SKILL.md')))

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

    def test_missing_launcher_target_exits_two(self):
        launcher = self.root / '.codex/hooks/launch.sh'
        self.script.rename(self.script.with_suffix('.absent'))
        proc = subprocess.run(['sh', str(launcher)], cwd=self.root, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2)
        self.assertIn('required hook file missing', proc.stderr)


if __name__ == '__main__':
    unittest.main()
