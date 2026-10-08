"""Offline contract guards; these never claim a native/model smoke PASS."""
from copy import deepcopy
import json
import unittest

from test_global_core import Fixture
from orchestrator.contracts import ContractError
from orchestrator.development import toml, native_success, tool_evidence, typed_review
from orchestrator.development import fixture_arithmetic, review_artifacts
from orchestrator.development import process_clean, attempt_cleanup_known


def clean_process():
    return {'status': 'EXITED', 'exit_code': 0, 'remaining_cgroup_pids': [],
            'output_readers_closed': True, 'output_limit_exceeded': False, 'unit': 'fixture.service',
            'observed_control_group': '/user.slice/fixture.service',
            'kernel_resource_limits': {'memory.max': '1073741824', 'memory.swap.max': '0', 'pids.max': '64'}}
from orchestrator.phase2 import Phase2Queue
from orchestrator.policy import compile_policy
from orchestrator.supervisor import Supervisor


class DevelopmentContracts(Fixture):
    def test_native_scratch_is_audited_separately_from_project_diff(self):
        from orchestrator.workspaces import scan
        from orchestrator.pipeline import artifact_manifest
        from unittest.mock import patch
        workspace = self.root / 'workspace'
        (workspace / '.tmp').mkdir(parents=True)
        (workspace / 'artifact').mkdir()
        before = scan(workspace, ignore_scratch=True)
        (workspace / '.tmp/lock').write_bytes(b'')
        (workspace / 'artifact/add.py').write_bytes(b'def add(a,b): return a+b\n')
        task = self.task()
        task.update(allowed_files=['artifact/add.py'], expected_artifacts=['artifact/add.py'], inputs=[])
        claim = {'task': task, 'task_hash': '1' * 64, 'attempt_id': 'a' * 32, 'epoch': 1}
        with patch('orchestrator.pipeline.git', return_value=task['base_sha']):
            receipt = artifact_manifest(workspace, claim, before, general=True, ignore_scratch=True)
        self.assertEqual(receipt['changed_files'], ['artifact/add.py'])
        self.assertIn('.tmp/lock', scan(workspace))
        (workspace / 'unexpected.py').write_bytes(b'changed')
        with patch('orchestrator.pipeline.git', return_value=task['base_sha']):
            with self.assertRaisesRegex(ContractError, 'OUT_OF_SCOPE_DIFF'):
                artifact_manifest(workspace, claim, before, general=True, ignore_scratch=True)

    def test_scratch_size_and_reparse_guards_are_not_excluded(self):
        from orchestrator.workspaces import scan
        workspace = self.root / 'workspace'
        (workspace / '.tmp').mkdir(parents=True)
        (workspace / '.tmp/large').write_bytes(b'0' * (2 * 1024 * 1024 + 1))
        with self.assertRaisesRegex(ContractError, 'ARTIFACT_SIZE_LIMIT'):
            scan(workspace, ignore_scratch=True)
    def test_explicit_mode_keeps_all_other_floors(self):
        high = compile_policy(self.repo)
        dev = compile_policy(self.repo, execution_mode='development')
        self.assertFalse(high['floors']['live_execution'])
        self.assertTrue(dev['floors']['live_execution'])
        for key, value in high['floors'].items():
            if key != 'live_execution':
                self.assertEqual(dev['floors'][key], value)
        self.assertNotEqual(high['policy_hash'], dev['policy_hash'])
        self.assertEqual(dev['settings']['scheduler']['max_active'], 2)

    def test_session_cannot_choose_mode_or_disable_review(self):
        for overlay in ({'execution_mode': 'development'}, {'floors': {'required_review': False}}):
            with self.assertRaises(ContractError):
                compile_policy(self.repo, session=overlay)

    def test_old_queue_cannot_be_reopened_as_development(self):
        path = self.root / 'controller/realm.sqlite'
        Phase2Queue(path, self.repo, evidence_mode='OFFLINE_TEST')
        with self.assertRaises(ContractError):
            Phase2Queue(path, self.repo, evidence_mode='DEVELOPMENT')

    def test_restart_binding_and_no_retry_intent(self):
        path = self.root / 'controller/dev.sqlite'
        queue = Phase2Queue(path, self.repo, evidence_mode='DEVELOPMENT')
        queue.enqueue([self.task()])
        claim = queue.claim()
        queue.start(claim)
        self.assertTrue(queue.dispatch_intent(claim))
        reopened = Phase2Queue(path, self.repo, evidence_mode='DEVELOPMENT')
        self.assertFalse(reopened.dispatch_intent(claim))
        reopened.fence(claim)
        self.assertFalse(reopened.cleanup(claim, tree_empty=True, retry=True))
        self.assertFalse(reopened.finish(claim, {'process_tree_empty': True}, True))

    def test_caller_cannot_import_development_review(self):
        queue = Phase2Queue(self.root / 'dev.sqlite', self.repo, evidence_mode='DEVELOPMENT')
        with self.assertRaisesRegex(ContractError, 'CONTROLLER_EXECUTION'):
            queue.import_review({'payload': {'decision': 'PASS', 'observed_model': 'gpt-6-astra'}})
        with self.assertRaisesRegex(ContractError, 'MERGE_EXECUTION_DISABLED'):
            queue.merge()

    def test_native_supervisor_requires_explicit_runner_and_capacity(self):
        queue = Phase2Queue(self.root / 'dev.sqlite', self.repo, evidence_mode='DEVELOPMENT')
        with self.assertRaisesRegex(ContractError, 'NATIVE_RUNNER_REQUIRED'):
            Supervisor(queue, self.root, self.repo)
        with self.assertRaisesRegex(ContractError, 'ACTIVE_CAP'):
            Supervisor(queue, self.root, self.repo, native_runner=object(), max_active=3)
        other = Phase2Queue(self.root / 'offline.sqlite', self.repo, evidence_mode='OFFLINE_TEST')
        with self.assertRaisesRegex(ContractError, 'RUNNER_REALM_MISMATCH'):
            Supervisor(other, self.root, self.repo, native_runner=object())

    def test_review_capacity_survives_restart(self):
        path = self.root / 'controller/dev.sqlite'
        queue = Phase2Queue(path, self.repo, evidence_mode='DEVELOPMENT')
        queue.enqueue([self.task(), self.task(2)])
        with queue.transaction() as db:
            db.execute('INSERT INTO development_native_slots VALUES(?,?,?)', ('review1', 'external1', 'nonce1'))
            db.execute('INSERT INTO development_native_slots VALUES(?,?,?)', ('review2', 'external2', 'nonce2'))
        reopened = Phase2Queue(path, self.repo, evidence_mode='DEVELOPMENT')
        self.assertIsNone(reopened.claim())

    def test_worker_clean_cannot_release_unknown_validator_capacity(self):
        path = self.root / 'controller/dev.sqlite'
        queue = Phase2Queue(path, self.repo, evidence_mode='DEVELOPMENT')
        queue.enqueue([self.task()])
        claim = queue.claim()
        queue.start(claim)
        queue.validating(claim)
        queue.fence(claim, 'validator_cleanup_unknown')
        processes = [{'role': 'worker', 'execution': clean_process()},
                     {'role': 'validator', 'execution': {**clean_process(), 'status': 'CLEANUP_UNVERIFIED'}}]
        self.assertFalse(attempt_cleanup_known(processes))
        self.assertFalse(queue.cleanup(claim, tree_empty=attempt_cleanup_known(processes)))
        reopened = Phase2Queue(path, self.repo, evidence_mode='DEVELOPMENT')
        self.assertEqual(reopened.snapshot()['tasks'][0]['state'], 'HELD')
        self.assertTrue(reopened.snapshot()['locks'])

    def test_launch_exception_keeps_cleanup_unknown(self):
        self.assertFalse(attempt_cleanup_known([{'role': 'worker', 'execution': clean_process()},
                                               {'role': 'validator', 'execution': None}]))
        execution = {**clean_process(), 'status': 'CLEANUP_UNVERIFIED'}
        self.assertFalse(process_clean(execution))

    def test_actual_attempt_failure_keeps_unknown_process_locks(self):
        from pathlib import Path
        import threading
        from unittest.mock import Mock, patch
        from orchestrator.development import NativeDevelopmentRunner
        for failed_role in ('worker', 'validator'):
            with self.subTest(failed_role=failed_role):
                queue = Phase2Queue(self.root / failed_role / 'controller/queue.sqlite', self.repo,
                                    evidence_mode='DEVELOPMENT')
                task = self.task()
                task['inputs'] = []
                queue.enqueue([task])
                claim = queue.claim()
                workspace = self.root / failed_role / 'workspace'
                workspace.mkdir(parents=True)
                runner = NativeDevelopmentRunner.__new__(NativeDevelopmentRunner)
                runner.queue, runner.root, runner.repo = queue, self.root, self.repo
                from orchestrator.evidence import digest
                runner.config = workspace / 'native-config-fixture'
                runner.config.write_bytes(b'public test config')
                runner.config_hash, runner.pins, runner.dispatches = digest(runner.config.read_bytes()), {}, 0
                runner._counter_lock = threading.Lock()
                runner.artifact_guard, runner.expected_stdout = None, {}
                plan = {'commands': [{'validator': 'unit', 'files': {}, 'argv': ['fixture-only'], 'timeout_seconds': 1}]}
                runner.validators = Mock()
                runner.validators.plan.return_value = plan
                def launch(argv, folder, prefix, *args, **kwargs):
                    if prefix == 'worker':
                        raw = b'{"type":"thread.started","thread_id":"00000000-0000-0000-0000-000000000001"}\n'
                        raw += b'{"type":"item.completed","item":{"id":"fixture-tool","type":"file_change","status":"completed"}}\n'
                        raw += b'{"type":"turn.completed"}\n'
                        (folder / 'worker.jsonl').write_bytes(raw)
                        kwargs['monitor'].feed(raw)
                    return {**clean_process(), 'status': 'CLEANUP_UNVERIFIED' if prefix == failed_role or (prefix == 'unit' and failed_role == 'validator') else 'EXITED'}
                with patch('orchestrator.development.allocate', return_value=(workspace, self.root)), \
                     patch('orchestrator.development.materialize', return_value={'snapshot_hash': 'fixture'}), \
                     patch('orchestrator.development.artifact_manifest', return_value={}), \
                     patch.object(runner, '_settings', return_value=({}, {})), \
                     patch.object(runner, '_argv', return_value=['fixture-only']), \
                     patch.object(runner, '_pins', return_value=None), \
                     patch.object(runner, '_run', side_effect=launch):
                    result = runner.attempt(claim, threading.Event())
                self.assertFalse(result['cleanup_known'])
                self.assertEqual(queue.snapshot()['tasks'][0]['state'], 'HELD')
                self.assertTrue(queue.snapshot()['locks'])
                self.assertEqual(len(result['processes']), 1 if failed_role == 'worker' else 2)
        execution = {**clean_process(), 'observed_control_group': None}
        self.assertFalse(process_clean(execution))

    def test_review_workspace_must_match_published_hash(self):
        from orchestrator.evidence import digest
        file = self.repo / 'source.py'
        file.write_bytes(b'def add(a,b): return a+b\n')
        manifest = {'artifacts': {'source.py': digest(file.read_bytes())}}
        self.assertIn('source.py', review_artifacts(manifest, self.repo))
        file.write_bytes(b'def add(a,b): return a-b\n')
        with self.assertRaisesRegex(ContractError, 'ARTIFACT_MISMATCH'):
            review_artifacts(manifest, self.repo)

    def test_policy_drift_during_review_cannot_publish_pass(self):
        import threading
        from unittest.mock import patch
        from orchestrator.development import NativeDevelopmentRunner
        from orchestrator.evidence import digest
        queue = Phase2Queue(self.root / 'controller/dev.sqlite', self.repo, evidence_mode='DEVELOPMENT')
        task = self.task()
        task['inputs'], task['expected_artifacts'] = [], ['src/api.py']
        queue.enqueue([task])
        claim = queue.claim()
        queue.start(claim)
        queue.validating(claim)
        workspace = self.root / 'worktrees' / claim['attempt_id']
        artifacts = {}
        for name in task['expected_artifacts']:
            file = workspace / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(b'public fixture\n')
            artifacts[name] = digest(file.read_bytes())
        manifest = queue.artifacts.publish(claim, workspace, artifacts)
        queue.finish(claim, {'process_tree_empty': True, 'artifact_manifest_hash': manifest,
                            'artifacts': artifacts, 'validator_evidence': [],
                            'completion': {'native_thread_id': '00000000-0000-0000-0000-000000000001'}}, True)
        runner = NativeDevelopmentRunner.__new__(NativeDevelopmentRunner)
        runner.queue, runner.root, runner.repo = queue, self.root, self.repo
        runner.config_hash, runner.dispatches = 'fixture-pin', 0
        runner._pins = queue._fresh
        with queue.transaction() as db:
            # Native constructor is excluded from this offline execution seam.
            db.execute('CREATE TABLE development_review_dispatch(task TEXT PRIMARY KEY, nonce TEXT UNIQUE, intent_hash TEXT)')
        supervisor = Supervisor(queue, self.root, self.repo, native_runner=runner)
        runner.supervisor_owner = supervisor.owner
        def launch(argv, folder, *args):
            raw = [{'type': 'thread.started', 'thread_id': '00000000-0000-0000-0000-000000000002'},
                   {'type': 'item.completed', 'item': {'type': 'agent_message',
                    'text': '{"decision":"PASS","findings":[]}'}}, {'type': 'turn.completed'}]
            (folder / 'reviewer.jsonl').write_text('\n'.join(json.dumps(item) for item in raw) + '\n')
            policy = self.repo / '.codex/orchestrator.json'
            policy.write_bytes(policy.read_bytes() + b' ')
            return clean_process()
        with patch.object(runner, '_settings', return_value=({}, {})), \
             patch.object(runner, '_argv', return_value=['fixture-only']), \
             patch.object(runner, '_run', side_effect=launch):
            result = runner.review(task['task_id'], threading.Event())
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertEqual(result['reason'], 'QUEUE_POLICY_DRIFT')
        with queue.transaction() as db:
            self.assertEqual(db.execute('SELECT state FROM tasks').fetchone()[0], 'REVIEW')
            self.assertEqual(db.execute('SELECT count(*) FROM reviews').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM development_review_dispatch').fetchone()[0], 1)

    def test_native_scope_uses_directory_ceiling_and_rejects_other_paths(self):
        from orchestrator.development import NativeDevelopmentRunner
        runner = NativeDevelopmentRunner.__new__(NativeDevelopmentRunner)
        runner.runtime = self.root
        runner.original_filesystem = {':minimal': 'read', ':workspace_roots': {}}
        settings, filesystem = runner._settings(self.repo, ['artifact/add.py'], {'model': 'gpt-6.1-sol', 'reasoning_effort': 'medium'})
        self.assertEqual(filesystem[':workspace_roots']['artifact'], 'write')
        self.assertNotIn('artifact/add.py', filesystem[':workspace_roots'])
        _, readonly = runner._settings(self.repo, [], {'model': 'gpt-6-astra', 'reasoning_effort': 'high'})
        self.assertEqual(readonly[':workspace_roots']['artifact'], 'read')
        with self.assertRaisesRegex(ContractError, 'OUTSIDE_PROFILE'):
            runner._settings(self.repo, ['src/add.py'], {'model': 'gpt-6.1-sol', 'reasoning_effort': 'medium'})

    def test_development_uses_native_validator_not_host_fallback(self):
        from pathlib import Path
        from orchestrator.validators import ValidatorRegistry
        from orchestrator.contracts import canonical, fingerprint
        from orchestrator.evidence import digest, frozen_bytes
        import sys
        queue = Phase2Queue(self.root / 'dev.sqlite', self.repo, evidence_mode='DEVELOPMENT')
        executable = str(Path(sys.executable).absolute())
        value = {'policy_hash': queue.policy['policy_hash'], 'mode': 'DEVELOPMENT', 'validators': {'unit': {
            'config_hash': fingerprint(queue.policy['settings']['validators']['unit']),
            'argv': [executable, '-I', '-B', '-c', 'print("fixture")'],
            'files': {executable: digest(Path(executable).read_bytes())}}}}
        path = self.root / 'registry.json'
        frozen_bytes(path, canonical(value).encode())
        registry = ValidatorRegistry(queue, path, digest(path.read_bytes()))
        queue.enqueue([self.task()])
        claim = queue.claim()
        queue.start(claim)
        queue.validating(claim)
        # Even in Development the old direct-host runner remains closed.
        from unittest.mock import patch
        with patch('orchestrator.validators.bounded_run', side_effect=AssertionError('HOST_FALLBACK')) as launch:
            with self.assertRaisesRegex(ContractError, 'VALIDATOR_NATIVE_SANDBOX_BLOCKED'):
                registry.run(claim, self.repo)
        launch.assert_not_called()

    def test_existing_failure_prevents_native_claim_and_dispatch(self):
        from unittest.mock import Mock
        for state in ('FAILED', 'CANCELLED', 'HELD'):
            with self.subTest(state=state):
                queue = Phase2Queue(self.root / state / 'dev.sqlite', self.repo, evidence_mode='DEVELOPMENT')
                a, b = self.task(), self.task(2)
                b['allowed_files'] = ['tests/test_api.py']
                queue.enqueue([a, b])
                claim = queue.claim()
                queue.start(claim)
                if state == 'FAILED':
                    queue.validating(claim)
                    queue.finish(claim, {'process_tree_empty': True}, False)
                else:
                    queue.fence(claim)
                    if state == 'CANCELLED':
                        queue.cleanup(claim, tree_empty=True, retry=False)
                before = queue.snapshot()
                self.assertIsNone(queue.claim(halt_on_failure=True))
                self.assertEqual(queue.snapshot(), before)
                runner = Mock(dispatches=0)
                result = Supervisor(queue, self.root, self.repo, max_active=2,
                                    native_runner=runner, capabilities={'backend'}).run(max_seconds=3)
                runner.attempt.assert_not_called()
                runner.review.assert_not_called()
                self.assertEqual(result['queue'], before)

    def test_native_failure_cancels_other_worker_without_review(self):
        import threading
        queue = Phase2Queue(self.root / 'dev.sqlite', self.repo, evidence_mode='DEVELOPMENT')
        a, b = self.task(), self.task(2)
        b['allowed_files'] = ['tests/test_api.py']
        queue.enqueue([a, b])
        barrier = threading.Barrier(2)
        class StubRunner:
            dispatches = 2
            cancelled = False
            def attempt(self, claim, stop):
                queue.start(claim)
                barrier.wait(timeout=3)
                if claim['task']['task_id'] == a['task_id']:
                    queue.fence(claim, 'offline_failure_fixture')
                    queue.cleanup(claim, tree_empty=True, retry=False)
                    return {'status': 'BLOCKED', 'offline_stub': True}
                self.cancelled = stop.wait(2)
                queue.fence(claim, 'offline_cancel_fixture')
                return {'status': 'HELD', 'offline_stub': True}
            def review(self, task_id, stop):
                raise AssertionError('REVIEW_AFTER_FAILURE')
        runner = StubRunner()
        result = Supervisor(queue, self.root, self.repo, max_active=2,
                            native_runner=runner, capabilities={'backend'}).run(max_seconds=10)
        self.assertTrue(runner.cancelled)
        self.assertEqual(result['queue']['budget']['used'], 2)
        self.assertNotIn('PASSED', {row['state'] for row in result['queue']['tasks']})

    def test_review_failure_stops_before_second_review(self):
        queue = Phase2Queue(self.root / 'dev.sqlite', self.repo, evidence_mode='DEVELOPMENT')
        a, b = self.task(), self.task(2)
        b['allowed_files'] = ['tests/test_api.py']
        queue.enqueue([a, b])
        class StubRunner:
            dispatches = 2
            reviews = []
            def attempt(self, claim, stop):
                queue.start(claim)
                queue.validating(claim)
                queue.finish(claim, {'process_tree_empty': True}, True)
                return {'status': 'REVIEW', 'offline_stub': True}
            def review(self, task_id, stop):
                self.reviews.append(task_id)
                with queue.transaction() as db:
                    db.execute("UPDATE tasks SET state='FAILED' WHERE id=?", (task_id,))
                return {'status': 'FAILED', 'offline_stub': True}
        runner = StubRunner()
        result = Supervisor(queue, self.root, self.repo, max_active=2,
                            native_runner=runner, capabilities={'backend'}).run(max_seconds=10)
        self.assertEqual(len(runner.reviews), 1)
        self.assertEqual({row['state'] for row in result['queue']['tasks']}, {'FAILED', 'REVIEW'})

    def test_supervisor_renews_during_serial_native_review(self):
        import time
        queue = Phase2Queue(self.root / 'dev.sqlite', self.repo, evidence_mode='DEVELOPMENT')
        queue.enqueue([self.task()])
        class StubRunner:
            dispatches = 0
            def attempt(self, claim, stop):
                queue.start(claim)
                queue.validating(claim)
                queue.finish(claim, {'process_tree_empty': True}, True)
                return {'status': 'REVIEW', 'offline_stub': True}
            def review(self, task_id, stop):
                with queue.transaction() as db:
                    before = db.execute('SELECT expires FROM supervisor_lock').fetchone()[0]
                time.sleep(2.3)
                with queue.transaction() as db:
                    after = db.execute('SELECT expires FROM supervisor_lock').fetchone()[0]
                self.renewed = after > before
                return {'status': 'BLOCKED', 'offline_stub': True}
        runner = StubRunner()
        supervisor = Supervisor(queue, self.root, self.repo, native_runner=runner, capabilities={'backend'})
        supervisor.run(max_seconds=10)
        self.assertTrue(runner.renewed)


class NativeEvidence(unittest.TestCase):
    def test_pure_fixture_rejects_import_time_exit_and_wrong_operation(self):
        fixture_arithmetic(b'def add(a,b): return a+b\n', 'add')
        for data in (b'import sys; sys.exit(0)\n', b'def add(a,b): return a-b\n',
                     b'print("ACCEPTANCE_PASS:add"); exit(0)\n', b'@evil\ndef add(a,b): return a+b\n'):
            with self.assertRaises(ContractError):
                fixture_arithmetic(data, 'add')
    def test_toml_is_literal_and_roundtrips(self):
        import tomllib
        value = {':workspace_roots': {'.': 'read', 'artifact/add.py': 'write'}, 'path': 'a"b\\c', 'flag': False}
        self.assertEqual(tomllib.loads('value=' + toml(value))['value'], value)

    def test_exit_zero_without_completion_is_rejected(self):
        execution = clean_process()
        with self.assertRaisesRegex(ContractError, 'COMPLETION_NOT_VERIFIED'):
            native_success(execution, b'{"type":"thread.started"}\n')
        with self.assertRaisesRegex(ContractError, 'NO_REAL_TOOL'):
            tool_evidence(b'{"type":"turn.completed"}\n')

    def test_typed_review_does_not_accept_caller_model_assertions(self):
        for text in ('PASS', '{"decision":"PASS","model":"gpt-6-astra"}', '{"decision":"PASS","findings":false}'):
            raw = json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': text}}).encode()
            with self.assertRaisesRegex(ContractError, 'REVIEW_OUTPUT_INVALID'):
                typed_review(raw)
        raw = json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message',
            'text': '{"decision":"PASS","findings":[]}'}}).encode()
        self.assertEqual(typed_review(raw)['decision'], 'PASS')

    def test_leftover_processes_and_failed_tools_rejected(self):
        execution = {'status': 'EXITED', 'exit_code': 0, 'remaining_cgroup_pids': ['123'],
                     'output_readers_closed': True, 'output_limit_exceeded': False}
        with self.assertRaises(ContractError):
            native_success(execution, b'{"type":"turn.completed"}\n')
        raw = b'{"type":"item.completed","item":{"type":"file_change","status":"failed"}}\n'
        with self.assertRaises(ContractError):
            tool_evidence(raw)

    def test_native_thread_identity_is_required_in_execution_receipt(self):
        execution = clean_process()
        with self.assertRaisesRegex(ContractError, 'THREAD_IDENTITY_MISSING'):
            native_success(execution, b'{"type":"turn.completed"}\n')
        raw = b'{"type":"thread.started","thread_id":"00000000-0000-0000-0000-000000000001"}\n{"type":"turn.completed"}\n'
        self.assertEqual(native_success(execution, raw)['native_thread_id'], '00000000-0000-0000-0000-000000000001')
