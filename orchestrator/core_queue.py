"""Generic controller ledger. No worker launch, review import or merge executor."""
from copy import deepcopy
from pathlib import Path
from .contracts import ContractError, fingerprint
from .store import Store
from .tasks import validate_tasks
from .policy import compile_policy


class CoreQueue(Store):
    def __init__(self, path, repo, *, session=None):
        path = Path(path).absolute()
        if path.resolve().is_relative_to(Path(repo).resolve()):
            raise ContractError("CONTROLLER_DATABASE_OUTSIDE_REPO_REQUIRED")
        for node in [path, *path.parents]:
            if node.is_symlink() or node.is_junction():
                raise ContractError("REPARSE_PATH")
        self.repo = repo
        self.session = deepcopy(session)
        self.policy = compile_policy(repo, session=session)
        settings = self.policy["settings"]["scheduler"]
        super().__init__(path, settings["max_dispatches"],
                         validator=lambda tasks: validate_tasks(tasks, self.policy),
                         max_active=settings["max_active"],
                         binding={"repo": self.policy["repo_identity"], "policy": self.policy["policy_hash"],
                                  "task_schema": 2, "core_version": self.policy["core_version"]})

    def _fresh(self):
        if compile_policy(self.repo, session=self.session)["policy_hash"] != self.policy["policy_hash"]:
            raise ContractError("QUEUE_POLICY_DRIFT")

    def enqueue(self, tasks):
        self._fresh()
        return super().enqueue(tasks)

    def claim(self, lease_seconds=180, now=None):
        self._fresh()
        if type(lease_seconds) not in (int, float) or not 0 < lease_seconds <= 600:
            raise ContractError("LEASE_BOUND")
        return super().claim(lease_seconds, now)

    def review(self, *args, **kwargs):
        # Caller booleans/model names cannot establish reviewer identity. The v1
        # synthetic method is deliberately inaccessible through this entrypoint.
        raise ContractError("TRUSTED_REVIEW_IMPORT_NOT_IMPLEMENTED")

    def dispatch_intent(self, claim):
        self._fresh()
        return super().dispatch_intent(claim)

    def merge_eligibility(self, task_id):
        self._fresh()
        rows = {r["id"]: r for r in self.snapshot()["tasks"]}
        if task_id not in rows:
            raise ContractError("UNKNOWN_TASK")
        return {"status": "HELD", "task_id": task_id, "task_state": rows[task_id]["state"],
                "reason": "TRUSTED_REVIEW_IMPORT_NOT_IMPLEMENTED", "merge_executed": False,
                "human_authorization_required": True}
