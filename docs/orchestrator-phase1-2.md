# ADR / Delivery: Phase 1–2 incremental orchestrator

Overall **PARTIAL**; native execution **BLOCKED**. Configuration/control-plane and a bounded mock attempt are implemented and tested. This is not a completed production scheduler.

## Architecture and reuse

User → Sol planning → immutable Task DAG → deterministic queue/admission → optional Jev semantic advice → isolated attempt → controller validation → required independent review → local merge queue.

Adopt the existing stdlib/SQLite CoreQueue, policy compiler, contracts, routing, worktree allocator and Windows Job Object. Extend their storage rather than create a second queue framework. The adopted source is now in this integration repo; installed Global source is unchanged. The old v1 synthetic driver remains for compatibility and is separate from the Phase 2 API.

The existing published Jev MCP payload and model roles remain intact. This phase does not install globally, change production config, push, create a PR or execute a merge.

## Effective Configuration Matrix

Custom namespace: packaged `orchestrator/defaults.json` → explicit repo `.codex/orchestrator.json` → explicit session JSON → compiled floors. These are controller settings, **not native Codex configuration**.

| Setting | Defaults | Repo/session | Immutable boundary |
|---|---|---|---|
| Worker model/effort | Existing Sol/medium role | Legal named model/effort overrides | Task execution equals compiled capability role |
| Research | Existing Luna/medium | Legal overrides | No observed model switch claimed |
| Review | Existing Astra/high | Repo may strengthen; session cannot lower repo effort | Required independent Astra, minimum high |
| Jev | Existing optional routing default | May disable; B uses rules_only | No permission/review/merge authority |
| Active tasks | 2 per queue | 1–2 | No active children increase |
| Acceptance | Registered validators | Repo may strengthen; session cannot remove or replace repo validators | Validator argv is data, not an execution grant |
| Owned files | Registered exact paths | Session can narrow existing scope | No protected metadata/wildcard/traversal/reparse paths |
| Live/external writes/merge | Closed | Cannot enable | Independently verified admission required |

`compile_policy()` provides source paths/hashes, per-field `field_sources`, compiled floor source, module fingerprints, repo identity and policy hash. Queue reopen rejects source/policy/repo drift. Native effective model/sandbox remains UNVERIFIED; requested flags are not observed enforcement. Main-session defaults and worker-role defaults are distinct.

## Contract and durable model

Reuse strict schema v2. Phase 2 also accepts schema v3 with the requested field names: `task_id`, `goal`, hashed `inputs`, `dependencies`, `allowed_files`, `capability`, `expected_artifacts`; `model_policy` maps to v2 execution, `acceptance={criteria,validators}` to criteria/tests, and `retry_budget={runtime_seconds,attempts}` to budgets. Attempts include the first attempt. Existing `base_sha`, `resource_locks`, authorization and required independent review fields remain mandatory.

Normalization precedes complete-DAG validation. Missing dependencies, cycles, ownership/model/review violations and task ID content drift are rejected before insertion/claim.

SQLite tables: tasks (contract/hash/state/epoch/attempt ID/count/expiry/receipt/reason/provider_unknown), locks, immutable budget, append-only events, controller_binding, phase2_binding and merge_queue. Transactions use BEGIN IMMEDIATE. Claim identity binds task/contract hash/attempt UUID/epoch/nonexpired lease. Provider intent is durable and one-shot; unknown completion cannot be forgotten on restart or parameter omission. No trusted terminal-event importer clears uncertainty yet.

```text
PENDING → READY → CLAIMED → RUNNING → VALIDATING → REVIEW
                                  ↘ HELD       ↘ FAILED
HELD → CANCELLED after verified process-tree cleanup
HELD → PENDING only for known-safe retry within budget
REVIEW → PASSED requires trusted independent review (NOT IMPLEMENTED)
```

Dependencies require PASSED. No caller boolean, worker or Jev can produce it. The full dependent DAG therefore cannot finish in this candidate; this is a missing feature, not a successful review.

## Execution and recovery evidence

