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

上述裁決屬於原 High-Assurance 路線。2026-10-08 使用者另行明確授權
Development 原生信任模式；新模式不改寫本節 FAIL 或將 Production Gate 標為 PASS。

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

## Development Execution Mode checkpoint — 2026-10-08

基準 `8c2499979e1b5ba8bf53d415a564801e51f28270`。使用者改變日常開發的
驗收要求，明確接受官方 Codex 原生 Sandbox、Approval 與模型安全機制。
本輪實作新的 `DEVELOPMENT` mode；不重開舊 Production queue，也不將歷史
High-Assurance FAIL 改成 PASS。完整責任、配置與操作入口見
[Development Execution Mode](development-execution-mode.md)。

### 已實作與重用

- 延伸現有 Policy Compiler、SQLite Queue、Supervisor、Lease/Fencing、
  Worktree、Dependency Snapshot、ArtifactStore 與 Merge Queue。
- 新 mode 綁 policy hash、source hash、queue ID 與 evidence realm；Workspace
  無法改選 mode、降低 review 或突破 active≤2。Rule Router 不依賴 Jev。
- `NativeDevelopmentRunner` 啟動 pinned 官方 Linux CLI 0.161.0，保存真正的
  CLI events、工具結果、diff、artifact hash 與 execution receipt。exit 0
  不足以驗收。Native Sandbox 啟動失敗沒有 unprotected Host fallback。
- 固定 Validator Registry 經官方 app-server `command/exec` 執行 literal argv，
  artifact readonly；AST guard 與四組算術斷言避免 fixture 自行假造完成標記。
- Reviewer 必須由 Controller 真正另開 Astra/high CLI turn；綁 task、attempt、
  artifact、獨立 native thread、nonce 與 Supervisor owner。Caller 的 review JSON
  不可入庫。執行 assurance 為 `CONTROLLER_EXECUTION_NATIVE_TRUST`，不偽造
  provider model attestation。此新 reviewer 路徑尚未經真實推論驗收。
- Review dispatch intent、capacity slot 與 nonce 持久化；重啟不能自動重發。
  Worker、Validator 或 Reviewer 的任何 cleanup 未確認，都保留 HELD/容量與鎖。
  不能以 Worker 已退出代替 Validator 已清理的證據。

額外 External Executor、同次 namespace attestation、Production provenance
程式保留在原有獨立入口；Development 預設不載入，沒有繼續擴建隔離框架。
本候選僅支援已準備的 WSL Linux fixture runtime，不是 Global 安裝或一般
Windows/任意 Repo Worker adapter 的完成宣告。

### 真實執行與停止條件

| Run / attempt | 實際結果 | 未完成的條件 |
|---|---|---|
| `development-live-20261008-01` / `5eb5bbf466a24d78b4f3c6402690bb73` | native instructions loader 不支援檔案型 writable root；模型 turn 未開始；CANCELLED / NO_RETRY | M1 FAIL，沒有重發此 dispatch |
| `development-live-20261008-02` / `72ca0dcf6fc2435a9ca7612a993ea6f4` | Sol/medium 真實 turn 完成；shell 與 file_change completed；`artifact/add.py` 已寫出正確加法 | Controller `OUT_OF_SCOPE_DIFF` 拒收；CANCELLED / NO_RETRY；Task Validator、Reviewer、雙 Worker NOT_RUN |
| `development-validator-readiness-20261008-02` | 官方 `thread/start` readiness 與 `command/exec` 成功；四組斷言輸出 `ACCEPTANCE_PASS:add`；inference turns=0；cgroup 空、readers 關閉 | 使用 Controller 自備 fixture，不是失敗 Worker artifact 的追認 |

第二次真實 Worker 的 native thread 為
`01a11b39-e82c-7262-ab2b-ff4c2769f570`；有 `turn.started`、`turn.completed`、
成功 command 與 file_change。第一次 `rg` 工具 exit 127 也保留在 raw events，
沒有把所有工具都報為成功。產物內容為 `def add(a, b): return a + b`，
31 bytes，SHA-256：
`b31ad9f0e26461c1e38ba4071046e8c3c6aa2cda4b46b6649872ba0ba61cd565`。

