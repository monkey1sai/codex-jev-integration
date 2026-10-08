# ADR / Delivery: Phase 1–2 incremental orchestrator

Overall **PARTIAL**; production native execution and observed native review **BLOCKED**. The later diagnostic Linux smoke executed real tools and changed its fixture, but failed its boundary gate; no artifact was accepted. This continuation implements the requested five capabilities in an explicitly separated OFFLINE_TEST realm. It is not a completed production scheduler. Native diagnosis is in [native-sandbox-diagnostics.md](native-sandbox-diagnostics.md).

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

### Isolated Linux admission continuation — 2026-10-08

The Windows failure was not retried. Current App is 26.930.7945.0, bundled
CLI 0.160.1, npm CLI 0.161.0. Existing Ubuntu 24.04.4 on WSL2 2.6.3.0 is
available; kernel 6.6.87.2-microsoft-standard-WSL2. Its default user has sudo
and docker memberships and its Windows drive is writable, so WSL alone is
not the boundary. The test repo and runtime are on its ext4 filesystem.

Official rust-v0.161.0 Linux musl CLI and its separately published bwrap were
installed only into a newly owned isolated test directory, with release API
SHA-256 digests checked. No production install/config or system ACL changed.
The binary-only asset lacks bwrap. Minimal-read also needs the nonstandard
isolated runtime bin directory explicitly readable. These two compatibility
fixes produced actual native command execution, without root-read grants.

An attempted file-only writable rule failed before execution with bwrap
ENOTDIR (synthetic `.git`/`.aws` descendants under the filename). The final
fixture uses a dedicated artifact directory instead; repo/tests/Git are
read-only, only artifact and private scratch directories writable. Its new
CODEX_HOME uses `never` to reject scope expansion and unsandboxed retries;
`approvals_reviewer=auto_review` remains configured. This stricter one-shot
setting is not a Global policy change and does not claim an approval occurred.
Fresh ephemeral exec has no resume/fork/sticky grants, ignores exec rules,
and disables children, permission requests, hooks, plugins, MCP/apps,
remote tools and the CLI's automatically seeded builtin skills.

| Admission item | App bundled Windows | npm Windows | Isolated Linux candidate |
|---|---|---|---|
| CLI version starts | VERIFIED 0.160.1 | VERIFIED 0.161.0 | VERIFIED 0.161.0 |
| Configured worker model/effort | UNKNOWN for a live worker | UNKNOWN for a live worker | VERIFIED config: Sol/medium; provider-observed identity UNKNOWN |
| Native isolation | UNKNOWN; version-matched check rejects this policy | BLOCKED by retained root-read error | Native namespaces/seccomp VERIFIED for canaries |
| Scoped read/write | UNKNOWN | UNKNOWN | Legal reads/private writes succeed; controller/other-worktree/home canaries hidden |
| Git/runtime protection | UNKNOWN | UNKNOWN | `.git` and runtime bin writes EROFS |
| Credentials/secrets | UNKNOWN | UNKNOWN | Actual isolated-home fake secret and fixture `.env` denied; official login status exit 0 |
| Windows/privileged host channels | UNKNOWN | UNKNOWN | `/mnt/c`, `/init`, binfmt unavailable; `/run/WSL` empty; AF_UNIX/TCP EPERM |
| Cancel, timeout, controller interruption | UNKNOWN | UNKNOWN | VERIFIED native fork/setsid and actual host cleanup in separate user cgroup tests |
| Failure and fresh process restart | UNKNOWN | UNKNOWN | Native exit 7 retained; subsequent command succeeds |
| Artifact custody | UNKNOWN | UNKNOWN | Bounded scan/pins implemented; first real attempt produced no artifact |
| Real model worker | NOT_RUN | NOT_RUN | One real turn completed; modification/acceptance FAILED; no retry |

The original process-group-only cancellation left native sandbox descendants.
They later exited naturally; this is retained as FAIL, not retroactive PASS.
Existing systemd user transient cgroups supply KillMode=control-group and an
independent deadline. Actual cancellation/timeout/controller-interruption
tests include detached descendants and verified empty namespaces afterwards.
Cgroups manage lifecycle; official bubblewrap/seccomp still enforce isolation.
No daemon, persistent scheduler or capacity increase was installed.

`tools/linux_worker_smoke.py` is a single authorized synthetic smoke, separate
from the production queue. It validates pinned binaries/config/acceptance,
semantic canary results, current cgroup receipts and official login status.
An exclusive root-owned controller intent prevents repeat model execution.
Bounded logs and file scans protect the controller; actual ControlGroup must
match the observed unit. A static AST gate limits this tiny add-function
contract before execution; native validation makes artifact read-only and
requires unchanged bytes/tree before custody. It is not a generic Python
validator. No caller metadata, CLI exit or stdout marker grants production
PASS or counted independent review.

