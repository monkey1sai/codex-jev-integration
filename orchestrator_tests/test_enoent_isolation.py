"""Zero-provider causal tests. Stub native receipts never establish live PASS."""
from copy import deepcopy
import json
from pathlib import Path
import shlex
import threading
import time
from unittest.mock import Mock, patch

from test_global_core import Fixture
from test_development import clean_process
from test_parallel_recovery import command
from test_worker_failures import line, failure
from orchestrator.contracts import ContractError, canonical, fingerprint
from orchestrator.development import NativeDevelopmentRunner, task_context
from orchestrator.evidence import digest, frozen_bytes
from orchestrator.phase2 import Phase2Queue
from orchestrator.supervisor import Supervisor
from orchestrator.worker_failures import (INDEPENDENT_POLICY, RepoReadContext, WorkerFailureMonitor,
                                           audit_failure_log, classify, public_repo_name)
from orchestrator.workspaces import scan
from tools.repo_parallel_campaign import open_campaign


class TrustedRead(Fixture):
    def context(self):
        (self.repo / 'tests').mkdir(exist_ok=True)
        (self.repo / 'tests/actual.test.ts').write_bytes(b'public test')
        (self.repo / 'vite.config.ts').write_bytes(b'public config')
        executable = self.root / 'pinned-cat'
        executable.write_bytes(b'controller-owned executable fixture, not executed')
        self.tools = {'cat': {'status': 'AVAILABLE', 'path': str(executable), 'sha256': digest(executable.read_bytes())}}
        return RepoReadContext(self.repo, {'tests/actual.test.ts': digest(b'public test'),
                                          'vite.config.ts': digest(b'public config')}, self.tools, 'context-hash')

    def missing(self, text=None, output=None):
        path = self.repo.as_posix() + '/tests/unity-preflight.test.ts'
        text = text or shlex.join(['/bin/bash', '-lc', shlex.join([self.tools['cat']['path'], path])])
        return command('missing', text, code=1, output=output or 'cat: ' + path + ': No such file or directory\n')

    def test_absolute_pinned_cat_missing_leaf_is_recoverable_only_with_context(self):
        context = self.context()
        event = self.missing()
        self.assertEqual(classify(event), ('TOOL_FAILURE_UNKNOWN', 'STOP'))
        self.assertEqual(classify(event, read_context=context), ('REPO_READ_ENOENT', 'RECOVER'))
        historical = self.missing("/bin/bash -lc 'cat tests/unity-preflight.test.ts vite.config.ts'",
                                  'cat: tests/unity-preflight.test.ts: No such file or directory\npublic config')
        self.assertEqual(classify(historical, read_context=context), ('TOOL_FAILURE_UNKNOWN', 'STOP'))
        for status, code in [('completed', 0), ('failed', 2)]:
            other = deepcopy(event); other['item'].update(status=status, exit_code=code)
            self.assertNotEqual(classify(other, read_context=context), ('REPO_READ_ENOENT', 'RECOVER'))

    def test_unsafe_ambiguous_or_non_repo_missing_reads_remain_unknown(self):
        context = self.context()
        commands = ['cat ../outside', 'cat /etc/missing', 'cat tests/missing; echo ok',
                    'cat tests/missing > tests/new', 'cat tests/missing | cat', 'cat $(echo tests/missing)',
                    'python3 -c pass', 'cat --help tests/missing', 'cat tests/*', 'cat .git/missing',
                    'cat runtime-home/missing', 'cat credentials.json', 'cat absent-parent/missing',
                    'cat tests/../missing', 'cat tests//missing', 'cat tests/missing node_modules/missing']
        for text in commands:
            with self.subTest(text=text):
                self.assertEqual(classify(self.missing(text), read_context=context)[1], 'STOP')
        # Reach operand checks with the correct pinned executable and an otherwise
        # exact diagnostic; do not test every denial only via the executable gate.
        operands = [self.root.as_posix() + '/outside', self.repo.as_posix() + '/tests/../missing',
                    self.repo.as_posix() + '/tests//missing', self.repo.as_posix() + '/.git/missing',
                    self.repo.as_posix() + '/credentials.json', self.repo.as_posix() + '/absent-parent/missing']
        for operand in operands:
            with self.subTest(operand=operand):
                event = self.missing(shlex.join([self.tools['cat']['path'], operand]),
                                     'cat: ' + operand + ': No such file or directory\n')
                self.assertEqual(classify(event, read_context=context)[1], 'STOP')
        for output in ['FileNotFoundError', 'ENOENT', 'AssertionError Permission denied', 'operation not permitted']:
            self.assertEqual(classify(self.missing(output=output), read_context=context)[1], 'STOP')

    def test_present_leaf_missing_executable_and_hash_drift_fail_closed(self):
        context = self.context()
        (self.repo / 'tests/unity-preflight.test.ts').write_bytes(b'now present')
        self.assertEqual(classify(self.missing(), read_context=context)[1], 'STOP')
        (self.repo / 'tests/unity-preflight.test.ts').unlink()
        Path(context.cat['path']).write_bytes(b'drift')
        self.assertEqual(classify(self.missing(), read_context=context)[1], 'STOP')
        context.cat['status'] = 'MISSING'
        self.assertEqual(classify(self.missing(), read_context=context)[1], 'STOP')

    def test_unknown_cwd_multiple_operands_and_mixed_eio_remain_unknown(self):
        context = self.context()
        missing = self.repo.as_posix() + '/tests/unity-preflight.test.ts'
        executable = self.tools['cat']['path']
        # Relative event text is identical for different actual tool cwd values;
        # no caller/worker-provided cwd field can grant recoverability.
        event = self.missing(shlex.join([executable, 'tests/unity-preflight.test.ts']),
                             'cat: tests/unity-preflight.test.ts: No such file or directory\n')
        for cwd in (str(self.repo), '/other/worktree'):
            event['item']['cwd'] = cwd
            self.assertEqual(classify(event, read_context=context)[1], 'STOP')
        event = self.missing(output='cat: ' + missing + ': No such file or directory\ncat: vite.config.ts: Input/output error\n')
        self.assertEqual(classify(event, read_context=context)[1], 'STOP')
        event = self.missing(shlex.join([executable, missing, self.repo.as_posix() + '/vite.config.ts']))
        self.assertEqual(classify(event, read_context=context)[1], 'STOP')
        self.assertEqual(classify(self.missing(shlex.join(['cat', missing])), read_context=context)[1], 'STOP')

    def test_symlink_or_junction_metadata_is_never_accepted(self):
        context = self.context()
        with patch('orchestrator.worker_failures.guarded', side_effect=ContractError('REPARSE_PATH')):
            self.assertEqual(classify(self.missing(), read_context=context)[1], 'STOP')

    def test_path_inventory_rejects_sensitive_and_noncanonical_names(self):
        for name in (None, '../x', './x', 'a//b', '.git/config', 'node_modules/x', 'Controller/x',
                     'runtime-home/x', 'auth.json', 'credentials.json', 'private.pem', 'x.key', '/x', 'C:/x', 'a\\b'):
            self.assertFalse(public_repo_name(name), name)
        self.assertTrue(public_repo_name('tests/zip.test.ts'))

    def test_repaired_read_plus_pinned_suite_closes_existing_budget_and_audits(self):
        context, now, stopped = self.context(), [10.], []
        checks = [{'argv': ['node', name], 'timeout_seconds': 120} for name in ('test', 'typecheck', 'build')]
        m = WorkerFailureMonitor(self.root / 'monitor', {'attempt': 'one'}, 300, stopped.append,
                                 policy=INDEPENDENT_POLICY, checks=checks, clock=lambda: now[0])
        m.bind_read_context(context)
        m.feed(line(self.missing()))
        now[0] += 10
        m.feed(line(command('found', 'cat tests/actual.test.ts')))
        self.assertIsNotNone(m.recovery_deadline)
        for name in ('test', 'typecheck', 'build'):
            m.feed(line(command(name, 'node ' + name, started=True)))
            now[0] += 70
            m.feed(line(command(name, 'node ' + name)))
        m.feed(line({'type': 'turn.completed'}))
        self.assertFalse(m.finish()['stopped'])
        self.assertEqual(m.count, 1)
        self.assertEqual(m.repair_remaining, 50)
        audit = audit_failure_log(m.folder, {'attempt': 'one'})
        self.assertEqual(audit['last_record_hash'], m.last_hash)
        self.assertFalse(audit['execution_resumed'])
        with self.assertRaisesRegex(ContractError, 'REPLAY_OR_STALE'):
            m.bind_read_context(context)
        (m.folder / 'read-context.json').write_text('{}')
        with self.assertRaisesRegex(ContractError, 'READ_CONTEXT_DRIFT'):
            audit_failure_log(m.folder, {'attempt': 'one'})

    def test_unresolved_complete_turn_is_task_rejection_but_eof_timeout_denial_stop(self):
        for name in ('complete', 'eof', 'timeout', 'denial'):
            stopped, now = [], [0.]
            m = WorkerFailureMonitor(self.root / name, {'attempt': name}, 120, stopped.append,
                                     policy=INDEPENDENT_POLICY, read_context=self.context(), clock=lambda: now[0])
            m.feed(line(self.missing()))
            if name == 'complete':
                m.feed(line({'type': 'turn.completed'}))
                self.assertFalse(m.finish()['stopped'])
                self.assertEqual(m.task_failure, 'UNRESOLVED_TOOL_FAILURE')
            else:
                if name == 'timeout':
                    now[0] = 60; m.tick()
                elif name == 'denial':
                    m.feed(line(failure('denied', 'Permission denied')))
                m.finish()
                self.assertTrue(stopped)

    def test_task_context_includes_actual_files_placeholders_checks_and_binding(self):
        q = Phase2Queue(self.root / 'context.sqlite', self.repo, evidence_mode='DEVELOPMENT')
        claim = {'task': self.task(), 'task_hash': 'task-hash', 'attempt_id': 'a' * 32, 'epoch': 1}
        baseline = {'tests/real.ts': '1' * 64, 'src/api.py': digest(b''), '.tmp/log': '2' * 64,
                    'node_modules/lib.js': '3' * 64, 'credentials.json': '4' * 64, '.git/config': '5' * 64}
        checks = [{'validator': 'unit', 'argv': ['node', 'test'], 'timeout_seconds': 120}]
        value = task_context(q, claim, baseline, ['src/api.py'], {'inventory': {}}, checks)
        self.assertEqual(list(value['public_files']), ['src/api.py', 'tests/real.ts'])
        self.assertEqual(value['created_empty_placeholders'], ['src/api.py'])
        self.assertEqual(value['required_checks'], checks)
        self.assertEqual(value['failure_isolation_hash'], q.failure_isolation_hash)
        claim['epoch'] += 1
        self.assertNotEqual(fingerprint(value), fingerprint(task_context(q, claim, baseline, [], {}, checks)))
        with self.assertRaisesRegex(ContractError, 'TASK_CONTEXT_LIMIT'):
            task_context(q, claim, {str(i): 'x' for i in range(2049)}, [], {}, [])

    def test_campaign_entry_requires_explicit_strict_new_isolation_marker(self):
        folder = self.root / 'controller'; folder.mkdir()
        for name, value in [('session.json', {}), ('tasks.json', [])]:
            (folder / name).write_text(canonical(value))
        marker = folder / 'failure-isolation.json'
        for mode in ('legacy_campaign', 'independent_tasks_v1'):
            if mode == 'independent_tasks_v1':
                marker.write_text(canonical({'mode': mode, 'version': 1}))
            with patch('tools.repo_parallel_campaign.RepoAdapter', return_value=Mock(repo=self.repo)), \
                 patch('tools.repo_parallel_campaign.Phase2Queue', side_effect=ContractError('AT_QUEUE_SEAM')) as ctor:
                with self.assertRaisesRegex(ContractError, 'AT_QUEUE_SEAM'):
                    open_campaign(self.root, self.root / 'unused-runtime')
                self.assertEqual(ctor.call_args.kwargs['failure_isolation'], mode)
        for value in ({'mode': 'independent_tasks_v1', 'version': True}, {'mode': 'independent_tasks_v1', 'version': 2},
                      {'mode': 'legacy_campaign', 'version': 1}, {'mode': 'independent_tasks_v1', 'version': 1, 'retry': 1}):
            marker.write_text(canonical(value))
            with patch('tools.repo_parallel_campaign.RepoAdapter', return_value=Mock(repo=self.repo)), \
                 patch('tools.repo_parallel_campaign.Phase2Queue') as ctor:
                with self.assertRaisesRegex(ContractError, 'FAILURE_ISOLATION_SCHEMA'):
                    open_campaign(self.root, self.root / 'unused-runtime')
                ctor.assert_not_called()


