# Blender parallel worker campaign 01 — preparation

Date: 2026-10-12. Baseline: `77bbdf25fe8d8b596a1e5ad123e326a1bf95beda`.

## Scope and current verdict

The user authorizes a **fresh campaign, at most two real Worker dispatches,
zero attempt retries**, testing a chair and a table lamp in separate worktrees.
Appearance, animation and video duration are excluded. No Task Review turns,
integration, merge, remote changes, Jev or Global changes are authorized.

Reserved campaign name: `blender-parallel-20261012-01`. No Linux campaign root,
Task, attempt or dispatch intent has yet been created. Usage: **0/2 Workers,
0 Reviews**. Existing campaigns and their verdicts remain unchanged.

| Acceptance | Current result | Missing evidence |
| --- | --- | --- |
| Parallel Execution | BLOCKED / NOT_RUN | Two native CLI processes and overlapping actual tool lifecycles |
| Failure Isolation | NOT_RUN live | Authorized ordinary missing-file read, recovery, healthy sibling completion |
| Lifecycle | PARTIAL | Offline cancellation/fencing/recovery tests pass; fresh campaign lifecycle not run |
| Task Delivery | NOT_RUN | Real Blender execution, separate blend artifacts, Controller format validation and custody |

## Verified environment

- WSL `Ubuntu-24.04`, kernel `6.6.87.2-microsoft-standard-WSL2`.
- Existing isolated official CLI reports `codex-cli 0.161.0`.
- Official `login status` reports `Logged in using ChatGPT`; no credentials read.
- `blender` is absent from PATH; bounded searches in home, `/opt`, `/usr/local`
  did not locate an executable. This does not assert no Blender exists anywhere.
- Existing Linux GL, Xi and Xrender libraries are present; compatibility is
  **not** proven until the actual Blender binary runs inside the native policy.
- Observed free Linux disk: about 942 GiB. Available memory: about 12 GiB.
  These observations do not raise any allocation limits.
- Existing limits stay 2 active children, each cgroup 1 GiB RAM, zero swap,
  64 PIDs, existing task/check/repair deadlines and no attempt retry.

The official public Blender index lists `blender-4.5.14-linux-x64.tar.xz`
(378,045,212 bytes) and `blender-4.5.14.sha256`:
<https://download.blender.org/release/Blender4.5/>.
No archive has been downloaded or executed. An exclusive-create helper is
prepared in ignored `runs/blender-parallel-20261012-01/prepare_tool.py`.
It checks the official SHA-256, exact download length, archive prefix and a
2 GiB archive-plus-extraction ceiling, using tar's data filter. It does not install
packages, change runtime-home, disable isolation or call a provider.

Two explicit questions are pending: this additional portable-tool disk budget,
and one independent Astra/high **code safety review** of the candidate permission
seam. The latter is distinct from a Task Review and grants no Task PASSED.

## Minimal candidate changes

Extend existing modules; do not replace Scheduler/Queue/Runner:

- `RepoAdapter`: optional trusted `readonly_tools` entries confined to a direct
  child of this campaign's `controller/toolchains`. Pins the executable hash and
  exposes only its tool root as native read access. No controller parent or extra
  writable root is added. Legacy adapters are unchanged.
- Allow an explicitly pinned campaign `review_budget=0`. Task contracts and
  immutable required-independent-review policy remain unchanged.
- `Supervisor`: after workers finish, zero authorized Review budget records
  `review_deferred` and leaves tasks at REVIEW. No review dispatch, PASSED,
  dependency release or integration is manufactured.
- Native process-overlap evidence may be collected for hash/custody-validated
  REVIEW tasks. The default reviewed path and integration gate remain unchanged.
- Parallel campaign result uses `WORKERS_VALIDATED_REVIEW_DEFERRED`; this is
  **not** an overall Campaign PASS or a review approval.

The tool-root addition is a candidate awaiting independent safety review. Only
the executable is rehashed by the adapter; archive/library verification and
fresh native readiness must be bound by campaign preparation before execution.

## Actual regression results

PowerShell, `PYTHONDONTWRITEBYTECODE=1`:

```text
python -B -m unittest discover -s orchestrator_tests -v
  286 PASS (69.896s)
python -B -m unittest test_response_diagnostics test_decision test_phase2a test_resources test_combined test_inventory_safety
  77 PASS (3.704s)
# cwd payload/jev
python -B -m unittest test_inventory
  12 PASS (0.016s)
```

375 passed, no skipped. Five added tests cover zero-review budget bounds,
retained task review requirements, tool root scope/hash drift, two-worker
completion stopping at REVIEW, blocked dependencies, restart/no redispatch,
and unreviewed overlap evidence rejecting missing/invalid custody.

The initial baseline run had 280 passes and one `QUEUE_POLICY_DRIFT`: controller
source was edited while the suite was running. That run remains failed and is
not used as acceptance. The later run used a fixed candidate. One intermediate
test assertion also failed because the old unit fixture's pinned Node executable
already lived directly inside its fake controller; the corrected assertion
checks that **new** reads add only the tool root, without rewriting legacy scope.

Logs are in `.test-runs/blender-*.log`, copied with hashes to the new ignored run
directory. These are offline control tests, not real Worker or native Blender proof.

## Continuation after pending decisions

1. Prepare the approved portable Linux tool in a fresh campaign; verify official
   checksum and bounded footprint. Freeze controller source and tool manifest.
2. Create a small new fixture with disjoint `scripts/chair/` and `scripts/lamp/`
   scopes, two Sol/medium tasks, budget 2/0/zero retry, independent failure mode.
3. Native zero-provider readiness must run Blender in both task scopes under the
   existing profile and resource limits. Test basic blend creation/opening,
   pinned validators, configured model/effort and tool inventory. Stop on failure.
4. Worker A intentionally reads one missing public leaf with the exact pinned
   absolute `cat` and absolute workspace path, then locates the correct README.
   Schedule this after main construction and before final pinned checks to keep
   recovery inside the unchanged 60-second/3-error budget. Worker B has no fault.
5. Use the existing Supervisor to dispatch exactly twice; preserve timestamped
   tool events, process overlap, raw completion/usage and cgroup samples.
6. Controller independently opens/validates each `.blend` with auto-execution
   disabled, hashes artifacts and checks exact diff and scratch separately.
   Leave successful tasks at REVIEW. No additional Reviewer is started.
7. Reopen the queue and evidence, prove no redispatch/stale publication, audit
   process cleanup. Distinguish real successful cleanup from zero-provider
   cancellation injection. Report all four verdicts independently.

No scaling above two is authorized. A later 2→5 proposal requires a measured
resource/capacity decision; this preparation cannot justify expansion.