Readiness (inside Linux; this does not authorize another model request):

```sh
python3 -B tools/linux_worker_smoke.py --root <isolated-root> --evidence <owned-evidence-directory>
# The original --execute budget has been consumed. The retained intent blocks reuse.
```

Local ignored evidence: `runs/wsl-worker-20261008/` contains release pins,
actual argv, effective-config-admitted.json, cgroup-lifecycle-admitted.json,
mutation-final-execution.json and output-final-execution.json. Final config
SHA-256 before the first model: f39081db3a690a9a8e5e8254bcd47cbac732ece85bda47defe3a5acac97f0d7b.
Prior failed receipts remain. No credentials are included or copied.

Pre-execution regression results: existing 105 orchestrator, 77 Jev and 12
Inventory tests all passed; four new guards passed (198 total).
Actual native canaries are separate evidence, not mock worker results.
Independent security review accepted the final bounded smoke design after
fixing marker spoof, self-mutation and cgroup identity gaps. User's default-home CLI screenshot (Sol/low)
does not establish this isolated home's login, medium effort or containment.
The later official status check in the exact isolated environment returned
exit 0 and the runner returned READY_NO_MODEL_LAUNCHED. That one-worker
authorization was then consumed by the real attempt below.

### First real attempt and mandatory host repair

Checkpoint 52c8cb99fe66fa06141584593b2951801b7534a1 preceded the model.
One fresh ephemeral `codex exec --strict-config --ignore-rules --json`
with Sol/medium completed real thread `01a11a1c-2581-7311-ad7b-4a142dacb24d`.
Usage: input 21266, cached input 8832, output 167, reasoning output 59.
CLI exit 0 and `turn.completed` establish an inference turn, not task success.
No file changed; the validator was NOT_RUN. Overall smoke result is
`FAILED_OR_UNKNOWN_NO_RETRY`, production/review flags remain false.

Cause: the controller incorrectly disabled the mandatory `code_mode_host`
feature. The engine explicitly reported Code Mode unavailable and requested
the official host. This was a tool-runtime compatibility failure, not evidence
of model task quality or sandbox failure. The original exclusive intent and
failed receipt are retained; no automatic second model request was made.

The same-version official host release archive SHA-256 is
30cc945f77b3eed15ee385cc2f844a33bf1d7c422ff3a97161f701bffe4f77f8;
ELF SHA-256 is e87096087c02aa6ab90a5a85031659665aa0bf3ee20c07ca0b8ab701c83fcd5b.
Official install-context source resolves the helper beside this custom CLI.
Only the isolated home's feature was changed to true; its prior config was
preserved. New config SHA-256:
53ba30443ce753d840150c2b669285470c8ce9a85d42ece17750dfa5e24ee081.
Never, auto_review, Sol/medium, native permissions, network denial, disabled
children/skills/plugins/MCP and all production policy floors remain in place.

Actual no-provider stdio host tests verified pure JS output, unavailable
process/require/fetch/Deno/Bun globals, static/dynamic import rejection and
unknown-tool rejection. This is HOST_PROTOCOL_ONLY. No successful shell
callback was fabricated; the CLI's full model-to-ToolCallRuntime chain remains
NOT_YET_VERIFIED. Source review shows callbacks return to that policy path.
The host itself is a trusted native V8 process, not an OS-sandboxed task shell;
source/API checks cannot rule out native runtime vulnerabilities.

Existing transient user cgroups now enforce kernel memory.max=1073741824,
memory.swap.max=0 and pids.max=64, with exact observed ControlGroup binding.
These are process/thread resource limits, not permission to add agent children.
Actual host PID/executable/group were observed for cancel, timeout and
controller interruption; all three left no cgroup processes. The same config
also passed native canaries, lifecycle, exit-7 failure and fresh-process restart.
No stress allocation, production service or other user session was touched.

Evidence: `smoke-result.json`, `worker-events.jsonl`, `code-host-candidate.json`,
`effective-config-code-host.json`, `cgroup-lifecycle-code-host.json`,
`host-protocol-execution.json`, `host-protocol.jsonl`,
`host-lifecycle-result.json` and `code-host-readiness.txt` under the same ignored
run directory. The last readiness exits 2 with
PREPARED_REEXECUTION_REQUIRES_NEW_AUTHORIZATION and provider_launches=0.
One additional explicit attempt authorization is needed before re-execution;
it must use separate evidence/intent and preserve the original failure.

