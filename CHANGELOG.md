# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

An entry for a change that moved `FINGERPRINT` carries one of two labels. **Breaking** means a
call the previous release accepted is now rejected, a value a caller read has changed meaning or
disappeared, or a stored job result can no longer be delivered: a caller has to change
something. **Surface** means the fingerprint moved for any other reason (a description, the
instructions text, an added field or parameter), so a fingerprint-aware client re-reads the
catalog and nothing else has to change. Sections before 0.3.0 predate the distinction and say
Breaking for both.

A release's section records what changed between the previous release and this one, not the
pull requests in between: an entry says where the release leaves a contract, and a problem
introduced and fixed between two releases is not listed. The 0.2.0 section predates this and is
per-change, as its own lead says.

## [Unreleased]

### Changed

- codex-cli 0.156 is a supported version, so `amicus_backends` no longer warns on it. It was
  checked against 0.155.1 at zero spend: `exec --help`, `exec review --help` and `login --help`
  are identical apart from trailing whitespace, and top-level `--help` adds only `--no-daemon`,
  which `exec` does not accept. The unknown-feature error, the logged-out `login status` line and
  the `--strict-config` rejection are unchanged, the four config keys amicus pins with `-c` are
  still accepted, and `remote_plugin` and `sleep_tool` are still `stable`. The tool list sent to
  `gpt-5.5` gains codex's `create_goal`, `get_goal` and `update_goal`, which amicus now disables
  (next entry). The tool lists of `gpt-6-astra`, `gpt-6-sol` and `gpt-6-luna` offer `clock.sleep`
  by default, and amicus's `--disable sleep_tool` still removes it. No paid call was part of the
  check.
- The bundled Codex model list that `amicus_models` falls back to gains `gpt-6-sol` and
  `gpt-6-luna`, copied from the catalog codex serves today, which is the same for 0.155.1 and
  0.156.1.
