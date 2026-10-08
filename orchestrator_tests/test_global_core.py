from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from orchestrator.contracts import ContractError, fingerprint
from orchestrator.policy import compile_policy, load, merge, validate_overlay, validate_jev
from orchestrator.provision import apply, encoded, plan, write_new, recover
from orchestrator.core_queue import CoreQueue
from orchestrator.routing import route
from orchestrator.tasks import validate_task, validate_tasks

ROOT = Path(__file__).resolve().parents[1]


def config():
    return {"schema_version": 1, "capabilities": {
        "backend": {"role": "worker", "description": "Bounded Python implementation",
                    "allowed_files": ["src/api.py", "tests/test_api.py"], "validators": ["unit"]}},
        "validators": {"unit": {"argv": ["python", "-m", "unittest"], "timeout_seconds": 120}},
        "guidance": ["AGENTS.md"]}


class Fixture(unittest.TestCase):
    def setUp(self):
        (ROOT / ".test-runs").mkdir(exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix="global-", dir=ROOT / ".test-runs"))
        self.repo = self.root / "repo"
        (self.repo / ".git").mkdir(parents=True)
        (self.repo / ".codex").mkdir()
        (self.repo / ".codex/orchestrator.json").write_bytes(encoded(config()))
        self.policy = compile_policy(self.repo)
        self.spec = {"orchestrator": {"roles": {"worker": {"model": "gpt-6-luna", "reasoning_effort": "medium"}}}, "jev": {"enabled": False}}

    def task(self, number=1):
        return {"schema_version": 2, "task_id": f"task-{number}", "goal": "Fix API behavior",
                "inputs": [{"path": "src/api.py", "sha256": "1" * 64}], "allowed_files": ["src/api.py"],
                "dependencies": [], "acceptance_criteria": ["Existing API contract passes"],
                "tests": ["unit"], "expected_artifacts": ["patch", "validation_receipt"],
                "execution": {"role": "worker", "model": "gpt-6.1-sol", "reasoning_effort": "medium", "native_children": 0},
                "budgets": {"runtime_seconds": 120, "attempts": 1}, "resource_locks": [],
                "base_sha": "0" * 40, "capability": "backend",
                "authorization": {"external_writes": False, "scope": "allocated_attempt_only"},
                "review": {"required": True, "independent": True}}

    def planned(self):
        path = self.root / "plan.json"
        digest = write_new(path, plan(self.repo, self.spec))
        return path, digest


class Policy(Fixture):
    def test_override_changes_worker_preserves_review_and_sources(self):
        result = compile_policy(self.repo, session={"roles": {"worker": {"model": "gpt-6-luna", "reasoning_effort": "low"}}, "routing": {"jev_enabled": False}})
        self.assertEqual(result["settings"]["roles"]["worker"]["model"], "gpt-6-luna")
        self.assertEqual(result["settings"]["roles"]["reviewer"]["model"], "gpt-6-astra")
        self.assertFalse(result["floors"]["live_execution"])
        self.assertEqual(result["sources"][-1]["layer"], "explicit_session")

    def test_downgrades_and_unknown_fields_rejected(self):
        for value in ({"floors": {"required_review": False}}, {"roles": {"reviewer": {"model": "gpt-6.1-sol", "reasoning_effort": "high"}}},
                      {"roles": {"reviewer": {"model": "gpt-6-astra", "reasoning_effort": "medium"}}},
                      {"scheduler": {"max_active": 20}}, {"routing": {"endpoint": "https://evil.invalid"}},
                      {"verifier": "repo_module.accept"}, {"scheduler": {"max_attempts": True}},
                      {"roles": {"worker": {"model": [], "reasoning_effort": "medium"}}}):
            with self.subTest(value=value), self.assertRaises(ContractError):
                compile_policy(self.repo, session=value)

    def test_duplicate_keys_nonfinite_and_oversized_json_rejected(self):
        path = self.root / "invalid.json"
        for value in ('{"enabled":true,"enabled":false}', '{"timeout_seconds":NaN}', ' ' * 65537):
            path.write_text(value)
            with self.assertRaises(ContractError):
                load(path)

    def test_json_reader_never_reads_more_than_limit_plus_one(self):
        reads = []
        class BoundedStream(io.BytesIO):
            def read(self, size=-1):
                reads.append(size)
                return super().read(size)
        with patch("pathlib.Path.open", return_value=BoundedStream(b"x" * 1000000)):
            with self.assertRaisesRegex(ContractError, "CONFIG_TOO_LARGE"):
                load(self.root / "ignored", max_bytes=64)
        self.assertEqual(reads, [65])

    def test_explicit_repo_only_no_ancestor_override(self):
        parent = self.repo.parent / ".codex"
        parent.mkdir()
        (parent / "orchestrator.json").write_bytes(encoded({"scheduler": {"max_active": 99}}))
        self.assertEqual(compile_policy(self.repo)["settings"]["scheduler"]["max_active"], 2)

    def test_jev_disabled_overrides_controller_enable_without_provider(self):
        (self.repo / ".codex/jev.json").write_bytes(encoded({"enabled": False, "timeout_seconds": 10}))
        self.assertFalse(compile_policy(self.repo, session={"routing": {"jev_enabled": True}})["settings"]["routing"]["jev_enabled"])

    def test_unregistered_validator_and_protected_ownership_rejected(self):
        for mutate in (lambda v: v["capabilities"]["backend"].update(validators=["missing"]),
                       lambda v: v["capabilities"]["backend"].update(allowed_files=[".codex/config.toml"])):
            value = config()
            mutate(value)
            (self.repo / ".codex/orchestrator.json").write_bytes(encoded(value))
            with self.assertRaises(ContractError):
                compile_policy(self.repo)


