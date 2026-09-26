# Implementation plan: one paid tool per verb with a `wait` flag

**Status:** Draft, revised 2026-09-26 after two reviews; implementation has not started.
**Issue:** [#247](https://github.com/briandconnelly/amicus/issues/247).
**Design:** [design spec](../specs/2026-09-04-amicus-design.md), [proposed ADR 0043](../../adr/0043-each-paid-verb-is-one-tool-with-a-wait-flag.md).
**Baseline:** `main` at `2ab6a8c`, the tree after v0.7.0 shipped on 2026-09-26; the `all` profile measures 112,105 bytes there, as `MEASURED` in `tests/test_discovery_cost.py` pins.
**Scope:** Post-milestone maintenance, executed as three draft PRs in the order below, as milestone 3's plan was executed as PRs #255 to #258.

## Outcome and boundaries

Expose one tool per paid verb with `wait: bool = true`, preserving existing calls that omit it.
Keep the two free dry-run tools separate because their annotations differ from paid tools.
Keep all four deprecated `_async` tools discoverable and callable for the published two-minor window.
This implementation ends with the deprecation window open; removal belongs to a later PR after the window expires.
The final catalog will have 14 tools, while the transitional catalog retains 18.
Keep this issue open for the later removal and its measured savings.

This plan does not trim output schemas or parameter prose, which are remediation items 2 and 3 of #247.
The reason is measured, not assumed: on the baseline wire, output schemas are 53,690 of the 112,105 bytes, but the fields ADR 0043 names as never branched on are small.

| Output-schema field on the baseline wire | Occurrences | Bytes |
| --- | --- | --- |
| `context_summary` | 3, one of them the dry run | 576 |
| `raw_response` | 4 | 1,020 |
| `coverage` | 3 | 5,874 |
| `findings` | 4 | 2,160 |

Hiding `context_summary` behind an `include_schemas` value would save at most 384 bytes on the paid tools before paying for a stub, a pointer sentence and a new enum value on `amicus_capabilities`, so it is dropped rather than carried as a task that cannot pay for itself.
The fields large enough to matter are the ones #38, #52 and #65 chose to keep explicit, and ADR 0043 records that they are not trimmed; changing that is a design decision for a later ADR, recorded on #247 in PR A, not a task here.
Retain explicit schemas and semantic descriptions for `raw_response.text`, findings, verdict, confidence, `review_status`, coverage, diagnostics, `poll_after_ms`, and `follow_up`.
The already-landed empty FastMCP metadata removal and shorter `timeout_seconds`/`detail` descriptions are baseline behavior.
Version literals, release tags, `.github/**`, `AGENTS.md`, and `CLAUDE.md` are outside this implementation.
Repository rules remain authoritative, especially [the gate and rules 10, 11, 16, and 18](../../../AGENTS.md).

## Decision sequence

The maintainer decides the design; measurements check its cost.
A byte count can show that one tool with a mode flag is cheap enough, and it cannot show that it is the right interface, so the two are separated.

1. PR A (Task 1) amends ADR 0043 and records the baseline and a projected transitional cost; the maintainer's merge of PR A, with the ADR's status moved to Accepted, is the design decision.
2. PR B (Tasks 2 to 4) implements the merge, proves identity, task and repair behavior, measures the delivered catalog against the bounds below, and opens the deprecation window; a measurement outside its bound stops PR B at a checkpoint for the maintainer rather than discarding work.
3. PR C (Task 5) migrates guidance and finishes the sweep.
4. The removal PR follows the window under [Deferred removal](#deferred-removal).

No implementation commit is made before PR A merges.

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
The tests are the four rows of the matrix in Task 3.

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

The lifecycle markers name `since` as the first minor release after PR B merges, currently 0.8.0, and `removal_at_or_after` two minors later, currently 0.10.0, without changing any version literal.
`check_deprecations` in `scripts/check_release_state.py` rejects a tag whose version is below any marker's `since`, and `tests/test_meta.py` requires `since` to be an `X.Y.0`, so between PR B merging and the 0.8.0 tag no patch release can be tagged.
The gate does not warn about this at merge time; the `verify` job refuses the tag.
PR B therefore adds one sentence to the Preconditions of `docs/RELEASING.md` naming the constraint and the markers that impose it, and states it in its PR body, so whoever cuts the next release sees it before choosing a version.
If a patch release is planned, it ships before PR B merges.

## Measurement bounds

Both bounds are per profile and are checked on the delivered catalog, not on estimates.
They are checkpoints: a miss stops PR B and puts the measured numbers on the PR for the maintainer, who chooses between proceeding with the numbers as they are, revising the ADR, or superseding it.
Nothing is discarded automatically.

- Transitional growth, the marker-and-`wait` catalog against the baseline: no more than 10,000 bytes.
- Post-removal saving, the 14-tool catalog against the baseline: at least 15,000 bytes.

The four `_async` records measure 26,452 bytes on the baseline, and the permanent handle branch was measured in-process at 1,668 bytes per verb, 6,672 in all, so the removal saving is expected near 18,000 bytes and the transitional growth near the cap once the four `wait` parameters, four markers, four description leads and the merged tools' longer descriptions are added.
That closeness is why Task 1 projects the transitional cost before PR A merges.

## Task 1: amend ADR 0043 and record the baseline (PR A)

**Files:** ADR 0043; `tests/test_discovery_cost.py` only if the instrument needs a change; the issue #247 thread.

Amend ADR 0043 to the contract above: remove the `IDENTITY_EXCLUDE` sentence and its rationale, replace its claim that `raw_response` is never needed for branching with the unstructured-result recovery contract, and state that closed success branches are already disjoint while requiring `tool` makes discrimination explicit.
Correct its measurement label: `tests/test_discovery_cost.py` measures the raw stdio wire through `manifest.tools_list_wire`, not in-process, and the current baseline is 112,105 bytes on `all`, distinct from the ADR's historical 112,683 and the issue's 112,730 full-line figure.
Record in the ADR that output-schema trimming is deferred, with the field table above, and post the same table on #247 so the deferral is visible where the remediation list lives.
Add the release constraint above to the ADR's consequences.
Move the ADR's status to Accepted with the date; the maintainer's merge of PR A is the decision, and PR B's checkpoints can send it back.

Record the current per-profile raw stdio measurements, protocol era, tool count, and revision.
Use `uv run python -m amicus.manifest --measure`, which invokes `manifest.tools_list_wire` through a real subprocess and measures the 2025-11-25 result body.
The existing `manifest.tools_list_bytes(profile, *, env=None)` measures the same body and has no protocol-era argument.
Keep that existing byte-exact instrument and era as the budget gate, and distinguish result-body bytes from the entire JSON-RPC line.
Modern-era behavior is exercised by the transport and host tests; this plan does not add a second byte-exact measurement instrument.

Project the transitional cost on a throwaway branch that is never pushed: four `DEPRECATED_TOOLS` entries with the intended migration text, a boolean `wait` parameter with its intended description on the four sync tools, the four description leads, and the union output schema, measured with the same instrument on all three profiles.
Record the per-profile numbers in the ADR as a labelled projection; they inform the maintainer's decision and are excluded from acceptance assertions, which Task 4 makes on the delivered catalog.
Record token counts only when the tokenizer and encoding are pinned; bytes remain the deterministic CI budget.

**Validation:** `uv run pytest tests/test_discovery_cost.py tests/test_manifest.py tests/test_check_sentence_per_line.py`, and the full [repository gate](../../../AGENTS.md#rules) before the PR is marked ready.
**Commit:** `docs(schemas): amend ADR 0043 and record the consolidation baseline`.

## Task 2: add the merged execution paths (PR B)

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
**Commit:** `feat(tools): support non-waiting calls on paid verbs`, followed by the pin commit described in [Fingerprint and pins](#fingerprint-and-pins).

## Task 3: prove job identity, task behavior, and repair migration (PR B)

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

## Task 4: measure, exercise hosts, and open deprecation (PR B)

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
Require correct result/handle interpretation and no duplicate fake worker for keyed attachment.
Use transport tests for task paths that these hosts do not negotiate; do not claim a host tested tasks when it did not.
A missing runnable host or capture harness is a recorded prerequisite failure, not a passing check; PR B stays draft until it is supplied.
Host invocation may consume the host model's quota even with fake backends; obtain execution authorization if needed at implementation time, and do not run live integration suites as a substitute.
Record prompt inputs as IDs and hashes and store no raw host transcript containing user-derived prompt text, following rule 18.
Use the separate `wait-mode` scenario tree so the original single-version host directories remain compatible with `tests/test_host_captures.py`, which reads only the top-level host directories.
Add `tests/test_wait_mode_captures.py` to check version/revision attribution, scenario IDs, required outcome fields, and input-hash records; this checks record shape, while reviewed host execution supplies the behavioral evidence.

**Validation:** `uv run pytest tests/test_meta.py tests/test_surface.py tests/test_discovery_cost.py tests/test_paid_tools.py tests/test_dry_run.py tests/test_wait_mode_captures.py tests/test_release_state.py` plus the host exercise above, then the full repository gate before PR B is marked ready.
**Commit:** `feat(tools): deprecate asynchronous tool aliases`, followed by the final re-pin commit for PR B.
**PR body:** the measured transitional sizes per profile, the post-removal projection, host outcomes, the release constraint, and the selected deprecation versions.

## Task 5: migrate guidance and finish the sweep (PR C)

**Files:** `skills/collaborating-with-amicus/`, `commands/`, `README.md`, `docs/MIGRATION.md`, the design spec, `CHANGELOG.md`; `tests/test_commands.py`, `test_skill_contract.py`, `test_migration_doc.py`.

Update routing, examples, timeout advice, keyed identity explanations, capability tool tables, and sync/async workflow references to lead with merged tools.
Retain alias references only for migration, compatibility tests, and clearly historical ADR/capture evidence.
Keep dry-run routing unchanged and explain that a returned handle can already be terminal.
Keep `commands/amicus/delegate-async.md` available, routing it to `amicus_delegate(wait=false)` and updating its command-contract test; tool deprecation does not remove that user-facing command.
Search executable and current guidance references with `rg '_async|async_twin_for' src skills commands README.md CHANGELOG.md docs/MIGRATION.md docs/superpowers/specs` and classify every surviving match; on the baseline that search names seventeen files outside `src` and `tests`.
Treat `docs/adr`, `docs/reviews`, and existing `docs/host-captures` as historical evidence rather than blindly rewriting old tool names.
Add an Unreleased changelog entry describing the new argument, deprecation window, temporary discovery growth and the release constraint; if PR B's own entry already exists, extend it.
Any guidance or test update that PR B needs to keep its own gate green moves forward into PR B; PR C is the completeness sweep.

**Validation:** run the complete [repository gate](../../../AGENTS.md#rules), `uv run python scripts/check_sentence_per_line.py`, and `git diff --check`.
**Commit:** `docs(tools): document paid tool wait modes`.

## Fingerprint and pins

PR B bumps `FINGERPRINT` once, in the pin commit that follows its first surface-changing commit, and every later surface commit in PR B re-pins under that same number; one unreleased PR takes one schema number, as milestone 3's PRs did.
Each pin commit is a dedicated `chore(schemas):` commit that regenerates all affected manifest snapshots, hashes, surface digests, wire-shape pins, and discovery budgets using the regeneration instructions in the relevant tests rather than hand-editing generated fixtures.
In each pin commit, remeasure `MEASURED` and `BUDGET` and add the explanatory schema-change paragraph in `tests/test_discovery_cost.py`.
A surface commit and its pin commit form one validation unit; the pair must pass the full repository gate before the next task proceeds or either is pushed.
The listed task-specific commands are focused development checks and do not replace that gate.
Leave `RESULT_FORMAT` unchanged while stored results remain unchanged; if implementation discovers a necessary stored-shape change, explicitly revise this plan and apply rule 11.
PR A and PR C touch no fingerprint-covered surface and need no pin commit; if PR C's sweep does move one, it takes the same one-bump rule.

## Deferred removal

After the earliest permitted minor release, open a separate PR removing the four aliases, their lifecycle markers, and compatibility-only routing/tests.
Keep shared worker, job status/result/cancel, and dry-run tools intact.
Rerun the full gate and discovery/host measurements against the actual 14-tool catalog, lower the exact budgets, and refresh the fingerprint/pins in their own commit.
Close #247 only when the removal and its measured reduction have landed.

The maintainer reviews and merges each PR; delete this plan once PR C has merged, preserving decisions in ADR 0043.

## Plan review disposition

One Claude read-only consultation reviewed the initial plan against repository code; the author checked its material findings against the source before the first revision.
A second Claude review of the PR at `fc575b9`, and a re-verification of it on 2026-09-26 against `main` and the live wire, produced this revision.
Accepted from those: the compaction task is dropped with its measured reason, the ADR is decided by the maintainer before implementation, the measurement bounds are checkpoints rather than discard rules, the transitional cost is projected before the decision, the fingerprint moves once per PR, the work is split into three PRs, the release constraint is named where the release procedure will see it, the task refusal is one rule with four tests, the identity argument cites that `wait` never enters `RunSpec`, and the sweep names the codex adapter's timeout alternative.
The measurement gate deliberately retains the existing handshake-era byte-exact instrument; modern-era behavior remains covered by transport and host exercises.
The timeout repair deliberately retains the existing no-echo prose fallback rather than introducing partial structured arguments; its reduced usefulness to structured-only consumers is documented and directly tested.
The delegate-async command remains available and routes to the merged tool, independently of the tool alias lifecycle.
A planning PR passes the full repository gate under rule 2 like any other change; the checks that can fail on a docs-only diff are the sentence-per-line test and `git diff --check`, so a green gate is reported as the rule's requirement met and not as evidence that the plan is correct.
This revision was reviewed by Codex before it was pushed; its disposition is recorded on the PR.
