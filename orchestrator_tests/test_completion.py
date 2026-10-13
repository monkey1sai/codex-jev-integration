"""Signed fixtures are OFFLINE_TEST only, never actual Astra review evidence."""
import base64
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from orchestrator.contracts import canonical, fingerprint, ContractError
from orchestrator.evidence import digest
from orchestrator.phase2 import Phase2Queue
from orchestrator.pipeline import mock_attempt
from orchestrator.policy import compile_policy
from orchestrator.workspaces import fixture_repo, git, write_new
from orchestrator.snapshots import materialize
from orchestrator.supervisor import Supervisor
from orchestrator.validators import ValidatorRegistry
from orchestrator.merge_validation import conflicts, validate_queue_merge

ROOT = Path(__file__).resolve().parents[1]


class Completion(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.openssl = shutil.which('openssl')
        if not cls.openssl:
            raise RuntimeError('OpenSSL verifier required; missing dependency is not PASS')
        (ROOT / '.test-runs').mkdir(exist_ok=True)
        cls.keys = Path(tempfile.mkdtemp(prefix='synthetic-keys-', dir=ROOT / '.test-runs'))
        # New disposable synthetic signing material; no user credentials accessed.
        subprocess.run([cls.openssl, 'genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:2048',
                        '-out', str(cls.keys / 'fixture-private.pem')], check=True, capture_output=True, timeout=30)
        subprocess.run([cls.openssl, 'pkey', '-in', str(cls.keys / 'fixture-private.pem'), '-pubout',
                        '-out', str(cls.keys / 'fixture-public.pem')], check=True, capture_output=True, timeout=10)

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='completion-', dir=ROOT / '.test-runs'))
        self.repo, self.base = fixture_repo(self.root)
        (self.repo / '.codex').mkdir()
        config = {'routing': {'strategy': 'rules_only', 'jev_enabled': False},
                  'capabilities': {'synthetic': {'role': 'worker', 'description': 'Synthetic data only',
                                                'allowed_files': ['result0.json', 'result1.json', 'result2.json'],
                                                'validators': ['data-check']}},
                  'validators': {'data-check': {'argv': ['repo-fixed-data-validator'], 'timeout_seconds': 5}}}
        write_new(self.repo / '.codex/orchestrator.json', config)
        self.registry = self.root / 'controller/review-trust.json'
        self.registry_value = {'openssl': self.openssl, 'openssl_sha256': digest(Path(self.openssl).read_bytes()),
                               'reviewers': {'fixture-reviewer': {'public_key': str(self.keys / 'fixture-public.pem'),
                                 'sha256': digest((self.keys / 'fixture-public.pem').read_bytes()), 'kind': 'offline_fixture'}}}
        write_new(self.registry, self.registry_value)
        self.registry_hash = digest(self.registry.read_bytes())
        self.database = self.root / 'controller/queue.sqlite'
        self.queue = self.reopen()
        self.validator_path = self.root / 'controller/validator-trust.json'
        script = ROOT / 'orchestrator/mock_validator.py'
        config = self.queue.policy['settings']['validators']['data-check']
        self.validator_value = {'policy_hash': self.queue.policy['policy_hash'], 'mode': 'OFFLINE_TEST',
                  'validators': {'data-check': {'config_hash': fingerprint(config),
                    'argv': [sys.executable, '-I', '-S', '-B', str(script)],
                    'files': {sys.executable: digest(Path(sys.executable).read_bytes()), str(script): digest(script.read_bytes())}}}}
        write_new(self.validator_path, self.validator_value)
        self.validators = ValidatorRegistry(self.queue, self.validator_path, digest(self.validator_path.read_bytes()))

    def reopen(self, mode='OFFLINE_TEST'):
        return Phase2Queue(self.database, self.repo, evidence_mode=mode, review_registry=self.registry,
                           registry_sha256=self.registry_hash)

    def task(self, n=0, dependencies=()):
        return {'schema_version': 2, 'task_id': 'task-' + str(n), 'goal': 'Write fixed JSON answer 42',
                'inputs': ([{'path': 'result0.json', 'sha256': digest(b'{"answer":42}\n')}] if dependencies else []),
                'dependencies': list(dependencies), 'allowed_files': ['result' + str(n) + '.json'],
                'capability': 'synthetic', 'execution': {'role': 'worker', **self.queue.policy['settings']['roles']['worker'], 'native_children': 0},
                'acceptance_criteria': ['Fixed oracle passes'], 'tests': ['data-check'],
                'expected_artifacts': ['result' + str(n) + '.json'], 'budgets': {'runtime_seconds': 5, 'attempts': 2},
                'resource_locks': [], 'base_sha': self.base,
                'authorization': {'external_writes': False, 'scope': 'allocated_attempt_only'},
                'review': {'required': True, 'independent': True}}

    def execute(self, n=0):
        self.queue.enqueue([self.task(n)])
        return mock_attempt(self.queue, self.root, self.repo, validators=self.validators)

    def sign(self, target, **changes):
        payload = {'target': target, 'reviewer_id': 'fixture-reviewer', 'decision': 'PASS',
                   'observed_model': 'gpt-6-astra', 'observed_effort': 'high',
                   'execution_evidence_hash': digest(b'OFFLINE_TEST_NOT_ACTUAL_MODEL_REVIEW')}
        payload.update(changes)
        signed = subprocess.run([self.openssl, 'dgst', '-sha256', '-sign', str(self.keys / 'fixture-private.pem')],
                                input=canonical(payload).encode(), capture_output=True, check=True, timeout=10).stdout
        return {'payload': payload, 'signature': base64.b64encode(signed).decode()}

    def accepted(self):
        self.execute()
        envelope = self.sign(self.queue.review_challenge('task-0'))
        result = self.queue.import_review(envelope)
        self.assertEqual(result['state'], 'PASSED')
        self.assertEqual(result['evidence_mode'], 'OFFLINE_TEST')
        return envelope

    def test_signed_review_replay_spoof_stale_and_atomic_import(self):
        self.execute()
        envelope = self.sign(self.queue.review_challenge('task-0'))
        forged = deepcopy(envelope)
        forged['payload']['decision'] = 'REJECT'
        with self.assertRaisesRegex(ContractError, 'INVALID_SIGNATURE'):
            self.queue.import_review(forged)
        forged['payload']['reviewer_id'] = 'unregistered'
        with self.assertRaisesRegex(ContractError, 'UNKNOWN_REVIEWER'):
            self.queue.import_review(forged)
        def attempt(_):
            try:
                return self.reopen().import_review(envelope)['state']
            except ContractError:
                return 'REJECTED'
        with ThreadPoolExecutor(max_workers=2) as pool:
            result = list(pool.map(attempt, range(2)))
        self.assertEqual(sorted(result), ['PASSED', 'REJECTED'])
        with self.assertRaisesRegex(ContractError, 'REVIEW_REPLAY'):
            self.reopen().import_review(envelope)

    def test_expired_challenge_and_artifact_tamper_rejected(self):
        self.execute()
        target = self.queue.review_challenge('task-0', ttl=1)
        envelope = self.sign(target)
        with unittest.mock.patch('orchestrator.phase2.time.time', return_value=target['expires'] + 1):
            with self.assertRaisesRegex(ContractError, 'STALE_REVIEW'):
                self.queue.import_review(envelope)
        record = self.queue.snapshot()['tasks'][0]
        (self.queue.artifacts.root / record['attempt_id'] / 'result0.json').write_bytes(b'corrupt')
        with self.assertRaisesRegex(ContractError, 'ARTIFACT_DRIFT'):
            self.queue.import_review(envelope)

    def test_cross_mode_registry_drift_and_model_floor_rejected(self):
        self.execute()
        with self.assertRaisesRegex(ContractError, 'EVIDENCE_BINDING_DRIFT'):
            self.reopen(mode='production')
        target = self.queue.review_challenge('task-0')
        with self.assertRaisesRegex(ContractError, 'REVIEW_MODEL_FLOOR'):
            self.queue.import_review(self.sign(target, observed_model='gpt-6-luna'))
        self.registry.write_text('{}')
        with self.assertRaisesRegex(ContractError, 'TRUST_DRIFT'):
            self.queue.import_review(self.sign(target))

    def test_downstream_snapshot_exact_hash_and_missing_or_tampered_parent(self):
        self.accepted()
        child = self.task(1, ['task-0'])
        self.queue.enqueue([child])
        result = mock_attempt(self.queue, self.root, self.repo, validators=self.validators)
        self.assertEqual(result['status'], 'REVIEW')
        path = self.root / 'worktrees' / result['attempt_id'] / 'result0.json'
        self.assertEqual(path.read_bytes(), b'{"answer":42}\n')
        rows = self.queue.snapshot()['tasks']
        self.assertIsNotNone(json.loads(rows[1]['receipt'])['snapshot_hash'])
        parent = rows[0]
        (self.queue.artifacts.root / parent['attempt_id'] / 'result0.json').write_bytes(b'corrupt')
        third = self.task(2, ['task-0'])
        self.queue.enqueue([third])
        with self.assertRaisesRegex(ContractError, 'ARTIFACT_DRIFT'):
            mock_attempt(self.queue, self.root, self.repo, validators=self.validators)

    def integration_pair(self):
        self.accepted()
        self.execute(1)
        self.queue.import_review(self.sign(self.queue.review_challenge('task-1')))
        from orchestrator.merge_validation import prepare_integration
        return prepare_integration(self.queue, self.root, self.repo, ['task-0', 'task-1'])

    def test_reviewed_integration_restart_tree_and_registry_binding(self):
        from orchestrator.merge_validation import verify_integration
        prepared = self.integration_pair()
        self.assertTrue(verify_integration(self.reopen(), prepared))
        plan = self.validators.integration_plan(prepared)
        self.assertEqual(len(plan['commands']), 1)  # Identical validator is not run twice.
        self.assertEqual(plan['trusted_registry'], self.validators.sha256)
        self.assertFalse(plan['execution_authorized'])
        self.assertEqual(git(self.repo, 'rev-parse', 'HEAD'), self.base)
        self.assertFalse((self.repo / 'result0.json').exists())
        (Path(prepared['workspace']) / 'result0.json').write_bytes(b'tampered')
        with self.assertRaisesRegex(ContractError, 'INTEGRATION_TREE_DRIFT'):
            verify_integration(self.queue, prepared)

    def test_integration_prepared_metadata_forgery_is_rejected(self):
        from orchestrator.merge_validation import verify_integration
        prepared = self.integration_pair()
        prepared['baseline_hash'] = '0' * 64
        with self.assertRaisesRegex(ContractError, 'INTEGRATION_PREPARED_DRIFT'):
            verify_integration(self.queue, prepared)

    def test_integration_without_review_and_with_duplicate_owners_is_rejected(self):
        from orchestrator.merge_validation import prepare_integration
        self.execute()
        with self.assertRaisesRegex(ContractError, 'INTEGRATION_REVIEW_REQUIRED'):
            prepare_integration(self.queue, self.root, self.repo, ['task-0'])
        self.queue.import_review(self.sign(self.queue.review_challenge('task-0')))
        other = self.task(1)
        other['allowed_files'] = other['expected_artifacts'] = ['result0.json']
        self.queue.enqueue([other])
        mock_attempt(self.queue, self.root, self.repo, validators=self.validators)
        self.queue.import_review(self.sign(self.queue.review_challenge('task-1')))
        with self.assertRaisesRegex(ContractError, 'INTEGRATION_OWNERSHIP_CONFLICT'):
            prepare_integration(self.queue, self.root, self.repo, ['task-0', 'task-1'])

    def test_integration_native_failure_retains_unknown_capacity(self):
        from orchestrator.development import NativeDevelopmentRunner
        prepared = self.integration_pair()
        runner = NativeDevelopmentRunner.__new__(NativeDevelopmentRunner)
        runner.queue, runner.root, runner.repo = self.queue, self.root, self.repo
        runner.validators = self.validators
        runner._pins = self.queue._fresh
        def failed(plan, command, workspace, folder, stop, processes):
            processes.append({'role': 'unknown-test-process', 'execution': None})
            raise ContractError('INJECTED_NATIVE_START_UNKNOWN')
        runner._validator_command = failed
        report = runner.integrate(['task-0', 'task-1'], threading.Event())
        self.assertEqual(report['status'], 'BLOCKED')
        self.assertFalse(report['process_tree_empty'])
        self.assertFalse(report['merge_executed'])
        self.assertIsNone(self.reopen().claim())
        with self.reopen().transaction() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM development_native_slots').fetchone()[0], 2)

    def test_integration_cancel_before_native_launch_releases_reserved_slots(self):
        from orchestrator.development import NativeDevelopmentRunner
        self.integration_pair()
        runner = NativeDevelopmentRunner.__new__(NativeDevelopmentRunner)
        runner.queue, runner.root, runner.repo = self.queue, self.root, self.repo
        runner._pins = self.queue._fresh
        stop = threading.Event()
        stop.set()
        report = runner.integrate(['task-0', 'task-1'], stop)
        self.assertEqual(report['status'], 'BLOCKED')
        self.assertEqual(report['reason'], 'INTEGRATION_CANCELLED')
        with self.queue.transaction() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM development_native_slots').fetchone()[0], 0)

    def test_integration_known_validator_failure_latches_stop_across_restart(self):
        from orchestrator.development import NativeDevelopmentRunner
        from test_development import clean_process
        self.integration_pair()
        self.queue.enqueue([self.task(2, ['task-0'])])
        runner = NativeDevelopmentRunner.__new__(NativeDevelopmentRunner)
        runner.queue, runner.root, runner.repo = self.queue, self.root, self.repo
        runner.validators, runner._pins = self.validators, self.queue._fresh
        def failed(plan, command, workspace, folder, stop, processes):
            processes.append({'role': 'native-test-fixture', 'execution': clean_process()})
            raise ContractError('INJECTED_VALIDATOR_FAILED')
        runner._validator_command = failed
        stop = threading.Event()
        report = runner.integrate(['task-0', 'task-1'], stop)
        self.assertEqual(report['status'], 'BLOCKED')
        self.assertTrue(report['process_tree_empty'])
        self.assertTrue(stop.is_set())
        reopened = self.reopen()
        self.assertEqual(reopened.snapshot()['tasks'][2]['state'], 'READY')
        self.assertIsNone(reopened.claim(halt_on_failure=True))
        self.assertIsNone(reopened.claim())
        self.assertEqual(reopened.snapshot()['budget']['used'], 2)
        with self.assertRaisesRegex(ContractError, 'INTEGRATION_FAILURE_STOP'):
            runner.integrate(['task-0', 'task-1'], threading.Event())

    def test_integration_allows_unchanged_expected_artifact_without_widening_scope(self):
        from orchestrator.merge_validation import prepare_integration, verify_integration
        (self.repo / '.gitattributes').write_bytes(b'result1.json -text\n')
        (self.repo / 'result1.json').write_bytes(b'{"answer":42}\n')
        git(self.repo, 'add', '--', '.gitattributes', 'result1.json')
        git(self.repo, '-c', 'user.name=Test', '-c', 'user.email=test@localhost.invalid', 'commit', '-m', 'fixed baseline artifact')
        self.base = git(self.repo, 'rev-parse', 'HEAD')
        task = self.task()
        task['allowed_files'] = task['expected_artifacts'] = ['result0.json', 'result1.json']
        self.queue.enqueue([task])
        mock_attempt(self.queue, self.root, self.repo, validators=self.validators)
        self.queue.import_review(self.sign(self.queue.review_challenge('task-0')))
        prepared = prepare_integration(self.queue, self.root, self.repo, ['task-0'])
        self.assertEqual(len(prepared['batch']['files']), 2)
        self.assertTrue(verify_integration(self.queue, prepared))
        self.assertEqual((Path(prepared['workspace']) / 'result1.json').read_bytes(), b'{"answer":42}\n')

    def test_failed_integration_pending_review_restart_cannot_consume_review_turn(self):
        from orchestrator.development import NativeDevelopmentRunner
        from test_development import clean_process
        self.accepted()
        self.execute(1)  # REVIEW, separate from the selected accepted batch.
        runner = NativeDevelopmentRunner.__new__(NativeDevelopmentRunner)
        runner.queue, runner.root, runner.repo = self.queue, self.root, self.repo
        runner.validators, runner._pins = self.validators, self.queue._fresh
        def failed(plan, command, workspace, folder, stop, processes):
            processes.append({'role': 'fixture', 'execution': clean_process()})
            raise ContractError('INJECTED_VALIDATOR_FAILED')
        runner._validator_command = failed
        self.assertEqual(runner.integrate(['task-0'], threading.Event())['status'], 'BLOCKED')
        runner.queue = self.reopen()
        runner.supervisor_owner, runner.config_hash = 'test-owner', 'test-config'
        runner._settings, runner._argv = mock.Mock(return_value=({}, {})), mock.Mock(return_value=['OFFLINE_ONLY'])
        runner._run = mock.Mock(side_effect=AssertionError('PROVIDER_MUST_NOT_LAUNCH'))
        with runner.queue.transaction() as db:
            db.execute('CREATE TABLE development_review_dispatch(task TEXT PRIMARY KEY, nonce TEXT UNIQUE, intent_hash TEXT)')
            db.execute('CREATE TABLE supervisor_lock(id INTEGER PRIMARY KEY, owner TEXT, expires REAL)')
            db.execute('INSERT INTO supervisor_lock VALUES(1,?,?)', ('test-owner', time.time() + 60))
            row = db.execute("SELECT receipt FROM tasks WHERE id='task-1'").fetchone()
            receipt = json.loads(row[0])
            receipt['completion'] = {'native_thread_id': '00000000-0000-0000-0000-000000000001'}
            db.execute("UPDATE tasks SET receipt=? WHERE id='task-1'", (canonical(receipt),))
        result = runner.review('task-1', threading.Event())
        self.assertEqual(result['reason'], 'INTEGRATION_FAILURE_STOP')
        runner._run.assert_not_called()
        with runner.queue.transaction() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM development_review_dispatch').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM development_native_slots').fetchone()[0], 0)
        self.assertEqual(runner.queue.snapshot()['budget']['used'], 2)

    def test_continuous_supervisor_dag_review_and_backpressure(self):
        self.queue.enqueue([self.task(), self.task(1, ['task-0']), self.task(2, ['task-0'])])
        supervisor = Supervisor(self.queue, self.root, self.repo, max_active=2, validators=self.validators)
        with self.assertRaisesRegex(ContractError, 'SUPERVISOR_ALREADY_ACTIVE'):
            Supervisor(self.reopen(), self.root, self.repo)
        failures = []
        def review_loop():
            while not supervisor.stop.is_set():
                for row in self.queue.snapshot()['tasks']:
                    if row['state'] == 'REVIEW':
                        try:
                            self.queue.import_review(self.sign(self.queue.review_challenge(row['id'])))
                        except Exception as error:
                            failures.append(error)
                time.sleep(.02)
        thread = threading.Thread(target=review_loop)
        thread.start()
        try:
            result = supervisor.run(max_seconds=15)
        finally:
            supervisor.cancel()
            thread.join(timeout=5)
        self.assertEqual(failures, [])
        self.assertEqual([r['state'] for r in result['queue']['tasks']], ['PASSED'] * 3)
        self.assertEqual(result['native_dispatches'], 0)
        self.assertEqual(result['metrics']['peak_inflight_submissions'], 2)
        self.assertEqual(result['metrics']['scope'], 'CONTROLLER_RUN_ONLY_NOT_MODEL_PROCESS_OVERLAP')
        self.assertEqual(self.reopen().snapshot()['budget']['used'], 3)

    def test_supervisor_cancel_restart_and_expiry_keep_fences(self):
        self.queue.enqueue([self.task()])
        supervisor = Supervisor(self.queue, self.root, self.repo, validators=self.validators)
        timer = threading.Timer(.25, supervisor.cancel)
        timer.start()
        result = supervisor.run(max_seconds=2, behavior='timeout')
        timer.join()
        self.assertEqual(result['queue']['tasks'][0]['state'], 'CANCELLED')
        self.assertEqual(self.reopen().snapshot()['budget']['used'], 1)
        # Safe restart cannot create another attempt for a cancelled task.
        second = Supervisor(self.reopen(), self.root, self.repo)
        self.assertEqual(second.run(max_seconds=.2)['outcomes'], [])

    def test_repo_validator_exit_timeout_and_task_command_injection(self):
        self.execute()
        task = self.task(1)
        task['tests'] = ['python -c injected']
        with self.assertRaisesRegex(ContractError, 'UNREGISTERED_VALIDATOR'):
            self.queue.enqueue([task])
        self.validator_path.write_text('{}')
        self.queue.enqueue([self.task(1)])
        with self.assertRaisesRegex(ContractError, 'VALIDATOR_TRUST_DRIFT'):
            mock_attempt(self.queue, self.root, self.repo, validators=self.validators)

    def test_local_merge_candidate_binding_clean_conflict_and_main_unchanged(self):
        self.accepted()
        (self.repo / 'result0.json').write_bytes(b'{"answer":42}\n')
        git(self.repo, 'add', '--', 'result0.json')
        git(self.repo, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@localhost.invalid', 'commit', '-m', 'candidate')
        candidate = git(self.repo, 'rev-parse', 'HEAD')
        result = validate_queue_merge(self.queue, 'task-0', self.repo, candidate, candidate)
        self.assertEqual(result['status'], 'CLEAN')
        self.assertEqual(result['eligibility'], 'OFFLINE_TEST_ONLY')
        self.assertEqual(git(self.repo, 'rev-parse', 'HEAD'), candidate)
        git(self.repo, 'checkout', '-b', 'conflicting', self.base)
        (self.repo / 'result0.json').write_bytes(b'{"answer":99}\n')
        git(self.repo, 'add', '--', 'result0.json')
        git(self.repo, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@localhost.invalid', 'commit', '-m', 'conflict')
        other = git(self.repo, 'rev-parse', 'HEAD')
        result = validate_queue_merge(self.queue, 'task-0', self.repo, other, candidate)
        self.assertEqual(result['status'], 'CONFLICT')
        self.assertEqual(git(self.repo, 'rev-parse', 'HEAD'), other)
        with self.assertRaisesRegex(ContractError, 'MERGE_CANDIDATE_ARTIFACT_DRIFT'):
            validate_queue_merge(self.queue, 'task-0', self.repo, other, other)
        with self.assertRaisesRegex(ContractError, 'MERGE_EXECUTION_DISABLED'):
            self.queue.merge(authorized=True)

    def test_invalid_claim_has_no_artifact_or_validator_filesystem_side_effect(self):
        self.queue.enqueue([self.task()])
        claim = self.queue.claim(capabilities={'synthetic'})
        self.queue.start(claim)
        self.queue.validating(claim)
        forged = deepcopy(claim)
        forged['attempt_id'] = '../../escaped-attempt'
        with self.assertRaisesRegex(ContractError, 'INVALID_ATTEMPT_ID'):
            self.queue.artifacts.publish(forged, self.repo)
        with self.assertRaisesRegex(ContractError, 'INVALID_ATTEMPT_ID'):
            self.validators.run(forged, self.repo)
        self.assertFalse(self.queue.artifacts.root.exists())
        self.assertFalse((self.root / 'controller/validator-temp').exists())
        self.assertFalse((self.root / 'escaped-attempt').exists())

    def test_validated_bytes_replaced_before_publication_are_rejected(self):
        self.queue.enqueue([self.task()])
        claim = self.queue.claim(capabilities={'synthetic'})
        self.queue.start(claim)
        self.queue.validating(claim)
        (self.repo / 'result0.json').write_bytes(b'changed-after-validation')
        with self.assertRaisesRegex(ContractError, 'VALIDATED_ARTIFACT_DRIFT'):
            self.queue.artifacts.publish(claim, self.repo, {'result0.json': digest(b'{"answer":42}\n')})
        self.assertFalse(self.queue.artifacts.root.exists())
        self.queue.fence(claim)
        with self.assertRaisesRegex(ContractError, 'STALE_ARTIFACT_PUBLICATION'):
            self.queue.artifacts.publish(claim, self.repo)

    def test_receipt_manifest_mismatch_cannot_issue_review_challenge(self):
        self.execute()
        with self.queue.transaction() as db:
            receipt = json.loads(db.execute('SELECT receipt FROM tasks').fetchone()[0])
            receipt['artifacts']['result0.json'] = digest(b'other')
            db.execute('UPDATE tasks SET receipt=?', (canonical(receipt),))
        with self.assertRaisesRegex(ContractError, 'VALIDATION_RECEIPT_ARTIFACT_DRIFT'):
            self.queue.review_challenge('task-0')

    def test_review_cross_queue_and_stale_attempt_are_rejected(self):
        self.execute()
        envelope = self.sign(self.queue.review_challenge('task-0'))
        other = Phase2Queue(self.root / 'controller/other.sqlite', self.repo, evidence_mode='OFFLINE_TEST',
                            review_registry=self.registry, registry_sha256=self.registry_hash)
        with self.assertRaisesRegex(ContractError, 'REVIEW_REPLAY_OR_UNKNOWN'):
            other.import_review(envelope)
        with self.queue.transaction() as db:
            db.execute('UPDATE tasks SET epoch=epoch+1')
        with self.assertRaisesRegex(ContractError, 'STALE_REVIEW'):
            self.queue.import_review(envelope)

    def test_validator_nonzero_exit_is_evidenced_and_held(self):
        self._validator_failure('--fail', 'EXIT_CODE')

    def test_validator_timeout_is_fenced_and_evidenced(self):
        self._validator_failure('--timeout', 'TIMEOUT')

    def _validator_failure(self, flag, reason):
        # A fresh controller explicitly pins the fixed synthetic validator variant.
        self.queue = Phase2Queue(self.root / 'controller/variant.sqlite', self.repo, evidence_mode='OFFLINE_TEST',
                                 review_registry=self.registry, registry_sha256=self.registry_hash)
        value = deepcopy(self.validator_value)
        value['validators']['data-check']['argv'].append(flag)
        path = self.root / 'controller/variant-validators.json'
        write_new(path, value)
        self.validators = ValidatorRegistry(self.queue, path, digest(path.read_bytes()))
        with self.assertRaisesRegex(ContractError, 'VALIDATOR_FAILED:' + reason):
            self.execute()
        row = self.queue.snapshot()['tasks'][0]
        self.assertEqual(row['state'], 'HELD')
        evidence = json.loads((self.root / 'controller/validator-evidence' / row['attempt_id'] / 'data-check/receipt.json').read_bytes())
        self.assertTrue(evidence['process_tree_empty'])
        self.assertEqual(evidence['reason'], 'TIMEOUT' if reason == 'TIMEOUT' else None)
        self.assertEqual(evidence['returncode'], 7 if reason == 'EXIT_CODE' else 1)

    def test_supervisor_lost_ownership_cancels_before_wait_and_fences(self):
        self.queue.enqueue([self.task()])
        supervisor = Supervisor(self.queue, self.root, self.repo)
        started = threading.Event()
        def worker(queue, root, repo, *, claim, stop, **kwargs):
            started.set()
            if not stop.wait(2):
                raise AssertionError('cancel was delayed until executor shutdown')
            self.assertFalse(queue.start(claim))
            return {'status': 'HELD'}
        original = supervisor._renew
        calls = 0
        def renew():
            nonlocal calls
            calls += 1
            if calls == 2:
                self.assertTrue(started.wait(1))
                raise ContractError('STALE_SUPERVISOR')
            original()
        with mock.patch('orchestrator.supervisor.mock_attempt', side_effect=worker), mock.patch.object(supervisor, '_renew', side_effect=renew):
            began = time.monotonic()
            with self.assertRaisesRegex(ContractError, 'STALE_SUPERVISOR'):
                supervisor.run(max_seconds=3)
            self.assertLess(time.monotonic() - began, 2)
        row = self.queue.snapshot()['tasks'][0]
        self.assertEqual(row['state'], 'HELD')
        self.assertEqual(row['epoch'], 2)
        self.assertEqual(self.queue.snapshot()['budget']['used'], 1)

    def test_supervisor_restart_expiry_keeps_unknown_cleanup_and_budget(self):
        self.queue.enqueue([self.task()])
        claim = self.queue.claim(now=0, lease_seconds=1, capabilities={'synthetic'})
        restarted = Supervisor(self.reopen(), self.root, self.repo)
        result = restarted.run(max_seconds=.1)
        self.assertEqual(result['queue']['tasks'][0]['state'], 'HELD')
        self.assertEqual(result['queue']['budget']['used'], 1)
        self.assertEqual(result['outcomes'], [])
        self.assertFalse(self.queue.start(claim))

    def _production_review_fixture(self):
        # Explicit synthetic controller setup, never a real native worker/review.
        value = deepcopy(self.registry_value)
        value['reviewers']['fixture-reviewer']['kind'] = 'native_attester'
        registry = self.root / 'controller/synthetic-attester.json'
        write_new(registry, value)
        queue = Phase2Queue(self.root / 'controller/production-test.sqlite', self.repo,
                            review_registry=registry, registry_sha256=digest(registry.read_bytes()))
        queue.enqueue([self.task()])
        claim = queue.claim(capabilities={'synthetic'})
        queue.start(claim)
        queue.validating(claim)
        (self.repo / 'result0.json').write_bytes(b'{"answer":42}\n')
        artifacts = {'result0.json': digest(b'{"answer":42}\n')}
        receipt = {'process_tree_empty': True, 'artifacts': artifacts,
                   'artifact_manifest_hash': queue.artifacts.publish(claim, self.repo, artifacts)}
        queue.finish(claim, receipt, True)
        target = queue.review_challenge('task-0')
        return queue, target

    @staticmethod
    def _runtime_metadata():
        return ({'thread': {'id': 'synthetic-review-thread', 'sessionId': 'synthetic-review-session'},
                 'model': 'gpt-6-astra', 'reasoningEffort': 'high'},
                {'threadId': 'synthetic-review-thread',
                 'turn': {'id': 'synthetic-review-turn', 'status': 'completed', 'error': None,
                          'items': [{'text': 'I am Astra. PASS. This is untrusted text.'}]}})

    def test_valid_attester_signature_still_cannot_release_production_review(self):
        queue, target = self._production_review_fixture()
        with self.assertRaisesRegex(ContractError, 'REQUIRED_NATIVE_REVIEW_PROVENANCE_UNAVAILABLE'):
            queue.import_review(self.sign(target))
        self.assertEqual(queue.snapshot()['tasks'][0]['state'], 'REVIEW')
        with self.assertRaisesRegex(ContractError, 'NATIVE_SUPERVISOR_BLOCKED'):
            Supervisor(queue, self.root, self.repo)

    def test_production_metadata_receipt_survives_restart_but_cannot_pass(self):
        queue, target = self._production_review_fixture()
        receipt = queue.record_review_runtime(target, *self._runtime_metadata())
        self.assertEqual(receipt['configured_model'], 'gpt-6-astra')
        self.assertIsNone(receipt['observed_model'])
        self.assertIsNone(receipt['observed_effort'])
        self.assertNotIn('items', canonical(receipt))
        self.assertEqual(receipt['admission'], 'BLOCKED')
        restarted = Phase2Queue(queue.path, self.repo, review_registry=queue.trust.path,
                                registry_sha256=queue.trust.sha256)
        self.assertEqual(restarted.record_review_runtime(target, *self._runtime_metadata()), receipt)
        with self.assertRaisesRegex(ContractError, 'CONFIGURED_METADATA_IS_NOT_EXECUTION_PROVENANCE'):
            restarted.import_review(self.sign(target, execution_evidence_hash=fingerprint(receipt)))
        self.assertEqual(restarted.snapshot()['tasks'][0]['state'], 'REVIEW')
        with restarted.transaction() as db:
            self.assertEqual(db.execute('SELECT used FROM review_challenges').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM reviews').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM review_runtime').fetchone()[0], 1)
            events = [json.loads(r[0]) for r in db.execute('SELECT event FROM events')]
        rejected = next(e for e in events if e['event'] == 'review_admission_rejected')
        evidence = json.loads((restarted.path.parent / 'review-admission' /
                               (rejected['evidence_id']+'.json')).read_bytes())
        self.assertEqual(rejected['receipt_hash'], fingerprint(evidence))
        self.assertNotIn('signature', canonical(evidence))
        self.assertEqual(restarted.merge_snapshot()[0]['status'], 'HELD')

    def test_production_runtime_evidence_hash_and_file_tamper_are_rejected(self):
        queue, target = self._production_review_fixture()
        receipt = queue.record_review_runtime(target, *self._runtime_metadata())
        with self.assertRaisesRegex(ContractError, 'EXECUTION_RECEIPT_MISMATCH'):
            queue.import_review(self.sign(target))
        (queue.path.parent / 'review-runtime' / (target['nonce'] + '.json')).write_bytes(b'tampered')
        with self.assertRaisesRegex(ContractError, 'REVIEW_RUNTIME_FILE_DRIFT'):
            queue.import_review(self.sign(target, execution_evidence_hash=fingerprint(receipt)))
        self.assertEqual(queue.snapshot()['tasks'][0]['state'], 'REVIEW')

    def test_runtime_metadata_missing_mismatched_and_failed_turn_rejected(self):
        queue, target = self._production_review_fixture()
        start, finish = self._runtime_metadata()
        cases = [(dict(start, model=None), finish, 'CONFIG_MISSING'),
                 (start, dict(finish, threadId='worker-thread'), 'SESSION_MISMATCH'),
                 (start, dict(finish, turn={'id': 'turn', 'status': 'interrupted'}), 'NOT_COMPLETED'),
                 (dict(start, thread={'id': 't'}), finish, 'SCHEMA')]
        for a, b, error in cases:
            with self.subTest(error=error), self.assertRaisesRegex(ContractError, error):
                queue.record_review_runtime(target, a, b)
        with queue.transaction() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM review_runtime').fetchone()[0], 0)

    def test_runtime_metadata_drift_foreign_target_and_expiry_rejected(self):
        queue, target = self._production_review_fixture()
        start, finish = self._runtime_metadata()
        queue.record_review_runtime(target, start, finish)
        with self.assertRaisesRegex(ContractError, 'REPLAY_OR_DRIFT'):
            queue.record_review_runtime(target, dict(start, model='gpt-6-luna'), finish)
        with self.assertRaisesRegex(ContractError, 'REPLAY_OR_UNKNOWN'):
            queue.record_review_runtime(dict(target, attempt_id='f'*32), start, finish)
        with mock.patch('orchestrator.phase2.time.time', return_value=target['expires']+1):
            with self.assertRaisesRegex(ContractError, 'STALE_REVIEW'):
                queue.record_review_runtime(target, start, finish)
        other = Phase2Queue(self.root / 'controller/foreign-prod.sqlite', self.repo,
                            review_registry=queue.trust.path, registry_sha256=queue.trust.sha256)
        with self.assertRaisesRegex(ContractError, 'REPLAY_OR_UNKNOWN'):
            other.record_review_runtime(target, start, finish)

    def test_runtime_metadata_crash_orphan_recovery_and_source_claim_not_trusted(self):
        queue, target = self._production_review_fixture()
        from orchestrator.admission import app_server_review_metadata
        from orchestrator.evidence import frozen_bytes
        start, finish = self._runtime_metadata()
        start.update(observed_model='gpt-6-astra', observed_effort='ultra', source='official', trusted=True)
        receipt = app_server_review_metadata(target, start, finish)
        frozen_bytes(queue.path.parent / 'review-runtime' / (target['nonce']+'.json'), canonical(receipt).encode())
        stored = queue.record_review_runtime(target, start, finish)
        self.assertEqual(stored, receipt)
        self.assertIsNone(stored['observed_model'])
        self.assertIn('UNTRUSTED_RUNTIME_SOURCE', stored['blockers'])
        with self.assertRaisesRegex(ContractError, 'PROVENANCE_UNAVAILABLE'):
            queue.import_review(self.sign(target, execution_evidence_hash=fingerprint(stored)))

    def test_forged_production_review_is_audited_without_consuming_nonce(self):
        queue, target = self._production_review_fixture()
        envelope = self.sign(target)
        envelope['payload']['decision'] = 'REJECT'
        with self.assertRaisesRegex(ContractError, 'INVALID_SIGNATURE'):
            queue.import_review(envelope)
        with queue.transaction() as db:
            self.assertEqual(db.execute('SELECT used FROM review_challenges').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT state FROM tasks').fetchone()[0], 'REVIEW')
        records = list((queue.path.parent/'review-admission').glob('*.json'))
        self.assertEqual(len(records), 1)
        record = json.loads(records[0].read_bytes())
        self.assertEqual(record['reason'], 'INVALID_SIGNATURE')
        self.assertEqual(record['envelope_hash'], fingerprint(envelope))

    def _validator_claim(self, production=False, value=None):
        queue = (Phase2Queue(self.root / 'controller/prod-validator.sqlite', self.repo)
                 if production else self.queue)
        pinned = deepcopy(value or self.validator_value)
        pinned.update(mode=queue.evidence_mode, policy_hash=queue.policy['policy_hash'])
        path = self.root / 'controller/admission-validators.json'
        write_new(path, pinned)
        registry = ValidatorRegistry(queue, path, digest(path.read_bytes()))
        queue.enqueue([self.task()])
        claim = queue.claim(capabilities={'synthetic'})
        queue.start(claim)
        queue.validating(claim)
        return queue, registry, claim

    def test_production_validator_pins_are_checked_without_host_execution(self):
        queue, registry, claim = self._validator_claim(production=True)
        with mock.patch('orchestrator.validators.bounded_run', side_effect=AssertionError('no host fallback')):
            plan = registry.plan(claim, self.repo)
            self.assertFalse(plan['execution_authorized'])
            with self.assertRaisesRegex(ContractError, 'VALIDATOR_NATIVE_SANDBOX_BLOCKED'):
                registry.run(claim, self.repo)
        self.assertEqual(queue.snapshot()['tasks'][0]['state'], 'VALIDATING')
        records = list((queue.path.parent / 'validator-admission' / claim['attempt_id']).glob('*.json'))
        self.assertEqual(len(records), 1)
        record = json.loads(records[0].read_bytes())
        self.assertEqual(record['execution'], 'NOT_RUN')
        self.assertEqual(record['plan']['task_hash'], claim['task_hash'])
        self.assertEqual(record['plan']['epoch'], claim['epoch'])
        self.assertFalse((queue.path.parent / 'validator-temp').exists())
        with queue.transaction() as db:
            events = [json.loads(r[0]) for r in db.execute('SELECT event FROM events')]
        event = next(e for e in events if e['event'] == 'validator_admission_blocked')
        self.assertEqual(event['receipt_hash'], fingerprint(record))

    def test_validator_unpinned_and_nonliteral_argv_are_rejected(self):
        value = deepcopy(self.validator_value)
        value['validators']['data-check']['argv'][0] = 'python'
        queue, registry, claim = self._validator_claim(production=True, value=value)
        with mock.patch('orchestrator.validators.bounded_run', side_effect=AssertionError('no launch')):
            with self.assertRaisesRegex(ContractError, 'VALIDATOR_ARGV'):
                registry.run(claim, self.repo)

    def test_validator_executable_drift_is_rejected_before_native_admission(self):
        value = deepcopy(self.validator_value)
        value['validators']['data-check']['files'][sys.executable] = '0'*64
        queue, registry, claim = self._validator_claim(production=True, value=value)
        with self.assertRaisesRegex(ContractError, 'VALIDATOR_EXECUTABLE_DRIFT'):
            registry.run(claim, self.repo)
        self.assertFalse((queue.path.parent / 'validator-temp').exists())

    def test_validator_already_cancelled_never_starts_process(self):
        queue, registry, claim = self._validator_claim()
        stop = threading.Event()
        stop.set()
        with mock.patch('orchestrator.validators.bounded_run', side_effect=AssertionError('no launch after cancel')):
            with self.assertRaisesRegex(ContractError, 'VALIDATOR_FAILED:CANCELLED'):
                registry.run(claim, self.repo, stop=stop)
        self.assertEqual(queue.snapshot()['tasks'][0]['state'], 'HELD')
        self.assertFalse((queue.path.parent / 'validator-temp').exists())

    def test_validator_expired_attempt_cannot_write_admission_evidence(self):
        queue, registry, claim = self._validator_claim(production=True)
        queue.fence(claim, 'interrupt')
        with self.assertRaisesRegex(ContractError, 'STALE_ARTIFACT_PUBLICATION'):
            registry.run(claim, self.repo)
        self.assertFalse((queue.path.parent / 'validator-admission').exists())

    def test_existing_cli_status_response_contract_preserved(self):
        result = subprocess.run([sys.executable, '-B', '-m', 'orchestrator', 'phase2-status',
                                 '--repo', str(self.repo), '--database', str(self.database),
                                 '--evidence-mode', 'OFFLINE_TEST', '--review-registry', str(self.registry),
                                 '--registry-sha256', self.registry_hash], cwd=ROOT,
                                capture_output=True, check=True, timeout=10)
        response = json.loads(result.stdout)
        self.assertFalse(response['executed'])
        self.assertFalse(response['merge_executed'])
        self.assertEqual(response['native_dispatches'], 0)
        self.assertEqual(response['queue']['tasks'], [])
