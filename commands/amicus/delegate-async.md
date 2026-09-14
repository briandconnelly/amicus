---
description: Delegate a coding task to another model (via amicus) in the background; get a job_id to poll
argument-hint: "<backend> <task>"
---

Use the `amicus_delegate_async` MCP tool from the amicus server to implement a
self-contained coding task in a throwaway worktree, in the background.

Request: $ARGUMENTS

`backend` is required — amicus has no default backend. `amicus_delegate_async`
supports `codex` and `kimi` only in v1 (Claude stays review-only) — do not route a
delegate request to `claude`. If the request does not name a backend, call
`amicus_backends` with `detail="full"` first and choose only among backends it reports
`enabled: true`, `status.authenticated: true`, and delegate listed under supported
features.

Pass the absolute repository path as `workspace_root` and describe the task
precisely in `task`; never put a secret in `task` — it travels to the backend's
provider raw. `task` is the only free-text field this tool carries — it takes no
extra-context argument.

Make the one call, then report the `job_id` from the returned handle and stop; do not
wait on the job here. Starting it commits to spend: it runs to completion or to its
deadline (`AMICUS_JOB_MAX_SECONDS`, default 1800s) whether or not anyone polls it.
Collect it later with `/amicus:jobs`, which polls `amicus_job_status` and fetches with
`amicus_job_result` once the status is anything but `running`.

**This never edits your working tree.** A finished job carries a diff; it does not
apply it. Review the diff yourself before applying it with your own tools.

Pass a fresh `idempotency_key` on the start call. If that call then fails ambiguously in
transport, look for the job with `amicus_job_list` first; only if none exists, retry this
same tool with the same arguments and the same key, which replays the job instead of
starting a second paid run. Never switch to `amicus_delegate` expecting the key to
carry over: sync and async are separate tools and never share one.
