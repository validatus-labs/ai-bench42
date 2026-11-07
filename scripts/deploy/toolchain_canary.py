"""Real host-toolchain canaries, never a C00 worker-readiness shortcut."""
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request
import uuid

import bootstrap_components as common
import toolchain_lifecycle as lifecycle


def text(result):
    return '\n'.join(item.get('text', '') for item in result.get('content', []) if item.get('type') == 'text')


def api(data, path, body=None, timeout=None):
    model = data['model_canary']
    lifecycle.model_endpoint(model)
    headers = {'Content-Type': 'application/json'}
    if model['auth_file'] is not None:
        key_file = lifecycle.private(Path(model['auth_file']))
        lifecycle.require(key_file.is_file() and key_file.stat().st_size <= 4096, 'Invalid canary key file')
        key = key_file.read_text().strip()
        lifecycle.require(key and '\n' not in key and '\r' not in key, 'Invalid canary key')
        headers['Authorization'] = 'Bearer ' + key
    request = urllib.request.Request(model['base_url'] + path,
                                     data=None if body is None else json.dumps(body).encode(), headers=headers)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), lifecycle.NoRedirect())
    with opener.open(request, timeout=timeout or model['timeout_seconds']) as response:
        raw = response.read(2 * 1024 * 1024 + 1)
    lifecycle.require(len(raw) <= 2 * 1024 * 1024, 'Oversized local inference response')
    return json.loads(raw)


def run(release, folder, data):
    marker = 'modelbench-update-' + uuid.uuid4().hex
    browser_work = folder / 'browser'; browser_work.mkdir(mode=0o700)
    raw = lifecycle.output(lifecycle.command_args(release, browser_work,
        ['/usr/bin/node', '/checks/browser.cjs', marker], probe=True), env=lifecycle.environment(folder, browser_tmp=data.get('browser_temporary_root')), timeout=180, log=folder / 'browser.log')
    browser = json.loads(raw.strip())
    lifecycle.require(browser.get('status') == 'PASS' and browser.get('marker') == marker, 'Browser sandbox/fixture did not pass')
    lifecycle.atomic(folder / 'browser.json', browser)

    cli = '/npm/node_modules/@playwright/mcp/cli.js'
    # CLI flags are checked against the candidate itself, not assumed forever.
    help_text = lifecycle.output(lifecycle.command_args(release, browser_work,
        ['/usr/bin/node', cli, '--help']), timeout=30)
    for option in ('--headless', '--isolated', '--sandbox', '--block-service-workers', '--executable-path'):
        lifecycle.require(option in help_text, 'Candidate MCP no longer supports required flag: ' + option)
    launcher = folder / 'playwright-mcp'
    argv = lifecycle.command_args(release, browser_work,
        ['/usr/bin/node', cli, '--headless', '--isolated', '--sandbox', '--block-service-workers',
         '--executable-path', '/opt/brave.com/brave/brave', '--output-dir', '/tmp/output'])
    import shlex
    launcher.write_text('#!/usr/bin/env bash\nset -Eeuo pipefail\nexec ' + shlex.join(argv) + '\n'); launcher.chmod(0o700)
    installer = common.load_script('install-playwright-mcp.py')
    mcp = installer.Mcp(launcher, folder, lifecycle.environment(folder, browser_tmp=data.get('browser_temporary_root')))
    try:
        info, tools = mcp.initialize()
        names = {tool['name'] for tool in tools}
        lifecycle.require({'browser_navigate', 'browser_snapshot', 'browser_close'} <= names, 'Required MCP tools disappeared')
        lifecycle.atomic(folder / 'schema.json', tools)
        lifecycle.atomic(folder / 'mcp.json', {'server': info['serverInfo'], 'schema_sha256': common.digest(folder / 'schema.json')})
        deadline = time.monotonic() + data['model_canary']['timeout_seconds']
        while True:
            try:
                models = api(data, '/models', timeout=min(10, max(1, deadline - time.monotonic())))
                break
            except urllib.error.HTTPError as exc:
                if exc.code != 503 or time.monotonic() >= deadline: raise
            except (urllib.error.URLError, TimeoutError):
                if time.monotonic() >= deadline: raise
            time.sleep(min(5, max(0, deadline - time.monotonic())))
        lifecycle.require(data['model_canary']['model'] in {item['id'] for item in models['data']}, 'Configured local model alias is not served')
        messages = [{'role': 'system', 'content': 'Use the supplied tool to read an unknown marker. Then answer with exactly that marker.'},
                    {'role': 'user', 'content': 'Read the marker now.'}]
        tool = {'type': 'function', 'function': {'name': 'read_browser_marker',
                'description': 'Read a fresh marker through the real browser MCP.',
                'parameters': {'type': 'object', 'properties': {}, 'additionalProperties': False}}}
        first = api(data, '/chat/completions', {'model': data['model_canary']['model'], 'messages': messages,
                    'tools': [tool], 'tool_choice': {'type': 'function', 'function': {'name': 'read_browser_marker'}},
                    'temperature': 0, 'max_tokens': 512})
        lifecycle.atomic(folder / 'api-first.json', first)
        assistant = first['choices'][0]['message']
        calls = assistant.get('tool_calls', [])
        lifecycle.require(len(calls) == 1 and calls[0]['function']['name'] == 'read_browser_marker', 'Model did not issue the required structured tool call')
        lifecycle.require(json.loads(calls[0]['function']['arguments']) == {}, 'Unexpected model tool arguments')
        tool_marker = 'mcp-model-' + uuid.uuid4().hex
        mcp.call('browser_navigate', {'url': 'data:text/html,<h1>' + tool_marker + '</h1>'})
        snapshot = text(mcp.call('browser_snapshot', {}))
        lifecycle.require(tool_marker in snapshot, 'Real browser MCP did not observe the marker')
        mcp.call('browser_close', {})
        messages += [assistant, {'role': 'tool', 'tool_call_id': calls[0]['id'], 'content': tool_marker}]
        second = api(data, '/chat/completions', {'model': data['model_canary']['model'], 'messages': messages,
                    'temperature': 0, 'max_tokens': 512})
        lifecycle.atomic(folder / 'api-second.json', second)
        answer = (second['choices'][0]['message'].get('content') or '').strip()
        lifecycle.require(answer == tool_marker, 'Model/tool-result second round failed')
        model = {'status': 'PASS', 'model': data['model_canary']['model'], 'base_url': data['model_canary']['base_url'],
                 'structured_tool_call': True, 'actual_mcp_marker': True, 'tool_result_round_trip': True,
                 'usage': [first.get('usage'), second.get('usage')], 'new_model_requests': 2}
        lifecycle.atomic(folder / 'model.json', model)
        return {'browser_sandbox': True, 'browser_fixture': True, 'mcp_tools': True,
                'service_workers_flag': True, 'model_tool_round_trip': True,
                'schema_sha256': common.digest(folder / 'schema.json'),
                'browser_evidence_sha256': common.digest(folder / 'browser.json'),
                'model_evidence_sha256': common.digest(folder / 'model.json')}
    finally:
        mcp.close()
