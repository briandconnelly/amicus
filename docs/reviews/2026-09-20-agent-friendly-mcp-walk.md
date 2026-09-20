# amicus — agent-friendly-mcp review walk

**Date:** 2026-09-20
**Reviewed surface:** `amicus/0.1/schema-39` (18 tools, 4 resources, 2 resource templates, 0 prompts), at `0.5.0`, `RESULT_FORMAT` 9.
**Protocol target:** MCP 2026-07-28, served dual-era; the `io.modelcontextprotocol/tasks` extension advertised only under `AMICUS_TASKS=1`.
**Protocol declared by:** `src/amicus/server.py` `CAPABILITY_SUMMARY` and `amicus_capabilities.protocol_revision`.
**Checklist:** `.claude/skills/agent-friendly-mcp/references/contract-checklist.md`; protocol `references/review-workflow.md`.
**Route:** full walk, §1–§9.
**Outcome:** no Critical and no Major findings survived review; the surface does not move for this walk.

Unlike the 2026-09-07 walk, which replayed committed captures and re-ran nothing, every probe here was re-run live against the current tree.
The reason is in the header: the surface has moved 33 schema versions, so the committed captures describe a different server.
The cost is that this walk's probe evidence is a re-runnable command rather than a committed artifact, and each probe below carries the command that reproduces it.
No paid backend call was made by any probe.
One paid call was made outside the probes: a single `amicus_consult` to `codex` that produced the second of the three independent reads below.

## How this walk was produced

Three independent reads, in order, each with a different job.

1. A Claude read of the wire surface, with every finding grounded in a re-run probe.
2. A Codex read of the same surface, commissioned through `amicus_consult` (`high` effort, 697s, `job_id` `0505acc8`), given the checklist and the repo but not the first read's findings.
3. A Fable read whose only job was to attack the merged findings of the first two, with the repo available and an explicit instruction that the highest-value outcome was an ADR either of the first two had missed.

The third read is why this document reports no Majors.
Every factual observation from reads 1 and 2 reproduced under read 3.
Three of the four Major findings did not survive it: two were decisions already recorded in an ADR neither of the first two readers cited, and one rested on an impact claim that is false.
That is the result worth recording, more than the findings themselves.

## Findings

#### Finding 1 — `FINGERPRINT_COVERS_DESC` claims a coverage the fingerprint does not have

- **Severity:** Minor
- **Section:** `§9` (`[9.fingerprint-coverage]`, `[9.fingerprint-format]`), `§1` (`[1.metadata-contract]`)
- **Summary:** The published description says a contract-semantic change in any listed category moves the fingerprint, `tool_annotations` is a listed category, and a change to `tool_annotations` does not move the fingerprint.
- **Evidence:** `src/amicus/schemas/fingerprint.py` lists `tool_annotations` in `FINGERPRINT_COVERS`, and `FINGERPRINT_COVERS_DESC` states "A contract-semantic change in any listed category changes the fingerprint; nothing outside them does."
  Measured across the three manifest profiles: `all` returns fingerprint `amicus/0.1/schema-39`, `surface_digest` `7fa04653ef5f5f2e`, `amicus_consult.destructiveHint` `true`; `codex-kimi` returns the same fingerprint, `surface_digest` `234f041a472c4508`, and `destructiveHint` `false`.
  The annotation moved, the digest moved, the fingerprint did not.
  The tension is sharper than a single false sentence: instructions rule 9 tells an agent the digest "covers only the server-side catalog records and this text", implying the fingerprint is the broader of the two, while for `tool_annotations` the digest is strictly the more sensitive one.
- **Remediation:** Correct `FINGERPRINT_COVERS_DESC` rather than the fingerprint.
  Encoding the profile in the fingerprint is not cleanly actionable: `parse_fingerprint`'s grammar fixes `name/major/schema-N`, `[9.fingerprint-format]` makes a computation change breaking, and issue #137 already owns that parser.
  Say instead that the fingerprint identifies the code revision's contract and that per-profile variance in `tool_annotations` and `enabled_backends` is carried by `surface_digest` and `enabled_backends`.
  That edit is itself a `capabilities_payload` change, so repo rule 10 applies and the fingerprint moves once for the correction.
  Open, not applied.

