# Codex + Jev handoff — explicit execution only

Updated: 2026-10-13 (Asia/Taipei).

## Current user decision

- Keep the working Codex/Jev integration. The user reports Jev is usable.
- Stop the four-worker animation effort. Do not start new agents, campaigns,
  provider checks or Jev experiments as part of this handoff.
- Deliver source, methods and honest verification state through Git.
- A global opt-in-only candidate was prepared but the user chose **NOT APPLIED**.
  Do not treat this document as permission to apply it or restart old work.

## Using the retained integration

Continue ordinary work in Codex App or CLI from the intended project repository.
The current agent can read, edit and verify the project directly. Jev offers an
advisory choice when there are several eligible roles, tools or skills; it does
not start them, grant permissions, approve tests, waive review or merge code.

Example operator request:

> Work on this repository with the current Codex agent. Use the existing Jev
> advisory integration only if the choice between eligible resources is
> ambiguous. Do not launch subagents or a campaign. Run the necessary local
> checks, then report the diff and create the authorized local checkpoint.

All six MCP interfaces remain documented in [the main README](../README.md),
[role/resource selection](codex-jev.md) and [context selection](codex-jev-context.md).
Credentials remain in their supported local provider; never put them into a
task, repository, command argument or handoff report. The repo configuration
example is not the user's installed production configuration.

## Optional Agent Factory source

The preserved Phase 1–2 implementation includes task DAGs, durable queue,
deterministic routing, worktree allocation, lease/fencing, failure isolation,
validators, independent review and local integration validation. It remains
available as source for a future explicit request, not an automatic global job.

- [ADR and history](orchestrator-phase1-2.md)
- [Native-trust Development Mode](development-execution-mode.md)
- [Bounded parallel entry](../tools/repo_parallel_campaign.py)
- [Recovery policy](parallel-worker-recovery.md)
- [File/worker isolation](parallel-worker-isolation.md)

`--prepare` performs zero-provider readiness. `--execute` requires a fresh,
explicitly authorized campaign with exact task, dispatch/review budgets and
capacity. Historical attempts and consumed budgets cannot be replayed or reset.
Do not infer live execution from mock commands or enqueue/status operations.
The custom implementation still caps active workers at two; this handoff does
not increase that cap. Native four-agent artwork was a separate, now stopped
activity, not an Agent Factory four-worker acceptance result.

## Global state and proposed opt-in boundary

The installed global configuration was read and its original hashes were
rechecked unchanged after the user declined application. In that observed
configuration Jev is enabled and native `multi_agent` is still `true`. No global
disablement or fresh-session enforcement is claimed.

The unapplied, reversible candidate would set native `multi_agent=false`,
disable global discovery of `configure-jev-repo`, and mark global orchestration
instructions as historical/explicit opt-in. It would leave the Jev MCP,
models/effort, sandbox, permissions, approvals, other pre-existing tools and
credentials unchanged. Live configuration and full backups are not tracked here.

The request not to launch workers is an operator constraint in the current
session. A policy document cannot itself prove machine enforcement. A future
global application needs a new authorized maintenance operation and fresh CLI/
App readback; the existing Windows sandbox failure must remain visible.

## Verified delivery and limits

The feature head `c6e7faad2eedc2aba35a611a6c758528ba2f44d2` was merged by
[PR #1](https://github.com/monkey1sai/codex-jev-integration/pull/1) into main at
`a7f3311c936676da5fd2239dc0ad2792bdc09faf`. GitHub MERGED state, main base and
merge-commit reachability in fetched `origin/main` were verified.

At that reviewed feature head:

| Check | Actual result |
|---|---|
| Orchestrator unittest discovery | 289 PASS |
| Jev offline regression | 77 PASS |
| Inventory offline regression | 12 PASS |
| Total | 378 PASS; source/offline evidence only |
| Independent source/tools review | Accept; confirmed findings repaired |
| Independent tests/docs review | Accept for reviewed snapshot |
| Remote CI | NOT_RUN; no configured workflows/check runs |
| New provider/Worker/Jev verification for this handoff | NOT_RUN |
| Global candidate | NOT APPLIED, at user's request |
| Windows Codex Doctor baseline | BLOCKED: existing sandbox provisioning FAIL |
| High-assurance Production Admission | BLOCKED; historical verdicts preserved |
| Animation v2 | Stopped WIP; no completed v2 movie/browser acceptance |

The two repaired findings are raw RPC config/error disclosure in validator
evidence and a synthetic recovery probe missing the successful matching command.
The fix retains the actual native permission check and the original failure
event; it does not relax execution or acceptance policy.

The stopped artwork snapshot is kept in a separate local Git repository with
its own WIP handoff. No new artwork remote, PR, render, capture or publication is
authorized or implied here.
