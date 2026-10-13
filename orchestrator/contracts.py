"""Strict task contracts and dependency checks; commands are not task data."""
from __future__ import annotations

import hashlib
import json
import re
from collections import deque
from pathlib import PurePosixPath


class ContractError(ValueError):
    pass


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fingerprint(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def relative_file(value):
    if (not isinstance(value, str) or not value or len(value) > 240
            or re.search(r'[\\:<>|"\x00-\x1f]', value)):
        raise ContractError("INVALID_RELATIVE_FILE")
    parts = value.split("/")
    if any(p in ("", ".", "..") or p.endswith((".", " ")) for p in parts):
        raise ContractError("INVALID_RELATIVE_FILE")
    if PurePosixPath(value).is_absolute() or any("*" in p or "?" in p for p in parts):
        raise ContractError("EXPLICIT_FILES_REQUIRED")
    if any(p.casefold() in (".git", ".codex", ".agents") for p in parts):
        raise ContractError("PROTECTED_FILE")
    if any(re.fullmatch(r"con|prn|aux|nul|com[1-9]|lpt[1-9]", p.split(".")[0], re.I) for p in parts):
        raise ContractError("WINDOWS_DEVICE_PATH")
    return value


KEYS = {"schema_version", "task_id", "goal", "inputs", "allowed_files", "dependencies",
        "acceptance_criteria", "tests", "expected_artifacts", "execution", "budgets",
        "resource_locks", "base_sha", "authorization", "review"}


def validate(task):
    if (type(task) is not dict or set(task) != KEYS
            or type(task["schema_version"]) is not int or task["schema_version"] != 1):
        raise ContractError("CONTRACT_SCHEMA")
    if not isinstance(task["task_id"], str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", task["task_id"]):
        raise ContractError("TASK_ID")
    if not isinstance(task["goal"], str) or not 1 <= len(task["goal"]) <= 2000:
        raise ContractError("GOAL")
    if not isinstance(task["base_sha"], str) or not re.fullmatch(r"[a-f0-9]{40}", task["base_sha"]):
        raise ContractError("BASE_SHA")
    files = task["allowed_files"]
    if type(files) is not list or not 1 <= len(files) <= 32:
        raise ContractError("FILE_SCOPE")
    for name in files:
        relative_file(name)
    if len({f.casefold() for f in files}) != len(files):
        raise ContractError("FILE_COLLISION")
    for key in ("dependencies", "resource_locks", "acceptance_criteria", "expected_artifacts"):
        values = task[key]
        if type(values) is not list or len(values) > 32 or any(not isinstance(v, str) or not v or len(v) > 300 for v in values):
            raise ContractError("LIST_FIELD")
        if len(values) != len(set(values)):
            raise ContractError("DUPLICATE_LIST_ENTRY")
    if not task["acceptance_criteria"] or task["expected_artifacts"] != [files[0], "validation_receipt"]:
        raise ContractError("ARTIFACT_CONTRACT")
    if task["tests"] != ["fixture_sum_v1"]:
        raise ContractError("UNREGISTERED_VALIDATOR")
    inputs = task["inputs"]
    if type(inputs) is not dict or set(inputs) != {"numbers"} or type(inputs["numbers"]) is not list:
        raise ContractError("INPUTS")
    if not 1 <= len(inputs["numbers"]) <= 100 or any(type(n) is not int or abs(n) > 1000000 for n in inputs["numbers"]):
        raise ContractError("INPUTS")
    execution = task["execution"]
    if type(execution) is not dict or set(execution) != {"role", "model", "reasoning_effort", "native_children"}:
        raise ContractError("EXECUTION")
    if execution != {"role": "worker", "model": "gpt-6.1-sol", "reasoning_effort": "medium", "native_children": 0}:
        raise ContractError("MVP_EXECUTION_POLICY")
    budgets = task["budgets"]
    if type(budgets) is not dict or set(budgets) != {"runtime_seconds", "attempts"}:
        raise ContractError("BUDGET")
    if type(budgets["runtime_seconds"]) is not int or not 1 <= budgets["runtime_seconds"] <= 600:
        raise ContractError("BUDGET")
    if type(budgets["attempts"]) is not int or not 1 <= budgets["attempts"] <= 2:
        raise ContractError("BUDGET")
    if task["authorization"] != {"external_writes": False, "scope": "allocated_attempt_only"}:
        raise ContractError("AUTHORIZATION")
    if task["review"] != {"required": True, "independent": True}:
        raise ContractError("REVIEW_FLOOR")
    return task


def validate_batch(tasks):
    if type(tasks) is not list or not 1 <= len(tasks) <= 1000:
        raise ContractError("QUEUE_CAPACITY")
    by_id = {}
    for task in tasks:
        validate(task)
        if task["task_id"] in by_id:
            raise ContractError("DUPLICATE_TASK_ID")
        by_id[task["task_id"]] = task
    indegree = {key: len(task["dependencies"]) for key, task in by_id.items()}
    children = {key: [] for key in by_id}
    for key, task in by_id.items():
        for dependency in task["dependencies"]:
            if dependency not in by_id:
                raise ContractError("MISSING_DEPENDENCY")
            children[dependency].append(key)
    ready = deque(key for key, count in indegree.items() if count == 0)
    visited = 0
    while ready:
        key = ready.popleft()
        visited += 1
        for child in children[key]:
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
    if visited != len(by_id):
        raise ContractError("DAG_CYCLE")
    return tasks


def synthetic_task(number, base_sha):
    name = f"results/task-{number:04d}.json"
    return validate({
        "schema_version": 1, "task_id": f"task-{number:04d}",
        "goal": "Produce synthetic sum and count as JSON in the one assigned file.",
        "base_sha": base_sha, "inputs": {"numbers": [number, -3, 7, 0, number * 2]},
        "allowed_files": [name], "dependencies": [],
        "resource_locks": [f"result:{number}"],
        "acceptance_criteria": ["Exact sum/count; no extra fields; only assigned file changes."],
        "tests": ["fixture_sum_v1"], "expected_artifacts": [name, "validation_receipt"],
        "execution": {"role": "worker", "model": "gpt-6.1-sol", "reasoning_effort": "medium", "native_children": 0},
        "budgets": {"runtime_seconds": 120, "attempts": 1},
        "authorization": {"external_writes": False, "scope": "allocated_attempt_only"},
        "review": {"required": True, "independent": True},
    })
