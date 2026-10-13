"""Generic v2 data-only contracts; execution is intentionally not implemented."""
from collections import deque
from .contracts import ContractError, fingerprint, relative_file
from .policy import identifier
import re

KEYS = {"schema_version", "task_id", "goal", "inputs", "allowed_files", "dependencies",
        "acceptance_criteria", "tests", "expected_artifacts", "execution", "budgets",
        "resource_locks", "base_sha", "authorization", "review", "capability"}


def validate_task(task, policy):
    if type(task) is not dict or set(task) - {'priority'} != KEYS or type(task["schema_version"]) is not int or task["schema_version"] != 2:
        raise ContractError("CONTRACT_SCHEMA")
    # Controller-owned immutable contract metadata, never execution authority.
    if type(task.get('priority', 0)) is not int or not 0 <= task.get('priority', 0) <= 100:
        raise ContractError('PRIORITY')
    identifier(task["task_id"])
    if not isinstance(task["goal"], str) or not 1 <= len(task["goal"]) <= 4000:
        raise ContractError("GOAL")
    if not isinstance(task["base_sha"], str) or not re.fullmatch(r"[a-f0-9]{40}", task["base_sha"]):
        raise ContractError("BASE_SHA")
    settings = policy["settings"]
    cap_id = identifier(task["capability"])
    cap = settings["capabilities"].get(cap_id)
    if not cap:
        raise ContractError("UNKNOWN_CAPABILITY")
    for key in ("allowed_files", "dependencies", "acceptance_criteria", "tests", "expected_artifacts", "resource_locks"):
        values = task[key]
        if type(values) is not list or len(values) > 64 or any(not isinstance(v, str) or not v or len(v) > 1000 for v in values):
            raise ContractError("LIST_FIELD")
        if len(set(v.casefold() for v in values)) != len(values):
            raise ContractError("DUPLICATE_LIST_ENTRY")
    for name in task["allowed_files"]:
        relative_file(name)
    if not set(task["allowed_files"]) <= set(cap["allowed_files"]):
        raise ContractError("OWNERSHIP_SCOPE")
    if not task["acceptance_criteria"] or not task["tests"] or not task["expected_artifacts"]:
        raise ContractError("ACCEPTANCE_REQUIRED")
    if not set(task["tests"]) <= set(cap["validators"]):
        raise ContractError("UNREGISTERED_VALIDATOR")
    for dep in task["dependencies"]:
        identifier(dep)
    inputs = task["inputs"]
    if type(inputs) is not list or len(inputs) > 32:
        raise ContractError("INPUTS")
    for item in inputs:
        if type(item) is not dict or set(item) != {"path", "sha256"}:
            raise ContractError("INPUTS")
        relative_file(item["path"])
        if not isinstance(item["sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", item["sha256"]):
            raise ContractError("INPUT_HASH")
    execution = task["execution"]
    if type(execution) is not dict or type(execution.get("native_children")) is not int or execution != {"role": cap["role"], **settings["roles"][cap["role"]], "native_children": 0}:
        raise ContractError("EXECUTION_POLICY")
    budget = task["budgets"]
    if type(budget) is not dict or set(budget) != {"runtime_seconds", "attempts"}:
        raise ContractError("BUDGET")
    for key, upper in (("runtime_seconds", 600), ("attempts", settings["scheduler"]["max_attempts"])):
        if type(budget[key]) is not int or not 1 <= budget[key] <= upper:
            raise ContractError("BUDGET")
    if type(task["authorization"]) is not dict or type(task["authorization"].get("external_writes")) is not bool or task["authorization"] != {"external_writes": False, "scope": "allocated_attempt_only"}:
        raise ContractError("AUTHORIZATION")
    if type(task["review"]) is not dict or any(type(task["review"].get(key)) is not bool for key in ("required", "independent")) or task["review"] != {"required": True, "independent": True}:
        raise ContractError("REVIEW_FLOOR")
    if len(str(task).encode("utf-8")) > 65536:
        raise ContractError("TASK_TOO_LARGE")
    return task


def validate_tasks(tasks, policy):
    if type(tasks) is not list or not 1 <= len(tasks) <= policy["settings"]["scheduler"]["max_queued"]:
        raise ContractError("QUEUE_CAPACITY")
    by_id = {}
    for task in tasks:
        validate_task(task, policy)
        if task["task_id"] in by_id:
            raise ContractError("DUPLICATE_TASK_ID")
        by_id[task["task_id"]] = task
    indegree = {key: len(t["dependencies"]) for key, t in by_id.items()}
    children = {key: [] for key in by_id}
    for key, task in by_id.items():
        for dep in task["dependencies"]:
            if dep not in by_id:
                raise ContractError("MISSING_DEPENDENCY")
            children[dep].append(key)
    ready = deque(k for k, n in indegree.items() if n == 0)
    count = 0
    while ready:
        key = ready.popleft()
        count += 1
        for child in children[key]:
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
    if count != len(tasks):
        raise ContractError("DAG_CYCLE")
    return tasks
