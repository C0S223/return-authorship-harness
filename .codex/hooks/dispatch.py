"""Local Codex transport. Shared guards own classification; unknown shapes block.

No claim of a hostile-agent boundary: this process and its state are agent-writable.
See docs/codex-enforcement.md for transport assumptions and activation probes.
"""
import contextlib
import fnmatch
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / '.claude/hooks'
# Local port must never inherit a Claude cloud-off switch or a caller's test root.
os.environ['HARNESS_ROOT'] = str(ROOT)
os.environ['CLAUDE_PROJECT_DIR'] = str(ROOT)
os.environ.pop('CLAUDE_CODE_REMOTE', None)
os.environ.pop('HARNESS_BOUNDARY', None)


class Refusal(Exception):
    pass


def require(ok, reason):
    if not ok:
        raise Refusal(reason)


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), HOOKS / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def audit(sid, event, detail):
    directory = ROOT / '.agent-log'
    directory.mkdir(exist_ok=True)
    # No command, prompt, tool arguments or secrets in the adapter trail.
    safe = re.sub(r'[^A-Za-z0-9_.:/ -]', '?', str(detail))[:240]
    with (directory / (time.strftime('%Y-%m-%d') + '.md')).open('a', encoding='utf-8') as f:
        f.write('- %s [codex] %s sid=%s %s\n' % (time.strftime('%H:%M:%S'), event, sid, safe))


def run_guard(name, data, sid):
    module = load(name)
    if name in ('net-post', 'env-global'):
        stem = 'net' if name == 'net-post' else 'env'
        module.UNLOCK = str(ROOT / '.agent-log' / (stem + '-unlock-' + sid + '.json'))
    if name == 'policy-prompt':
        original = module.arm
        def arm(stem, ignored_sid, *args, **kwargs):
            return original(stem, sid, *args, **kwargs)
        module.arm = arm
    output = io.StringIO()
    old_stdin = sys.stdin
    try:
        sys.stdin = io.StringIO(json.dumps(data))
        with contextlib.redirect_stdout(output):
            try:
                module.main()
            except SystemExit as error:
                require(error.code in (None, 0), name + ' failed')
    finally:
        sys.stdin = old_stdin
    result = output.getvalue().strip()
    if name == 'policy-prompt':
        return result
    if name == 'policy-integrity':
        return json.loads(result)['systemMessage'] if result else ''
    if result:
        answer = json.loads(result)
        if set(answer) == {'systemMessage'} and isinstance(answer['systemMessage'], str):
            return answer['systemMessage']
        specific = answer['hookSpecificOutput']
        decision = specific['permissionDecision']
        require(decision in ('allow', 'deny', 'ask'), name + ': unknown decision')
        if decision != 'allow':
            reason = specific.get('permissionDecisionReason', name)
            if decision == 'ask':
                reason += ' Codex cannot translate ask safely: blocked. The operator must perform this outside-scope action; a grant does not change the sandbox.'
            raise Refusal(reason)
    return ''


def patch_paths(command):
    """Recognize the complete apply_patch grammar before checking ANY target.

    No regex scanning of apparent headers: added content can itself contain them.
    Refuse unsupported extensions rather than interpreting an incomplete patch.
    """
    require(isinstance(command, str) and '\x00' not in command and '\r' not in command,
            'patch must be a plain LF string')
    lines = command.removesuffix('\n').split('\n')
    require(len(lines) >= 3 and lines[0] == '*** Begin Patch' and lines[-1] == '*** End Patch',
            'patch framing is unsupported')
    paths, seen = [], set()
    i = 1
    def add(path):
        require(path and path.strip() == path and not any(ord(c) < 32 for c in path), 'invalid patch path')
        require(path not in seen, 'duplicate patch target')
        seen.add(path)
        paths.append(path)
    while i < len(lines) - 1:
        line = lines[i]
        if line.startswith('*** Add File: '):
            add(line[14:]); i += 1
            while i < len(lines) - 1 and lines[i].startswith('+'):
                i += 1
        elif line.startswith('*** Delete File: '):
            add(line[17:]); i += 1
            raise Refusal('patch deletion requires recoverability and exact-batch review; operator performs it')
        elif line.startswith('*** Update File: '):
            add(line[17:]); i += 1
            if i < len(lines) - 1 and lines[i].startswith('*** Move to: '):
                add(lines[i][13:]); i += 1
            body, change = 0, False
            while i < len(lines) - 1:
                value = lines[i]
                if value.startswith(('*** Add File: ', '*** Update File: ', '*** Delete File: ')):
                    break
                require(value == '@@' or value.startswith('@@ ') or
                        (bool(value) and value[0] in ' +-') or value == '*** End of File',
                        'unsupported patch hunk')
                if value == '*** End of File':
                    i += 1
                    break
                change = change or value.startswith(('+', '-'))
                body += 1; i += 1
            require(body > 0 and change, 'empty update hunk')
        else:
            raise Refusal('unsupported patch section')
    require(paths, 'empty patch')
    return paths


