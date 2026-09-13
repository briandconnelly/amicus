# Migration guide

amicus replaces three older single-model servers: `codex-in-claude`, `moonbridge`, and `claude-in-codex`.
Each sibling's tools, environment variables, and jobs now live behind one server with `backend` as a parameter.
This guide covers the environment-variable renames, the tool-name mapping for each sibling, and the behavior changes a migrating user actually hits.

## Environment variables

Every `AMICUS_*` name below is declared once in `src/amicus/config/envspec.py` (global) and each backend's `config.py` (per backend).
A sibling's old name still works during the deprecation window: it is read only when the new `AMICUS_*` name is unset, and every such read logs a warning.
Setting both the `AMICUS_*` name and a legacy name to different values is an error, not a silent override; two legacy names for the same setting that disagree is also an error.
Legacy names are removed in `0.3.0`.

| amicus name | legacy names | default |
| --- | --- | --- |
| `AMICUS_BACKENDS` | — | — |
| `AMICUS_TIMEOUT_SECONDS` | `CODEX_IN_CLAUDE_TIMEOUT_SECONDS`, `MOONBRIDGE_TIMEOUT_SECONDS`, `CLAUDE_IN_CODEX_TIMEOUT_SECONDS` | `300` |
| `AMICUS_MAX_INPUT_BYTES` | `CODEX_IN_CLAUDE_MAX_INPUT_BYTES`, `MOONBRIDGE_MAX_INPUT_BYTES`, `CLAUDE_IN_CODEX_MAX_INPUT_BYTES` | `200000` |
| `AMICUS_JOB_TTL` | `CODEX_IN_CLAUDE_JOB_TTL`, `MOONBRIDGE_JOB_TTL`, `CLAUDE_IN_CODEX_JOB_TTL` | `86400` |
| `AMICUS_JOB_MAX_SECONDS` | `CODEX_IN_CLAUDE_JOB_MAX_SECONDS`, `MOONBRIDGE_JOB_MAX_SECONDS`, `CLAUDE_IN_CODEX_JOB_MAX_SECONDS` | `1800` |
| `AMICUS_JOB_MAX_COUNT` | `CODEX_IN_CLAUDE_JOB_MAX_COUNT`, `MOONBRIDGE_JOB_MAX_COUNT`, `CLAUDE_IN_CODEX_JOB_MAX_COUNT` | `50` |
| `AMICUS_MAX_OUTPUT_BYTES` | `CODEX_IN_CLAUDE_MAX_OUTPUT_BYTES`, `MOONBRIDGE_MAX_OUTPUT_BYTES`, `CLAUDE_IN_CODEX_MAX_OUTPUT_BYTES` | `10485760` |
| `AMICUS_MAX_DELEGATE_DIFF_BYTES` | `CODEX_IN_CLAUDE_MAX_DELEGATE_DIFF_BYTES`, `MOONBRIDGE_MAX_DELEGATE_DIFF_BYTES`, `CLAUDE_IN_CODEX_MAX_DELEGATE_DIFF_BYTES` | `200000` |
| `AMICUS_GIT_TIMEOUT_SECONDS` | `CODEX_IN_CLAUDE_GIT_TIMEOUT_SECONDS`, `MOONBRIDGE_GIT_TIMEOUT_SECONDS`, `CLAUDE_IN_CODEX_GIT_TIMEOUT_SECONDS` | `60` |
| `AMICUS_STATE_DIR` | — | — |
| `AMICUS_LOG_LEVEL` | `CODEX_IN_CLAUDE_LOG_LEVEL`, `MOONBRIDGE_LOG_LEVEL` | `WARNING` |
| `AMICUS_LOG_FILE` | `CODEX_IN_CLAUDE_LOG_FILE`, `MOONBRIDGE_LOG_FILE` | — |
| `AMICUS_TASKS` | — | `0` |
| `AMICUS_TASKS_BACKEND_URL` | — | `memory://` |
| `AMICUS_HOST_NAME` | — | — |
| `AMICUS_ALLOW_CWD_WORKSPACE` | — | `0` |
| `AMICUS_CODEX_BIN` | `CODEX_IN_CLAUDE_CODEX_BIN` | — |
| `AMICUS_CODEX_EXTRA_ARGS` | `CODEX_IN_CLAUDE_EXTRA_ARGS` | — |
| `AMICUS_CODEX_MODEL` | `CODEX_IN_CLAUDE_MODEL` | — |
| `AMICUS_CODEX_REASONING_EFFORT` | `CODEX_IN_CLAUDE_REASONING_EFFORT` | — |
| `AMICUS_CODEX_ISOLATION` | `CODEX_IN_CLAUDE_ISOLATION` | `inherit` |
| `AMICUS_CODEX_SUPPORTED_VERSIONS` | `CODEX_IN_CLAUDE_SUPPORTED_VERSIONS` | — |
| `AMICUS_KIMI_BIN` | — | — |
| `AMICUS_KIMI_EXTRA_ARGS` | `MOONBRIDGE_EXTRA_ARGS` | — |
| `AMICUS_KIMI_MODEL` | `MOONBRIDGE_MODEL` | — |
| `AMICUS_KIMI_REASONING_EFFORT` | `MOONBRIDGE_REASONING_EFFORT` | — |
| `AMICUS_KIMI_ISOLATION` | `MOONBRIDGE_ISOLATION` | `inherit` |
| `AMICUS_KIMI_SUPPORTED_VERSIONS` | `MOONBRIDGE_SUPPORTED_VERSIONS` | — |
| `AMICUS_CLAUDE_BIN` | — | — |
| `AMICUS_CLAUDE_CONFIG_MODE` | `CLAUDE_IN_CODEX_CLAUDE_CONFIG` | `inherit` |
| `AMICUS_CLAUDE_ACCESS` | `CLAUDE_IN_CODEX_ACCESS` | `toolless` |
| `AMICUS_CLAUDE_MODEL` | `CLAUDE_IN_CODEX_MODEL` | — |
| `AMICUS_CLAUDE_REASONING_EFFORT` | `CLAUDE_IN_CODEX_EFFORT` | `xhigh` |
| `AMICUS_CLAUDE_MAX_BUDGET_USD` | `CLAUDE_IN_CODEX_MAX_BUDGET_USD` | `1.0` |
| `AMICUS_CLAUDE_SUPPORTED_MAJORS` | `CLAUDE_IN_CODEX_SUPPORTED_MAJORS` | — |