拒收原因是 native runtime 在既有可寫 `.tmp/` 留下零 byte lock。Controller
當時把 scratch 算成專案 diff。修正後只排除固定 `.tmp/` 的 project diff；
scratch hashes 另入 receipt，大小、檔案數、symlink/reparse 與 special-file
限制仍套用。没有增加 writable scope。此修正有離線驗證，尚未取得新 Worker
端到端結果；原失敗 attempt 不會因此改成 PASS。

Native release 對 writable root 需要目錄；本候選沿用原 profile 的 `artifact/`
目錄 ceiling，精確 allowed_files 是 Controller diff/custody 驗收，不能宣稱
OS 已阻止該目錄內所有暫時越界寫入。Reviewer/Validator 的 artifact 為只讀。

### Evidence custody 與重啟核對

公開 execution evidence 保存於 ignored
`runs/development-execution-20261008/`；沒有搬動或讀出 credentials。
其中 `custody.json` 記錄 56 個檔案，SHA-256：
`f8f1ac2ca758b04a723af04869524016c9cd43cb06d68da94680ee3220168f66`。
Fresh read-only hash audit 56/56 一致；兩個新失敗 result 仍為
`BLOCKED_SINGLE_NO_RETRY`。既有 WSL smoke result、authorized attempt result、
worker-events 與 External PoC custody 也符合既存 hashes。
第一次歷史 events audit 用錯 filename `events.jsonl`，保留該 MISSING 查找紀錄；
另外的 path-correction audit 以實際 `worker-events.jsonl` 驗證一致。
這些 hash audit 不重開 queue、不建立 dispatch，也不等於 M1/M2 成功後的 recovery。

### 回歸與獨立審查

