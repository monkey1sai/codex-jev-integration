"""Offline combined choice and versioned outcome acceptance. No live provider."""
import copy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


MODULE = Path(__file__).parent / 'payload/jev/decision.py'
spec = importlib.util.spec_from_file_location('combined_candidate', MODULE)
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)


def candidate(resource_id, kind='tool', **updates):
    row = {'id': resource_id, 'kind': kind, 'description': 'Read synthetic evidence',
           'available': True, 'in_scope': True, 'when_to_use': 'Inspect local synthetic input',
           'limits': ['No external writes'], 'requires': [], 'conflicts': []}
    row.update(updates)
    return row


class CombinedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / 'workspace'
        self.workspace.mkdir()
        self.config = self.root / 'config.json'
        self.write_config()
        self.args = {'workspace': str(self.workspace), 'task_summary': 'Read synthetic local evidence',
            'inventory': {'captured_at': datetime.now(timezone.utc).isoformat(), 'version': 'a' * 64},
            'context': {'goal': 'Locate synthetic symbol', 'success_criteria': ['Find its definition'],
                        'environment': ['Synthetic local fixture'], 'constraints': ['Read only'],
                        'evidence': ['Input contains the symbol'], 'unknowns': [], 'critical_unknowns': []},
            'candidates': [candidate('required', 'skill'), candidate('read')], 'required_ids': ['required']}
        self.calls = []
        self.journal = d._resource_journal_module()

    def write_config(self, **updates):
        config = {'enabled': True, 'confidence_threshold': .8, 'timeout_seconds': 20,
                  'observability': {'enabled': True, 'max_records': 100, 'max_bytes': 524288}}
        config.update(updates)
        self.config.write_text(json.dumps(config), encoding='utf-8')

    def requester(self, choices=None, confidence=None, invalid=None):
        def request(body, config):
            self.calls.append(copy.deepcopy(body))
            answers = {}
            for key, question in body['questions'].items():
                chosen = (choices or {}).get(key, {'context': 'sufficient', 'role': 'explore'}.get(key, 'read'))
                answers[key] = {'type': 'choice', 'choice': chosen,
                    'confidence': (confidence or {}).get(key, .99),
                    'probabilities': {option: int(option == chosen) for option in question['criteria']}}
            if invalid:
                answers[invalid]['choice'] = 'not_an_option'
            return {'model': 'jev-test', 'answers': answers, 'usage': {'input_tokens': 200, 'output_tokens': 20}}
        return request

    def run_decision(self, args=None, **request_options):
        return d.decide(self.args if args is None else args, self.config, self.requester(**request_options))

    def ids(self, result):
        return [x['id'] for x in result['selected']]

    def test_unknown_dependency_never_calls_provider(self):
        self.args['candidates'][1]['requires'] = ['missing']
        with self.assertRaisesRegex(d.SafeFailure, 'UNKNOWN_RESOURCE_REFERENCE'):
            self.run_decision()
        self.assertEqual(self.calls, [])

    def test_long_context_missing_environment_zero_provider(self):
        del self.args['context']['environment']
        self.args['context']['goal'] = 'long' * 200
        result = self.run_decision()
        self.assertEqual(result['reason'], 'INSUFFICIENT_CONTEXT')
        self.assertIn('environment', result['missing_fields'])
        self.assertEqual(self.calls, [])
        self.assertEqual(self.ids(result), ['required'])

    def test_critical_unknown_blocks_before_provider(self):
        self.args['context']['critical_unknowns'] = ['Whether external resources are authorized']
        self.assertEqual(self.run_decision()['reason'], 'INSUFFICIENT_CONTEXT')
        self.assertEqual(self.calls, [])

    def test_one_shared_request_and_required_preserved(self):
        result = self.run_decision()
        self.assertEqual(result['reason'], 'COMBINED_SELECTION')
        self.assertEqual(len(self.calls), 1)
        body = self.calls[0]
        self.assertEqual(body['state']['eligible_candidates'], self.args['candidates'])
        self.assertEqual(body['state']['required_ids'], ['required'])
        self.assertEqual(body['state']['context'], self.args['context'])
        self.assertEqual(set(body['questions']), {'context', 'role', 'tool'})
        self.assertTrue(all(q['type'] == 'choice' for q in body['questions'].values()))
        self.assertEqual(self.ids(result), ['required', 'read'])
        self.assertFalse(result['executed'])

    def test_insufficient_overrides_high_confidence_optional(self):
        result = self.run_decision(choices={'context': 'insufficient'})
        self.assertEqual(result['reason'], 'INSUFFICIENT_CONTEXT')
        self.assertEqual(self.ids(result), ['required'])
        self.assertTrue(result['provider_called'])
        self.assertEqual(result['usage']['output_tokens'], 20)

    def test_low_confidence_discards_optional(self):
        for key in ['context', 'role', 'tool']:
            with self.subTest(key=key):
                result = self.run_decision(confidence={key: .1})
                self.assertEqual(self.ids(result), ['required'])
                self.assertEqual(result['reason'], 'INSUFFICIENT_CONTEXT' if key == 'context' else 'LOW_CONFIDENCE')

    def test_any_illegal_answer_discards_all_optional(self):
        for key in ['context', 'role', 'tool']:
            with self.subTest(key=key):
                result = self.run_decision(invalid=key)
                self.assertEqual(result['reason'], 'INVALID_RESOURCE_RESPONSE')
                self.assertEqual(self.ids(result), ['required'])
                self.assertNotEqual(result.get('provider_called'), True)

    def test_disabled_and_review_gate_zero_provider(self):
        self.write_config(enabled=False)
        self.assertEqual(self.run_decision()['reason'], 'JEV_DISABLED')
        for updates in [{'stage': 'before_plan', 'large_plan': True}, {'failure_count': 2}, {'stage': 'before_delivery'}]:
            result = self.run_decision({**self.args, **updates})
            self.assertEqual(result['reason'], 'DETERMINISTIC_REVIEW_GATE')
            self.assertTrue(result['required_review'])
        self.assertEqual(self.calls, [])

    def test_stale_inventory_zero_provider(self):
        self.args['inventory']['captured_at'] = (datetime.now(timezone.utc) - timedelta(seconds=301)).isoformat()
        self.assertEqual(self.run_decision()['reason'], 'STALE_INVENTORY')
        self.assertEqual(self.calls, [])

    def test_dependency_and_conflict_reject_proposal(self):
        for field in ['requires', 'conflicts']:
            args = copy.deepcopy(self.args)
            if field == 'requires':
                args['candidates'].append(candidate('alternative'))
                args['candidates'][1][field] = ['alternative']
            else:
                args['candidates'][1][field] = ['required']
            result = self.run_decision(args)
            self.assertEqual(result['reason'], 'RESOURCE_DEPENDENCY_OR_CONFLICT')
            self.assertEqual(self.ids(result), ['required'])

    def test_required_only_needs_no_context_or_api(self):
        self.args.update(select_role=False, candidates=[candidate('required', 'skill')])
        del self.args['context']
        result = self.run_decision()
        self.assertEqual(result['reason'], 'REQUIRED_RESOURCES')
        self.assertEqual(self.ids(result), ['required'])
        self.assertEqual(self.calls, [])

    def outcome(self, oid, **updates):
        return d.report_selection_outcome({'workspace': str(self.workspace), 'observation_id': oid,
                                          'adopted': True, 'result': 'completed', **updates}, self.config)

    def test_outcome_workspace_idempotence_conflict_and_private_metadata(self):
        result = self.run_decision()
        oid = result['observation']['id']
        self.assertEqual(self.outcome(oid)['status'], 'written')
        self.assertEqual(self.outcome(oid)['status'], 'duplicate')
        with self.assertRaisesRegex(d.SafeFailure, 'OUTCOME_CONFLICT'):
            self.outcome(oid, adopted=False)
        other = self.root / 'other'
        other.mkdir()
        with self.assertRaisesRegex(d.SafeFailure, 'OBSERVATION_NOT_FOUND'):
            self.outcome(oid, workspace=str(other))
        raw = (self.root / 'audit/resource-decisions.jsonl').read_text()
        self.assertNotIn(self.args['task_summary'], raw)
        self.assertNotIn(str(self.workspace), raw)
        rows = [json.loads(x) for x in raw.splitlines()]
        self.assertTrue(all(r['schema_version'] == 2 for r in rows))
        self.assertFalse(rows[-1]['execution_verified'])
        self.assertEqual(rows[-1]['provenance'], 'caller_reported')

    def test_legacy_journal_coexists_and_old_ids_rejected(self):
        legacy = d.route({'workspace': str(self.workspace), 'task_summary': 'synthetic', 'stage': 'before_delivery'}, self.config)
        old_path = self.root / 'audit/decisions.jsonl'
        before = old_path.read_bytes()
        self.run_decision()
        self.assertEqual(old_path.read_bytes(), before)
        with self.assertRaisesRegex(d.SafeFailure, 'OBSERVATION_NOT_FOUND'):
            self.outcome(legacy['observation']['id'])
        self.assertEqual(d.report_outcome({'workspace': str(self.workspace), 'observation_id': legacy['observation']['id']}, self.config)['status'], 'written')

    def test_capacity_preserves_journal(self):
        self.write_config(observability={'enabled': True, 'max_records': 1, 'max_bytes': 524288})
        result = self.run_decision()
        path = self.root / 'audit/resource-decisions.jsonl'
        before = path.read_bytes()
        self.assertEqual(self.run_decision()['observation']['status'], 'full')
        self.assertEqual(path.read_bytes(), before)
        with self.assertRaisesRegex(d.SafeFailure, 'full'):
            self.outcome(result['observation']['id'])

    def test_corruption_preserved_without_affecting_selection(self):
        self.run_decision()
        path = self.root / 'audit/resource-decisions.jsonl'
        path.write_bytes(b'{not json}\n')
        result = self.run_decision()
        self.assertEqual(result['reason'], 'COMBINED_SELECTION')
        self.assertEqual(result['observation']['status'], 'corrupt')
        self.assertEqual(path.read_bytes(), b'{not json}\n')

    def test_lock_conflict_no_write(self):
        with self.journal.j._locked(self.config, True, self.journal.STEM):
            result = self.run_decision()
            self.assertEqual(result['observation']['status'], 'locked')
        self.assertEqual(result['reason'], 'COMBINED_SELECTION')

    def test_malformed_mcp_call_then_ping_server_survives(self):
        msgs = [{'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                 'params': {'name': 'jev_decide', 'arguments': []}},
                {'jsonrpc': '2.0', 'id': 2, 'method': 'ping'}]
        run = subprocess.run([sys.executable, str(MODULE), 'serve', '--config', str(self.config)],
            input=''.join(json.dumps(x) + '\n' for x in msgs), text=True, capture_output=True, timeout=10)
        self.assertEqual(run.returncode, 0, run.stderr)
        replies = [json.loads(x) for x in run.stdout.splitlines()]
        self.assertTrue(replies[0]['result']['isError'])
        self.assertEqual(replies[1], {'jsonrpc': '2.0', 'id': 2, 'result': {}})


if __name__ == '__main__':
    unittest.main()
