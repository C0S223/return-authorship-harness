"""Native discovery/configuration and existing policy integration, without activation."""
import json
from pathlib import Path
import subprocess
import sys
import tomllib

import ci_policy_check as ci
import prepush_check as pc
from codex_status import inspect

ROOT = Path(__file__).resolve().parents[1]


def main():
    checker = pc._load_is_policy()
    assert checker is not None, 'policy predicate unavailable'
    paths = ['CODEX-SETUP.md', 'docs/codex-enforcement.md', 'AGENTS.md', 'AGENTS.override.md',
             'nested/AGENTS.md', '.codex/config.toml', '.codex/agents/recall.toml',
             '.agents/skills/new/SKILL.md', 'worktrees/lane/.agents/skills/new/SKILL.md']
    assert ci.flagged(paths, checker) == paths, 'Codex policy escaped operator review'
    assert (ROOT / 'AGENTS.md').read_bytes() == (ROOT / 'CLAUDE.md').read_bytes()
    original = subprocess.run(['git', '-C', str(ROOT), 'show',
                              '759372bd98a7e25381ee413a045ec81a927f994f:CLAUDE.md'],
                             capture_output=True)
    # Template clones need not retain this port's historical object. Where the
    # object exists, ensure equal contracts did not both drift from the original.
    if original.returncode == 0:
        assert original.stdout == (ROOT / 'CLAUDE.md').read_bytes(), 'original contract changed'
    config = tomllib.loads((ROOT / '.codex/config.toml').read_text())
    assert config['approval_policy'] == 'on-request'
    assert config['sandbox_mode'] == 'workspace-write'
    assert config['sandbox_workspace_write']['network_access'] is False
    assert config['project_doc_fallback_filenames'] == ['CLAUDE.md']
    assert config['features']['unified_exec'] is False
    assert config['features']['unified_exec_tty'] is False
    status = inspect(ROOT)
    assert status['contract_identical']
    assert 'unprobed' in status['cli_activation'] and 'unprobed' in status['app_activation']
    assert status['hooks_enabled_in_project_file'] == config['features']['hooks']
    roster = {'Explore', 'claude-code-guide', 'adversarial-reviewer',
              'senior-engineer', 'recall', 'super-doer'}
    assert set(status['agents_on_disk']) == roster
    for path in (ROOT / '.codex/agents').glob('*.toml'):
        agent = tomllib.loads(path.read_text())
        assert set(agent) >= {'name', 'description', 'developer_instructions'}
        assert not set(agent) & {'config_file', 'sandbox_mode', 'approval_policy'}, path
    expected_skills = {'harness-grill', 'harness-lane', 'review-order', 'closeout', 'cite-check'}
    assert set(status['skills_on_disk']) == expected_skills
    for name in expected_skills:
        text = (ROOT / '.agents/skills' / name / 'SKILL.md').read_text()
        front = text.split('---', 2)[1]
        assert 'name: ' + name in front and 'description:' in front
    hooks = json.loads((ROOT / '.codex/hooks.json').read_text())['hooks']
    assert set(hooks) == {'SessionStart', 'UserPromptSubmit', 'PreToolUse', 'PostToolUse', 'Stop'}
    for groups in hooks.values():
        assert len(groups) == 1 and len(groups[0]['hooks']) == 1, 'ordered checks need one dispatcher'
        hook = groups[0]['hooks'][0]
        assert hook['type'] == 'command' and hook['timeout'] > 0
        assert 'commandWindows' in hook
        assert '.codex/hooks/launch.sh' in hook['command']
    assert (ROOT / 'docs/codex-enforcement.md').is_file()
    print('ok: native discovery, configuration and policy classification; runtime activation unprobed')


if __name__ == '__main__':
    main()