After the host repair, actual regression reruns passed: `python -B -m unittest
discover -s orchestrator_tests -v` (110 tests, 28.731s), the root Jev command
in `tests/README.md` (77 tests, 2.687s), and its payload Inventory command
(12 tests, 0.015s). Total 199, retaining the original 194 and five guards.
Final logs are `runs/wsl-admission-*-final-20261008.txt`. These offline tests
remain separate from actual native/host probes and the failed real model.
Independent security source/evidence review accepted this preparation scope,
without granting production review or another provider attempt. Its cleanup
finding was addressed by continuing evidence collection after a stop command
timeout/error and retaining CLEANUP_UNVERIFIED. That infrastructure exception
path was source-reviewed but not injected in a runtime test.

Reviewer assurance: controller can bind executable/config/argv/process/
artifact facts to this attempt; caller claims and assistant text are not
provider attestation. Installed Thread model/reasoningEffort describe
configured state, not authenticated per-turn execution. Actual provider
model/effort remain UNKNOWN. Production reviewer, validators, native queue
dispatch and merge acceptance stay blocked; a future smoke cannot unlock
them or Phase 3 by itself.

- DONE: custom configuration composition/provenance; tested durable lifecycle primitives; B exact-capability routing without Jev; bounded single mock attempt/evidence; review/merge rejection gates.
- DONE in OFFLINE_TEST: trusted fixture importer, accepted dependency snapshots, continuous bounded supervisor, pinned synthetic command validators and isolated local merge conflict validation.
- PARTIAL: full Rule-Based Orchestrator. Observed native review importer and production repo validators are not released; no shared cross-queue native slot ledger exists. The two-task cap is per controller, not authorization to run multiple controllers with native children.
- BLOCKED: Windows native worker under the current policy; production review/provenance, validators and end-to-end admission. The latest Linux diagnostic worker made the expected modification, but its live boundary gate failed and controller validation/acceptance remain incomplete.
- NOT STARTED: live E adapter, larger-worker capacity authorization and full B/E worker benchmark. Remote merge executor is intentionally excluded.

The native provenance/custody gaps remain distinct from completed synthetic source paths. Overall Phase 1–2 remains unaccepted until real smoke and required independent native review are verified. No background worker/scheduler is installed. Phase 3 entry conditions are not met.

## Newly authorized real smoke — 2026-10-08

Base checkpoint: `8d26fb9302dd5895bfa426927c4a60e6ba4fcc97` on
`feat/orchestrator-phase1-2`. **Smoke FAIL; Production Admission BLOCKED.**
The explicit authorization allowed one additional CLI worker, not a retry of
the original failed intent. Original intent/result/events hashes were checked
before and after this attempt and remain unchanged.

`tools/linux_worker_attempt.py` extends the existing smoke helper without
changing production dispatch. A separate exclusive controller intent binds
attempt `87c1e1d5-9186-4ed7-b006-4e780ec41980`, its public challenge, baseline
snapshot, allowed file, literal argv and runtime pins. Never recreating that
slot enforces no redispatch after failure or unknown completion. Its budget
is now consumed. This is a controller-owned slot, not root-UID ownership.

The parser uses only outer CLI JSONL frames, matches the full fixed canary
command, pairs command starts/completions, binds the thread and challenge,
and rejects failed, incomplete or replayed commands. Agent text and nested
stdout cannot supply event provenance. A non-accepted candidate is verified
before final PASS can be written; a failed verification leaves a failed final
receipt. Production/review flags are always false. Six adversarial guards
include a verifier-failure test of the actual candidate/final file writes.

Zero-provider preflights exposed CLI scrubbing of externally injected session
metadata and the fixed Bash command's observed `SHLVL=0`. Original assertion
failures were retained. Rechecking the same native receipt, with independent
architecture review, accepted only that exact shell value. Controller-injected
metadata is explicitly not a model tool event. Live failure guards were not
relaxed after dispatch.

One real execution used pinned CLI 0.161.0, the pinned same-version official
Code Mode Host and configured `gpt-6.1-sol / medium`. Its argv is in
`dispatch-intent-copy.json` and `worker-events-execution.json`; the operator
invocation was `wsl.exe --distribution Ubuntu-24.04 --exec /usr/bin/python3 -B`
followed by the ignored run's `invoke_attempt.py --execute`. There was no
second invocation. Thread: `01a11a68-72d1-7d80-b9d8-33e381a1cfb2`.