class Contracts(Fixture):
    def test_task_valid_and_scope_model_command_review_downgrades_fail(self):
        validate_task(self.task(), self.policy)
        for mutate in (lambda t: t.update(allowed_files=["src/unknown.py"]), lambda t: t.update(tests=["shell arbitrary"]),
                       lambda t: t["execution"].update(model="gpt-6-luna"), lambda t: t["execution"].update(native_children=False),
                       lambda t: t["review"].update(independent=1), lambda t: t["authorization"].update(external_writes=0)):
            value = self.task()
            mutate(value)
            with self.assertRaises(ContractError):
                validate_task(value, self.policy)

    def test_generic_thousand_task_dag_is_bounded_and_iterative(self):
        values = [self.task(i) for i in range(1000)]
        for before, after in zip(values, values[1:]):
            after["dependencies"] = [before["task_id"]]
        validate_tasks(values, self.policy)
        values[0]["dependencies"] = [values[-1]["task_id"]]
        with self.assertRaisesRegex(ContractError, "DAG_CYCLE"):
            validate_tasks(values, self.policy)


class Queue(Fixture):
    def ledger(self, name="queue.sqlite", **kwargs):
        return CoreQueue(self.root / name, self.repo, **kwargs)

    def test_cross_batch_dependencies_and_dedup(self):
        queue = self.ledger()
        a, b = self.task(), self.task(2)
        b["dependencies"] = [a["task_id"]]
        queue.enqueue([a]); queue.enqueue([b]); queue.enqueue([a])
        self.assertEqual(len(queue.snapshot()["tasks"]), 2)
        self.assertEqual(queue.claim()["task"]["task_id"], "task-1")
        self.assertIsNone(queue.claim())

    def test_same_file_lock_casefold(self):
        queue = self.ledger()
        queue.enqueue([self.task(), self.task(2)])
        self.assertIsNotNone(queue.claim())
        self.assertIsNone(queue.claim())

    def test_atomic_active_cap_and_held_cleanup_consumes_slot(self):
        tasks = [self.task(i) for i in range(4)]
        for task in tasks:
            task["allowed_files"] = []
        queue = self.ledger(); queue.enqueue(tasks)
        with ThreadPoolExecutor(20) as pool:
            claims = [c for c in pool.map(lambda _: self.ledger().claim(), range(20)) if c]
        self.assertEqual(len(claims), 2)
        queue.fence(claims[0])
        self.assertIsNone(queue.claim())
        self.assertFalse(queue.cleanup(claims[0], tree_empty=False))
        self.assertIsNone(queue.claim())
        self.assertTrue(queue.cleanup(claims[0], tree_empty=True))
        self.assertIsNotNone(queue.claim())

    def test_queue_reopen_repo_and_policy_drift_rejected(self):
        queue = self.ledger(); queue.enqueue([self.task()])
        with self.assertRaisesRegex(ContractError, "QUEUE_POLICY_DRIFT"):
            self.ledger(session={"routing": {"jev_enabled": False}})
        other = self.root / "other"; (other / ".codex").mkdir(parents=True)
        (other / ".codex/orchestrator.json").write_bytes(encoded(config()))
        with self.assertRaisesRegex(ContractError, "QUEUE_POLICY_DRIFT"):
            CoreQueue(queue.path, other)
        (self.repo / ".codex/jev.json").write_bytes(encoded({"enabled": False}))
        with self.assertRaisesRegex(ContractError, "QUEUE_POLICY_DRIFT"):
            queue.claim()

    def test_forged_review_is_denied_and_merge_remains_held(self):
        queue = self.ledger(); queue.enqueue([self.task()])
        claim = queue.claim(); queue.validating(claim)
        queue.finish(claim, {"process_tree_empty": True}, True)
        with self.assertRaisesRegex(ContractError, "TRUSTED_REVIEW_IMPORT"):
            queue.review("task-1", receipt_hash="x", reviewer="astra", independent=True)
        self.assertEqual(queue.merge_eligibility("task-1")["status"], "HELD")
        self.assertEqual(queue.snapshot()["tasks"][0]["state"], "awaiting_review")

    def test_database_inside_worker_repo_denied(self):
        with self.assertRaisesRegex(ContractError, "CONTROLLER_DATABASE"):
            CoreQueue(self.repo / "queue.sqlite", self.repo)


