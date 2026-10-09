"""Causal zero-provider fault injection; no model calls or native PASS claims."""
import json
from pathlib import Path
import threading
import time
from unittest.mock import Mock, patch

from test_global_core import Fixture
from test_development import clean_process
from test_worker_failures import failure, line
from orchestrator.contracts import ContractError, canonical, fingerprint
from orchestrator.development import NativeDevelopmentRunner, OrdinaryValidationFailure
from orchestrator.phase2 import Phase2Queue
from orchestrator.supervisor import Supervisor
from orchestrator.worker_failures import WorkerFailureMonitor, LEGACY_POLICY, audit_failure_log
from tools.development_tool_probe import TOOLS
from tools.linux_worker_smoke import resource_sample, resource_limit_hit


def command(key, text, *, started=False, code=0, output=''):
    return {'type': 'item.started' if started else 'item.completed', 'item': {
        'id': key, 'type': 'command_execution', 'command': text,
        'status': 'in_progress' if started else 'completed' if code == 0 else 'failed',
        'exit_code': None if started else code, 'aggregated_output': output}}


class RepairTiming(Fixture):
    def monitor(self, name='new', checks=(), policy=None, seconds=300):
        self.now = getattr(self, 'now', [1.0])
        return WorkerFailureMonitor(self.root / name, {'attempt': name}, seconds, lambda _: None,
                                    checks=checks, policy=policy, clock=lambda: self.now[0])

    def test_repair_resolves_exact_command_then_build_can_exceed_old_deadline(self):
        check = {'argv': ['/node', 'build'], 'timeout_seconds': 120}
        m = self.monitor(checks=[check])
        m.feed(line(failure()))
        self.now[0] += 10
        m.feed(line(command('fixed', 'python3 -m unittest')))
        self.assertIsNone(m.recovery_deadline)
        self.assertEqual(m.repair_remaining, 50)
        m.feed(line(command('build', '/node build', started=True)))
        self.now[0] += 90
        m.tick()
        self.assertFalse(m.stopped)
        m.feed(line(command('build', '/node build')) + line({'type': 'turn.completed'}))
        self.assertFalse(m.finish()['stopped'])
        self.assertEqual(m.count, 1)

    def test_success_edit_or_new_failure_does_not_refill_repair_budget(self):
        m = self.monitor()
        m.feed(line(failure()))
        deadline = m.recovery_deadline
        self.now[0] += 10
        m.feed(line(command('unrelated', 'echo ok')))
        m.feed(line({'type': 'item.completed', 'item': {'type': 'file_change', 'id': 'edit', 'status': 'completed'}}))
        self.assertEqual(m.recovery_deadline, deadline)
        m.feed(line(command('fixed', 'python3 -m unittest')))
        self.now[0] += 100
        m.feed(line(failure('again')))
        self.assertEqual(m.recovery_deadline, self.now[0] + 50)
        self.now[0] += 50
        m.tick()
        self.assertEqual(m.reason, 'RECOVERY_TIME_EXHAUSTED')
        self.assertEqual(m.count, 2)

    def test_pinned_check_pauses_repair_but_has_own_timeout(self):
        check = {'argv': ['python3', '-m', 'unittest'], 'timeout_seconds': 120}
        m = self.monitor(checks=[check])
        m.feed(line(failure()))  # Without a matching started event: fail closed.
        self.assertEqual(m.reason, 'CHECK_LIFECYCLE_UNKNOWN')
        m = self.monitor('lifecycle', checks=[check])
        m.feed(line(command('first', 'python3 -m unittest', started=True)))
        m.feed(line(failure('first')))
        self.now[0] += 10
        m.feed(line(command('rerun', 'python3 -m unittest', started=True)))
        self.now[0] += 80
        m.tick()
        self.assertFalse(m.stopped)
        m.feed(line(command('rerun', 'python3 -m unittest')))
        self.assertEqual(m.repair_remaining, 50)
        m.feed(line(command('hang', 'python3 -m unittest', started=True)))
        self.now[0] += 120
        m.tick()
        self.assertEqual(m.reason, 'REQUIRED_CHECK_TIMEOUT')

    def test_task_deadline_applies_to_checks_and_controller_validation(self):
        m = self.monitor(seconds=20)
        m.feed(line({'type': 'turn.completed'}))
        self.now[0] += 20
        m.tick()
        self.assertEqual(m.reason, 'TASK_TIMEOUT')

    def test_missing_tool_fallback_requires_complete_pinned_suite(self):
        checks = [{'argv': ['/node', name], 'timeout_seconds': 120} for name in ('test', 'build')]
        m = self.monitor(checks=checks)
        missing = failure('rg', 'rg: command not found', 127)
        missing['item']['command'] = 'rg --files tests'
        m.feed(line(missing))
        m.feed(line(command('fallback', 'grep -R example tests')))
        self.assertIsNotNone(m.recovery_deadline)
        for name in ('test', 'build'):
            m.feed(line(command(name, '/node ' + name, started=True)))
            self.now[0] += 70
            m.feed(line(command(name, '/node ' + name)))
        self.assertFalse(m.stopped)
        self.assertIsNone(m.recovery_deadline)
        self.assertEqual(m.count, 1)
        m.feed(line({'type': 'turn.completed'}))
        self.assertFalse(m.finish()['stopped'])

    def test_unresolved_failure_cannot_escape_budget_by_turn_completion(self):
        m = self.monitor()
        m.feed(line(failure()) + line({'type': 'turn.completed'}))
        self.assertEqual(m.reason, 'UNRESOLVED_TOOL_FAILURE')
        self.assertFalse(m.completed)

    def test_legacy_policy_keeps_first_failure_deadline_and_readonly_audit(self):
        m = self.monitor(policy=LEGACY_POLICY)
        m.feed(line(failure()))
        m.feed(line(command('fixed', 'python3 -m unittest')))
        self.now[0] += 60
        m.tick()
        self.assertEqual(m.reason, 'RECOVERY_TIME_EXHAUSTED')
        before = {p.name: p.read_bytes() for p in m.folder.iterdir()}
        self.assertFalse(audit_failure_log(m.folder, {'attempt': 'new'})['execution_resumed'])
        self.assertEqual(before, {p.name: p.read_bytes() for p in m.folder.iterdir()})
        with self.assertRaises(FileExistsError):
            self.monitor(policy=LEGACY_POLICY)

    def test_pinned_check_wrong_id_or_missing_completion_is_unknown(self):
        for key in ('other', 'turn'):
            m = self.monitor(key, checks=[{'argv': ['/node', 'build'], 'timeout_seconds': 120}])
            m.feed(line(command('build', '/node build', started=True)))
            m.feed(line(command('other', '/node build')) if key == 'other' else line({'type': 'turn.completed'}))
            self.assertEqual(m.reason, 'CHECK_LIFECYCLE_UNKNOWN')


