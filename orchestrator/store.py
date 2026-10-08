"""Controller-only SQLite ledger: atomic admission, ownership and fencing."""
from __future__ import annotations

from contextlib import contextmanager
import json
import sqlite3
import time
import uuid
from pathlib import Path

from .contracts import canonical, fingerprint, validate_batch, ContractError


class Store:
    def __init__(self, path, max_dispatches=38, *, validator=validate_batch, max_active=None, binding=None):
        if type(max_dispatches) is not int or not 1 <= max_dispatches <= 1000:
            raise ContractError("BATCH_BUDGET")
        self.path = Path(path)
        self.validator = validator
        if max_active is not None and (type(max_active) is not int or not 1 <= max_active <= 2):
            raise ContractError("ACTIVE_CAP")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as db:
            schema = """
                CREATE TABLE IF NOT EXISTS tasks(
                    id TEXT PRIMARY KEY, contract TEXT NOT NULL, hash TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'queued', epoch INTEGER NOT NULL DEFAULT 0,
                    attempts INTEGER NOT NULL DEFAULT 0, attempt_id TEXT, expires REAL,
                    receipt TEXT, reason TEXT);
                CREATE TABLE IF NOT EXISTS locks(resource TEXT PRIMARY KEY, task TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS budget(id INTEGER PRIMARY KEY CHECK(id=1),
                    max_dispatches INTEGER NOT NULL, used INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY, task TEXT,
                    event TEXT NOT NULL, at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS controller_binding(id INTEGER PRIMARY KEY CHECK(id=1),
                    active_cap INTEGER, binding TEXT);
            """
            for statement in schema.split(";"):
                if statement.strip():
                    db.execute(statement)
            columns = {r[1] for r in db.execute('PRAGMA table_info(tasks)')}
            if 'provider_unknown' not in columns:
                db.execute('ALTER TABLE tasks ADD COLUMN provider_unknown INTEGER NOT NULL DEFAULT 0')
            db.execute("INSERT OR IGNORE INTO budget VALUES(1,?,0)", (max_dispatches,))
            if db.execute("SELECT max_dispatches FROM budget").fetchone()[0] != max_dispatches:
                raise ContractError("BATCH_BUDGET_IMMUTABLE")
            expected = canonical(binding) if binding is not None else None
            old = db.execute("SELECT * FROM controller_binding").fetchone()
            if old is None and binding is not None and db.execute("SELECT count(*) FROM tasks").fetchone()[0]:
                raise ContractError("UNBOUND_EXISTING_QUEUE")
            db.execute("INSERT OR IGNORE INTO controller_binding VALUES(1,?,?)", (max_active, expected))
            row = db.execute("SELECT * FROM controller_binding").fetchone()
            if row["active_cap"] != max_active or row["binding"] != expected:
                raise ContractError("QUEUE_POLICY_DRIFT")

    @contextmanager
    def transaction(self, *, timeout=10):
        # Trusted stop paths may tighten waiting; ordinary queue defaults stay unchanged.
        if type(timeout) not in (int, float) or not .01 <= timeout <= 10:
            raise ContractError('TRANSACTION_TIMEOUT_BOUND')
        db = sqlite3.connect(self.path, timeout=timeout, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA busy_timeout=" + str(int(timeout * 1000)))
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def enqueue(self, tasks):
        if type(tasks) is not list or not tasks:
            raise ContractError("QUEUE_CAPACITY")
        if any(type(t) is not dict or "task_id" not in t for t in tasks):
            raise ContractError("CONTRACT_SCHEMA")
        ids = [t["task_id"] for t in tasks]
        if any(not isinstance(t, str) for t in ids) or len(set(ids)) != len(ids):
            raise ContractError("DUPLICATE_TASK_ID")
        with self.transaction() as db:
            existing = {r["id"]: json.loads(r["contract"]) for r in db.execute("SELECT * FROM tasks")}
            for task in tasks:
                if task["task_id"] in existing and fingerprint(existing[task["task_id"]]) != fingerprint(task):
                    raise ContractError("IMMUTABLE_TASK_DRIFT")
                existing[task["task_id"]] = task
            self.validator(list(existing.values()))
            for task in tasks:
                db.execute("INSERT OR IGNORE INTO tasks(id,contract,hash) VALUES(?,?,?)",
                           (task["task_id"], canonical(task), fingerprint(task)))

    def claim(self, lease_seconds=180, now=None):
        now = time.time() if now is None else now
        with self.transaction() as db:
            budget = db.execute("SELECT * FROM budget").fetchone()
            if budget["used"] >= budget["max_dispatches"]:
                return None
            cap = db.execute("SELECT active_cap FROM controller_binding").fetchone()[0]
            active = db.execute("SELECT count(*) FROM tasks WHERE state IN ('running','validating','held_cleanup')").fetchone()[0]
            if cap is not None and active >= cap:
                return None
            states = dict(db.execute("SELECT id,state FROM tasks"))
            for row in db.execute("SELECT * FROM tasks WHERE state='queued' ORDER BY rowid").fetchall():
                task = json.loads(row["contract"])
                if row["attempts"] >= task["budgets"]["attempts"]:
                    continue
                if any(states.get(dep) != "reviewed" for dep in task["dependencies"]):
                    continue
                resources = sorted(set(task["resource_locks"] + ["file:" + f.casefold() for f in task["allowed_files"]]))
                if any(db.execute("SELECT 1 FROM locks WHERE resource=?", (r,)).fetchone() for r in resources):
                    continue
                attempt_id = uuid.uuid4().hex
                epoch = row["epoch"] + 1
                db.execute("UPDATE tasks SET state='running',epoch=?,attempts=attempts+1,attempt_id=?,expires=? WHERE id=?",
                           (epoch, attempt_id, now + lease_seconds, row["id"]))
                db.executemany("INSERT INTO locks VALUES(?,?)", [(r, row["id"]) for r in resources])
                db.execute("UPDATE budget SET used=used+1 WHERE id=1")
                db.execute("INSERT INTO events(task,event,at) VALUES(?,?,?)", (row["id"], "claimed", now))
                return {"task": task, "task_hash": row["hash"], "attempt_id": attempt_id, "epoch": epoch}
        return None

    @staticmethod
    def _current(db, claim, states, now):
        row = db.execute("SELECT * FROM tasks WHERE id=?", (claim["task"]["task_id"],)).fetchone()
        return (row and row["state"] in states and row["epoch"] == claim["epoch"]
                and row["attempt_id"] == claim["attempt_id"] and row["hash"] == claim["task_hash"]
                and fingerprint(claim["task"]) == row["hash"]
                and row["expires"] > now)

    def validating(self, claim, now=None):
        now = time.time() if now is None else now
        with self.transaction() as db:
            if not self._current(db, claim, {"running"}, now):
                return False
            db.execute("UPDATE tasks SET state='validating' WHERE id=?", (claim["task"]["task_id"],))
            return True

    def finish(self, claim, receipt, passed, now=None):
        now = time.time() if now is None else now
        with self.transaction() as db:
            if not self._current(db, claim, {"validating"}, now):
                return False
            if type(receipt) is not dict or receipt.get("process_tree_empty") is not True:
                raise ContractError("CLEANUP_EVIDENCE_REQUIRED")
            if type(passed) is not bool:
                raise ContractError("VALIDATION_RESULT")
            key = claim["task"]["task_id"]
            state = "awaiting_review" if passed else "failed"
            db.execute("UPDATE tasks SET state=?,receipt=?,expires=NULL WHERE id=?", (state, canonical(receipt), key))
            db.execute("DELETE FROM locks WHERE task=?", (key,))
            db.execute("INSERT INTO events(task,event,at) VALUES(?,?,?)", (key, state, now))
            return True

    @staticmethod
    def _identity(row, claim, epoch_delta=0):
        return (row and row["epoch"] == claim["epoch"] + epoch_delta
                and row["attempt_id"] == claim["attempt_id"]
                and row["hash"] == claim["task_hash"]
                and fingerprint(claim["task"]) == row["hash"])

    def fence(self, claim, reason="cancelled"):
        task_id = claim["task"]["task_id"]
        with self.transaction() as db:
            row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not self._identity(row, claim) or row["state"] not in {"running", "validating"}:
                return False
            db.execute("UPDATE tasks SET state='held_cleanup',epoch=epoch+1,reason=? WHERE id=?", (reason, task_id))
            db.execute("INSERT INTO events(task,event,at) VALUES(?,?,?)", (task_id, "fenced", time.time()))
            return True

    def expired(self, now=None):
        now = time.time() if now is None else now
        with self.transaction() as db:
            claims = [{"task": json.loads(r["contract"]), "task_hash": r["hash"],
                       "attempt_id": r["attempt_id"], "epoch": r["epoch"]}
                      for r in db.execute("SELECT * FROM tasks WHERE state IN ('running','validating') AND expires<=?", (now,))]
            db.execute("UPDATE tasks SET state='held_cleanup',epoch=epoch+1,reason='lease_expired' WHERE state IN ('running','validating') AND expires<=?", (now,))
            return claims  # original attempt tokens; locks remain until matching cleanup

    def cleanup(self, claim, *, tree_empty, retry=False, provider_completion_unknown=False):
        task_id = claim["task"]["task_id"]
        with self.transaction() as db:
            row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if (not self._identity(row, claim, epoch_delta=1)
                    or row["state"] != "held_cleanup" or tree_empty is not True):
                return False
            task = json.loads(row["contract"])
            if provider_completion_unknown:
                db.execute('UPDATE tasks SET provider_unknown=1 WHERE id=?', (task_id,))
            if retry and (provider_completion_unknown or row["provider_unknown"] or row["attempts"] >= task["budgets"]["attempts"]):
                return False
            db.execute("UPDATE tasks SET state=?,expires=NULL WHERE id=?", ("queued" if retry else "cancelled", task_id))
            db.execute("DELETE FROM locks WHERE task=?", (task_id,))
            return True

    def dispatch_intent(self, claim):
        """Persist uncertainty BEFORE any provider invocation; crashes retain it."""
        with self.transaction() as db:
            row = db.execute('SELECT * FROM tasks WHERE id=?', (claim['task']['task_id'],)).fetchone()
            if not self._current(db, claim, {'running'}, time.time()) or row['provider_unknown']:
                return False
            db.execute('UPDATE tasks SET provider_unknown=1 WHERE id=?', (row['id'],))
            db.execute('INSERT INTO events(task,event,at) VALUES(?,?,?)', (row['id'], 'dispatch_intent', time.time()))
            return True

    def review(self, task_id, *, receipt_hash, reviewer, independent):
        with self.transaction() as db:
            row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if (not row or row["state"] != "awaiting_review" or not independent
                    or reviewer in {"", "worker", row["attempt_id"]}
                    or fingerprint(json.loads(row["receipt"])) != receipt_hash):
                return False
            db.execute("UPDATE tasks SET state='reviewed' WHERE id=?", (task_id,))
            return True  # local handoff only; never authorizes a merge

    def snapshot(self):
        with self.transaction() as db:
            return {"tasks": [dict(r) for r in db.execute("SELECT * FROM tasks ORDER BY rowid")],
                    "budget": dict(db.execute("SELECT * FROM budget").fetchone()),
                    "locks": [dict(r) for r in db.execute("SELECT * FROM locks")]}
