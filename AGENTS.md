# Repository instructions

Use Traditional Chinese for operator reports. This repository contains the bounded Jev advisory MCP integration and its offline regression tests.

- Read affected source and tests, preserve unrelated edits, and use `apply_patch` for hand edits.
- Keep the standard-library-only runtime and existing payload layout. Decisions are advisory; they grant no execution, permissions, model switch, approval, or verified task completion.
- Before committing, run both offline unittest commands in `tests/README.md`, inspect `git status`, the full staged diff and file list, and run `git diff --cached --check`.
- Never track credentials, credential stores, live Codex configuration, private profile paths, audit journals, session logs, caches, compiled files, generated fixtures, or task-specific installation backups.
- Global installation and configuration writes require a separate bounded, reviewed maintenance operation. Preserve the caller's sandbox and approval reviewer. This source repo is not an installer or a global permissions grant.
- Provider requests require authorized sanitized input and an explicit available inference budget. Offline tests and status calls do not establish provider quality, speed, cost, or full-task benchmark results.
- Use scoped commits. Remote writes require an explicit destination/branch authorization. Never force-push or weaken ownership, ACL, sandbox, review, or branch protection to overcome a failure.
