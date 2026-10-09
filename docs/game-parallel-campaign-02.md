# Real-game Parallel Campaign 02 — stopped without retry

Controller baseline: `09290f8e64cd1e85763af929e6115ad8fe896caa`.
Branch: `feat/orchestrator-phase1-2`; Campaign: `game-parallel-20261010-02`.
Game base: `805db86f67ab2be152dea8abe57ca47f4e735fb7`.
User approval: “Ok, do it” for the proposed new 2 Sol/medium Workers +
2 Astra/high Reviews, zero attempt retry, isolated clone max_active=2.

## Actual verdict

**BLOCKED_NO_RETRY; both tasks CANCELLED; game delivery NOT_COMPLETED.**
Two real CLI Agents started independent native threads, executed successful tools
and overlapped in populated owned cgroups for **12.023527 seconds**. Neither
produced a file change or completed its turn. No accepted Artifact, candidate
validation, Task Review, integration, merge or completed game feature exists.

Budget consumed: **2/2 Worker dispatches, 0/2 Review turns**, zero attempt retry.
The unused Review allowance is not transferred or repurposed. No Provider/Jev
request followed the stop. This run does not resume any historical Campaign.
Overall Agent Factory remains **PARTIAL**; 5 Workers remains **NO-GO**.

## Readiness and task separation

Used existing Queue, Supervisor, NativeDevelopmentRunner, RepoAdapter, Validators,
Review and Integration code without runtime source changes. Frozen source came
from exact 09290f8. Game source came from the existing pinned local public bundle;
Node/dependency hashes matched the prepared manifest. No install or remote fetch.

New clone only: max_active=2. Original game HEAD and max_active=1 unchanged.
Global cap, native Sandbox, deny-only approval/auto_review, disabled network and
1 GiB / swap 0 / 64 cgroup tasks remain unchanged. Readiness verified official CLI
0.161.0, configured Worker Sol/medium and Reviewer Astra/high native sessions.
These are controller-observed configuration facts, not provider attestation.

Both readiness worktrees passed **308 Vitest tests / 35 files, Typecheck and Vite
Build**. Native tool inventories found `rg` and `python` MISSING;
bash/cat/find/git/grep/node/python3 AVAILABLE. Inventory/hash/fallback guidance
was bound into each new attempt before dispatch. Readiness resource peaks were
54/53 tasks for tests, 43/44 for Typecheck and 58/58 for Build; no sampled OOM or
PID-limit event. Readiness is not candidate acceptance or full-lifetime accounting.

| Task | Ownership | Attempt | Actual result |
|---|---|---|---|
| ZIP hardening | scripts/zip.mjs, tests/zip.test.ts | d998cb2c56c948338f79ae27caa868bc | CANCELLED; no file changes |
| Packaging API | scripts/package-itch.mjs, scripts/package-itch.d.mts, tests/package-itch.test.ts | 5816b98e82214195a1be3e891f4b656d | CANCELLED; no file changes |

No mutual dependency or overlapping ownership. Packaging contract explicitly
uses baseline createZip/legal names; cross-feature validation waits for integration.
Task runtime=300 seconds, failures<=3, cumulative repair=60 seconds, pinned
checks=120 seconds, all within existing policy ceilings. No budget was extended.

## Precise failure

Packaging Worker issued this native tool command:

```text
/bin/bash -lc 'cat tests/unity-preflight.test.ts vite.config.ts'
```

Native result: exit **1**, status failed; output included:

```text
cat: tests/unity-preflight.test.ts: No such file or directory
```

The output also contained the successfully read vite.config.ts. A missing file
in that multi-operand cat makes the command fail. Current classifier has no
recognized recoverable category for this missing read target; it returned
`TOOL_FAILURE_UNKNOWN`, triggering the required global stop. ZIP Worker was then
cancelled. Both monitors recorded **0 recoverable failures**, no completed turn,
and approximately 277 seconds remaining. This was not rg failure, repair-budget
exhaustion, a test assertion, native Sandbox startup failure or observed quota hit.

