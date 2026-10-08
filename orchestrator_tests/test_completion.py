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

    def test_valid_attester_signature_still_cannot_release_production_review(self):
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
        with self.assertRaisesRegex(ContractError, 'REQUIRED_NATIVE_REVIEW_PROVENANCE_UNAVAILABLE'):
            queue.import_review(self.sign(target))
        self.assertEqual(queue.snapshot()['tasks'][0]['state'], 'REVIEW')
        with self.assertRaisesRegex(ContractError, 'NATIVE_SUPERVISOR_BLOCKED'):
            Supervisor(queue, self.root, self.repo)

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
