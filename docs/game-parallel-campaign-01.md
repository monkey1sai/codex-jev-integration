# Real-game Parallel Campaign 01 — actual stopped result

Campaign label: `game-parallel-20261010-01`; execution timestamps are preserved as Unix
times in evidence. Controller baseline `7b251f39517b163f2222508a6fe462910f7a0b72`;
game base `805db86f67ab2be152dea8abe57ca47f4e735fb7`.

## Verdict

**BLOCKED_NO_RETRY / both Tasks CANCELLED**. Two real Codex CLI Agents executed
tools and changed disjoint files in independent worktrees. Controller-observed
populated cgroup samples overlap for **66.037476 seconds**. Neither Worker finished
the required checks and turn, so no accepted Artifact, Task Review, integration,
merge or completed game delivery exists. Historical FAIL/PARTIAL remains unchanged.

Budget: Worker **2/2**, Astra Review **0/2 NOT_RUN**, zero attempt retry. Unused
Review allowance was not repurposed. No further Provider or Jev request followed
the stop. Original game HEAD/max_active=1 and Global production were not modified;
only the expressly authorized new isolated clone has max_active=2. No push/PR/merge.

## Preparation and actual dispatch

Reused the existing `repo_parallel_campaign.py`, Phase2Queue, Supervisor,
NativeDevelopmentRunner, RepoAdapter, native validator RPC, lease/fencing and
Failure Policy. Campaign-specific setup/oracle/readonly telemetry scripts are
saved under ignored `runs/game-parallel-20261010-01/`; no new execution framework
or changes to the controller runtime were made.

Frozen controller source was exported from exact 7b251f3. Game source came from
the existing pinned public bundle. Node/dependency hashes were verified against
the prior prepared dependency manifest; no reinstall, credentials copy or remote fetch.
New Task IDs, attempts, dispatch intents, challenges and evidence are independent.

Zero-provider readiness **PASS**: both worktrees ran **308 game tests / 35 files**,
TypeScript `--noEmit`, and Vite build. Worker session Sol/medium and Reviewer session
Astra/high matched the effective native config. CLI 0.161.0, original minimal-read
Sandbox, network off, deny-only approval and auto_review were preserved. Reviewer
session start was zero inference, not a Review turn or a Task Review PASS.

Task A hardens ZIP names while preserving the existing public `createZip` API.
Task B extracts an import-safe synchronous `packageItch({distDir,outFile})` API
against that existing API. They have no mutual dependency or overlapping ownership.
The planned integration waits for both PASSED; that prerequisite was never met.

| Worker | Attempt | Actual candidate modifications | Required candidate checks |
|---|---|---|---|
| A ZIP | `583f8ef2e69b4be49aec27447f665aeb` | scripts/zip.mjs, tests/zip.test.ts | Full Vitest started, interrupted; Typecheck/Build NOT_RUN |
| B package | `770062e497b945f69f4d0f86ccf63e5e` | scripts/package-itch.mjs, scripts/package-itch.d.mts, tests/package-itch.test.ts | Test/Typecheck/Build NOT_RUN |

A's saved candidate adds segment/drive/backslash/NUL/Unicode/duplicate/UTF-8 limit
checks and DataView/TextDecoder tests. B's saved candidate extracts the API, preserves
default CLI reporting and adds a declaration/tests. These are **unaccepted candidates**,
not verified fixes; they were not committed to the game or fed to integration.

## Exact stop cause

B issued a native command using `rg --files tests scripts ...`. The tool returned
exit **127**, `/bin/bash: line 1: rg: command not found`. This proves rg was not
available on that native tool PATH; it does not prove anything about unrelated
host installations or a Sandbox vulnerability. Readiness had not checked search-tool
availability, so this environment dependency gap consumed a recoverable-failure window.

The Controller classified the failed command as `ORDINARY_TOOL_OR_TEST_FAILURE /
RECOVER`. B then successfully used `cat` and Python and added scoped files. Existing
policy nevertheless starts an irreversible **60-second window from the first
recoverable failure until turn completion**, bounded also by the 300-second task
timeout and three-failure ceiling. A later successful tool does not reset it.

Journal elapsed time: first recovery **7.507278s**, stop **67.523581s**, difference
**60.016304s**. B had one recoverable failure, no completed turn, and was stopped
as `RECOVERY_TIME_EXHAUSTED`. Shared stop cancelled A **0.047327s** later in the
failure journals. A had no failed completed command; it was executing full Vitest
when cancelled. This is not a verified game-product defect, permission denial,
Provider-capacity error or native Sandbox startup failure.

No recovery budget was extended, no success event cleared the deadline, no
attempt was retried and no incomplete test was counted PASS. Both queues retain
provider_unknown=1 because final Provider completion/usage was not observed.