class FailureIsolation(Fixture):
    def local_receipt(self, queue, claim):
        return {'queue_id': queue.queue_id, 'task_id': claim['task']['task_id'], 'task_hash': claim['task_hash'],
            'attempt_id': claim['attempt_id'], 'epoch': claim['epoch'], 'policy_hash': queue.policy['policy_hash'],
            'failure_scope': 'TASK', 'category': 'VALIDATOR_ASSERTION', 'process_tree_empty': True,
            'provider_completion_known': True, 'no_retry': True}

    def test_local_failure_drains_healthy_worker_no_refill_review_or_integration(self):
        queue = Phase2Queue(self.root / 'dev.sqlite', self.repo, evidence_mode='DEVELOPMENT')
        a, b, child = self.task(), self.task(2), self.task(3)
        b['allowed_files'] = ['tests/test_api.py']
        child['dependencies'] = [a['task_id']]
        queue.enqueue([a, b, child])
        barrier = threading.Barrier(2)
        failed = threading.Event()
        parent = self
        class Stub:
            dispatches = 0
            healthy_cancelled = None
            def attempt(self, claim, stop):
                self.dispatches += 1
                queue.start(claim); queue.dispatch_intent(claim)
                barrier.wait(timeout=3)
                queue.validating(claim)
                if claim['task']['task_id'] == a['task_id']:
                    receipt = parent.local_receipt(queue, claim)
                    queue.isolate_task_failure(claim, receipt)
                    failed.set()
                    return {'status': 'BLOCKED', 'failure_scope': 'TASK', 'attempt_id': claim['attempt_id']}
                failed.wait(3)
                self.healthy_cancelled = stop.wait(.2)
                queue.finish(claim, {'process_tree_empty': True}, True)
                return {'status': 'REVIEW'}
            def review(self, *args):
                raise AssertionError('FAILED_CAMPAIGN_CONSUMED_REVIEW')
        runner = Stub()
        result = Supervisor(queue, self.root, self.repo, max_active=2, native_runner=runner,
                            capabilities={'backend'}).run(max_seconds=10)
        self.assertFalse(runner.healthy_cancelled)
        self.assertEqual(runner.dispatches, 2)
        self.assertEqual({r['id']: r['state'] for r in result['queue']['tasks']},
                         {a['task_id']: 'FAILED', b['task_id']: 'REVIEW', child['task_id']: 'PENDING'})
        reopened = Phase2Queue(queue.path, self.repo, evidence_mode='DEVELOPMENT')
        self.assertTrue(reopened.failures_are_isolated())
        self.assertIsNone(reopened.claim())
        self.assertEqual(reopened.snapshot()['budget']['used'], 2)
        native = NativeDevelopmentRunner.__new__(NativeDevelopmentRunner)
        native.queue = reopened
        with self.assertRaisesRegex(ContractError, 'NO_REVIEW'):
            native.review(b['task_id'], threading.Event())
        with patch('orchestrator.merge_validation.reviewed_batch', return_value={}):
            with self.assertRaisesRegex(ContractError, 'NO_INTEGRATION'):
                native.integrate([b['task_id']], threading.Event())

    def test_forged_scope_unknown_completion_and_stale_binding_cannot_isolate(self):
        q = Phase2Queue(self.root / 'dev.sqlite', self.repo, evidence_mode='DEVELOPMENT')
        q.enqueue([self.task()]); claim = q.claim(); q.start(claim); q.validating(claim)
        for key, value in [('provider_completion_known', False), ('process_tree_empty', False),
                           ('attempt_id', 'forged'), ('category', 'PROVIDER_UNKNOWN')]:
            with self.assertRaises(ContractError):
                q.isolate_task_failure(claim, {**self.local_receipt(q, claim), key: value})
        q.fence(claim, 'lease_lost')
        self.assertFalse(q.isolate_task_failure(claim, self.local_receipt(q, claim)))
        self.assertTrue(q.snapshot()['locks'])
        self.assertFalse(q.failures_are_isolated())

    def test_unmarked_or_tampered_failure_stays_global_across_restart(self):
        q = Phase2Queue(self.root / 'dev.sqlite', self.repo, evidence_mode='DEVELOPMENT')
        q.enqueue([self.task()]); claim = q.claim(); q.start(claim); q.validating(claim)
        q.isolate_task_failure(claim, self.local_receipt(q, claim))
        self.assertTrue(q.failures_are_isolated())
        with q.transaction() as db:
            db.execute("UPDATE tasks SET receipt='{}'")
        reopened = Phase2Queue(q.path, self.repo, evidence_mode='DEVELOPMENT')
        self.assertFalse(reopened.failures_are_isolated())
        self.assertFalse(reopened.finish(claim, {'process_tree_empty': True}, True))
        self.assertFalse(reopened.dispatch_intent(claim))

    def test_actual_runner_validator_assertion_is_local_but_denial_or_unknown_is_global(self):
        for case, output in (('ordinary', 'AssertionError: expected 42'),
                             ('denial', 'AssertionError Permission denied'), ('unknown', 'unrecognized failure')):
            with self.subTest(case=case):
                q = Phase2Queue(self.root / case / 'controller/queue.sqlite', self.repo, evidence_mode='DEVELOPMENT')
                task = self.task(); task['inputs'] = []
                q.enqueue([task]); claim = q.claim()
                workspace = self.root / case / 'workspace'; workspace.mkdir(parents=True)
                runner = NativeDevelopmentRunner.__new__(NativeDevelopmentRunner)
                runner.queue, runner.root, runner.repo = q, self.root, self.repo
                runner.config = workspace / 'public-config'; runner.config.write_bytes(b'fixed')
                from orchestrator.evidence import digest
                runner.config_hash, runner.pins, runner.dispatches = digest(b'fixed'), {}, 0
                runner._counter_lock = threading.Lock()
                runner.artifact_guard, runner.expected_stdout = None, {}
                plan = {'commands': [{'validator': 'unit', 'files': {}, 'argv': ['fixed'], 'timeout_seconds': 1}]}
                runner.validators = Mock(); runner.validators.plan.return_value = plan
                def launch(argv, folder, prefix, *args, **kwargs):
                    if prefix == 'worker':
                        raw = line({'type': 'thread.started', 'thread_id': '00000000-0000-0000-0000-000000000001'})
                        raw += line(command('native-command', 'fixed')) + line({'type': 'turn.completed'})
                        (folder / 'worker.jsonl').write_bytes(raw); kwargs['monitor'].feed(raw)
                        return clean_process()
                    (folder / (prefix + '.jsonl')).write_text(canonical({'status': 'FAIL', 'local_fallback': False,
                        'plan_hash': fingerprint(plan), 'result': {'exitCode': 1, 'stdout': output, 'stderr': ''}}))
                    return {**clean_process(), 'exit_code': 1}
                stop = threading.Event()
                with patch('orchestrator.development.allocate', return_value=(workspace, self.root)), \
                     patch('orchestrator.development.materialize', return_value={'snapshot_hash': 'fixture'}), \
                     patch('orchestrator.development.artifact_manifest', return_value={}), \
                     patch.object(runner, '_settings', return_value=({}, {})), \
                     patch.object(runner, '_argv', return_value=['fixed']), \
                     patch.object(runner, '_pins', return_value=None), \
                     patch.object(runner, 'tool_readiness', return_value={'inventory': {}, 'guidance': 'OFFLINE_TEST_ONLY'}), \
                     patch.object(runner, '_run', side_effect=launch):
                    result = runner.attempt(claim, stop)
                if case == 'ordinary':
                    self.assertEqual(result['failure_scope'], 'TASK')
                    self.assertFalse(stop.is_set())
                    self.assertTrue(q.failures_are_isolated())
                    self.assertEqual(q.snapshot()['tasks'][0]['state'], 'FAILED')
                    self.assertEqual(q.snapshot()['locks'], [])
                else:
                    self.assertTrue(stop.is_set())
                    self.assertFalse(q.failures_are_isolated())

    def test_integration_transaction_rechecks_late_failure_without_reserving_slots(self):
        q = Phase2Queue(self.root / 'dev.sqlite', self.repo, evidence_mode='DEVELOPMENT')
        q.enqueue([self.task()]); claim = q.claim(); q.start(claim); q.validating(claim)
        runner = NativeDevelopmentRunner.__new__(NativeDevelopmentRunner)
        runner.queue = q
        def late_failure():
            # Exactly the external-check/transaction interleaving reported in review.
            q.isolate_task_failure(claim, self.local_receipt(q, claim))
            return False
        with patch.object(q, 'task_failure_latched', side_effect=late_failure), \
             patch('orchestrator.merge_validation.reviewed_batch', return_value={}):
            with self.assertRaisesRegex(ContractError, 'INTEGRATION_FAILURE_STOP'):
                runner.integrate([claim['task']['task_id']], threading.Event())
        with q.transaction() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM development_native_slots').fetchone()[0], 0)

    def test_review_transaction_rechecks_late_failure_without_consuming_turn(self):
        q = Phase2Queue(self.root / 'dev.sqlite', self.repo, evidence_mode='DEVELOPMENT')
        q.enqueue([self.task()]); claim = q.claim(); q.start(claim); q.validating(claim)
        with q.transaction() as db:
            db.execute('CREATE TABLE development_review_dispatch(task TEXT PRIMARY KEY, nonce TEXT, intent_hash TEXT)')
        runner = NativeDevelopmentRunner.__new__(NativeDevelopmentRunner)
        runner.queue = q
        def late_failure():
            q.isolate_task_failure(claim, self.local_receipt(q, claim))
            return False
        with patch.object(q, 'task_failure_latched', side_effect=late_failure), \
             patch.object(q, 'review_challenge', side_effect=AssertionError('CHALLENGE_AFTER_FAILURE')):
            result = runner.review(claim['task']['task_id'], threading.Event())
        self.assertEqual(result['status'], 'BLOCKED')
        with q.transaction() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM development_review_dispatch').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM development_native_slots').fetchone()[0], 0)