- Every Codex run now also passes `--disable goals`, so the model is no longer offered codex's
  `create_goal`, `get_goal` and `update_goal` tools. codex-cli 0.156.1 started offering them to
  `gpt-5.5`. On a persistent thread, an active goal can make codex start another turn after
  the final answer, and that turn never appears in `codex exec --json` output. This was seen once
  in seven runs against a scripted local endpoint, so the continuation is intermittent. amicus's
  runs were already protected, because under the `--ephemeral` flag amicus always sends codex
  refuses `create_goal` ("Goal tools require a persistent thread"). The disable removes the tools
  instead of relying on that refusal. `AMICUS_CODEX_EXTRA_ARGS` now refuses `--enable goals`,
  `--disable goals` and `-c features.goals…`, as it already did for `remote_plugin` and
  `sleep_tool`. `--disable goals` was checked on codex-cli 0.152.0, 0.153.4, 0.154.0, 0.155.1 and
  0.156.1, where `goals` is a `stable` feature (#222).
- `obs` reads FastMCP's own argument-validation summary. FastMCP 4.0.4 closed the leak issue
  #79 worked around (PrefectHQ/fastmcp#5106): it logs a `{"error_count", "error_types"}`
  summary in place of pydantic's error list. amicus's filter did not recognise that shape and
  withheld it whole, so the record read `Invalid arguments for tool amicus_consult: <detail
  withheld>`. It now renders the summary — `1 error(s): missing_argument` — with no field
  named, because upstream's summary carries no `loc`. The list shape is still read, since the
  `fastmcp>=4.0,<4.1` floor admits 4.0.3, and upstream's count and types are re-checked here
  rather than trusted. Nothing a caller sent reached the log under either shape.

### Fixed

- A `CODEX_HOME` that is not an absolute path as written is refused (#193). A relative value
  named one directory to the server, which read the models cache and probed `codex login status`
  from its own cwd, and another to each codex run, which resolves it against the workspace or a
  delegate's throwaway worktree. A literal `~` was expanded by amicus but not by codex, which
  then fails with "path does not exist". A paid Codex call now fails before spawning codex as
  `user_config_rejected`, whose repair says to set `CODEX_HOME` to an absolute path or unset it.
  `amicus_backends` reports codex with `authenticated: null` and a warning naming the variable,
  never its value, rather than probing a login from the wrong directory, and `amicus_models` falls
  back to the bundled list. An empty `CODEX_HOME` is still treated as unset, as codex treats it.
  An operator who set a relative `CODEX_HOME` must make it absolute before Codex calls run again.
- `amicus_job_consume_result` and `amicus_job_cancel` now advertise `destructiveHint: true` in
  every profile (#213). Consume deletes a retained result and cancel kills the worker and removes
  its worktree, so neither update is additive, and the `false` they carried contradicted their own
  descriptions. `amicus_capabilities.annotations_reading` now states this. **Surface**:
  `FINGERPRINT` moves to schema-40 for the annotations and the reading text.

## [0.5.0] - 2026-09-20

Across this release the discovery surface moves `amicus/0.1/schema-35`, what 0.4.0 shipped, to
`amicus/0.1/schema-39`, and stored job results move `RESULT_FORMAT` 7 to 9, so a job result 0.4.0
stored cannot be delivered after upgrading. The entries labelled **Breaking** are the changes a
caller or operator using 0.4.0 has to handle, and `docs/MIGRATION.md` ("Upgrading from 0.4.0")
walks through each. It was checked against codex-cli 0.155, Kimi Code 2.0 and Claude Code 2.1.278.

### Changed

- Kimi Code 2.0 is a supported version, so `amicus_backends` no longer warns on it. Kimi Code
  went from 0.43.1 to 2.0.2 in one upgrade; amicus has seen no 1.x and claims none. It was
  checked against the 0.43.1 capture at zero spend: `--help` differs by one new subcommand and no
  option, the `provider list --json` shape is identical, and `kimi session` still offers `list`
  only and still reads the existing session store, so no new way to avoid that carrier was
  found. The kimi live suite then passed on 2.0.2, which exercises consult, the read-only tool
  profile, review and delegate; whether 2.0.2 still writes to the session store was not looked
  at in that run (#202).
- Releasing now checks the backend CLIs first. `docs/RELEASING.md` gains a precondition, run
  immediately before the release evidence: bring `codex`, `kimi` and `claude` to their latest
  releases, run the new zero-spend `scripts/check_backend_compat.py` (installed and latest
  version, the warnings `amicus_backends` would raise, and the flags each `--help` declares
  against the newest committed capture), and do the AGENTS.md rule-18 carrier re-check by
  reading, which no script can. Codex gains its first committed help capture (0.155.1), held
  to the flags amicus always sends as Kimi's and Claude's already were, and Claude gains one for
  2.1.278. Nothing about how amicus runs changes (#188).
- codex-cli 0.155 is a supported version, so `amicus_backends` no longer warns on it. It was
  checked against 0.154.0 at zero spend: `--help`, `exec --help`, `exec review --help` and
  `login --help` are byte-identical, the unknown-feature error and the logged-out `login status`
  line are unchanged, both features amicus disables on every run are still `stable`, the cached
  model list is the same seven slugs in the same order, the tool list sent to `gpt-5.5` is
  identical with and without those disables, and the four config keys amicus pins with `-c` are
  accepted under `--strict-config` while an unknown key is still rejected in the form amicus
  parses. No paid call was part of the check (#187).

### Removed

- **Breaking.** `amicus_dry_run`, the deprecated alias of `amicus_review_changes_dry_run`, is
  removed. It was deprecated in 0.3.0 (#98) with a marker in its lifecycle `_meta`, on its
  `amicus_capabilities` row and at the head of its description, each naming 0.5.0, and ADR 0028
  removes a tool at the end of its window. Call `amicus_review_changes_dry_run` with the same
  arguments. The server now lists 18 tools, and no tool carries a deprecation marker; the
  mechanism and `amicus_capabilities.deprecation_policy` stay (#204).

### Fixed

- **Surface.** A replayed keyed `_async` call can hand back a job that is already terminal, and
  its handle's `follow_up` still said `poll_job_status` / `amicus_job_status`, which the skill's
  own rules forbid for a finished job. A terminal handle now carries `next_step:
  fetch_job_result` and `tool: amicus_job_result` with the same `job_id` and `workspace_root`; a
  running handle is unchanged. The two are separate correlated shapes in the output schema, so
  no mismatched step/tool pair is admitted. `fetch_job_result` is a new `repair.next_step`
  value. A caller that went by `status`, as the 0.4.0 descriptions told it to, changes nothing
  (#103).
- **Surface.** The `idempotency_key` parameter description said the key is scoped to "this tool
  + backend + workspace", which reads as though the same key on another backend were a separate
  identity. It never was: the key is scoped to the tool and the workspace, and `backend` is one
  of the arguments that must match, so that call is an `idempotency_conflict`. The description
  now says so; behaviour is unchanged (#178).
- **Breaking.** An answer file amicus refuses to read is no longer delivered as an empty answer.
  The bounded reader accepts only a regular file within 1,000,000 bytes (ADR 0009), and a file
  it refused was indistinguishable from a backend that wrote nothing: a Codex review came back
  `invalid_json`, and a Codex consult came back `ok: true` with "(the backend returned no
  message)". Both are now the new error `answer_unavailable`, with `error.details.reason` one of
  `artifact_oversize` (carrying `limit_bytes` and, when known, `actual_bytes`),
  `artifact_not_regular` or `artifact_unreadable`, never the path. It is temporary only for an
  unreadable file whose cause passes (descriptor or memory exhaustion); oversize repairs with
  `reduce_input`. Every other failure is still reported as itself, a refusal
  standing in only for a clean exit diagnosed as empty. A Kimi run whose stream carried the
  answer, captured whole, is delivered with a `meta.security_warnings` entry. A delegate with no
  such answer keeps its captured diff, with amicus's own summary saying the backend's could not
  be read and `raw_response.text` left null. An absent or empty file is unchanged: that is the
  backend saying nothing. The reader also now reads to the end of the file, where one short
  `read` could have delivered a prefix as the whole answer. The new error code is one of the two changes that move
  `RESULT_FORMAT` in this release, since an older reader's closed set of codes rejects it (#162).
- **Breaking.** A finding that cited one of amicus's own temporary files no longer carries it.
  Kimi is handed its prompt as a file, so a finding could come back with `file` set to
  `<tmp>/amicus-kimi-handshake-…/prompt.md` and `line` set to an offset into amicus's framing:
  a path deleted before the result is read, and a line into nothing the caller supplied. Every
  reference to a run's own staged files is now replaced by `[amicus temporary file]`, in the
  summary, the prose lists, a finding's text and `raw_response.text`, before the result is
  built or stored; a `file` that named one is null together with its `line`; and
  `findings_diagnostics.reasons` reports `backend_artifact_reference_removed` at `dropped: 0`.
  It never moves a verdict, and a failed run's error message is scrubbed the same way. Only the
  run's own staged paths match, the files it listed and anything under Kimi's per-run handshake
  directory, at path boundaries, so a workspace file that merely looks like one is untouched.
  A JSON answer is judged by what it decodes to, object keys included, whatever spelling it
  used; an answer that is prose around a JSON fragment is never decoded, so there the `\/` and
  `\u002f` spellings of a separator are recognised and a path spelled wholly in `\uXXXX` is
  not (#207). The new reason is the other change that moves `RESULT_FORMAT`, so a job result
  0.4.0 stored is `job_result_incompatible` after upgrading: fetch it first
  (`docs/MIGRATION.md`, "Upgrading from 0.4.0") (#140).

- The codex live gate, whose passing run is part of the evidence a release is tagged on, could
  pass on a codex version amicus had never checked: it asserted only the `codex-cli` prefix, as
  0.3.0's run on 0.154.0 showed. It now requires the installed minor to be in the built-in
  `SUPPORTED_VERSIONS` and `amicus_backends` to report no warnings, so neither an ambient
  `AMICUS_CODEX_SUPPORTED_VERSIONS` nor an unparseable version string can vouch for one (#113).
- Kimi's `carriers` disclosure on `amicus_backends(detail="full")` now names the kimi CLI's own
  session store (observed under `~/.kimi-code/sessions`), whose files can hold the whole prompt and
  any answer produced. amicus does not delete it, and `AMICUS_JOB_TTL`, the per-workspace cap and
  `amicus_job_consume_result` never reach it. Kimi's `readonly_honesty` no longer says Kimi
  "cannot MODIFY anything": read-only removes the agent's shell and write tools, not the CLI's
  own session files. Nothing about what is written changed; only what is said about it (#179).
- A relative `AMICUS_STATE_DIR`, `AMICUS_CODEX_BIN`, `AMICUS_KIMI_BIN` or `AMICUS_CLAUDE_BIN` is
  now refused instead of being resolved against the process's working directory. The server and
  each job worker resolve configuration separately, and a worker runs from its job directory, so
  a relative value named one place to the server and another to the worker. With a relative
  state directory the server now refuses to start, naming the variable on stderr: falling back
  to the default would keep whole answers somewhere the operator did not choose. A relative
  binary override makes that backend report the override as unusable, as a missing file already
  did. Absolute values are unchanged, and so is a leading `~` in `AMICUS_STATE_DIR`, which is
  still expanded. `$XDG_CACHE_HOME` is different: a value that is not absolute as written,
  `~/cache` included, is ignored and never expanded, as the XDG Base Directory specification
  requires (#173).
- `config.settings()` no longer documents itself as never raising: it never raises on a
  malformed or conflicting setting, and an unresolvable home directory is a startup failure
  (#147).

## [0.4.0] - 2026-09-18

Across this release the discovery surface moves `amicus/0.1/schema-30`, what 0.3.0 shipped, to
`amicus/0.1/schema-35`, and stored job results move `RESULT_FORMAT` 6 to 7, so a job result 0.3.0
stored cannot be delivered after upgrading. The entries labelled **Breaking** are the changes a
caller or operator using 0.3.0 has to handle, and `docs/MIGRATION.md` ("Upgrading from 0.3.0")
walks through each.

### Added

- The `collaborating-with-amicus` skill gains a blind-comparison workflow
  (`references/blind-comparison.md`): two or more finalized candidates, compared by a backend
  that wrote none of them, blinded, against criteria fixed before the call, returning
  per-criterion reasons and one preference the host verifies as a finding rather than a score it
  adopts. A new root rule says a backend's stated preference never stands in for the decision.
  No tool or server surface changes and `FINGERPRINT` does not move.

### Changed

- Every paid tool, sync and async, and the `detail` parameter now disclose that the job record
  keeps the backend's whole answer whatever `detail` delivered it, that the answer can quote the
  caller's inputs, and what ends it: expiry under `AMICUS_JOB_TTL` (an expired record is removed
  on a later job call, not by a daemon), the per-workspace cap or `amicus_job_consume_result`
  (#163, ADR 0035). Nothing stored or delivered changes: the record has kept the answer since M2,
  and the decision recorded is that rule 18 binds the inputs amicus writes, not the answer a
  backend returns. **Surface**: `FINGERPRINT` moves to schema-35 for the description text.
- amicus no longer depends on `pontonier`. Its backend SDK is now part of amicus, as
  `amicus.sdk` (#13, ADR 0029): the same code as pontonier 0.9.0, copied from its `v0.9.0`
  tag with the imports rewritten. Nothing on the wire or in a stored job result changes, and
  `FINGERPRINT` does not move. A third-party backend distribution imports the SDK types from
  `amicus.sdk` instead of `pontonier` and declares plugin API version 2: `PLUGIN_API_VERSION`
  moved from 1 to 2, so the registry rejects a plugin that pins `api_version=1` (#115 covers
  one that leaves it unset). No release can enable a third-party backend yet, so no running
  deployment is affected. SDK log records are no longer named `pontonier.*` in stderr and
  `AMICUS_LOG_FILE`, since the log format prints the logger name, which matters for an
  operator who filters logs by name: they are named `amicus.sdk.*`, except the job store and
  its idempotency index, which are `amicus.jobs.store` and `amicus.jobs.idempotency`. These
  `amicus.sdk` import paths are not yet stable for a third-party backend. ADR 0030 settles
  where they end up, and this release leaves that move finished (#118–#123): `amicus.sdk`
  holds what a backend imports — the backend protocol and contract, the error vocabulary,
  annotations and preflight, the subprocess runtime, stream capping, redaction, path-alias
  sanitizing and a bounded JSON reader — plus the conformance kit, which is the one thing
  there that a backend does not import: the registry imports it and runs it against a plugin
  before it will use one. The job store, the git layer, the fingerprint mechanics and the
  prompt framings live in the amicus package that owns each. Of the pontonier-named literals
  the copy brought with it, one was visible outside the code: the throwaway directory amicus
  creates to run git with its hooks disabled is now named `amicus-nohooks-*` under the system
  temp dir, not `pontonier-nohooks-*`. Nothing keys on that name.

### Removed

- **Breaking.** The three siblings' environment names — `CODEX_IN_CLAUDE_*`, `MOONBRIDGE_*`
  and `CLAUDE_IN_CODEX_*` — are no longer read (#176), as 0.3.0's warnings and
  `docs/MIGRATION.md` said they would not be from 0.4.0. An operator who still sets one gets
  the `AMICUS_*` default instead of the value, which for `CODEX_IN_CLAUDE_ISOLATION` or
  `CLAUDE_IN_CODEX_CLAUDE_CONFIG` is looser than what was set. Each former name is now a
  tombstone on the `AMICUS_*` declaration that replaced it: a name still set is reported by
  `amicus_backends`, in `env_warnings` for a global setting and in the backend's
  `status.warnings` for a backend one (so only while that backend is enabled and loaded),
  naming the `AMICUS_*` name to set; its value is never read, not even to recognise a
  placeholder, so it neither supplies the setting nor conflicts with the `AMICUS_*` value,
  and the conflict error of the window is gone with it. The tombstones have no removal window: they
  are the migration table's data and a diagnostic, not a compatibility path. The shim itself
  (`EnvVar.legacy`) and the release guard that refuses a release at or past
  `LEGACY_REMOVAL_VERSION` while an alias is declared both stay, so a later rename gets the
  same window. `FINGERPRINT` moves to `schema-34` only because the `amicus_backends`
  description no longer says "legacy-env warnings"; no schema changes.

### Fixed

- **Surface.** A Claude budget stop no longer reports `input_tokens: 0` and
  `output_tokens: 0` beside a nonzero `cost_usd` (#158). claude prints its top-level `usage`
  block zeroed on that envelope while `modelUsage` carries the real counts, and its own
  result schema names `modelUsage` as the accounting field, so `meta.usage` now comes from
  `modelUsage` (summed across models) whenever at least one of its entries is an object,
  and from the top-level block only when none is (ADR 0034). A field is read from one
  block, never both: once `modelUsage` is in use, a field any one entry leaves out is
  `null`, and a non-object entry beside an object one makes every count `null`. So an older
  envelope whose `modelUsage` has no cache keys now reports `cached_input_tokens` and
  `cache_creation_input_tokens` as `null` where it used to copy the block's numbers.
  `budget_exceeded`'s message and repair, the `max_budget_usd` option description and the
  `AMICUS_CLAUDE_MAX_BUDGET_USD` description now say claude checks the threshold only
  between model calls, so one call can carry the estimated cost past it; none states an
  overshoot bound, and the repair no longer suggests a 0.10-0.20 floor it had no evidence
  for. The recorded 2.1.274 budget-stop envelope is `tests/fixtures/claude_budget_stop_envelope.json`,
  documented in `docs/claude-help/2.1.274/`. `RESULT_FORMAT` does not move.

- Every tool that resolves a workspace no longer fails as a retryable `internal_error`
  (`FileNotFoundError`) when the server process's working directory has been deleted under
  it, as happens when the Claude Code worktree the server was started in is removed (#170).
  The resolver now reads the process cwd only on the one branch where it decides the
  outcome (no `workspace_root`, no client root, and `AMICUS_ALLOW_CWD_WORKSPACE=1`), so a
  call that names its workspace never consults it. When that branch is reached and the cwd
  is gone, the call fails as a non-temporary `invalid_workspace_root` whose message says to
  pass `workspace_root`, configure an MCP root, or restart the server from an existing
  directory, instead of a `retry_then_report` repair that could never succeed. No error
  code was added and `FINGERPRINT` does not move.

- Codex usage-limit failures without a parseable relative delay now report
  `retry_after_ms: null` with an `inspect_and_retry` repair instead of inventing a
  60-second delay for a reset that may be days away (#165). When codex states the reset
  as a clock time (`try again at Sep 19th, 2026 8:37 AM.` or `try again at 12:39 PM.`),
  that phrase is echoed in `error.message`, `error.details.reason` and the repair, marked
  as a clock time with no time zone stated when it names none, so the caller can read the
  reset it must wait for. Only a clock-time shape is echoed; other wording gets the generic
  guidance. Explicit relative delays and the 60-second fallback for ordinary rate limits are
  unchanged.

- Codex failure classification now reads backend error events and stderr instead of
  matching authentication, contract-drift and rate-limit terms in model answers or tool
  output (#166). Model prose can no longer override the backend's diagnosis or retry delay.
  Generic failure details also exclude model and tool items, preventing that text from
  being copied into a background job's stored error.
  Plain-text startup diagnostics and error events containing only an HTTP status remain
  supported. Neither `FINGERPRINT` nor `RESULT_FORMAT` moves.

- `amicus_backends` no longer reports `authenticated: false` whenever the Codex login-status
  probe exits nonzero (#169). Only a recognized authentication failure reports `false`; a
  configuration error or other probe failure reports `authenticated: null` and adds a sanitized
  diagnostic to the backend's warnings. `FINGERPRINT` does not move.

- **Surface.** `amicus_review_changes` on the `claude` backend now defaults to
  `backend_options.access = "readonly"` (#116, ADR 0032). On the previous `toolless` default a
  review had no tool to read the code it was judging, and answered with tool-call markup
  instead of the review: amicus reported `invalid_json`, or under the default
  `config_mode = "inherit"` ran to the budget stop. A Claude review that omits `access` can now
  read files with `Read`, `Grep` and `Glob`, inside and outside the workspace, which bypasses
  diff redaction; pass `access: "toolless"` to keep the old behaviour for one call.
  `amicus_consult` and `amicus_adversarial_review` still default to `toolless`, and setting
  `AMICUS_CLAUDE_ACCESS` sets the default for every verb, reviews included. A structured Claude
  review also now carries the output guardrails adversarial reviews already had, telling the
  model never to simulate a tool call. `amicus_backends` reports `access` under
  `default_by_verb`. `FINGERPRINT` moves to `amicus/0.1/schema-31`.
- **Breaking.** A review whose answer amicus cannot read as one JSON object is no longer
  discarded (#139, ADR 0033). `amicus_review_changes` and `amicus_adversarial_review` used to
  return `invalid_json` or `schema_violation`. They kept a 300-character preview of the answer,
  lost the rest, and prescribed a retry that could fail the same way. They now return
  `ok: true` with the new `review_status: unstructured`: `verdict` and `confidence` are
  `unknown`, `findings` and the prose lists are empty with diagnostics saying nothing was
  parsed, and the whole answer, redacted, is `raw_response.text`, at `detail="full"` on the call
  or free from `amicus_job_result`. A caller that read the verdict after checking `ok` must now
  handle this value. An answer that wraps exactly one object in a preamble, a fence or a
  sign-off is now read as that object. A repeated key is still refused (#51). Only an empty
  answer is still an error (`invalid_json`, or `empty_response` on Kimi), and
  `schema_violation` is no longer a review outcome. `empty_response`, which Kimi already
  returned for an empty answer, is now listed in the `error_codes` of every paid tool that can
  select Kimi.
  `RESULT_FORMAT` moves to 7 and `FINGERPRINT` to `amicus/0.1/schema-32`.

- A plugin install no longer runs an older release's server than its bundled skills (#117,
  ADR 0031, superseding ADR 0015). Hosts key an installed plugin by `plugin.json`'s version and
  do not re-read it until that version changes, so a plugin whose `.mcp.json` named the previous
  release kept launching that older server. `.mcp.json` now names its own release, and after
  0.4.0 is published the marketplace entry pins that tag by `ref` and `sha`, so the installed
  skills and server come from one release snapshot. Installs already stuck on an older server
  recover when the 0.4.0 version change reaches them.

- **Security.** An exception's own text can no longer reach a background job's `stderr.log`
  (#128). The job worker never called `obs.configure`, so nothing in that process installed
  the handlers that withhold exception text, and an `amicus.*` record fell through to
  `logging.lastResort` — which renders the exception's `str()` and a full traceback. The
  worker's stdout and stderr are both `<job_dir>/stderr.log`, so that text was written to a
  file the job keeps. The reachable call site is the SDK runtime's
  `logger.error("stdout capture failed: %s", exc, exc_info=True)` on a capture failure, and
  an exception raised inside a backend adapter can embed the prompt text that provoked it,
  which AGENTS.md rule 18 forbids writing to a log. `_worker.main` now configures logging
  before anything else it does, so such a record renders as the exception's type and its
  frame locations, the same policy the server has always applied. The worker inherits the
  server's environment, so it honours the same `AMICUS_LOG_LEVEL` and `AMICUS_LOG_FILE` —
  except a *relative* `AMICUS_LOG_FILE`, which it drops: `logging.FileHandler` resolves a
  relative path against the process's cwd, and the worker's cwd is the job directory, so
  honouring it would leave a differently-located log file inside every job directory instead
  of adding to the one file the operator asked for. An absolute path is honoured, and the
  server's own handler is unaffected either way. Nothing about a job's result, status or
  wire shape changes, and `FINGERPRINT` does not move.
- A `codex` run that hit its usage limit could fail as `backend_auth_required` instead of
  `backend_rate_limited` (#160). The classifier checks authentication first and matched the bare
  substring `401`, so any output carrying those digits, such as a token count of 14012, read as
  "not authenticated". The repair then told the caller to log in again, and marked the failure
  not temporary. A `401` now counts only as an HTTP status, and codex's own "could not be
  refreshed" token failures are recognized as authentication failures. `FINGERPRINT` does not
  move.

## [0.3.0] - 2026-09-15

Across this release the discovery surface moves `amicus/0.1/schema-13`, what 0.2.0 shipped, to
`amicus/0.1/schema-30`, and stored job results move `RESULT_FORMAT` 4 to 6, so a job result
0.2.0 stored cannot be delivered after upgrading. The entries labelled **Breaking** are the
changes a caller written against 0.2.0 has to handle, and `docs/MIGRATION.md` ("Upgrading from
0.2.0") walks through each. `tools/list` grows from 18 tools to 19 and from 98,925 to 114,780
bytes on the `all` profile, both measured the same way, as a real stdio server writes the result
for a handshake-era client; about 9 KB of the growth is the deprecated `amicus_dry_run` alias,
which goes when the alias does.

### Added

- **Surface.** Review and adversarial-review results and the review preview carry a top-level
  `coverage` object (#65, ADR 0019): `status`, untracked-file counts, `omission_reasons` and a
  `redaction` breakdown, in the siblings' shape plus amicus's own `focused` reason. An omitted
  untracked file, a tree that changed during the gather, or a focused pass reached a 0.2.0
  caller only as prose in `summary`, and the free preview reported none of it. The preview also
  accepts `focus` and reports `max_input_bytes`, so it previews the coverage the paid call will
  report. ADR 0019 supersedes ADR 0007's coverage clause.
- **Breaking.** Consult, review and adversarial-review results carry `lists_diagnostics`, the
  prose-list twin of `findings_diagnostics` (#52, ADR 0024). In 0.2.0 their `questions`,
  `assumptions` and `next_steps` lists kept string, number and bool entries as strings, dropped
  every other entry with no count, and turned a non-list member into `[]`, so a caller could not
  tell "the backend said nothing" from "amicus could not carry what it said". The field is null
  when all three lists were carried intact, otherwise one `{dropped, reasons}` member per list
  that was not, with a fixed reason vocabulary (`number_stringified`, `invalid_entry`,
  `invalid_container`, `missing_member`) and never the omitted content. A number is still
  delivered as its string and now says so; a bool, which 0.2.0 delivered as `"True"` or
  `"False"`, is now dropped and counted like a null, object or array entry. A consult answered
  in prose rather than the requested object reports `missing_member` on all three lists and
  `missing_findings` in `findings_diagnostics`, which 0.2.0 left null on that path. A
  `review_status: not_run` result keeps both diagnostics null, because no backend ran. Nothing
  folds into the verdict or confidence. Delegate results do not carry the field: their
  `next_steps` is amicus's own text.
- **Surface.** `amicus_consult`, `amicus_review_changes`, `amicus_adversarial_review` and
  `amicus_delegate` accept `idempotency_key`, as both siblings' synchronous tools do (#66, ADR
  0020); in 0.2.0 only the `_async` twins accepted it. A keyed sync call awaits the run the key
  names, its own or another caller's for the same key and arguments, and delivers its result
  marked `meta.idempotency_replayed: true`, so a retried sync call cannot pay twice. A keyed
  sync run gets the job deadline (`AMICUS_JOB_MAX_SECONDS`), as an `_async` run does, and
  `timeout_seconds` bounds only how long the call waits for it. A keyed waiter does not own the
  job: its local timeout returns a temporary `timeout` with a `poll_job_status` repair naming
  `amicus_job_status` for that job instead of cancelling it, its cancellation leaves the run
  going, and under the tasks extension a keyed task's job survives `tasks/cancel` (an unkeyed
  task's is still cancelled with it). Sync and `_async` stay separate identities, and the sync
  tools' error catalogs name the three dedup codes. ADR 0020 supersedes ADR 0008's unkeyed-sync
  clause. The empty-key rejection that came with this is under Changed.
- **Surface.** `amicus_review_changes_dry_run`, the review preview, named for the call it
  previews as `amicus_delegate_dry_run` is (#98, ADR 0028). It takes `amicus_dry_run`'s
  arguments and returns its result, with `tool` naming it; the old name is under Deprecated.
  With it comes the marker the `deprecation_policy` promised: a deprecated tool's lifecycle
  `_meta` carries `deprecation` beside its unchanged `stability`, with exactly `since`,
  `removal_at_or_after`, `replaced_by` and `migration`, and every `amicus_capabilities`
  `tool_details` row carries a `deprecation` field with the same object, null for a tool that is
  not deprecated.
- `/amicus:delegate-async`, a slash command that starts one `amicus_delegate_async` job,
  reports its `job_id` and hands the poll and fetch to `/amicus:jobs` (#67). Delegation is the
  verb likeliest to outrun the synchronous deadline, so its background start is the one that
  gets a command of its own; the other async twins stay reachable from their verb's command.
  `/amicus:delegate` points at it for long tasks, and `/amicus:jobs` says to fetch once the
  status is anything but `running` rather than waiting on `result_available`, which is true
  only for `done`.

### Changed

- **Breaking.** A job result stored by 0.2.0 can no longer be delivered. `RESULT_FORMAT` moves
  from 4 to 6 for `coverage` (#65) and `lists_diagnostics` (#52), so `amicus_job_result` and
  `amicus_job_consume_result` return `job_result_incompatible` for a record 0.2.0 wrote, rather
  than a result whose new fields would answer for a run that never measured them. The record
  itself stays until `AMICUS_JOB_TTL` or the per-workspace cap evicts it.
- **Breaking.** Every success envelope's `meta` is sparse on the wire, on every tool (#47, ADR
  0025). In 0.2.0 only a delivered paid result dropped meta's null-valued keys, as the
  `amicus://result-meta` description said; a job handle, job status, job list or dry run carried
  every key, null or not. Read an absent key as null. The guard every tool passes through slims
  every success, keyed on null and never on falsiness. The always-present core is published as
  the schema's own `required`: `elapsed_ms`, `truncated`, `compat_warnings`,
  `security_warnings`, `redacted_paths`, `request_id` and `fingerprint`. An empty list there
  means that envelope reports none, not that a check ran: a job handle, status or list and a
  dry run report on the call that produced them, and the run's warnings arrive on its own
  result. Only meta's top level is touched: a null inside `usage`, or outside `meta` such as
  `JobListResult.truncation_hint`, is that object's own contract.
- **Breaking.** A `review_status: not_run` review reports `confidence: unknown`, not `low` (#54,
  ADR 0026). No backend ran on an empty scope, so there was no rating to carry, and `low` is
  the lowest rating a backend can report: stating it manufactured a claim. The published
  `confidence` description names `not_run` as one of the two causes of `unknown`, beside an
  unreadable backend rating, and the substituted `low` has two sources instead of three:
  partial coverage and findings amicus could not carry, each beside an `unknown` verdict, so a
  `low` beside any other verdict is still the backend's word. Branch on `review_status` for
  whether a review ran.
- **Breaking.** A replayed keyed `_async` handle for a job that has already finished reports
  `poll_after_ms: null`, as `amicus_job_status` already did on every terminal status (#101). In
  0.2.0 it reported `1000`, the store's flat base, so a host that read a non-null hint as "still
  running" waited a second and polled once more before it saw the terminal status.
  `JobStarted.poll_after_ms` is required but nullable on the four `_async` tools' output
  schemas, with a published description saying when it is null, the same one
  `amicus_job_status` and `amicus_job_cancel` carry. The four `_async` descriptions, the
  `amicus_job_status` description, the synchronous `timeout` repair and the skill say to poll
  only while `status` is `running`. A terminal handle's `follow_up` still names
  `amicus_job_status`, because pontonier has no repair step yet for fetching a finished job's
  result (briandconnelly/pontonier#30, #103).
- **Breaking.** The free discovery tools default to a summary (#46). `amicus_capabilities`
  defaults to `detail="summary"`, whose `tool_details` rows carry `name`, `cost`, `stability`,
  `deprecation` and `backends`; `use_when`, `required_params`, `key_optional_params`, `returns`
  and `error_codes` are on `detail="full"`, and a summary row carries no `error_codes` key at
  all rather than an empty list that would read as "raises nothing". `detail` changes field
  density only, never the row count, and a new `include_tool_details=false` selects the
  rowless payload for a fingerprint or `surface_digest` re-check (see Removed).
  `amicus_backends` gains `detail` (`summary` default, `full`); `summary` leaves each backend's
  `egress`, `carriers`, `readonly_honesty` and `implicit_context` keys out of every entry and
  names them in a new top-level `omitted_fields` (empty on `full`), so an absent key means "not
  requested" and a `null` on `full` still means no loaded plugin declares one. The
  `amicus://backends/{backend}` resource is always the `full` entry. The server instructions
  and the skill say to read `amicus_backends(detail="full")` once before the first paid call.
- **Breaking.** Two workspace errors, `invalid_workspace_root` and `workspace_outside_roots`,
  carry no `repair` (#42, ADR 0021): no call can supply the caller's directory, and
  `details.field` and `candidate_roots` already name what to fix. Every other error's
  `repair.arguments` carries a complete call wherever one is uniquely known. An
  `invalid_arguments` rejection whose every rejected argument is an unknown key repairs with
  the call as sent minus those keys, but only when every remaining value is null, a bool, a
  number, a published enum member, or an object built from those: a prompt input, path, model
  slug or `idempotency_key` is never echoed and suppresses the arguments instead.
  `amicus_models` and `amicus_backends` repairs name the failing call's `backend` when the tool
  accepts it (`amicus_models` requires it, so its 0.2.0 repair was not callable), and
  `job_not_found` repairs to `amicus_job_list({})` when the workspace came from roots. A repair
  that names no tool (`correct_config`, `reduce_input` and the like) is still a symbolic next
  step. The policy is published on the error-envelope schema.
- **Breaking.** An empty `idempotency_key` is rejected before spending on every paid tool, as
  `invalid_arguments` (`minLength: 1`, the siblings' bound); 0.2.0's `_async` tools accepted
  `""` as a key (#66).
- **Breaking.** Claude adversarial reviews, sync and async, default to `config_mode="safe"`
  (#64). Inherited Claude instructions can displace the JSON critique contract, so an
  adversarial review no longer inherits the user's Claude configuration unless the call passes
  `backend_options.config_mode` as `inherit` or `scoped`, the two modes that read it; an
  explicit mode is honoured on every verb. When
  `AMICUS_CLAUDE_CONFIG_MODE=bare` the default stays `bare`, so API-key-only installations keep
  their authentication path; consult and review-changes calls still use the configured default.
  `amicus_backends` reports the option's per-verb defaults in `default_by_verb`, with a null
  common `default` where the verbs differ, where 0.2.0 reported one default for every verb.
  Adversarial runs also carry a JSON-only, no-simulated-tools guardrail in their prompt.
- **Surface.** `amicus_job_consume_result` reports what deleting the record did, in
  `meta.consume` (#44, ADR 0022). 0.2.0 always delivered the stored envelope but reported plain
  success even when the deletion failed, while its description promised that a repeat call
  returns `job_not_found`. `meta.consume.discard_outcome` is `removed`, `missing`, `not_done` or
  `delete_failed`; only the first two keep that promise, and the other two carry a `follow_up`
  that calls `amicus_job_status` on the job. A real failed delete can leave a record that reads
  as `failed`, so the follow-up promises neither redelivery nor deletion at expiry. The field is
  delivery-only: it is never stored, and `amicus_job_result` never sets it. A job that failed,
  was cancelled or timed out has no stored envelope, so consuming it returns its terminal error
  with no `meta.consume` and deletes nothing, leaving the record to the usual expiry and
  per-workspace eviction as 0.2.0 did; every consume surface now says so (#94). Deleting such a
  record on request needs an atomic compare-and-delete from pontonier
  (briandconnelly/pontonier#31), because a record read as `failed` can turn `done` after it is
  read.
- **Surface.** A running job's `poll_after_ms` keeps growing past ten seconds, up to 30 s (#95).
  The hint still means roughly "wait about as long as the job has already run", but 0.2.0
  inherited pontonier's 10 s stop, so a four-minute review was polled about 28 times; with the
  30 s ceiling it is about 13, and a finished job is noticed at most 30 s late. Every place that
  hands out the hint agrees on it: `amicus_job_status`, the `job_running` repair's
  `retry_after_ms`, a keyed sync wait's `timeout` repair, and a replayed keyed `_async` handle
  for a job that is still running. The `amicus_job_status` description states the ceiling. MCP
  tasks keep FastMCP's own flat `pollIntervalMs` (#100).
- **Surface.** The server `instructions` lead with their rules and ship as three blocks: what
  amicus does and does not do, a list of rules, then reference (#49, ADR 0027). 0.2.0's were one
  unbroken 3,698-character line, and Claude Code shows the model only the first 2,048
  characters of a server's instructions, so everything after "read error.backend, and" never
  reached it there: following `error.repair`, treating findings as claims, reading a
  `completed` task as a delivery statement rather than a success, and the job-handle TTL. Every
  rule now ends before character 2,048, and a test holds it there. The tool-failure and
  resource-read-failure rules are separate items, each naming its own path: a resource-read
  failure's code is `error.data.machine_code`, not the era-bound numeric JSON-RPC
  `error.code`. The protocol-era mechanics moved to reference, beside the now-stated `stdio`
  transport, and the host-capture provenance is gone. The job rule names both retention bounds,
  `AMICUS_JOB_TTL` and the per-workspace cap that can evict a result sooner. The text is 3,392
  characters. Treating findings as claims to verify, not commands, also rides the `findings`
  description on `amicus_consult`, `amicus_review_changes`, `amicus_adversarial_review` and
  `amicus_delegate` (#97), so it no longer depends on a host showing the instructions.
- **Surface.** `tools/list` states each shared parameter contract once in full rather than on
  every tool (#41). Each tool's schema is self-contained on the wire, so the six shared
  contracts (`workspace_root`, `reasoning_effort`, `backend_options`, `instructions_append`,
  `extra_context`, `idempotency_key`) were repeated on every tool that declares them, up to
  fifteen times per catalog; their inline descriptions are now a one-line summary plus the
  `amicus://params` pointer, and the elaboration lives in that resource's `full` text, which was
  already the authoritative contract. The `default: null` pydantic stamps on every optional
  parameter is stripped at list time; non-null defaults such as `detail: "summary"` stay. The
  error-envelope and result-meta pointer descriptions on every `outputSchema` are one clause
  each, and the four `_async` tools' `follow_up` is published as the one action it ever carries
  (`poll_job_status` via `amicus_job_status`) instead of the whole repair-step enum. No tool,
  parameter, accepted input value, runtime behaviour or error changed.
- **Surface.** The `reasoning_effort` contract names claude beside kimi as a backend whose CLI
  does not reject a bad effort, and says claude checks a fixed list where kimi reads the model
  catalog (#76). The adapter change is under Fixed.
- The kimi backend supports kimi-code 0.42 and 0.43 (#109), beside 0.35, 0.39 and 0.41.
  Neither changes a flag amicus sends or refuses: 0.42.0's `--help` adds only an `rc|remote`
  subcommand, 0.43.1's only an `[options]` placeholder on `upgrade`, and the
  `provider list --json` shape is unchanged in both (captures in `docs/kimi-help/0.42.0/` and
  `docs/kimi-help/0.43.1/`), so `amicus_backends` does not warn that such an install is outside
  the versions amicus was built against. `FINGERPRINT` does not move: the supported set is not
  part of the discovery surface.
- The codex backend supports codex-cli 0.154 (#112), beside 0.152 and 0.153. Zero-spend checks
  against 0.153.4 found no change in what they cover: `codex exec --help` adds only
  `--worktree`, `codex --help` drops only the `mcp-server` subcommand amicus never used,
  `remote_plugin` and `sleep_tool` are still feature flags, and the rejections amicus
  classifies (an unknown config key in both forms, an unknown feature, an unknown flag, an
  invalid value, an unknown enum variant) read the same. The paid semantic probes (the
  workspace-write sandbox pins, the reasoning-effort key, structured output) were not re-run
  for 0.154. `amicus_backends` does not warn that such an install is outside the versions
  amicus was built against. When codex's `models_cache.json` is unreadable, `amicus_models`
  lists 0.154.0's catalog where 0.2.0 listed 0.149.1's: `gpt-6-astra` is added and `gpt-5.4`
  and `gpt-5.4-mini` are gone. `gpt-6-astra` advertises codex's `clock` tools, so its default
  exec path offers `clock.sleep`, which can wait up to 12 hours; the `--disable sleep_tool`
  amicus sends on every model-bearing run removes it. `FINGERPRINT` does not move: the
  supported set only decides a status warning, and the listed models are runtime values in
  `amicus_models` results, while `FINGERPRINT_COVERS` covers that tool's schema rather than
  the values it returns.
- Legacy environment names (`CODEX_IN_CLAUDE_*`, `MOONBRIDGE_*`, `CLAUDE_IN_CODEX_*`) are
  removed in 0.4.0, not in 0.3.0 as 0.2.0's warnings and `docs/MIGRATION.md` said. 0.2.0, the
  first release to warn on them, shipped four days before 0.3.0 was cut, and one
  warning-bearing release is too short a window for an operator-facing rename; each warning
  now names 0.4.0. `scripts/check_release_state.py` refuses a release at or past
  `LEGACY_REMOVAL_VERSION` while any `EnvVar` still declares a legacy name, so the promise
  cannot be missed again.
- The `mcp` requirement is `>=2.1,<2.3`, so amicus runs on mcp 2.2 (#81); 0.2.0 capped it below
  2.2. `fastmcp` stays `>=4.0,<4.1` and pontonier stays at `0.9.0`.

### Deprecated

- **Surface.** `amicus_dry_run`, in favour of `amicus_review_changes_dry_run` (#98, ADR 0028).
  It read as a preview for any paid call, while it covers only `amicus_review_changes`. It
  stays listed, last among the free tools, with its input schema, annotations and outputSchema
  unchanged, so existing calls keep working and its result's `tool` stays `amicus_dry_run`; its
  title, description and lifecycle `_meta` say it is deprecated, and its description still
  carries the full preview contract. It is deprecated from 0.3.0 and removed in 0.5.0:
  `scripts/check_release_state.py` refuses to release outside that window.

### Removed

- **Breaking.** `amicus_capabilities(detail="contracts")`, which returned no `tool_details` rows
  (#46). It is rejected as `invalid_arguments`; pass `include_tool_details=false` for the same
  rowless payload.

### Fixed

- **Breaking.** Resource records carry their size in the native `Resource.size` field, and only
  when it is known (#48). In 0.2.0 every record published `size_bytes` under the private
  `dev.bconnelly.amicus/triage` `_meta` convention, which an off-the-shelf client may never
  surface, while the native field stayed empty, and the volatile `amicus://capabilities`
  advertised `size_bytes: 0` for a body that is never empty. The three static resources now
  carry `size`, the byte length of exactly the text a read returns, and no triage block; the
  volatile resource and both templates carry no size at all, and their triage block is the one
  `volatile: true` key, which has no native home.
- A structured answer whose JSON object repeats a key is refused as `invalid_json` (#51). 0.2.0
  parsed it with plain `json.loads`, which keeps the last member silently, so a populated
  `findings` followed by `findings: []` arrived as empty and `findings_diagnostics` reported no
  loss: the content was gone before anything could measure it. The parse now fails on a
  repeated key at any depth, which the strict review and adversarial paths return as a hard
  error, and consult falls to its prose passthrough (sanitized summary, redacted
  `raw_response`). The codex backend's `parse_structured` delegates to the shared classifier as
  claude's and kimi's already did, so no backend can carry a collapsed object.
- The `collaborating-with-amicus` skill told an agent to confirm a backend's `features` list
  contains the verb it was about to call, and its backend reference called `features` "the
  verbs it supports" (#84). `features` names only the gated verbs (`delegate`,
  `adversarial_review`) plus non-verb capabilities, so a host following the rule concluded
  `consult` and `review_changes` were unsupported everywhere. The rule now names the two gated
  verbs and says the other two never appear there, and the reference documents every member.
  The skill also says that `poll_after_ms` grows only to a 30 s ceiling, that a reported review
  of a few hundred lines runs two to four minutes against the 300 s sync default, and that a
  sync call with an `idempotency_key` waits inside one call.
- FastMCP logged every rejected `tools/call` to the server's stderr with pydantic's error list,
  and each error's `input` is the rejected value itself, against AGENTS.md rule 18 (#79).
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
- Exception text is kept out of stored background-job crash results and returned spawn-failure
  envelopes, since backend exceptions can contain prompt inputs (#56).

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

[Unreleased]: https://github.com/briandconnelly/amicus/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/briandconnelly/amicus/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/briandconnelly/amicus/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/briandconnelly/amicus/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/briandconnelly/amicus/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/briandconnelly/amicus/releases/tag/v0.1.0
