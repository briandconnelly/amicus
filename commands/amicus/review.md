---
description: Have another model (via amicus) review your git changes
argument-hint: "<backend> [working_tree|branch <base>|commit <sha>]"
---

Use the `amicus_review_changes` MCP tool from the amicus server to get an
independent code review of changes already represented in git.

Request: $ARGUMENTS

`backend` is required — amicus has no default backend. If the request does not name
one (`codex`, `kimi`, or `claude`), call `amicus_backends` first and choose only
among backends it reports `enabled: true` and `status.authenticated: true`.

Map the rest of the request to the tool's parameters: default `scope=working_tree`;
for a branch review pass `scope=branch` and `base=<branch>`; for a single commit pass
`scope=commit` and `commit=<sha>`. Pass the absolute repo path as `workspace_root`.
Optionally call `amicus_dry_run` first (free) to preview the scope and diff size —
that preview covers the input amicus assembles, not what the backend itself reads
during the paid run.

For a multi-file or whole-branch review that can exceed the synchronous deadline,
use `amicus_review_changes_async` instead and poll `amicus_job_status` for the
result — a sync call whose deadline expires still spends the paid run.

When findings come back, verify each one against the actual code before presenting
it — note which you confirm and which you think are false positives.