`AMICUS_KIMI_BIN` and `AMICUS_CLAUDE_BIN` have no legacy alias, because neither `moonbridge` nor `claude-in-codex` offered a CLI-path override to rename.
`AMICUS_CODEX_BIN` does have one — `CODEX_IN_CLAUDE_CODEX_BIN`, as the table above shows — because `codex-in-claude` did.
`AMICUS_STATE_DIR`, `AMICUS_TASKS`, `AMICUS_TASKS_BACKEND_URL`, `AMICUS_HOST_NAME`, `AMICUS_ALLOW_CWD_WORKSPACE`, `AMICUS_BACKENDS`, `AMICUS_KIMI_BIN`, and `AMICUS_CLAUDE_BIN` are new in amicus and have no sibling equivalent.

## Tool-name mapping

Most amicus tools take `backend` as a required parameter (no default); pick `"codex"`, `"kimi"`, or `"claude"` to reproduce a sibling's behavior.
`amicus_backends` and `amicus_job_list` take `backend` as an optional filter instead (omit it to see every backend or every job).
`amicus_capabilities` has no `backend` parameter at all: it reports the whole server (tool inventory, fingerprint, error catalog), not one backend's readiness — use `amicus_backends(backend=...)` for that.

### From `codex-in-claude`

| old tool | new call |
| --- | --- |
| `codex_consult` | `amicus_consult(backend="codex", ...)` |
| `codex_consult_async` | `amicus_consult_async(backend="codex", ...)` |
| `codex_review_changes` | `amicus_review_changes(backend="codex", ...)` |
| `codex_review_changes_async` | `amicus_review_changes_async(backend="codex", ...)` |
| `codex_delegate` | `amicus_delegate(backend="codex", ...)` |
| `codex_delegate_async` | `amicus_delegate_async(backend="codex", ...)` |
| `codex_delegate_dry_run` | `amicus_delegate_dry_run(backend="codex", ...)` |
| `codex_dry_run` | `amicus_dry_run(backend="codex", ...)` |
| `codex_status` | `amicus_backends(backend="codex")` |
| `codex_capabilities` | `amicus_capabilities()` (server-wide now; per-backend detail is `amicus_backends(backend="codex")`) |
| `codex_models` | `amicus_models(backend="codex")` |
| `codex_transfer` | not ported; there is no amicus equivalent |
| `codex_job_status` | `amicus_job_status(...)` |
| `codex_job_result` | `amicus_job_result(...)` |
| `codex_job_consume_result` | `amicus_job_consume_result(...)` |
| `codex_job_cancel` | `amicus_job_cancel(...)` |
| `codex_job_list` | `amicus_job_list(...)` |