def agent_control(tool, args, sid):
    """One exact native control call, approved in a separate user prompt.

    The digest binds tool, target and message without putting message text in
    the audit trail. This grants no standing peer-mailbox or spawn authority.
    """
    allowed = {'send_input': {'id', 'message', 'interrupt'},
               'resume_agent': {'id'}, 'close_agent': {'id'}}
    require(set(args) <= allowed[tool], 'unknown native agent-control argument')
    require(isinstance(args.get('id'), str) and bool(args['id']), 'agent control requires an id')
    if tool == 'send_input':
        require(isinstance(args.get('message'), str) and bool(args['message']), 'send_input requires a message')
        require('interrupt' not in args or isinstance(args['interrupt'], bool), 'interrupt must be boolean')
    encoded = json.dumps({'tool': tool, 'input': args}, sort_keys=True, separators=(',', ':'), ensure_ascii=True)
    digest = hashlib.sha256(encoded.encode()).hexdigest()
    path = ROOT / '.agent-log' / ('agent-unlock-' + sid + '.json')
    grant = load('unlock_consume').consume(str(path), match=lambda g: g.get('digest') == digest)
    require(grant is not None,
            'agent control requires explicit approval of this exact target and input. '
            'Show the complete proposed call to the operator, then request a new prompt: auth-agent ' + digest)
    audit(sid, 'unlock-consumed', tool + ' ' + digest)


def normalize(data, sid):
    tool, args = data.get('tool_name'), data.get('tool_input')
    require(isinstance(tool, str) and tool, 'missing tool name')
    require(isinstance(args, dict), 'tool_input must be an object')
    cwd = data.get('cwd')
    require(isinstance(cwd, str) and os.path.isabs(cwd), 'missing absolute cwd')
    base = dict(data, session_id=sid, cwd=cwd)
    # Names are explicit transport mappings, not shell classifiers.
    if tool in ('exec_command', 'write_stdin', 'functions.exec', 'functions.execute', 'multi_tool_use.parallel'):
        raise Refusal('unified execution/continuation or nested tool envelope is unsupported; use the noninteractive shell with unified_exec disabled')
    if tool in ('Bash', 'shell', 'shell_command'):
        require(set(args) <= {'command', 'workdir', 'timeout_ms', 'max_output_tokens',
                              'max_output_chars', 'login', 'sandbox_permissions',
                              'justification', 'prefix_rule', 'tty', 'interactive', 'session_id'},
                'unknown shell input field; cannot verify the execution shape')
        require(not args.get('tty') and not args.get('interactive') and not args.get('session_id'),
                'interactive shell cannot be guarded across stdin continuation')
        command = args.get('command')
        require(isinstance(command, str) and command.strip(), 'shell command must be a string')
        require('cmd' not in args, 'ambiguous shell command envelope')
        # Legacy shell has no continuation tool. Client activation must verify this.
        workdir = args.get('workdir', cwd)
        require(isinstance(workdir, str) and os.path.isabs(workdir), 'shell workdir must be absolute')
        base.update(tool_name='Bash', cwd=workdir, tool_input={'command': command})
        return [base], 'shell'
    if tool in ('apply_patch', 'ApplyPatch'):
        require(set(args) == {'command'}, 'unknown patch input field')
        return [dict(base, tool_name='Write', tool_input={'file_path': p})
                for p in patch_paths(args.get('command'))], 'patch'
    if tool in ('Write', 'Edit', 'NotebookEdit'):
        p = args.get('file_path') or args.get('notebook_path')
        require(isinstance(p, str) and p and '\x00' not in p, 'missing file path')
        return [base], 'file'
    if tool in ('spawn_agent', 'Agent'):
        # Alias matching does not transform native args into subagent_type.
        require(set(args) <= {'agent_type', 'message', 'items', 'fork_context'},
                'unknown spawn input field; cannot verify native role selection')
        role = args.get('agent_type')
        require(isinstance(role, str), 'spawn must name a custom agent_type; defaults are refused')
        require(load('spawn-roster').verdict(role) == 'allow', 'agent is outside the shared roster')
        import tomllib
        path = ROOT / '.codex/agents' / (role + '.toml')
        agent = tomllib.loads(path.read_text(encoding='utf-8'))
        require(agent.get('name') == role and bool(agent.get('developer_instructions')),
                'custom agent definition unavailable')
        base.update(tool_name='Agent', tool_input={'subagent_type': role})
        return [base], 'spawn'
    if tool in ('send_input', 'resume_agent', 'close_agent'):
        agent_control(tool, args, sid)
        return [base], 'agent-control'
    # Only these local tools have a known non-mutating envelope. Hosted tools
    # never reach this hook and must not be called covered by this allowlist.
    if tool in ('read_file', 'list_dir', 'grep_files', 'view_image', 'wait_agent', 'wait'):
        return [base], 'read'
    settings = json.loads((ROOT / '.claude/settings.json').read_text(encoding='utf-8'))
    for pattern in settings['permissions']['deny']:
        if fnmatch.fnmatchcase(tool, pattern):
            raise Refusal('shared settings deny this tool')
    raise Refusal('unmapped tool envelope: ' + tool + '; no verified policy translation')


