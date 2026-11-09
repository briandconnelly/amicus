---
description: Have an amicus backend harness review your git changes
argument-hint: "<backend> [working_tree|branch <base>|commit <sha>]"
---

Use the `amicus_review_changes` MCP tool from the amicus server to get an
independent code review of changes already represented in git.

Request: $ARGUMENTS

`backend` is required — amicus has no default backend. It names the harness (the CLI that
runs the call), not the model. Resolve the harness and model from the request by the routing
procedure in the `collaborating-with-amicus` skill (`references/choosing-a-backend.md` →
Routing procedure) and never substitute one silently: a named harness wins, and bare `kimi`
means the deprecated kimi harness. Whether or not the request names one, call
`amicus_backends` with `detail="full"` first and use only a harness it reports
`enabled: true` and `status.installed: true` and ready for the model
(`status.authenticated: true`, or for `pi` a `model` it lists). For `pi`, pass `model` as an exact `provider/id` that
`amicus_models` lists for `pi`, unless `AMICUS_PI_MODEL` is set and names the model you mean;
pi's `status.authenticated` is unknown while that is unset. `kimi` is deprecated in favour of
`pi` (removal at or after 0.15.0). A
`pi` review is read-only except that pi at startup renames the workspace's `.pi/commands/` to
`.pi/prompts/` when the latter does not exist.

Map the rest of the request to the tool's parameters: default `scope=working_tree`;
for a branch review pass `scope=branch` and `base=<branch>`; for a single commit pass
`scope=commit` and `commit=<sha>`. Pass the absolute repo path as `workspace_root`.
Optionally call `amicus_review_changes_dry_run` first (free) to preview the scope and diff size —
that preview covers the input amicus assembles, not what the backend itself reads
during the paid run.

For a multi-file or whole-branch review that can exceed the synchronous deadline,
use `amicus_review_changes_async` instead: poll `amicus_job_status` while its
status is `running`, then fetch with `amicus_job_result` — a sync call whose
deadline expires still spends the paid run.

When findings come back, verify each one against the actual code before presenting
it — note which you confirm and which you think are false positives.
