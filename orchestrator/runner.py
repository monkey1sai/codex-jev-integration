"""Offline controller and CLI plans. No unattended merge or live bypass entry."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import threading
import time

from .contracts import canonical, synthetic_task, fingerprint, ContractError
from .store import Store
from .workspaces import allocate, fixture_repo, scan, validate_artifact, write_new, git
from .processes import bounded_run
from .cli_adapter import cli_plan


ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "orchestrator" / "fake_worker.py"


def source_hashes():
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((ROOT / "orchestrator").glob("*.py"))}


def reconcile_stale(store, claim, *, tree_empty):
    """Fence only this attempt, including expired leases; never touch a successor."""
    store.fence(claim, "stale_result")
    return store.cleanup(claim, tree_empty=tree_empty)


def _execute(store, claim, worktree, temp, baseline, barrier, *, delay=1.0, behavior="valid"):
    try:
        barrier.wait(timeout=30)
        start = time.monotonic()
        result = bounded_run([sys.executable, "-B", str(WORKER), "--delay", str(delay), "--behavior", behavior],
                             cwd=worktree, stdin=canonical(claim["task"]).encode(),
                             timeout=claim["task"]["budgets"]["runtime_seconds"],
                             before_terminate=lambda: store.fence(claim, "process_stop"))
        end = time.monotonic()
        interval = [result["process_created_at"], result["process_exited_at"]]
        if result["reason"] or not result["tree_empty"]:
            store.fence(claim, result["reason"] or "cleanup_unverified")
            store.cleanup(claim, tree_empty=result["tree_empty"])
            return {"task_id": claim["task"]["task_id"], "status": "HELD", "reason": result["reason"],
                    "tree_empty": result["tree_empty"], "interval": interval}
        if not store.validating(claim):
            reconciled = reconcile_stale(store, claim, tree_empty=True)
            return {"task_id": claim["task"]["task_id"], "status": "STALE_REJECTED",
                    "interval": interval, "cleanup_reconciled": reconciled, "tree_empty": True}
        try:
            receipt = validate_artifact(worktree, claim, baseline)
            passed = result["returncode"] == 0
        except (ContractError, ValueError, OSError) as error:
            receipt = {"status": "FAIL", "reason": str(error) if isinstance(error, ContractError) else "INVALID_ARTIFACT"}
            passed = False
        receipt.update({"process_tree_empty": True, "pid": result["pid"],
                        "process_boundary": result["process_boundary"],
                        "elapsed_seconds": result["elapsed_seconds"],
                        "evidence_kind": "OFFLINE_FAKE_WORKER", "model_inference_calls": 0,
                        "independent_review": "NOT_RUN", "merge_authorization": False})
        artifact_dir = worktree.parents[1] / "controller-artifacts" / claim["attempt_id"]
        if passed:
            artifact = (worktree / claim["task"]["allowed_files"][0]).read_bytes()
            if hashlib.sha256(artifact).hexdigest() != receipt["artifact_sha256"]:
                raise ContractError("ARTIFACT_DRIFT")
            artifact_dir.mkdir(parents=True)
            with (artifact_dir / "result.raw.json").open("xb") as stream:
                stream.write(artifact)
        write_new(artifact_dir / "validation-receipt.json", receipt)
        accepted = store.finish(claim, receipt, passed)
        if not accepted:
            reconciled = reconcile_stale(store, claim, tree_empty=True)
            return {"task_id": claim["task"]["task_id"], "status": "STALE_REJECTED",
                    "interval": interval, "cleanup_reconciled": reconciled, "tree_empty": True}
        return {"task_id": claim["task"]["task_id"], "status": "VALIDATED" if passed else "REJECTED",
                "receipt_hash": fingerprint(receipt), "interval": interval, "tree_empty": True}
    except BaseException as error:
        store.fence(claim, "controller_exception")
        # Exceptions do not constitute cleanup evidence; retain locks and worktree.
        return {"task_id": claim["task"]["task_id"], "status": "HELD", "reason": type(error).__name__,
                "tree_empty": False}


def offline(root, *, workers=5, tasks=20, behavior="valid", delay=1.0):
    if workers not in (1, 2, 5, 10, 20) or not 1 <= tasks <= 1000:
        raise ContractError("MVP_CAPACITY")
    root = Path(root).resolve()
    if root.exists():
        raise ContractError("RUN_OUTPUT_COLLISION")
    if ROOT not in root.parents:
        raise ContractError("RUN_OUTSIDE_FIXTURE")
    root.mkdir(parents=True)
    sources = source_hashes()
    repo, base = fixture_repo(root)
    store = Store(root / "controller" / "queue.sqlite", max_dispatches=tasks)
    contracts = [synthetic_task(i, base) for i in range(1, tasks + 1)]
    store.enqueue(contracts)
    write_new(root / "contracts.json", contracts)
    rows = []
    oracle_hash = hashlib.sha256((ROOT / "orchestrator" / "workspaces.py").read_bytes()).hexdigest()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for offset in range(0, tasks, workers):
            batch = []
            for _ in range(min(workers, tasks - offset)):
                claim = store.claim(lease_seconds=300)
                if claim is None:
                    raise ContractError("UNEXPECTED_ADMISSION_BLOCK")
                worktree, temp = allocate(root, repo, claim)
                batch.append((claim, worktree, temp, scan(worktree)))
            barrier = threading.Barrier(len(batch))
            pending = [pool.submit(_execute, store, claim, worktree, temp, baseline, barrier,
                                   delay=delay, behavior=behavior) for claim, worktree, temp, baseline in batch]
            for future in as_completed(pending):
                rows.append(future.result())
            if any(row["status"] in {"HELD", "STALE_REJECTED"} for row in rows):
                break  # no escalation or repeated startup after a failed wave
    if hashlib.sha256((ROOT / "orchestrator" / "workspaces.py").read_bytes()).hexdigest() != oracle_hash:
        raise ContractError("ORACLE_DRIFT")
    if source_hashes() != sources:
        raise ContractError("CONTROLLER_SOURCE_DRIFT")
    points = sorted((point, change) for row in rows if "interval" in row
                    for point, change in ((row["interval"][0], 1), (row["interval"][1], -1)))
    current = peak = 0
    for _, change in points:
        current += change
        peak = max(peak, current)
    snapshot = store.snapshot()
    report = {"kind": "OFFLINE_FAKE_WORKER", "run_root": str(root), "workers_requested": workers,
              "process_intervals_peak": peak, "queued_tasks": tasks,
              "result_counts": dict(Counter(row["status"] for row in rows)),
              "states": dict(Counter(row["state"] for row in snapshot["tasks"])),
              "budget": snapshot["budget"], "results": rows,
              "oracle_sha256": oracle_hash, "fixture_base_sha": base,
              "source_sha256": sources, "interval_measurement": "PARENT_OBSERVED_ROOT_LIFETIME_POLL_20MS",
              "native_codex_workers": 0, "model_inference_calls": 0,
              "sandbox_isolation": "NOT_RUN", "independent_review": "NOT_RUN",
              "merge": "NOT_RUN", "retained_worktrees": len(rows)}
    write_new(root / "report.json", report)
    return report


def plan(root, executable, global_home):
    root = Path(root).resolve()
    if root.exists() or ROOT not in root.parents:
        raise ContractError("PLAN_OUTPUT_COLLISION_OR_SCOPE")
    root.mkdir(parents=True)
    repo, base = fixture_repo(root)
    task = synthetic_task(1, base)
    claim = {"task": task, "task_hash": fingerprint(task), "attempt_id": "plan-only", "epoch": 0}
    worktree, temp = allocate(root, repo, claim)
    result = cli_plan(executable, worktree, temp, task, global_home)
    result["stdin"] = result["stdin"].decode()
    result["authorization_envelope"] = {
        "destination": "existing supported Codex provider", "purpose": "synthetic fixture only",
        "allowed_operations": "no dispatch until native admission passes",
        "data": "synthetic contract + existing Global instructions",
        "forbidden": "secrets, private source, global/remote mutation, permission bypass",
        "stop": "any unverified native isolation/control/cleanup or quota failure",
    }
    write_new(root / "cli-plan.json", result)
    return {"status": "HELD", "live_admission": result["live_admission"], "native_dispatches": 0,
            "plan": str(root / "cli-plan.json"), "effective_controls": "UNVERIFIED"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    fake = sub.add_parser("offline")
    fake.add_argument("--run-id", required=True)
    fake.add_argument("--workers", type=int, default=5)
    fake.add_argument("--tasks", type=int, default=20)
    fake.add_argument("--behavior", choices=("valid", "bad", "scope"), default="valid")
    native = sub.add_parser("cli-plan")
    native.add_argument("--run-id", required=True)
    native.add_argument("--executable", required=True)
    native.add_argument("--global-home", required=True)
    args = parser.parse_args()
    if not re_safe_id(args.run_id):
        raise ContractError("INVALID_RUN_ID")
    root = ROOT / "runs" / args.run_id
    try:
        if args.command == "offline":
            result = offline(root, workers=args.workers, tasks=args.tasks, behavior=args.behavior)
            print(json.dumps({k: v for k, v in result.items() if k != "results"}, ensure_ascii=False, indent=2))
            return 0 if result["result_counts"] == {"VALIDATED": args.tasks} else 2
        result = plan(root, args.executable, args.global_home)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2
    except ContractError as error:
        print(json.dumps({"status": "HELD", "reason": str(error)}))
        return 2


def re_safe_id(value):
    import re
    return re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", value) is not None


if __name__ == "__main__":
    raise SystemExit(main())