def handle(data):
    require(isinstance(data, dict), 'hook input must be an object')
    raw_sid = data.get('session_id')
    require(isinstance(raw_sid, str) and raw_sid, 'missing session identity')
    sid = 'codex-' + hashlib.sha256(raw_sid.encode()).hexdigest()
    event = data.get('hook_event_name')
    base = dict(data, session_id=sid)
    if event == 'UserPromptSubmit':
        prompt = data.get('prompt')
        require(isinstance(prompt, str), 'missing prompt')
        # Codex documents no provenance field. Preserve absence; reject any
        # explicit non-user source. Never manufacture source=user.
        if data.get('source') not in (None, 'user'):
            audit(sid, 'prompt-refused', 'non-user source')
            return 'Prompt source cannot arm or revoke grants.'
        if prompt.strip() in ('revoke-net', 'revoke-env', 'revoke-agent'):
            stem = prompt.strip()[7:]
            path = ROOT / '.agent-log' / (stem + '-unlock-' + sid + '.json')
            # Write a spent tombstone instead of removing audit/state files.
            path.parent.mkdir(exist_ok=True)
            path.write_text(json.dumps({'used': True}), encoding='utf-8')
            audit(sid, 'unlock-revoked', stem)
            return stem + ' grant revoked for this session.'
        match = re.fullmatch(r'\s*auth-agent ([0-9a-f]{64})\s*', prompt)
        if match:
            path = ROOT / '.agent-log' / ('agent-unlock-' + sid + '.json')
            path.parent.mkdir(exist_ok=True)
            path.write_text(json.dumps({'digest': match[1], 'epoch': time.time(), 'used': False}), encoding='utf-8')
            audit(sid, 'unlock-armed', 'agent ' + match[1])
            return 'One exact agent-control call armed for this session (30 min); replaces its previous grant.'
        result = run_guard('policy-prompt', base, sid)
        audit(sid, 'prompt', 'grant parser completed')
        return result
    if event == 'SessionStart':
        source = data.get('source')
        require(source in ('startup', 'resume', 'compact', 'clear', 'fork'), 'unknown session-start source')
        integrity = run_guard('policy-integrity', dict(base, source='resume' if source == 'compact' else 'startup'), sid)
        audit(sid, 'startup', source)
        return ('Codex harness wired: shared guards, session grants and audit. Activation is unprobed on this client until CODEX-SETUP.md probes pass. ' +
                integrity + ' Use $harness-grill, $harness-lane, $review-order or $closeout. '
                'Unknown tools and approval-required scope escapes block; unified_exec must be disabled. Read docs/codex-enforcement.md.')
    if event == 'PostToolUse':
        # Any successful/failed tool can have produced effects. Shared integrity
        # is observational; force a compare without trusting mutation claims.
        integrity = run_guard('policy-integrity', dict(base, tool_name='Write'), sid)
        audit(sid, event, data.get('tool_name', 'unknown'))
        return integrity
    if event == 'Stop':
        integrity = run_guard('policy-integrity', dict(base, tool_name='Write'), sid)
        audit(sid, 'stop', 'turn ended; closeout only on operator request')
        return integrity
    require(event == 'PreToolUse', 'unsupported hook event')
    try:
        calls, kind = normalize(data, sid)
        notices = []
        # Scope first prevents spending a policy/network grant on a blocked escape.
        for call in calls:
            if kind in ('file', 'patch'):
                run_guard('filetool-scope', call, sid)
            elif kind == 'shell':
                run_guard('shell-scope', call, sid)
                run_guard('git-guard', call, sid)
        for call in calls:
            if kind in ('file', 'patch', 'shell'):
                run_guard('policy-mutate', call, sid)
            if kind == 'shell':
                run_guard('net-post', call, sid)
                notice = run_guard('env-global', call, sid)
                if notice:
                    notices.append(notice)
            if kind == 'spawn':
                run_guard('spawn-roster', call, sid)
        audit(sid, 'allow', data['tool_name'])
        return '\n'.join(notices)
    except Exception:
        audit(sid, 'deny', data.get('tool_name', 'unknown'))
        raise


def main():
    event = None
    try:
        data = json.load(sys.stdin)
        event = data.get('hook_event_name') if isinstance(data, dict) else None
        context = handle(data)
        if context:
            if event == 'Stop':
                print(json.dumps({'systemMessage': context}))
            else:
                print(json.dumps({'hookSpecificOutput': {'hookEventName': event, 'additionalContext': context}}))
    except Exception as error:
        reason = str(error) if isinstance(error, Refusal) else 'adapter failure: ' + type(error).__name__
        if event == 'PreToolUse' or event is None:
            print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse',
                  'permissionDecision': 'deny', 'permissionDecisionReason': 'codex-harness: ' + reason}}))
        else:
            print('codex-harness: ' + reason, file=sys.stderr)
            return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
