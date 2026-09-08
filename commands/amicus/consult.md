---
description: Ask another model (via amicus) for a read-only second opinion
argument-hint: "<backend> <question>"
---

Ask another model for an independent second opinion using the `amicus_consult` MCP
tool from the amicus server.

Request: $ARGUMENTS

`backend` is required — amicus has no default backend. If the request does not name
one (`codex`, `kimi`, or `claude`), call `amicus_backends` first and choose only
among backends it reports `enabled: true` and `status.authenticated: true`; do not
guess or fall back to a favorite.

Pass the absolute repository path as `workspace_root` so the backend reasons about
the right project, and include any specific files or context the question needs as
`extra_context`. Never put a secret in `question` or `extra_context` — both travel
to the backend's provider raw. When the result comes back, treat the backend's
findings as claims to verify against the actual code, not settled fact.

For a high-reasoning-effort or broad repo-grounded consult that can exceed the
synchronous deadline, use `amicus_consult_async` instead and poll `amicus_job_status`
for the result — a sync call whose deadline expires still spends the paid run.