實際執行命令（repo root，Inventory 命令於 `payload/jev`）：

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
python -B -m unittest discover -s orchestrator_tests -v
python -B -m unittest test_response_diagnostics test_decision test_phase2a test_resources test_combined test_inventory_safety
python -B -m unittest test_inventory
```

本候選實跑 **257 PASS**：Orchestrator 168（37.993s）、Jev 77（3.058s）、
Inventory 12（0.015s）。原 234 項保留，新增 23 項 Development tests。
包括 mode/review floor、舊 queue realm、防 replay、review capacity/restart、
native thread 身分、published artifact 比對、scratch guard、validator 假完成、
沒有 Host fallback、Supervisor review heartbeat，以及 Worker 已清理但 Validator
未知時仍保留鎖的實際 attempt fault injection。另以實際 review method 驗證
審查期間 policy drift 不可發布 PASS；Reviewer 完成後再次核對 policy/binary pins。

獨立 architecture/security review 為 source/evidence advisory，已接受已修正的
候選；不能代替 Task 的 Astra/high review 或 production attestation。

### 狀態與下一步

- **DONE（實作與離線驗證）**：明確 Development mode、原生 dispatch/validation/
  independent-review 接點、scratch 修正、cleanup/capacity fail-closed。
- **PARTIAL（真實驗收）**：Worker 已真正呼叫工具並改碼；Controller 尚未接受
  完整 Task→Validation→Review→PASSED。M1 未完成，M2 NOT_RUN。
- **BLOCKED（保留路線）**：原 High-Assurance Production Admission；不作新的日常 gate。

最新已授權 envelope 為最多 3 Worker + 3 Review turns、各 task 一次、零重試。
其中一個 Worker dispatch 已消耗且失敗；Controller 的修正不重設已用次數。
本輪已另詢問後續範圍，答覆前不發出新模型請求：可用剩餘額度只完成新單 Worker，
或取得完整新 1→2 envelope。所有後續測試使用全新 task/attempt；舊失敗 immutable。
沒有修改 Global production、ACL、安全策略或 children ceiling；沒有 push、PR、merge。

## Development M1 → M2 Campaign checkpoint — 2026-10-08

本節是新 Campaign 的獨立結果，不改寫前節失敗或移轉其預算。
使用者授權基準 `fa1cb70bf74c735a62dd365df43f335561ad75e8`，
最多 3 次 Worker dispatch、3 次 Task Review turn、零自動重試，active≤2。
Campaign ID：`development-campaign-20261008-96f3c4f5`；
run ID：`e85df6ed1a9f4248a958ef135d33de68`；
queue ID：`ddf96bb9` 前綴。實際執行來源 checkpoint：
`fe68d2e3c5284ec55645996d1a2a27e1312938f6`。

**整體 Campaign：PARTIAL。M1/M2 的既定技術驗收 PASS；嚴格「任何 FAIL
立即停止」符合性 FAIL。** 下列事實分別記錄，不能以技術成功取代停止政策。

### 最小修正與基準

執行前 257 項既有測試全部實跑通過。Source recheck 發現 native Supervisor
在失敗後可能繼續 claim 或 review。只延伸既有 Supervisor/Queue，沒有新調度框架：

- Native claim 前檢查 FAILED/HELD/CANCELLED；同一 SQLite transaction 再檢查，
  在 budget、lease 或 lock 改變前阻擋派工。
- Native attempt 的非 REVIEW 結果、exception，或 Review 非 PASSED 結果，
  觸發現有取消、fencing、cleanup；停止其他派工與後續 Review。
- 新增三個因果 guard tests：既有失敗不能 claim、執行失敗取消另一 Worker、
  第一個 Review 失敗不執行第二個。原 OFFLINE 行為保留。

上述修正在本地 checkpoint `fe68d2e` 通過獨立 source review。
**它控制 attempt/validation/review 層級，不是 live 每個工具項目的即時取消 gate。**
本 Campaign 的後續工具失敗暴露了這個層級差異。

### 真實派工、驗收與相依成果

| 階段／Task | Attempt | Worker / Review native thread | 既定技術驗收 |
|---|---|---|---|
| M1 `dev-add-ddf96bb9` | `3aad7d7de36f4f00881cc7fbe75da354` | `01a11bc9-a92f-7010-9578-f58d0b12e150` / `01a11bc9-e512-7351-b483-de1be15f0459` | 真實 file_change、command；Controller 4 組斷言；獨立 Review PASS；Task PASSED |
| M2 `dev-multiply-ddf96bb9` | `edb5a920fd1b4ad49f0022d7ba5c1626` | `01a11bca-1f68-7df0-98ff-063d6e3e889d` / `01a11bca-78f1-7ea2-b5a7-09f7d4811389` | 真實 file_change、成功 command；Controller 4 組斷言；獨立 Review PASS；Task PASSED；另有下述工具失敗 |
| M2 `dev-subtract-ddf96bb9` | `eb31cae71500431d801131bf00b966af` | `01a11bca-1f97-7c23-8e91-fcbd210ba055` / `01a11bca-9d0c-7901-ade5-41a6517cf696` | 真實 file_change、command；Controller 4 組斷言；獨立 Review PASS；Task PASSED |

M1 完整 PASSED 後，腳本重開 Controller 並驗證 custody，再自動加入兩個
dependent tasks。兩者都綁 M1 manifest/review hash，取得相同
`artifact/add.py` SHA-256 的快照，分配不同 detached worktrees。
Queue events 證明上游 PASSED 早於兩個下游 CLAIMED；下游完成後 input hash
仍一致。此 fixture 驗證交付與 dispatch ordering，不等於複雜 API/Build 相依驗收。

兩個 M2 Worker 的實際 controller-observed PID 執行區間重疊 **9.141 秒**；
active cap 沒有超過 2。Workers 結束後 serialized Review，各占同一容量治理。
三個 artifact 在另外的隔離 worktree 做 **12 組 integration 斷言**，
輸出 `ACCEPTANCE_PASS:integration`；base ref 未變，未執行 Git merge。
Merge Queue 三列均為 `HELD / HUMAN_MERGE_AUTHORIZATION_REQUIRED`。

| Artifact | SHA-256 |
|---|---|
| `artifact/add.py` | `59b422d2103632f1e0e580b334bbae30706ffd3004257085b632372ff030d6c4` |
| `artifact/multiply.py` | `83b38b3130d12363cb70834b2e7a8d81de126563ef924f1970149dfe0f56a20b` |
| `artifact/subtract.py` | `01a0a7861b37d40e66c3a22033dab45570a0852b5d5596f2e43b725b4fed91ec` |

Controller final diff 各只有 assigned file；固定 `.tmp/` scratch 的零 byte native
lock 分開保存 hash，不算 project diff。所有 scan 的 reparse、special-file、
檔案數與大小限制仍套用。Native profile/CLI/Code Mode Host pins 未漂移，
不是增加可寫 scope 或宣稱 OS 的精確 per-file 寫入阻擋。

### 工具失敗與停止政策偏差

乘法 Worker raw events `item_3`：`/bin/bash: line 1: python: command not found`，
`exit_code=127`、`status=failed`，分類 `ENVIRONMENT_FAILURE`。
`item_4` 在同一 native thread/turn 改用 `python3`，成功執行本地檢查，
最後 `turn.completed`。沒有新增 attempt、dispatch 或重新開模型 turn；
Controller pinned Validator 與獨立 Review 隨後都通過。

此同 turn correction 不計為新的 Worker dispatch retry，但使用者的停止條件
沒有事先限定 FAIL 層級，也沒有授權工具失敗後繼續的例外。
**失敗當下並未立即停止，不能事後縮限授權文字而宣稱全程符合。**
現有 `tool_evidence` 要求存在成功工具，completion gate 拒絕 turn/top-level failure；
未實作逐項工具失敗即時取消。因此 `result.json` 的 Controller PASS 與三列
Task PASSED 保留，Campaign 的無保留驗收不成立。

`post-campaign-integrity.json` 額外檢查「所有個別工具成功」，aggregate 為 FAIL。
其中新 79/79 與歷史 56/56 hashes 全一致；FAIL 來自上述一筆工具失敗，
不是 artifact custody 破壞。此事後檢查亦不能冒稱執行中的阻擋。
不將「所有工具零錯誤」反向加入既定 artifact/Task 驗收，再推翻有效測試與 Review。
獨立唯讀 evidence/authorization review 確認上述分層；屬 advisory，不替代 Task Review。

### Durable evidence、重啟與預算

公開 evidence 位於 ignored `runs/development-campaign-20261008-96f3c4f5/`：

- `authorized-plan.json`、`launch-plan.json`：新授權、來源 hashes、實際命令及預算。
- `evidence/result.json`、`evidence/controller/`：native CLI JSONL、實際程序、
  pinned validators、review intents/nonce/receipts、SQLite ledger、artifact manifests。
- `restart-audit.json`：新的零推論 Controller 程序重開 Queue，重核 policy/config/pins、
  artifacts、原始 events、Validator/Review receipt 與 dependency snapshots；
  logical ledger 未變、budget 未重設、無新 dispatch。
- `custody.json`：79 檔，SHA-256
  `65184d2d95b7b22ca0bddc7b9c681e7edf6f50cc967d856c305bf3314cd54488`。
- `post-campaign-integrity.json`：公開 copy 再驗 hashes、歷史 56 檔一致，
  並保存個別 failed tool 的真實狀態。
- `verification-results.json` 與三份 regression logs：實跑命令、exit codes、計數及 hashes。

本 Campaign 消耗 **3/3 Worker dispatch、3/3 Task Review turn、0 次新 attempt retry**。
零推論 readiness、Controller Validators、integration 與 custody audit 不算模型 turn；
native startup 仍可能有 metadata HTTP。沒有回收或轉移歷史已用額度。
各程序都有正向 cgroup cleanup/readers-closed evidence；fresh systemd 唯讀核對
沒有仍在執行的 `codex-development-*.service`。

Reviewer assurance 仍為 `CONTROLLER_EXECUTION_NATIVE_TRUST`，configured
`gpt-6-astra/high`、獨立 native thread、真實 completion 與 challenge/artifact 綁定。
`provider_attested_model=None` 不變；沒有恢復 High-Assurance Admission 開發。

### 完成後回歸與最小下一步

完整三組命令同前節，全部 exit 0、沒有 skipped：

| Suite | 實跑結果 |
|---|---|
| Orchestrator | 171 PASS，44.136s |
| Jev regression | 77 PASS，3.896s；零 Jev provider |
| Inventory | 12 PASS，0.024s |
| 合計 | **260 PASS**；原 257 保留，加 3 項停止 guard |

本輪 **DONE（限既定技術驗收）**：單 Worker、兩個平行 dependent Workers、
真實工具修改、Controller Validators、獨立 Review、artifact/input custody 與重啟核對。
**PARTIAL（Campaign）**：立即停止政策存在上述偏差；不宣稱全域 Agent Factory
或整個 Phase 1–2 無保留完成。原 High-Assurance Production Admission 保持 BLOCKED。
真實 cancellation/timeout、故障中 restart、實際修改衝突未在此成功 Campaign 注入；
既有回歸 guard 不冒稱這些 native 情境已驗收。M3、Phase 3、擴容 NOT_STARTED。

到 3＋3 授權邊界停止，不再發模型請求。下一個最小修正是先明確制定下一輪
stop policy 的 failure 層級；若仍要求任何工具 FAIL 即停，須在現有 native output
reader 接入即時取消/fencing，不能用事後 audit 代替。也可在新的、明確授權契約
允許同 turn 的無害工具環境修正；這不會追溯更改本輪偏差。
任何新真實驗證需要新的 bounded envelope。沒有 Global 變更、push、PR 或 merge。

## 2026-10-08 Worker Failure Policy 與即時停止（零 Provider）

基準 `6c52ca6fa1dac3ea2c8b7b0cd341cb6b5d796b69`。使用者授權只涵蓋新的
Failure Policy、零 Provider 故障注入、完整回歸及本地 checkpoint。
沒有啟動新的 Worker Campaign、Codex inference 或 Jev，沒有修改 Global runtime、
原生 Sandbox/Approval、active children ceiling、Review 或人工 Merge 要求。
前節 Campaign **PARTIAL**、歷史 FAIL/UNKNOWN/PASSED 及已消耗額度保持不變。

### 最小增量

- `orchestrator/worker_failures.py`：固定分類、3 筆可恢復失敗／首次失敗 60 秒／
  task runtime 上限、incremental JSONL、fatal/control-unknown latch、immutable hash chain。
- `orchestrator/development.py`：Worker stdout/tick/EOF 接入 monitor；即時 fence/cancel；
  claim/config watchdog；成功轉 REVIEW 前的 watchdog handoff；未知清理不釋放 locks。
- `tools/linux_worker_smoke.py`：沿用既有 systemd cgroup，改增量 read1、callback drain、
  fence-before-stop、cancel/control failure 記錄；停止指令非零保持 cleanup unverified。
- `orchestrator/policy.py`：新增 Failure Policy source hash，禁止默默換執行規則。
- `orchestrator/store.py`、`phase2.py`、`evidence.py`：既有 transaction/fence/heartbeat/
  authenticate 介面只增加可信 timeout keyword，預設不變；native stop/watchdog 用 50ms。
- `tools/worker_failure_probe.py` 與 tests：固定零 Provider emitter／受控故障注入；
  原 Development test 只補 monitor 接線，不用 mock 冒稱 native Worker PASS。

完整 Failure Matrix 與邊界位於 `docs/development-execution-mode.md` 的 v1 政策。
沒有重寫 Queue、Scheduler、Runner 或新增隔離框架。

### 實際停止、fencing 與重啟證據

初版 run `worker-failure-policy-20261008-6c704033` 的 9 案例符合當時斷言。
獨立審查另找出 watchdog-origin UNKNOWN、publication/guard 競態與同 chunk deadline
三個缺口。先新增定向 regression，實跑 21 項呈現 1 FAIL／4 ERROR，之後修正。
初版證據不刪除，不將初版九案冒稱 final source 的完整驗收。

中間 12／13 案例版本各保留獨立 evidence。提交前另以真實 SQLite 鎖重現 fatal
callback 與 watchdog 查詢被原 10 秒 busy wait 阻擋；兩個定向測試各先 FAIL，
修正後 PASS。fatal 先發取消訊號，受信任停止／watchdog 路徑用 50ms 單次 DB 等待，
一般 Queue 預設不變。DB 故障期間不假稱 durable fence 已成功或 ledger 已變 HELD；
停止執行、保留 locks/slot 及 UNKNOWN，DB 恢復後才核對並 fence，不接納結果。

最終 run **`worker-failure-policy-final-20261008-aa10fc53`**，14 個新的固定 fault fixtures，
逐一啟動、各 2 秒 lifecycle budget；每個 SQLite fixture 僅一筆 synthetic dispatch intent。
這些不是 Codex Worker dispatch；**Provider turns=0、Jev calls=0、重試=0**。

| Fault injection | 實際結果 |
|---|---|
| 普通 command-not-found | 保留 exit 127，原 emitter turn 修正並完成；monitor 未停止；不是模型驗收 |
| permission denial | turn 結束前 fence/cancel，late main/child marker 均未產生 |
| 第四筆可恢復失敗 | `RECOVERY_COUNT_EXHAUSTED`，沒有重置次數 |
| 恢復時間用完 | 使用更嚴 0.25 秒測試上限；`RECOVERY_TIME_EXHAUSTED` |
| cancel、task timeout | 即時 STOP、durable fence 在 cgroup stop request 之前 |
| lease invalidation | watchdog 停止；舊 epoch/result/intent 被拒絕 |
| missing provider completion | exit 0 仍 STOP；本案 stop 命令回報 unit 已消失、非零，保守 HELD |
| stdout callback fence exception | `control_unknown=true`；HELD、locks 保留，cleanup 不宣稱 verified |
| watchdog callback fence exception | DB 回復後仍 `control_unknown=true`；HELD、locks 保留 |
| cancellation result unknown | 真的停止 owned unit後注入非零控制回覆；`CLEANUP_UNVERIFIED`、HELD |
| Controller reopen during execution | fresh Queue 重開並注入 lease-expiry clock；STOP；拒絕 stale intent/result |
| 真實 SQLite 鎖：stdout-origin | 關閉此 case 的 watchdog，分離原因；fault callback 有界結束，CONTROL_UNKNOWN／HELD |
| 真實 SQLite 鎖：watchdog-origin | guard 查詢短等待後 STOP；沒有等待正常 10 秒上限，CONTROL_UNKNOWN／HELD |

正常 fatal 案例均核對 fence/stop 順序、實際 owned cgroup 空、output readers 關閉，
沒有 late markers。UNKNOWN 案例即使 cgroup 已空，也不將 `process_cleanup_verified`
設為 true。fixture 最後不製造 Task PASSED；只保存 CANCELLED／HELD。

permission case 從公開 stimulus 到 Controller STOP record 為 **4.493ms**；正常取消
及 fatal 案例從 stop request 至 lifecycle receipt 完成約 **7.111–7.874ms**。
這是固定本地 emitter 的量測，不是 native Worker SLA，也不是 atomic pre-tool gate。
`fence_callback_started_unix` 表示停止 callback 開始；`stop_requested_unix` 在 callback
返回後記錄，表示隨後的 cgroup stop request，不混稱為取消 flag 最早送達時間。
第 4 次失敗的 observation 數字從第 1 次 fault 起算，不將它誤報為第四次取消延遲。

fresh 零 Provider 程序重開全部 14 Queue，核對 policy/source pins、failure hash chain、
ledger/budget 未變、stale result/dispatch 拒絕；全部 systemd unit inactive、MainPID=0。
公開 evidence 在 `runs/worker-failure-policy-final-20261008-aa10fc53/`：

- `launch-plan.json`：執行前 scope、零 Provider 預算與 source hashes。
- `result.json`、逐案 `result.json`／`controller/execution/`：原始合成 events、真實 cgroup
  argv/receipt、failure records、SQLite backup、公開 canary／程序資料。
- `restart-audit.json`：fresh Controller 核對、current unit 狀態與 source hashes。
- `custody.json`：155 檔 SHA-256；manifest SHA-256
  `11d448373ff523753b6afafbb8ee18a45e859d401fd3ebec5c3ed10e9ff530b2`。
- `verification-results.json`、三份 regression logs／`verification-custody.json`：完整測試命令、
  實際結果、初版/歷史 hashes與獨立 advisory review 摘要。

Windows 上再次逐檔重算 final 155、初版 103、歷史 Campaign 79、歷史 Development
56 hashes，全部一致。沒有重新開啟或改寫歷史 queue，也沒有改判歷史 Campaign。
source 改變時舊 policy-bound queue 應拒絕當新執行 queue 使用，audit 不授權遷移或 replay。

### 實跑命令與 Regression

```powershell
# WSL：固定 emitter only，不啟動 CLI/model/Jev。
wsl.exe -d Ubuntu-24.04 --exec /usr/bin/python3 -I -B /mnt/c/.llmcode/codex-orchestrator-phase1-2/tools/worker_failure_probe.py --runtime /home/ssss/codex-orchestrator-smoke-20261008 --run-root /home/ssss/codex-orchestrator-smoke-20261008/worker-failure-policy-final-20261008-aa10fc53

