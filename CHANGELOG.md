# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

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
