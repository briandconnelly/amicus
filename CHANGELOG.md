# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `/amicus:delegate-async`, a slash command that starts one `amicus_delegate_async` job,
  reports its `job_id` and hands the poll and fetch to `/amicus:jobs` (#67). Delegation is the
  verb likeliest to outrun the synchronous deadline, where a sync call made without an
  idempotency key is terminated with its partial work lost, so its background start is the one
  that gets a command of its own; the other async twins stay reachable from their verb's
  command. `/amicus:delegate` now points at it for long tasks, and `/amicus:jobs` now says to fetch
  once the status is anything but `running` rather than waiting on `result_available`, which
  is true only for `done`: a job that failed, was cancelled or timed out never sets it, so
  waiting on it polls that job forever.

### Changed

- **Breaking (`FINGERPRINT` `schema-29`).** A replayed keyed `_async` handle for a job that has
  already finished now reports `poll_after_ms: null`, as `amicus_job_status` does for the same
  job on every terminal status (#101). It used to report `1000`, the store's flat base, so a
  host that read a non-null hint as "still running" waited a second and polled once more before
  it saw the terminal status. `JobStarted.poll_after_ms` is now required but nullable on the
  four `_async` tools' output schemas. It also carries a published description saying when it
  is null, the same one `amicus_job_status` and `amicus_job_cancel` now carry. The four `_async`
  descriptions, the `amicus_job_status` description, the synchronous `timeout` repair and the
  skill now say to poll only while `status` is `running`, and the skill says to read a handle's
  `status` before waiting on its hint. A terminal handle's `follow_up` still names
  `amicus_job_status`, because pontonier has no repair step yet for fetching a finished job's
  result (briandconnelly/pontonier#30, #103).
  `tools/list` grows by 953 bytes on the `all` profile. `RESULT_FORMAT` stays 6: a handle is
  never stored as a job result.

- **Breaking (`FINGERPRINT` `schema-28`).** A running job's `poll_after_ms` now keeps growing
  past ten seconds, up to 30 s (#95). The hint still means roughly "wait about as long as the
  job has already run", but pontonier 0.9.0 stops it at 10 s, so a job that ran for minutes was
  polled every ten seconds for almost its whole life: about 28 `amicus_job_status` calls for a
  four-minute review, the 15–25 the #84 reporter counted. amicus now computes the hint itself,
  with pontonier's own formula and a 30 s ceiling, which makes that about 13 calls and notices a
  finished job at most 30 s late; a 60 s ceiling would save three more calls and double that
  delay. Every place that hands out the hint agrees on it: `amicus_job_status`, the
  `job_running` repair's `retry_after_ms`, a keyed sync wait's `timeout` repair, and a replayed
  keyed `_async` handle for a job that is still running. The `amicus_job_status` description
  now states the ceiling. MCP tasks keep FastMCP's own flat `pollIntervalMs` (#100).
  `RESULT_FORMAT` stays 6: no stored result carries the hint.

- **Breaking (`FINGERPRINT` `schema-27`).** The review preview is now
  `amicus_review_changes_dry_run`, named for the call it previews as `amicus_delegate_dry_run`
  is (#98, ADR 0028). `amicus_dry_run` read as a preview for any paid call, while it covers only
  `amicus_review_changes`, and consult and adversarial review have no preview at all. The new
  tool takes the same arguments and returns the same result, with `tool` naming it; the old
  name stays as a deprecated alias (see Deprecated). This is amicus's first deprecation, so
  the marker the `deprecation_policy` promised now exists: a deprecated tool's lifecycle
  `_meta` carries `deprecation` beside its unchanged `stability`, with exactly `since`,
  `removal_at_or_after`, `replaced_by` and `migration`, and every `amicus_capabilities`
  `tool_details` row gains a `deprecation` field carrying the same object, null for a tool
  that is not deprecated. tools/list grows by 9,042 bytes on the `all` profile while the alias
  ships. `RESULT_FORMAT` stays 6: no dry run is ever stored as a job result.

- **Breaking (`FINGERPRINT` `schema-26`).** The server `instructions` lead with their rules
  and ship as three blocks - what amicus does and does not do, a list of rules, then
  reference - instead of one unbroken 4,033-character line that opened with protocol
  background (#49). The order is not style. Claude Code shows the model only the first 2,048
  characters of a server's instructions (measured on amicus 0.2.0 and codex-in-claude 0.22.0,
  both cut at exactly that offset), so on 0.2.0 everything after "read error.backend, and"
  never reached it there: following `error.repair`, treating findings as claims, reading a
  `completed` task as a delivery statement rather than a success, and the job-handle TTL.
  Every rule now ends before character 2,048, and a test holds it there (ADR 0027). The
  tool-failure and resource-read-failure rules are separate items, each naming its own
  path: a resource-read failure's code is `error.data.machine_code`, not the era-bound
  numeric JSON-RPC `error.code`. The
  protocol-era mechanics moved to reference, beside the now-stated `stdio` transport, and the
  host-capture provenance is gone; `amicus_capabilities` already carries `protocol_revision`
  and `tasks`. The job rule names both retention bounds, `AMICUS_JOB_TTL` and the
  per-workspace cap that can evict a result sooner. The text is now 3,377 characters.
  Treating findings as claims to verify, not commands, also rides the `findings` description
  on `amicus_consult`, `amicus_review_changes`, `amicus_adversarial_review` and
  `amicus_delegate` now (#97), so it no longer depends on a host showing the instructions.
  `initialize`, `server/discover` and those four `outputSchema`s change; `RESULT_FORMAT` does
  not.

- **Breaking (`FINGERPRINT` `schema-25`).** A `review_status: not_run` review reports
  `confidence: unknown`, not `low` (#54, ADR 0026). No backend ran on an empty scope, so there
  was no rating to carry, and `low` is the lowest rating a backend can report: stating it
  manufactured a claim in the direction issue #53 had already removed. The published
  `confidence` description now names `not_run` as one of the two causes of `unknown`,
  beside an unreadable backend rating, one meaning with two causes rather than two meanings, and the substituted `low` has two sources instead of
  three: partial coverage and findings amicus could not carry, each still beside an `unknown`
  verdict, so a `low` beside any other verdict is still the backend's word. A caller that
  read only `low` as "do not rely on this" has to handle `unknown` on every review and branch
  on `review_status` for whether one ran; it already had to, since an unreadable rating on a
  completed review has been `unknown` since 0.2.0. The enum is unchanged, so `RESULT_FORMAT`
  stays 6.

- **Breaking (`FINGERPRINT` `schema-24`).** Every success envelope's `meta` is sparse on the
  wire, on every tool (#47, ADR 0025). A delivered paid result already dropped meta's
  null-valued keys, and the `amicus://result-meta` description said so, but a job-lifecycle
  handle, a job status, a job list or a dry run dumped the full model: the audit's plain
  `amicus_job_list` call carried 27 meta keys, 15 of them null, 626 bytes that were about a
  third of the result and paid twice because `content[0].text` mirrors `structuredContent`.
  The guard every tool passes through now slims every success, keyed on null and never on
  falsiness; the delivery chokepoint keeps slimming a stored result too, so a job result is
  slimmed twice and the second pass is a no-op. The always-present core is published as the
  schema's own `required`:
  `elapsed_ms`, `truncated`, `compat_warnings`, `security_warnings`, `redacted_paths`,
  `request_id` and `fingerprint`, derived from the model so a new defaulted field cannot be
  added without being declared. An empty list there means that envelope reports none, not
  that a check ran: a job handle, status or list and a dry run report on the call that
  produced them, and the run's warnings arrive on its own result. Only meta's
  top level is touched: a null inside `usage`, or outside `meta` such as
  `JobListResult.truncation_hint`, is that object's own contract. The persisted dump is
  unchanged, so `RESULT_FORMAT` stays 6. On the wire-shape snapshot's `amicus_job_list`
  envelope, whose meta populates `workspace_source` and `roots_source` and so carried 14
  nulls, `meta` falls from 591 to 304 bytes (27 keys to 13) on each carrier.

- **Breaking (`FINGERPRINT` `schema-23`, `RESULT_FORMAT` 6).** The `questions`, `assumptions`
  and `next_steps` lists of consult, review and adversarial results no longer lose entries in
  silence (#52). `_str_list` kept string and numeric entries, dropped every other entry with
  no count and no reason, and turned a non-list member into `[]`, so a backend that structured
  a next step as an object lost it and the caller could not tell "the backend said nothing"
  from "amicus could not carry what it said". Those results now carry `lists_diagnostics`, the
  prose-list twin of `findings_diagnostics` (#38): null when all three lists were carried
  intact, otherwise one `{dropped, reasons}` member per list that was not, with a fixed reason
  vocabulary (`number_stringified`, `invalid_entry`, `invalid_container`, `missing_member`) and
  never the omitted content. A number is still delivered as its string and now says so; a
  bool, null, object or array entry is dropped and counted; a present non-list member and an
  absent one are told apart, because the output schema requires all three. A consult answered
  in prose rather than the requested object reports `missing_member` on all three lists and,
  on the same path, `findings_diagnostics` now reports `missing_findings` where #38 left it
  null: nothing was parsed, the answer is `summary`, and the empty lists are not the backend
  saying none. A `review_status: not_run` result keeps both diagnostics null, because no
  backend ran and `review_status` is the signal; both published descriptions say so. Nothing
  folds into the verdict or confidence (ADR 0024). Delegate results do not carry the field: their
  `next_steps` is amicus's own text. `RESULT_FORMAT` moves to 6 so a format-5 record's
  defaulted null cannot assert that every list was carried intact by a run that never measured
  it. `tools/list` grows 5181 bytes on the `all` profile, the field's description once per
  tool plus the object inlined per tool; the first draft carried the reason prose on each of
  the nine inlined members and was 2400 bytes larger.
- **Breaking (`FINGERPRINT` `schema-22`).** The free discovery tools have a concise default
  (#46). `amicus_capabilities(detail="summary")`, the default, now carries `name`, `cost`,
  `stability` and `backends` per `tool_details` row; `use_when`, `required_params`,
  `key_optional_params`, `returns` and `error_codes` are on `detail="full"`, and a summary row
  carries no `error_codes` key at all rather than an empty list that would read as "raises
  nothing". `detail` now changes field density only, never the row count: the `contracts`
  value, which returned zero rows, is removed, and a new `include_tool_details=false` selects
  the rowless payload for a fingerprint or `surface_digest` re-check. `amicus_backends` gains
  `detail` (`summary` default, `full`); `summary` leaves each backend's `egress`, `carriers`,
  `readonly_honesty` and `implicit_context` keys out of every entry and names them in a new
  top-level `omitted_fields` (empty on `full`), so an absent key means "not requested" and a
  `null` on `full` still means no loaded plugin declares one. The `amicus://backends/{backend}`
  resource is always the `full` entry. Measured on the `all` profile, both carriers: the
  default `amicus_capabilities` falls from 27,842 to 14,864 bytes and the default
  `amicus_backends` from 17,250 to 4,000. `detail="full"` grows by 64 bytes on
  `amicus_capabilities` (the two new parameters appear in two tools' `key_optional_params`) and
  by 40 on `amicus_backends` (the empty `omitted_fields`).
  The server instructions and the skill now say to read `amicus_backends(detail="full")` once
  before the first paid call. `RESULT_FORMAT` stays 5.
- **Breaking (`FINGERPRINT` `schema-18`).** `amicus_consult`, `amicus_review_changes`,
  `amicus_adversarial_review` and `amicus_delegate` accept `idempotency_key`, as both siblings'
  sync tools do (#66); it was async-only, and `docs/MIGRATION.md` never said so. A keyed sync
  call awaits the run the key names (its own, or another caller's for the same key and
  arguments) and delivers its result marked `meta.idempotency_replayed: true`, so a retried
  sync call cannot pay twice. A keyed sync run gets the job deadline (`AMICUS_JOB_MAX_SECONDS`),
  as an `_async` run does, and `timeout_seconds` bounds only how long the call waits for it. A
  keyed waiter does not own the job: its local timeout returns a temporary `timeout` with a
  `poll_job_status` repair naming `amicus_job_status` for that job instead of cancelling it, its
  cancellation leaves the run going, and under the tasks extension a keyed task's job survives
  `tasks/cancel` (an unkeyed task's is still cancelled with it). Sync and `_async` stay separate
  identities. An empty key is now rejected pre-spend on every paid tool
  (`minLength: 1`, the siblings' bound), which tightens the `_async` contract by that one
  value. The sync tools' error catalogs name the three dedup codes, and the server
  instructions, `timeout_seconds` and task-support text qualify their categorical "terminated"
  and "cancelling a task cancels its job" with the keyed exception. ADR 0020 supersedes ADR
  0008's unkeyed-sync clause. `RESULT_FORMAT` stays 5.
- `FINGERPRINT` moves `amicus/0.1/schema-18` → `amicus/0.1/schema-19` for the `reasoning_effort`
  parameter contract, which now names claude beside kimi as a backend whose CLI does not reject
  a bad effort, and says claude checks a fixed list where kimi reads the model catalog (#76).
  Every pin was regenerated in a dedicated commit (rule 10). `RESULT_FORMAT` stays 5: no stored
  result changed shape.

- **Breaking (`FINGERPRINT` `schema-20`).** An error's `repair.arguments` carries a complete call
  wherever one is uniquely known, and the two workspace codes carry no repair (#42, ADR 0021). An
  `invalid_arguments` rejection whose every rejected argument is an unknown key repairs with the call
  as sent minus those keys, but only when every remaining value is null, a bool, a number, a
  published enum member, or an object built from those: a prompt input, path, model slug or
  `idempotency_key` is never echoed and suppresses the arguments instead. `amicus_models` and
  `amicus_backends` repairs name the failing call's `backend` when the tool accepts it
  (`amicus_models` requires it, so its repair was not callable before), and `job_not_found`
  repairs to `amicus_job_list({})` when the workspace came from roots. `invalid_workspace_root` and
  `workspace_outside_roots` no longer carry a repair: no call can supply the caller's directory,
  and `details.field` and `candidate_roots` already name what to fix. A repair that names no tool
  (`correct_config`, `reduce_input` and the like) is still a symbolic next step. The policy is
  published on the error-envelope schema. `RESULT_FORMAT` stays 5, because `repair.arguments` was
  already in the stored schema.

- **Breaking (`FINGERPRINT` `schema-21`).** `amicus_job_consume_result` reports what deleting the
  record did, in `meta.consume` (#44, ADR 0022). It always delivered the stored envelope, but
  reported plain success even when the deletion failed, while its description promised that a
  repeat call returns `job_not_found`. `meta.consume.discard_outcome` is `removed`, `missing`,
  `not_done` or `delete_failed`; only the first two keep that promise, and the other two carry a
  `follow_up` that calls `amicus_job_status` on the job. A real failed delete can leave a record
  that reads as `failed`, so the follow-up promises neither redelivery nor deletion at expiry. The
  field is delivery-only: it is never stored, and `amicus_job_result` never sets it.
  `RESULT_FORMAT` stays 5.

### Deprecated

- `amicus_dry_run`, in favour of `amicus_review_changes_dry_run` (#98, ADR 0028). It stays
  listed, last among the free tools, with its input schema, annotations and outputSchema
  unchanged by the rename, so existing calls keep working; its title,
  description and lifecycle `_meta` now say it is deprecated, and its description still
  carries the full preview contract. It is deprecated from 0.3.0 and removed in 0.5.0:
  `scripts/check_release_state.py` refuses to release outside that window, and a unit test
  fails once the tree declares 0.5.0 with the alias still in place.

### Fixed

- Resource records carry their size in the native `Resource.size` field, and only when it is
  known (#48). Every record published `size_bytes` under the private
  `dev.bconnelly.amicus/triage` `_meta` convention, which an off-the-shelf client may never
  surface, while the native field stayed empty, and the volatile `amicus://capabilities`
  advertised `size_bytes: 0` for a body of roughly 13.5 KB. The three static resources now
  carry `size`, the byte length of exactly the text a read returns, and no triage block; the
  volatile resource and both templates carry no size at all, and their triage block is the one
  `volatile: true` key, which has no native home. Part of the `schema-24` bump above.
- A structured answer whose JSON object repeats a key is now refused as `invalid_json` (#51).
  `classify_structured` parsed with plain `json.loads`, which keeps the last member silently,
  so a populated `findings` followed by `findings: []` reached `coerce_findings` as empty and
  `findings_diagnostics` reported no loss: the content was gone before anything could measure
  it. The parse now fails on a repeated key at any depth, which the strict review and
  adversarial paths already return as a hard error, and consult falls to its existing prose
  passthrough (sanitized summary, redacted `raw_response`). The codex backend's `parse_structured` delegates to the shared
  classifier as claude's and kimi's already did, so `ExecResult.structured` cannot carry a
  collapsed object on any backend. `FINGERPRINT` and `RESULT_FORMAT` do not move: no error
  code, value enum, envelope shape, tool description or stored result shape changes.
- The `collaborating-with-amicus` skill told an agent to confirm a backend's `features` list
  contains the verb it was about to call, and its backend reference called `features` "the
  verbs it supports" (#84). `features` names only the gated verbs (`delegate`,
  `adversarial_review`) plus non-verb capabilities, so a host following the rule concluded
  `consult` and `review_changes` were unsupported everywhere. The rule now names the two gated
  verbs and says the other two never appear there; the reference documents every member. The
  skill also says that `poll_after_ms` grows only to a ceiling (30 s, see #95 above), that a
  reported review of a few hundred lines runs two to four minutes against the 300 s sync
  default, and that a sync call with an `idempotency_key` waits inside one call.
  `tests/test_skill_contract.py` asserts the gated verbs, the declared features, the poll
  ceiling and the timeout bounds against source and checks that the keyed alternative is named
  (its behaviour is tested in `tests/test_lifecycle.py`); scenario S15 covers the misreading
  for both baseline verbs.
- FastMCP logged every rejected `tools/call` to the server's stderr with pydantic's error
  list, and each error's `input` is the rejected value itself, against AGENTS.md rule 18 (#79).
  For a missing required argument that `input` is the whole argument dict, so a valid prompt
  field sent beside the omission was written verbatim, and a key the client chose reached the
  log through `loc`. amicus now rewrites the record on `fastmcp.server.server` before any
  handler sees it, keeping the tool name and each error's type and top-level declared field
  (`Invalid arguments for tool amicus_consult: 1 error(s): missing_argument at question`). It
  recognises the record by its shape as well as its text, and any other record from that logger
  it has not audited keeps its level and loses its message. `obs.configure` also takes over the
  `fastmcp` and `mcp` loggers for stderr, so an exception either library logs renders as its
  type and frames rather than its own text: FastMCP's rich handlers and `mcp`'s fall-through to
  `logging.lastResort` are gone. Both stay at WARNING or above whatever `AMICUS_LOG_LEVEL` says,
  because the `mcp` stdio runner logs a whole inbound frame at DEBUG, and neither is written to
  `AMICUS_LOG_FILE`. FastMCP's INFO log lines no longer reach stderr; its startup banner, which it
  prints rather than logs, still does, once, before any request arrives. This does not make every
  dependency record safe: a message either library preformats with an f-string is still written
  as it stands.

- The claude contract declared `effort_silently_ignored_upstream=False`, but claude 2.1.270 warns
  on an unknown `--effort`, ignores it and runs at its default effort (#76). Callers were never
  exposed: the adapter already refuses any effort outside its fixed list before spending. The flag
  is now `True`, so pontonier's conformance check probes that refusal when the plugin loads, and a
  claude adapter that dropped it would be registered unavailable rather than spend at the wrong
  effort. The refusal's repair text no longer says claude rejects the value itself.

- A claude budget stop returned `nonzero_exit` instead of `budget_exceeded`, so a caller got
  a generic error rather than the repair that names `backend_options.max_budget_usd` (#73).
  Claude reports the stop as `subtype: "error_max_budget_usd"` with no `result` text, and the
  word-bounded budget pattern could not match inside the subtype.

- A job named by several tasks reported one task on `amicus_job_status` and `amicus_job_result`
  and another on `amicus_job_list`; every surface now reports the first task that named it, and
  a list filtered by any associated task still finds the job (#66).

- **Breaking (`FINGERPRINT` `schema-17`).** `tools/list` is 10,474 bytes smaller (105,485 to
  95,011 on the `all` profile as the stdio transport writes it for a handshake-era client, the
  era both captured hosts negotiate; 26,046 to 23,800 o200k_base tokens), with no tool,
  parameter, accepted input value, runtime behaviour or error changed (#41); the one output
  contract that narrows is named below. Each tool's schema is self-contained on the wire, so
  the six shared parameter contracts (`workspace_root`, `reasoning_effort`, `backend_options`,
  `instructions_append`, `extra_context`, `idempotency_key`) were repeated up to fifteen times
  per catalog; their inline descriptions are now a one-line summary plus the `amicus://params`
  pointer, and the elaboration lives in that resource's `full` text, which was already the
  authoritative contract. The `default: null` pydantic stamps on every optional parameter is
  stripped at list time (a FastMCP transform, so `surface_digest` and the wire agree);
  non-null defaults such as `detail: "summary"` stay. The error-envelope and result-meta
  pointer descriptions on every `outputSchema` are one clause each, and the four `_async`
  tools' `follow_up` is published as the one action it ever carries (`poll_job_status` via
  `amicus_job_status`) instead of the whole repair-step enum. The discovery-cost ratchet now
  measures the result body of a real `amicus.server` subprocess, taken off the response line
  byte for byte, and `python -m amicus.manifest --measure --tokens` (`uv sync --group
  measure`) reports reference-encoding token counts of that text in place of the byte/4
  proxy. `RESULT_FORMAT` stays 5:
  no stored result shape moved.
- **Breaking (`FINGERPRINT` `schema-16`, `RESULT_FORMAT` 5).** Review and adversarial-review
  results, and `amicus_dry_run`, now carry a top-level `coverage` object (#65): `status`,
  untracked-file counts, `omission_reasons` and a `redaction` breakdown, in the siblings' shape
  plus amicus's own `focused` reason. An omitted untracked file, a tree that changed during the
  gather, or a focused pass used to reach a caller only as prose in `summary`, and the free
  preview reported none of it. `amicus_dry_run` also accepts `focus` and reports
  `max_input_bytes`, so it previews the coverage the paid call will report. A stored job result
  written under `RESULT_FORMAT` 4 is now returned as `job_result_incompatible`. ADR 0019
  supersedes ADR 0007's coverage clause.

### Fixed

- Keep exception text out of stored background-job crash results and returned spawn-failure
  envelopes, since backend exceptions can contain prompt inputs (#56).
- Default Claude adversarial reviews to `safe` config isolation (preserving a configured
  `bare` API-key mode) and reinforce their JSON-only and available-tool contract (#64).
  Explicit per-call modes remain supported; consult and review-changes defaults are unchanged.
  Discovery exposes `default_by_verb` when defaults vary by verb, with no single common default.

## [0.2.0] - 2026-09-10

Across this release the discovery surface moves `amicus/0.1/schema-7` -- what 0.1.0 shipped -- to
`amicus/0.1/schema-13`, and stored job results move `RESULT_FORMAT` 2 to 4. The entries below are
per-change rather than net, so they also name intermediate states that no release ever shipped:
`schema-8` through `schema-12`, and `RESULT_FORMAT` 3.

### Changed

- **Breaking (`FINGERPRINT` `schema-13`).** The discovery catalog now advertises a real
  SEP-2549 freshness window instead of the SDK's `ttlMs: 0`. `server/discover`,
  `tools/list`, `resources/list`, `resources/templates/list` and `prompts/list` carry
  `ttlMs: 300000`, `cacheScope: private`; those records are fixed for the life of the
  process, so a modern client that opts into caching no longer re-walks 99,053 bytes of
  `tools/list` to learn nothing changed. `resources/read` deliberately carries no hint and
  stays at `ttlMs: 0`: the SDK chooses a hint per method while the client keys its cache
  per URI, and `amicus://backends/{backend}` and `amicus://models/{backend}` report live
  install, auth and model-catalog state. `tools.listChanged` and `resources.listChanged`
  now report `false` on the handshake era too, matching the modern era and matching
  amicus, which has no `notifications/*/list_changed` emission site -- the handshake `true`
  came from FastMCP's hardcoded `NotificationOptions` and promised a notification that
  could not arrive. The committed manifest also pinned
  `initialize.capabilities.resources.listChanged: true`, a value the shipped stdio
  transport never sent, because it is built over the in-memory transport; both eras'
  capabilities are now asserted against a real `amicus-mcp` subprocess. `RESULT_FORMAT`
  stays `4`. `surface_digest` moves only because `instructions` gained a clause naming it
  as the catalog re-read check: revert that clause and the digest returns to its previous
  value, because the digest covers the catalog records as the server holds them (before
  response middleware) plus `instructions`, and not the capability blocks or the cache
  envelope. The cache hints are inert for both captured hosts, which negotiate the
  handshake era; the `listChanged` flip is not, and is visible to exactly those clients. Supersedes ADR 0006's cache-hint clause; see
  ADR 0018. (#45)
- **Breaking (`FINGERPRINT` `schema-12`).** The published stability tier is now inside the
  closed set an agent can filter on. Nine of the 18 tools -- the ones absent from the per-tool
  override table -- carried `alpha` in their lifecycle `_meta`, as did all four static resources
  and both resource templates, and `amicus_capabilities.stability` reported it too:
  a value outside both `[9.stability-tiers]`'s `stable | preview | experimental` and amicus's
  own `ToolStability` literal, so a caller filtering on the tier could not interpret it. The
  server-wide tier is now `experimental`, the honest one for a 0.1.x surface and already the
  tier the four `_async` and five `amicus_job_*` tools declared; their per-tool overrides are
  gone, and `amicus_capabilities.tool_details[].stability` is `null` for all 18 tools, which
  means what it always meant -- inherit the top-level tier. `stability` is also published as
  the three-value enum rather than a bare string, so an illegal tier now fails assembly
  instead of reaching a caller. `RESULT_FORMAT` stays `4`: no stored result carries a tier.
  tools/list grows 106 bytes and the discovery-cost ratchet is raised deliberately
  (`tests/test_discovery_cost.py` says what the bytes buy).
- `FINGERPRINT` moves `amicus/0.1/schema-10` → `amicus/0.1/schema-11` for the scoped
  `workspace_root` prerequisite, which changes `initialize_response` and `capabilities_payload`,
  with every pin regenerated in a dedicated commit (rule 10). `RESULT_FORMAT` stays `4`: no stored
  result changed shape, and no `inputSchema` changed, so the discovery-cost ratchet does not move.
- **Breaking (`FINGERPRINT` `schema-10`, `RESULT_FORMAT` 4).** `confidence` on a review or
  adversarial-review result gained a fourth value, `unknown`, and both tools now publish what the
  field means. `unknown` is the ABSENCE of a rating -- the backend supplied none amicus could
  read, and the verdict was not withheld either -- never a low one. amicus substitutes `low`
  only where it also withholds the verdict as `unknown` -- partial coverage, findings it could
  not carry, or a `not_run` review -- so a `low` beside any other verdict is the backend's own
  word, and a high confidence is never evidence that coverage was complete. Backends are still asked for `low|medium|high`; the new value is amicus's, not
  theirs. A `RESULT_FORMAT` 3 reader's closed enum rejects a stored result
  carrying it.
- **Breaking (`FINGERPRINT` `schema-9`, `RESULT_FORMAT` 3).** Every consult, review,
  adversarial-review and delegate result gained `findings_diagnostics`: `null` when nothing was
  lost, otherwise a `dropped` count and reasons from a fixed vocabulary
  (`severity_normalized`, `extra_fields_omitted`, `invalid_entry`, `invalid_container`,
  `missing_findings`). Read the
  reasons rather than the count: `dropped` counts whole entries, so a `0` beside
  `extra_fields_omitted` still means content was lost, and a `null` means the count was
  unknowable, never that nothing was lost.
- A job result stored under a different `result_format` is now rejected before validation rather
  than after it. It used to pass, because a field added since it was written validates from its
  own default -- and that default would have asserted, on the producing run's behalf, that no
  finding was lost on a run that never measured loss.
- `FINGERPRINT` moves `amicus/0.1/schema-7` → `amicus/0.1/schema-8` for the `amicus_job_result`
  description change, with every pin regenerated in a dedicated commit (rule 10).
  `RESULT_FORMAT` did not move for it: no stored result changed shape.
- `SKILL.md`'s rule block is now the complete contract: ten obligations that lived in explanatory
  prose moved into labelled rules, and the facts that motivate them moved to an adjacent
  `Semantics` section ([ADR 0016](docs/adr/0016-skill-rules-are-a-complete-contract.md)).
- The returned-diff response contract separates the assessment of a proposal
  (`Verdict: accept | reject | cannot-assess`) from the action taken on the working tree
  (`Action: applied | not applied`). S6's recorded pass was graded against the superseded contract
  and is not carried forward as a pass against the new one.
- Both plugin manifests carry `author.url`, and their `longDescription` names
  `docs/MIGRATION.md` by absolute URL rather than by a repository-root-relative path that
  does not resolve for a consumer who vendors the manifest without the repository around it.
- `.mcp.json`'s pin now names an already-published release rather than the version being
  released, so `main` never sends a fresh install to a tag that does not exist yet
  ([ADR 0015](docs/adr/0015-mcp-json-pins-an-already-published-release.md), issue #26).
  The pin is no longer a release version literal; a small `chore(release):` PR moves it after the
  tag is pushed.
- `scripts/check_release_state.py` replaces its `pin == version being released` equality — which was
  true by construction on any tree a release PR had touched — with a shape check, a check that the
  pin never leads the release, and a check that the pinned tag actually exists.
- `docs/RELEASING.md` gains a pre-tag install rehearsal that runs the committed manifest's own
  command against the release commit's SHA, so git transport, a clean-machine build and the wire
  handshake are all exercised before anything irreversible happens.
- The README's status section describes 0.2.0 rather than 0.1.0, and names the surface and
  stored-result moves a client upgrading across this release has to account for.

### Fixed

- The published prerequisite no longer sends a sessionless client's first call into an
  `invalid_arguments` error (issue #40). Both the server `instructions` and
  `amicus_capabilities.prerequisites` told a sessionless (2026-07-28) client to pass
  `workspace_root` on EVERY call, and the same `instructions` name `amicus_backends` as the call
  to make before the first paid one. `amicus_backends`, `amicus_models` and `amicus_capabilities`
  declare no `workspace_root`, and every `inputSchema` is `additionalProperties: false`, so an
  agent that followed the prerequisite failed at exactly the call the instructions told it to make
  first. The prerequisite was correct for the other fifteen tools, so it is scoped to the calls
  that declare the parameter, and both surfaces now render one shared sentence built from
  `WORKSPACELESS_TOOLS` rather than each stating the rule in its own words; the
  `invalid_workspace_root` repair carried the same "every call" wording and is scoped with it. A
  manifest test binds that tuple to the live schemas, probes that each named tool really does
  reject `workspace_root`, and requires every surface stating the prerequisite to carry the shared
  sentence and no other workspace_root claim. What is machine-checked is the tool set and the
  single source, not the prose: one sentence is what a reviewer has to read, and it can no longer
  disagree with the schemas or with itself.

- Exception text no longer reaches the diagnostic log, on any path (issue #39). AGENTS.md rule 18
  forbids writing a prompt input to a log, and an exception raised inside a backend adapter can
  embed the text that provoked it. Two carriers did exactly that: the unexpected-exception guard
  logged with `.exception()`, whose rendered traceback carries the original exception's `str()`,
  and its own message interpolated `exc_summary(exc)` -- which masks secrets and control
  characters, not prompt inputs, so it was never the safe form the guard's comment claimed. A
  third call site, the task-map write warning in `amicus.jobs.lifecycle`, interpolated
  `exc_summary` the same way; its `OSError` carries a path rather than a prompt, so it was a
  latent instance of the pattern rather than a demonstrated leak, and it is gone too. Every
  handler `amicus.obs` installs now renders under one policy: exception types and source
  locations, never message text, notes, or source lines. The policy lives at the handler rather
  than the call site because `pontonier`'s own runtime logs exceptions through these handlers too.
  It is not a claim that no prompt input can ever be logged -- a call site that interpolates a
  prompt field itself still would -- only that the exception-text family is closed.

- An unreadable `confidence` no longer defaults UPWARD to `medium` (issue #53). A backend that
  returned nothing amicus could read about its own certainty was delivered as moderately
  confident, with nothing in the envelope to say the value had been invented -- the same
  direction of dishonesty as issue #38, on a different field. It now falls to `unknown`. `low`
  was not the fix: it is the lowest rating a backend can REPORT, so defaulting to it would
  manufacture a claim too. The verdict beside it is untouched, so a backend that reported `fail`
  and said nothing readable about its certainty is delivered as `fail`/`unknown`.
- Review findings are no longer discarded in silence while the verdict survives (issue #38). A
  finding that failed validation was dropped with no count and no warning, so a backend could
  report a real problem and the caller receive an apparently clean review. Only `codex` is held
  to the output schema natively; `claude` and `kimi` are merely asked for it in the prompt, so an
  added `category` key or a shouted `"HIGH"` was an ordinary return that cost the whole finding.
  Findings now survive case-normalization and unknown keys, anything still unrepresentable is
  counted and named, and a `pass` no longer stands over a loss -- it is delivered as
  `unknown`/`low`, while a `fail` or `concerns` keeps its verdict and its confidence.

- `collaborating-with-amicus` no longer tells an agent that delegate runs have no network egress.
  That holds for `codex`, whose sandbox amicus pins to `network_access=false`; it is false for
  `kimi`, which has no sandbox at all. The skill now states containment per backend
  ([ADR 0016](docs/adr/0016-skill-rules-are-a-complete-contract.md)).
- The skill's async recipe no longer polls terminal jobs forever. `poll_after_ms` is `null` on
  every terminal status and a cancelled job reports `result_available: false`, so the loop is now
  driven by `status == "running"`.
- The server's own waiting instructions now terminate too. The `job_running` repair, the
  `follow_up` every `*_async` start returns, and `amicus_job_result`'s description all told an
  agent to wait for `result_available`, a flag that never flips for a `cancelled`, `failed` or
  `timeout` job. All three now gate the wait on `status` and name the terminal path, so the
  machine-readable repair agrees with the lifecycle and with the skill (issue #35).
- `amicus_job_result`'s description no longer tells callers to branch on `tool` unconditionally.
  A stored error is delivered as an `ErrorResult`, which carries no `tool`, so `ok` is what to
  check first.
- The skill no longer claims a timed-out synchronous call costs the same quota as a completed one.
  Amicus is not told what a terminated call cost; the reason to prefer `_async` is that a sync
  timeout destroys the result.
- Result guidance no longer stops at `ok`, `verdict` and `diff`. `review_status: not_run`,
  `meta.truncated`, `meta.redacted_paths`, `meta.security_warnings` and `meta.compat_warnings`
  all change what a result means, and `diffstat` is computed before redaction and truncation, so
  it is not an integrity check on the returned `diff`.
- Rule 5 no longer requires naming the backend whose annotation caused an approval prompt — an
  attribution a host does not supply. It now separates the observed prompt from the annotation
  policy. `effects` is documented as the static per-backend declaration it is, not "call-specific
  truth".
- The README's verb matrix no longer reads as a claim about what the models can do. A `no` there is
  amicus's routing decision: `delegate` is absent on Claude by a review-only policy, and
  `adversarial_review` is scoped to Claude for v1. The verb itself is amicus's own — the prompt it
  builds and the result shape it returns are amicus's for any backend, with Claude contributing a
  critic stance on top — so Codex and Kimi can review adversarially. The README now says so, points
  at `consult` and `review_changes` for it, and names what the verb adds over them (issue #23).

### Added

- `collaborating-with-amicus` gains `reading-results.md`, `active-workflows.md`,
  `options-and-errors.md`, `independent-attempt.md`, `review-revise.md` and
  `server-down-fallback.md`. Backend selection now covers what each backend can actually inspect —
  `claude` defaults to `access="toolless"` and cannot read the repository unless asked — and git
  scope, brief preparation, and `idempotency_key` recovery are documented.
- Six prospective scenarios (S9–S14) covering git scope, terminal-job lifecycle, coverage
  reporting, backend evidence, delegate containment, and independent-attempt ordering. Schema
  validity now binds every described call in every scenario.

## [0.1.0] - 2026-09-08

### Added

- One MCP server for three second-opinion backends — `codex`, `kimi` and `claude` — with the backend as a tool parameter rather than a separate server (M0–M4).
- Synchronous verbs: `amicus_consult`, `amicus_review_changes`, `amicus_delegate`, `amicus_adversarial_review`, plus free dry-run previews for review (`amicus_dry_run`) and delegate (`amicus_delegate_dry_run`).
- Discovery surface: `amicus_backends`, `amicus_capabilities`, `amicus_models`, and the MCP resources that back them.
- A jobs surface: `_async` twins of the paid verbs, `amicus_job_status`, `amicus_job_result`, `amicus_job_consume_result`, `amicus_job_list`, `amicus_job_cancel`, with idempotency keys, restart survival and task-id lookup (M2).
- `task=True` on the four paid synchronous tools behind the `AMICUS_TASKS` flag (M5).
- Packaging for both hosts: a `.claude-plugin/` manifest, a `.codex-plugin/` manifest, an `amicus-mcp` console script, and the `collaborating-with-amicus` skill (M6).
- Release automation: a tag- and dispatch-triggered publish workflow with trusted publishing to TestPyPI and PyPI.
- A release predicate gating that upload: a `verify` job runs `scripts/check_release_state.py` against the tagged commit, and `pypi` depends on it (issue #25, ADR 0014). It proves the tagged tree's release-state coherence — every version literal, the dated changelog section, `uv.lock` — and checks that the live-gate record carried in the annotated tag's message is well formed and names that commit. That record remains the maintainer's assertion, never proof the live gates ran.

### Fixed

- `record_live_gate_evidence.validate` accepted a record that omitted `batch_id` from every backend entry, so the "one shared run produced this record" property it documented was not actually checkable. `batch_id` is now a required backend field.

### Known limitations

- The tagged publish path to pypi.org has never run. Only the TestPyPI dispatch path has been exercised.
- Eval scenario S6 in `skills/collaborating-with-amicus/tests/scenarios.md` passed on one run (status: `pass`, validated by that run alone); an M7 follow-up run against the current skill text did not isolate the still-open F3 finding, so F3 remains open. S7 (real-host approval friction) has failed both of its recorded runs (status: `fail`); an M7 zero-spend recheck reached neither a pass nor a fail and is recorded as inconclusive, so it does not move S7's status. See their `status` fields and ADR 0012.

[Unreleased]: https://github.com/briandconnelly/amicus/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/briandconnelly/amicus/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/briandconnelly/amicus/releases/tag/v0.1.0
