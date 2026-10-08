"""Incremental controller over CoreQueue's storage and v2 policy/contracts.

No live-admission bypass, trusted-review forgery, or merge executor.
"""
import json
import time
import uuid
from .core_queue import CoreQueue
from .contracts import ContractError, canonical, fingerprint

STATES = {'PENDING', 'READY', 'CLAIMED', 'RUNNING', 'VALIDATING', 'REVIEW',
          'PASSED', 'FAILED', 'HELD', 'CANCELLED'}
ACTIVE = {'CLAIMED', 'RUNNING', 'VALIDATING', 'HELD'}


class Phase2Queue(CoreQueue):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        with self.transaction() as db:
            db.execute('CREATE TABLE IF NOT EXISTS phase2_binding(id INTEGER PRIMARY KEY CHECK(id=1), version INTEGER)')
            if not db.execute('SELECT 1 FROM phase2_binding').fetchone():
                if db.execute('SELECT 1 FROM tasks').fetchone():
                    raise ContractError('LEGACY_QUEUE_MIGRATION_REQUIRED')
                db.execute('INSERT INTO phase2_binding VALUES(1,1)')
            db.execute('CREATE TABLE IF NOT EXISTS merge_queue(task TEXT PRIMARY KEY, receipt_hash TEXT, status TEXT, reason TEXT)')

    @staticmethod
    def _event(db, key, name, **data):
        db.execute('INSERT INTO events(task,event,at) VALUES(?,?,?)',
                   (key, canonical({'event': name, **data}), time.time()))

    def enqueue(self, tasks):
        self._fresh()
        if type(tasks) is list:
            tasks = [normalize_task(t) for t in tasks]
        # CoreQueue's validator validates the complete DAG, policy and exact scope.
        with self.transaction() as db:
            existing = {r['id']: json.loads(r['contract']) for r in db.execute('SELECT * FROM tasks')}
            if type(tasks) is not list or not tasks:
                raise ContractError('CONTRACT_SCHEMA')
            ids = [t.get('task_id') for t in tasks if type(t) is dict]
            if len(ids) != len(tasks) or len(set(ids)) != len(ids):
                raise ContractError('DUPLICATE_TASK_ID')
            for task in tasks:
                key = task['task_id']
                if key in existing and fingerprint(existing[key]) != fingerprint(task):
                    raise ContractError('IMMUTABLE_TASK_DRIFT')
                existing[key] = task
            self.validator(list(existing.values()))
            for task in tasks:
                inserted = db.execute('INSERT OR IGNORE INTO tasks(id,contract,hash,state) VALUES(?,?,?,?)',
                                      (task['task_id'], canonical(task), fingerprint(task), 'PENDING')).rowcount
                if inserted:
                    self._event(db, task['task_id'], 'PENDING', contract_hash=fingerprint(task))
            self._ready(db)

    def _ready(self, db):
        states = dict(db.execute('SELECT id,state FROM tasks'))
        for row in db.execute("SELECT * FROM tasks WHERE state='PENDING'").fetchall():
            task = json.loads(row['contract'])
            if all(states.get(dep) == 'PASSED' for dep in task['dependencies']):
                db.execute("UPDATE tasks SET state='READY' WHERE id=?", (row['id'],))
                self._event(db, row['id'], 'READY')

    def claim(self, lease_seconds=180, now=None, *, capabilities=None):
        self._fresh()
        if type(lease_seconds) not in (int, float) or not 0 < lease_seconds <= 600:
            raise ContractError('LEASE_BOUND')
        now = time.time() if now is None else now
        with self.transaction() as db:
            self._ready(db)
            cap = db.execute('SELECT active_cap FROM controller_binding').fetchone()[0]
            active = db.execute("SELECT count(*) FROM tasks WHERE state IN ('CLAIMED','RUNNING','VALIDATING','HELD')").fetchone()[0]
            budget = db.execute('SELECT * FROM budget').fetchone()
            if active >= cap or budget['used'] >= budget['max_dispatches']:
                return None
            for row in db.execute("SELECT * FROM tasks WHERE state='READY' ORDER BY rowid").fetchall():
                task = json.loads(row['contract'])
                if capabilities is not None and task['capability'] not in capabilities:
                    continue
                if row['attempts'] >= task['budgets']['attempts'] or row['provider_unknown']:
                    continue
                resources = sorted(set(task['resource_locks'] + ['file:' + p.casefold() for p in task['allowed_files']]))
                if any(db.execute('SELECT 1 FROM locks WHERE resource=?', (r,)).fetchone() for r in resources):
                    continue
                token, epoch = uuid.uuid4().hex, row['epoch'] + 1
                db.execute("UPDATE tasks SET state='CLAIMED',epoch=?,attempts=attempts+1,attempt_id=?,expires=? WHERE id=?",
                           (epoch, token, now + lease_seconds, row['id']))
                db.executemany('INSERT INTO locks VALUES(?,?)', [(r, row['id']) for r in resources])
                db.execute('UPDATE budget SET used=used+1 WHERE id=1')
                self._event(db, row['id'], 'CLAIMED', epoch=epoch, attempt_id=token)
                return {'task': task, 'task_hash': row['hash'], 'attempt_id': token, 'epoch': epoch}
        return None

    def _transition(self, claim, before, after, now=None):
        self._fresh()
        now = time.time() if now is None else now
        with self.transaction() as db:
            if not self._current(db, claim, before, now):
                return False
            key = claim['task']['task_id']
            db.execute('UPDATE tasks SET state=? WHERE id=?', (after, key))
            self._event(db, key, after, epoch=claim['epoch'], attempt_id=claim['attempt_id'])
            return True

    def start(self, claim, now=None):
        return self._transition(claim, {'CLAIMED'}, 'RUNNING', now)

    def validating(self, claim, now=None):
        return self._transition(claim, {'RUNNING'}, 'VALIDATING', now)

    def heartbeat(self, claim, lease_seconds=180, now=None):
        self._fresh()
        if type(lease_seconds) not in (int, float) or not 0 < lease_seconds <= 600:
            raise ContractError('LEASE_BOUND')
        now = time.time() if now is None else now
        with self.transaction() as db:
            if not self._current(db, claim, {'CLAIMED', 'RUNNING', 'VALIDATING'}, now):
                return False
            key = claim['task']['task_id']
            db.execute('UPDATE tasks SET expires=? WHERE id=?', (now + lease_seconds, key))
            self._event(db, key, 'heartbeat', epoch=claim['epoch'], expires=now + lease_seconds)
            return True

    def finish(self, claim, receipt, passed, now=None):
        self._fresh()
        now = time.time() if now is None else now
        if type(receipt) is not dict or receipt.get('process_tree_empty') is not True:
            raise ContractError('CLEANUP_EVIDENCE_REQUIRED')
        if type(passed) is not bool:
            raise ContractError('VALIDATION_RESULT')
        with self.transaction() as db:
            if not self._current(db, claim, {'VALIDATING'}, now):
                return False
            key, state = claim['task']['task_id'], 'REVIEW' if passed else 'FAILED'
            db.execute('UPDATE tasks SET state=?,receipt=?,expires=NULL WHERE id=?', (state, canonical(receipt), key))
            db.execute('DELETE FROM locks WHERE task=?', (key,))
            self._event(db, key, state, receipt_hash=fingerprint(receipt), epoch=claim['epoch'])
            if passed:
                db.execute('INSERT INTO merge_queue VALUES(?,?,?,?)',
                           (key, fingerprint(receipt), 'HELD', 'TRUSTED_REVIEW_IMPORT_NOT_IMPLEMENTED'))
            return True

    def fence(self, claim, reason='cancelled'):
        with self.transaction() as db:
            key = claim['task']['task_id']
            row = db.execute('SELECT * FROM tasks WHERE id=?', (key,)).fetchone()
            if not self._identity(row, claim) or row['state'] not in {'CLAIMED', 'RUNNING', 'VALIDATING'}:
                return False
            db.execute("UPDATE tasks SET state='HELD',epoch=epoch+1,reason=? WHERE id=?", (reason, key))
            self._event(db, key, 'fenced', reason=reason, epoch=claim['epoch'] + 1)
            return True

    def expired(self, now=None):
        now = time.time() if now is None else now
        with self.transaction() as db:
            claims = [{'task': json.loads(r['contract']), 'task_hash': r['hash'], 'attempt_id': r['attempt_id'], 'epoch': r['epoch']}
                      for r in db.execute("SELECT * FROM tasks WHERE state IN ('CLAIMED','RUNNING','VALIDATING') AND expires<=?", (now,))]
            for claim in claims:
                key = claim['task']['task_id']
                db.execute("UPDATE tasks SET state='HELD',epoch=epoch+1,reason='lease_expired' WHERE id=?", (key,))
                self._event(db, key, 'lease_expired', epoch=claim['epoch'] + 1)
            return claims

    def cleanup(self, claim, *, tree_empty, retry=False, provider_completion_unknown=False):
        self._fresh()
        with self.transaction() as db:
            key = claim['task']['task_id']
            row = db.execute('SELECT * FROM tasks WHERE id=?', (key,)).fetchone()
            if not self._identity(row, claim, 1) or row['state'] != 'HELD' or tree_empty is not True:
                return False
            if provider_completion_unknown:
                db.execute('UPDATE tasks SET provider_unknown=1 WHERE id=?', (key,))
            if retry and (provider_completion_unknown or row['provider_unknown'] or row['attempts'] >= claim['task']['budgets']['attempts']):
                return False
            state = 'PENDING' if retry else 'CANCELLED'
            db.execute('UPDATE tasks SET state=?,expires=NULL WHERE id=?', (state, key))
            db.execute('DELETE FROM locks WHERE task=?', (key,))
            self._event(db, key, 'cleanup', tree_empty=True, retry=retry, state=state)
            self._ready(db)
            return True

    def dispatch_intent(self, claim):
        self._fresh()
        with self.transaction() as db:
            row = db.execute('SELECT * FROM tasks WHERE id=?', (claim['task']['task_id'],)).fetchone()
            if not self._current(db, claim, {'RUNNING'}, time.time()) or row['provider_unknown']:
                return False
            key = claim['task']['task_id']
            db.execute('UPDATE tasks SET provider_unknown=1 WHERE id=?', (key,))
            self._event(db, key, 'dispatch_intent', epoch=claim['epoch'], provider_completion='UNKNOWN')
            return True

    def merge_snapshot(self):
        with self.transaction() as db:
            return [dict(r) for r in db.execute('SELECT * FROM merge_queue ORDER BY rowid')]

    def merge(self, *args, **kwargs):
        raise ContractError('MERGE_EXECUTION_DISABLED')


def normalize_task(task):
    """Named Phase 1–2 fields map losslessly onto the reused strict v2 contract."""
    if type(task) is not dict or task.get('schema_version') != 3:
        return task
    result = dict(task)
    try:
        acceptance = result.pop('acceptance')
        if type(acceptance) is not dict or set(acceptance) != {'criteria', 'validators'}:
            raise ContractError('ACCEPTANCE_SCHEMA')
        result['acceptance_criteria'] = acceptance['criteria']
        result['tests'] = acceptance['validators']
        result['execution'] = result.pop('model_policy')
        result['budgets'] = result.pop('retry_budget')
        result['schema_version'] = 2
    except KeyError:
        raise ContractError('CONTRACT_SCHEMA') from None
    return result
