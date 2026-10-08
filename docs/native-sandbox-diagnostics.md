# Native sandbox diagnostic — 2026-10-08

Status: **BLOCKED / ENVIRONMENT_FAILURE**. No native worker PASS is claimed.

## Observed evidence

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
