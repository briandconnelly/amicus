# ADR 0043: each paid verb is one tool with a `wait` flag

**Status:** Proposed (2026-09-24)

## Context

`tools/list` is 112,683 bytes on the `all` profile, 27,975 o200k tokens, for 18 tools, and a preloading host (Codex CLI, `docs/host-captures/install-smoke/codex/0.153.4/transcript.md`) pays it per session (#247).
Output schemas are 46% of it; the four `_async` records are 26,513 bytes, each carrying an input schema that repeats its sync twin's minus two parameters, and a byte-identical 1,959-byte `JobStarted` output schema.
The sync and `_async` twins carry identical annotations in every profile, and every sync call already runs as a detached job that the sync tail awaits (`jobs.lifecycle.run_sync` is `start_job` plus `await_job_result`), so the twin is the sync call without the wait.
The two dry-run tools are annotated `readOnlyHint: true` (`ann.free_read()`, free, no model call), while the paid tools are annotated `readOnlyHint: false` (`ann.active()`).
Hosts gate tool approval on that annotation: the Codex install-smoke capture (`docs/host-captures/install-smoke/codex/0.153.4/notes.md`) observed auto-approval of the read-only-hinted tools and refusal of the others under `approval_policy = "never"`.
Folding a dry run into its paid tool behind a flag would lose that read-only annotation, which the worst-enabled-backend annotation rule (`[3.ap-mode-annotations]`) requires; nothing like that separates a twin from its sync tool.
The prose kept on the output schemas by #38, #52 and #65 guards specific misreadings and is not repetition; #41 already compressed the repeated parameter prose behind `amicus://params`.

## Decision

**Each paid verb becomes one tool, its sync tool, with a `wait: bool = true` parameter.**
`wait: false` takes exactly the `_async` twin's path today: `prepare_run` with no `timeout_seconds` and `background=True`, then `lifecycle.start_async`, returning the `JobStarted` handle; `timeout_seconds` and `detail` are ignored on that path and the parameter description says so.
The output schema is `published_schema(<Result>, JobStarted)`, a union of the verb's result and the handle behind the existing `ok` discriminator; a caller branches on top-level `job_id` (a handle) against `tool` (a result).
A keyed `wait: false` start and a keyed `wait: true` call share the `(tool, key)` reservation, because both run under the sync tool's name, so a caller can start in the background and later attach with the same key; the `idempotency_key` contract's sentence that sync and `_async` never share a key becomes "the `_async` twins, while they last, never share a key with the merged tool".

**The four `_async` tools are deprecated under the published policy and removed at the end of the window.**
They keep their whole records, gain the lifecycle marker with `replaced_by` naming the sync tool and a migration that says to pass `wait: false`, lead their descriptions with the deprecation, and move to the end of `ACTIVE_TOOLS` so each sits last in its group (ADR 0028's placement rule; the wire order of the other tools is unchanged).
`since` is the next minor release and `removal_at_or_after` is two minors later, written as constants when the follow-up plan is executed; `scripts/check_release_state.py` and `tests/test_meta.py` hold the window.
The byte win, about 26.5 KB on the `all` profile, lands at removal; during the window `tools/list` grows by the four markers and the `wait` parameter, and `tests/test_discovery_cost.py` records both moves with their reasons.

**What is taken now, before the window.**
`timeout_seconds` and `detail`, the two sync-only parameters, join the `amicus://params` mechanism as `ParamContract`s, and `_meta.fastmcp` is stripped from every catalog record (done in #250).
The output-schema prose #38, #52 and #65 chose to keep is not trimmed.
Two fields are never branched on, `raw_response` and `context_summary`; making them opaque needs a home for their schema, and none of the existing resources is it, so that is left to the follow-up plan as an `amicus_capabilities` `include_schemas` value.

## Consequences

- The follow-up plan implements the merge and the deprecation, sweeps the skill, the commands, the README and `docs/MIGRATION.md` (fifteen files name the `_async` tools), and updates the design spec's tool table and parameter matrix; `tests/test_params.py` gains `wait` in `SYNC_ONLY_PARAMS`.
- Until removal, `amicus_capabilities` still lists 18 tools; after it, 14.
- `FINGERPRINT` moves at each step; `RESULT_FORMAT` does not, since the stored result shapes are unchanged.
