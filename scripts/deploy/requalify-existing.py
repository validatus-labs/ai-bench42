#!/usr/bin/env python3
"""Qualify current installed Brave/Node/MCP in a new private registration.

requalify-existing.py
|-- inspect   exact operator-supplied hashes, normal account and safe paths
|-- apply     new launcher -> real browser/MCP proof -> atomic adoption
`-- verify    all retained bytes, model identity and native health observations

No APT/npm installation, model generation, restart or old-registry replacement.
The profile must explicitly pin the observed native hashes. This is host-tool
qualification, not an isolated Kilo worker or held-out evaluation certificate.
"""
import argparse
import contextlib
import io
import json
from pathlib import Path
import sys

import bootstrap_adoption as adoption


def run(data, action, output=None):
    adoption.identity(data)
    adoption.require(data.get('browser_runtime') and data.get('controller_source'),
                     'Explicit new browser runtime and controller source required')
    browser = adoption.safe(data['browser_runtime'])
    old_browser = Path(data['existing_runtime']) / 'tools/playwright-tool'
    adoption.require(browser != old_browser, 'Preserve the historical launcher')
    adoption.require(data['destination_runtime'] != str(Path(data['existing_runtime']) / 'tools/ai-bench42-host'),
                     'Preserve the historical whole-stack registration')
    installer = adoption.module(Path(data['controller_source']) / 'scripts/deploy/install-playwright-mcp.py')
    profile = installer.load_profile(Path(data['source_root']))
    profile['runtime'] = str(browser)
    observed = installer.inventory(profile)
    for field, value in [('browser_sha256', observed['browser_sha256']),
                         ('node_sha256', observed['node_sha256']),
                         ('module_seal_sha256', observed['module_seal']['sha256'])]:
        adoption.require(data[field] == value, 'Observed native pin differs: ' + field)
    result = {'status': 'PINS_MATCH', 'browser_sha256': observed['browser_sha256'],
              'node_sha256': observed['node_sha256'], 'packages': observed['packages'],
              'new_model_requests': 0, 'model_service_changes': 0,
              'scope': 'Existing host tools; not worker C00 or held-out qualification'}
    if action == 'apply':
        adoption.require(output is not None, 'A private evidence directory is required')
        # Keep the CLI structured even when the legacy installer prints a receipt.
        with contextlib.redirect_stdout(io.StringIO()):
            installer.install(profile)
        state = adoption.adopt(data, output)
        result.update(status=state['status'], registry=state['registry'])
    elif action == 'verify':
        adoption.check(data['destination_runtime'], data)
        result.update(status='VERIFIED', registry=str(adoption.registry_path(data['destination_runtime'])))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('action', choices=['inspect', 'apply', 'verify'])
    parser.add_argument('--profile', required=True, type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(run(adoption.profile(args.profile), args.action, args.output), indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        print(json.dumps({'status': 'BLOCKED', 'reason': str(exc)}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
