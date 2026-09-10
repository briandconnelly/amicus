# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- **Breaking (`FINGERPRINT` `schema-12`).** The published stability tier is now inside the
  closed set an agent can filter on. Every tool, static resource and resource template carried
  `alpha` in its lifecycle `_meta`, and `amicus_capabilities.stability` reported it too --
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

### Changed

- `FINGERPRINT` moves `amicus/0.1/schema-7` → `amicus/0.1/schema-8` for the `amicus_job_result`
  description change, with every pin regenerated in a dedicated commit (rule 10). `RESULT_FORMAT`
  stays `2`: no stored result changed shape.
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

[Unreleased]: https://github.com/briandconnelly/amicus/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/briandconnelly/amicus/releases/tag/v0.1.0
