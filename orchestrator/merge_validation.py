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
                  eligibility='HELD_HUMAN_AUTHORIZATION' if queue.evidence_mode == 'production' else 'OFFLINE_TEST_ONLY')
    frozen_bytes(queue.path.parent / 'merge-evidence' / (fingerprint(result) + '.json'), canonical(result).encode())
    return result
