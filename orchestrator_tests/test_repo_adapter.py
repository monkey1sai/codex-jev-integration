"""Zero-provider guards for the opt-in real-repo seam."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from orchestrator.contracts import canonical, ContractError
from orchestrator.evidence import digest, frozen_bytes
from orchestrator.pipeline import artifact_manifest
from orchestrator.repo_adapter import RepoAdapter, repository_scan
from orchestrator.workspaces import allocate, git, scan
from orchestrator.phase2 import Phase2Queue


class RealRepoAdapter(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / 'controller').mkdir()
        for name in ('controller-git-hooks', 'controller-git-template'):
            (self.root / name).mkdir()
        self.repo = self.root / 'source-repo'
        self.repo.mkdir()
        self.record = self.root / 'controller/repo-adapter.json'
        self.record.write_text(canonical({'mode': 'DEVELOPMENT_REPO', 'repo': str(self.repo)}))
        git(self.repo, 'init', '-b', 'baseline')
        for name, data in {'AGENTS.md': b'Only assigned paths', 'scripts/zip.mjs': b'old',
                           'tests/zip.test.ts': b'old', 'public/model.bin': b'0' * (3 * 1024 * 1024)}.items():
            frozen_bytes(self.repo / name, data)
        git(self.repo, 'add', '--', '.')
        git(self.repo, '-c', 'user.name=Adapter Test', '-c', 'user.email=test@localhost.invalid', 'commit', '-m', 'test baseline')
        self.base = git(self.repo, 'rev-parse', 'HEAD')
        node = self.root / 'controller/node'
        node.write_bytes(b'fixed-node-fixture')
        deps = self.root / 'controller/dependencies'
        deps.mkdir()
        (deps / 'trusted.js').write_bytes(b'dependency')
        self.value = {'mode': 'DEVELOPMENT_REPO', 'repo': str(self.repo), 'source': 'public/test',
            'base_sha': self.base, 'bundle_sha256': '1' * 64,
            'allowed_files': ['scripts/zip.mjs', 'tests/zip.test.ts'],
            'node': str(node), 'node_sha256': digest(node.read_bytes()), 'dependencies': str(deps),
            'dependency_hashes': repository_scan(deps), 'protected_hashes': {'AGENTS.md': digest((self.repo / 'AGENTS.md').read_bytes())}}
        self.record.write_text(canonical(self.value))
        self.adapter = RepoAdapter(self.root)
        self.claim = {'attempt_id': 'a' * 32, 'task_hash': '2' * 64, 'epoch': 1,
            'task': {'base_sha': self.base, 'allowed_files': self.value['allowed_files'],
                     'expected_artifacts': self.value['allowed_files'], 'inputs': [], 'tests': ['unit']}}

    def workspace(self):
        workspace, _ = allocate(self.root, self.repo, self.claim)
        (workspace / '.tmp').mkdir()
        self.adapter.prepare(workspace)
        return workspace

    def test_real_worktree_preserves_source_and_exact_sha(self):
        path = self.workspace()
        self.assertEqual(git(path, 'rev-parse', 'HEAD'), self.base)
        self.assertEqual((path / 'node_modules/trusted.js').read_bytes(), b'dependency')
        self.assertFalse((self.repo / 'node_modules').exists())

    def test_synthetic_limits_remain_while_repo_is_bounded(self):
        path = self.workspace()
        with self.assertRaisesRegex(ContractError, 'SIZE_LIMIT'):
            scan(path)
        self.assertIn('public/model.bin', self.adapter.scan(path))

    def test_exact_diff_and_artifact_custody(self):
        path = self.workspace()
        before = self.adapter.scan(path, ignore_scratch=True)
        for name in self.value['allowed_files']:
            (path / name).write_bytes(b'new')
        value = artifact_manifest(path, self.claim, before, general=True, ignore_scratch=True, scanner=self.adapter.scan)
        self.assertEqual(value['artifacts']['scripts/zip.mjs'], digest(b'new'))
        self.assertEqual(value['changed_files'], self.value['allowed_files'])

    def test_untracked_and_dependency_edits_cannot_hide(self):
        path = self.workspace()
        before = self.adapter.scan(path, ignore_scratch=True)
        (path / 'scripts/zip.mjs').write_bytes(b'new')
        for name in ('rogue.txt', 'node_modules/trusted.js'):
            (path / name).write_bytes(b'bad')
            with self.assertRaisesRegex(ContractError, 'OUT_OF_SCOPE_DIFF'):
                artifact_manifest(path, self.claim, before, general=True, scanner=self.adapter.scan)
            if name == 'rogue.txt':
                (path / name).unlink()

    def test_scratch_is_audited_separately(self):
        path = self.workspace()
        before = self.adapter.scan(path, ignore_scratch=True)
        (path / '.tmp/build').mkdir()
        (path / '.tmp/build/index.html').write_bytes(b'built')
        self.assertEqual(before, self.adapter.scan(path, ignore_scratch=True))
        self.assertIn('.tmp/build/index.html', self.adapter.scan(path))

    def test_permission_scope_does_not_grant_repo_root(self):
        path = self.workspace()
        files, _ = self.adapter.permissions(path, self.value['allowed_files'], [])
        self.assertEqual(files['.'], 'read')
        self.assertEqual(files['scripts'], 'write')
        self.assertEqual(files['.git'], 'read')
        self.assertEqual(files['node_modules'], 'read')
        self.assertEqual(files['artifact'], 'read')
        readonly, _ = self.adapter.permissions(path, [], [])
        self.assertNotIn('scripts', readonly)
        with self.assertRaisesRegex(ContractError, 'WRITE_SCOPE'):
            self.adapter.permissions(path, ['src/other.ts'], [])

    def test_dependency_drift_blocks_before_worker(self):
        (self.adapter.dependencies / 'trusted.js').write_bytes(b'changed')
        path, _ = allocate(self.root, self.repo, self.claim)
        with self.assertRaisesRegex(ContractError, 'DEPENDENCY_DRIFT'):
            self.adapter.prepare(path)

    def test_node_and_config_drift_fail_closed(self):
        (self.repo / 'AGENTS.md').write_bytes(b'changed')
        with self.assertRaisesRegex(ContractError, 'CONFIG_DRIFT'):
            self.adapter.verify()
        (self.repo / 'AGENTS.md').write_bytes(b'Only assigned paths')
        Path(self.value['node']).write_bytes(b'new-node')
        with self.assertRaisesRegex(ContractError, 'NODE_DRIFT'):
            self.adapter.verify()

    def test_readonly_instruction_pins_do_not_use_write_contract(self):
        self.adapter.verify()  # AGENTS.md is a protected write path, valid read pin.
        (self.repo / '.codex').mkdir()
        (self.repo / '.codex/orchestrator.json').write_bytes(b'{}')
        value = json.loads(self.record.read_text())
        value['protected_hashes']['.codex/orchestrator.json'] = digest(b'{}')
        self.record.write_text(canonical(value))
        RepoAdapter(self.root).verify()

    def test_record_replacement_rejected_after_restart(self):
        self.record.write_text(canonical({**self.value, 'base_sha': '0' * 40}))
        with self.assertRaisesRegex(ContractError, 'ADAPTER_DRIFT'):
            self.adapter.verify()
        with self.assertRaisesRegex(ContractError, 'ADAPTER_BASE'):
            RepoAdapter(self.root)

    def test_restart_revalidates_tree_and_scope(self):
        path = self.workspace()
        value = self.adapter.scan(path)
        reopened = RepoAdapter(self.root)
        self.assertEqual(reopened.scan(path), value)
        self.assertIn('diff', reopened.review_context(path))

    def test_binding_requires_one_turn_development_with_jev_off(self):
        queue = Phase2Queue(self.root / 'controller/test.sqlite', self.repo, evidence_mode='DEVELOPMENT',
            session={'routing': {'jev_enabled': False}, 'scheduler': {'max_dispatches': 1}})
        self.adapter.bind(queue, self.root, self.repo)
        queue.policy['settings']['scheduler']['max_dispatches'] = 2
        with self.assertRaisesRegex(ContractError, 'BINDING'):
            self.adapter.bind(queue, self.root, self.repo)

    def test_fresh_adapter_cannot_rebind_changed_dependency_identity(self):
        session = {'routing': {'jev_enabled': False}, 'scheduler': {'max_dispatches': 1}}
        path = self.root / 'controller/test.sqlite'
        queue = Phase2Queue(path, self.repo, evidence_mode='DEVELOPMENT', session=session)
        self.adapter.bind(queue, self.root, self.repo)
        (self.adapter.dependencies / 'trusted.js').write_bytes(b'new')
        self.value['dependency_hashes'] = repository_scan(self.adapter.dependencies)
        self.record.write_text(canonical(self.value))
        changed = RepoAdapter(self.root)
        reopened = Phase2Queue(path, self.repo, evidence_mode='DEVELOPMENT', session=session)
        with self.assertRaisesRegex(ContractError, 'RESTART_DRIFT'):
            changed.bind(reopened, self.root, self.repo)
        self.assertEqual(reopened.snapshot()['budget']['used'], 0)

    def test_readiness_drift_blocks_before_dispatch_marker(self):
        from tools.game_repo_campaign import verify_readiness
        from orchestrator.contracts import fingerprint
        envelope = {'campaign_id': self.root.name, 'adapter_hash': self.adapter.hash, 'policy_hash': 'policy'}
        frozen_bytes(self.root / 'envelope.json', canonical(envelope).encode())
        ready = {**envelope, 'status': 'READY_ZERO_PROVIDER', 'native_config_hash': 'runtime', 'envelope_hash': fingerprint(envelope)}
        (self.root / 'preflight.json').write_text(canonical(ready))
        queue = SimpleNamespace(policy={'policy_hash': 'policy'})
        runner = SimpleNamespace(config_hash='runtime')
        verify_readiness(self.root, queue, self.adapter, runner)
        ready['adapter_hash'] = 'changed'
        (self.root / 'preflight.json').write_text(canonical(ready))
        with self.assertRaisesRegex(ContractError, 'READINESS_BINDING'):
            verify_readiness(self.root, queue, self.adapter, runner)
        self.assertFalse((self.root / 'execute-once.json').exists())

    def test_removal_and_symlink_do_not_evade_audit(self):
        path = self.workspace()
        (path / 'scripts/zip.mjs').unlink()
        with self.assertRaisesRegex(ContractError, 'REMOVAL_DRIFT'):
            self.adapter.scan(path)
