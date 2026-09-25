# Implementation plan: compact discovery and consolidate paid tool execution

**Status:** Draft, revised after one Claude review; implementation has not started.
**Issue:** [#247](https://github.com/briandconnelly/amicus/issues/247).
**Design:** [design spec](../specs/2026-09-04-amicus-design.md), [proposed ADR 0043](../../adr/0043-each-paid-verb-is-one-tool-with-a-wait-flag.md).
**Baseline:** `9903d1f`; rebase measurements on the implementation branch before changing the surface.
**Scope:** Post-milestone maintenance, with one implementation draft PR following this plan.

## Outcome and boundaries

Expose one tool per paid verb with `wait: bool = true`, preserving existing calls that omit it.
Keep the two free dry-run tools separate because their annotations differ from paid tools.
Keep all four deprecated `_async` tools discoverable and callable for the published two-minor window.
This implementation ends with the deprecation window open; removal belongs to a later PR after the window expires.
The final catalog will have 14 tools, while the transitional catalog retains 18.
Keep this issue open for the later removal and its measured savings.

Start with selective output-schema compaction, then implement the merged paths, and enable deprecation only after the evidence gate below passes.
Tasks 3-4 are candidate commits on the implementation branch until Task 5 passes; they must not merge or ship independently.
If the evidence gate fails, remove those candidate changes before submitting a reduced PR containing only the measured Task 2 compaction and its documentation.
Retain explicit schemas and semantic descriptions for `raw_response.text`, findings, verdict, confidence, `review_status`, coverage, diagnostics, `poll_after_ms`, and `follow_up`.
Output compaction changes advertised supporting detail, never the response payload, its retention, or its summary/full delivery rules.
The already-landed empty FastMCP metadata removal and shorter `timeout_seconds`/`detail` descriptions are baseline behavior.
Version literals, release tags, `.github/**`, `AGENTS.md`, and `CLAUDE.md` are outside this implementation.
Repository rules remain authoritative, especially [the gate and rules 10, 11, 16, and 18](../../../AGENTS.md).

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
Use value checks, not an attempt to distinguish explicit defaults from injected defaults.
Leave the published `detail` default as `"summary"`.

`ok` selects success versus error; required `tool` selects a completed result, and required top-level `job_id` selects a handle.
Keep both success branches closed, retain `meta.job_id` on results, and do not add top-level `job_id` to results or `tool` to handles.
Publish the existing result-plus-handle union through `published_schema`, making `tool` required in the advertised result branch without changing stored payloads.
Add a narrow publication option that requires named fields only in branches declaring them; use it for `tool` and test that no other defaulted field becomes required.

Treat `wait` and `detail` as delivery controls outside `RunSpec`.
Prepare every keyed merged call with `background=True`, regardless of `wait`, so the effective execution deadline in the identity stays equal.
Do not add an unused `wait` exclusion to `IDENTITY_EXCLUDE`.
A start and attach with the same merged tool, workspace, key, and effective run inputs must reserve exactly one worker even when the waiting timeout and detail differ.
Changed effective run inputs still conflict, and the deprecated twins retain their own tool/key namespaces.
Retain existing cancellation, expiry, cap, and failed-result replay semantics.

Keep task support on the waiting path.
If a non-waiting call reaches a task worker, return `invalid_arguments` before `prepare_run` and worker creation, with guidance to use the waiting path or make an ordinary non-task call.
Distinguish a negotiated capability from an actual task execution; advertising task capability alone must not reject an otherwise ordinary call.
The refusal avoids completing a task with merely another asynchronous start; it does not claim that two identifiers are forbidden, since existing waiting tasks already map to jobs.
Document that this refusal may itself be delivered through a task, and do not claim that no task wrapper was created.

For a terminated synchronous timeout, point recovery advice at the merged verb and explicitly instruct a new paid attempt with `wait: false`, omitting `timeout_seconds` and using summary detail.
Preserve the existing omission of prompt-bearing repair arguments and explain how the caller reuses its original inputs.
Do not put an incomplete `{wait: false}` call in `repair.arguments`, or introduce a delta-arguments convention in this change.
For a continuing keyed job, preserve the callable status lookup and job ID; do not recommend a second launch.
For an exhausted job deadline, preserve the advice to narrow the request or change configuration rather than retrying the same exhausted deadline.
This fallback requires reading the repair's prose because prompt-bearing arguments cannot be reconstructed from the structured repair alone.
Record that limitation in the ADR; never describe the merged tool name alone as a complete corrective call.
Pin this guidance with direct tests of both timeout carriers, since `repair_rules` deliberately excludes alternative prose and dynamically selected timeout tools.
Refresh fingerprinted repair rules only where their covered fields actually change, and bump the fingerprint for changed resource and tool guidance as applicable.

## Task 1: amend the ADR and establish measurement fixtures

**Files:** ADR 0043; `tests/test_discovery_cost.py`; `src/amicus/manifest.py`; this plan's baseline record.

Amend ADR 0043 to the contract above, removing the blanket explicit-default rejection and incorrect identity-exclusion rationale.
Replace its claim that `raw_response` is never needed for branching with the unstructured-result recovery contract.
State that closed success branches are already disjoint, while requiring `tool` makes discrimination explicit.
Keep the ADR proposed until the implementation evidence gate passes.
Correct its historical measurement label and distinguish its old 112,683-byte figure from the current baseline.

Record the current per-profile raw stdio measurements, protocol era, tool count, and revision.
Use `uv run python -m amicus.manifest --measure`, which invokes `manifest.tools_list_wire` through a real subprocess and measures the 2025-11-25 result body.
The existing `manifest.tools_list_bytes(profile, *, env=None)` measures the same body and has no protocol-era argument.
Keep that existing byte-exact instrument and era as the budget gate, and distinguish result-body bytes from the entire JSON-RPC line.
Modern-era behavior is exercised by the transport and host tests; this plan does not add a second byte-exact measurement instrument.
The baseline pin is 112,105 bytes for `all`; do not substitute the issue's historical full-line measurement for it.
The previously measured result-plus-handle growth is 1,668 bytes per verb, or 6,672 total, from compact JSON of `publish.published_schema`; treat this schema-level delta as a hypothesis to remeasure on the branch.

Task 1 records only the baseline and validates the existing measurement instrument.
Task 5 compares candidate variants once they exist, using runnable temporary worktrees and actual subprocess measurements.
Any record-copy estimate used during development is a labelled projection and is excluded from acceptance assertions.
Record token counts only when the tokenizer and encoding are pinned; bytes remain the deterministic CI budget.

**Validation:** `uv run pytest tests/test_discovery_cost.py tests/test_manifest.py`.
**Commit:** `test(manifest): measure paid tool consolidation candidates`.
Use `docs(manifest): record discovery consolidation baseline` instead if no instrument test changes are needed.

## Task 2: compact supporting output detail

**Files:** `src/amicus/schemas/publish.py`, `results.py`, `params.py`; `src/amicus/tools/discovery.py`; `tests/test_results.py`, `test_params.py`, and `test_discovery.py`.

First add tests that full result schemas remain retrievable and all schemas still accept actual summary and full payloads.
Add a specific `include_schemas` value for full paid-result schemas, following the existing capabilities-schema pattern.
Replace only `context_summary` in advertised paid-result schemas with a nullable object stub and a short pointer to that on-demand schema.
Keep the dry-run context counts explicit because they inform the decision to spend.
Keep the entire `raw_response` schema explicit in this iteration; its small metadata fields do not justify hiding its recovery text contract.
Use the existing `opaque_fields` and orphan-definition pruning mechanism, preserving nullability and pointer descriptions through noise stripping.
Require a positive measured saving after paying for the new discovery parameter and pointer prose; if it is neutral or negative, retain the explicit schema and record that result.

**Validation:** `uv run pytest tests/test_results.py tests/test_params.py tests/test_discovery.py`.
**Commit:** `perf(schemas): compact supporting review result detail`, only if the measured candidate improves discovery.
Follow each accepted surface change with the separate fingerprint/pin commit described in Task 6.

## Task 3: add the merged execution paths

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
Add a wire-shape fixture for a handle minted under the merged name, retaining the alias fixture.
Update `tests/test_paid_tools.py` pair-parity expectations for the additional merged-only parameter.

**Validation:** `uv run pytest tests/test_wait_mode.py tests/test_sync_tools.py tests/test_async_tools.py tests/test_paid_tools.py tests/test_results.py tests/test_publish.py tests/test_params.py tests/test_wire_shape.py`.
**Commit:** `feat(tools): support non-waiting calls on paid verbs`.

## Task 4: prove job identity, task behavior, and repair migration

**Files:** `tests/test_wait_mode.py`, `test_tasks_client.py`, `test_tasks_spike.py`, `test_errors.py`, `test_lifecycle.py`, `test_run.py`, `test_prepare.py`, `test_dry_run.py`, `test_surface_honesty.py`; `src/amicus/errors.py`; `src/amicus/jobs/lifecycle.py`; `src/amicus/tools/dry_run.py`, `_prepare.py`, `_resolve.py`; relevant error rule definitions.

Test keyed false-to-true attachment and true-to-false replay, both while running and after completion.
Assert one worker start, one job ID, equal effective identity across wait/detail changes, conflict on changed run inputs, and independent aliases.
Cover cancellation of one keyed waiter, retention/cap refusal, missing or expired keyed results, and terminal failure without a duplicate launch.
Test the task matrix with tasks disabled, capability absent, capability present on an ordinary call, and actual task execution.
For a tasked false call, assert the error has the correct carrier and `isError`, and no model worker starts.
For tasked true calls, preserve job/task lookup, cancellation, and keyed recovery behavior.

Sweep `async_twin_for`, timeout alternatives, deadline advisories, paid-tool descriptions, and structured per-code repair rules.
Include `TIMEOUT_ALTERNATIVE`, `KEYED_TIMEOUT_ALTERNATIVE`, `JOB_DEADLINE_TIMEOUT_ALTERNATIVE`, and the full `idempotency_key` ParamContract text.
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
**Commit:** `fix(jobs): preserve recovery across paid tool wait modes`.

## Task 5: run the evidence gate and open deprecation

**Files:** `src/amicus/tools/_meta.py`; tool registration/order and discovery modules; `tests/test_meta.py`, `test_surface.py`, `test_paid_tools.py`, `test_dry_run.py`; new `tests/test_wait_mode_captures.py`; `docs/host-captures/wait-mode/<host>/<version>/` evidence summaries; ADR 0043.

Before adding lifecycle markers, compare complete candidate catalogs, including marker text, new union branches, `wait` parameters, changed descriptions, and on-demand schema additions.
Build runnable temporary candidate worktrees for baseline, compacted-only, merged-with-aliases-and-markers, and post-removal variants, with and without compaction.
Do not publish the removal variant or merge the candidate commits until this gate passes.
Measure all three backend profiles using the existing handshake-era subprocess wire instrument, recording the revision for each variant.
Apply the acceptance bounds to merge-only deltas against the compacted-only revision: require at least 15,000 bytes saved after removal and no more than 10,000 bytes of transitional growth per profile.
Report cumulative deltas against the original baseline separately, so compaction cannot conceal weak consolidation savings.
These are proposed acceptance bounds for this implementation, not already observed results; if they fail, discard Tasks 3-4 and the marker candidate, and retain only beneficial Task 2 compaction with revised documentation.
Move `MEASURED` and `BUDGET` together to the exact delivered catalog size, with no unused headroom.

Run a concrete host exercise in Codex and Claude Code against the candidate server with synthetic prompts and fake backend executables.
Record host and server versions and whether each host preloads or defers definitions.
Exercise background start followed by status/result retrieval, a terminal replay requiring immediate fetch, keyed start/attach, full unstructured-answer retrieval, and invalid mode arguments followed by a successful repair.
Require correct result/handle interpretation and no duplicate fake worker for keyed attachment.
Use transport tests for task paths that these hosts do not negotiate; do not claim a host tested tasks when it did not.
A missing runnable host or capture harness is a recorded prerequisite failure, not a passing check; keep the ADR proposed and deprecation disabled until it is supplied.
Host invocation may consume the host model's quota even with fake backends; obtain execution authorization if needed at implementation time, and do not run live integration suites as a substitute.
Record prompt inputs as IDs and hashes and store no raw host transcript containing user-derived prompt text, following rule 18.
Use the separate `wait-mode` scenario tree so the original single-version host directories remain compatible with `tests/test_host_captures.py`.
Add `tests/test_wait_mode_captures.py` to check version/revision attribution, scenario IDs, required outcome fields, and input-hash records; this checks record shape, while reviewed host execution supplies the behavioral evidence.

After the gate passes, mark ADR 0043 accepted and add the four lifecycle markers with replacement tool and `wait: false` migration instructions.
Choose `since` as the actual next minor release and `removal_at_or_after` two minor releases later without changing package version literals in this PR.
The next release after implementation merges must be that minor release, currently 0.7.0; resolve any planned patch release before opening the deprecation window.
Keep deprecated tools as a contiguous suffix of their active cost group, preserving their relative order and all annotation semantics.
Test the marker window, discoverability, old-call behavior, and byte-identical alias input/output schemas against the pre-merge baseline.
Update the exact lifecycle assertions in `tests/test_paid_tools.py`, deprecated ordering assertions in `tests/test_dry_run.py`, and each alias's discovery `use_when` text.

**Validation:** `uv run pytest tests/test_meta.py tests/test_surface.py tests/test_discovery_cost.py tests/test_paid_tools.py tests/test_dry_run.py tests/test_wait_mode_captures.py` plus the host exercise above.
**Commit:** `feat(tools): deprecate asynchronous tool aliases`.

## Task 6: migrate guidance, refresh pins, and finish the implementation PR

**Files:** `skills/collaborating-with-amicus/`, `commands/`, `README.md`, `docs/MIGRATION.md`, the design spec, `CHANGELOG.md`; `tests/test_commands.py`, `test_skill_contract.py`, `test_migration_doc.py`; fingerprint and fixture files covered by existing regeneration tests.

Update routing, examples, timeout advice, keyed identity explanations, capability tool tables, and sync/async workflow references to lead with merged tools.
Retain alias references only for migration, compatibility tests, and clearly historical ADR/capture evidence.
Keep dry-run routing unchanged and explain that a returned handle can already be terminal.
Keep `commands/amicus/delegate-async.md` available, routing it to `amicus_delegate(wait=false)` and updating its command-contract test; tool deprecation does not remove that user-facing command.
Search executable and current guidance references with `rg '_async|async_twin_for' src skills commands README.md CHANGELOG.md docs/MIGRATION.md docs/superpowers/specs` and classify every surviving match.
Treat `docs/adr`, `docs/reviews`, and existing `docs/host-captures` as historical evidence rather than blindly rewriting old tool names.
Add an Unreleased changelog entry describing the new argument, deprecation window, and temporary discovery growth.

After each coherent fingerprint-covered surface change, bump `FINGERPRINT` and regenerate all affected manifest snapshots, hashes, surface digests, wire-shape pins, and discovery budgets in a dedicated `chore(schemas):` commit.
This applies immediately after each surface-changing task, including candidate Tasks 3-4, rather than being deferred until Task 6.
In each pin commit, remeasure `MEASURED` and `BUDGET` and add the explanatory schema-change paragraph in `tests/test_discovery_cost.py`.
A surface commit and its pin commit form one validation unit; the pair must pass the full repository gate before the next task proceeds or either is pushed.
The listed task-specific commands are focused development checks and do not replace that gate.
Move any dependent guidance/test update forward into the surface-changing task when needed to keep its validation unit green; Task 6 is the final completeness sweep.
Use the existing regeneration instructions in the relevant tests rather than hand-editing generated fixtures.
Leave `RESULT_FORMAT` unchanged while stored results remain unchanged; if implementation discovers a necessary stored-shape change, explicitly revise this plan and apply rule 11.
Do not claim final size savings while the aliases remain present.

**Validation:** run the complete [repository gate](../../../AGENTS.md#rules), `uv run python scripts/check_sentence_per_line.py`, and `git diff --check`.
**Commits:** `docs(tools): document paid tool wait modes`, followed by dedicated `chore(schemas): refresh compact discovery pins` commits where required.
Update the draft PR with measured transition/final sizes, host outcomes, test results, and the selected deprecation versions.
The maintainer reviews and merges; delete this plan once implemented and merged, preserving decisions in ADR 0043.

## Deferred removal

After the earliest permitted minor release, open a separate PR removing the four aliases, their lifecycle markers, and compatibility-only routing/tests.
Keep shared worker, job status/result/cancel, and dry-run tools intact.
Rerun the full gate and discovery/host measurements against the actual 14-tool catalog, lower the exact budgets, and refresh the fingerprint/pins in their own commit.
Close #247 only when the removal and its measured reduction have landed.

## Plan review disposition

One Claude read-only consultation reviewed the initial plan against repository code; the author checked its material findings against the source before revising this document.
Accepted corrections cover the actual measurement helper, merge-gate rollback, immediate pin/budget commits, timeout-carrier prose tests, separate scenario capture storage, missing compatibility tests, capability descriptions, and explicit acceptance baselines.
The measurement gate deliberately retains the existing handshake-era byte-exact instrument; modern-era behavior remains covered by transport and host exercises.
The timeout repair deliberately retains the existing no-echo prose fallback rather than introducing partial structured arguments; its reduced usefulness to structured-only consumers is documented and directly tested.
The delegate-async command remains available and routes to the merged tool, independently of the tool alias lifecycle.
The final revised plan has not received a second model pass.