#### Finding 2 — ADR 0021's deferred repair question is still open

- **Severity:** Minor
- **Section:** `§6` (`[6.repair-callable]`, `[6.repair-object]`)
- **Summary:** Five failure paths return a `repair` an agent cannot execute, which is the shape ADR 0021 deliberately deferred rather than a defect it missed.
- **Evidence:** Captured on the wire from a real `amicus.server` stdio subprocess: an invalid `backend` enum and a blank `question` both return `repair.tool` set with no `arguments`; `not_a_git_repo` and `invalid_commit` return `{next_step, alternative}` with no `tool`; a `resources/read` of an unknown URI returns the same tool-less shape in JSON-RPC `error.data.repair`.
  `feature_unsupported` and `job_not_found` return literally callable repairs, so the server already has the wanted shape on other paths.
  `docs/adr/0021-repair-arguments-are-a-complete-call.md:49-51` records the first case exactly: "An `invalid_arguments` repair whose correction is not unique (an enum value, a missing argument, or a free-form survivor) still names the failing tool with no arguments… changing it is left to a decision of its own."
  Line 53 records the second: next steps naming no call "keep their repair, because they are pontonier's closed vocabulary and a central 'call or nothing' invariant would strip them from every code."
- **Remediation:** Do not adopt a blanket "omit `repair` when no callable tool exists" rule.
  `docs/host-captures/install-smoke/claude-code/2.1.263/transcript.md:84-87` shows a model reading `not_a_git_repo` with `next_step: init_git_repo` and correctly declining to spend, which that rule would delete.
  The honest scope is ADR 0021's own deferred question, for the non-unique `invalid_arguments` case only.
  Open by prior decision; recorded here, not re-opened.

#### Finding 3 — `amicus_job_consume_result` declares `destructiveHint: false` on a delete

- **Severity:** Minor
- **Section:** `§3` (`[3.honest-annotations]`, `[3.annotation-defaults]`, `[3.document-reading]`)
- **Summary:** The one tool whose purpose is to delete a retained paid result advertises the annotation reserved for calls that do not remove state a caller may still need.
- **Evidence:** `src/amicus/sdk/conventions/annotations.py` `job_mutate` hardcodes `destructiveHint: False` for both consume and cancel, and its docstring reasons only about idempotency, never about destructiveness.
  The wire carries `{readOnlyHint: false, destructiveHint: false, idempotentHint: false}` for `amicus_job_consume_result`, whose own description says it deletes the record and that a repeat returns `job_not_found`.
  `[3.honest-annotations]` reserves `destructiveHint: true` for calls that "remove state a caller may still need", naming deletes as the case.
  No ADR, comment or test records a rationale: ADR 0001 covers paid tools only, and `tests/test_discovery.py:54-57` pins consume's `read_only_hint` and `idempotent_hint` and never either tool's `destructive_hint`, so the manifest snapshot is the sole guard.
- **Remediation:** Flip `destructiveHint` to `true` in `job_mutate(idempotent=False)`, decide `amicus_job_cancel` deliberately in the same change (it SIGKILLs a worker and removes its worktree), record the reading in `annotations_reading` as `[3.document-reading]` requires, add a test pin beside the existing assertions, regenerate the three manifest snapshots, and bump `FINGERPRINT` because `tool_annotations` is covered.
  Filed as issue #213.

#### Finding 4 — every paid tool advertises backends that cannot serve it

- **Severity:** Minor
- **Section:** `§3` (`[3.strict-types]`), `§2` (`[2.pd-reduction]`)
- **Summary:** `backend` is one closed enum of three on every paid tool, including the five where two of the three values can never succeed, and every profile registers all 18 tools.
- **Evidence:** `amicus_delegate`, `amicus_delegate_async`, `amicus_delegate_dry_run`, `amicus_adversarial_review` and `amicus_adversarial_review_async` all publish `enum: ["codex", "kimi", "claude"]`; `src/amicus/tools/_resolve.py` rejects the unsupported pairing afterwards with `feature_unsupported`.
  Measured per profile: the delegate family is 18,435 bytes and the adversarial family 21,807 bytes, and all three profiles register 18 tools, so the `claude` profile carries the first as dead weight and `codex-kimi` the second.
