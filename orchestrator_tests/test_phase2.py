from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from orchestrator.contracts import ContractError
from orchestrator.phase2 import Phase2Queue
from orchestrator.pipeline import smoke, rule_route
from orchestrator.pipeline import mock_attempt
from orchestrator.benchmark import score
from test_global_core import Fixture


class Lifecycle(Fixture):
    def setUp(self):
        super().setUp()
        self.database = self.root / 'controller/phase2.sqlite'
        self.queue = Phase2Queue(self.database, self.repo, session={'routing': {'strategy': 'rules_only', 'jev_enabled': False}})

    def reopen(self):
        return Phase2Queue(self.database, self.repo, session={'routing': {'strategy': 'rules_only', 'jev_enabled': False}})

    def test_cycle_and_missing_dependencies_rejected_atomically(self):
        a, b = self.task(), self.task(2)
        a['dependencies'], b['dependencies'] = [b['task_id']], [a['task_id']]
        with self.assertRaisesRegex(ContractError, 'DAG_CYCLE'):
            self.queue.enqueue([a, b])
        with self.assertRaisesRegex(ContractError, 'MISSING_DEPENDENCY'):
            self.queue.enqueue([a])
        self.assertEqual(self.queue.snapshot()['tasks'], [])

    def test_atomic_claim_ownership_restart_and_stale_submit(self):
        self.queue.enqueue([self.task()])
        with ThreadPoolExecutor(max_workers=2) as pool:
            claims = list(pool.map(lambda _: self.reopen().claim(now=10), range(2)))
        self.assertEqual(sum(c is not None for c in claims), 1)
        claim = next(c for c in claims if c)
        self.assertTrue(self.reopen().start(claim, now=11))
        self.assertTrue(self.queue.heartbeat(claim, now=12))
        self.assertEqual(len(self.reopen().expired(now=999)), 1)
        self.assertFalse(self.queue.validating(claim, now=13))
        self.assertFalse(self.queue.finish(claim, {'process_tree_empty': True}, True, now=13))
        self.assertEqual(self.reopen().snapshot()['tasks'][0]['state'], 'HELD')
        self.assertTrue(self.queue.snapshot()['locks'])

    def test_permission_mismatch_and_dependencies_do_not_dispatch(self):
        a, b = self.task(), self.task(2)
        b['dependencies'] = [a['task_id']]
        self.queue.enqueue([a, b])
        self.assertIsNone(self.queue.claim(capabilities={'unknown'}))
        self.assertIsNotNone(self.queue.claim())
        self.assertIsNone(self.queue.claim())
        self.assertEqual(self.queue.snapshot()['tasks'][1]['state'], 'PENDING')

    def test_unknown_provider_survives_restart_and_cannot_retry(self):
        task = self.task()
        task['budgets']['attempts'] = 2
        self.queue.enqueue([task])
        claim = self.queue.claim()
        self.assertTrue(self.queue.start(claim))
        self.assertTrue(self.queue.dispatch_intent(claim))
        self.assertFalse(self.reopen().dispatch_intent(claim))
        reopened = self.reopen()
        self.assertTrue(reopened.fence(claim))
        self.assertFalse(reopened.cleanup(claim, tree_empty=True, retry=True))
        self.assertEqual(reopened.snapshot()['tasks'][0]['provider_unknown'], 1)
        self.assertEqual(reopened.snapshot()['budget']['used'], 1)

    def test_named_contract_fields_normalize_to_strict_v2(self):
        task = self.task()
        task['schema_version'] = 3
        task['model_policy'] = task.pop('execution')
        task['retry_budget'] = task.pop('budgets')
        task['acceptance'] = {'criteria': task.pop('acceptance_criteria'), 'validators': task.pop('tests')}
        self.queue.enqueue([task])
        claim = self.queue.claim()
        self.assertEqual(claim['task']['schema_version'], 2)

    def test_dispatch_intent_atomic_one_shot_and_expiry(self):
        self.queue.enqueue([self.task()])
        claim = self.queue.claim()
        self.queue.start(claim)
        with ThreadPoolExecutor(max_workers=2) as pool:
            granted = list(pool.map(lambda _: self.reopen().dispatch_intent(claim), range(2)))
        self.assertEqual(sum(granted), 1)

    def test_session_cannot_remove_repo_acceptance_or_weaken_review(self):
        overlay = {'capabilities': {'backend': {'role': 'worker', 'description': 'weaker', 'allowed_files': ['src/api.py'], 'validators': []}}}
        with self.assertRaisesRegex(ContractError, 'REPO_ACCEPTANCE_DOWNGRADE'):
            Phase2Queue(self.root / 'other.sqlite', self.repo, session=overlay)

    def test_review_and_merge_cannot_be_forged(self):
        self.queue.enqueue([self.task()])
        claim = self.queue.claim()
        self.assertTrue(self.queue.start(claim))
        self.assertTrue(self.queue.validating(claim))
        self.assertTrue(self.queue.finish(claim, {'process_tree_empty': True}, True))
        with self.assertRaisesRegex(ContractError, 'TRUSTED_REVIEW'):
            self.queue.review('task-1', reviewer='astra', independent=True, receipt_hash='fake')
        with self.assertRaisesRegex(ContractError, 'MERGE_EXECUTION_DISABLED'):
            self.queue.merge(authorized=True)
        self.assertEqual(self.queue.merge_snapshot()[0]['status'], 'HELD')
        self.assertEqual(self.queue.snapshot()['tasks'][0]['state'], 'REVIEW')

    def test_rule_router_works_with_jev_disabled(self):
        result = rule_route(self.queue.policy, ['backend'], capability='backend')
        self.assertFalse(result['provider_called'])
        self.assertEqual(result['selected_id'], 'backend')
        with self.assertRaisesRegex(ContractError, 'NO_LEGAL_CANDIDATE'):
            rule_route(self.queue.policy, ['evil'], capability='backend')

    def test_retry_budget_and_successor_fencing(self):
        task = self.task()
        task['budgets']['attempts'] = 2
        self.queue.enqueue([task])
        old = self.queue.claim(now=10)
        self.queue.expired(now=999)
        self.assertTrue(self.queue.cleanup(old, tree_empty=True, retry=True))
        new = self.queue.claim(now=1000)
        self.assertEqual(new['epoch'], old['epoch'] + 2)
        self.assertFalse(self.queue.fence(old))
        self.assertFalse(self.queue.cleanup(old, tree_empty=True))
        self.queue.expired(now=2000)
        self.assertFalse(self.queue.cleanup(new, tree_empty=True, retry=True))
        self.assertEqual(self.queue.snapshot()['budget']['used'], 2)

    def test_policy_drift_blocks_active_transitions(self):
        self.queue.enqueue([self.task()])
        claim = self.queue.claim()
        config = json.loads((self.repo / '.codex/orchestrator.json').read_text())
        config['routing'] = {'jev_enabled': True}
        (self.repo / '.codex/orchestrator.json').write_text(json.dumps(config))
        with self.assertRaisesRegex(ContractError, 'QUEUE_POLICY_DRIFT'):
            self.queue.start(claim)

    def test_phase2_source_fingerprint_is_bound(self):
        hashes = self.queue.policy['core_sha256']
        for name in ('phase2.py', 'pipeline.py', 'cli_adapter.py', 'processes.py', 'workspaces.py'):
            self.assertIn(name, hashes)
        self.assertEqual(self.queue.policy['field_sources']['routing.jev_enabled']['layer'], 'explicit_session')

    def test_expired_dispatch_intent_is_rejected(self):
        self.queue.enqueue([self.task()])
        claim = self.queue.claim(now=10)
        self.queue.start(claim, now=11)
        self.assertFalse(self.queue.dispatch_intent(claim))