### From `moonbridge`

| old tool | new call |
| --- | --- |
| `kimi_consult` | `amicus_consult(backend="kimi", ...)` |
| `kimi_consult_async` | `amicus_consult_async(backend="kimi", ...)` |
| `kimi_review_changes` | `amicus_review_changes(backend="kimi", ...)` |
| `kimi_review_changes_async` | `amicus_review_changes_async(backend="kimi", ...)` |
| `kimi_delegate` | `amicus_delegate(backend="kimi", ...)` |
| `kimi_delegate_async` | `amicus_delegate_async(backend="kimi", ...)` |
| `kimi_delegate_dry_run` | `amicus_delegate_dry_run(backend="kimi", ...)` |
| `kimi_dry_run` | `amicus_dry_run(backend="kimi", ...)` |
| `kimi_status` | `amicus_backends(backend="kimi")` |
| `kimi_capabilities` | `amicus_capabilities()` (server-wide now; per-backend detail is `amicus_backends(backend="kimi")`) |
| `kimi_models` | `amicus_models(backend="kimi")` |
| `kimi_job_status` | `amicus_job_status(...)` |
| `kimi_job_result` | `amicus_job_result(...)` |
| `kimi_job_consume_result` | `amicus_job_consume_result(...)` |
| `kimi_job_cancel` | `amicus_job_cancel(...)` |
| `kimi_job_list` | `amicus_job_list(...)` |

### From `claude-in-codex`

| old tool | new call |
| --- | --- |
| `claude_consult` | `amicus_consult(backend="claude", ...)` |
| `claude_consult_async` | `amicus_consult_async(backend="claude", ...)` |
| `claude_review_changes` | `amicus_review_changes(backend="claude", ...)` |
| `claude_review_changes_async` | `amicus_review_changes_async(backend="claude", ...)` |
| `claude_adversarial_review` | `amicus_adversarial_review(backend="claude", ...)` |
| `claude_adversarial_review_async` | `amicus_adversarial_review_async(backend="claude", ...)` |
| `claude_dry_run` | `amicus_dry_run(backend="claude", ...)` |
| `claude_status` | `amicus_backends(backend="claude")` |
| `claude_capabilities` | `amicus_capabilities()` (server-wide now; per-backend detail is `amicus_backends(backend="claude")`) |
| `claude_models` | `amicus_models(backend="claude")` |
| `claude_job_status` | `amicus_job_status(...)` |
| `claude_job_result` | `amicus_job_result(...)` |
| `claude_job_consume_result` | `amicus_job_consume_result(...)` |
| `claude_job_cancel` | `amicus_job_cancel(...)` |
| `claude_job_list` | `amicus_job_list(...)` |

`claude-in-codex` had no `claude_delegate`: Claude is review-only in amicus too, so `amicus_delegate` and `amicus_delegate_async` reject `backend="claude"` with `feature_unsupported`.
`amicus_adversarial_review(_async)` is the only pair that rejects `backend="codex"` and `backend="kimi"`, because only Claude declares the `adversarial_review` capability.

## Behavior deltas

