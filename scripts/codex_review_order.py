#!/usr/bin/env python3
"""Reuse the review-order Git/citation machinery with the native Codex binding."""
import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def main():
    source = ROOT / '.claude/skills/review-order/review_order.py'
    spec = importlib.util.spec_from_file_location('review_order', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    def binding(reviewer):
        if reviewer not in ('senior-engineer', 'adversarial-reviewer'):
            sys.exit('REFUSED: not a Codex reviewer binding')
        config = tomllib.loads((ROOT / '.codex/agents' / (reviewer + '.toml')).read_text())
        if config.get('name') != reviewer or not config.get('developer_instructions'):
            sys.exit('REFUSED: incomplete Codex reviewer binding')
        return []
    module.tool_grant = binding
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        result = module.main()
    for line in output.getvalue().splitlines():
        if line.startswith('REVIEWER:'):
            reviewer = sys.argv[1]
            line = ('REVIEWER: %s -- Codex custom binding .codex/agents/%s.toml; '
                    'parent sandbox/approvals/MCP inherited; one-review-file scope is prose. '
                    'Verify effective tools and hook activation before dispatch.' % (reviewer, reviewer))
        print(line)
    return result


if __name__ == '__main__':
    sys.exit(main())
