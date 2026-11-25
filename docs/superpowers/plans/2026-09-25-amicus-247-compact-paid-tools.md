# Implementation plan: one paid tool per verb with a `wait` flag, and result-field rules published once

**Status:** Parked on 2026-09-26 pending the maintainer's decision on whether either change is worth doing; the measured basis, benefits, downsides and how to resume are recorded on [#247](https://github.com/briandconnelly/amicus/issues/247#issuecomment-5848329258); implementation has not started.
**Issue:** [#247](https://github.com/briandconnelly/amicus/issues/247).
**Design:** [design spec](../specs/2026-09-04-amicus-design.md), [proposed ADR 0043](../../adr/0043-each-paid-verb-is-one-tool-with-a-wait-flag.md), [proposed ADR 0045](../../adr/0045-result-field-reading-rules-are-published-once.md).
**Baseline:** `main` at `2ab6a8c`, the tree after v0.7.0 shipped on 2026-09-26; the `all` profile measures 112,105 bytes there, as `MEASURED` in `tests/test_discovery_cost.py` pins.
**Scope:** Post-milestone maintenance, executed as four draft PRs in the order below, as milestone 3's plan was executed as PRs #255 to #258.

## Outcome and boundaries

Expose one tool per paid verb with `wait: bool = true`, preserving existing calls that omit it.
Keep the two free dry-run tools separate because their annotations differ from paid tools.
Keep all four deprecated `_async` tools discoverable and callable for the published two-minor window.
This implementation ends with the deprecation window open; removal belongs to a later PR after the window expires.
The final catalog will have 14 tools, while the transitional catalog retains 18.
Keep this issue open for the later removal and its measured savings.

This plan also takes #247's second remediation, trimming output schemas, but only the part that is repetition: the reading rules of `findings_diagnostics`, `lists_diagnostics` and `coverage`, which are the same prose once per tool.
On the baseline wire, output schemas are 53,690 of the 112,105 bytes, and those three fields are 18,088 of them, 10,897 bytes of it description text.

| Output-schema field on the baseline wire | Occurrences | Bytes |
| --- | --- | --- |
| `findings_diagnostics` | 4 | 6,592 |
| `coverage` | 3 | 5,874 |
| `lists_diagnostics` | 3 | 5,622 |
| `context_summary` | 3, one of them the dry run | 576 |
| `raw_response` | 4 | 1,020 |

ADR 0045 decides where those rules live: the structure and the guarding sentences stay on every tool verbatim, and the reason vocabularies, 6,231 bytes of the prose, are published once behind `amicus_capabilities(include_schemas=["result-fields"])` and `amicus://result-fields`, with one pointer sentence appended to each parent field's retained guard; measured on a throwaway edit of the baseline, the saving is 5,234 bytes on every profile before the new enum value, which the ADR calls modest and says why.
Hiding `context_summary` behind an `include_schemas` value would save at most 384 bytes on the paid tools before paying for a stub, a pointer sentence and a new enum value, so it is not taken; `raw_response` keeps its full schema because its recovery text is the unstructured-result contract.
The two changes are independent in code and in bytes, since the `_async` records carry none of the three fields, so their savings add and each is measured on its own.
Retain explicit schemas and semantic descriptions for `raw_response.text`, findings, verdict, confidence, `review_status`, coverage, diagnostics, `poll_after_ms`, and `follow_up`.
The already-landed empty FastMCP metadata removal and shorter `timeout_seconds`/`detail` descriptions are baseline behavior.
Version literals, release tags, `.github/**`, `AGENTS.md`, and `CLAUDE.md` are outside this implementation.
Repository rules remain authoritative, especially [the gate and rules 10, 11, 16, and 18](../../../AGENTS.md).

## Decision sequence

The maintainer decides the design; measurements check its cost.
A byte count can show that one tool with a mode flag is cheap enough, and it cannot show that it is the right interface, so the two are separated.

1. PR A (Task 1) amends ADR 0043, records the baseline and a projected transitional cost, and carries ADR 0045; the maintainer's merge of PR A, with each ADR's status moved to Accepted or the ADR removed, is the design decision, and the two ADRs are decided separately.
2. PR B (Task 2) publishes the result-field reading rules once under ADR 0045; it needs no deprecation window and its saving lands at the next release.
3. PR C (Tasks 3 to 5) implements the merge under ADR 0043, proves identity, task and repair behavior, measures the delivered catalog against the bounds below, and opens the deprecation window; a measurement outside its bound stops PR C at a checkpoint for the maintainer rather than discarding work.
4. PR D (Task 6) migrates guidance and finishes the sweep.
5. The removal PR follows the window under [Deferred removal](#deferred-removal).

PR B and PR C are independent and either may merge first; if only one ADR is accepted, its PR proceeds alone.
No implementation commit is made before PR A merges.
The net-benefit test for both is the same: a preloading host pays less per connection, an agent using the skill changes nothing, a client validator enforces the same structure, and no guard that keeps an agent from acting on a result that lost something becomes weaker than the #41 and `meta` precedents already made it; the host exercise in Task 5 is where that last condition is checked rather than assumed.

## Contract to implement

| Call | Execution deadline | Response and recovery |
| --- | --- | --- |
| `wait: true`, no key | Existing clamped synchronous timeout | Existing result or timeout; a timed-out run is terminated |
| `wait: true`, key | Job deadline; caller timeout bounds waiting | Await the keyed job; a wait timeout points to the continuing job |
| `wait: false`, with or without key | Job deadline | Existing `JobStarted` shape; replay may already be terminal |
| Deprecated `_async` name | Existing behavior | Existing handle and separate tool/key namespace |

For `wait: false`, accept omitted or null `timeout_seconds` and omitted or explicit `detail: "summary"`.
Reject non-null `timeout_seconds` and `detail: "full"` with field-level `invalid_arguments` before preparation or spend.
Explain that the handle has no full-detail variant and `amicus_job_result(detail="full")` retrieves the full answer.
Use value checks, not an attempt to distinguish explicit defaults from injected defaults; this is safe because `timeout_seconds` is published with no default and `detail` defaults to `"summary"`, which the path accepts.
Leave the published `detail` default as `"summary"`.

`ok` selects success versus error; required `tool` selects a completed result, and required top-level `job_id` selects a handle.
`JobStarted` carries no top-level `tool` today, and every paid result carries `tool` as a defaulted literal that no result schema lists in `required`, so the discrimination is already disjoint and requiring `tool` makes it explicit.
Keep both success branches closed, retain `meta.job_id` on results, and do not add top-level `job_id` to results or `tool` to handles.
Publish the existing result-plus-handle union through `published_schema`, making `tool` required in the advertised result branch without changing stored payloads.
Add a narrow publication option that requires named fields only in branches declaring them; use it for `tool` and test that no other defaulted field becomes required.

Treat `wait` and `detail` as delivery controls outside `RunSpec`.
Neither enters `RunSpec.identity()`, which hashes only spec fields, so no `IDENTITY_EXCLUDE` entry is possible or needed; ADR 0043's sentence adding one is wrong and PR A removes it.
Prepare every keyed merged call with `background=True`, regardless of `wait`, as `prepare_run` already does for a keyed sync call, so the job deadline the spec stores is the same in both modes and the two hash identically.
A start and attach with the same merged tool, workspace, key, and effective run inputs must reserve exactly one worker even when the waiting timeout and detail differ.
Changed effective run inputs still conflict, and the deprecated twins retain their own tool/key namespaces.
Retain existing cancellation, expiry, cap, and failed-result replay semantics.

Keep task support on the waiting path.
The rule is one sentence: a `wait: false` call that is executing inside a task, which `lifecycle.current_task_id()` reports by returning an id, is `invalid_arguments` before `prepare_run` and before any worker starts, and a merely negotiated task capability with no executing task is not.
The refusal exists because a task that completes with a job handle would put two recovery handles on one run; it says nothing about whether a task wrapper was created, since the refusal may itself be delivered through the task.
The tests are the four rows of the matrix in Task 4.

For a terminated synchronous timeout, point recovery advice at the merged verb and explicitly instruct a new paid attempt with `wait: false`, omitting `timeout_seconds` and using summary detail.
Preserve the existing omission of prompt-bearing repair arguments and explain how the caller reuses its original inputs.
Do not put an incomplete `{wait: false}` call in `repair.arguments`, or introduce a delta-arguments convention in this change.
For a continuing keyed job, preserve the callable status lookup and job ID; do not recommend a second launch.
For an exhausted job deadline, preserve the advice to narrow the request or change configuration rather than retrying the same exhausted deadline.
This fallback requires reading the repair's prose because prompt-bearing arguments cannot be reconstructed from the structured repair alone.
Record that limitation in the ADR; never describe the merged tool name alone as a complete corrective call.
Pin this guidance with direct tests of both timeout carriers, since `repair_rules` deliberately excludes alternative prose and dynamically selected timeout tools.
Refresh fingerprinted repair rules only where their covered fields actually change, and bump the fingerprint for changed resource and tool guidance as applicable.

## Release constraint

The lifecycle markers name `since` as the first minor release after PR C merges, currently 0.8.0, and `removal_at_or_after` two minors later, currently 0.10.0, without changing any version literal.
`check_deprecations` in `scripts/check_release_state.py` rejects a tag whose version is below any marker's `since`, and `tests/test_meta.py` requires `since` to be an `X.Y.0`, so between PR C merging and the 0.8.0 tag no patch release can be tagged.
The gate does not warn about this at merge time; the `verify` job refuses the tag.
PR C therefore adds one sentence to the Preconditions of `docs/RELEASING.md` naming the constraint and the markers that impose it, and states it in its PR body, so whoever cuts the next release sees it before choosing a version.
If a patch release is planned, it ships before PR C merges; PR B imposes no such constraint.

## Measurement bounds

Every bound is per profile and is checked on the delivered catalog, not on estimates.
They are checkpoints: a miss stops PR C and puts the measured numbers on the PR for the maintainer, who chooses between proceeding with the numbers as they are, revising the ADR, or superseding it.
Nothing is discarded automatically.

- Transitional growth, the marker-and-`wait` catalog against the baseline: no more than 10,000 bytes.
- Post-removal saving, the 14-tool catalog against the baseline: at least 15,000 bytes.
- Reading-rules saving, PR B's catalog against its own pre-change catalog: at least 4,500 bytes, ADR 0045's own bound.

Each PR's bound is measured as that PR's isolated delta, its delivered catalog against the catalog of the commit it is rebased on, in whichever order PR B and PR C merge, so neither PR's change can offset or conceal the other's; the cumulative delta against `2ab6a8c` is reported beside it and is not a bound.

The four `_async` records measure 26,452 bytes on the baseline, and the permanent handle branch was measured in-process at 1,668 bytes per verb, 6,672 in all, so the removal saving is expected near 18,000 bytes and the transitional growth near the cap once the four `wait` parameters, four markers, four description leads and the merged tools' longer descriptions are added.
That closeness is why Task 1 projects the transitional cost before PR A merges.

## Task 1: amend ADR 0043, propose ADR 0045 and record the baseline (PR A)

**Files:** ADR 0043; ADR 0045; the design spec's ADR references; `tests/test_discovery_cost.py` only if the instrument needs a change; the issue #247 thread.

Amend ADR 0043 to the contract above: remove the `IDENTITY_EXCLUDE` sentence and its rationale, replace its claim that `raw_response` is never needed for branching with the unstructured-result recovery contract, and state that closed success branches are already disjoint while requiring `tool` makes discrimination explicit.
Correct its measurement label: `tests/test_discovery_cost.py` measures the raw stdio wire through `manifest.tools_list_wire`, not in-process, and the current baseline is 112,105 bytes on `all`, distinct from the ADR's historical 112,683 and the issue's 112,730 full-line figure.
Carry ADR 0045 as drafted with this plan, with the field table above, and post the same table on #247 so the remediation list shows what is taken and what is not.
Add the release constraint above to the ADR's consequences.
Move each ADR's status to Accepted with the date, or remove the one the maintainer declines; the maintainer's merge of PR A is the decision, and the checkpoints in PR B and PR C can send either back.

Record the current per-profile raw stdio measurements, protocol era, tool count, and revision.
Use `uv run python -m amicus.manifest --measure`, which invokes `manifest.tools_list_wire` through a real subprocess and measures the 2025-11-25 result body.
The existing `manifest.tools_list_bytes(profile, *, env=None)` measures the same body and has no protocol-era argument.
Keep that existing byte-exact instrument and era as the budget gate, and distinguish result-body bytes from the entire JSON-RPC line.
Modern-era behavior is exercised by the transport and host tests; this plan does not add a second byte-exact measurement instrument.

Project the transitional cost on a throwaway branch that is never pushed: four `DEPRECATED_TOOLS` entries with the intended migration text, a boolean `wait` parameter with its intended description on the four sync tools, the four description leads, and the union output schema, measured with the same instrument on all three profiles.
Record the per-profile numbers in the ADR as a labelled projection; they inform the maintainer's decision and are excluded from acceptance assertions, which Task 5 makes on the delivered catalog.
Repeat ADR 0045's throwaway measurement on the same branch, removing the nested vocabulary descriptions it names and appending the pointer to each parent guard, and record the per-profile numbers in ADR 0045 beside the 5,234-byte figure it starts from, saying whether they differ.
Record token counts only when the tokenizer and encoding are pinned; bytes remain the deterministic CI budget.

**Validation:** `uv run pytest tests/test_discovery_cost.py tests/test_manifest.py tests/test_check_sentence_per_line.py`, and the full [repository gate](../../../AGENTS.md#rules) before the PR is marked ready.
**Commit:** `docs(schemas): amend ADR 0043, propose ADR 0045 and record the baseline`.

## Task 2: publish the result-field reading rules once (PR B)

**Files:** `src/amicus/schemas/results.py`, `envelope.py`, `params.py`, `publish.py`; `src/amicus/tools/discovery.py`; `src/amicus/manifest.py` and `server.py` for the static resource set; `tests/test_results.py`, `test_publish.py`, `test_discovery.py`, `test_resources.py`, `test_discovery_cost.py`; new `tests/test_reading_rules_captures.py`; `docs/host-captures/reading-rules/<host>/<version>/`; `skills/collaborating-with-amicus/references/reading-results.md`; `docs/MIGRATION.md`; `CHANGELOG.md`.

First write the two tests that pin the move: every vocabulary constant that leaves `KEPT_DESCRIPTIONS` must appear verbatim in the `result-fields` schema returned by `amicus_capabilities(include_schemas=["result-fields"])` and by `amicus://result-fields`, so a rule can move but never be dropped; and every guard ADR 0045 names must be byte-identical to its pre-change text on the wire, so a guard cannot drift.
Add the `result-fields` document, `FindingsDiagnostics`, `ListDiagnostics` and `Coverage` with their full prose, as a new `include_schemas` value and a fourth static resource, leaving `result-meta` as the `Meta` schema alone; update the `include_schemas` description, the resource description and every place the static resource set is enumerated.
Remove the nested vocabulary descriptions rather than replacing them, append one pointer sentence to each parent field's retained guard, leading with the tool path and naming the resource second, and split `_LISTS_DESC` at its reason definitions so its guard stays and its vocabulary moves; ten pointers in all, on `findings_diagnostics`, `lists_diagnostics` and `coverage` including the dry run's.
Keep the structure, enums, required members, nullability and numeric bounds byte-identical to today's, asserted by a test that strips descriptions from both and compares.
Keep `_FINDINGS_DESC`, `_REVIEW_STATUS_DESC` and `_CONFIDENCE_DESC` as they are; they are single sentences that guard a misreading and are not repetition.
Update the tests that assert the vocabulary prose on the wire to assert the pointer sentences instead, and the skill's reading-results reference and `docs/MIGRATION.md` to name the new carrier.
Measure all three profiles with the existing wire instrument, as PR B's isolated delta under [Measurement bounds](#measurement-bounds), and record it in `tests/test_discovery_cost.py` with `MEASURED` and `BUDGET` moved together; a miss stops PR B at a checkpoint with the numbers on the PR.
Run ADR 0045's five host scenarios before PR B is marked ready, each a fake-backend review presented in Codex and Claude Code with no skill loaded: a result whose `lists_diagnostics` reports a lost `next_steps` member beside a `pass` and an otherwise clean result; a result whose `findings_diagnostics` reports `extra_fields_omitted` at `dropped: 0`; a result whose only diagnostic is `number_stringified`; a `focused` review whose coverage is `partial` with nothing withheld; and a review whose `omission_reasons` names `redacted` beside a null `redaction`.
Each scenario passes only when the agent's stated reading of the result is correct after it follows the pointer: the first is not the backend recommending nothing, the second lost content, the third lost nothing, the fourth withheld nothing, the fifth had secret-looking content cut by the byte cap rather than no redaction; a capabilities call alone is not a pass.
Record them with the same version, revision and rule-18 hashing discipline as Task 5's captures, under `docs/host-captures/reading-rules/<host>/<version>/`, and add `tests/test_reading_rules_captures.py` for their record shape; the deterministic prose-preservation tests are the cheap gate, and these captures are the behavioral evidence.
If any scenario fails on any host, PR B stops: the vocabulary move is dropped from it, no saving is claimed, and ADR 0045 is recorded as rejected on that evidence; the `result-fields` document may still land on its own merits as a separate no-savings outcome if the maintainer wants it, stated as such in the PR.
Add an Unreleased changelog entry naming the moved prose, the carrier and the measured reduction.

**Validation:** `uv run pytest tests/test_results.py tests/test_publish.py tests/test_discovery.py tests/test_resources.py tests/test_manifest.py tests/test_discovery_cost.py tests/test_reading_rules_captures.py tests/test_skill_contract.py tests/test_migration_doc.py`, plus the host scenarios, then the full repository gate before PR B is marked ready.
**Commit:** `perf(schemas): publish result-field reading rules once`, followed by PR B's single pin commit under [Fingerprint and pins](#fingerprint-and-pins).

## Task 3: add the merged execution paths (PR C)

**Files:** `src/amicus/tools/consult.py`, `review.py`, `delegate.py`, `_prepare.py`, `discovery.py`; `src/amicus/schemas/params.py`, `results.py`, `publish.py`; `src/amicus/jobs/lifecycle.py`; `src/amicus/wire_shape_snapshot.py`; `src/amicus/middleware.py` only if transport-level validation requires it.

Write parameterized fake-backend tests for all four verbs in `tests/test_wait_mode.py` before adding the handlers.
Cover omitted `wait`, explicit true, false, invalid mode-specific arguments, running handles, terminal replay handles, and result/error delivery through MCP.
Use existing fake-backend fixtures and keep the real-binary unit-test guard intact.
Implement the common pre-spend validation once where practical, and route true through `run_sync` and false through `start_async` under the merged tool name.
Preserve the original `_async` functions and their input/output schemas without adding `wait` to them.
Add `wait` to the merged tools' published parameter contracts, discovery parameter matrix, and `SYNC_ONLY_PARAMS` expectations as appropriate to that test's actual meaning.
Test union validation using real fake-backend tool responses: result, handle, and error must validate; each success must fail validation against the other success branch.
Exercise all four verbs and both summary/full completed results.
Update `TOOL_DETAILS` use/return descriptions and error-code inventories to cover both merged paths.
Clarify that `amicus_job_result` returns the originating tool's completed-result branch, never its handle branch.
Add a wire-shape fixture for a handle minted under the merged name, retaining the alias fixture; a `wait: false` job's record carries the merged name in its `tool` field, which changes a value and not a shape, so `RESULT_FORMAT` does not move.
Update `tests/test_paid_tools.py` pair-parity expectations for the additional merged-only parameter.

**Validation:** `uv run pytest tests/test_wait_mode.py tests/test_sync_tools.py tests/test_async_tools.py tests/test_paid_tools.py tests/test_results.py tests/test_publish.py tests/test_params.py tests/test_wire_shape.py`.
**Commit:** `feat(tools): support non-waiting calls on paid verbs`, followed by PR C's pin commit described in [Fingerprint and pins](#fingerprint-and-pins).

## Task 4: prove job identity, task behavior, and repair migration (PR C)

**Files:** `tests/test_wait_mode.py`, `test_tasks_client.py`, `test_tasks_spike.py`, `test_errors.py`, `test_lifecycle.py`, `test_run.py`, `test_prepare.py`, `test_dry_run.py`, `test_surface_honesty.py`; `src/amicus/errors.py`; `src/amicus/jobs/lifecycle.py`; `src/amicus/tools/dry_run.py`, `_prepare.py`, `_resolve.py`; `src/amicus/backends/codex/cli.py` for its capture-failure timeout alternative; relevant error rule definitions.

Test keyed false-to-true attachment and true-to-false replay, both while running and after completion.
Assert one worker start, one job ID, equal effective identity across wait/detail changes, conflict on changed run inputs, and independent aliases.
Cover cancellation of one keyed waiter, retention/cap refusal, missing or expired keyed results, and terminal failure without a duplicate launch.
Test the task matrix as four rows: tasks disabled, capability absent, capability present on an ordinary call, and actual task execution.
For a tasked false call, assert the error has the correct carrier and `isError`, and no model worker starts.
For tasked true calls, preserve job/task lookup, cancellation, and keyed recovery behavior.

Sweep `async_twin_for`, timeout alternatives, deadline advisories, paid-tool descriptions, and structured per-code repair rules.
Include `TIMEOUT_ALTERNATIVE`, `KEYED_TIMEOUT_ALTERNATIVE`, `JOB_DEADLINE_TIMEOUT_ALTERNATIVE`, the codex adapter's `_CAPTURE_FAILED_TIMEOUT_ALTERNATIVE`, the dry-run advisories that name the `_async` tools, and the full `idempotency_key` ParamContract text.
Keep shared parameter summary text unchanged while preserving byte-identical alias input schemas; put the revised cross-mode identity explanation in the full resource text and merged-tool descriptions.
Introduce an explicitly named replacement mapping/helper if needed rather than leaving a function named `async_twin_for` returning non-twins.
Test terminated sync timeouts, continuing keyed waits, exhausted job deadlines, and alias calls separately.
For an alias's failed keyed run, changing to the merged name creates a different namespace; disclose a new paid attempt rather than claiming recovery.
Assert that repair arguments and diagnostics never echo prompt fields, and that advice never treats an omitted `wait` as a background retry.
Test both the stored worker failure rendered by `errors.render_failure` and the waiter's `await_job_result` grace-timeout response.
In each unkeyed timeout path, cover job deadlines greater than, equal to, and shorter than the exhausted synchronous deadline; recommend a new background attempt only when it provides a longer deadline.
Pin the required mode-change and new-spend guidance directly in those response tests, rather than expecting the repair-rules fingerprint to cover prose.
Extend the status-gated polling assertions in `tests/test_surface_honesty.py` to merged-tool descriptions.

**Validation:** `uv run pytest tests/test_wait_mode.py tests/test_tasks_client.py tests/test_tasks_spike.py tests/test_errors.py tests/test_taskmap.py tests/test_lifecycle.py tests/test_run.py tests/test_prepare.py tests/test_dry_run.py tests/test_surface_honesty.py`.
**Commit:** `fix(jobs): preserve recovery across paid tool wait modes`, followed by a re-pin commit if the surface moved.

## Task 5: measure, exercise hosts, and open deprecation (PR C)

**Files:** `src/amicus/tools/_meta.py`; tool registration/order and discovery modules; `docs/RELEASING.md`; `tests/test_meta.py`, `test_surface.py`, `test_paid_tools.py`, `test_dry_run.py`; new `tests/test_wait_mode_captures.py`; `docs/host-captures/wait-mode/<host>/<version>/` evidence summaries; ADR 0043.

Add the four lifecycle markers with replacement tool and `wait: false` migration instructions, choosing `since` and `removal_at_or_after` under [Release constraint](#release-constraint).
Keep deprecated tools as a contiguous suffix of their active cost group, preserving their relative order and all annotation semantics.
Test the marker window, discoverability, old-call behavior, and byte-identical alias input/output schemas against the pre-merge baseline.
Update the exact lifecycle assertions in `tests/test_paid_tools.py`, deprecated ordering assertions in `tests/test_dry_run.py`, and each alias's discovery `use_when` text.
Add the release-constraint sentence to `docs/RELEASING.md`.

Measure the delivered catalog on all three backend profiles with the existing handshake-era subprocess wire instrument, recording the revision, and measure the post-removal variant in a temporary worktree that is not pushed.
Compare both against the baseline under [Measurement bounds](#measurement-bounds) and record the numbers in the ADR beside Task 1's projection, saying where they differ.
Move `MEASURED` and `BUDGET` together to the exact delivered catalog size, with no unused headroom.
Do not claim final size savings while the aliases remain present.

Run a concrete host exercise in Codex and Claude Code against the candidate server with synthetic prompts and fake backend executables.
Record host and server versions and whether each host preloads or defers definitions.
Exercise background start followed by status/result retrieval, a terminal replay requiring immediate fetch, keyed start/attach, full unstructured-answer retrieval, and invalid mode arguments followed by a successful repair.
ADR 0045's host scenario is PR B's own, under Task 2, and is not repeated here.
Require correct result/handle interpretation and no duplicate fake worker for keyed attachment.
Use transport tests for task paths that these hosts do not negotiate; do not claim a host tested tasks when it did not.
A missing runnable host or capture harness is a recorded prerequisite failure, not a passing check; PR C stays draft until it is supplied.
Host invocation may consume the host model's quota even with fake backends; obtain execution authorization if needed at implementation time, and do not run live integration suites as a substitute.
Record prompt inputs as IDs and hashes and store no raw host transcript containing user-derived prompt text, following rule 18.
Use the separate `wait-mode` scenario tree so the original single-version host directories remain compatible with `tests/test_host_captures.py`, which reads only the top-level host directories.
Add `tests/test_wait_mode_captures.py` to check version/revision attribution, scenario IDs, required outcome fields, and input-hash records; this checks record shape, while reviewed host execution supplies the behavioral evidence.

**Validation:** `uv run pytest tests/test_meta.py tests/test_surface.py tests/test_discovery_cost.py tests/test_paid_tools.py tests/test_dry_run.py tests/test_wait_mode_captures.py tests/test_release_state.py` plus the host exercise above, then the full repository gate before PR C is marked ready.
**Commit:** `feat(tools): deprecate asynchronous tool aliases`, followed by the final re-pin commit for PR C.
**PR body:** the measured transitional sizes per profile, the post-removal projection, host outcomes, the release constraint, and the selected deprecation versions.

## Task 6: migrate guidance and finish the sweep (PR D)

**Files:** `skills/collaborating-with-amicus/`, `commands/`, `README.md`, `docs/MIGRATION.md`, the design spec, `CHANGELOG.md`; `tests/test_commands.py`, `test_skill_contract.py`, `test_migration_doc.py`.

Update routing, examples, timeout advice, keyed identity explanations, capability tool tables, and sync/async workflow references to lead with merged tools.
Retain alias references only for migration, compatibility tests, and clearly historical ADR/capture evidence.
Keep dry-run routing unchanged and explain that a returned handle can already be terminal.
Keep `commands/amicus/delegate-async.md` available, routing it to `amicus_delegate(wait=false)` and updating its command-contract test; tool deprecation does not remove that user-facing command.
Search executable and current guidance references with `rg '_async|async_twin_for' src skills commands README.md CHANGELOG.md docs/MIGRATION.md docs/superpowers/specs` and classify every surviving match; on the baseline that search names seventeen files outside `src` and `tests`.
Treat `docs/adr`, `docs/reviews`, and existing `docs/host-captures` as historical evidence rather than blindly rewriting old tool names.
Add an Unreleased changelog entry describing the new argument, deprecation window, temporary discovery growth and the release constraint; if PR C's own entry already exists, extend it.
Any guidance or test update that PR B or PR C needs to keep its own gate green moves forward into that PR; PR D is the completeness sweep.

**Validation:** run the complete [repository gate](../../../AGENTS.md#rules), `uv run python scripts/check_sentence_per_line.py`, and `git diff --check`.
**Commit:** `docs(tools): document paid tool wait modes`.

## Fingerprint and pins

PR B and PR C each bump `FINGERPRINT` once, in the pin commit that follows the PR's first surface-changing commit, and every later surface commit in that PR re-pins under the same number; one unreleased PR takes one schema number, as milestone 3's PRs did.
Each pin commit is a dedicated `chore(schemas):` commit that regenerates all affected manifest snapshots, hashes, surface digests, wire-shape pins, and discovery budgets using the regeneration instructions in the relevant tests rather than hand-editing generated fixtures.
In each pin commit, remeasure `MEASURED` and `BUDGET` and add the explanatory schema-change paragraph in `tests/test_discovery_cost.py`.
A surface commit and its pin commit form one validation unit; the pair must pass the full repository gate before the next task proceeds or either is pushed.
The listed task-specific commands are focused development checks and do not replace that gate.
Leave `RESULT_FORMAT` unchanged while stored results remain unchanged; if implementation discovers a necessary stored-shape change, explicitly revise this plan and apply rule 11.
PR A and PR D touch no fingerprint-covered surface and need no pin commit; if PR D's sweep does move one, it takes the same one-bump rule.

## Deferred removal

After the earliest permitted minor release, open a separate PR removing the four aliases, their lifecycle markers, and compatibility-only routing/tests.
Keep shared worker, job status/result/cancel, and dry-run tools intact.
Rerun the full gate and discovery/host measurements against the actual 14-tool catalog, lower the exact budgets, and refresh the fingerprint/pins in their own commit.
Close #247 only when the removal and its measured reduction have landed.

The maintainer reviews and merges each PR; delete this plan once PR D has merged, preserving decisions in ADRs 0043 and 0045.

## Plan review disposition

One Claude read-only consultation reviewed the initial plan against repository code; the author checked its material findings against the source before the first revision.
A second Claude review of the PR at `fc575b9`, and a re-verification of it on 2026-09-26 against `main` and the live wire, produced this revision.
Accepted from those: the untargeted compaction task is replaced by ADR 0045's measured move of repeated prose, the ADR is decided by the maintainer before implementation, the measurement bounds are checkpoints rather than discard rules, the transitional cost is projected before the decision, the fingerprint moves once per PR, the work is split into three PRs, the release constraint is named where the release procedure will see it, the task refusal is one rule with four tests, the identity argument cites that `wait` never enters `RunSpec`, and the sweep names the codex adapter's timeout alternative.
The measurement gate deliberately retains the existing handshake-era byte-exact instrument; modern-era behavior remains covered by transport and host exercises.
The timeout repair deliberately retains the existing no-echo prose fallback rather than introducing partial structured arguments; its reduced usefulness to structured-only consumers is documented and directly tested.
The delegate-async command remains available and routes to the merged tool, independently of the tool alias lifecycle.
A planning PR passes the full repository gate under rule 2 like any other change; the checks that can fail on a docs-only diff are the sentence-per-line test and `git diff --check`, so a green gate is reported as the rule's requirement met and not as evidence that the plan is correct.
The second revision adds ADR 0045 after the maintainer asked whether the #38, #52 and #65 prose could be taken into this plan; the measurements above are its basis, and the condition that no captured host has read a resource is why the pointer leads with the tool path and why host scenarios gate it.
Codex's first round on that revision found that rewritten guard sentences changed the disclosed semantics, that the host scenario missed `lists_diagnostics`, that PR B's bound was mis-based when PR C merges first, and that the failure path contradicted itself; the guards now stay verbatim and only vocabularies move, which cut the projected saving from about 9,500 to about 5,200 bytes, and the ADR says so.
Its second round found that no scenario turned on the moved coverage vocabulary and that the pointer placement was unstated, so the arithmetic could not be checked; the placement is now one pointer per parent field, the saving was measured on a throwaway edit rather than projected, and two coverage scenarios were added.
Each revision was reviewed by Codex before it was pushed; the dispositions are recorded on the PR.
