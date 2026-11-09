---
description: Get a read-only second opinion through an amicus backend harness
argument-hint: "<backend> <question>"
---

Get an independent second opinion from another harness — and, where you choose it, another
model — using the `amicus_consult` MCP tool from the amicus server.

Request: $ARGUMENTS

`backend` is required — amicus has no default backend. It names the harness (the CLI that
runs the call), not the model. Resolve the harness and model from the request by the routing
procedure in the `collaborating-with-amicus` skill (`references/choosing-a-backend.md` →
Routing procedure) and never substitute one silently: a named harness wins, and bare `kimi`
means the deprecated kimi harness. Whether or not the request names one, call
`amicus_backends` with `detail="full"` first and use only a harness it reports
`enabled: true` and `status.installed: true` and ready for the model
(`status.authenticated: true`, or for `pi` a `model` it lists); do not guess or fall
back to a favorite. For `pi`, pass `model` as an exact `provider/id` that
`amicus_models` lists for `pi`, unless `AMICUS_PI_MODEL` is set and names the model you mean;
pi's `status.authenticated` is unknown while that is unset. `kimi` is deprecated in favour of
`pi` (removal at or after 0.15.0). A `claude` consult defaults to
`access="toolless"`, so decide `access` up front when the answer needs the repository.

Pass the absolute repository path as `workspace_root` so the backend reasons about
the right project, and include any specific files or context the question needs as
`extra_context`. Never put a secret in `question` or `extra_context` — both travel
to the backend's provider raw (on `pi`, the provider the model's prefix names). Read-only
holds on every harness, but `pi` at startup renames the workspace's `.pi/commands/` to
`.pi/prompts/` when the latter does not exist. When the result comes back, treat the backend's
findings as claims to verify against the actual code, not settled fact.

For a high-reasoning-effort or broad repo-grounded consult that can exceed the
synchronous deadline, use `amicus_consult_async` instead: poll `amicus_job_status`
while its status is `running`, then fetch with `amicus_job_result` — a sync call
whose deadline expires still spends the paid run.