- **Remediation:** None applied, and none obviously correct; three considerations pull against the narrowing this finding suggests.
  The pairing is already disclosed on three agent-visible surfaces — each tool's description ("Codex and Kimi in v1 (feature delegate); Claude stays review-only", "Claude only in v1 (feature adversarial_review)"), the server instructions, and the `amicus_capabilities` tool table's per-tool `backends` list — so an agent that reads the description does not reach the failure.
  The enum is `BackendId`, one closed `Literal` shared by every tool by design, and ADR 0012's "Known gaps" names that `Literal` as the reason a third-party backend "loads and then stops"; open issue #16 is about *widening* it, so narrowing it per tool needs #16 decided first.
  The catalog tax is paid only by a preloading client, which is Codex CLI and not Claude Code (`tests/test_discovery_cost.py`, ADR 0012), and only on a non-default profile.
  The legitimate residue is narrower than the finding: no document records why the catalog is not reduced per profile, which `[2.pd-reduction]` names as a valid mechanism and which the static-per-process design would support without `list_changed`.
  Open as a question, not a defect.

#### Finding 5 — `invalid_workspace_root` collapses four causes into one code with no machine-readable reason

- **Severity:** Minor
- **Section:** `§6` (`[6.field-feedback]`)
- **Summary:** Four distinct workspace failures share one code and one `details` shape, and the text that tells them apart exists only in `message`.
- **Evidence:** A missing `workspace_root`, a relative one and a nonexistent one all return code `invalid_workspace_root` with `details` `{field: "workspace_root", field_withheld: false}` and no `reason`; the distinguishing text ("no workspace_root was given…", "workspace_root must be an absolute path", "not a directory: …") appears only in `message`.
  `src/amicus/orchestration/workspace.py:71,76,89,108` produces four distinct `error_detail` strings under the one code, the fourth being the deleted-cwd case of issue #170, and `src/amicus/tools/_prepare.py:156-166` builds `ErrorDetail(field="workspace_root")` without carrying that detail into `reason`.
  `ErrorDetail.reason` exists (`src/amicus/schemas/envelope.py:242`) and is populated for `invalid_arguments`, so this is an omission rather than a missing field.
  The three reachable causes call for three different corrections.
- **Remediation:** Populate `reason` from the same `resolution.error_detail`, through the same `redaction.sanitize_echo_prose` the message already uses, since the string can contain a resolved path.
  Omitting `repair` on this code stays correct: the corrected value is caller-supplied, and `[6.repair-callable]` forbids a placeholder argument.
  Filed as issue #214.

#### Finding 6 — a docstring justifies a design with a premise the server contradicts

- **Severity:** Nit
- **Section:** `§4` (`[4.description-constraints]`), `§6` (`[6.resource-errors]`)
- **Summary:** `amicus://models/{backend}` returns an informational payload for a known-but-unavailable backend "because a resource read has no repair carrier to put one in", and a resource read does have one.
- **Evidence:** `src/amicus/tools/resources.py:190-194` carries that reason.
  A captured `resources/read` of an unknown URI returned JSON-RPC `-32602` with `error.data.repair` populated (`{next_step: "list_resources", alternative: …}`), and instructions rule 5 tells agents to branch on `error.data.machine_code`.
  The design the sentence justifies is independently sound; only the reason is false.
  It is a docstring rather than an agent-visible surface, which is why this is a Nit and not the Minor it was first rated.
- **Remediation:** Rewrite the reason to say that a known-but-unavailable backend returns `available: false` so an agent can read the catalog without treating the backend as absent, and that an unknown id returns `resource_not_found` in JSON-RPC `error.data`.
  Open, not applied.

## Withdrawn during review

#### Withdrawn 1 — static resource bodies ship `ttlMs: 0`