`Phase2Queue` extends CoreQueue/Store. `pipeline.mock_attempt()` composes detached worktrees and bounded subprocesses. Windows processes join a kill-on-close Job while suspended, then resume. Runtime is the smaller of caller timeout and task budget; heartbeat uses effective runtime plus 30-second validation grace, capped at 600 seconds.

The v2 executable validator is fixed controller-owned `constant-json-v1`, which parses typed JSON answer 42. It never imports worker code or runs repo-provided validator argv. General project validators remain unimplemented.

Artifact manifests verify HEAD, tracked/untracked bytes, exact scope, immutable inputs and expected outputs. Bytes are frozen into controller evidence with exclusive creation and rehashed before fenced publication. Missing input snapshots are rejected; parent-artifact integration is not implemented.

Recovery fences expired attempts and retains locks until verified cleanup. Missing PID, controller exception or crash is not cleanup proof. Unknown provider completion cannot auto-retry. Local merge rows bind receipt hash and remain HELD. `merge()` rejects even a caller-supplied authorized=True. No local integration-branch application or conflict dry-run exists yet.

## Test results, 2026-10-08

| Check | Result | Practical limit |
|---|---|---|
| Orchestrator tests | PASS: 75 | Offline/mock; includes 1000-task queue/DAG, race, fencing, restart, timeout, policy/review gates |
| Original Jev source tests | PASS: 77 | No provider inference |
| Original inventory tests | PASS: 12 | Offline |
| Real mock process/worktree/manifest | PASS | Not native sandbox evidence |
| Timeout Job cleanup and stale callback | PASS in tests | Not provider-side cancellation |
| Native CLI 0.161.0 readonly preflight | BLOCKED, exit 1 | elevated Windows sandbox requires effective :root read access |
| Real Codex worker smoke | NOT_RUN | Native admission closed |
| Trusted task review/full DAG/local merge validation | NOT_RUN | Source gaps |
| Remote CI/20-worker benchmark | NOT_RUN | Outside this phase |

App package was observed as 26.1002.7124.0. Global config still requests Sol/xhigh, workspace-write, on-request and auto_review; these settings do not prove a launched worker's effective controls. Jev status was callable and advisory; no inference request was made.

Native preflight used the existing readonly profile and managed config; no read grants, ACLs or global settings were expanded. Tool sandbox also encountered helper_sandbox_lock_failed. Scoped reads/tests used auto-reviewed host commands; this does not prove worker isolation. One log command had an incorrect cwd and failed; corrected root invocation produced the final 75-test log. Failed invocation is not counted as PASS.

Evidence remains under ignored runs/ and .test-runs/. Final architecture/security review accepted only this PARTIAL boundary after runtime/uncertainty findings were fixed. Reviewers inspected source and existing logs, without independently rerunning tests. Evidence/run records and worker snapshots are not committed.

## Operational commands

From this worktree root, Python 3.12+:

```powershell
python -B -m unittest discover -s orchestrator_tests -v
python -B -m unittest test_response_diagnostics test_decision test_phase2a test_resources test_combined test_inventory_safety
python -B -m orchestrator.pipeline --run-root "$PWD/runs/phase2-valid-new"
python -B -m orchestrator.pipeline --run-root "$PWD/runs/phase2-timeout-new" --behavior timeout
python -B -m orchestrator effective --repo '<explicit repo>' --session '<explicit session JSON>'
python -B -m orchestrator phase2-enqueue --repo '<repo>' --database '<controller-owned external SQLite path>' --tasks '<v2/v3 task list JSON>'
python -B -m orchestrator phase2-status --repo '<repo>' --database '<same SQLite path>'
python -B -m orchestrator phase2-expire --repo '<repo>' --database '<same SQLite path>'
```

Use fresh smoke run roots. Queue reopen needs the same source/config/session binding; drift requires deliberate migration. `phase2-expire` fences only and never clears locks. `phase2-status` may initialize a missing DB through its constructor; it is not a completely read-only command. Queue CLI does not dispatch/validate workers.

## KEEP / MODIFY / ADD