| Evidence | Actual result | Acceptance |
|---|---|---|
| `item_2`, fixed Python boundary command | Real command start/completion, exit 0; thread/challenge match | Tool execution VERIFIED; boundary FAIL |
| Live login-home write canary | `credential_home_write.access=ALLOWED` | Violates the required deny assertion; no smoke PASS |
| Controller/other-worktree/home reads, Git/bin writes, sockets/TCP | Expected deny results in the live canary | Verified for these specific operations only |
| `item_4`, file change | Actual patch of `artifact/mathutil.py`; controller snapshot confirms sole changed path | Scope VERIFIED, artifact NOT_ACCEPTED |
| `item_5`, worker test | Real `/usr/bin/python3 -B test_mathutil.py`, exit 0, `ACCEPTANCE_PASS` | Worker self-test VERIFIED; separate controller Validator NOT_RUN |
| Runtime lifecycle | CLI exit 0; observed cgroup/resource limits; empty remaining PID list | Exit/cleanup VERIFIED; exit alone does not approve task |
| Fresh controller audit / public `--verify` | Hashes, rejected artifact and boundary failure rechecked; verifier exit 1 | Durable failure preserved, no accepted restart receipt |

Observed rejected artifact SHA-256:
`ba1a531f581d2e6094e978ed6f7aca7a8d92eeb62c6e7ad73ee692f7f18bc772`.
The change is `return a - b` to `return a + b`; the controller's pure AST
check did not execute this code. Only a rejected copy/manifest of diagnostic
facts was preserved. No accepted artifact or controller validation was made.

Live `credential_home_write` targeted the public test path
`runtime-home/write-canary`. A later host-side read-only check found that path
absent. Thus the runtime namespace write is verified, while host credential
modification is not established. The live policy path differs from the
zero-provider command/exec preflight; private overlay behavior requires
source confirmation before selecting a correction. No credentials were read
or copied, and the failure cannot be relabeled PASS.