class Routing(Fixture):
    def test_single_candidate_deterministic_and_ambiguity_optional(self):
        result = route(self.repo, goal="Fix", candidate_ids=["backend"], context={})
        self.assertEqual(result["status"], "SELECTED")
        self.assertFalse(result["provider_called"])
        value = config(); value["capabilities"]["alternate"] = deepcopy(value["capabilities"]["backend"])
        (self.repo / ".codex/orchestrator.json").write_bytes(encoded(value))
        result = route(self.repo, goal="Fix", candidate_ids=["backend", "alternate"], context={"evidence": ["bounded"]})
        self.assertEqual(result["status"], "HELD")
        self.assertTrue(result["optional_jev"])
        advisory = {"state_hash": result["state_hash"], "selected_id": "alternate", "observation_id": "caller-id", "advisory_only": True}
        proposal = route(self.repo, goal="Fix", candidate_ids=["backend", "alternate"], context={"evidence": ["bounded"]}, advisory=advisory)
        self.assertEqual(proposal["status"], "PROPOSED")
        self.assertFalse(proposal["executed"])
        advisory["state_hash"] = "stale"
        with self.assertRaisesRegex(ContractError, "STALE_OR_INVALID"):
            route(self.repo, goal="Fix", candidate_ids=["backend", "alternate"], context={"evidence": ["bounded"]}, advisory=advisory)

    def test_disabled_routing_rejects_advisory_and_retains_required(self):
        value = config(); value["capabilities"]["alternate"] = deepcopy(value["capabilities"]["backend"])
        (self.repo / ".codex/orchestrator.json").write_bytes(encoded(value))
        result = route(self.repo, goal="Fix", candidate_ids=["backend", "alternate"], context={}, required_ids=["backend"], session={"routing": {"strategy": "rules_only"}}, advisory={"ignored": True})
        self.assertEqual(result["reason"], "ADVISORY_ROUTING_DISABLED")
        self.assertEqual(result["required_ids"], ["backend"])
        self.assertNotIn("selected_id", result)


