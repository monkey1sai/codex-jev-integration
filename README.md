# Codex Jev integration

Jev 2.2 is a standard-library-only MCP server for advisory role and resource selection in Codex CLI and App. It exposes six tools: `jev_status`, `jev_route`, `jev_report_outcome`, `jev_select_resources`, `jev_decide`, and `jev_report_selection_outcome`.

This repository versions the four runtime modules, a nonsecret configuration example, the interface contracts, and 85 offline regression tests. The runtime files match the reviewed integration payload. Machine-specific maintenance launchers, permission drafts, live Codex configuration, journals, and backups remain outside this source repository.

## Behavior and boundaries

`jev_decide` shares the task goal, success criteria, environment, constraints, evidence, unknowns, and complete eligible candidate descriptions across separate Choice questions. Missing critical context returns to Codex. Required resources remain authoritative. Candidate freshness, dependency/conflict checks, response validation, and confidence fallback run locally.

The tools do not execute resources, launch agents, switch models, change permissions, or approve actions. Deterministic review gates run before provider requests. Observations and outcomes retain `caller_reported` provenance; reported completion is not independent execution verification.

The fixed TypeSafe endpoint is `https://api.typesafe.ai/v1/systemone`, using `jev-latest`. Requests are single-attempt, do not follow redirects, and bound request/response bytes. Only sanitized input with explicit transmission and inference authorization may be sent. Credential values belong in a supported local provider, never in this repository, command arguments, or chat.

## Run locally

Python 3.12 was used for offline validation; no package installation is required.

```powershell
python -B payload/jev/decision.py serve --config payload/jev/config.json
```

`serve` uses newline-delimited JSON-RPC on standard input/output. The configuration contains only enabled/confidence/timeout/observability settings. The caller supplies an explicit existing absolute workspace. A workspace `.codex/jev.json` may override supported settings; it cannot change the provider endpoint or credential source.

## Configure Codex

Merge the following MCP entry into the supported Codex configuration for the intended scope. Replace the two absolute path placeholders with the Python executable and this repository's runtime file. Retain existing permissions, sandbox, approval policy, and reviewer settings. Review and back up a global configuration diff before applying it.

```toml
[mcp_servers.jev_decision]
command = "<absolute Python executable path>"
args = ["-B", "<absolute repo path>/payload/jev/decision.py", "serve"]
enabled_tools = ["jev_status", "jev_route", "jev_report_outcome", "jev_select_resources", "jev_decide", "jev_report_selection_outcome"]
tool_timeout_sec = 25
```

The server uses the adjacent `config.json` by default. Tool loading does not require permanent write access to global integration code. Confirm the actual tools and make a native status/gate call in the intended CLI or App session after supported loading/reconnection; files on disk or an auxiliary stdio smoke alone do not verify that session.

## Tests and evidence

Run both commands in [tests/README.md](tests/README.md). The export passed 73 runtime/regression tests and 12 inventory tests, with no skips and no provider requests. Source tests, native App calls, native CLI calls, installation checks, and full-task comparisons are separate claims.

The prior native App integration exposed all six tools and successfully called status, a deterministic `jev_decide` gate, and outcome reporting without provider inference. Native CLI health/runtime acceptance in that installation was blocked before process startup by a Windows sandbox setup error. This source export does not repair or close that environment gap. The full Codex-only versus Codex-plus-Jev task comparison has not run; no cost, speed, or quality improvement is claimed.

## Contracts

- [Role and resource selection](docs/codex-jev.md)
- [Legacy resource selection](docs/codex-jev-resources.md)
- [Combined context and observation contract](docs/codex-jev-context.md)

Global maintenance remains a separate operation: audit exact targets, stage verified backups and hashes, obtain applicable independent review, apply only the bounded diff, then verify the actual CLI/App and preserve concurrent changes. This repository does not provide the earlier machine-specific transactional installer.