## Parallel, resource and recovery evidence

There are two distinct native thread IDs, service units and attempt worktrees.
Each raw stream has thread.started, turn.started, successful command execution
and completed file changes. A has 11 events, B 13. The 66.037476s overlap is from
Controller observations of populated owned cgroups, with 67 samples per Worker;
it is not Provider-side simultaneous-reasoning attestation or a Task PASS.

| Metric | A ZIP | B package |
|---|---:|---:|
| Observed kernel memory peak at sampling | 247,300,096 bytes (235.84 MiB) | 98,856,960 bytes (94.28 MiB) |
| Observed kernel pids peak | 61 | 55 |
| Last sampled cpu.stat usage | 3.840130 CPU seconds | 1.503111 CPU seconds |
| Kernel limits | 1 GiB / swap 0 / 64 pids | 1 GiB / swap 0 / 64 pids |

Sampling is not full-lifetime resource accounting. Supervisor elapsed **75.589392s**,
peak inflight submissions=2. The independent sampled cgroup evidence supports the
overlap claim; thread-pool submissions alone would not. Final token usage is
**UNKNOWN**, not zero: neither stream has turn.completed usage after cancellation.
There is no successful serial baseline or throughput/speedup measurement.

Post-stop full scans/modes and HEAD checks verified only assigned candidate files
changed; hash custody does not make them accepted Artifacts. Failure journal
binding/hash chains verified. Both execution receipts report control_unknown=false,
closed output readers, stop_exit=0, remaining PIDs=[]; readonly systemctl confirmed
both owned units inactive with MainPID=0. No background Campaign Worker remains.

Fresh controller reopen verified: CANCELLED/CANCELLED, fenced epoch=2, attempts=1
each, budget used=2, native slots=0, locks=[], Review dispatches=0. A new claim with
halt_on_failure returned None. No execution resumed and no budget was replenished.
Frozen controller source manifest matched after execution. **92 saved public evidence
files** were hashed and read back; no credentials/runtime-home or dependency binaries
were exported into this delivery evidence.

Saved-evidence manifest SHA-256:
`a52794c65f8121e83b042564e722f68d751edf618459fde7b471bc0ae87e1a89`.
Post-stop audit SHA-256:
`6dd95ec73d044c8c9f6ed702a24a8fe8dd48b7b3ce3513536d6a6932e410dff4`.

Primary machine-readable evidence: ignored
`runs/game-parallel-20261010-01/saved-evidence/post-stop-audit.json`, raw native streams,
execution/failure receipts, SQLite backup, readiness, resource samples, candidate
bytes and `saved-evidence-manifest.json`. Do not edit or replay this Campaign.

## Regression and next step

Final deterministic regression after Campaign stop:

| Command | Actual result |
|---|---|
| `python -B -m unittest discover -s orchestrator_tests -v` | 241 PASS, 63.941s |
| `python -B -m unittest test_response_diagnostics test_decision test_phase2a test_resources test_combined test_inventory_safety` | 77 PASS, 3.296s |
| cwd payload/jev: `python -B -m unittest test_inventory` | 12 PASS, 0.024s |
| Total | **330 PASS**, no skipped |

Existing zero-provider conflicts, DAG/review dependency, cancellation, stale-result,
restart, fencing and integration-stop regressions remain PASS. Real candidate
Controller validation, Astra Task Review, integration Build/conflict and combined
artifact acceptance are **NOT_RUN**. Baseline and regression PASS do not replace them.

Two operator-only diagnostics were corrected without Worker retries: Windows WSL
service access required the existing scoped owner-context call; auto-review rejected
whole native config output, and an approved whitelist-only summary replaced it.
A monitoring command's quote error was corrected as readonly inspection. No ACL,
runtime configuration or native safety policy was changed to overcome these.

Smallest next implementation: add native tool-availability evidence to readiness
and supply that exact availability/fallback to Task Context. Use already observed
working cat/Python when rg is unavailable; do not install tools, expand Sandbox or
reset the 60-second policy silently. Verify the revised readiness at zero Provider,
then obtain a **new** bounded Campaign authorization if real execution is wanted.
Neither this failed Campaign nor the two unused Reviews may be resumed/repurposed.

**5 Workers: NO-GO now.** First finish a fresh two-Worker Test/Review/integration
acceptance. Any later capacity change needs explicit Global/governance authorization,
OS quotas and repeatable resource/latency evidence. Current cap=2 remains; pids peaks
61/55 against 64 also warrant measured headroom rather than linear extrapolation.
Jev Phase3, 5/20-worker benchmarks, gameplay/browser acceptance and publication were
not started. Overall Agent Factory end-to-end game delivery remains **PARTIAL**.