class IndependentFailures(Fixture):
    def queue(self, name='new', **kwargs):
        return Phase2Queue(self.root / name / 'queue.sqlite', self.repo, evidence_mode='DEVELOPMENT',
                           failure_isolation='independent_tasks_v1', **kwargs)

    def local_receipt(self, q, claim):
        return {'queue_id': q.queue_id, 'task_id': claim['task']['task_id'], 'task_hash': claim['task_hash'],
                'attempt_id': claim['attempt_id'], 'epoch': claim['epoch'], 'policy_hash': q.policy['policy_hash'],
                'failure_scope': 'TASK', 'category': 'WORKER_ACCEPTANCE_FAILURE', 'process_tree_empty': True,
                'provider_completion_known': True, 'no_retry': True, 'failure_isolation_hash': q.failure_isolation_hash}

    def test_local_failure_allows_healthy_inflight_review_and_queued_independent_task(self):
        q = self.queue(session={'scheduler': {'max_dispatches': 3}})
        a, b, c, child = [self.task(i) for i in range(1, 5)]
        b['allowed_files'] = ['tests/test_api.py']
        child['dependencies'] = [a['task_id']]
        q.enqueue([a, b, c, child])
        barrier, failed, parent = threading.Barrier(2), threading.Event(), self
        class Stub:
            dispatches = 0
            healthy_cancelled = None
            reviewed = []
            def attempt(self, claim, stop):
                self.dispatches += 1
                q.start(claim); q.dispatch_intent(claim)
                if claim['task']['task_id'] in (a['task_id'], b['task_id']):
                    barrier.wait(3)
                q.validating(claim)
                if claim['task']['task_id'] == a['task_id']:
                    q.isolate_task_failure(claim, parent.local_receipt(q, claim)); failed.set()
                    return {'status': 'BLOCKED', 'failure_scope': 'TASK'}
                failed.wait(3)
                self.healthy_cancelled = stop.wait(.05)
                q.finish(claim, {'process_tree_empty': True}, True)
                return {'status': 'REVIEW'}
            def review(self, key, stop):
                self.reviewed.append(key)
                # State-only seam; actual review trust/publication is separately tested.
                with q.transaction() as db:
                    parent.assertFalse(q.work_blocked(db, key))
                    db.execute("UPDATE tasks SET state='PASSED' WHERE id=?", (key,)); q._ready(db)
                return {'status': 'PASSED'}
        runner = Stub()
        result = Supervisor(q, self.root, self.repo, max_active=2, native_runner=runner,
                            capabilities={'backend'}).run(max_seconds=5)
        self.assertFalse(runner.healthy_cancelled)
        self.assertEqual(runner.dispatches, 3)
        self.assertEqual(set(runner.reviewed), {b['task_id'], c['task_id']})
        self.assertEqual({r['id']: r['state'] for r in result['queue']['tasks']},
                         {a['task_id']: 'FAILED', b['task_id']: 'PASSED', c['task_id']: 'PASSED', child['task_id']: 'PENDING'})
        self.assertLess(result['metrics']['elapsed_seconds'], 4)
        reopened = self.queue(session={'scheduler': {'max_dispatches': 3}})
        self.assertEqual(reopened.snapshot()['budget']['used'], 3)
        self.assertIsNone(reopened.claim())
        runner = NativeDevelopmentRunner.__new__(NativeDevelopmentRunner); runner.queue = reopened
        with self.assertRaisesRegex(ContractError, 'CAMPAIGN_TASK_FAILURE'):
            runner.integrate([b['task_id'], c['task_id']], threading.Event())

    def test_mode_binding_rejects_legacy_reinterpretation_and_restart_drift(self):
        legacy = Phase2Queue(self.root / 'legacy.sqlite', self.repo, evidence_mode='DEVELOPMENT')
        legacy.enqueue([self.task()])
        with self.assertRaisesRegex(ContractError, 'FAILURE_ISOLATION_DRIFT'):
            Phase2Queue(legacy.path, self.repo, evidence_mode='DEVELOPMENT', failure_isolation='independent_tasks_v1')
        with legacy.transaction() as db:
            db.execute('DELETE FROM failure_isolation_binding')
        with self.assertRaisesRegex(ContractError, 'FRESH_ISOLATION_QUEUE_REQUIRED'):
            Phase2Queue(legacy.path, self.repo, evidence_mode='DEVELOPMENT', failure_isolation='independent_tasks_v1')
        q = self.queue(); q.enqueue([self.task()])
        with q.transaction() as db:
            db.execute("UPDATE failure_isolation_binding SET hash='drift'")
        with self.assertRaisesRegex(ContractError, 'FAILURE_ISOLATION_DRIFT'):
            q.claim()

    def test_unknown_cancel_and_unmarked_failure_still_stop_all_healthy_work(self):
        for state in ('HELD', 'CANCELLED', 'FAILED'):
            q = self.queue(state); a, b = self.task(), self.task(2)
            b['allowed_files'] = ['tests/test_api.py']; q.enqueue([a, b])
            claim = q.claim(); q.start(claim); q.dispatch_intent(claim)
            with q.transaction() as db:
                db.execute('UPDATE tasks SET state=? WHERE id=?', (state, a['task_id']))
            self.assertIsNone(q.claim())
            self.assertFalse(q.failures_are_isolated())
            with q.transaction() as db:
                self.assertTrue(q.work_blocked(db, b['task_id']))

    def test_stale_replay_tamper_and_provider_unknown_cannot_be_isolated(self):
        q = self.queue(); q.enqueue([self.task()]); claim = q.claim(); q.start(claim); q.validating(claim)
        receipt = self.local_receipt(q, claim)
        for key, value in [('provider_completion_known', False), ('process_tree_empty', False),
                           ('epoch', 2), ('failure_isolation_hash', 'forged')]:
            bad = {**receipt, key: value}
            with self.assertRaisesRegex(ContractError, 'TASK_FAILURE_BINDING'):
                q.isolate_task_failure(claim, bad)
        self.assertTrue(q.isolate_task_failure(claim, receipt))
        self.assertFalse(q.isolate_task_failure(claim, receipt))
        self.assertFalse(q.finish(claim, {'process_tree_empty': True}, True))
        self.assertTrue(self.queue().failures_are_isolated())
        with q.transaction() as db:
            db.execute("UPDATE tasks SET provider_unknown=1 WHERE id=?", (claim['task']['task_id'],))
        self.assertFalse(self.queue().failures_are_isolated())
        self.assertIsNone(q.claim())

    def test_global_integration_failure_blocks_claim_and_review_even_with_local_failures(self):
        q = self.queue(); a, b = self.task(), self.task(2)
        b['allowed_files'] = ['tests/test_api.py']; q.enqueue([a, b])
        claim = q.claim(); q.start(claim); q.validating(claim)
        q.isolate_task_failure(claim, self.local_receipt(q, claim))
        with q.transaction() as db:
            db.execute("INSERT INTO integration_failures VALUES('global','evidence')")
        self.assertIsNone(q.claim())
        runner = NativeDevelopmentRunner.__new__(NativeDevelopmentRunner); runner.queue = q
        result = runner.review(b['task_id'], threading.Event())
        self.assertEqual(result['status'], 'BLOCKED')

    def test_actual_runner_completed_ordinary_failure_is_local_but_unsafe_diff_is_global(self):
        for name in ('ordinary', 'unsafe'):
            q = self.queue(name); task = self.task(); task['inputs'] = []; q.enqueue([task]); claim = q.claim()
            workspace = self.root / name / 'workspace'; workspace.mkdir()
            runner = NativeDevelopmentRunner.__new__(NativeDevelopmentRunner)
            runner.queue, runner.root, runner.repo = q, self.root, self.repo
            runner.config = workspace / 'public-config'; runner.config.write_bytes(b'fixed')
            runner.config_hash, runner.pins, runner.dispatches = digest(b'fixed'), {}, 0
            runner._counter_lock = threading.Lock(); runner._scan = scan
            runner.artifact_guard, runner.expected_stdout = None, {}
            runner.validators = Mock()
            def launch(argv, folder, prefix, *args, **kwargs):
                raw = line({'type': 'thread.started', 'thread_id': '00000000-0000-0000-0000-000000000001'})
                raw += line(failure()) + line({'type': 'turn.completed'})
                (folder / 'worker.jsonl').write_bytes(raw); kwargs['monitor'].feed(raw)
                if name == 'unsafe':
                    (workspace / 'rogue').write_bytes(b'forbidden')
                return clean_process()
            stop = threading.Event()
            with patch('orchestrator.development.allocate', return_value=(workspace, self.root)), \
                 patch('orchestrator.development.materialize', return_value={'snapshot_hash': 'fixture'}), \
                 patch('orchestrator.development.git', return_value=task['base_sha']), \
                 patch.object(runner, '_settings', return_value=({}, {})), \
                 patch.object(runner, '_argv', return_value=['fixed']), \
                 patch.object(runner, '_pins', return_value=None), \
                 patch.object(runner, 'tool_readiness', return_value={'inventory': {'tools': {}}, 'guidance': 'OFFLINE_ONLY'}), \
                 patch.object(runner, '_run', side_effect=launch):
                result = runner.attempt(claim, stop)
            if name == 'ordinary':
                self.assertFalse(stop.is_set()); self.assertEqual(result['failure_scope'], 'TASK')
                self.assertTrue(q.failures_are_isolated())
                runner.validators.run.assert_not_called()
                with q.transaction() as db:
                    self.assertEqual(db.execute('SELECT count(*) FROM artifact_manifests').fetchone()[0], 0)
            else:
                self.assertTrue(stop.is_set()); self.assertNotIn('failure_scope', result)
                self.assertFalse(q.failures_are_isolated())

    def test_global_failure_cancels_healthy_inflight_worker_and_recovery_keeps_fencing(self):
        q = self.queue(); a, b = self.task(), self.task(2)
        b['allowed_files'] = ['tests/test_api.py']; q.enqueue([a, b])
        barrier = threading.Barrier(2)
        class Stub:
            dispatches = 0
            cancelled = False
            def attempt(self, claim, stop):
                self.dispatches += 1
                q.start(claim); q.dispatch_intent(claim); barrier.wait(3)
                if claim['task']['task_id'] == a['task_id']:
                    q.fence(claim, 'protection_failure')
                    return {'status': 'BLOCKED', 'reason': 'PROTECTION_OR_CONTROL_FAILURE'}
                self.cancelled = stop.wait(3)
                q.fence(claim, 'CANCELLED')
                q.cleanup(claim, tree_empty=True, retry=False, provider_completion_unknown=True)
                return {'status': 'BLOCKED', 'reason': 'CANCELLED'}
        runner = Stub()
        Supervisor(q, self.root, self.repo, max_active=2, native_runner=runner,
                   capabilities={'backend'}).run(max_seconds=5)
        self.assertTrue(runner.cancelled)
        reopened = self.queue()
        self.assertFalse(reopened.failures_are_isolated())
        self.assertIsNone(reopened.claim())
        self.assertEqual(reopened.snapshot()['budget']['used'], 2)


