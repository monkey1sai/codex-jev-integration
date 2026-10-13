"""Isolated Git conflict oracle; writes isolated objects, never merge refs."""
import json
import tempfile
import os
import shutil
from .processes import bounded_run
from pathlib import Path
from .contracts import ContractError, canonical, fingerprint
from .evidence import guarded, frozen_bytes, digest


class IsolatedGit:
    def __init__(self, repo):
        self.source = guarded(repo).resolve(strict=True)
        self.folder = guarded(Path(tempfile.mkdtemp(prefix='merge-validation-', dir=self.source.parent)))
        self.repo = self.folder / 'objects.git'
        self.executable = shutil.which('git')
        if not self.executable:
            raise ContractError('GIT_REQUIRED')
        self.executable = str(guarded(self.executable))
        from .evidence import clean_env
        self.env = clean_env(self.folder)
        self.env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
                        GIT_ATTR_NOSYSTEM='1', GIT_NO_LAZY_FETCH='1', GIT_NO_REPLACE_OBJECTS='1',
                        GIT_TERMINAL_PROMPT='0', GIT_CONFIG_COUNT='0')
        self.command(['clone', '--bare', '--local', '--no-hardlinks', '--', str(self.source), str(self.repo)], isolated=False)

    def command(self, args, *, isolated=True, codes=(0,)):
        argv = [self.executable, '-c', 'core.hooksPath=', '-c', 'core.fsmonitor=false', '-c', 'protocol.allow=never']
        if isolated:
            argv += ['-C', str(self.repo)]
        else:
            # Only this fixed, absolute local source clone may use file transport.
            argv += ['-c', 'protocol.file.allow=always']
        result = bounded_run(argv + args, cwd=self.folder, timeout=30, env=self.env)
        if result['reason'] or not result['tree_empty'] or result['returncode'] not in codes:
            raise ContractError('ISOLATED_GIT_FAILED:' + (result['reason'] or 'EXIT_CODE'))
        return result

    def read(self, *args):
        return self.command(list(args))['stdout']

    def conflicts(self, base, ours, theirs):
        import re
        if any(not isinstance(sha, str) or not re.fullmatch('[a-f0-9]{40}', sha) for sha in (base, ours, theirs)):
            raise ContractError('MERGE_SHA')
        result = self.command(['merge-tree', '--write-tree', '--merge-base=' + base, ours, theirs], codes=(0, 1))
        return {'status': 'CONFLICT' if result['returncode'] else 'CLEAN', 'base': base, 'ours': ours,
                'theirs': theirs, 'output_sha256': digest(result['stdout']), 'merge_executed': False,
                'head_modified': False, 'human_authorization_required': True, 'isolated_repo': str(self.repo)}


def conflicts(repo, base, ours, theirs):
    return IsolatedGit(repo).conflicts(base, ours, theirs)


def validate_queue_merge(queue, task_id, integration_repo, integration_head, candidate_head):
    queue._fresh()
    with queue.transaction() as db:
        row = db.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
        review = db.execute('SELECT * FROM reviews WHERE task=?', (task_id,)).fetchone()
        if not row or row['state'] != 'PASSED' or not review:
            raise ContractError('MERGE_REVIEW_REQUIRED')
        manifest, sha = queue.artifacts.verified(db, row)
        queue.artifacts.bind_receipt(manifest, sha, json.loads(row['receipt']))
        envelope = json.loads(review['envelope'])
        target = envelope['payload']['target']
        if (fingerprint(envelope) != review['hash'] or target['artifact_hash'] != sha
                or target['queue_id'] != queue.queue_id or target['attempt_id'] != row['attempt_id']
                or target['epoch'] != row['epoch'] or target['mode'] != queue.evidence_mode):
            raise ContractError('MERGE_REVIEW_DRIFT')
        task = json.loads(row['contract'])
    # Binding Git trees to the reviewed bytes is mandatory, even for dry-run.
    isolated = IsolatedGit(integration_repo)
    def git(*args):
        return isolated.read(*args).decode().strip()
    if git('rev-parse', 'HEAD') != integration_head:
        raise ContractError('STALE_INTEGRATION_HEAD')
    import re
    if not re.fullmatch('[a-f0-9]{40}', candidate_head):
        raise ContractError('MERGE_SHA')
    changed = git('diff', '--name-only', '--no-ext-diff', task['base_sha'], candidate_head).splitlines()
    if set(changed) != set(manifest['artifacts']):
        raise ContractError('MERGE_CANDIDATE_SCOPE')
    for name, expected in manifest['artifacts'].items():
        entry = git('ls-tree', candidate_head, '--', name).split()
        if len(entry) < 3 or entry[0] != '100644' or entry[1] != 'blob':
            raise ContractError('MERGE_CANDIDATE_FILE_MODE')
        data = isolated.read('cat-file', 'blob', entry[2])
        if digest(data) != expected:
            raise ContractError('MERGE_CANDIDATE_ARTIFACT_DRIFT')
    result = isolated.conflicts(task['base_sha'], integration_head, candidate_head)
    result.update(task_id=task_id, review_hash=review['hash'], artifact_hash=sha, mode=queue.evidence_mode,
                  eligibility='OFFLINE_TEST_ONLY' if queue.evidence_mode == 'OFFLINE_TEST' else 'HELD_HUMAN_AUTHORIZATION')
    frozen_bytes(queue.path.parent / 'merge-evidence' / (fingerprint(result) + '.json'), canonical(result).encode())
    return result