Version-matched official source confirms that minimal-read Linux isolation
starts with a private `--tmpfs /` and adds scoped mounts
([bwrap.rs](https://github.com/openai/codex/blob/rust-v0.161.0/codex-rs/linux-sandbox/src/bwrap.rs#L386));
Landlock FS is disabled inside this bwrap path because mounts provide FS
isolation ([linux_run_main.rs](https://github.com/openai/codex/blob/rust-v0.161.0/codex-rs/linux-sandbox/src/linux_run_main.rs#L220)).
This source mechanism is VERIFIED; the exact live caller/mount that created
the login-home parent remains UNKNOWN. No evidence establishes an actual
grant to the full host CODEX_HOME.

The controller currently checks canary semantics after the worker turn.
Because the reporting canary returned exit 0, the worker proceeded to the
legal patch and self-test. This is not an online admission gate. A future
preflight must cover the same live tool runtime's permission/mount composition
before dispatch, and canary semantic failure must stop subsequent execution.
First collect public mount metadata in a separately authorized zero-provider
diagnostic; do not relax this guard or launch another model under this budget.

Evidence is retained under ignored `runs/wsl-worker-authorized-20261008/`:
authorization plan, current effective config, immutable result, raw events,
execution receipt, intent copy, rejected artifact/diff, restart rejection and
`failed-attempt-restart-audit.json`. `post-run-containment.json` additionally
rechecks those hashes/snapshot in another fresh process and confirms the
dedicated unit is inactive/dead, MainPID 0, with its cgroup absent.
Original failed evidence remains in
`runs/wsl-worker-20261008/`. Actual model usage: input 59572, cached input
43264, output 301, reasoning output 0. These are CLI-reported usage, not
provider attestation of actual model/effort. Code Mode ancestry remains
NOT_DIRECTLY_OBSERVED in the public JSONL interface.

Post-attempt regression commands all passed:

- `python -B -m unittest discover -s orchestrator_tests -v`: 116, 29.744s.
- Root Jev command in `tests/README.md`: 77, 3.148s.
- `python -B -m unittest test_inventory` in `payload/jev`: 12, 0.020s.

Total **205 PASS**, retaining the 199 baseline tests plus six new guards.
Actual logs: `runs/regression-{orchestrator,jev,inventory}-authorized-20261008.log`.
Independent development source review accepted the final receipt ordering;
it is not counted production reviewer evidence. Production Reviewer Provenance,
general production validator admission and end-to-end PASSED remain BLOCKED.
No Global/runtime policy, ACL, child limit or remote operation was changed.
No Phase 3 or benchmark was started; no worker remains from this run.

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

## Zero-Provider containment diagnostics — 2026-10-08

**PARTIAL / native admission BLOCKED.** Baseline
`15284d0d0113a59be40148c3d9ec0c35be1802e2`. 本輪未建立 Worker dispatch、
未發出 inference、未呼叫 Jev。既有兩個 Worker slots 的 intent、result 與 events
hash 均未變；`87c1e1d5-9186-4ed7-b006-4e780ec41980` 仍是
`FAILED_OR_UNKNOWN_NO_RETRY`，artifact 仍 NOT_ACCEPTED。

### Live Unified-Exec Permission Trace

| 節點 | 證據與界線 |
| --- | --- |
| 前次 live command | 保存的 `item_2` 確實執行固定 boundary command；`credential_home_write=ALLOWED`。當時沒有 mountinfo、mount ID 或 backing-device evidence，因此其分類仍 UNKNOWN。 |
| Code Mode → delegate | 版本相符 [CodeModeService::execute](https://github.com/openai/codex/blob/rust-v0.161.0/codex-rs/core/src/tools/code_mode/mod.rs#L311) 建立 delegate，交給 [dispatch broker](https://github.com/openai/codex/blob/rust-v0.161.0/codex-rs/core/src/tools/code_mode/delegate.rs#L106)。這是 source evidence，並非前次事件的完整 ancestry receipt。 |
| delegate → tools | broker 建立 `ToolCallRuntime`，經 [tools/parallel.rs](https://github.com/openai/codex/blob/rust-v0.161.0/codex-rs/core/src/tools/parallel.rs#L117) 分派 nested tool；需要 Session、StepContext 與 turn worker。 |
| Unified-Exec → permissions | [unified_exec.rs](https://github.com/openai/codex/blob/rust-v0.161.0/codex-rs/core/src/tools/runtimes/unified_exec.rs#L205) 組合 turn permissions、additional permissions、shell snapshot 與選定 execution environment。前次 local/non-login command 與 native 分支相符，但事件不足以 attests 所有選擇及臨時 read grants。 |
| Linux sandbox | [bwrap.rs](https://github.com/openai/codex/blob/rust-v0.161.0/codex-rs/linux-sandbox/src/bwrap.rs#L488) 的 restricted minimal-read 使用 tmpfs root 與 scoped binds；[linux_run_main.rs](https://github.com/openai/codex/blob/rust-v0.161.0/codex-rs/linux-sandbox/src/linux_run_main.rs#L220) 由該 mount view 提供 filesystem enforcement。 |
| 零 Provider API | 官方 [command_exec_processor.rs](https://github.com/openai/codex/blob/rust-v0.161.0/codex-rs/app-server/src/request_processors/command_exec_processor.rs#L193) 是 standalone `build_exec_request` 路徑，並未走完整 Code Mode/ToolCallRuntime/Unified-Exec。已裝 schema 同樣區分此入口。`process/spawn` 與 unsandboxed shell 不被用作替代。 |

因此本次診斷 scope 固定為 **LOWER_SANDBOX_ONLY / THIS_STANDALONE_PROBE_ONLY**。
可證明該次觀測的 backing filesystem，不能代表前次 live tool。helper alias
read grant 或合成 parent directory 是 source 可支持的候選解釋；未確認是前次
`runtime-home/write-canary` 的建立原因，也未發現可證明 live-equivalent 的公開零 turn API。

### 實際 Mount Namespace / Mountinfo Evidence

最終診斷 ID：`a9064c19-d575-45d5-9760-86f38a481a6f`。
durable evidence 位於 ignored `runs/wsl-mount-diagnostics-opaque-root-20261008/`。

| 欄位 | 實際觀測 |
| --- | --- |
| Controller mount namespace | `mnt:[4026533274]` |
| Command mount namespace，寫入前／後 | `mnt:[4026533447]`，相同且與 controller 不同 |
| 根 mount | ID `1825`，device `0:338`，root `/`，point `/`，source/fstype `tmpfs`，mount/super options 均 rw |
| Propagation | 根 mount optional fields 為空，無 shared/master/propagate_from；該 device 未出現在 host 前後 mountinfo |
| 新公開 canary | 同一 O_EXCL fd 的 device `0:338`、inode `20`、78 bytes；實際 readback SHA-256 `9d0ae69d7579484ea5a6e21795a85e83ee7cda9cb5a72d0aa916bd65040a9cdc` |
| Kernel restrictions | `CapEff=0`、`NoNewPrivs=1`、`Seccomp=2`；`/mnt/c` 與 `/init` 不可見 |
| Host custody | 新公開 leaf 均未出現在 host，公開 sentinel 的 descriptor metadata 前後相同，fixture tree 與 runtime/attempt pins 未變。此敘述不涵蓋真憑證內容；未讀取其內容。 |

`sandbox.mountinfo` 完整保存每個 mount，包含允許的 `.tmp`／`artifact` rw
carveouts 及其受保護 metadata masks；沒有 runtime-home bind。stacked mountpoints
不被任意挑選，classifier 對無法確定的 closest mount 維持 UNKNOWN。

### Protected Path Access Matrix

| 公開測試對象 | 固定指令 access observation | 分類與限制 |
| --- | --- | --- |
| runtime-home fake-secret / fresh write canary | open/write 均 ENOENT；parent 不在 view | WRITE_DENIED，僅本次 standalone |
| controller / other-worktree sentinel 與 fresh leaf | open/write 均 ENOENT | WRITE_DENIED，僅本次 standalone |
| fixture `.git/HEAD` / fresh `.git` leaf | open ALLOWED；write EROFS；mount `1841` ro/ext4 `8:80` | WRITE_DENIED；Git read 是既有合法權限 |
| runtime bin fresh leaf | write EROFS；mount `1839` ro/ext4 `8:80` | WRITE_DENIED |
| 私有 root fresh leaf | O_EXCL write/readback ALLOWED，完整正面 namespace/device/mount 證據 | PRIVATE_TMPFS_WRITE，VERIFIED 僅此 canary |
| 前次 live `runtime-home/write-canary` | 前次 ALLOWED，缺少當時 mount/parent identity | UNKNOWN，不能回填 PRIVATE 或 PASS |

本次 runtime-home ENOENT 與前次 live ALLOWED **不同**。host 看不到檔案本身不足以
證明隔離；PRIVATE 分類另要求新 mount namespace、相符 stat device、fresh tmpfs
device、exact root `/`、rw、無 propagation、完整 host custody。確認相同 host
object 的 device/inode/hash 變更才分類 HOST_PROTECTED_PATH_WRITE。缺 metadata、
混合／矛盾資料或 opaque root 均不能取得 PRIVATE。WRITE_DENIED 只記錄 syscall
結果，不等於整個 namespace 或 production isolation PASS。

### 診斷失敗與零 Provider 保證

保留 `runs/wsl-mount-diagnostics-20261008/` 的第一次 pre-CLI 拒絕，以及
`runs/wsl-mount-diagnostics-kernel-routes-20261008/` 的第二次 parser failure。
它們是有不同實際證據支持的診斷修正，沒有建立或重試任何 Worker intent。
Linux UAPI 的 RTF_REJECT `0x0200`／RTF_UP `0x0001` 說明新 network namespace
可有不可用的 reject sentinel；gate 仍拒絕一般／UP routes。實際 mountinfo
又顯示 `/bindfileHhNBBb//deleted` 的 opaque synthetic-mask root；parser 保留
該 record，不將它正規化成 `/` 或略過，避免誤判最上層 tmpfs。

官方 app-server [models refresh worker](https://github.com/openai/codex/blob/rust-v0.161.0/codex-rs/app-server/src/models_refresh_worker.rs#L38)
在啟動時嘗試 Online metadata refresh。僅限制 RPC 不能證明 zero provider egress。
所以整棵 app-server 程序樹先進入新的 user/network namespace，再在 CLI exec 前
驗證非 root、only loopback、無 usable route、CapEff 0、NoNewPrivs 1。
`offline-network-before-cli.json` 保存此證據。沒有 filesystem wrapper mount、
配置／ACL 變更或未隔離 fallback。RPC 只含 initialize/config/read/command/exec。
零 inference 與外部 provider network egress 被阻擋是已支持的主張；不能把
`provider_requests: 0` 讀作 SDK 沒有在本機建立任何背景 HTTP 嘗試。

Code Mode Host 另外重用 SHA-pinned protocol probe，實際確認 process/require/fetch/
Deno/Bun undefined、dynamic/static node:fs imports 與 unlisted tool 被拒、純 JS
回傳 5，無 delegate executor。`host-protocol-summary.json` scope 僅
HOST_PROTOCOL_ONLY；它是 trusted native helper，沒有藉此證明 filesystem
containment 或前次 live ancestry。Host 和 tool sandbox 的保證分別記錄。

### Pre-Execution Admission Gate Result

`tools/linux_containment.py` 是 stdlib parser/classifier 與 controller 診斷 receipt，
未新增授權 broker。receipt 使用 exclusive durable write，綁定 challenge、配置、
policy、CLI/bwrap/host、固定 probe 與 mountinfo hashes，含期限，固定
`admission=BLOCKED`／`live_equivalence=UNKNOWN`。

兩個既有 smoke 的 `--execute` 入口在 prepare、intent/evidence 寫入與 process
dispatch **之前硬性拒絕**。caller 自稱 VERIFIED、有效／重播／過期 receipt，
都沒有放行分支。這是已實作且測試的 **pre-dispatch hard block**；不是成功的
live 即時 canary admission。完整同次 live 工具 namespace 的 containment gate
仍 BLOCKED，不以事後檢查補充它。

新 controller 的 `controller-restart-audit.json` 重新計算所有 receipt evidence
hashes 與分類、核對原 slots/runtime/public metadata；actual-time stale receipt
被拒，測試 snapshot time 仍回 LIVE_PATH_NOT_VERIFIED。診斷 unit 已
inactive/dead、MainPID 0、cgroup 不存在。collect 中 app-server shutdown 超時後
由 controller kill（server exit -9），讀取器關閉、無剩餘 cgroup PID；固定
command exit 0 只表示收集完成，未提升為 Worker 或 production PASS。

### 驗收與尚存阻礙

15 項新增測試涵蓋 PRIVATE／HOST 分類、缺失 mount metadata、policy mismatch、
stale/replay、caller forged metadata、兩個入口在 intent 前拒絕、fresh controller
reopen，以及 public symlink/hardlink/collision 和 offline route gate。
既有 205 項保留；本輪全部命令實跑，合計 **220 PASS**：

- `python -B -m unittest discover -s orchestrator_tests -v`：131。
- `python -B -m unittest test_response_diagnostics test_decision test_phase2a test_resources test_combined test_inventory_safety`：77。
- payload/jev 的 `python -B -m unittest test_inventory`：12。

log 為 `runs/regression-orchestrator-containment-final3-20261008.log`、
`runs/regression-jev-containment-20261008.log`、
`runs/regression-inventory-containment-20261008.log`。獨立 architecture/security
source review 仍是 advisory，不是 Task REVIEW→PASSED 的 reviewer evidence。

**DONE**：固定零 inference 下層收集、觀测分類、durable restart 核對與執行前
硬拒絕。**PARTIAL**：Live Unified-Exec trace 的 source 部分。
**BLOCKED**：前次 ALLOWED 的實際 backing filesystem、完整 live-equivalent
零 Provider route、same-execution online admission、host filesystem assurance、
Production Reviewer Provenance、Production Validator 與完整 E2E。
最小必要下一步是可驗證的官方 live-tool 零 inference 入口／hook，能在同一次
實際 tool namespace 保存 policy/mount evidence 並在修改前阻擋；相似 sandbox、
本地重新編譯 harness 或 controller 簽章不能自行證明 release binary continuity。
未啟用 Phase 3、未提高 children、未改 Global production、未 push/PR/merge。

## External Containment Executor PoC — 2026-10-08

以 `823515cdc080aedb45f67730969de026244d6282` 為基準。裁決為
**NO-GO（目前 Executor 導入）／Production Admission BLOCKED**。
這次只建立並執行一個零 Provider PoC，沒有建立 Worker dispatch、修改歷史
attempt 或啟動模型。此次失敗是 PoC 的程序識別假設未成立，不能推論官方
`exec-server` 接點不支援。

### 實作與重用

`tools/external_executor_poc.py` 是獨立實驗入口，沒有接入 scheduler 或改動
既有 native admission hard block。重用 pinned 官方 CLI/bwrap、
`run_cgroup` 的 timeout/limits/cleanup、既有 mount parser、network gate、
artifact tree/hash 與 exclusive durable writes，沒有新增依賴或替代 patch 工具。

實際 CLI `0.161.0` 的 `exec-server --help` 支援 experimental stdio service、
`--concurrent-requests 1` 及 `--exit-on-stdin-close`。這是 release help 證據；
本次未通過 gate，因此 server startup/protocol compatibility 尚未驗證。
RPC 參數參照固定官方 source commit
[`979011409de0a60b52f179721948e65531d26144`](https://github.com/openai/codex/blob/979011409de0a60b52f179721948e65531d26144/codex-rs/exec-server-protocol/src/protocol.rs)。
source schema 不替代實際 release RPC 驗證。

外層計畫為新 user/pid/net/ipc namespace、readonly tmpfs root、readonly
runtime/system binaries、僅 synthetic workspace 可寫且 `.git` readonly、
private scratch、無 credentials/controller/worktree/Windows host mounts。
Controller 從實際 `/proc/<pid>` 讀取 executable、mountinfo、namespace、
capabilities、NoNewPrivs 與 network evidence；gate receipt 持久化後才發 `G`。
CLI exec 後還必須核對 pin 與 namespace continuity，才允許 modifying RPC。
process RPC 刻意不提供 optional inner sandbox，測試惡意 request 仍受外層
floor 約束；此路徑不宣稱原 native policy 或 live tool PASS。

最終 verdict 同時要求實際 RPC/artifact 驗收及 cgroup exit、kernel limits、
reader closure、輸出上限、無殘留程序。RPC 子集成功不能掩蓋清理失敗。
沒有 local fallback，正式 Worker admission 一律 BLOCKED。

### 唯一實跑結果與停止原因

Run ID：`be38f571-6210-419f-8bba-675fec823369`。
Evidence 位於 ignored `runs/external-executor-poc-20261008/`，只含公開 canary。
`custody.json` SHA-256：
`a72a46622ad04c45300328cc5e8420dbc9f1907ab21435bb76305cad71f71fc9`。

Controller 收到 `bwrap --info-fd` 的 `child-pid=15919`，其 `/proc/.../exe`
hash 為 pinned bwrap `77360cb7…e62c4c`，不是預期 Python bootstrap。
因此拒絕 `EXECUTABLE_MISMATCH`；沒有 gate receipt，沒有送 `G`，沒有
exec Codex，`rpc-trace.json=[]`，`changed_files=[]`。
artifact SHA 保持
`e1a894022d1a082987b87adecb623438c9e386d86b2b621cff4a5fe7fdf7edc8`。

| 項目 | 實際結果／scope |
|---|---|
| Release 接點 help／CLI+bwrap pins | VERIFIED；不是 service startup PASS |
| 外層 namespace/mount observations | 已保存 bwrap init 實際 mountinfo；不等於 payload boundary VERIFIED |
| Bootstrap/payload PID/executable binding | FAIL；尚未建立可信 payload 綁定 |
| Pre-execution fail-closed | VERIFIED：沒有 G、RPC 或修改 |
| Shell/process、filesystem RPC | NOT_RUN，不能標為 isolation PASS |
| Live unified-exec、apply_patch、Code Mode Host | NOT_RUN／UNKNOWN，沒有等價性或 routing coverage 證據 |
| Protected paths、credentials、Git、network | init observations 已保存；實際修改／讀取拒絕驗證 NOT_RUN |
| Cancellation/timeout | Worker/process RPC NOT_RUN；本次拒絕後強制 launcher 結束已記錄 |
| cgroup limits/cleanup | VERIFIED：1 GiB、swap 0、64 tasks、無殘留 PID、reader 關閉 |
| Restart custody audit | HASHES_VERIFIED；fresh controller 重算 verdict 仍 BLOCKED |
| Production Reviewer / Validator / E2E | BLOCKED；本次没有改變既有 gates |

獨立 security reviewer 已唯讀核對 raw run、custody hashes、artifact 起始與
結束 hash、空 trace 和 cgroup evidence，接受停止並保存 NO-GO checkpoint。
此 review 是 advisory，沒有匯入 Task REVIEW→PASSED，也不是 provider attestation。

本輪停止此執行路線，不再啟動 Executor、standalone canary 或 Worker。
最小必要修正是以可信 kernel ancestry 識別實際 bootstrap/payload，不能把
bwrap init PID 當 payload。修正亦須重新驗證全部 mount/network gate 條件；
本次 raw mountinfo 的 device bind propagation tags 與 loopback IPv6 route
尚未被 gate 驗收，不能刪除未知或直接放寬 predicate。

若選擇替代路線，應評估將整個 Codex CLI/Code Mode Host/所有 tool descendants
置於獨立、無 controller/host mounts 的 Linux VM；避免只隔離 exec-server 而
local tool 留在外部。該路線 NOT_STARTED，需要另外驗證 filesystem、credentials
broker、network、cancellation/custody；不能憑 VM 名稱宣稱安全。
目前沒有可授予下一個 Real Worker Smoke 的完整 admission evidence。

### 重啟核對與回歸

本輪 fresh controller 實跑：

```text
python3 -I -B tools/external_executor_poc.py --audit --run-root <existing-PoC-run>
=> custody=HASHES_VERIFIED, verdict=BLOCKED, admission=BLOCKED
```

此 audit 不啟動 subprocess、模型或 executor，也不重新核發 intent。
14 項新測試涵蓋 gate ordering/replay、missing mounts、policy/pin mismatch、
host carveout、readonly Git/runtime、protected visibility、network floor、
RPC allowlist、protocol error 不算存取拒絕，以及 lifecycle failure 不得假 PASS。
原 220 項保留；回歸結果記錄於 `runs/regression-*-external-executor-20261008.log`。
本輪全部實跑 **234 PASS**：Orchestrator 145（41.916s）、Jev 77（3.881s）、
Inventory 12（0.020s）。離線 guard tests 不作為實際 Executor containment PASS。