Review results and `amicus_dry_run` carry a top-level `coverage` object, in the shape `codex_review_changes` returns (#65).
Its `status`, untracked counts, `omission_reasons` and `redaction` read as they do there, and it adds one reason of amicus's own: `focused`, for a call that passed `focus`.
Adversarial reviews carry it too, with null untracked counts when no scope was attached.
`amicus_dry_run` now accepts `focus` and reports `coverage` and `max_input_bytes`, so a preview reports the same omissions the paid call will.
It still has no `redacted_paths_count` or top-level `deadline_advisory`: count `meta.redacted_paths` instead, and read the advisory from `warnings`.

Claude adversarial reviews (sync and async) now default to `config_mode="safe"`, isolating them from inherited Claude instructions that can displace the JSON critique contract (#64).
When `AMICUS_CLAUDE_CONFIG_MODE=bare`, the default remains `bare` so API-key-only installations keep their authentication path.
Consult and review-changes calls still use the configured default, and an explicit `backend_options.config_mode` overrides the default on every verb.
This also applies when the operator explicitly configures `inherit` or `scoped`; use a per-call override to opt an adversarial review into inherited configuration.
`amicus_backends` reports structured `default_by_verb` values and a null common `default` when the verbs differ; each call's `meta.backend_details.config_mode` reports its resolved mode.
`amicus_dry_run` previews review-changes defaults, not adversarial-review defaults.
If an explicitly inherited configuration produces `invalid_json` or `schema_violation`, change `backend_options.config_mode` to `safe` before making another paid call.
An invalid JSON response alone does not establish config displacement, so the error is not automatically reclassified as a permanent configuration failure.

`idempotency_key` is accepted on the sync tools as well as the `_async` twins, as on both siblings (#66; before this it was async-only, and this guide did not say so).
A keyed sync call behaves as the siblings' did: a duplicate awaits the existing run and returns its result marked `meta.idempotency_replayed`, a transient keyed outcome is waited on for about a second before it is surfaced, and a keyed wait that times out or is cancelled leaves the run going and points at `amicus_job_status`.
Two things are new (ADR 0020).
A keyed sync run gets the job deadline (`AMICUS_JOB_MAX_SECONDS`), as an `_async` run does, and `timeout_seconds` bounds only how long the call waits; on the siblings the worker kept the caller's timeout, so their "the run continues" claim held only for a worker slower to finalize than the grace window.
And because neither sibling had the tasks extension: a keyed task's job survives `tasks/cancel`, while an unkeyed task's is cancelled with it.
An empty key is rejected pre-spend on every paid tool, as it was on the siblings.

These are the differences a user migrating from a single-model server actually hits; they are deliberate, not bugs.

**Approval friction follows the worst enabled backend (ADR 0001).**
One tool serves every backend, so its annotations are static and must cover the strictest case.
Enabling the Claude backend gives *every* tool mutation-grade annotations, including `amicus_consult(backend="codex", ...)`.
A call that never prompted under `codex-in-claude` alone can now prompt for approval once Claude is enabled.
Disable the Claude backend (via `AMICUS_BACKENDS`) to get the old, lighter approval friction back for codex/kimi-only use.
`amicus_backends` publishes each backend's own `AnnotationEffects` so an agent can read the per-backend truth directly.

**Remove the sibling servers when you switch; do not run them alongside amicus.**
A host that still has `codex-in-claude`, `moonbridge`, or `claude-in-codex` registered sees two servers offering the same job, and it may pick the sibling.
This was observed: on the Codex CLI capture, a cold-start run with the maintainer's full MCP fleet loaded called a sibling second-opinion server's status and consult tools and never reached amicus (`docs/host-captures/install-smoke/codex/0.153.4/notes.md`).
Delete each sibling's entry from your host's MCP configuration in the same change that adds amicus, and keep one of them only while you are still comparing the two.
`amicus_backends` is the tool that reports what amicus itself can reach; a sibling's `*_status` tool answers only for that sibling.

**One server, one job store.**
Jobs started against any backend share the same job store under `AMICUS_STATE_DIR`, instead of each sibling keeping its own.
`AMICUS_JOB_MAX_COUNT` is enforced per workspace, but the underlying task map is one file per state directory, so jobs from `codex`, `kimi`, and `claude` calls are visible to `amicus_job_list` together.
Point `AMICUS_STATE_DIR` at separate directories only if you need to keep job history isolated per backend or per project.

**`backend_options` is a closed superset (ADR 0002).**
Every backend's options (`isolation`, `config_mode`, `access`, `max_budget_usd`, and the rest) live in one closed schema shared by all calls.
A key that the selected backend does not accept is a validation error (`invalid_arguments`, `details.field = "backend_options.<key>"`), not a value that gets silently dropped the way an unrecognized sibling option might have been.
Check `amicus_backends(backend=...)` or a tool's `amicus_dry_run` echo to see which options apply to your chosen backend before spending.

**Legacy environment names warn now and are removed in `0.3.0`.**
Every sibling env var above is read automatically until then, but each read logs a warning naming the removal version.
Setting the new `AMICUS_*` name and the old legacy name to different values is an error rather than a silent pick of one; the same is true if two legacy names for the same setting disagree with each other.
Rename your environment before `0.3.0` ships to avoid a hard failure at that point.