def reviewed_batch(queue, task_ids):
    """Resolve accepted, immutable bytes; never trust a caller's review claim."""
    queue._fresh()
    if (type(task_ids) is not list or not task_ids or len(task_ids) > 1000
            or any(not isinstance(key, str) for key in task_ids) or len(set(task_ids)) != len(task_ids)):
        raise ContractError('INTEGRATION_TASKS')
    bindings, files, base = [], {}, None
    with queue.transaction() as db:
        for key in task_ids:
            row = db.execute('SELECT * FROM tasks WHERE id=?', (key,)).fetchone()
            review = db.execute('SELECT * FROM reviews WHERE task=?', (key,)).fetchone()
            if not row or row['state'] != 'PASSED' or not review:
                raise ContractError('INTEGRATION_REVIEW_REQUIRED')
            manifest, sha = queue.artifacts.verified(db, row)
            receipt = json.loads(row['receipt'])
            queue.artifacts.bind_receipt(manifest, sha, receipt)
            envelope = json.loads(review['envelope'])
            target = envelope['payload']['target']
            expected = {'queue_id': queue.queue_id, 'task_id': key, 'task_hash': row['hash'],
                        'attempt_id': row['attempt_id'], 'epoch': row['epoch'],
                        'policy_hash': queue.policy['policy_hash'], 'receipt_hash': fingerprint(receipt),
                        'artifact_hash': sha, 'mode': queue.evidence_mode}
            if (fingerprint(envelope) != review['hash'] or envelope['payload']['decision'] != 'PASS'
                    or any(target.get(k) != value for k, value in expected.items())):
                raise ContractError('INTEGRATION_REVIEW_DRIFT')
            if base is not None and base != manifest['base_sha']:
                raise ContractError('INTEGRATION_BASE_CONFLICT')
            base = manifest['base_sha']
            bindings.append({**expected, 'review_hash': review['hash']})
            for name, expected_hash in manifest['artifacts'].items():
                # Even identical bytes with two owners require an explicit
                # composition contract; never silently choose last writer.
                if name in files or any(name.casefold() == p.casefold()
                        or name.casefold().startswith(p.casefold() + '/')
                        or p.casefold().startswith(name.casefold() + '/') for p in files):
                    raise ContractError('INTEGRATION_OWNERSHIP_CONFLICT')
                source = guarded(queue.artifacts.root / row['attempt_id'] / name)
                if digest(source.read_bytes()) != expected_hash:
                    raise ContractError('INTEGRATION_ARTIFACT_DRIFT')
                files[name] = {'sha256': expected_hash, 'source': str(source)}
    return {'queue_id': queue.queue_id, 'policy_hash': queue.policy['policy_hash'],
            'mode': queue.evidence_mode, 'base_sha': base, 'bindings': bindings, 'files': files}


def prepare_integration(queue, root, repo, task_ids, *, repo_adapter=None):
    """Apply reviewed bytes to a fresh detached worktree, never main or refs."""
    import uuid
    from .workspaces import allocate, git
    from .contracts import relative_file
    root, repo = guarded(root), guarded(repo)
    batch = reviewed_batch(queue, task_ids)
    if queue.repo.resolve() != repo.resolve() or git(repo, 'rev-parse', 'HEAD') != batch['base_sha']:
        raise ContractError('INTEGRATION_SOURCE_BASE')
    workspace, _ = allocate(root, repo, {'attempt_id': uuid.uuid4().hex, 'task': {'base_sha': batch['base_sha']}})
    (workspace / '.tmp').mkdir()
    if repo_adapter:
        repo_adapter.bind(queue, root, repo)
        repo_adapter.prepare(workspace)
    # Streaming limits from the existing Repo seam; no execution occurs here.
    from .repo_adapter import repository_scan, file_modes
    before = repository_scan(workspace, ignore_scratch=True)
    for name, artifact in batch['files'].items():
        path = guarded(workspace / relative_file(name))
        data = guarded(artifact['source']).read_bytes()
        if digest(data) != artifact['sha256']:
            raise ContractError('INTEGRATION_ARTIFACT_DRIFT')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)  # Fresh base only, never a live/dirty workspace.
    after = repository_scan(workspace, ignore_scratch=True)
    changed = {p for p in set(before) | set(after) if before.get(p) != after.get(p)}
    if (not changed <= set(batch['files'])
            or any(after.get(name) != item['sha256'] for name, item in batch['files'].items())):
        raise ContractError('INTEGRATION_SCOPE')
    plan = {'batch': batch, 'task_ids': task_ids, 'workspace': str(workspace),
            'baseline_hash': fingerprint(before), 'candidate_tree_hash': fingerprint(after),
            'candidate_modes_hash': fingerprint(file_modes(workspace)),
            'status': 'PREPARED_NOT_VALIDATED', 'merge_executed': False}
    frozen_bytes(queue.path.parent / 'integration-evidence' / workspace.name / 'prepared.json', canonical(plan).encode())
    return plan


def verify_integration(queue, plan):
    from .repo_adapter import repository_scan, file_modes
    from .workspaces import git
    if reviewed_batch(queue, plan['task_ids']) != plan['batch']:
        raise ContractError('INTEGRATION_BINDING_DRIFT')
    workspace = guarded(plan['workspace'])
    saved = guarded(queue.path.parent / 'integration-evidence' / workspace.name / 'prepared.json')
    if saved.read_bytes() != canonical(plan).encode():
        raise ContractError('INTEGRATION_PREPARED_DRIFT')
    if (git(workspace, 'rev-parse', 'HEAD') != plan['batch']['base_sha']
            or git(queue.repo, 'rev-parse', 'HEAD') != plan['batch']['base_sha']
            or fingerprint(repository_scan(workspace, ignore_scratch=True)) != plan['candidate_tree_hash']
            or fingerprint(file_modes(workspace)) != plan['candidate_modes_hash']):
        raise ContractError('INTEGRATION_TREE_DRIFT')
    return True