Raised independently by two of the three readers, at Minor, and withdrawn on the third.
The observation reproduces: `amicus://error-envelope` (14,759 bytes), `amicus://result-meta` (8,053) and `amicus://params` (6,170) are process-static and carry `ttlMs: 0`, while the catalog methods carry 300,000.
`docs/adr/0018-the-catalog-carries-a-ttl-and-resource-reads-do-not.md:58-59` decides exactly this — "`resources/read` carries no hint at all… there is no client-visible cost to leaving four small static reads uncached" — and line 31 records that the per-URI override this finding proposed was considered and rejected.
Both readers who raised it also named the wrong cause: ADR 0018:28 rebuts the claim that `amicus://capabilities` is the volatile read, since `capabilities_payload` reports `enabled_backends` from settings and is fixed per process.
The volatile reads are the two templates.
The SDK keys `Server.cache_hints` by method, so a per-resource TTL is not expressible in amicus without patching the SDK.

## Instrument defects in this walk

Recorded because a walk that hides them is worth less than its findings.

1. **A probe harness that could not fail.** The first Claude probe built its app with `manifest.app_for_profile`, which loads no backends, so five probes returned `backend_unavailable` and never reached the validation path they were written to exercise.
   Re-run against `server.create_app(config.settings())`.
2. **A stdio client that closed `stdin`.** The first raw JSON-RPC probe wrote all requests then closed `stdin`, and the server exited on EOF before answering the later ones, presenting as "the server answers `server/discover` and then stops".
   Three requests, then two, then one, across three runs — the inconsistency is what exposed it.
   Fixed by holding `stdin` open and reading one response at a time.
3. **A hypothesis killed before it was reported.** That the 35,313 bytes of byte-identical repeated sub-schemas were `$defs` flattened by a downstream layer.
   Measured: `published_schema(ReviewResult)` is 8,363 bytes with `$defs` and the wire body is 8,493, so inlining costs about 130 bytes per tool and is sometimes negative.
   ADR 0024's premise that "the published schemas inline every model per tool, so sharing a type saves no wire bytes" holds, and the duplication is cross-tool, which the per-tool `Tool` record makes unavoidable.
4. **A false impact claim in a Major finding.** Finding 3 was first written as allowing an agent to discard a paid result "at read-grade friction".
   That is wrong: `amicus_job_consume_result` is `readOnlyHint: false`, which is mutation grade.
   The captured hosts gate on `readOnlyHint` and no capture shows either changing behaviour on `destructiveHint` (`docs/host-captures/install-smoke/codex/0.153.4/transcript.md:63-69`), so the defect is contract honesty and carries no demonstrated approval bypass.
5. **A byte count that disagreed with the ratchet.** The third reader measured the catalog at 112,443 bytes.
   `python -m amicus.manifest --measure` and `tests/test_discovery_cost.py` `MEASURED` both say 112,553, which is the figure this document uses.
6. **The artifact guard could not hold two walks.** `tests/test_review_artifact.py` bound itself to one file via `next(glob(...))`, so writing this walk did not add a second set of assertions but silently replaced the first, leaving the 2026-09-07 artifact unguarded.
   Its mandatory-probe rule also admitted only `docs/host-captures/` citations, which no re-run walk can satisfy without citing a capture it did not use.
   Both are fixed in this change and recorded as holes 5 and 6 in that file's docstring.

## Probes

### Probe: cold-start

Simulated from the wire, which `review-workflow.md` Step 1 permits where no transcript is available and the committed ones describe an older surface.
`server/discover` returns identity, capabilities and the instructions in one read.
Measured: the `tools/list` body is 112,553 bytes across 18 tools; the instructions are 3,392 characters, of which a Claude Code client is shown the first 2,048; the Rules block ends at character 2,002, so every binding rule is inside the cap and only the Reference paragraph is cut.
That cap is pinned by `tests/test_server.py:101`, which asserts `len(scope) + len(rules) + 2 <= INSTRUCTIONS_HOST_CAP`.
An agent therefore learns scope, negative scope and all nine rules before its first call.

**Re-run:** `uv run python scripts/probe_review_surface.py cold-start`

### Probe: first-repair

Sixteen failures were forced across both carriers and read as payloads rather than as messages.
Tool-result errors carry the envelope in `structuredContent` with `isError: true`; the `content[0].text` mirror equalled `structuredContent` on every one.
Resource failures carry it in JSON-RPC `error.data` with the mandatory `[6.rename]` applied (`machine_code`, `human_message`), under `-32602`, which is correct now that `-32002` is retired.
`repair` is omitted rather than nulled where none exists, and the `value`-omission policy is disclosed on `amicus://error-envelope`.
Findings 2 and 5 are what this probe produced.