The failure exposes an ordinary-read classification gap. It does not prove a
permission bypass. UNKNOWN remained fail-closed: no policy was relaxed to continue
the run, no dispatch was reissued, and neither incomplete task reached PASSED.
The v2 repair and task-local completed-validator isolation paths were not exercised
by this early UNKNOWN stop; they remain NOT_VERIFIED_BY_THIS_CAMPAIGN.

## Lifecycle, custody and recovery

Both execution receipts have clean output readers, remaining cgroup PIDs=[],
control_unknown=false, and successful stop. Fencing callback completion preceded
stop request for both. Readback of **16 owned units** found inactive / MainPID=0.
Observer thread stopped. There is no Campaign Worker left running.

Cold reopen verified CANCELLED/CANCELLED, epochs=2, attempts=1 each,
budget used=2, native slots=0, locks=[], Review dispatches=0. A halted claim
returned None. No execution resumed and no budget was replenished.
Source manifest and native configuration pins still matched. Complete file/mode
scans found no changes outside or inside assigned project files; Git HEAD unchanged.

| Observed metric | ZIP | Packaging |
|---|---:|---:|
| Native events | 5 | 7 |
| Kernel pids.peak at sampling | 60 | 55 |
| Kernel memory peak at sampling, bytes | 122589184 | 100089856 |
| Last sampled cpu.stat usage, microseconds | 1086188 | 1075653 |

Supervisor elapsed=25.943805 seconds; peak inflight submissions=2.
Overlap uses distinct populated cgroups and native thread IDs, not merely executor
submission count. It is not provider simultaneous-reasoning attestation or speedup.
Final tokens/usage are **UNKNOWN** because neither turn.completed was observed.
Sampling does not prove all-lifetime resource headroom or establish admission for 5.

Ignored evidence: `runs/game-parallel-20261010-02/saved-evidence/` contains raw
native events, failure/cleanup/readiness receipts, scoped task contracts, SQLite
backup and post-stop audit; no credentials/runtime-home or dependencies exported.
110 evidence files were hashed and read back with zero mismatches.

- Evidence manifest SHA-256: `3a9c835c20dac65d829837b6eaff27cd4f827f1868c417d580296f043aec080e`
- Audit SHA-256: `4bbfd75888291373cf9484d3bbddc9903e97b145c1b9128a44f3b4de097e4991`
- Frozen controller archive SHA-256: `608901b7ad8bdfa2828684aabd554e0602db87677b282ff6393e9fd1567f7799`

An operator-only export parser initially failed on the new tool-readiness receipt
shape. It was corrected before producing the audit; no raw evidence or attempt
was changed, and no Worker was retried. Source changes this round are reports only.

## Regression and next step

Final actual regression, commands as in [recovery report](parallel-worker-recovery.md):
257 Orchestrator tests PASS (76.531s), 77 Jev tests PASS (4.541s),
12 Inventory tests PASS (0.026s): **346 PASS, no skipped**.
Readiness tests do not replace missing candidate Build/Test, Review or integration.

Smallest next implementation: at zero Provider, narrowly recognize a native
completed read-only command's missing in-repo target as recoverable, with literal
argv/scope checks and denial precedence. Do not blanket-allow exit 1 or match
arbitrary “No such file” output. Supply actual repository file inventory to reduce
guessed paths. Preserve count/time budgets, all UNKNOWN/security global stops and
no-retry. Test missing read targets, permission denials, ambiguous command chains,
outside-scope paths, budget exhaustion, stale/restart and healthy sibling behavior.
Only then propose a newly authorized Campaign; neither current nor historical
attempt may be retried. No new Campaign is running or scheduled.

No Global production or original Repo configuration was modified. No ACL/native
permission or capacity-ceiling change, Jev Phase3, push, PR, merge,
gameplay/browser acceptance or release was performed.
