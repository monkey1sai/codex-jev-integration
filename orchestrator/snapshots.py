"""Only reviewed immutable dependency artifacts enter a child attempt."""
import json
from pathlib import Path
from .contracts import ContractError, fingerprint, canonical
from .evidence import guarded, frozen_bytes, digest


def materialize(queue, claim, workspace):
    queue._fresh()
    queue.artifacts.authenticate(claim, {'CLAIMED', 'RUNNING'})
    task, files, sources = claim['task'], {}, []
    with queue.transaction() as db:
        if not queue._current(db, claim, {'CLAIMED', 'RUNNING'}, __import__('time').time()):
            raise ContractError('STALE_SNAPSHOT')
        for dep in task['dependencies']:
            row = db.execute('SELECT * FROM tasks WHERE id=?', (dep,)).fetchone()
            review = db.execute('SELECT * FROM reviews WHERE task=?', (dep,)).fetchone()
            if not row or row['state'] != 'PASSED' or not review:
                raise ContractError('DEPENDENCY_NOT_REVIEWED')
            envelope = json.loads(review['envelope'])
            if fingerprint(envelope) != review['hash'] or envelope['payload']['target']['queue_id'] != queue.queue_id:
                raise ContractError('DEPENDENCY_REVIEW_DRIFT')
            manifest, sha = queue.artifacts.verified(db, row)
            queue.artifacts.bind_receipt(manifest, sha, json.loads(row['receipt']))
            target = envelope['payload']['target']
            if (manifest['mode'] != queue.evidence_mode or sha != target['artifact_hash']
                    or target['attempt_id'] != row['attempt_id'] or target['epoch'] != row['epoch']):
                raise ContractError('DEPENDENCY_MANIFEST_STALE')
            sources.append({'task_id': dep, 'manifest_hash': sha, 'review_hash': review['hash']})
            for name, artifact_hash in manifest['artifacts'].items():
                if name in files and files[name][0] != artifact_hash:
                    raise ContractError('DEPENDENCY_ARTIFACT_CONFLICT')
                files[name] = (artifact_hash, queue.artifacts.root / row['attempt_id'] / name)
    wanted = {item['path']: item['sha256'] for item in task['inputs']}
    paths = []
    for name, expected in wanted.items():
        if name not in files:
            path = guarded(Path(workspace) / name)
            if not path.is_file() or digest(path.read_bytes()) != expected:
                raise ContractError('INPUT_SNAPSHOT_MISSING')
            continue
        actual, source = files[name]
        data = guarded(source).read_bytes()
        if actual != expected or digest(data) != expected:
            raise ContractError('DEPENDENCY_INPUT_HASH_MISMATCH')
        destination = guarded(Path(workspace) / name)
        if destination.exists():
            if digest(destination.read_bytes()) != expected:
                raise ContractError('DEPENDENCY_OVERWRITE_DENIED')
        else:
            frozen_bytes(destination, data)
        paths.append(name)
    snapshot = {'queue_id': queue.queue_id, 'mode': queue.evidence_mode, 'task_hash': claim['task_hash'],
                'attempt_id': claim['attempt_id'], 'epoch': claim['epoch'], 'dependencies': sources, 'inputs': wanted}
    queue.artifacts.authenticate(claim, {'CLAIMED', 'RUNNING'})
    frozen_bytes(queue.path.parent / 'snapshots' / (claim['attempt_id'] + '.json'), canonical(snapshot).encode())
    return {'snapshot_hash': fingerprint(snapshot), 'materialized': paths, 'snapshot': snapshot}
