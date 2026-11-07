"""One offline HTML report, numeric JSON companion and private evidence links."""
from html import escape
import json
from pathlib import Path
import shlex
import statistics
from urllib.parse import quote

from . import common as c


def aggregate(state):
    measurements = {}
    grouped = []
    for phase in state['phases']:
        if phase['status'] != 'PASS': continue
        for name, row in sorted(phase.get('result', {}).get('metrics', {}).items()):
            if row.get('n', 1) > 1:
                grouped.append({'kind': phase['kind'], 'metric': name, 'unit': row['unit'],
                                'n': row['n'], 'median': row['value'], 'min': row['min'], 'max': row['max']})
                continue
            key = (phase['kind'], name, row['unit'])
            measurements.setdefault(key, []).append(row['value'])
    return grouped + [{'kind': kind, 'metric': name, 'unit': unit, 'n': len(values),
             'median': statistics.median(values), 'min': min(values), 'max': max(values)}
            for (kind, name, unit), values in measurements.items()]


def conclusion(state):
    phases = state['phases']
    if any(row['status'] in ('FAILED', 'INTERRUPTED', 'CANDIDATE_REJECTED') for row in phases):
        return 'INCOMPLETE', 'One or more phases failed. Read the failed cases and retained evidence before drawing a model-quality conclusion.'
    if any(row['status'] in ('BLOCKED', 'NOT_EVALUATED') for row in phases):
        return 'PARTIAL', 'Some measurements are unavailable. Missing evaluation is not a zero score or a success.'
    if any(row['status'] in ('PENDING', 'RUNNING') for row in phases):
        return 'RUNNING', 'The experiment has not completed.'
    smoke = any('smoke' in str(row.get('result', {}).get('scope', '')).lower() for row in phases)
    return ('COMPLETED_WITH_SMOKE' if smoke else 'COMPLETED'), ('All requested phases completed. '
            + ('At least one standard suite used a smoke subset. ' if smoke else '')
            + 'Scores describe this model, harness, hardware and task; they do not establish a universal ranking.')


def progress(state):
    from .resume import COMPLETE
    next_phase = next((row for row in state['phases'] if row['status'] not in COMPLETE), None)
    if next_phase is None: return {'next_phase': None, 'action': 'COMPLETE', 'reason': None}
    review = next_phase.get('effects_started', False) and next_phase['id'] != 'deploy'
    return {'next_phase': next_phase['id'],
            'action': 'REVIEW_REQUIRED' if review else 'REPEAT_SAME_COMMAND',
            'reason': next_phase.get('reason', next_phase.get('result', {}).get('scope')),
            'completed': sum(row['status'] == 'PASS' for row in state['phases']),
            'attempt': next_phase.get('attempt', 0)}