class ToolAndResourceReadiness(Fixture):
    def test_native_inventory_missing_optional_tool_binding_and_replay(self):
        runner = NativeDevelopmentRunner.__new__(NativeDevelopmentRunner)
        runner.repo_adapter = None
        runner.config_hash = 'fixed-native-config'
        runner._settings = Mock(return_value=({'shell_environment_policy.set': {'PATH': 'fixed-path'}}, {}))
        tools = {name: {'status': 'MISSING', 'path': None, 'sha256': None} for name in TOOLS}
        import sys
        from orchestrator.evidence import digest
        executable = Path(sys.executable).resolve()
        for name in ('python3', 'bash'):
            tools[name] = {'status': 'AVAILABLE', 'path': str(executable), 'sha256': digest(executable.read_bytes())}
        value = {'version': 1, 'cwd': str(self.repo), 'path': 'fixed-path', 'tools': tools}
        runner._validator_command = Mock(return_value={'result': {'stdout': canonical(value)}})
        # The probe requires Linux Python; patch only path lookup for this parser test.
        original = Path.resolve
        def resolve(path, *args, **kwargs):
            return executable if path.as_posix() == '/usr/bin/python3' else original(path, *args, **kwargs)
        with patch.object(Path, 'resolve', resolve):
            row = runner.tool_readiness(self.repo, self.root / 'probe', {}, [], {'attempt': 'one'}, threading.Event(), [])
            self.assertEqual(row['inventory']['tools']['rg']['status'], 'MISSING')
            self.assertIn('grep', row['guidance'])
            with self.assertRaises(FileExistsError):
                runner.tool_readiness(self.repo, self.root / 'probe', {}, [], {'attempt': 'one'}, threading.Event(), [])
            value['path'] = 'wrong-path'
            runner._validator_command.return_value = {'result': {'stdout': canonical(value)}}
            with self.assertRaisesRegex(ContractError, 'BINDING'):
                runner.tool_readiness(self.repo, self.root / 'other', {}, [], {}, threading.Event(), [])

    def test_kernel_resource_counters_headroom_and_limit_events(self):
        group = self.root / 'cgroup'; group.mkdir()
        entries = {'pids.current': '61', 'memory.current': '247300096', 'memory.peak': '247300096',
            'cpu.stat': 'usage_usec 3840130\nuser_usec 2725770\nsystem_usec 1114359',
            'memory.events': 'oom 0\noom_kill 0', 'pids.events': 'max 0', 'cgroup.procs': '123\n456'}
        for name, data in entries.items():
            (group / name).write_text(data)
        sample = resource_sample(group)
        self.assertEqual(64 - sample['pids_current'], 3)
        self.assertFalse(resource_limit_hit(sample))
        (group / 'pids.events').write_text('max 1')
        self.assertTrue(resource_limit_hit(resource_sample(group)))
        (group / 'memory.events').write_text('oom 1\noom_kill 1')
        self.assertTrue(resource_limit_hit(resource_sample(group)))
        (group / 'pids.current').unlink()
        with self.assertRaises(OSError):
            resource_sample(group)
