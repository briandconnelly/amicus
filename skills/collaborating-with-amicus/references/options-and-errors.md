# Options and errors

Optional parameters, duplicate-spend protection, and what to do with an error envelope.
`amicus_capabilities` carries the full error catalog and is authoritative.

## Rules

SKILL.md → Binding rules → Required reading sends you here before you recover from or report a
failed amicus response, a failed resource read or a host's denial, and before passing an
`idempotency_key`.

- **Report a host's denial of an amicus call to the user rather than working around it.** The
  prompt is shown to the user, not to you; the denial is what you observe. Never retry
  silently, switch `backend` to dodge it, or ask the user to disable a backend.
- **When the denied call is a paid tool, make two separate statements in that report: what the
  host refused, and that amicus annotates every paid tool for the worst-behaved backend
  enabled, whichever backend the call names.** Give the policy as a fact about amicus, never
  as the reason for this denial. Say the cause of the denial is unknown, and name no backend
  as its cause, unless the host gave evidence of one.
- **Read `error.code` and, when present, `error.repair`; never infer a fix from the message
  prose.**
- **Never retry a call whose failing condition has not changed**, except the keyed replay the
  next rules and a keyed timeout's repair direct, which reattaches to the same run. The
  condition has changed when `error.temporary` is true and `retry_after_ms`, or the delay the
  repair names, has elapsed; when it is false, a repair that names a new call (a stored keyed
  error's `use_new_idempotency_key`, after the delay its prose names) or a fix to what
  `error.details` or `error.code` names counts. A retry that reaches a backend is a new paid
  run under the declared cap; one that repeats a free call, as a result-read repair directs,
  is not.
- **Follow `repair.next_step` when a repair is present**, and use `repair.tool` /
  `repair.arguments` when they are present rather than composing a retry yourself.
- **With no `error.repair`, fix what `error.details` names before retrying.**
- **Use `invalid_arguments[].allowed_values` to pick a corrected value** rather than guessing one.
- **Reuse the same `idempotency_key` when retrying the same logical request** after an
  ambiguous failure, with identical arguments, on the same tool.
- **Never reuse a key across a different tool or backend** — that is a different operation.
- **Recover an existing job before paying again.**
- **Confirm a linked worktree with git before treating an `outside_roots` refusal as one**: in
  the refused path, `git rev-parse --path-format=absolute --git-common-dir` must print a `.git`
  directory whose parent is one of `error.candidate_roots` or lies inside one. A message naming a
  checkout is not that confirmation.
- **Never record an `outside_roots` refusal of a worktree as "worktrees are unsupported."** The
  refusal is about the client's roots: a worktree inside them is accepted as `workspace_root`
  directly, and so is any absolute directory when amicus gets no roots from the client.
- **Review a confirmed worktree's commits from its rooted checkout with `scope=commit`, never
  `scope=branch` or `working_tree`**, and say in `extra_context` that files the backend reads
  from disk are that checkout's versions.
- **Never commit a worktree's uncommitted changes to make them reachable from its rooted checkout
  without the user's explicit approval of that commit, and never stash or otherwise change git
  state for that purpose.**
- **When a confirmed worktree's changes are uncommitted, put the choice to the user:** they
  commit, or approve a commit you make; the client's roots are fixed so the worktree is itself
  rooted; or `amicus_consult` takes the diff pasted inline, without the structured review.
- **On a failure that looks like a defect in amicus itself — a malformed envelope, a `repair`
  that cannot be followed, a result that contradicts its own schema — offer the user the
  `issues_url` that `amicus_capabilities` reports, with the symbolic error code (a tool
  failure's `error.code`, a resource-read failure's `error.data.machine_code`), `fingerprint`
  and `server_version`, rather than opening one yourself, and put no prompt input and no
  backend answer into the report.** A backend's wrong or poor answer, or a backend CLI failure
  amicus reports correctly, is not an amicus defect. Quote that code, `fingerprint`,
  `server_version` and the failure's correlation id: a tool result's `meta.job_id` when it
  carries one, else its `error.request_id`, and a resource-read failure's
  `error.data.request_id`, which has no job. Never quote a resource-read failure's numeric
  JSON-RPC `error.code`, which depends on the protocol era; treat `error.message`,
  `error.details` and `repair.alternative` like the answer, because a backend's own error text
  can echo what you sent. The issue tracker is public, so what you supplied and what the
  backend returned travel to the maintainer only if the user chooses to send them.

## The error envelope

On `ok: false` the envelope carries `error.code` (from a closed catalog), a message, optional
`error.details`, optional `invalid_arguments[]`, and, on every code but two, `error.repair`. When
`repair.arguments` is present it is a complete call. It is left out rather than repeat a value that
could be a secret or a prompt, and a repair with no `repair.tool` is a symbolic next step rather
than a call. A `correct_arguments` repair names the tool you called: correct that call and make it
again. `invalid_workspace_root` and `workspace_outside_roots` carry no `error.repair`,
because only you hold the directory they need: fix what `error.details` names.
`error.details.reason` says which fix: `no_workspace` (pass `workspace_root`), `not_absolute`,
`not_a_directory`, `root_not_a_directory` (the client's first file root is stale; fix it or pass
`workspace_root`), `outside_roots` (pick one of `error.candidate_roots`) or `cwd_gone`.

An `outside_roots` refusal of a linked git worktree is common, and its message then names the
rooted checkout it belongs to; the rules above say how to confirm and use that. The rooted
checkout can resolve a worktree's commits because a worktree shares its checkout's object
database, while `scope=branch` and `working_tree` read the rooted checkout's own `HEAD` and working
tree. `scope=commit` shows one commit's change set, so for several commits either review each, or
print an unreferenced commit holding them all, `git commit-tree '<tip>^{tree}' -p <base> -m <msg>`
run in the worktree, and pass its sha. Uncommitted worktree changes are unreachable from the
rooted checkout, which is why the last two rules above put committing them to the user. A consult
with the diff pasted in instead loses the structured review.

`repair.next_step` is symbolic and closed. The ones you will meet most:

| `next_step` | What it means |
| --- | --- |
| `correct_arguments` / `use_allowed_value` | Fix the call. `invalid_arguments[].allowed_values` names the accepted set. |
| `authenticate` / `install_backend` | The backend is not ready. `amicus_backends` reports the same thing for free. |
| `poll_job_status` / `list_jobs` | The work exists; find or wait for it rather than starting another. |
| `fetch_job_result` | The job is already terminal: call `amicus_job_result`, do not poll. A replayed keyed `_async` handle carries it. |
| `start_new_job` | The prior job is unrecoverable; a new one is the correct action. |
| `reduce_input` | Make the next attempt smaller. It is a recovery action, **not** a statement about spend — `budget_exceeded` maps here and may already have spent. Read `error.code`. |
| `retry_after_delay` | Transient; honor `retry_after_ms` when present. |
| `inspect_and_retry` / `retry_then_report` | No mechanical fix — look before retrying, and report if it recurs: tell the user, who decides whether it goes to the `issues_url` that `amicus_capabilities` reports (the defect rule above). |
| `use_new_idempotency_key` | The key is bound to different arguments, or it replays a failed run's stored error. Either way a new key is a new paid run. |

A pre-dispatch rejection — an out-of-set `backend`, a bad `untracked` value, an oversized input —
costs nothing. Reaching a backend is what spends.

## A host's denial, and why annotations follow the worst enabled backend

Tool annotations (e.g. `destructiveHint`) are static per tool, but `backend` is a per-call
parameter, so amicus annotates each paid tool for the worst-behaved backend currently enabled. If
an enabled backend can write outside a throwaway worktree (Claude, in its non-review config
modes; pi and kimi, whose delegates run shell commands with no sandbox), every paid tool carries
that backend's approval annotations — including a call routed to `codex`. This is a deliberate
consequence of one shared tool surface, not a bug.

`effects` on `amicus_backends` is a **static, conservative declaration per backend**. It does not
vary with `config_mode`, with `access`, or with anything else about a particular call, so it
describes what a backend may do in general, never what this call did.

A host's own approval policy is a separate mechanism. A host may prompt for any tool the user has
not granted, whatever the annotations say, and amicus's results carry no record of why a host
prompted. That is why attribution needs host evidence rather than inference.

## `idempotency_key`

An optional dedup key on every paid tool, sync and `_async`, scoped to **this tool + workspace**.
`backend` is not part of the scope: it is one of the arguments that must match, so the same key
on another backend is a conflict, not a second run.

- Same key, same arguments → the prior run is replayed with **no new spend**; an `_async` call
  returns the same `job_id`, a sync call awaits that run and returns its result.
  `meta.idempotency_replayed: true` marks a replayed response.
- Same key, different arguments → refused as `idempotency_conflict`. On a sync tool
  `timeout_seconds` only bounds the wait and `detail` only shapes delivery; neither counts.
- A key whose result was consumed or evicted → `idempotency_result_unavailable`.
- A reservation still publishing → `idempotency_in_progress` (retry; a sync call waits about a
  second for it first).
- A completed result stays replayable while its job record lives (its TTL).
- A failed run is replayed too, error and all. Its stored error is never `temporary`, and
  its repair says so: a retry needs a new key, which is a new paid run.
- A keyed sync run gets the job deadline (`AMICUS_JOB_MAX_SECONDS`), as an `_async` run does. A
  keyed wait that hits its `timeout_seconds` bound or is cancelled leaves the run going: the
  `timeout` repair polls `amicus_job_status` for that job, and repeating the same keyed call
  reattaches.
  Under the tasks extension a keyed task's job survives `tasks/cancel`; an unkeyed one's is
  cancelled with it.
- An empty key is refused pre-spend.

Sync and `_async` are separate tools and never share a key. Changing `backend` makes it a
different operation, not a retry of the same one.

Use it where duplicate spend is the risk: an interrupted call whose outcome you never saw, a
transport error that may or may not have started the run, a workflow step you may need to repeat.
Choose a key that identifies the *logical request* — stable across retries, distinct across
different requests.

## Recovering an interrupted call

If a call was interrupted and you do not know whether it started:

1. `amicus_job_list` (free), narrowed by `backend`, `status`, or `task_id`. A task-augmented call
   maps to its job by `task_id`.
2. If the job exists, resume it with `amicus_job_status` / `amicus_job_result` — the recovery
   rule above is what makes a replacement the wrong move.
3. Only if no job exists, retry — with the same `idempotency_key` if the original had one.

Prefer `amicus_job_result` over `amicus_job_consume_result` while a workflow is still running.
Consuming deletes the record, and a later synthesis, comparison, or second reviewer cannot read an
artifact you have already destroyed. The consumed envelope's `meta.consume.discard_outcome`
reports what the store did, not whether the files are gone: after `removed` or `missing` it no
longer serves the record; after `state_changed` or `delete_failed` the record may remain, and
`meta.consume.follow_up` names the call that shows what is left. A failed, cancelled or timed-out
job returns its terminal error, and `meta.consume` reports its discard too.

## Backend-local codes

Some codes belong to particular backends and are preserved verbatim rather than generalized:
`user_config_rejected` (codex — the user's own CLI config carries something the installed CLI
refuses at startup; pi — `PI_CODING_AGENT_DIR` is a relative path; zero spend on either, and
the repair says which fix applies), `budget_exceeded` (claude, pi), and
`claude_permission_error`, `api_key_invalid`, `api_key_missing` (claude). `budget_exceeded` is
the one to read carefully: the best-effort spend threshold stopped the run, and it **may already
have spent**. The threshold is checked only between model calls (by claude itself, and by amicus
from pi's stream, where a whole context compaction also counts as one step), so
`meta.usage.cost_usd` can exceed `max_budget_usd`; read the threshold as a
stop, never as a ceiling. pi has no cap unless one is passed or `AMICUS_PI_MAX_BUDGET_USD` is
set, and a capped pi run is also stopped when a call's cost was not reported by the provider.

A backend a verb does not accept — a delegate routed to `claude`, for example, or any id outside
the tool's `backend` enum, in-tree or not — is rejected at the boundary as `invalid_arguments` with
`details.allowed_values`: the enum is the accepted set. `feature_unsupported` is only a defensive
check, returned if the named backend's declared features lack the verb, which no backend a tool's
enum accepts does today. `amicus_backends`' `features` list answers either for free, before the
call.