**Re-run:** `uv run python scripts/probe_review_surface.py first-repair`

### Probe: tool selection

Traced across the four verb families, their `_async` twins, the two dry runs and the five job tools.
Names, descriptions, the required intent field (`question`, `task`, `target`, or a git `scope`) and the result shapes separate them.
Finding 4 is the one wrong-but-plausible path found, and it is a backend choice rather than a tool choice.

**Re-run:** `uv run python scripts/probe_review_surface.py tool-selection`

### Probe: advertised vs. actual

Every tool's `outputSchema`, annotations, `title` and lifecycle `_meta` read off the wire: 18 of 18 publish all four.
Annotations are internally consistent — paid tools `readOnlyHint: false` with `openWorldHint: true`, free reads `readOnlyHint: true` with the mutation hints omitted as `[3.annotation-defaults]` requires.
Finding 3 is the one dishonest value found.

**Re-run:** `uv run python scripts/probe_review_surface.py advertised`

### Probe: discovery cost

Counted with the repo's own instrument rather than estimated: 112,553 bytes for profile `all`, against a zero-headroom ratchet in `tests/test_discovery_cost.py`.
Output schemas are 53,183 bytes and input schemas 44,168.
The repeated sub-schema mass is cross-tool and protocol-forced, not a local encoding defect — see instrument defect 3.

**Re-run:** `uv run python scripts/probe_review_surface.py discovery-cost` (and `uv run python -m amicus.manifest --measure`)

### Probe: cross-version

Fingerprint and `surface_digest` compared across all three manifest profiles.
Finding 1 is the result: the digest distinguishes the profiles and the fingerprint does not, while the published coverage text claims it does.

**Re-run:** `uv run python scripts/probe_review_surface.py cross-version`

### Probe: capability gating

`server/discover` advertises `completions` and `resources: {subscribe: false, listChanged: false}`, and `tasks` is absent unless `AMICUS_TASKS=1`.
`completion/complete` answers for both resource templates with `['codex', 'kimi', 'claude']`, so `[2.completion]` and `[4.template-completion]` are satisfied rather than merely advertised.

**Re-run:** `uv run python scripts/probe_review_surface.py capability-gating`

### Probe: resource freshness

Cache hints read on every list method and on `resources/read`: the four catalog methods carry `ttlMs: 300000, cacheScope: "private"`, and `resources/read` carries `ttlMs: 0`.
Withdrawn 1 is what this produced, and ADR 0018 is why it was withdrawn.
Subscriptions are advertised off, so the `listChanged` and `resources/updated` half of this probe has nothing to exercise.

**Re-run:** `uv run python scripts/probe_review_surface.py resource-freshness`

### Probe: security boundary

Egress, prompt carriers, `readonly_honesty` and `implicit_context` read from `amicus_backends(detail="full")`, which discloses per backend that a CLI can read outside the workspace, that redaction is best-effort and never covers supplied inputs, and which carrier each field rides.
No open-world tool was invoked, because every one of them spends; the disclosure surface, not the behaviour, is what this probe checked.

**Re-run:** `uv run python scripts/probe_review_surface.py security-boundary`

### Probe: long-running operation

**Skipped.**
**Inapplicability reason:** exercising the task lifecycle needs a server started with `AMICUS_TASKS=1` and a client that declares the `io.modelcontextprotocol/tasks` extension, and driving one to a terminal status creates job state and risks backend spend, which this walk's budget and the review workflow's Safety rule both forbid.
The static half was checked instead and is recorded as OK in the coverage table: task gating, the `completed`-is-not-success rule and the retention window are disclosed in `amicus_capabilities.tasks.fallback`.

## Checklist coverage

