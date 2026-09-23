# Migration guide

amicus replaces three older single-model servers: `codex-in-claude`, `moonbridge`, and `claude-in-codex`.
Each sibling's tools, environment variables, and jobs now live behind one server with `backend` as a parameter.
This guide covers the environment-variable renames, the tool-name mapping for each sibling, and the behavior changes a migrating user actually hits.

## Environment variables

Every `AMICUS_*` name below is declared once in `src/amicus/config/envspec.py` (global) and each backend's `config.py` (per backend).
A sibling's old name was read during a deprecation window that closed with `0.3.0`: it supplied the setting only when the new `AMICUS_*` name was unset, and every such read logged a warning.
The sibling names were removed in `0.4.0` (#176): a sibling name is never read, and the `AMICUS_*` name's value or default applies.
A sibling name that is still set is reported as a warning naming the `AMICUS_*` name to set: in `amicus_backends`' `env_warnings` for a global setting, and in that backend's `status.warnings` for a backend setting, which exists only while that backend is enabled and loaded.
A stale name for a backend that is not enabled affects nothing and is not reported.
Its value is never read, not even to recognise an unexpanded `${...}` placeholder, so it is never compared with the `AMICUS_*` value and the conflict error the window had is gone with it.

| amicus name | former sibling names (not read since 0.4.0) | default |
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

`AMICUS_KIMI_BIN` and `AMICUS_CLAUDE_BIN` have no sibling equivalent, because neither `moonbridge` nor `claude-in-codex` offered a CLI-path override to rename.
`AMICUS_CODEX_BIN` had one — `CODEX_IN_CLAUDE_CODEX_BIN`, as the table above shows — because `codex-in-claude` did.
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
| `codex_dry_run` | `amicus_review_changes_dry_run(backend="codex", ...)` |
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
| `kimi_dry_run` | `amicus_review_changes_dry_run(backend="kimi", ...)` |
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
| `claude_dry_run` | `amicus_review_changes_dry_run(backend="claude", ...)` |
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

`amicus_dry_run` was renamed `amicus_review_changes_dry_run` (#98), and the sibling maps above point at the new name.
The old name worked as a deprecated alias in 0.3.x and 0.4.x, and 0.5.0 removed it at the end of that window (#204); the new name takes the same arguments.
Call the new name in anything you write now.

Review results and `amicus_review_changes_dry_run` carry a top-level `coverage` object, in the shape `codex_review_changes` returns (#65).
Its `status`, untracked counts, `omission_reasons` and `redaction` read as they do there, and it adds one reason of amicus's own: `focused`, for a call that passed `focus`.
Adversarial reviews carry it too, with null untracked counts when no scope was attached.
`amicus_review_changes_dry_run` now accepts `focus` and reports `coverage` and `max_input_bytes`, so a preview reports the same omissions the paid call will.
It still has no `redacted_paths_count` or top-level `deadline_advisory`: count `meta.redacted_paths` instead, and read the advisory from `warnings`.

Claude adversarial reviews (sync and async) now default to `config_mode="safe"`, isolating them from inherited Claude instructions that can displace the JSON critique contract (#64).
When `AMICUS_CLAUDE_CONFIG_MODE=bare`, the default remains `bare` so API-key-only installations keep their authentication path.
Consult and review-changes calls still use the configured default, and an explicit `backend_options.config_mode` overrides the default on every verb.
This also applies when the operator explicitly configures `inherit` or `scoped`; use a per-call override to opt an adversarial review into inherited configuration.
`amicus_backends` reports structured `default_by_verb` values and a null common `default` when the verbs differ; each call's `meta.backend_details.config_mode` reports its resolved mode.
`amicus_review_changes_dry_run` previews review-changes defaults, not adversarial-review defaults.
If an explicitly inherited configuration produces `review_status: unstructured`, read `raw_response.text`, then change `backend_options.config_mode` to `safe` before making another paid call.
An unreadable answer alone does not establish config displacement, so it is not reported as a configuration failure.

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
Check `amicus_backends(backend=...)` or a tool's `amicus_review_changes_dry_run` echo to see which options apply to your chosen backend before spending.

**Sibling environment names are not read since `0.4.0`.**
Every sibling env var above was read, with a warning, through `0.3.0`; from `0.4.0` it supplies nothing, and the `AMICUS_*` name's value or default applies (#176).
A sibling name that is still set is reported as a warning naming the `AMICUS_*` name to set, and it is never compared with that name's value, so the conflict error the window had is gone with it.
There is no hard failure: a forgotten rename shows up only as the default taking effect, and as that warning.

### Discovery defaults are concise

`amicus_backends` now takes `detail` and defaults to `summary`, which omits each backend's `egress`, `carriers`, `readonly_honesty` and `implicit_context` and lists those names in the top-level `omitted_fields`.
Pass `detail="full"` to read them.
A `null` there means no loaded plugin declares one.
The `amicus://backends/{backend}` resource is always the full entry.
`amicus_capabilities(detail="contracts")` is removed: pass `include_tool_details=false` for the same rowless payload, and `detail` now selects only how much each `tool_details` row carries (`summary` is `name`, `cost`, `stability`, `backends`; `full` adds the rest, including `error_codes`).

## Upgrading from 0.5.0

The change below is the one an operator using amicus 0.5.0 may have to handle before running 0.6.0.
`CHANGELOG.md`'s 0.6.0 section lists every user-visible change since 0.5.0, including the ones that require no migration.
A job result stored by 0.5.0 is still readable: `RESULT_FORMAT` did not move.

**A `CODEX_HOME` that is not an absolute path as written is refused (#193).**
A relative value, or one starting with a literal `~`, used to name one directory to the server and another to each codex run, and codex does not expand `~` at all.
A paid Codex call now fails before codex starts, as `user_config_rejected`, and `amicus_backends` reports codex with `authenticated: null` and a warning naming the variable.
Set `CODEX_HOME` to an absolute path in the environment amicus runs in, or unset it to use codex's default; an empty value is still treated as unset.

## Upgrading from 0.4.0

The changes below are the ones an operator or caller using amicus 0.4.0 has to handle before running 0.5.0.
`CHANGELOG.md`'s 0.5.0 section lists every user-visible change since 0.4.0, including the ones that require no migration.

**A job result stored by 0.4.0 is no longer readable (#140, #162).**
`RESULT_FORMAT` moved from 7 to 9: to 8 because `findings_diagnostics.reasons` gained `backend_artifact_reference_removed`, and to 9 because `error.code` gained `answer_unavailable`, each a value a 0.4.0 reader's closed enum rejects.
`amicus_job_result` and `amicus_job_consume_result` return `job_result_incompatible` for a record 0.4.0 wrote.
Fetch or consume any stored result you still need before upgrading; the record itself stays until `AMICUS_JOB_TTL` or the per-workspace cap evicts it.

**A finding that cited one of amicus's own temporary files no longer carries it (#140).**
On Kimi, which is handed its prompt as a file, a finding could come back with `file` set to that temporary path and `line` set to an offset into amicus's framing.
Such a `file` is now null together with its `line`, the path is replaced by `[amicus temporary file]` wherever the answer's text named it, and `findings_diagnostics.reasons` says `backend_artifact_reference_removed` at `dropped: 0`.
A caller that treated any non-null `findings_diagnostics` as loss should read the reason: this one loses nothing a caller could have opened.

**`amicus_dry_run` is gone (#204).**
It was the deprecated alias of `amicus_review_changes_dry_run` since 0.3.0 (#98), with a marker in its lifecycle `_meta` and on its `amicus_capabilities` row naming 0.5.0 as its removal, and ADR 0028 removes a tool at that release.
Call `amicus_review_changes_dry_run` with the same arguments; the result is the same except that `tool` names the tool you called.
A call to the old name now returns `isError: true` with the text `Unknown tool: 'amicus_dry_run'` and no `structuredContent`: it comes from the MCP layer, so there is no amicus error envelope and no `error.code` to branch on.

**An answer file amicus refuses to read is `answer_unavailable`, not an empty answer (#162).**
amicus reads a backend's answer file only if it is a regular file within a 1,000,000-byte limit.
A refused file used to be indistinguishable from a backend that wrote nothing: a Codex review returned `invalid_json`, and a Codex consult returned `ok: true` with the summary "(the backend returned no message)".
Both now return `answer_unavailable` with `error.details.reason` set to `artifact_oversize`, `artifact_not_regular` or `artifact_unreadable`; it is temporary only for an unreadable file whose cause passes, such as descriptor exhaustion, and for oversize its repair is `reduce_input`.
A caller that treated "(the backend returned no message)" as the backend having nothing to say should branch on `ok` first, as it always should have.
A delegate whose summary file was refused, and which has no other whole answer from the backend, is still `ok: true` when its diff was captured, with the diff and a `meta.security_warnings` entry.

## Upgrading from 0.3.0

The changes below are the ones an operator or caller using amicus 0.3.0 has to handle before running 0.4.0.
`CHANGELOG.md`'s 0.4.0 section lists every user-visible change since 0.3.0, including the ones that require no migration.

**Sibling environment names are no longer read (#176).**
`CODEX_IN_CLAUDE_*`, `MOONBRIDGE_*` and `CLAUDE_IN_CODEX_*` supplied a setting through 0.3.0 when the `AMICUS_*` name was unset; from 0.4.0 they supply nothing.
Rename each to the `AMICUS_*` name in the table above; a name left set is reported by `amicus_backends`, for a backend setting only while that backend is enabled and loaded, and otherwise ignored.
The settings where this matters most are the ones whose default is looser than what you had set, such as `CODEX_IN_CLAUDE_ISOLATION=ignore-rules` or `CLAUDE_IN_CODEX_CLAUDE_CONFIG=safe`, which now fall back to `inherit`.

**A review amicus cannot parse is delivered as `unstructured` (#139).**
A review or critique whose answer is not one readable JSON object returned `invalid_json` or `schema_violation`; it now returns `ok: true` with `review_status: unstructured`, `verdict` and `confidence` set to `unknown`, and the whole answer in `raw_response.text` at `detail="full"`.
Branch on `review_status` before reading the verdict, and read that text before paying for the same review again.
Only an answer amicus could not read at all is still an error: `invalid_json` for an empty one, or `empty_response` on Kimi, which detects it first, and, from 0.5.0, `answer_unavailable` for an answer file amicus refuses to read (see "Upgrading from 0.4.0").

**A job result stored by 0.3.0 is no longer readable (#139).**
`RESULT_FORMAT` moved from 6 to 7 for the unstructured review result, so `amicus_job_result` and `amicus_job_consume_result` return `job_result_incompatible` for a record 0.3.0 wrote rather than manufacturing the new shape for an older run.
Fetch or consume any stored result you still need before upgrading; the record itself stays until `AMICUS_JOB_TTL` or the per-workspace cap evicts it.

## Upgrading from 0.2.0

The changes below are the ones a caller written against amicus 0.2.0 has to handle.
`CHANGELOG.md`'s 0.3.0 section lists every user-visible change since 0.2.0, and a caller written against 0.2.0 needs to change nothing for the ones not listed here.

**Every success `meta` is sparse on the wire (#47).**
A `meta` key whose value is null is omitted from every tool's success, not only from a delivered paid result as before.
Read an absent key as null.
Seven keys are always present, and the result-meta schema requires exactly them: `elapsed_ms`, `truncated`, `compat_warnings`, `security_warnings`, `redacted_paths`, `request_id` and `fingerprint`.

**A review that did not run reports `confidence: unknown` (#54).**
`review_status: not_run` carried `confidence: low`; it now carries `unknown`, the value an unreadable backend rating has carried since 0.2.0.
Branch on `review_status` for whether a review ran, and read `unknown` as "no rating", never as a low one.

**A finished job's `poll_after_ms` is null (#95, #101).**
`amicus_job_status`, `amicus_job_cancel` and a replayed keyed `_async` handle report `poll_after_ms: null` on every terminal status; a replayed handle used to report `1000`.
While a job runs the hint grows with its elapsed time to a ceiling of 30 s, where the SDK amicus was built on stopped at 10 s.
Poll only while `status` is `running`; a caller that read a non-null hint as "still running" waited one extra interval on every finished job.

**The free discovery tools default to a summary (#46).**
`amicus_capabilities(detail="contracts")` is rejected as `invalid_arguments`, and the default `amicus_backends` omits four disclosure fields; the "Discovery defaults are concise" section above has the replacement calls.

**A review amicus cannot parse is delivered as `unstructured` (#139).**
A review or critique whose answer is not one readable JSON object returned `invalid_json` or `schema_violation`; it now returns `ok: true` with `review_status: unstructured`, `verdict` and `confidence` `unknown`, and the whole answer in `raw_response.text` at `detail="full"`.
Branch on `review_status` before reading the verdict, and read that text before paying for the same review again.
Only an answer amicus could not read at all is still an error: `invalid_json` for an empty one, or `empty_response` on Kimi, which detects it first, and, from 0.5.0, `answer_unavailable` for an answer file amicus refuses to read (see "Upgrading from 0.4.0").

**A job result stored by 0.2.0 is no longer readable (#65, #52, #139).**
`RESULT_FORMAT` moved from 4 to 9, so `amicus_job_result` and `amicus_job_consume_result` return `job_result_incompatible` for a record 0.2.0 wrote, rather than a result whose new fields would answer for a run that never measured them.
Fetch or consume any stored result you still need before upgrading; the record itself stays until `AMICUS_JOB_TTL` or the per-workspace cap evicts it.

**An empty `idempotency_key` is rejected (#66).**
The four `_async` tools accepted `""`; every paid tool now rejects it before spending as `invalid_arguments` (`minLength: 1`).
Omit the key instead.

**`amicus_dry_run` is a deprecated alias (#98), and 0.5.0 removed it (#204).**
Call `amicus_review_changes_dry_run`.

**Two workspace errors carry no `repair` (#42).**
`invalid_workspace_root` and `workspace_outside_roots` omit the `error.repair` key, because no call can supply the caller's directory; read `details.field`, `details.reason` (a fixed token naming the cause, #214) and `error.candidate_roots` instead.
Every other repair that names a tool carries a complete call in `repair.arguments`.

**Claude adversarial reviews default to `config_mode="safe"` (#64).**
An adversarial review no longer inherits your Claude configuration unless the call passes `backend_options.config_mode` as `inherit` or `scoped`, the two modes that read the workspace's `CLAUDE.md` and `.claude/settings*.json`; the "Behavior deltas" section above has the details.
`amicus_backends` reports that option's per-verb defaults in `default_by_verb`, and its common `default` is null where the verbs differ.

**A bool in a prose list is dropped and counted (#52).**
0.2.0 delivered a bool entry of `questions`, `assumptions` or `next_steps` as the string `"True"` or `"False"`.
It is now dropped and counted in `lists_diagnostics`, as a null, object or array entry is.

**A resource's size is the native `size` field (#48).**
The `size_bytes` key under the `dev.bconnelly.amicus/triage` `_meta` block is gone; read `Resource.size`, which only the three static resources carry.
