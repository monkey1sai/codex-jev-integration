# Native sandbox diagnostic — 2026-10-08

Latest continuation: the existing Windows failure was not retried. A separately
installed official Linux CLI/bwrap now executes real restricted commands in
WSL2. This does not repair or certify Windows native sandbox. The admission
matrix and retained compatibility/lifecycle failures are recorded in
[the ADR](orchestrator-phase1-2.md#isolated-linux-admission-continuation--2026-10-08).
The isolated model worker is still NOT_RUN at the pre-execution checkpoint;
official login status and readiness now succeed. No mock
result has been substituted. Production reviewer/provider provenance remains
BLOCKED independently of Linux command-isolation evidence.

Status: **BLOCKED / ENVIRONMENT_FAILURE**. No native worker PASS is claimed.

## Checkpoint afe963a evidence, before external recovery

- Current CLI: `codex --version` → `codex-cli 0.161.0`.
- Current App package: `Get-AppxPackage -Name OpenAI.Codex` → `26.1002.7124.0`.
- Readback of selected non-secret global fields: `sandbox_mode="workspace-write"`,
  `approval_policy="on-request"`, `approvals_reviewer="auto_review"`,
  `[windows] sandbox="elevated"`.
- Named filesystem profiles use `":minimal"="read"` plus workspace-root access.
  This is configured policy evidence, not proof of the native process's effective permissions.
- Previous checkpoint's actual native preflight failed:
  `windows sandbox failed: elevated Windows sandbox requires effective :root read access`.
- The current session's tool sandbox independently failed before command startup:
  `helper_sandbox_lock_failed` on the sandbox helper directory. Scoped host reads
  and offline tests underwent auto-review. Their success does not validate native isolation.
- A read of the expected `managed_config.toml` location found no file. This does
  not establish absence of managed policies from other supported sources.

## Compatibility assessment

The [official Windows sandbox documentation](https://learn.chatgpt.com/docs/windows/windows-sandbox)
describes OS containment; the [official permissions documentation](https://learn.chatgpt.com/docs/permissions)
describes permission policy. Neither source establishes that this installed version
supports the currently selected minimal-read/elevated combination. The observed
error explicitly requires effective root-read, while selected profiles request
minimal-read. A configuration incompatibility is **INFERRED**, not a verified root cause.

The parent session's effective `:root` read entry does not prove the separately
launched CLI receives that entry. No supported fix preserving this exact boundary
was demonstrated. The CLI version and selected fields have not changed; an identical
native retry would add no new hypothesis. The existing retry budget was not reset.

## Preserved boundary and next evidence

No ACL, ownership, sandbox read grants, broad profile, Global production runtime,
hooks or authentication was changed. Native smoke is **NOT_RUN this continuation**;
the previous preflight remains failed, not reclassified as PASS.

Production supervisor, repo-command validators and native review acceptance remain
closed. Windows Job Objects limit process lifecycle; they do not provide filesystem,
network or controller-root custody isolation. Pinned executable hashes and fixture
review signatures likewise do not prove observed Astra identity or reviewer independence.

Revisit only with a new supported compatibility mechanism or version evidence.
Then verify effective worker permissions, controller-evidence write denial, observed
model/effort and independent review before enabling production admission. A global
maintenance operation would require its own bounded scope. Phase 3 remains unopened.

## After user-reported recovery — 2026-10-08

The App tool sandbox now starts PowerShell. Current App is **26.930.7945.0**;
its bundled CLI is **0.160.1**, while npm CLI remains **0.161.0**. This is a
successful App-tool observation, not a worker isolation or model smoke PASS.
The separate recovery session owns the downgrade; this continuation made no
installation, Global config, ACL, ownership or sandbox permission changes.

Read-only identity evidence: the App tool runs as `CodexSandboxOffline` with
only `SeChangeNotifyPrivilege` reported by `whoami /priv`. The worktree and
Git metadata are owned by the interactive account. Normal sandbox Git rejects
dubious ownership; scoped auto-reviewed host Git verified the expected HEAD
and clean starting status. No safe.directory exception was added. ACL readback
and token identity do not prove the separate worker's effective access.

## Version-matched root-cause evidence

The official [`rust-v0.161.0` source](https://github.com/openai/codex/blob/rust-v0.161.0/codex-rs/windows-sandbox-rs/src/resolved_permissions.rs#L95)
and [`rust-v0.160.1` source](https://github.com/openai/codex/blob/rust-v0.160.1/codex-rs/windows-sandbox-rs/src/resolved_permissions.rs#L95)
have the same elevated-policy check. They reject a policy when the command's
filesystem root cannot be read or is denied. This is a policy compatibility
check, distinct from an NTFS access-denied result from the requested command.

The new protocol probe used the npm native binary and official `command/exec`,
with no thread, turn or model request. A fresh isolated, credential-free
CODEX_HOME reproduced the existing `workspace-readonly` definition: minimal
read, workspace read, network disabled, elevated sandbox, on-request and
auto_review. It did not add root-read or switch to a more permissive profile.
This isolated reproduction does not claim all Global/managed layers were
cloned or that the synthetic CLI worker plan has identical effective policy.

| Evidence | Actual result | Classification |
|---|---|---|
| `initialize`, `config/read`, `permissionProfile/list` | Responses received; configured approvals are on-request/auto_review; named readonly profile listed | Protocol/config observation only |
| First `command/exec` with custom outputBytesCap | `-32600: custom outputBytesCap is not supported with windows sandbox` | TOOL_FAILURE; command did not run |
| Compatible request, native `whoami /user`, same readonly policy | `-32603: exec failed: windows sandbox: elevated Windows sandbox requires effective :root read access` | ENVIRONMENT_FAILURE / native policy incompatibility; command did not run |
| App-bundled CLI under the same profile | NOT_RUN | Version-matched source has the same check; no redundant native retry |
| Real Codex model worker | NOT_RUN / BLOCKED | Containment/effective launch policy not admitted |

The diagnostic script exited 0 after saving the JSON-RPC error. This means
the diagnostic completed, **not** that sandbox or worker execution passed.
Likewise, profile `allowed=true` means requirements allow selecting it; it
does not establish Windows backend compatibility or actual read/write access.

Evidence (ignored, retained locally):

- `runs/native-admission-npm-20261008/report.json`: first protocol rejection.
- `runs/native-admission-npm-compatible-20261008/report.json`: root-read rejection.
- `runs/production-admission-environment-20261008.json`: exact executable hashes,
  versions, current config hash and diagnostic token. No credential data.
- npm binary SHA-256: `a0f89acca07a511734cac7fddee26b2106fab68918717bc90df16104a0760a30`.
- App binary SHA-256: `3b8f6e33caa75f232558a3cf76ff9b87bb5ef6dbcf4996372f24e55c78b1b916`.

**VERIFIED:** the isolated minimal-read/elevated combination still fails on
installed npm 0.161.0. **UNVERIFIED:** exact effective production worker layers,
worker token, controller/Global/other-worktree/Git write denial, and network
containment. The old App helper lock/refresh failure and current Git ownership
failure remain separate issues; neither is proven to cause this policy rejection.

## Provenance and minimum next repair

Installed CLI's `app-server generate-json-schema --experimental` completed
without starting a server or model. Its Thread schema explicitly describes
model and reasoningEffort as configured state, not per-turn execution telemetry.
ThreadStartResponse exposes configuration; ReviewStartResponse and completed
Turn do not provide authenticated observed model/effort. Newer online docs
cannot be used to assume fields missing from this installed schema exist.

No supported repair preserving the minimal-read/elevated boundary was
demonstrated. Adding root-read, switching to unelevated/full-access, changing
ACLs or bypassing native containment is excluded. The minimum next step is a
version-matched upstream fix/support for that boundary, followed by a fresh
single-command isolation test under the exact authorized worker policy. A
separate verified effective-policy adapter is still needed before using legacy
worker flags; the current root-config guard is not full layer resolution.

Reviewer admission separately needs a trusted controller transport/identity,
challenge-bound execution receipts and actual model/effort provenance. Neither
restoring App command execution nor signing configured metadata solves that
gap. Production validators and real E2E therefore remain BLOCKED/NOT_RUN.

## Isolated Linux real attempt — 2026-10-08

The Windows root-read check was not repeated or relaxed. Isolated Linux
official CLI 0.161.0 executed native bwrap/seccomp canaries within scoped
artifact/scratch permissions. Controller/home/other-worktree paths were hidden,
Git/runtime were read-only, networking/host sockets were denied. WSL alone
remains unsuitable as the boundary; its host has writable DrvFS and privileged
memberships. Admission facts are summarized in the ADR matrix.

One actual provider turn ran with configured Sol/medium, thread
01a11a1c-2581-7311-ad7b-4a142dacb24d. Exit 0, real token usage and empty cgroup
were observed, but there was no file change or acceptance execution. The
engine error was `Code Mode is unavailable because code-mode host is disabled`.
This is a TOOL_FAILURE in controller runtime preparation, distinct from the
Windows root-read incompatibility. The smoke is FAILED_OR_UNKNOWN_NO_RETRY;
the exclusive original intent is retained and no second model was launched.

Only the disposable runtime was repaired: official same-version host was
hash-pinned and placed beside the custom CLI, and code_mode_host enabled.
No production/global config or native sandbox policy was changed. Actual
no-provider V8 protocol/API restrictions and host cancel/timeout/interruption
passed. Kernel cgroup limits were read back, not inferred from properties:
1 GiB memory, zero swap, 64 tasks/threads. Same-config native canaries and
failure/restart also passed. Host protocol tests do not prove the full model
tool chain or provider identity; that chain remains NOT_YET_VERIFIED.

Readiness now reports PREPARED_REEXECUTION_REQUIRES_NEW_AUTHORIZATION (exit 2).
The compatible candidate is ready for a separately authorized single attempt,
with all production gates kept closed. Real artifact acceptance, independent
review/provenance and production validator admission remain incomplete.
There is no pending model/scheduler process launched by this continuation.