class Execution(unittest.TestCase):
    def test_mock_timeout_is_bounded_by_task_contract(self):
        queue = Mock()
        queue.claim.return_value = {'task': {'budgets': {'runtime_seconds': 1}, 'inputs': []}, 'attempt_id': 'fixed'}
        with patch('orchestrator.pipeline.allocate', return_value=(Path('.'), Path('.'))), \
             patch('orchestrator.pipeline.scan', return_value={}), \
             patch('orchestrator.pipeline.bounded_run', side_effect=RuntimeError('stop')) as run:
            with self.assertRaisesRegex(RuntimeError, 'stop'):
                mock_attempt(queue, Path('.'), Path('.'), timeout=5)
        self.assertEqual(run.call_args.kwargs['timeout'], 1)
        self.assertEqual(queue.heartbeat.call_args.kwargs['lease_seconds'], 31)
    def test_real_mock_process_worktree_manifest_and_review_gate(self):
        root = Path(__file__).resolve().parents[1] / '.test-runs'
        root.mkdir(exist_ok=True)
        parent = Path(tempfile.mkdtemp(dir=root))
        result = smoke(parent / 'valid')
        self.assertEqual(result['status'], 'REVIEW')
        self.assertEqual(result['model_calls'], 0)
        self.assertFalse(result['merge_executed'])
        evidence = json.loads((parent / 'valid/smoke-report.json').read_text())
        self.assertEqual(evidence['queue']['tasks'][0]['state'], 'REVIEW')
        self.assertEqual(evidence['merge_queue'][0]['status'], 'HELD')

    def test_real_mock_timeout_fences_before_cleanup(self):
        root = Path(__file__).resolve().parents[1] / '.test-runs'
        parent = Path(tempfile.mkdtemp(dir=root))
        result = smoke(parent / 'timeout', behavior='timeout')
        self.assertEqual(result['reason'], 'TIMEOUT')
        self.assertTrue(result['tree_empty'])
        evidence = json.loads((parent / 'timeout/smoke-report.json').read_text())
        self.assertEqual(evidence['queue']['tasks'][0]['state'], 'CANCELLED')
        self.assertEqual(evidence['queue']['locks'], [])


