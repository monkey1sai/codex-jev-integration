"""Offline candidate acceptance. Run only after coordinator review."""
import importlib.util
import json
import multiprocessing
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

CANDIDATE = Path(__file__).parent / 'payload' / 'jev' / 'decision.py'


def load_candidate():
    spec = importlib.util.spec_from_file_location('phase2a_candidate', CANDIDATE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def concurrent_append(config, workspace, ready, start, queue):
    module = load_candidate()
    ready.put(True)
    start.wait(10)
    queue.put(module.route({'workspace': workspace, 'task_summary': 'synthetic', 'stage': 'before_delivery'}, Path(config))['observation']['status'])


class Phase2A(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / 'workspace'
        self.workspace.mkdir()
        self.config = self.root / 'config.json'
        self.module = load_candidate()
        self.obs = self.module._journal_module()
        self.write_config()
        self.args = {'workspace': str(self.workspace), 'task_summary': 'synthetic confidential summary marker'}

    def write_config(self, **updates):
        data = {'enabled': True, 'confidence_threshold': .8, 'timeout_seconds': 20,
                'observability': {'enabled': True, 'max_records': 1000, 'max_bytes': 2097152}}
        data.update(updates)
        self.config.write_text(json.dumps(data), encoding='utf-8')

    def local(self, data):
        directory = self.workspace / '.codex'
        directory.mkdir(exist_ok=True)
        (directory / 'jev.json').write_text(json.dumps(data), encoding='utf-8')

    def answer(self, confidence=.9):
        probs = {role: (.9 if role == 'implement' else .025) for role in self.module.ROLES}
        return self.module.validate_answer({'model': 'jev-test', 'answers': {'route': {
            'type': 'choice', 'choice': 'implement', 'confidence': confidence, 'probabilities': probs}}})

    def route(self, **updates):
        return self.module.route({**self.args, **updates}, self.config, lambda *_: self.answer())

    def rows(self):
        path = self.root / 'audit' / 'decisions.jsonl'
        return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]

    def report(self, oid, **updates):
        return self.module.report_outcome({'workspace': str(self.workspace), 'observation_id': oid, **updates}, self.config)

    def test_success_and_allowlist_privacy(self):
        result = self.route()
        self.assertEqual((result['route'], result['model'], result['reasoning_effort']), ('implement', 'gpt-6.1-sol', 'medium'))
        self.assertFalse(result['executed'])
        row = self.rows()[0]
        self.assertEqual(set(row), self.obs.DECISION)
        self.assertTrue(self.obs._valid_record(row))
        raw = json.dumps(row)
        self.assertNotIn(self.args['task_summary'], raw)
        self.assertNotIn(str(self.workspace), raw)
        self.assertNotIn('summary', raw)
        self.assertEqual(row['usage'], {'input_tokens': None, 'output_tokens': None})
        self.assertEqual(row['usage_status'], 'unknown')
        self.assertEqual(row['provider_model'], 'jev-test')

    def test_recorded_time_and_used_configuration_provenance(self):
        self.local({'confidence_threshold': .85, 'timeout_seconds': 5})
        self.route()
        row = self.rows()[0]
        self.assertEqual(row['routing_config'], {'enabled': True, 'confidence_threshold': .85,
                                                'timeout_seconds': 5, 'workspace_override': True})
        self.assertEqual(row['config_version'], self.obs._config_version(row['routing_config']))
        self.assertRegex(row['recorded_at'], r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z$')
        self.route(stage='before_delivery')
        gate = self.rows()[-1]
        self.assertIsNone(gate['routing_config'])
        self.assertIsNone(gate['config_version'])

    def test_gates_precede_config_workspace_credentials(self):
        self.config.write_text('broken', encoding='utf-8')
        for update in ({'stage': 'before_delivery'}, {'stage': 'before_plan', 'large_plan': True}, {'failure_count': 2}):
            result = self.module.route({**self.args, 'workspace': str(self.root / 'missing'), **update}, self.config,
                                       lambda *_: self.fail('gate invoked evaluator'))
            self.assertTrue(result['required_review'])
            self.assertEqual(result['reason'], 'DETERMINISTIC_REVIEW_GATE')
            self.assertEqual(result['observation']['status'], 'invalid_config')

    def test_all_route_branches(self):
        self.assertEqual(self.route(stage='before_delivery')['observation']['status'], 'written')
        self.write_config(enabled=False)
        result = self.module.route(self.args, self.config, lambda *_: self.fail('disabled invoked evaluator'))
        self.assertEqual(result['reason'], 'JEV_DISABLED')
        self.write_config(unrecognized=True)
        self.assertEqual(self.route()['reason'], 'UNKNOWN_CONFIG_FIELD')
        self.write_config()
        for code in ('AUTH_MISSING', 'HTTP_401', 'HTTP_429', 'TIMEOUT', 'INVALID_RESPONSE'):
            def failed(*_, fixed=code):
                raise self.module.SafeFailure(fixed)
            result = self.module.route(self.args, self.config, failed)
            self.assertEqual(result['route'], 'coordinate')
            self.assertEqual(result['observation']['status'], 'written')
        result = self.module.route(self.args, self.config, lambda *_: self.answer(.79))
        self.assertEqual(result['reason'], 'LOW_CONFIDENCE')
        result = self.module.route(self.args, self.config, lambda *_: self.answer(.8))
        self.assertEqual(result['reason'], 'JEV_CHOICE')

    def test_bad_observation_settings_leave_routes_and_gates(self):
        for value in (None, [], {'enabled': 1}, {'enabled': True, 'path': 'escape'},
                      {'enabled': True, 'max_records': 0}, {'enabled': True, 'max_bytes': 2097153}):
            self.write_config(observability=value)
            self.assertEqual(self.route()['route'], 'implement')
            result = self.route(stage='before_delivery')
            self.assertTrue(result['required_review'])
            self.assertEqual(result['observation']['status'], 'invalid_config')

    def test_workspace_lowering_and_reenable_rejected(self):
        original = self.config.read_bytes()
        self.local({'observability': {'enabled': False}})
        self.assertEqual(self.route()['observation']['status'], 'disabled')
        self.assertEqual(self.config.read_bytes(), original)
        self.write_config(observability={'enabled': False, 'max_records': 3, 'max_bytes': 4096})
        self.local({'observability': {'enabled': True}})
        self.assertEqual(self.route()['observation']['status'], 'invalid_config')
        self.write_config(observability={'enabled': True, 'max_records': 3, 'max_bytes': 4096})
        for override in ({'max_records': 4}, {'max_bytes': 4097}, {'path': 'outside'}):
            self.local({'observability': override})
            self.assertEqual(self.route()['observation']['status'], 'invalid_config')
        self.local({'observability': {'max_records': 1, 'max_bytes': 1024}})
        self.assertEqual(self.route()['observation']['status'], 'written')
        self.assertEqual(self.route()['observation']['status'], 'full')

    def test_original_workspace_enabled_override(self):
        self.write_config(enabled=False)
        self.local({'enabled': True})
        self.assertEqual(self.route()['route'], 'implement')
        self.local({'enabled': False})
        self.assertEqual(self.route()['reason'], 'JEV_DISABLED')

    def test_usage_exact_validation(self):
        response = {'model': 'jev-test', 'answers': {'route': {'type': 'choice', 'choice': 'implement', 'confidence': .9,
                    'probabilities': {r: (.9 if r == 'implement' else .025) for r in self.module.ROLES}}}}
        for usage in ({}, {'input_tokens': 0, 'output_tokens': (1 << 63) - 1, 'secret': 'discard'}):
            value = self.module.validate_answer({**response, 'usage': usage})
            self.assertEqual(set(value['usage']), {'input_tokens', 'output_tokens'})
        for usage in (None, [], {'input_tokens': True}, {'output_tokens': -1}, {'input_tokens': 1.2}, {'output_tokens': 1 << 63}):
            value = self.module.validate_answer({**response, 'usage': usage})
            self.assertEqual(value['choice'], 'implement')
            self.assertEqual(value['usage'], {'input_tokens': None, 'output_tokens': None})
            self.assertEqual(value['usage_status'], 'invalid')
        self.assertEqual(self.module.validate_answer(response)['usage_status'], 'unknown')
        self.assertEqual(self.module.validate_answer({**response, 'usage': {'input_tokens': 0}})['usage_status'], 'partial')
        self.assertEqual(self.module.validate_answer({**response, 'usage': {'input_tokens': 0, 'output_tokens': 0}})['usage_status'], 'provided')
        for observation_enabled in (False, True):
            self.write_config(observability={'enabled': observation_enabled})
            value = self.module.route(self.args, self.config, lambda *_: self.module.validate_answer(
                {**response, 'usage': {'input_tokens': True}}))
            self.assertEqual(value['route'], 'implement')
            self.assertEqual(value['judgment']['usage_status'], 'invalid')
            self.assertEqual(value['observation']['status'], 'written' if observation_enabled else 'disabled')

    def test_original_answer_validation(self):
        response = {'model': 'jev-test', 'answers': {'route': {'type': 'choice', 'choice': 'implement', 'confidence': .9,
                    'probabilities': {r: (.9 if r == 'implement' else .025) for r in self.module.ROLES}}}}
        for confidence in (True, float('nan'), float('inf'), -1, 1.1):
            bad = json.loads(json.dumps(response))
            bad['answers']['route']['confidence'] = confidence
            with self.assertRaises(self.module.SafeFailure):
                self.module.validate_answer(bad)
        for model in ('private/path', 'gpt-6.1-sol', 'jev-' + 'x' * 49):
            with self.assertRaises(self.module.SafeFailure):
                self.module.validate_answer({**response, 'model': model})

    def test_record_byte_caps_no_rewrite(self):
        self.write_config(observability={'enabled': True, 'max_records': 1, 'max_bytes': 2097152})
        self.route()
        path = self.root / 'audit' / 'decisions.jsonl'
        old = path.read_bytes()
        self.assertEqual(self.route()['observation']['status'], 'full')
        self.assertEqual(path.read_bytes(), old)
        self.write_config(observability={'enabled': True, 'max_records': 1000, 'max_bytes': 1024})
        self.assertEqual(self.route()['observation']['status'], 'full')
        self.assertEqual(path.read_bytes(), old)

    def test_corruption_preserved(self):
        self.route()
        path = self.root / 'audit' / 'decisions.jsonl'
        for raw in (b'broken\n', b'{}\n', b'{}', b'{"private":"secret"}\n'):
            path.write_bytes(raw)
            self.assertEqual(self.route()['observation']['status'], 'corrupt')
            self.assertEqual(path.read_bytes(), raw)

    def test_lock_conflict(self):
        with self.obs._locked(self.config, True):
            self.assertEqual(self.route()['observation']['status'], 'locked')
        self.assertEqual(self.route()['observation']['status'], 'written')

    def test_directory_regular_file_rejected(self):
        (self.root / 'audit').write_text('keep', encoding='utf-8')
        self.assertEqual(self.route()['observation']['status'], 'unsafe_path')
        self.assertEqual((self.root / 'audit').read_text(), 'keep')

    def test_journal_directory_rejected(self):
        (self.root / 'audit').mkdir()
        (self.root / 'audit' / 'decisions.jsonl').mkdir()
        self.assertEqual(self.route()['observation']['status'], 'unsafe_path')

    def test_real_hardlinks_rejected_without_target_changes(self):
        directory = self.root / 'audit'
        directory.mkdir()
        for name in ('decisions.jsonl', 'decisions.lock'):
            with self.subTest(name=name):
                outside = self.root / ('outside-' + name)
                original = b'external ordinary file must remain unchanged\n'
                outside.write_bytes(original)
                linked = directory / name
                os.link(outside, linked)
                self.assertEqual(outside.stat().st_nlink, 2)
                self.assertEqual(self.route()['observation']['status'], 'unsafe_path')
                self.assertEqual(outside.read_bytes(), original)
                self.assertEqual(linked.read_bytes(), original)
                # Only task-created fixture links are removed between subcases.
                linked.unlink()
                if name == 'decisions.jsonl':
                    # The rejected journal attempt may have created its fixed lock.
                    lock = directory / 'decisions.lock'
                    if lock.exists():
                        lock.unlink()

    def test_reparse_and_symlink_escape(self):
        # Synthetic Windows reparse attributes are deterministic without admin rights.
        class Reparse:
            st_mode = 0o100600
            st_file_attributes = 0x400
        with patch.object(Path, 'lstat', return_value=Reparse()):
            with self.assertRaisesRegex(self.obs.JournalFailure, 'unsafe_path'):
                self.obs._safe(self.root / 'synthetic')
        outside = self.root / 'outside'
        outside.mkdir()
        try:
            (self.root / 'audit').symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('host symlink privilege unavailable; reparse rejection verified above')
        self.assertEqual(self.route()['observation']['status'], 'unsafe_path')
        self.assertFalse((outside / 'decisions.jsonl').exists())

    def test_workspace_config_escape(self):
        outside = self.root / 'outside.json'
        outside.write_text('{"enabled":true}', encoding='utf-8')
        (self.workspace / '.codex').mkdir()
        try:
            (self.workspace / '.codex' / 'jev.json').symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest('host symlink privilege unavailable')
        self.assertEqual(self.route()['reason'], 'WORKSPACE_CONFIG_ESCAPES_ROOT')
        self.assertTrue(self.route(stage='before_delivery')['required_review'])

    def test_observation_exception_cannot_fail_route(self):
        with patch.object(self.module, '_journal_module', side_effect=RuntimeError('private error')):
            result = self.route(stage='before_delivery')
        self.assertEqual(result['observation'], {'status': 'io_error'})
        self.assertTrue(result['required_review'])

    def test_outcome_idempotence_conflict_and_provenance(self):
        oid = self.route()['observation']['id']
        result = self.report(oid, result='completed', reported_model='gpt-6-luna', elapsed_ms=100)
        self.assertFalse(result['execution_verified'])
        self.assertTrue(result['advisory_only'])
        self.assertEqual(result['provenance'], 'caller_reported')
        before = (self.root / 'audit' / 'decisions.jsonl').read_bytes()
        self.assertEqual(self.report(oid, result='completed', reported_model='gpt-6-luna', elapsed_ms=100)['status'], 'duplicate')
        self.assertEqual((self.root / 'audit' / 'decisions.jsonl').read_bytes(), before)
        with self.assertRaisesRegex(self.module.SafeFailure, 'OUTCOME_CONFLICT'):
            self.report(oid, result='failed')
        self.assertEqual((self.root / 'audit' / 'decisions.jsonl').read_bytes(), before)
        outcome = self.rows()[1]
        self.assertEqual(set(outcome), self.obs.OUTCOME)
        self.assertEqual(outcome['reported_route'], 'unknown')
        self.assertNotIn('approval', outcome)
        self.assertNotIn('test_pass', outcome)

    def test_outcome_workspace_unknown_and_invalid(self):
        oid = self.route()['observation']['id']
        other = self.root / 'other'
        other.mkdir()
        with self.assertRaisesRegex(self.module.SafeFailure, 'OBSERVATION_NOT_FOUND'):
            self.module.report_outcome({'workspace': str(other), 'observation_id': oid}, self.config)
        with self.assertRaisesRegex(self.module.SafeFailure, 'OBSERVATION_NOT_FOUND'):
            self.report(str(uuid.uuid4()))
        for fields in ({'notes': 'secret'}, {'elapsed_ms': True}, {'elapsed_ms': -1}, {'elapsed_ms': 1 << 63},
                       {'reported_model': 'jev-test'}, {'result': 'PASS'}, {'reported_route': 'admin'}):
            with self.assertRaises(self.module.SafeFailure):
                self.report(oid, **fields)

    def test_status_no_writes_and_capacity(self):
        before = set(self.root.rglob('*'))
        status = self.module.status({'workspace': str(self.workspace)}, self.config)
        self.assertEqual(set(self.root.rglob('*')), before)
        self.assertEqual(status['observability']['records'], 0)
        self.route()
        raw = (self.root / 'audit' / 'decisions.jsonl').read_bytes()
        status = self.module.status({'workspace': str(self.workspace)}, self.config)
        self.assertEqual(status['observability']['records'], 1)
        self.assertEqual((self.root / 'audit' / 'decisions.jsonl').read_bytes(), raw)

    def test_config_original_validation(self):
        for updates in ({'enabled': 1}, {'confidence_threshold': True}, {'timeout_seconds': float('inf')}, {'timeout_seconds': 21}, {'unknown': 1}):
            self.write_config(**updates)
            result = self.route()
            self.assertEqual(result['route'], 'coordinate')
        with self.assertRaises(self.module.SafeFailure):
            self.route(unknown=True)

    def test_multiprocess_capacity_and_complete_rows(self):
        self.write_config(observability={'enabled': True, 'max_records': 3, 'max_bytes': 2097152})
        ctx = multiprocessing.get_context('spawn')
        ready, queue, start = ctx.Queue(), ctx.Queue(), ctx.Event()
        processes = [ctx.Process(target=concurrent_append, args=(str(self.config), str(self.workspace), ready, start, queue)) for _ in range(8)]
        try:
            for process in processes:
                process.start()
            for _ in processes:
                self.assertTrue(ready.get(timeout=20))
            start.set()
            results = [queue.get(timeout=20) for _ in processes]
            for process in processes:
                process.join(timeout=20)
                self.assertEqual(process.exitcode, 0)
            self.assertTrue(set(results) <= {'written', 'locked', 'full'})
            rows = self.rows()
            self.assertGreaterEqual(len(rows), 1)
            self.assertLessEqual(len(rows), 3)
            self.assertEqual(len({row['observation_id'] for row in rows}), len(rows))
            self.assertTrue(all(self.obs._valid_record(row) for row in rows))
        finally:
            for process in processes:
                if process.is_alive():
                    process.terminate()
                process.join(timeout=5)

    def test_stdio_three_tools_disabled_gate_report_and_cli(self):
        self.write_config(enabled=False)
        oid = self.route(stage='before_delivery')['observation']['id']
        messages = [
            {'id': 1, 'method': 'tools/list'},
            {'id': 2, 'method': 'tools/call', 'params': {'name': 'jev_route', 'arguments': self.args}},
            {'id': 3, 'method': 'tools/call', 'params': {'name': 'jev_route', 'arguments': {**self.args, 'stage': 'before_delivery'}}},
            {'id': 4, 'method': 'tools/call', 'params': {'name': 'jev_report_outcome', 'arguments': {'workspace': str(self.workspace), 'observation_id': oid}}},
            {'id': 5, 'method': 'tools/call', 'params': {'name': 'jev_report_outcome', 'arguments': {'workspace': str(self.workspace), 'observation_id': oid, 'notes': 'private'}}},
        ]
        # Absolute Python path needs no PATH; these names are OS/temp runtime inputs.
        # Enumerate only the explicit safe names, never environment values in bulk.
        runtime_env = {name: os.environ[name] for name in ('SystemRoot', 'WINDIR', 'TEMP', 'TMP') if name in os.environ}
        run = subprocess.run([sys.executable, '-B', str(CANDIDATE), 'serve', '--config', str(self.config)],
                             input=''.join(json.dumps(msg) + '\n' for msg in messages), capture_output=True, text=True,
                             timeout=20, env=runtime_env)
        self.assertEqual(run.returncode, 0, run.stderr)
        answers = [json.loads(line) for line in run.stdout.splitlines()]
        self.assertEqual({tool['name'] for tool in answers[0]['result']['tools']}, {'jev_status', 'jev_route', 'jev_report_outcome', 'jev_select_resources', 'jev_decide', 'jev_report_selection_outcome'})
        values = [json.loads(answer['result']['content'][0]['text']) for answer in answers[1:4]]
        self.assertEqual(values[0]['reason'], 'JEV_DISABLED')
        self.assertTrue(values[1]['required_review'])
        self.assertFalse(values[2]['execution_verified'])
        self.assertTrue(answers[4]['result']['isError'])
        self.assertEqual(answers[4]['result']['content'][0]['text'], 'JEV_TOOL_INPUT_OR_CONFIG_ERROR')
        cli = subprocess.run([sys.executable, '-B', str(CANDIDATE), 'report-outcome', '--config', str(self.config)],
                             input=json.dumps({'workspace': str(self.workspace), 'observation_id': oid}), capture_output=True,
                             text=True, timeout=20, env=runtime_env)
        self.assertEqual(cli.returncode, 0, cli.stderr)
        self.assertEqual(json.loads(cli.stdout)['status'], 'duplicate')


if __name__ == '__main__':
    unittest.main(verbosity=2)
