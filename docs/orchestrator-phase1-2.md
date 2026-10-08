# ADR / Delivery: Phase 1–2 incremental orchestrator

Overall **PARTIAL**; native execution and observed native review **BLOCKED**. This continuation implements the requested five capabilities in an explicitly separated OFFLINE_TEST realm. It is not a completed production scheduler. Native diagnosis is in [native-sandbox-diagnostics.md](native-sandbox-diagnostics.md).

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
REVIEW → PASSED requires verified fixture review in OFFLINE_TEST
Production REVIEW → PASSED remains BLOCKED pending observed native provenance
```

Dependencies require PASSED plus bound review, receipt and immutable artifact evidence. A three-task dependent DAG can finish with signed synthetic fixtures. No caller boolean, worker or Jev can produce PASSED. Fixture review is never actual Astra review.

## Execution and recovery evidence

`Phase2Queue` extends CoreQueue/Store. `pipeline.mock_attempt()` composes detached worktrees and bounded subprocesses. Windows processes join a kill-on-close Job while suspended, then resume. Runtime is the smaller of caller timeout and task budget; heartbeat uses effective runtime plus 30-second validation grace, capped at 600 seconds.

The fixed controller-owned `constant-json-v1` remains available. `ValidatorRegistry` additionally executes literal argv approved in an external controller-pinned registry, bound to compiled repo validator definitions and policy hash. Executables and fixed scripts are pinned outside worker scope; task data cannot inject commands. Clean environment, Job/process timeout, exit code, output hashes and frozen receipts are checked. Actual execution is restricted to OFFLINE_TEST synthetic validators. Arbitrary project-generated test code remains BLOCKED without native containment.

Artifact manifests verify HEAD, tracked/untracked bytes, exact scope, immutable inputs and expected outputs. Current claim and attempt format are checked before artifact I/O. Published bytes must equal validated hashes, and receipts must bind the resulting manifest. Parent artifacts enter only explicitly declared child inputs with matching hashes, PASSED state and immutable review/manifest binding. Missing, stale, conflicting or tampered artifacts are rejected. Controller-owned storage is hash-detectable and exclusive-create; physical custody is unverified until native sandbox canaries pass.

Recovery fences expired attempts and retains locks until verified cleanup. Missing PID, controller exception or crash is not cleanup proof. Unknown provider completion cannot auto-retry. Continuous `Supervisor` replenishes eligible DAG tasks with at most two synthetic attempts, durable owner lease, queue admission/backpressure and bounded runtime. Cancellation or ownership loss stops and fences work before waiting for executor shutdown. Recovery conservatively holds unknown cleanup; it does not silently rerun it.

Local merge rows remain HELD. Conflict validation clones an independent bare object store, disables inherited Git configuration/hooks/drivers/lazy fetch/replacements and limits all Git subprocess output/time. Candidate regular-file blobs and exact changed paths must match reviewed artifacts. `merge-tree --write-tree` writes objects only in the isolated clone, without changing source HEAD/index/worktree. CLEAN is conflict evidence, never merge permission. `merge()` rejects even caller-supplied authorized=True.

## Trusted review contract

Controller bootstrap pins a registry outside the reviewed repo, installed OpenSSL executable and public keys. Detached SHA-256/RSA signatures authenticate the registered key; the importer never loads private keys. Challenges bind queue UUID, immutable production/OFFLINE_TEST realm, registry/policy hash, task/attempt/epoch, receipt/manifest hash, purpose, expiry and one-shot nonce. Import consumes the nonce and changes state atomically; duplicate, unknown, modified, cross-queue, stale or low-model/effort evidence is rejected. Repo-strengthened Astra effort is retained.

Identity authenticity, actor independence and observed model provenance are separate claims. `offline_fixture` keys can release only OFFLINE_TEST. Production requires a native attester and still unconditionally rejects `REQUIRED_NATIVE_REVIEW_PROVENANCE_UNAVAILABLE`: a valid signature plus a claimed model name cannot establish a real independent Astra run. Trust enrollment, native execution ledger and controller-root custody are still blockers. No production key or auto-approval broker was installed.

Added durable tables: evidence_binding, artifact_manifests, review_challenges, reviews, validator_binding and supervisor_lock. Controller-owned frozen snapshots, validator output/receipts and merge evidence complement the existing SQLite events. Policy/source hashes intentionally require explicit migration after source changes.

## Previous checkpoint test results, 2026-10-08

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

Use fresh smoke run roots. Queue reopen needs the same source/config/session binding; drift requires deliberate migration. `phase2-expire` fences only and never clears locks. `phase2-status` may initialize a missing DB through its constructor; it is not a completely read-only command. Production/native dispatch is unavailable. Explicit OFFLINE_TEST `phase2-supervise-mock` runs synthetic workers and pinned synthetic validators; it does not automatically sign or approve reviews.

New operator commands are `phase2-review-challenge`, `phase2-import-review`, `phase2-supervise-mock` and `phase2-merge-check`. All accept explicit `--evidence-mode`, `--review-registry` and `--registry-sha256`; these must match the queue's immutable initial binding. Production is the default. Existing production queues cannot silently become OFFLINE_TEST. External trust registry enrollment is a controller/bootstrap responsibility, not a task or worker action. `--help` lists exact arguments.

For an already provisioned synthetic fixture queue (not an arbitrary development repo):

```powershell
python -B -m orchestrator phase2-supervise-mock --repo '<fixture-repo>' --database '<external controller DB>' --run-root '<fixture run root>' --evidence-mode OFFLINE_TEST --review-registry '<pinned external registry>' --registry-sha256 '<hash>' --validator-registry '<pinned validator registry>' --validator-sha256 '<hash>' --max-active 2 --max-seconds 30
python -B -m orchestrator phase2-review-challenge --repo '<fixture-repo>' --database '<same DB>' --evidence-mode OFFLINE_TEST --review-registry '<same registry>' --registry-sha256 '<hash>' --task-id '<task>'
python -B -m orchestrator phase2-import-review --repo '<fixture-repo>' --database '<same DB>' --evidence-mode OFFLINE_TEST --review-registry '<same registry>' --registry-sha256 '<hash>' --envelope '<signed fixture envelope>'
python -B -m orchestrator phase2-merge-check --repo '<fixture-repo>' --database '<same DB>' --evidence-mode OFFLINE_TEST --review-registry '<same registry>' --registry-sha256 '<hash>' --task-id '<task>' --integration-repo '<integration fixture>' --integration-head '<40hex SHA>' --candidate-head '<40hex SHA>'
```

## Continuation verification — 2026-10-08

| Actual command / check | Result | Evidence / limit |
|---|---|---|
| `python -B -m unittest discover -s orchestrator_tests -v` | PASS, 93 tests / 31.895s | `runs/orchestrator-completion-final-20261008.txt` |
| Root Jev command from `tests/README.md` | PASS, 77 tests / 3.539s | `runs/jev-completion-20261008.txt`; no provider |
| `python -B -m unittest test_inventory` in payload/jev | PASS, 12 tests / 0.018s | `runs/inventory-completion-20261008.txt` |
| Completion/adversarial subset | 18 included in 93 | Signature spoof/replay/expiry/concurrent/cross-queue, artifact/receipt drift, DAG inputs, cancel/restart/lost supervisor ownership, validator exit/timeout, merge conflicts and existing CLI response compatibility |
| CLI `phase2-supervise-mock --help` | PASS parsing | The full lifecycle is exercised through API integration tests, not a production CLI run |
| Actual independent native Astra task review | BLOCKED / NOT_RUN | Signed fixtures assert synthetic fields; production importer rejects even a valid attester signature |
| Native worker smoke | NOT_RUN this continuation; prior preflight failed | Separate native diagnostic; no loosened controls |
| Actual local/remote merge | NOT_RUN | Executor is disabled; only isolated object-store conflict validation runs |

The first full candidate run had 1 failure and 2 errors (83 tests). After correcting Windows text newline drift and security findings, a targeted run exposed a missing test import and overly restrictive local-clone transport. Both were fixed, the targeted eight-test set and full 92-test set passed. Final diff inspection restored the existing CLI `executed=False` response field and added a compatibility check; the final source passed 93 tests. Earlier failures are not counted as passing runs.

The new signed fixtures generate disposable synthetic keys under ignored `.test-runs`; no private key, production registry, credentials, SQLite queue or runtime evidence is tracked. Independent architecture/security reviewers read the source and saved test evidence; they did not independently rerun tests or act as counted worker reviewers. Security closure accepts only OFFLINE_TEST and production fail-closed boundaries. Original Global production runtime and Jev payload are unchanged.

## KEEP / MODIFY / ADD

| Action | Scope |
|---|---|
| KEEP | Jev payload, model roles, sandbox/auto-review, required review, original tests/worktrees |
| ADOPT | Existing contracts/CoreQueue/Store/policy/routing/workspace/Job source and deterministic tests |
| MODIFY | Candidate durable uncertainty, policy provenance/source hashes/acceptance floors, queue operator API |
| ADD | Phase2Queue lifecycle, fixed mock pipeline/manifest, phase2 tests, benchmark plan/descriptive scorer, ADR |
| REMOVE | Nothing |

## Production admission continuation — 2026-10-08, after App recovery

**Overall PARTIAL; Production Admission BLOCKED.** Extend the existing
challenge/importer/registry rather than introduce a new approval framework.
This checkpoint adds usable diagnostic and preflight APIs; it does not release
native dispatch, production review/validators or merge. Phase 3 remains closed.

| Component | Implemented and verified | Admission status |
|---|---|---|
| App tool sandbox | PowerShell starts after external recovery; App 26.930.7945.0, bundled CLI 0.160.1 | App tool observation, not worker proof |
| Native readonly preflight | Official npm 0.161.0 command/exec reproduces root-read rejection in credential-free isolated config | BLOCKED; no requested command execution |
| Review runtime ledger | Challenge/task/attempt/epoch/policy/artifact/receipt binding; immutable diagnostic receipt, restart/idempotent/orphan handling | DONE as diagnostics; official execution provenance BLOCKED |
| Production importer | Missing execution receipt, hash mismatch and configured-metadata rejection; durable rejection audit outside failed transaction | BLOCKED even with valid synthetic native-attester signature |
| Validator preflight | Complete registry/config/file/executable hash and literal argv checks; production blocked receipt/event, pre-cancel fence | DONE preflight; production command execution BLOCKED |
| Real DAG → worker → validator → independent review → PASSED | Necessary native/reviewer conditions missing | NOT_RUN / BLOCKED |

`Phase2Queue.record_review_runtime(target, started, completed)` accepts the
shape of thread-start metadata and turn-completion metadata. Its source is
explicitly `UNVERIFIED_CALLER_SUPPLIED_APP_SERVER_METADATA`. It stores only
bounded allowlisted metadata and fixes observed_model/observed_effort to null;
caller `trusted` flags, extra model claims and assistant text cannot change
that. This is a diagnostic receipt, not a reliable execution receipt or signed
provider attestation. Current installed protocol does not expose the required
observed per-turn model/effort. The production hard reject remains unconditional.

The `review_runtime` SQLite table and frozen `review-runtime/<nonce>.json`
bind the diagnostic to the existing one-shot challenge. Import still rechecks
expiry/current state/artifacts and does not consume the nonce on rejection.
Rejection records contain only hashes/reasons under `review-admission/`, with
corresponding durable events. Existing detached-signature verification is
retained; disposable synthetic signatures prove rejection mechanics, not a
real Astra review or production reviewer identity. No attester was enrolled.

`ValidatorRegistry.plan(claim, workspace)` checks the full pinned command
chain without execution and returns execution_authorized=false. Production
`run()` records `NOT_RUN/BLOCKED` evidence and raises before process launch.
OFFLINE_TEST retains real bounded execution of fixed synthetic validators,
rechecks every pin/lease before launch, checks pre-cancellation before spawning,
and binds execution receipts to queue/task/attempt/epoch/policy/plan hashes.
Executable hashes do not solve custody or replacement races; native OS
containment remains a prerequisite for worker-generated test code.

The existing synthetic CLI plan now rejects a root-level named default
permissions configuration when no legacy sandbox_mode is configured. This
avoids silently replacing that profile with its legacy workspace-write flags.
It is **not** full effective-layer resolution: repo/profile/managed layers
remain UNVERIFIED, and the plan remains HELD. Existing model roles are unchanged.
Source fingerprints include the new admission module; existing queues need
deliberate policy/source migration rather than a silent source-binding update.

Actual final regression commands from this worktree:

| Command | Actual result | Retained evidence |
|---|---|---|
| `python -B -m unittest discover -s orchestrator_tests -v` | PASS: 105 / 26.696s | `runs/production-admission-full-20261008.txt` |
| `python -B -m unittest test_response_diagnostics test_decision test_phase2a test_resources test_combined test_inventory_safety` | PASS: 77 / 2.761s | `runs/production-admission-jev-20261008.txt` |
| `python -B -m unittest test_inventory` from payload/jev | PASS: 12 / 0.018s | `runs/production-admission-inventory-20261008.txt` |

Total **194** tests; baseline was 182. The 12 added tests cover production
receipt binding/no-PASS, forged signature rejection audit, missing/mismatched
metadata, receipt tampering, expiry/cross-queue/drift, restart/orphan recovery,
production validator no-host-fallback, literal argv/executable drift, cancellation,
stale attempts and named-profile root-config rejection. Existing restart/DAG/
supervisor-interruption/merge-conflict tests were rerun in the full suite.
No test is counted as native sandbox, actual model review or real E2E PASS.

Independent architecture and security reviewers inspected the scoped code/test
diff. Architecture accepted only the fail-closed increment; security found no
new production PASS/execute/merge bypass and requires follow-up for native
custody, actual reviewer provenance and complete effective-layer validation.
They did not independently run tests or act as counted task reviewers. Local
merge execution and remote actions remain disabled. Details and minimum
compatible repair are in [native-sandbox-diagnostics.md](native-sandbox-diagnostics.md).

KEEP: model roles, Jev adapter, original tests, review/sandbox/auto-review floors.
MODIFY: importer rejection evidence, validator preflight and CLI plan guard.
ADD: diagnostic runtime ledger, admission receipts/events and 12 tests.
REMOVE: nothing. No Global production runtime or capacity setting was changed.
No live background scheduler/worker was installed. Phase 3 entry conditions
are still not met; there is no pending request to enable routing or benchmark.

## Remaining acceptance and blockers

- DONE: custom configuration composition/provenance; tested durable lifecycle primitives; B exact-capability routing without Jev; bounded single mock attempt/evidence; review/merge rejection gates.
- DONE in OFFLINE_TEST: trusted fixture importer, accepted dependency snapshots, continuous bounded supervisor, pinned synthetic command validators and isolated local merge conflict validation.
- PARTIAL: full Rule-Based Orchestrator. Observed native review importer and production repo validators are not released; no shared cross-queue native slot ledger exists. The two-task cap is per controller, not authorization to run multiple controllers with native children.
- BLOCKED: native CLI isolation/admission and real worker smoke under the current Windows runtime/profile. Worktree/Job/diff checks cannot replace actual worker-token filesystem/network/controller-custody canaries.
- NOT STARTED: live E adapter, larger-worker capacity authorization and full B/E worker benchmark. Remote merge executor is intentionally excluded.

The native provenance/custody gaps remain distinct from completed synthetic source paths. Overall Phase 1–2 remains unaccepted until real smoke and required independent native review are verified. No background worker/scheduler is installed. Phase 3 entry conditions are not met.

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
