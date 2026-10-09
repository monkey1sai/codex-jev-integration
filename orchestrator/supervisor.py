"""Bounded supervisor for offline tests or explicit native-trust Development."""
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import json
import threading
import time
import uuid
from .contracts import ContractError
from .pipeline import mock_attempt


class Supervisor:
    def __init__(self, queue, root, repo, *, max_active=1, validators=None,
                 native_runner=None, capabilities=None):
        if queue.evidence_mode not in {'OFFLINE_TEST', 'DEVELOPMENT'}:
            raise ContractError('NATIVE_SUPERVISOR_BLOCKED')
        if queue.evidence_mode == 'DEVELOPMENT' and native_runner is None:
            raise ContractError('NATIVE_RUNNER_REQUIRED')
        if queue.evidence_mode != 'DEVELOPMENT' and native_runner is not None:
            raise ContractError('RUNNER_REALM_MISMATCH')
        if type(max_active) is not int or not 1 <= max_active <= min(2, queue.policy['settings']['scheduler']['max_active']):
            raise ContractError('ACTIVE_CAP')
        self.queue, self.root, self.repo = queue, root, repo
        self.max_active, self.validators = max_active, validators
        self.native_runner = native_runner
        self.capabilities = capabilities or {'synthetic'}
        self.stop = threading.Event()
        self.owner = uuid.uuid4().hex
        with queue.transaction() as db:
            db.execute('CREATE TABLE IF NOT EXISTS supervisor_lock(id INTEGER PRIMARY KEY CHECK(id=1), owner TEXT, expires REAL)')
            row = db.execute('SELECT * FROM supervisor_lock').fetchone()
            if row and row['expires'] > time.time():
                raise ContractError('SUPERVISOR_ALREADY_ACTIVE')
            db.execute('INSERT OR REPLACE INTO supervisor_lock VALUES(1,?,?)', (self.owner, time.time() + 60))
        # Restarts fence expired attempts, but never manufacture cleanup proof.
        queue.expired()

    def cancel(self):
        self.stop.set()

    def _renew(self):
        with self.queue.transaction() as db:
            row = db.execute('SELECT * FROM supervisor_lock').fetchone()
            if not row or row['owner'] != self.owner or row['expires'] <= time.time():
                raise ContractError('STALE_SUPERVISOR')
            db.execute('UPDATE supervisor_lock SET expires=? WHERE owner=?', (time.time() + 60, self.owner))

    def run(self, *, max_seconds=30, behavior='valid'):
        if type(max_seconds) not in (int, float) or not 0 < max_seconds <= 600:
            raise ContractError('SUPERVISOR_RUNTIME')
        started = time.monotonic()
        deadline = started + max_seconds
        pending, outcomes = {}, []
        peak_submissions = 0
        pool = ThreadPoolExecutor(max_workers=self.max_active)
        renew_done = threading.Event()
        def maintain_owner():
            while not renew_done.wait(2):
                try:
                    self._renew()
                    if time.monotonic() >= deadline:
                        self.stop.set()
                except Exception:
                    self.stop.set()
                    return
        renewer = threading.Thread(target=maintain_owner, daemon=True)
        if self.native_runner:
            self.native_runner.supervisor_owner = self.owner
            renewer.start()
        try:
            try:
                while not self.stop.is_set() and time.monotonic() < deadline:
                    self._renew()
                    if self.queue.integration_stopped():
                        self.stop.set()
                        break
                    while len(pending) < self.max_active and not self.stop.is_set():
                        if self.native_runner and any(r['state'] in {'HELD', 'FAILED', 'CANCELLED'}
                                                      for r in self.queue.snapshot()['tasks']):
                            if not self.queue.failures_are_isolated():
                                self.stop.set()
                                break
                            if not self.queue.independent_failures:
                                break
                        claim = self.queue.claim(lease_seconds=60, capabilities=self.capabilities,
                                                 halt_on_failure=self.native_runner is not None)
                        if claim is None:
                            break
                        if self.native_runner:
                            future = pool.submit(self.native_runner.attempt, claim, self.stop)
                        else:
                            future = pool.submit(mock_attempt, self.queue, self.root, self.repo,
                                                 claim=claim, stop=self.stop, validators=self.validators,
                                                 timeout=min(30, claim['task']['budgets']['runtime_seconds']), behavior=behavior)
                        pending[future] = claim
                        peak_submissions = max(peak_submissions, len(pending))
                    if not pending:
                        if self.native_runner:
                            # Review is serial and runs only after all workers stop:
                            # reviewer processes count toward the same capacity.
                            rows = self.queue.snapshot()['tasks']
                            if (any(r['state'] in {'HELD', 'FAILED', 'CANCELLED'} for r in rows)
                                    and not (self.queue.independent_failures and self.queue.failures_are_isolated())):
                                self.stop.set()
                                break
                            for row in rows:
                                if self.stop.is_set():
                                    break
                                if row['state'] == 'REVIEW':
                                    if self.queue.integration_stopped():
                                        self.stop.set()
                                        break
                                    try:
                                        reviewed = self.native_runner.review(row['id'], self.stop)
                                    except Exception as error:
                                        reviewed = {'status': 'BLOCKED', 'task_id': row['id'], 'reason': type(error).__name__}
                                    outcomes.append(reviewed)
                                    if not isinstance(reviewed, dict) or reviewed.get('status') != 'PASSED':
                                        if (self.queue.independent_failures and isinstance(reviewed, dict)
                                                and reviewed.get('failure_scope') == 'TASK'
                                                and self.queue.failures_are_isolated()):
                                            continue
                                        self.stop.set()
                                        break
                            if self.stop.is_set():
                                break
                            rows = self.queue.snapshot()['tasks']
                            if any(r['state'] in {'REVIEW', 'HELD', 'CANCELLED'} for r in rows):
                                break
                            if any(r['state'] == 'READY' for r in rows):
                                continue
                            if self.queue.independent_failures:
                                # Remaining PENDING branches have failed ancestors, or no
                                # dispatch budget. No external review can make them ready.
                                break
                        # External reviews can make child tasks READY while polling.
                        rows = self.queue.snapshot()['tasks']
                        if all(r['state'] in {'PASSED', 'FAILED', 'CANCELLED'} for r in rows):
                            break
                        self.stop.wait(.05)
                        continue
                    completed, _ = wait(pending, timeout=.05, return_when=FIRST_COMPLETED)
                    for future in completed:
                        claim = pending.pop(future)
                        try:
                            outcome = future.result()
                            outcomes.append(outcome)
                            if self.native_runner and (not isinstance(outcome, dict) or outcome.get('status') != 'REVIEW'):
                                if not (isinstance(outcome, dict) and outcome.get('failure_scope') == 'TASK'
                                        and self.queue.failures_are_isolated()):
                                    self.stop.set()
                        except Exception as error:
                            self.queue.fence(claim, 'supervisor_exception')
                            outcomes.append({'status': 'HELD', 'reason': type(error).__name__})
                            if self.native_runner:
                                self.stop.set()
            finally:
                # Cancel before executor shutdown waits, including lost-owner/claim exceptions.
                self.stop.set()
                for future, claim in pending.items():
                    self.queue.fence(claim, 'supervisor_shutdown')
                pool.shutdown(wait=True, cancel_futures=True)
                for future in pending:
                    if not future.cancelled():
                        try:
                            outcomes.append(future.result())
                        except Exception:
                            outcomes.append({'status': 'HELD', 'reason': 'supervisor_shutdown'})
        finally:
            self.stop.set()
            renew_done.set()
            if self.native_runner:
                renewer.join(timeout=3)
            with self.queue.transaction() as db:
                db.execute('DELETE FROM supervisor_lock WHERE owner=?', (self.owner,))
        snapshot = self.queue.snapshot()
        elapsed = time.monotonic() - started
        passed = sum(row['state'] == 'PASSED' for row in snapshot['tasks'])
        metrics = {'elapsed_seconds': elapsed, 'peak_inflight_submissions': peak_submissions,
                   'passed_tasks_at_exit': passed, 'queue_tasks': len(snapshot['tasks']),
                   'scope': 'CONTROLLER_RUN_ONLY_NOT_MODEL_PROCESS_OVERLAP'}
        with self.queue.transaction() as db:
            self.queue._event(db, None, 'supervisor_metrics', owner=self.owner, **metrics)
        return {'outcomes': outcomes, 'queue': snapshot, 'mode': self.queue.evidence_mode, 'metrics': metrics,
                'native_dispatches': self.native_runner.dispatches if self.native_runner else 0,
                'merge_executed': False}
