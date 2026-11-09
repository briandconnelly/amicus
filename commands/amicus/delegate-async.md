---
description: Delegate a coding task to an amicus backend harness in the background; get a job_id to poll
argument-hint: "<backend> <task>"
---

Use the `amicus_delegate_async` MCP tool from the amicus server to implement a
self-contained coding task in a throwaway worktree, in the background.

Request: $ARGUMENTS

`backend` is required — amicus has no default backend. It names the harness (the CLI that
runs the call), not the model. Resolve the harness and model from the request by the routing
procedure in the `collaborating-with-amicus` skill (`references/choosing-a-backend.md` →
Routing procedure) and never substitute one silently: a named harness wins, and bare `kimi`
means the deprecated kimi harness. Whether or not the request names one, call
`amicus_backends` with `detail="full"` first and use only a harness it reports
`enabled: true`, `status.installed: true`, ready for the model
(`status.authenticated: true`, or for `pi` a `model` it lists), and with delegate listed
under supported features. `amicus_delegate_async` supports `codex`, `kimi` and `pi` only — `claude`
has no delegate, whatever model it runs, so offer `pi` with a listed model instead.
For `pi`, pass `model` as an exact `provider/id` that
`amicus_models` lists for `pi`, unless `AMICUS_PI_MODEL` is set and names the model you mean;
pi's `status.authenticated` is unknown while that is unset. `kimi` is deprecated in favour of
`pi` (removal at or after 0.15.0). `kimi` and `pi` run the task with no OS sandbox and no network
block; only `codex` has both.

Pass the absolute repository path as `workspace_root` and describe the task
precisely in `task`; never put a secret in `task` — it travels to the backend's
provider raw. `task` is the only free-text field this tool carries — it takes no
extra-context argument.

Make the one call, then report the `job_id` from the returned handle and stop; do not
wait on the job here. Starting it commits to spend: it runs to completion or to its
deadline (`AMICUS_JOB_MAX_SECONDS`, default 1800s) whether or not anyone polls it.
Collect it later with `/amicus:jobs`, which polls `amicus_job_status` and fetches with
`amicus_job_result` once the status is anything but `running`.

**amicus does not apply the patch.** A finished job carries a diff and amicus itself writes
nothing to your working tree; on `kimi` and `pi`, which have no sandbox, the backend's own commands are
not confined to the throwaway worktree. Review the diff yourself before applying it with your own tools.

Pass a fresh `idempotency_key` on the start call. If that call then fails ambiguously in
transport, look for the job with `amicus_job_list` first; only if none exists, retry this
same tool with the same arguments and the same key, which replays the job instead of
starting a second paid run. Never switch to `amicus_delegate` expecting the key to
carry over: sync and async are separate tools and never share one.
