"""Harness regressions; fake model responses are never benchmark measurements."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
import sys
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modelbench import common as c, kolibri as k


PROFILE = c.read(k.ROOT / 'config/kolibri-benchmark.json')
BACKEND = {'id': 'kolibri-1', 'created': 42, 'root': '/fixture/model', 'max_model_len': 262144, 'server': {'version': 'fixture'}}


def response(content, finish='stop', tools=None):
    message = {'role': 'assistant', 'content': content}
    if tools is not None: message['tool_calls'] = tools
    return {'model': 'kolibri-1', 'choices': [{'message': message, 'finish_reason': finish}], 'usage': {'prompt_tokens': 10, 'completion_tokens': 2}}


class HarnessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / 'runs'

    def fake_case(self, p, definition, seed, folder):
        c.save(folder / 'response.json', {'fixture': True, 'id': definition['id']})
        result = {'status': 'MEASURED', 'assessment': {'passed': True}}
        if definition['kind'] == 'speed': result['metrics'] = {'ttft_seconds': 0.1}
        return result

    def test_plan_read_only_and_no_other_models(self):
        with patch.object(k, 'wire', side_effect=AssertionError('no transport')):
            plan = k.plan(PROFILE)
        self.assertFalse(plan['other_models_required'])
        self.assertIn('BLOCKED', plan['coding'])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_reject_profile_drift_unknown_remote_and_context_reduction(self):
        for change in ({'model': 'mistral'}, {'base_url': 'https://example.com/v1'}, {'context_tokens': 8192}, {'extra': True}, {'temperature': float('nan')}, {'max_tokens': True}):
            with self.subTest(change=change), self.assertRaises(c.Blocked):
                k.validate(dict(PROFILE, **change))

    def test_exact_whole_answer_not_reasoning_substring(self):
        case = k.QUALITY[0]
        self.assertTrue(k.score(case, response('READY'))['passed'])
        self.assertFalse(k.score(case, response('READY but also a sentence'))['passed'])
        self.assertFalse(k.score(case, response('READY', 'length'))['passed'])
        self.assertFalse(k.score(case, response(None))['passed'])

    def test_json_schema_and_no_bool_number_equivalence(self):
        case = {'scorer': 'json', 'expected': {'count': 1}}
        self.assertFalse(k.score(case, response('{"count":true}'))['passed'])
        self.assertFalse(k.score(case, response('```json\n{"count":1}\n```'))['passed'])
        self.assertTrue(k.score(case, response('{"count":1}'))['passed'])
        self.assertFalse(k.score(case, response('{"count":0,"count":1}'))['passed'])
        self.assertFalse(k.score(case, response('{"count":NaN}'))['passed'])

    def test_backend_requires_exact_context_and_single_model(self):
        models = {'data': [{'id': 'kolibri-1', 'max_model_len': 8192, 'root': 'fixture', 'created': 1}]}
        with patch.object(k, 'wire', return_value=models), self.assertRaisesRegex(c.Blocked, 'Context'):
            k.backend(PROFILE)

    def test_dynamic_api_creation_time_is_not_process_identity(self):
        row = {'id': 'kolibri-1', 'root': '/fixture/model', 'max_model_len': 262144}
        with patch.object(k, 'wire', side_effect=[{'data': [dict(row, created=1)]}, {'version': 'fixture'},
                                                {'data': [dict(row, created=2)]}, {'version': 'fixture'}]), patch.object(k, 'service_identity', return_value={'MainPID': '42', 'process_start_ticks': '100'}):
            self.assertEqual(k.backend(PROFILE), k.backend(PROFILE))

    def test_tools_dispatch_denies_arbitrary_functions_and_arguments(self):
        call = {'id': 'c1', 'type': 'function', 'function': {'name': 'add', 'arguments': '{"a":173,"b":269}'}}
        self.assertEqual(k.tool_result(k.TOOL_CASES[0], call, 'opaque'), '442')
        call['function']['name'] = 'os.system'
        with self.assertRaises(c.Blocked): k.tool_result(k.TOOL_CASES[0], call, 'opaque')
        call['function'] = {'name': 'add', 'arguments': '{"a":173,"b":269,"shell":"ls"}'}
        with self.assertRaises(c.Blocked): k.tool_result(k.TOOL_CASES[0], call, 'opaque')

    def test_real_dispatch_then_model_followup_uses_actual_result(self):
        definition = dict(k.TOOL_CASES[0], kind='tools')
        call = {'id': 'c1', 'type': 'function', 'function': {'name': 'add', 'arguments': '{"a":173,"b":269}'}}
        with patch.object(k, 'completion', side_effect=[response(None, 'tool_calls', [call]), response('442')]) as model:
            result = k.run_case(PROFILE, definition, 1, self.root)
        self.assertTrue(result['assessment']['passed'])
        self.assertTrue(c.read(self.root / 'tool.json')['executed'])
        self.assertEqual(model.call_args_list[1].args[1]['messages'][-1]['content'], '442')
        self.assertEqual(model.call_count, 2)

    def test_unexecuted_tool_cannot_count_as_pass(self):
        with patch.object(k, 'completion', return_value=response('442')):
            result = k.run_case(PROFILE, dict(k.TOOL_CASES[0], kind='tools'), 1, self.root)
        self.assertEqual(result['status'], 'ERROR')
        self.assertFalse((self.root / 'tool.json').exists())

    def test_smoke_completed_reuse_has_zero_network_and_model_calls(self):
        with patch.object(k, 'backend', return_value=BACKEND), patch.object(k, 'run_case', side_effect=self.fake_case) as cases:
            first = k.run(PROFILE, self.output, 'smoke', True)
            self.assertEqual(cases.call_count, 4)
        self.assertEqual(first['status'], 'COMPLETED')
        with patch.object(k, 'backend', side_effect=AssertionError('no live metadata')), patch.object(k, 'run_case', side_effect=AssertionError('no replay')):
            again = k.run(PROFILE, self.output, 'smoke', True)
            verified = k.verify(self.output, 'smoke', PROFILE, True)
        self.assertEqual(again['status'], 'COMPLETED'); self.assertEqual(verified['model_requests_issued'], 0)

    def test_corrupt_evidence_rejected_before_any_model_call(self):
        with patch.object(k, 'backend', return_value=BACKEND), patch.object(k, 'run_case', side_effect=self.fake_case):
            k.run(PROFILE, self.output, 'tamper', True)
        target = next((self.output / 'tamper/cases').glob('*/response.json')); target.write_text('{}')
        with patch.object(k, 'backend', side_effect=AssertionError('no model')), self.assertRaisesRegex(c.Blocked, 'evidence changed'):
            k.run(PROFILE, self.output, 'tamper', True)

    def test_interrupted_request_not_replayed(self):
        with patch.object(k, 'backend', return_value=BACKEND), patch.object(k, 'run_case', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt): k.run(PROFILE, self.output, 'interrupted', True)
        with patch.object(k, 'run_case', side_effect=AssertionError('no replay')), self.assertRaisesRegex(c.Blocked, 'Uncertain'):
            k.run(PROFILE, self.output, 'interrupted', True)

    def test_partial_run_resumes_only_pending_cases(self):
        groups = k.definitions(PROFILE, True)
        with patch.object(k, 'backend', return_value=BACKEND), patch.object(k, 'definitions', return_value=groups[:1]), patch.object(k, 'run_case', side_effect=self.fake_case):
            k.run(PROFILE, self.output, 'partial', True)
        # Simulate a clean checkpoint between groups, not an in-flight request.
        file = self.output / 'partial/state.json'; state = c.read(file); state.pop('coding')
        for group in groups[1:]:
            for definition in group: state['cases'][definition['id']] = {'status': 'PENDING', 'definition': definition}
        c.save(file, state)
        with patch.object(k, 'backend', return_value=BACKEND), patch.object(k, 'run_case', side_effect=self.fake_case) as cases:
            result = k.run(PROFILE, self.output, 'partial', True)
        self.assertEqual(cases.call_count, 3); self.assertEqual(result['status'], 'COMPLETED')

    def test_model_restart_blocks_partial_run(self):
        state = {'schema_version': 1, 'run_id': 'changed', 'identity': k.identity(PROFILE, True), 'backend': BACKEND,
                 'cases': {d['id']: {'status': 'PENDING', 'definition': d} for group in k.definitions(PROFILE, True) for d in group}}
        folder = k.folder_for(self.output, 'changed'); c.save(folder / 'state.json', state)
        with patch.object(k, 'backend', return_value=dict(BACKEND, created=43)), patch.object(k, 'run_case', side_effect=AssertionError('no trial')), self.assertRaisesRegex(c.Blocked, 'instance changed'):
            k.run(PROFILE, self.output, 'changed', True)

    def test_full_diagnostics_do_not_fabricate_coding_success(self):
        with patch.object(k, 'backend', return_value=BACKEND), patch.object(k, 'run_case', side_effect=self.fake_case):
            result = k.run(PROFILE, self.output, 'no-coding')
        self.assertEqual(result['status'], 'PARTIAL')
        self.assertEqual(result['dimensions']['P4 Melusense coding']['status'], 'BLOCKED')
        self.assertEqual(result['dimensions']['P2 answer quality']['attempts'], 24)

    def test_changed_sampling_cannot_reuse_result(self):
        with patch.object(k, 'backend', return_value=BACKEND), patch.object(k, 'run_case', side_effect=self.fake_case):
            k.run(PROFILE, self.output, 'profile', True)
        with self.assertRaisesRegex(c.Blocked, 'different profile'):
            k.run(dict(PROFILE, temperature=0.5), self.output, 'profile', True)

    def test_stream_parser_handles_split_utf8_and_requires_done(self):
        events = [dict(model='kolibri-1', choices=[{'delta': {'role': 'assistant'}}]),
                  dict(model='kolibri-1', choices=[{'delta': {'content': 'café'}}]),
                  dict(model='kolibri-1', choices=[], usage={'completion_tokens': 2})]
        data = ''.join('data: ' + json.dumps(row, ensure_ascii=False) + '\r\n\r\n' for row in events).encode() + b'data: [DONE]\n\n'
        connection = Mock(); response = connection.getresponse.return_value
        response.status = 200; response.getheader.return_value = 'text/event-stream; charset=utf-8'
        # One byte at a time, including the split multibyte accent.
        response.read1.side_effect = [bytes([value]) for value in data] + [b'']
        with patch.object(k.http.client, 'HTTPConnection', return_value=connection):
            result = k.wire(PROFILE, '/v1/chat/completions', {'stream': True}, True)
        self.assertEqual(result['deltas'], [{'content': 'café'}])
        self.assertIsNotNone(result['ttft_seconds']); connection.close.assert_called_once()
        response.read1.side_effect = [data.split(b'data: [DONE]')[0], b'']
        with patch.object(k.http.client, 'HTTPConnection', return_value=connection), self.assertRaisesRegex(c.Blocked, 'Incomplete SSE'):
            k.wire(PROFILE, '/v1/chat/completions', {'stream': True}, True)

    def test_transport_denies_redirects_and_unapproved_paths(self):
        connection = Mock(); connection.getresponse.return_value.status = 302
        with patch.object(k.http.client, 'HTTPConnection', return_value=connection), self.assertRaisesRegex(c.Blocked, 'HTTP 302'):
            k.wire(PROFILE, '/v1/models')
        self.assertEqual(connection.request.call_count, 1); connection.close.assert_called_once()
        with patch.object(k.http.client, 'HTTPConnection') as transport, self.assertRaisesRegex(c.Blocked, 'Endpoint denied'):
            k.wire(PROFILE, '/admin')
        transport.assert_not_called()

    def test_response_size_limit_and_cleanup(self):
        connection = Mock(); response = connection.getresponse.return_value
        response.status = 200; response.read1.side_effect = [b'x' * 65, b'']
        with patch.object(k.http.client, 'HTTPConnection', return_value=connection), patch.object(k, 'LIMIT', 64), self.assertRaisesRegex(c.Blocked, 'too large'):
            k.wire(PROFILE, '/v1/models')
        connection.close.assert_called_once()

    def test_model_error_remains_in_denominator_and_report_is_partial(self):
        def cases(p, definition, seed, folder):
            if definition['id'].startswith('p2-instruction'):
                c.save(folder / 'error.json', {'fixture': 'HTTP failure'})
                return {'status': 'ERROR', 'reason': 'fixture transport failure'}
            return self.fake_case(p, definition, seed, folder)
        with patch.object(k, 'backend', return_value=BACKEND), patch.object(k, 'run_case', side_effect=cases):
            report = k.run(PROFILE, self.output, 'error', True)
        self.assertEqual(report['status'], 'PARTIAL')
        self.assertEqual(report['dimensions']['P2 answer quality']['fraction'], 0.5)
        self.assertEqual(report['dimensions']['P2 answer quality']['errors'], 1)

    def test_actual_coding_controller_delegation_is_not_self_awarded_pass(self):
        from modelbench import pipeline
        config = c.read(k.ROOT / 'config/benchmark.example.json')
        config['deployment']['enabled'] = False
        for spec in config['benchmarks'].values(): spec['enabled'] = False
        file = self.root / 'coding-config.json'; c.save(file, config)
        profile = dict(PROFILE, coding_config={'path': str(file), 'sha256': c.digest(file)})
        with patch.object(k, 'backend', return_value=BACKEND), patch.object(k, 'run_case', side_effect=self.fake_case), patch.object(pipeline, 'run', return_value={'status': 'PARTIAL'}) as delegate:
            report = k.run(profile, self.output, 'delegate')
        self.assertEqual(delegate.call_count, 1)
        self.assertEqual(report['status'], 'PARTIAL')
        self.assertEqual(report['dimensions']['P4 Melusense coding']['status'], 'PARTIAL')


if __name__ == '__main__': unittest.main()