class Provision(Fixture):
    def test_partial_observability_update_preserves_existing_limits(self):
        (self.repo / ".codex/jev.json").write_bytes(encoded({"observability": {"enabled": True, "max_records": 100, "max_bytes": 4096}}))
        self.spec["jev"] = {"observability": {"enabled": False}}
        path, digest = self.planned()
        apply(self.repo, path, digest, self.root / "journal")
        value, _ = load(self.repo / ".codex/jev.json")
        self.assertEqual(value["observability"], {"enabled": False, "max_records": 100, "max_bytes": 4096})

    def test_apply_preserves_existing_config_and_jev_observation_fields(self):
        obs = {"enabled": True, "max_records": 100, "max_bytes": 4096}
        (self.repo / ".codex/jev.json").write_bytes(encoded({"enabled": True, "timeout_seconds": 10, "observability": obs}))
        path, digest = self.planned()
        result = apply(self.repo, path, digest, self.root / "journal")
        self.assertEqual(result["status"], "APPLIED")
        data, _ = load(self.repo / ".codex/jev.json")
        self.assertEqual(data["observability"], obs); self.assertEqual(data["timeout_seconds"], 10)
        settings = compile_policy(self.repo)["settings"]
        self.assertIn("backend", settings["capabilities"])
        self.assertEqual(settings["roles"]["worker"]["model"], "gpt-6-luna")
        self.assertFalse((self.repo / ".codex/config.toml").exists())

    def test_stale_config_blocks_all_writes(self):
        path, digest = self.planned()
        target = self.repo / ".codex/orchestrator.json"
        target.write_bytes(encoded({**config(), "routing": {"strategy": "rules_only"}}))
        before = target.read_bytes()
        with self.assertRaisesRegex(ContractError, "STALE_OR_TAMPERED"):
            apply(self.repo, path, digest, self.root / "journal")
        self.assertEqual(target.read_bytes(), before)
        self.assertFalse((self.repo / ".codex/jev.json").exists())

    def test_modified_plan_targets_rejected_even_with_new_hash(self):
        path, _ = self.planned()
        payload, _ = load(path)
        payload["files"][0]["relative"] = "../outside.json"
        path.write_bytes(encoded(payload)); digest = hashlib.sha256(path.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ContractError, "STALE_OR_TAMPERED"):
            apply(self.repo, path, digest, self.root / "journal")

    def test_wrong_hash_and_journal_inside_repo_rejected(self):
        path, digest = self.planned()
        with self.assertRaisesRegex(ContractError, "PLAN_HASH"):
            apply(self.repo, path, "0" * 64, self.root / "journal")
        with self.assertRaisesRegex(ContractError, "CONTROLLER_JOURNAL"):
            apply(self.repo, path, digest, self.repo / "journal")

    def test_partial_failure_restores_own_versions_and_preserves_journal(self):
        path, digest = self.planned(); before = (self.repo / ".codex/orchestrator.json").read_bytes()
        from orchestrator.provision import replace as original
        calls = 0
        def fail_second(target, data):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("injected second write failure")
            return original(target, data)
        with patch("orchestrator.provision.replace", fail_second), self.assertRaises(OSError):
            apply(self.repo, path, digest, self.root / "journal")
        self.assertEqual((self.repo / ".codex/orchestrator.json").read_bytes(), before)
        self.assertFalse((self.repo / ".codex/jev.json").exists())
        self.assertTrue((self.root / "journal/held.json").exists())

    def test_rollback_never_overwrites_concurrent_change(self):
        path, digest = self.planned()
        from orchestrator.provision import replace as original
        calls = 0
        new = encoded({"schema_version": 1, "guidance": []})
        def race(target, data):
            nonlocal calls
            calls += 1
            if calls == 2:
                (self.repo / ".codex/orchestrator.json").write_bytes(new)
                raise OSError("concurrent edit")
            return original(target, data)
        with patch("orchestrator.provision.replace", race), self.assertRaises(OSError):
            apply(self.repo, path, digest, self.root / "journal")
        self.assertEqual((self.repo / ".codex/orchestrator.json").read_bytes(), new)
        held, _ = load(self.root / "journal/held.json")
        self.assertIn(".codex/orchestrator.json", held["rollback_conflicts"])

    def test_manual_recovery_and_tampered_backup_fail_before_writes(self):
        path, digest = self.planned()
        before = (self.repo / ".codex/orchestrator.json").read_bytes()
        journal = self.root / "journal"
        apply(self.repo, path, digest, journal)
        (journal / "before-0.bin").write_bytes(b"tampered")
        after = (self.repo / ".codex/orchestrator.json").read_bytes()
        with self.assertRaisesRegex(ContractError, "RECOVERY_BACKUP_HASH"):
            recover(self.repo, journal, digest)
        self.assertEqual((self.repo / ".codex/orchestrator.json").read_bytes(), after)
        self.assertTrue((self.repo / ".codex/jev.json").exists())
        (journal / "before-0.bin").write_bytes(before)
        result = recover(self.repo, journal, digest)
        self.assertEqual(result["status"], "ROLLED_BACK")
        self.assertEqual((self.repo / ".codex/orchestrator.json").read_bytes(), before)
        self.assertFalse((self.repo / ".codex/jev.json").exists())

    def test_manual_recovery_preserves_concurrent_version(self):
        path, digest = self.planned(); journal = self.root / "journal"
        apply(self.repo, path, digest, journal)
        target = self.repo / ".codex/orchestrator.json"
        target.write_bytes(encoded({"guidance": []}))
        result = recover(self.repo, journal, digest)
        self.assertEqual(result["status"], "HELD")
        self.assertEqual(result["conflicts"], [".codex/orchestrator.json"])
        self.assertEqual(target.read_bytes(), encoded({"guidance": []}))

    @unittest.skipUnless(os.name == "nt", "Windows junction guard")
    def test_junction_target_rejected_before_configuration_read(self):
        outside = self.root / "outside"; outside.mkdir()
        target = self.repo / "junction"
        result = subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(target), str(outside)], capture_output=True)
        self.assertEqual(result.returncode, 0)
        from orchestrator.policy import safe_path
        with self.assertRaisesRegex(ContractError, "REPARSE_PATH"):
            safe_path(self.repo, "junction/config.json")