| Section | Status | Notes |
| --- | --- | --- |
| §1 | OK | **Server-Level.** `[1.name]` distinctive and unversioned; `[1.transport]` stdio, declared in the summary and in `amicus_capabilities.transport`; `[1.stdout]` verified clean under the raw stdio probe, with logs on stderr; `[1.state-handles]` job ids opaque with a declared `AMICUS_JOB_TTL` and a per-workspace cap; `[1.spec-revision]` declared dual-era. |
| §2 | OK | **Discovery.** Finding 4 touches this section. `[2.summary]` met on three carriers (`instructions`, `amicus_capabilities`, `amicus://capabilities`), which is what `[2.instructions-advisory]` requires; `[2.negative-scope]` explicit; the 2,048-character host cap is respected and pinned by `tests/test_server.py:101`. |
| §3 | covered | **Tools.** Findings 3 and 4. 18/18 publish `outputSchema`, `title` and lifecycle `_meta`; `[3.mutation-scope]` and `[3.document-reading]` are discharged by `amicus_capabilities.annotations_reading`, which states the observable-scope reading and the worst-enabled-backend rule explicitly. Finding 3 is the one value that contradicts it. |
| §4 | covered | **Resources.** Finding 6 and Withdrawn 1. 4 resources plus 2 templates; `[4.tool-fallback]` satisfied, since every resource's content is also reachable from `tools/list` alone; `[4.templates]` published for both parameterised URIs and paired with working completion; `[4.jsonrpc-errors]` carries the same envelope in `error.data` with the mandatory `[6.rename]`. |
| §5 | not-checked | **Prompts.** The server defines no prompts: `prompts/list` returns `[]` on every profile, so there is nothing for §5's rules to bind to and `[5.optional]` makes that a valid design. Nothing on this surface is load-bearing in a prompt. |
| §6 | covered | **Failure Recovery.** Findings 2 and 5. One envelope, two carriers, exercised on 16 forced failures; `[6.rename]` applied on the JSON-RPC side; `[6.offending-value]` omission disclosed on the agent-visible error-envelope schema; `[6.presence]` holds, with `repair` omitted rather than nulled and `retry_after_ms` always emitted. |
| §7 | OK | **Long-Running Operations.** Reviewed against the schemas and the capability summary, not against a live tasked session — the probe is recorded as skipped with its reason. `[7.task-support]` gates tasks on the declared extension at both ends; `[7.failed-task]`'s completed-is-not-success rule is stated in the instructions as the rule demands; `[7.task-fallback]` is the labeled `amicus_job_*` family. |
| §8 | covered | **Token Efficiency.** Finding 4 and Withdrawn 1. 112,553 bytes across 18 tools against a zero-headroom ratchet; `[8.concise-default]` and `[8.per-capability-detail]` real, with `detail=summary` the default on all eight density-varying tools; `amicus_job_list` carries filters, `limit` and `truncated`, so `[8.truncation]` is satisfied and no house convention is bolted onto a native list. |
| §9 | covered | **Versioning.** Finding 1. `[9.deterministic-order]` holds; `[9.deprecation-semantics]` states a committed two-minor-release window and `amicus_dry_run` ran its full declared 0.3.0→0.5.0 window with a release-time check in `scripts/check_release_state.py`; `[9.tier-metadata]` rides every tool and resource record. |

## Residual risks

- **No live agent transcript.** The cold-start and tool-selection probes are simulated from the captured wire, which the workflow permits but which is weaker evidence than a host transcript.
  A walk that re-runs probes against the current tree trades capture fidelity for surface currency, and this one took that trade knowingly.
- **The task lifecycle was never exercised.** §7 rests entirely on the static disclosure; a server that disclosed the contract correctly and implemented it wrongly would pass this walk.
- **Three of six findings were demoted by a single reader.** The demotions are each backed by a citation checked against the source, but the walk has no evidence that a different third reader would have demoted the same three.
- **One paid call underlies part of this walk.** The Codex read cannot be reproduced without spending again, so its contribution is recorded here rather than re-derivable.

## Open questions and assumptions

- **Assumed:** that the three manifest profiles are the configurations worth comparing.
  They are the ones the manifest pins, and `all` is the default.
- **Assumed:** that a re-run probe against the current tree is better evidence here than a committed capture.
  The surface moved 33 schema versions since the last walk, so the captures describe a different server; the cost is recorded under Residual risks.
- **Open:** whether the catalog should be reduced per profile (Finding 4's residue), which `[2.pd-reduction]` permits and no document has yet refused.
- **Open:** whether `amicus_job_cancel` is destructive under the same reading that decides Finding 3.
- **Open:** whether a walk conducted by three models with different priors is repeatable, or whether the demotion of three Majors was a property of this particular third reader.
