---
description: Delegate a coding task to another model (via amicus); get back a reviewable diff
argument-hint: "<backend> <task>"
---

Use the `amicus_delegate` MCP tool from the amicus server to implement a
self-contained coding task in a throwaway worktree.

Request: $ARGUMENTS

`backend` is required — amicus has no default backend. `amicus_delegate` supports
`codex` and `kimi` only in v1 (Claude stays review-only) — do not route a delegate
request to `claude`. If the request does not name a backend, call `amicus_backends`
first and choose only among backends it reports `enabled: true`,
`status.authenticated: true`, and delegate listed under supported features.

Pass the absolute repository path as `workspace_root` and describe the task
precisely in `task`; never put a secret in `task` or `extra_context` — both travel
to the backend's provider raw.

**This never edits your working tree.** The tool returns a diff (`meta.job_id`,
`diff` in the result) — it does not apply it. Review the diff yourself before
applying it with your own tools.

For a task that can exceed the synchronous deadline, use `amicus_delegate_async`
instead and poll `amicus_job_status` for the result — a sync call whose deadline
expires still spends the paid run.