| Action | Scope |
|---|---|
| KEEP | Jev payload, model roles, sandbox/auto-review, required review, original tests/worktrees |
| ADOPT | Existing contracts/CoreQueue/Store/policy/routing/workspace/Job source and deterministic tests |
| MODIFY | Candidate durable uncertainty, policy provenance/source hashes/acceptance floors, queue operator API |
| ADD | Phase2Queue lifecycle, fixed mock pipeline/manifest, phase2 tests, benchmark plan/descriptive scorer, ADR |
| REMOVE | Nothing |

## Remaining acceptance and blockers

- DONE: custom configuration composition/provenance; tested durable lifecycle primitives; B exact-capability routing without Jev; bounded single mock attempt/evidence; review/merge rejection gates.
- PARTIAL: full Rule-Based Orchestrator. Continuous replenishment supervisor/shared cross-queue slot ledger, dependency artifact snapshots, general project validators, trusted review importer and conflict-tested local merge validation are source gaps.
- BLOCKED: native CLI isolation/admission and real worker smoke under the current Windows runtime/profile. Worktree/Job/diff checks cannot replace actual worker-token filesystem/network/controller-custody canaries.
- NOT STARTED: live E adapter, larger-worker capacity authorization and full B/E worker benchmark. Remote merge executor is intentionally excluded.

These source gaps are separate from the native sandbox failure. Overall Phase 1–2 remains unaccepted until required features and real smoke are verified. No background worker/scheduler is installed.

## Phase 3 Jev adapter

Keep payload/jev/decision.py and its bounded MCP API. Code filters legal capability/availability/scope first. Only multiple semantically ambiguous legal candidates may reach a single hash-bound sanitized advisory request. Revalidate candidate/current policy before dispatch; deterministic fallback or explicit ambiguity hold. Jev outage cannot lower review or block unambiguous B work.

Persist intent/outcome/circuit state and provenance. Written Jev observations require corresponding outcome reports. Jev cannot approve tests, grant permissions, produce PASSED, waive review or merge. Live calls need fresh admission and bounded request/transmission authorization.

## Phase 4 B vs E commands and limits

Actual executable planning/scoring commands; no worker/provider launch:

```powershell
python -B -m orchestrator.benchmark plan --output "$PWD/runs/phase4-plan-new.json"
python -B -m orchestrator.benchmark score --baseline '<B result list JSON>' --experiment '<E paired result list JSON>' --output "$PWD/runs/phase4-description-new.json"
```

Results require task_id, dag_id, contract_hash, worker_policy_hash, completed, harmful_assignment, tokens, wall_seconds, retry_count, escalated, merge_conflicts, jev_adopted, routing_correct and hard_policy_bypass. Paired IDs/policies/contracts must match, numeric metrics must be finite and counters integer. Keep failed/incomplete tasks in both arms.

Plan: 400 heterogeneous tasks (80 development/240 heldout/80 stress), three paired repetitions, DAG as inference cluster. Freeze scheduler/DAG/worker models/efforts/tools/validators/review. Independently label acceptable candidates and record full-run wall-clock separately from summed per-task times.

Proposed thresholds: harmful misassignment improves at least 20% relatively; completion noninferiority margin 3 percentage points; adopted Jev accuracy at least 95%; zero hard-policy bypasses. Scorer is DESCRIPTIVE_ONLY and cannot establish Go/No-Go without clustered uncertainty/blinded labels/coverage/run metadata. Zero baseline harm or zero adopted decisions cannot prove value.

The twenty-worker live launcher is NOT IMPLEMENTED. No fabricated execution command bypasses the active cap. Full benchmark driver follows native isolation, shared admission, review/snapshot/general-validation features, E adapter and explicit capacity authorization. No Jev improvement is claimed.

## Official references

- [Non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode): supported CLI/JSONL interface instead of private App APIs.
- [Windows sandbox](https://learn.chatgpt.com/docs/windows/windows-sandbox): native OS isolation must be verified independently.
- [Permissions](https://learn.chatgpt.com/docs/permissions): effective permissions/managed constraints remain authoritative.