class BenchmarkEvidence(unittest.TestCase):
    def row(self):
        return {'task_id': 'case-1', 'dag_id': 'dag-1', 'contract_hash': '1' * 64,
                'worker_policy_hash': '2' * 64, 'completed': True, 'harmful_assignment': False,
                'tokens': 10, 'wall_seconds': 1.5, 'retry_count': 0, 'escalated': False,
                'merge_conflicts': 0, 'jev_adopted': False, 'routing_correct': True, 'hard_policy_bypass': False}

    def test_zero_baseline_harm_and_no_adoption_cannot_claim_gain(self):
        result = score([self.row()], [self.row()])
        self.assertIsNone(result['harmful_relative_improvement'])
        self.assertIsNone(result['E']['adopted_accuracy'])
        self.assertEqual(result['status'], 'DESCRIPTIVE_ONLY')
        self.assertTrue(result['go_no_go'].startswith('NOT_EVALUATED'))

    def test_unequal_task_sets_or_contracts_rejected(self):
        different = self.row()
        different['task_id'] = 'case-2'
        with self.assertRaisesRegex(ContractError, 'PAIRED_TASK_SET_MISMATCH'):
            score([self.row()], [different])
        different = self.row()
        different['contract_hash'] = '3' * 64
        with self.assertRaisesRegex(ContractError, 'PAIRED_POLICY_OR_CONTRACT_DRIFT'):
            score([self.row()], [different])

    def test_nonfinite_metric_and_duplicate_tasks_rejected(self):
        invalid = self.row()
        invalid['tokens'] = float('nan')
        with self.assertRaises(ContractError):
            score([invalid], [self.row()])
        with self.assertRaises(ContractError):
            score([self.row(), self.row()], [self.row()])
