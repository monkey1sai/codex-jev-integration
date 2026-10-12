"""Worker-only observation stops at Review; these are zero-provider tests."""
from types import SimpleNamespace
import threading

from test_global_core import Fixture
from orchestrator.contracts import ContractError
from orchestrator.development import NativeDevelopmentRunner
from orchestrator.phase2 import Phase2Queue
from orchestrator.supervisor import Supervisor


class WorkerOnlyCampaign(Fixture):
    def test_two_workers_finish_review_deferred_restart_does_not_redispatch(self):
        queue = Phase2Queue(self.root / 'worker-only.sqlite', self.repo, evidence_mode='DEVELOPMENT',
                            failure_isolation='independent_tasks_v1',
                            session={'scheduler': {'max_active': 2, 'max_dispatches': 2, 'max_attempts': 1}})
        a, b, child = self.task(), self.task(2), self.task(3)
        b['allowed_files'] = ['tests/test_api.py']
        child['dependencies'] = [a['task_id']]
        queue.enqueue([a, b, child])
        barrier = threading.Barrier(2)
        class Runner:
            dispatches = 0
            repo_adapter = SimpleNamespace(review_budget=0, hash='fixed', verify=lambda: None)
            def attempt(self, claim, stop):
                self.dispatches += 1
                queue.start(claim)
                queue.dispatch_intent(claim)
                barrier.wait(5)
                queue.validating(claim)
                queue.finish(claim, {'process_tree_empty': True}, True)
                return {'status': 'REVIEW'}
            def review(self, *args):
                raise AssertionError('No review turn is authorized')
        runner = Runner()
        result = Supervisor(queue, self.root, self.repo, max_active=2, native_runner=runner,
                            capabilities={'backend'}).run(max_seconds=10)
        self.assertEqual(runner.dispatches, 2)
        self.assertEqual({r['id']: r['state'] for r in result['queue']['tasks']},
                         {a['task_id']: 'REVIEW', b['task_id']: 'REVIEW', child['task_id']: 'PENDING'})
        reopened = Phase2Queue(queue.path, self.repo, evidence_mode='DEVELOPMENT',
                               failure_isolation='independent_tasks_v1', session=queue.session)
        Supervisor(reopened, self.root, self.repo, max_active=2, native_runner=runner,
                   capabilities={'backend'}).run(max_seconds=5)
        self.assertEqual(runner.dispatches, 2)
        self.assertEqual(reopened.snapshot()['budget']['used'], 2)
        self.assertIsNone(reopened.claim())

    def test_unreviewed_overlap_requires_validated_custody(self):
        queue = Phase2Queue(self.root / 'overlap.sqlite', self.repo, evidence_mode='DEVELOPMENT')
        queue.enqueue([self.task()])
        runner = NativeDevelopmentRunner.__new__(NativeDevelopmentRunner)
        runner.queue, runner._pins = queue, lambda: None
        for ids, reason in [([], 'TASK_SET'), (['task-1', 'task-1'], 'TASK_SET'),
                            (['missing'], 'VALIDATED_WORKER_REQUIRED'),
                            (['task-1'], 'VALIDATED_WORKER_REQUIRED')]:
            with self.subTest(ids=ids), self.assertRaisesRegex(ContractError, reason):
                runner.parallel_evidence(ids, require_review=False)
        with queue.transaction() as db:
            db.execute("UPDATE tasks SET state='REVIEW' WHERE id='task-1'")
        with self.assertRaisesRegex(ContractError, 'MANIFEST'):
            runner.parallel_evidence(['task-1'], require_review=False)
