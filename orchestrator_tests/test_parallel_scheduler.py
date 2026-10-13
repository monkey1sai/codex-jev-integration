"""Zero-provider scheduling contracts; no inference or capacity authorization."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json

from test_global_core import Fixture, config
from orchestrator.contracts import ContractError, canonical
from orchestrator.phase2 import Phase2Queue
from orchestrator.policy import compile_policy


class ParallelScheduling(Fixture):
    def ledger(self, value=None, session=None):
        if value is not None:
            (self.repo / '.codex/orchestrator.json').write_text(canonical(value))
        return Phase2Queue(self.root / 'parallel.sqlite', self.repo, session=session,
                           evidence_mode='OFFLINE_TEST')

    def pair(self):
        a, b = self.task(1), self.task(2)
        b['allowed_files'] = ['tests/test_api.py']
        return a, b

    def resource_config(self, limit=1):
        value = config()
        value['scheduler'] = {'resource_limits': {'build': limit}}
        value['capabilities']['backend']['resources'] = {'build': 1}
        return value

    def test_session_cannot_raise_explicit_repo_capacity_or_budget(self):
        value = config()
        value['scheduler'] = {'max_active': 1, 'max_dispatches': 1, 'max_attempts': 1}
        self.ledger(value)
        for field in value['scheduler']:
            with self.subTest(field=field), self.assertRaisesRegex(ContractError, 'REPO_SCHEDULER_CEILING'):
                compile_policy(self.repo, session={'scheduler': {field: 2}})

    def test_session_may_reduce_capacity_and_change_model(self):
        value = config()
        value['scheduler'] = {'max_active': 2}
        queue = self.ledger(value, {'scheduler': {'max_active': 1},
            'roles': {'worker': {'model': 'gpt-6-luna', 'reasoning_effort': 'low'}}})
        self.assertEqual(queue.policy['settings']['scheduler']['max_active'], 1)
        self.assertEqual(queue.policy['settings']['roles']['worker']['model'], 'gpt-6-luna')

    def test_priority_is_bounded_and_does_not_grant_scope(self):
        queue = self.ledger()
        for priority in (-1, 101, True, '100'):
            task = self.task()
            task['priority'] = priority
            with self.subTest(priority=priority), self.assertRaisesRegex(ContractError, 'PRIORITY'):
                queue.enqueue([task])
        task['priority'], task['allowed_files'] = 100, ['src/rogue.py']
        with self.assertRaisesRegex(ContractError, 'OWNERSHIP_SCOPE'):
            queue.enqueue([task])

    def test_highest_eligible_priority_and_stable_fifo_tie(self):
        queue = self.ledger()
        a, b = self.pair()
        a['priority'], b['priority'] = 5, 20
        queue.enqueue([a, b])
        self.assertEqual(queue.claim()['task']['task_id'], b['task_id'])
        self.assertEqual(queue.claim()['task']['task_id'], a['task_id'])

    def test_priority_tie_and_legacy_default_preserve_fifo(self):
        queue = self.ledger()
        a, b = self.pair()
        b['priority'] = 0
        queue.enqueue([a, b])
        self.assertEqual(queue.claim()['task']['task_id'], a['task_id'])

    def test_priority_cannot_bypass_dependency_or_file_ownership(self):
        queue = self.ledger()
        a, b = self.pair()
        b['dependencies'], b['priority'] = [a['task_id']], 100
        queue.enqueue([a, b])
        claim = queue.claim()
        self.assertEqual(claim['task']['task_id'], a['task_id'])
        self.assertIsNone(queue.claim())

    def test_resource_quota_blocks_until_confirmed_cleanup(self):
        queue = self.ledger(self.resource_config())
        queue.enqueue(list(self.pair()))
        claim = queue.claim()
        queue.fence(claim)
        self.assertIsNone(queue.claim())
        self.assertFalse(queue.cleanup(claim, tree_empty=False))
        self.assertIsNone(queue.claim())
        self.assertTrue(queue.cleanup(claim, tree_empty=True))
        self.assertEqual(queue.claim()['task']['task_id'], 'task-2')

    def test_atomic_resource_claims_and_restart_do_not_refill_budget(self):
        queue = self.ledger(self.resource_config())
        queue.enqueue(list(self.pair()))
        def claim(_):
            return Phase2Queue(queue.path, self.repo, evidence_mode='OFFLINE_TEST').claim()
        with ThreadPoolExecutor(max_workers=8) as pool:
            claims = [c for c in pool.map(claim, range(8)) if c]
        self.assertEqual(len(claims), 1)
        reopened = Phase2Queue(queue.path, self.repo, evidence_mode='OFFLINE_TEST')
        self.assertIsNone(reopened.claim())
        self.assertEqual(reopened.snapshot()['budget']['used'], 1)

    def test_native_review_slots_also_reserve_resources(self):
        queue = self.ledger(self.resource_config())
        a, b = self.pair()
        queue.enqueue([a, b])
        with queue.transaction() as db:
            db.execute("UPDATE tasks SET state='REVIEW' WHERE id=?", (a['task_id'],))
            db.execute('INSERT INTO development_native_slots VALUES(?,?,?)', ('test-review', a['task_id'], 'nonce'))
        self.assertIsNone(queue.claim())

    def test_unknown_resource_and_oversized_request_rejected(self):
        for resources in ({'unknown': 1}, {'build': 2}, {'build': True}):
            value = self.resource_config()
            value['capabilities']['backend']['resources'] = resources
            (self.repo / '.codex/orchestrator.json').write_text(canonical(value))
            with self.subTest(resources=resources), self.assertRaises(ContractError):
                compile_policy(self.repo)

    def test_session_cannot_raise_quota_or_remove_repo_resource_cost(self):
        self.ledger(self.resource_config())
        with self.assertRaisesRegex(ContractError, 'REPO_SCHEDULER_CEILING'):
            compile_policy(self.repo, session={'scheduler': {'resource_limits': {'build': 2}}})
        cap = config()['capabilities']['backend']
        with self.assertRaisesRegex(ContractError, 'REPO_ACCEPTANCE_DOWNGRADE'):
            compile_policy(self.repo, session={'capabilities': {'backend': cap}})

    def test_file_prefix_conflicts_not_just_identical_spelling(self):
        value = config()
        value['capabilities']['backend']['allowed_files'] = ['src/tree', 'src/tree/child.py']
        queue = self.ledger(value)
        a, b = self.pair()
        a['allowed_files'], b['allowed_files'] = ['src/tree'], ['src/tree/child.py']
        queue.enqueue([a, b])
        self.assertIsNotNone(queue.claim())
        self.assertIsNone(queue.claim())

    def test_decision_audit_is_durable_and_deduplicates_polling(self):
        queue = self.ledger(self.resource_config())
        queue.enqueue(list(self.pair()))
        queue.claim()
        queue.claim()
        with queue.transaction() as db:
            before = db.execute('SELECT count(*) FROM events').fetchone()[0]
        for _ in range(5):
            self.assertIsNone(queue.claim())
        with queue.transaction() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM events').fetchone()[0], before)
            decisions = [json.loads(r[0]) for r in db.execute('SELECT event FROM events')
                         if json.loads(r[0]).get('event') == 'dispatch_decision']
        self.assertTrue(any(d['selected'] == 'task-1' for d in decisions))
        blocked = decisions[-1]
        self.assertEqual(blocked['policy_hash'], queue.policy['policy_hash'])
        self.assertEqual(blocked['candidates'][0]['reason'], 'RESOURCE_QUOTA')
