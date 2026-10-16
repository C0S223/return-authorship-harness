#!/usr/bin/env python3
"""Read-only repository capability report; never claims runtime activation."""
import json
from pathlib import Path
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def inspect(root=ROOT):
    config = tomllib.loads((root / '.codex/config.toml').read_text(encoding='utf-8'))
    registrations = json.loads((root / '.codex/hooks.json').read_text(encoding='utf-8'))['hooks']
    agents = []
    for path in sorted((root / '.codex/agents').glob('*.toml')):
        agent = tomllib.loads(path.read_text(encoding='utf-8'))
        if not all(isinstance(agent.get(key), str) and agent[key] for key in ('name', 'description', 'developer_instructions')):
            raise ValueError('incomplete agent: ' + path.name)
        if path.stem != agent['name']:
            raise ValueError('agent filename/name mismatch: ' + path.name)
        agents.append(agent['name'])
    return {'contract_identical': (root / 'CLAUDE.md').read_bytes() == (root / 'AGENTS.md').read_bytes(),
            'hooks_configured': sorted(registrations),
            'hooks_enabled_in_project_file': config.get('features', {}).get('hooks', False),
            'unified_exec_in_project_file': config.get('features', {}).get('unified_exec'),
            'sandbox_in_project_file': config.get('sandbox_mode'),
            'approval_in_project_file': config.get('approval_policy'),
            'agents_on_disk': agents,
            'skills_on_disk': sorted(p.parent.name for p in (root / '.agents/skills').glob('*/SKILL.md')),
            'cli_activation': 'unprobed by this report',
            'app_activation': 'unprobed by this report',
            'effective_settings': 'not inspected; project files are not runtime evidence',
            'python': sys.version.split()[0]}


def main():
    try:
        result = inspect()
        print(json.dumps(result, indent=2))
        return 0 if result['contract_identical'] else 1
    except Exception as error:
        print(json.dumps({'error': str(error), 'activation': 'unverified'}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
