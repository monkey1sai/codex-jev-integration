"""Opt-in real-repo Development contract; no new queue or executor."""
import json
import shutil
import stat
from pathlib import Path

from .contracts import ContractError, canonical, fingerprint, relative_file
from .evidence import guarded, digest, frozen_bytes
from .policy import identifier, load, safe_path
from .workspaces import scan, git

MAX_BYTES = 256 * 1024 * 1024
MAX_FILES = 20000


def repository_scan(workspace, *, ignore_scratch=False):
    return scan(workspace, ignore_scratch=ignore_scratch, max_bytes=MAX_BYTES, max_files=MAX_FILES)


def file_modes(workspace):
    return {p.relative_to(workspace).as_posix(): stat.S_IMODE(p.stat().st_mode)
            for p in workspace.rglob('*') if p.is_file() and not p.relative_to(workspace).as_posix().startswith('.tmp/')}


class RepoAdapter:
    """Trusted controller selection, never task-provided paths or commands."""
    def __init__(self, root):
        self.root = guarded(root).resolve(strict=True)
        self.path = self.root / 'controller/repo-adapter.json'
        self.value, self.hash = load(self.path, max_bytes=2 * 1024 * 1024)
        v = self.value
        if set(v) - {'campaign', 'readonly_tools'} != {'mode', 'repo', 'source', 'base_sha', 'bundle_sha256', 'allowed_files',
                      'node', 'node_sha256', 'dependencies', 'dependency_hashes', 'protected_hashes'}:
            raise ContractError('REPO_ADAPTER_SCHEMA')
        self.repo = guarded(v['repo'])
        self.dependencies = guarded(v['dependencies'])
        if (v['mode'] != 'DEVELOPMENT_REPO' or self.repo != self.root / 'source-repo'
                or not self.dependencies.is_relative_to(self.root / 'controller')
                or self.repo.is_relative_to(self.dependencies)):
            raise ContractError('REPO_ADAPTER_SCOPE')
        if (type(v['allowed_files']) is not list or not v['allowed_files']
                or len(set(v['allowed_files'])) != len(v['allowed_files'])):
            raise ContractError('REPO_ADAPTER_FILES')
        for name in v['allowed_files']:
            relative_file(name)
            if name.split('/')[0] not in {'src', 'scripts', 'tests'} or name in v['protected_hashes']:
                raise ContractError('REPO_ADAPTER_FILES')
        self.campaign = v.get('campaign')
        if self.campaign is not None:
            c = self.campaign
            if type(c) is not dict or set(c) != {'campaign_id', 'max_active', 'worker_budget', 'review_budget', 'tasks'}:
                raise ContractError('REPO_CAMPAIGN_SCHEMA')
            identifier(c['campaign_id'])
            if (c['campaign_id'] != self.root.name or type(c['tasks']) is not dict
                    or not 1 <= len(c['tasks']) <= 38
                    or type(c['worker_budget']) is not int or c['worker_budget'] != len(c['tasks'])
                    or type(c['review_budget']) is not int or not 0 <= c['review_budget'] <= c['worker_budget']
                    or type(c['max_active']) is not int or not 1 <= c['max_active'] <= 2):
                raise ContractError('REPO_CAMPAIGN_LIMIT')
            for task_id, entry in c['tasks'].items():
                identifier(task_id)
                if (type(entry) is not dict or set(entry) != {'task_hash', 'allowed_files', 'validators', 'worker_checks'}
                        or not isinstance(entry['task_hash'], str) or len(entry['task_hash']) != 64
                        or any(ch not in '0123456789abcdef' for ch in entry['task_hash'])):
                    raise ContractError('REPO_CAMPAIGN_TASK')
                for field in ('allowed_files', 'validators', 'worker_checks'):
                    if (type(entry[field]) is not list or not entry[field] or len(entry[field]) > 64
                            or any(not isinstance(item, str) for item in entry[field])
                            or len(set(entry[field])) != len(entry[field])):
                        raise ContractError('REPO_CAMPAIGN_TASK')
                if (not set(entry['allowed_files']) <= set(v['allowed_files'])
                        or not set(entry['worker_checks']) <= set(entry['validators'])):
                    raise ContractError('REPO_CAMPAIGN_TASK')
                for name in entry['validators']:
                    identifier(name)
        self.verify()
        if git(self.repo, 'rev-parse', 'HEAD') != v['base_sha']:
            raise ContractError('REPO_ADAPTER_BASE')

    def verify(self):
        if load(self.path, max_bytes=2 * 1024 * 1024)[1] != self.hash:
            raise ContractError('REPO_ADAPTER_DRIFT')
        v = self.value
        if digest(guarded(v['node']).read_bytes()) != v['node_sha256']:
            raise ContractError('REPO_NODE_DRIFT')
        tools = v.get('readonly_tools', {})
        if type(tools) is not dict or len(tools) > 4:
            raise ContractError('REPO_TOOL_SCHEMA')
        for name, tool in tools.items():
            identifier(name)
            if type(tool) is not dict or set(tool) != {'root', 'executable', 'sha256'}:
                raise ContractError('REPO_TOOL_SCHEMA')
            root, executable = guarded(tool['root']), guarded(tool['executable'])
            if (root.parent != self.root / 'controller/toolchains' or not root.is_dir()
                    or not executable.is_relative_to(root) or not executable.is_file()):
                raise ContractError('REPO_TOOL_SCOPE')
            if digest(executable.read_bytes()) != tool['sha256']:
                raise ContractError('REPO_TOOL_DRIFT')
        for name, sha in v['protected_hashes'].items():
            # Write-contract paths deliberately reject AGENTS/.codex. These
            # separately trusted readonly pins must not use that write parser.
            if name not in {'AGENTS.md', 'CONTEXT.md', 'package.json', 'package-lock.json',
                            'vite.config.ts', 'tsconfig.json', '.codex/orchestrator.json', '.codex/jev.json'}:
                raise ContractError('REPO_PROTECTED_PIN_PATH')
            if digest(safe_path(self.repo, name).read_bytes()) != sha:
                raise ContractError('REPO_CONFIG_DRIFT')

    def bind(self, queue, root, repo):
        expected_dispatches = self.campaign['worker_budget'] if self.campaign else 1
        if (root != self.root or repo != self.repo or queue.evidence_mode != 'DEVELOPMENT'
                or queue.policy['settings']['routing']['jev_enabled']
                or queue.policy['settings']['scheduler']['max_dispatches'] != expected_dispatches
                or (self.campaign and (queue.policy['settings']['scheduler']['max_active'] > self.campaign['max_active']
                                       or queue.policy['settings']['scheduler']['max_attempts'] != 1))):
            raise ContractError('REPO_ADAPTER_BINDING')
        with queue.transaction() as db:
            db.execute('CREATE TABLE IF NOT EXISTS repo_adapter_binding(id INTEGER PRIMARY KEY CHECK(id=1), hash TEXT)')
            db.execute('INSERT OR IGNORE INTO repo_adapter_binding VALUES(1,?)', (self.hash,))
            if db.execute('SELECT hash FROM repo_adapter_binding').fetchone()[0] != self.hash:
                raise ContractError('REPO_ADAPTER_RESTART_DRIFT')

    def authorize_task(self, task):
        """Pinned controller contract, not a grant to exceed repo/runtime ceilings."""
        self.verify()
        if not self.campaign:
            return []  # Preserve the legacy single-task contract and evidence.
        entry = self.campaign['tasks'].get(task['task_id'])
        if (not entry or entry['task_hash'] != fingerprint(task)
                or task['base_sha'] != self.value['base_sha']
                or task['allowed_files'] != entry['allowed_files'] or task['tests'] != entry['validators']
                or task['budgets']['attempts'] != 1):
            raise ContractError('REPO_CAMPAIGN_CONTRACT_DRIFT')
        return entry['worker_checks']

    @property
    def review_budget(self):
        return self.campaign['review_budget'] if self.campaign else 1

    def prepare(self, workspace):
        self.verify()
        workspace = guarded(workspace)
        if workspace.parent != self.root / 'worktrees' or git(workspace, 'rev-parse', 'HEAD') != self.value['base_sha']:
            raise ContractError('REPO_WORKTREE_BINDING')
        if repository_scan(self.dependencies) != self.value['dependency_hashes']:
            raise ContractError('REPO_DEPENDENCY_DRIFT')
        shutil.copytree(self.dependencies, workspace / 'node_modules', symlinks=False)
        if repository_scan(workspace / 'node_modules') != self.value['dependency_hashes']:
            raise ContractError('REPO_DEPENDENCY_COPY')
        frozen_bytes(self.root / 'controller/workspace-modes' / (workspace.name + '.json'),
                     canonical(file_modes(workspace)).encode())

    def scan(self, workspace, *, ignore_scratch=False):
        workspace = guarded(workspace)
        result = repository_scan(workspace, ignore_scratch=ignore_scratch)
        modes, _ = load(self.root / 'controller/workspace-modes' / (workspace.name + '.json'), max_bytes=2 * 1024 * 1024)
        current = file_modes(workspace)
        if any(current.get(name) != mode for name, mode in modes.items()):
            raise ContractError('REPO_FILE_MODE_OR_REMOVAL_DRIFT')
        return result

    def permissions(self, workspace, allowed_files, extra_reads):
        self.verify()
        if not set(allowed_files) <= set(self.value['allowed_files']):
            raise ContractError('REPO_NATIVE_WRITE_SCOPE')
        files = {'.': 'read', 'artifact': 'read', '.tmp': 'write', '.git': 'read', '.codex': 'read', '.agents': 'read',
                 'node_modules': 'read', '**/*.env': 'deny'}
        # Native directory roots; exact file scope remains controller enforced.
        for name in allowed_files:
            files[str(Path(name).parent)] = 'write'
        for name in self.value['protected_hashes']:
            files[name] = 'read'
        reads = (*extra_reads, str(Path(self.value['node']).parent),
                 *(tool['root'] for tool in self.value.get('readonly_tools', {}).values()))
        return files, reads

    def receipt(self, workspace, baseline):
        after = self.scan(workspace, ignore_scratch=True)
        return {'adapter_hash': self.hash, 'source': self.value['source'], 'base_sha': self.value['base_sha'],
                'bundle_sha256': self.value['bundle_sha256'], 'baseline_hash': fingerprint(baseline),
                'candidate_tree_hash': fingerprint(after), 'dependency_tree_hash': fingerprint(self.value['dependency_hashes']),
                'modes_hash': fingerprint(file_modes(workspace)), 'native_write_scope': 'DIRECTORY_ROOTS',
                'exact_allowed_files_gate': 'CONTROLLER_DIFF', 'generated_output_root': '.tmp',
                'visual_acceptance': 'NOT_APPLICABLE_PACKAGING_ONLY', 'merge_executed': False}

    def review_context(self, workspace):
        self.scan(workspace, ignore_scratch=True)
        patch = git(workspace, 'diff', '--no-ext-diff', '--no-textconv', '--', *self.value['allowed_files'])
        if len(patch.encode()) > 65536:
            raise ContractError('REPO_REVIEW_DIFF_LIMIT')
        return {'adapter_hash': self.hash, 'source_base': self.value['base_sha'], 'diff': patch,
                'protected_config': self.value['protected_hashes'], 'visual': 'NOT_APPLICABLE_PACKAGING_ONLY'}