def render(folder, state):
    status, summary = conclusion(state)
    health_notes = []
    for phase in state['phases']:
        for check in phase.get('result', {}).get('checks', []):
            for observation in check.get('details', {}).get('non_ok_observations', []) if isinstance(check.get('details'), dict) else []:
                health_notes.append(str(observation['check']) + ': status ' + str(observation['status']))
    data = {'schema_version': 1, 'run_id': state['run_id'], 'status': status,
            'summary': summary, 'generated_at': max([state['created_at']] + [row.get('finished_at', row.get('started_at', state['created_at'])) for row in state['phases']]), 'identity': state['identity'],
            'live_backend_identity': state.get('live_identity'),
            'progress': progress(state), 'phases': state['phases'], 'aggregates': aggregate(state), 'health_observations_requiring_review': health_notes,
            'interpretation': ['PASS means a measurement completed, not that its quality score is high.',
                               'Visible tests and TRAIN are development evidence; held-out accuracy needs the independent evaluator.',
                               'Token usage, cache reuse, energy and cost are unknown unless separately measured.',
                               'Evidence may contain correspondence or generated code. Review/redact before publication.']}
    def write_if_changed(path, content):
        if not path.exists() or path.read_bytes() != content: c.atomic_bytes(path, content)
    write_if_changed(folder / 'report.json', c.encoded(data))
    esc = lambda value: escape(str(value), quote=True)
    cards = ''.join('<div class="card"><span>' + esc(key) + '</span><strong>' + esc(value) + '</strong></div>'
                    for key, value in [('Run', state['run_id']), ('Model', state['identity']['model']['id']),
                                       ('Status', status), ('Phases complete', str(sum(p['status'] == 'PASS' for p in state['phases']))
                                        + ' / ' + str(len(state['phases'])))])
    if health_notes:
        cards += '<div class="card"><span>Health observations requiring review</span><strong>' + esc('; '.join(health_notes)) + '</strong></div>'
    sections = ['<section><h2>Continuation</h2><pre>' + esc(json.dumps(data['progress'], indent=2, sort_keys=True)) + '</pre><p>Repeat the same run command after resolving the recorded blocker. Completed evidence is verified and retained.</p></section>']
    for phase in state['phases']:
        result = phase.get('result', {})
        rows = ''.join('<tr><th>' + esc(name) + '</th><td>' + esc(row['value']) + '</td><td>' + esc(row['unit']) + '</td></tr>'
                       for name, row in sorted(result.get('metrics', {}).items()))
        metrics = '<table><thead><tr><th>Measurement</th><th>Value</th><th>Unit</th></tr></thead><tbody>' + rows + '</tbody></table>' if rows else ''
        reason = '<p>' + esc(phase.get('reason', result.get('scope', ''))) + '</p>'
        evidence = ''
        if phase.get('evidence_directory'):
            relative = Path(phase['evidence_directory'])
            if not relative.is_absolute() and '..' not in relative.parts:
                evidence = '<p><a href="' + quote(str(relative / 'receipt.json')) + '">Phase receipt and evidence index</a></p>'
        # Never embed arbitrary HTML, email text or raw agent logs in the report.
        details = {key: value for key, value in result.items()
                   if key in ('samples', 'suites', 'evaluated_samples', 'scope', 'usage', 'candidate_tree_sha256',
                              'train_examples_checked', 'assessment', 'trials', 'telemetry', 'non_ok_observations', 'checks')}
        technical = '<details><summary>Measurement details</summary><pre>' + esc(json.dumps(details, indent=2, sort_keys=True)) + '</pre></details>' if details else ''
        sections.append('<section><h2>' + esc(phase['name']) + ' <span class="badge ' + esc(phase['status']) + '">' + esc(phase['status'])
                        + '</span></h2>' + reason + metrics + technical + evidence + '</section>')
    aggregates = ''.join('<tr>' + ''.join('<td>' + esc(row[key]) + '</td>' for key in ('kind', 'metric', 'n', 'median', 'min', 'max', 'unit')) + '</tr>'
                         for row in data['aggregates'])
    aggregate_table = '<section><h2>Repetitions: median and range</h2><table><tr><th>Phase</th><th>Metric</th><th>N</th><th>Median</th><th>Min</th><th>Max</th><th>Unit</th></tr>' + aggregates + '</table></section>' if aggregates else ''
    model = esc(json.dumps({'experiment': state['identity'], 'live_backend': state.get('live_identity')}, indent=2, sort_keys=True))
    document = '''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>ModelBench — ''' + esc(state['run_id']) + '''</title><style>
:root{font-family:system-ui,sans-serif;color:#16302b;background:#f1f5f3}body{max-width:1120px;margin:auto;padding:32px 20px}
h1{font-size:2.3rem;margin-bottom:8px}h2{font-size:1.2rem}header p{max-width:76ch;line-height:1.6}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin:28px 0}
.card,section{background:white;border:1px solid #d6e1dc;border-radius:12px;padding:20px}.card span{display:block;color:#526960;font-size:.85rem}.card strong{display:block;margin-top:10px;overflow-wrap:anywhere}
section{margin:18px 0;overflow:auto}table{border-collapse:collapse;width:100%;text-align:left}td,th{border-bottom:1px solid #e0e9e4;padding:10px;font-size:.9rem}
.badge{font-size:.72rem;padding:5px 9px;border-radius:20px;background:#edf0ef;white-space:nowrap}.PASS{background:#d5efdf}.FAILED,.BLOCKED,.INTERRUPTED,.CANDIDATE_REJECTED{background:#ffe1d7}.RUNNING{background:#dce9ff}
pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:.8rem}a{color:#08644c}footer{line-height:1.7;color:#526960}.eyebrow{text-transform:uppercase;letter-spacing:.15em;font-size:.75rem}
</style><header><div class="eyebrow">ModelBench · reproducible local-agent evaluation</div><h1>One experiment. The full evidence.</h1><p>''' + esc(summary) + '</p></header><div class="cards">' + cards + '</div>' + aggregate_table + ''.join(sections)
    command = shlex.join(['python3', '-B', 'scripts/benchmark.py', 'run', '--config', str(folder / 'configuration.json'), '--run-id', state['run_id'], '--output', str(folder.parent)])
    document += '<section><h2>Continue this experiment</h2><p>From the same source checkout, with unchanged pinned inputs:</p><pre>' + esc(command) + '</pre><details><summary>Exact identities</summary><pre>' + model + '</pre></details><p><a href="configuration.json">Experiment configuration</a> · <a href="report.json">Machine-readable report</a></p></section><footer><ul>'
    document += ''.join('<li>' + esc(line) + '</li>' for line in data['interpretation'])
    document += '</ul><p>Generated ' + esc(data['generated_at']) + ' (UTC). No combined universal model score is calculated.</p></footer></html>'
    write_if_changed(folder / 'report.html', document.encode())
    return data