class ReviewContinuation(Fixture):
    queue = IndependentFailures.queue
    local_receipt = IndependentFailures.local_receipt

    def setup_review(self, name='review'):
        q = self.queue(name); a, b, child = self.task(), self.task(2), self.task(3)
        b.update(inputs=[], allowed_files=['tests/test_api.py'], expected_artifacts=['tests/test_api.py'])
        child['dependencies'] = [b['task_id']]
        q.enqueue([a, b, child])
        failed = q.claim(); healthy = q.claim()
        q.start(failed); q.validating(failed)
        q.isolate_task_failure(failed, self.local_receipt(q, failed))
        q.start(healthy); q.dispatch_intent(healthy); q.validating(healthy)
        workspace = self.root / 'worktrees' / healthy['attempt_id']
        frozen_bytes(workspace / 'tests/test_api.py', b'public candidate')
        artifacts = {'tests/test_api.py': digest(b'public candidate')}
        manifest_hash = q.artifacts.publish(healthy, workspace, artifacts)
        q.finish(healthy, {'process_tree_empty': True, 'artifact_manifest_hash': manifest_hash,
            'artifacts': artifacts, 'validator_evidence': [], 'worker_checks': [],
            'completion': {'native_thread_id': '00000000-0000-0000-0000-000000000001'}}, True)
        runner = NativeDevelopmentRunner.__new__(NativeDevelopmentRunner)
        runner.queue, runner.root, runner._scan = q, self.root, scan
        runner.config_hash, runner.supervisor_owner = 'config-fixture', 'supervisor-fixture'
        with q.transaction() as db:
            db.execute('CREATE TABLE supervisor_lock(id INTEGER PRIMARY KEY,owner TEXT,expires REAL)')
            db.execute('INSERT INTO supervisor_lock VALUES(1,?,?)', (runner.supervisor_owner, time.time() + 60))
            db.execute('CREATE TABLE development_review_dispatch(task TEXT PRIMARY KEY,nonce TEXT UNIQUE,intent_hash TEXT)')
        return q, runner, b, child

    def launch(self, verdict, mutate=None):
        def run(argv, folder, prefix, *args, **kwargs):
            raw = line({'type': 'thread.started', 'thread_id': '00000000-0000-0000-0000-000000000002'})
            raw += line({'type': 'item.completed', 'item': {'id': 'verdict', 'type': 'agent_message',
                          'text': canonical({'decision': verdict, 'findings': []})}})
            raw += line({'type': 'turn.completed'})
            (folder / 'reviewer.jsonl').write_bytes(raw)
            if mutate:
                mutate()
            return clean_process()
        return run

    def review(self, runner, task, verdict='PASS', mutate=None):
        with patch.object(runner, '_settings', return_value=({}, {})), \
             patch.object(runner, '_argv', return_value=['NOT_EXECUTED_OFFLINE']), \
             patch.object(runner, '_pins', return_value=None), \
             patch.object(runner, '_run', side_effect=self.launch(verdict, mutate)):
            return runner.review(task['task_id'], threading.Event())

    def test_actual_review_method_can_pass_healthy_task_and_release_its_dependency(self):
        q, runner, task, child = self.setup_review()
        self.assertEqual(self.review(runner, task)['status'], 'PASSED')
        states = {r['id']: r['state'] for r in q.snapshot()['tasks']}
        self.assertEqual(states, {'task-1': 'FAILED', task['task_id']: 'PASSED', child['task_id']: 'READY'})
        claim = self.queue('review').claim()
        self.assertEqual(claim['task']['task_id'], child['task_id'])
        with q.transaction() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM reviews').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT count(*) FROM development_review_dispatch').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT count(*) FROM development_native_slots').fetchone()[0], 0)
        with self.assertRaisesRegex(ContractError, 'CAMPAIGN_TASK_FAILURE_NO_INTEGRATION'):
            runner.integrate([task['task_id']], threading.Event())
        self.assertEqual(runner.review(task['task_id'], threading.Event())['reason'], 'REVIEW_ALREADY_DISPATCHED_NO_RETRY')

    def test_known_review_rejection_is_local_and_its_child_does_not_dispatch(self):
        q, runner, task, child = self.setup_review()
        result = self.review(runner, task, 'REJECT')
        self.assertEqual(result['status'], 'FAILED')
        self.assertEqual(result['failure_scope'], 'TASK')
        reopened = self.queue('review')
        self.assertTrue(reopened.failures_are_isolated())
        self.assertIsNone(reopened.claim())
        self.assertEqual(reopened.snapshot()['tasks'][-1]['state'], 'PENDING')

    def test_global_failure_arriving_during_review_blocks_publication(self):
        q, runner, task, child = self.setup_review()
        def mutate():
            with q.transaction() as db:
                db.execute("INSERT INTO integration_failures VALUES('global','evidence')")
        result = self.review(runner, task, mutate=mutate)
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertEqual(result['reason'], 'GLOBAL_FAILURE_BEFORE_REVIEW_PUBLICATION')
        with q.transaction() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM reviews').fetchone()[0], 0)
        self.assertEqual(q.snapshot()['tasks'][1]['state'], 'REVIEW')
        self.assertIsNone(q.claim())

    def test_tampered_failure_metadata_blocks_review_before_dispatch(self):
        q, runner, task, child = self.setup_review()
        with q.transaction() as db:
            row = db.execute("SELECT receipt FROM tasks WHERE id='task-1'").fetchone()
            receipt = json.loads(row['receipt']); receipt['provider_completion_known'] = False
            db.execute("UPDATE tasks SET receipt=? WHERE id='task-1'", (canonical(receipt),))
            # Even replacing the unkeyed hash cannot validate missing positive flags.
            db.execute("UPDATE isolated_task_failures SET receipt_hash=? WHERE task='task-1'", (fingerprint(receipt),))
        with patch.object(runner, '_run', side_effect=AssertionError('REVIEW_DISPATCHED_AFTER_TAMPER')):
            result = runner.review(task['task_id'], threading.Event())
        self.assertEqual(result['status'], 'BLOCKED')
        with q.transaction() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM development_review_dispatch').fetchone()[0], 0)

    def test_stale_artifact_during_review_never_publishes_pass(self):
        q, runner, task, child = self.setup_review()
        attempt = q.snapshot()['tasks'][1]['attempt_id']
        path = self.root / 'worktrees' / attempt / 'tests/test_api.py'
        result = self.review(runner, task, mutate=lambda: path.write_bytes(b'drift'))
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertEqual(result['reason'], 'REVIEW_CHANGED_ARTIFACT_OR_CANCELLED')
        self.assertEqual(q.snapshot()['tasks'][1]['state'], 'REVIEW')
        self.assertTrue(self.queue('review').integration_stopped())

    def test_unknown_review_and_crash_after_intent_block_restart_sibling_dispatch(self):
        for case in ('invalid', 'crash'):
            q, runner, task, child = self.setup_review(case)
            sibling = self.task(4); sibling['inputs'] = []; q.enqueue([sibling])
            if case == 'invalid':
                result = self.review(runner, task, 'UNVERIFIED')
                self.assertEqual(result['status'], 'BLOCKED')
                self.assertEqual(result['reason'], 'REVIEW_OUTPUT_INVALID')
                self.assertTrue(q.integration_stopped())
            else:
                # Crash after durable intent but before any receipt/failure marker.
                # Neither process disappearance nor an empty slot proves a verdict.
                with q.transaction() as db:
                    db.execute("INSERT INTO development_review_dispatch VALUES(?,'interrupted','intent')", (task['task_id'],))
            reopened = self.queue(case)
            self.assertIsNone(reopened.claim())
            with q.transaction() as db:
                db.execute('DELETE FROM supervisor_lock')
            class NeverDispatch:
                dispatches = 0
                def attempt(self, *args):
                    raise AssertionError('DISPATCH_AFTER_UNKNOWN_REVIEW')
                def review(self, *args):
                    raise AssertionError('REVIEW_AFTER_UNKNOWN_REVIEW')
            checked = NeverDispatch()
            Supervisor(reopened, self.root, self.repo, max_active=2, native_runner=checked,
                       capabilities={'backend'}).run(max_seconds=.2)
            self.assertEqual(checked.dispatches, 0)
            self.assertEqual(reopened.snapshot()['budget']['used'], 2)

    def test_late_global_failure_before_review_dispatch_consumes_no_turn(self):
        q, runner, task, child = self.setup_review()
        original = q.review_challenge
        def late(key, **kwargs):
            target = original(key, **kwargs)
            with q.transaction() as db:
                db.execute("INSERT INTO integration_failures VALUES('late','evidence')")
            return target
        with patch.object(q, 'review_challenge', side_effect=late), \
             patch.object(runner, '_run', side_effect=AssertionError('DISPATCH_AFTER_GLOBAL_FAILURE')):
            result = self.review(runner, task)
        self.assertEqual(result['status'], 'BLOCKED')
        with q.transaction() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM development_review_dispatch').fetchone()[0], 0)