# repo root；PYTHONDONTWRITEBYTECODE=1
python -B -m unittest discover -s orchestrator_tests -v
python -B -m unittest test_response_diagnostics test_decision test_phase2a test_resources test_combined test_inventory_safety
# payload/jev
python -B -m unittest test_inventory
```

probe 的 run-root 必須全新，已使用路徑拒絕重開。以上是已跑命令，不是再次啟動授權。
三個 regression commands 均 exit 0、OK、沒有 skipped：

| Suite | 結果 |
|---|---|
| Orchestrator | **195 PASS**，41.556s；原 171 保留，加 24 Failure Policy tests |
| Jev regression | **77 PASS**，3.800s；零 Jev provider |
| Inventory | **12 PASS**，0.021s |
| 合計 | **284 PASS**；原 260 保留 |

獨立唯讀 architecture review 複查前述 P1/P2 全部解除，recommendation=accept，
沒有新的 blocking finding。這個 review 僅對本輪 Controller/lifecycle 改動 advisory，
不偽造 Task Reviewer receipt 或 provider provenance。

### 狀態、未測邊界與 M3 最小方案

**DONE（限本輪範圍）**：Failure Policy、bounded same-turn recovery、串流 fatal stop、
durable fencing、UNKNOWN fail-closed、零 Provider 真實程序清理、fresh recovery audit、
全部 regression及獨立改動審查。

**NOT_RUN**：新政策的真實 Codex Worker Campaign、強制殺死 Controller 的 hard crash
recovery、真實模型工具拒絕的取消延遲。事件仍是觀測後取消，不能保證事件傳到
Controller 前未開始下一個工具。分類清單可能保守誤停，未知錯誤仍停止。
kernel RuntimeMaxSec 是保留的 crash 時間上限，不是 immediate crash cleanup 證明。

**PARTIAL**：歷史 Campaign、整個 Agent Factory/Phase 1–2 仍不能無保留宣稱完成。
原 High-Assurance Production Admission 繼續 BLOCKED／可選；本輪不投入該路線。

下一次遊戲 Repo 實戰的最小前置工作是指定一個授權 Repo/基準及單一任務，盤點
該 Repo 的 AGENTS/OpenSpec、Build/Test與既有能力，再讓現有 Worktree Allocator/
Development runner 支援該明確 Repo 的最小 scope 與 pinned validators。
目前 runner 仍限定 synthetic fixture／artifact directory，不能直接冒稱任意遊戲 Repo 可用。
不重寫 Scheduler，不安裝 Global runtime，不直接修改 main。

完成零 Provider 前置檢查後才另取得 **1 Worker＋1獨立Review、零新attempt retry** 的
明確新 envelope，驗證 Task→真實修改→Repo Build/Test→Artifact→Review→PASSED。
只有單 Worker 新政策驗收完整通過才提出雙 Worker 方案；不沿用歷史已用額度，Merge 仍須
人工授權。本輪到本地 checkpoint 停止；沒有 background Worker 或 remote mutation。

## 2026-10-09 Real-game Repo Adapter checkpoint

基準 `c328366`，遊戲 source `monkey1sai/changshan-longdan @805db86`；詳見
[real-game report](game-repo-development.md)。沿用 Development runner/Queue/Supervisor/
native Sandbox，加入 explicit opt-in Repo Adapter、pinned game Build/Test/acceptance。

300 offline regression PASS（211 Orchestrator、77 Jev、12 Inventory）；native zero-provider
baseline 308 game tests、tsc/Vite build、scope/cleanup/readiness bindings PASS。
本次唯一 Campaign `game-campaign-20261009-05` 仍 **BLOCKED_NO_RETRY**：CLI startup warning
透過 error item 觸發 UNEXPECTED_TOOL 即時取消，worker 1/1、review 0/1、game diff 空。
原 raw、fencing、fresh restart audit、source-v6 保留；沒有 accepted artifact 或 PASSED。

安全修正只加 Development 單次 warning suppression，error/UNKNOWN仍停止；其 native
Worker 效果 NOT_RUN。沒有重派、Global/權限變更、Jev Phase3、push/PR/merge。
單 Worker 真實遊戲交付尚未完成；需新的明確有界模型額度才能進下一次 attempt。

## 2026-10-09 Parallel Worker orchestration increment

基準 `54677b6`；詳見 [parallel controller / Campaign proposal](parallel-worker-development.md)。
沿用既有 Queue/Supervisor/Runner/RepoAdapter，新增 priority、可信資源配額、Repo ceiling、
多任務契約預算、最後修改後 Worker checks、reviewed native integration 與 durable failure stop。
新入口只組合既有元件，不授權 inference 或提高容量。原 game max_active=1、歷史
05/06 FAIL/PARTIAL、Global production 與高保證 optional gates 均保留。
新真實遊戲雙 Worker/Review/Integration **NOT_RUN**；需獨立 2 Worker＋2 Review、零 retry
及隔離 clone 的 max_active=2 明確批准。整體 Agent Factory 仍 **PARTIAL**。

## Authorized real parallel game Campaign — stopped

以 `7b251f3` 及全新 `game-parallel-20261010-01` 執行獨立授權的 2 Worker＋2 Review、
零 retry。兩個真實 CLI Agents 的 owned-cgroup 採樣重疊 66.037476 秒，各有獨立
worktree 與不重疊候選修改；B 的 native rg 缺失啟動 60 秒 recovery window，turn
未完成即 `RECOVERY_TIME_EXHAUSTED`，A 隨 shared stop 取消。裁決 **BLOCKED_NO_RETRY**，
Worker 2/2、Review 0/2；Controller candidate validation／Review／integration 均 NOT_RUN。
Frozen source、92 檔 evidence custody、清理與冷重啟停止已核對，330 項回歸 PASS。
原 Repo HEAD/max_active=1、Global production、Failure Policy 與歷史 FAIL 不變。
完整限制與下一步見 [actual Campaign report](game-parallel-campaign-01.md)；不將此結果
改稱遊戲交付成功或 5-worker admission。

## Parallel Worker readiness / recovery — zero Provider increment

基準 `ee33371`。延伸既有 Runner/Queue/Supervisor：native tool inventory、v2 累計修復時間與
pinned check/task deadline 分離、已完成且 clean 的普通 validator failure 局部隔離、durable
no-refill/review/integration latch、固定 cgroup resource metrics 與 Controller timeout fencing。
原 241 tests 保留，加 16 項 causal tests；257 + 77 + 12 = 346 regression PASS。
零 Provider native 遊戲 308 tests / Typecheck / Build / cancel / timeout 診斷 02 PASS；
診斷 01 timeout FAIL 與原雙 Worker Campaign BLOCKED_NO_RETRY 均保留。
Global/Repo capacity、原生 safety、歷史 attempts 不變；Worker/Review turns 本輪均為 0。
新真實雙 Worker v2 驗收 NOT_RUN，整體仍 PARTIAL；詳見
[failure matrix、證據與下一個有界提案](parallel-worker-recovery.md)。
