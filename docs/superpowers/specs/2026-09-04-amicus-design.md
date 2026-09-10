# amicus design spec (rev 2, Codex-reviewed, 2026-09-04)

## Context

Three sibling MCP servers each bridge a host coding agent to one other model's CLI:
`codex-in-claude` (Codex, 0.22.0), `moonbridge` (Kimi, 0.3.0), `claude-in-codex`
(Claude Code, 0.9.0). Their generic machinery was already extracted into the shared
library **pontonier** (0.8.0, protocol frozen at `CONTRACT_API_VERSION = 1`), and every
model-bearing run in all three now stages through a `pontonier.backend.AgentBackend`
adapter. What remains duplicated is the whole server layer: ~38k LOC of tool
registration, envelopes, orchestration, job workers, config and packaging, forked three
ways. The naming/scoping notes in `~/projects/amicus.md` (2026-09-04) settled the name
and the shape (verb-first tools, backend as a parameter).

**amicus** is a new server at `~/projects/amicus` (package `amicus`, console script
`amicus-mcp`) that exposes every backend through one tool vocabulary, built on FastMCP
4.0.x and MCP 2026-07-28, designed against the canonical agent-friendly-mcp checklist
(`~/projects/skills/agent-friendly-mcp`, already rebased onto 2026-07-28), with a backend
plugin seam so a fourth model is one package, not a fourth server.

### Decisions (user-confirmed 2026-09-04)

1. **Verb-first surface, backend as a parameter.** `amicus_consult(backend="codex", ...)`.
2. **Async = both.** Durable pontonier `JobStore` jobs (`*_async` twins + `amicus_job_*`)
   AND the spec-native tasks extension (`@mcp.tool(task=True)`) on the sync paid tools.
3. **All three backends ship in v1.** The three repos enter maintenance at parity.
4. **Per-backend capability flags** via `BackendContract.supported_features`. Claude
   stays review-only; `adversarial_review` is a feature-gated verb (Claude-only in v1).
5. **Agent-friendliness is a design input**, not a review pass: every checklist section
   gets an answer below, cited by rule id.
6. **Implementable by Opus/Sonnet agents.** One executable plan per milestone (Part 2).

### Review record

Codex reviewed rev 1 adversarially (xhigh, 2026-09-04, job
`78298cece11541c2826a440f2743f77c`): 12 findings, 5 blockers. Six load-bearing claims
were verified against source before adoption; all held. Rev 2 absorbs every finding:

- pontonier 0.9.0 is a **prerequisite milestone (M-1)** with additive seams.
- An **outcome-inspection step** runs after every completed process, before `finalize`,
  because Claude reports errors in a zero-exit JSON envelope.
- The Kimi adapter is **fixed in the port** (last message + sanitizer before truncation).
- `backend_options` is a **closed superset object** for first-call correctness.
- Repair rules are **backend-overridable**; `timeout` is not retryable for Claude.
- Workspace resolution keeps **handshake-era roots** and never silently falls back to cwd.
- The tasks spike moves to **M0**, with a persisted task-id → job-id mapping.
- The tools/list target is **measured in M0 on all 18 real schemas**, not asserted.
- Deprecating the siblings requires **sibling-hot-path result differentials** and all
  three live gates enforced in publish.

### Verified constraints

- **FastMCP 4.0.0** (2026-08-31; 4.0.2 current) targets MCP **2026-07-28** on MCP SDK
  v2 (`mcp` 2.1.1) and negotiates the legacy 2025-11-25 handshake for older clients.
  **Claude Code and Codex CLI both still negotiate the handshake era**, and Claude Code
  advertises roots (codex-in-claude ADR 0004, lines 212-225). Stateless by default on
  modern connections; `server/discover`; roots/sampling/logging deprecated;
  `ctx.elicit()` raises on modern connections. Tasks: `task=True` requires
  `io.modelcontextprotocol/tasks` registered via `add_extension` on the root server;
  `fastmcp[tasks]` is not installed in any sibling venv; **default task TTL is 60 s**
  (`fastmcp/utilities/tasks.py:25`). `Context` and `report_progress` work inside
  background execution. `import_server` gone; `exclude_args` gone; snake_case fields;
  `mcp_camelcase_compat=False` in tests.
- **codex-in-claude already runs FastMCP 4 / MCP 2.1.1** and pins `fastmcp>=4.0,<4.1`,
  `mcp>=2.1,<2.2`. Its `tools/list` is 97,398 bytes for 17 tools with a 97,500-byte
  ceiling (`tests/test_wire_size.py:201-215`). Its consult/review advertise
  `destructiveHint: false`; claude-in-codex's paid tools advertise `true`.
- **pontonier** depends only on anyio; no MCP wiring; does not run the subprocess; does
  not serialize error envelopes; ships no job worker; its shared repair rules mark
  `timeout` and `nonzero_exit` temporary (`conventions/envelope.py:269-280`). Adapter
  gaps confirmed in source:
  - `KimiBackend.classify_failure` (`moonbridge/backend.py:178-196`) omits
    `last_message` and `sanitize`; `kimi.classify_failure` uses `last_message` for
    auth/rate/model detection and **sanitizes before a 300-char truncation**
    (`kimi.py:529-549`). `RunRequest.sanitize_aliases` already exists. `KimiBackend.finalize`
    and `CodexBackend.finalize` drop `cached_input_tokens`.
  - `ClaudeBackend.finalize` (`claude-in-codex/backend.py:163-202`) never checks
    `is_error`/`subtype`; production `normalize.py:527` treats those as failure on exit 0.
    `ClassifiedFailure` cannot carry `repair`/`details`/`retryable` (background: briandconnelly/claude-in-codex#145).
    Claude marks `timeout` non-retryable (`claude.py:303-313`) and distinguishes
    `claude_auth_required`/`api_key_missing`/`api_key_invalid`.
- Conventions inherited from the siblings: uv, ruff, ty, hatchling, MIT, conventional
  commits, draft PRs, `>=3.11` (documented SPEC 0 carve-out), 95% branch coverage,
  `prek`, `CLAUDE.md` = `@AGENTS.md`, release lockstep, FINGERPRINT bump + digest re-pin
  in the same PR, one sentence per line in markdown, ADRs in `docs/adr/`, Claude's
  non-skipping live release gate, Kimi's captured help/signature evidence rule.
- **Open item before PyPI publish:** trademark clearance for "amicus".

## Reuse inventory

| Need | Reuse from | Notes |
|---|---|---|
| Jobs, idempotency, worktrees, diff gathering, redaction, runtime, workspace resolution | `pontonier.core.*` | wholesale |
| Backend protocol types, shared classifier | `pontonier.backend.*` | frozen; additive only (M-1) |
| Error taxonomy + repair symbols, prompt framings, annotation builders, `HelpProbe`, fingerprint check | `pontonier.conventions.*` | vocabulary, not wiring; repair rules are defaults |
| Surface honesty, conformance (`check_contract` AND `check_backend`), pair parity | `pontonier.testing.*` | issue #15: a clean result is weak evidence |
| Codex adapter, CLI contract, argv builder, normalize, models cache, binary resolver, field policy | `codex-in-claude/src/codex_in_claude/{backend,cli_contract,codex,normalize,codex_models,binpath,binresolve,field_policy}.py` | → `amicus/backends/codex/` |
| Kimi adapter, CLI contract, handshake + read-only agent profile | `moonbridge/src/moonbridge/{backend,cli_contract,kimi,normalize,kimi_models}.py` | → `amicus/backends/kimi/`; `runspace.py` becomes a strategy |
| Claude adapter, CLI contract, config-mode/access flags, envelope normalize, auth probe, critic prompt | `claude-in-codex/src/claude_in_codex/{backend,cli_contract,claude,config,normalize,claude_models}.py` | → `amicus/backends/claude/`; `normalize_envelope` failure branch becomes the outcome inspector |
| Middlewares, guards, capability suppression, `main()`, param aliases | `codex-in-claude/server.py:300-782, 1473-1558` | plus claude-in-codex `_repair_action` (`server.py:490-621`) |
| Sync-through-detached-job lifecycle, delivery chokepoint | `codex-in-claude/server.py:3624-4143, 4709-5187` | |
| Worker, cleanup manifest, activity recorder; stdin prompt transport | `codex-in-claude/_worker.py`, `claude-in-codex/_job_worker.py` | |
| Coverage, finalize, gitdiff error mapping, worktree lifecycle | `codex-in-claude/orchestration.py`, `delegate.py:108-190`, `moonbridge/runspace.py:94-190` | |
| Manifest, wire-shape, result-format snapshots; wire-size ratchet | `codex-in-claude/{manifest,wire_shape_snapshot,result_format_snapshot}.py`, `tests/test_wire_size.py` | |
| Fingerprint digest triple, discovery-cost ratchet | `claude-in-codex/tests/{test_fingerprint,test_discovery_cost}.py` | |
| Roots resolution incl. handshake-era probe | `codex-in-claude/server.py` `_roots_from_ctx` + ADR 0004 D5; `claude-in-codex/server.py:1061-1139` | |
| Plugin manifests (incl. `.mcp.json` `env_vars`), skills, commands, CI, prek, check scripts | `codex-in-claude/.claude-plugin`, `moonbridge/.codex-plugin`, `claude-in-codex/.mcp.json`, `*/scripts/`, `*/.github/workflows/` | |
| Dev skills | `~/projects/skills/{agent-friendly-mcp,agent-friendly-github,agent-friendly-docs,separating-context-from-constraints}` | vendor the canonical copies into `.agents/skills/` |

## Architecture

### Package layout (`src/amicus/`)

```
server.py            create_app(settings, registry) -> FastMCP; main()
middleware.py        InputSchemaDialect, SemanticError, ValidationEnvelope, ResourceError
plugin.py            BackendPlugin + OptionSpec + capability Protocols (the plugin API)
registry.py          BackendRegistry: in-tree factories + entry points; never raises on a bad backend
request.py           RunSpec: the one serializable description of a paid run (incl. resolved host identity)
errors.py            render_failure(): backend-aware envelope rendering; generalize()
manifest.py, wire_shape_snapshot.py, result_format_snapshot.py   (ports)
_worker.py           python -m amicus._worker <job_dir>
config/              settings() (AMICUS_*), envspec.py (EnvVar/EnvNamespace, legacy shim, placeholder check)
schemas/             codes.py, envelope.py (Meta, ErrorInfo, Repair, ErrorResult), results.py,
                     params.py (Annotated aliases + ParamContract registry + verb×backend matrix),
                     options.py (closed BackendOptions model), fingerprint.py, field_policy.py
tools/               __init__.py register_all() in a FIXED order; _guard.py; _resolve.py;
                     consult.py, review.py, delegate.py, dry_run.py, discovery.py, jobs.py, resources.py
orchestration/       run.py (THE loop), isolation.py (DirectSite | WorktreeSite), review.py,
                     finalize.py, prompts.py (framing incl. host identity)
jobs/                lifecycle.py (start_job, run_sync, await_job_result, idempotency, task↔job map),
                     delivery.py
backends/            __init__.py IN_TREE lazy factories; codex/, kimi/, claude/ each with
                     __init__.plugin(), contract.py, adapter.py, cli.py, normalize.py, models.py,
                     status.py, options.py, config.py (claude adds adversarial.py)
```

Import rules, enforced with import-linter: `backends/*` may import `amicus.plugin`,
`amicus.config.envspec`, `amicus.schemas.codes` and pontonier, never
`tools`/`server`/`orchestration`; `orchestration`, `jobs`, `_worker` never import
`server` or `tools`. The worktree prefix `amicus-wt-` is orchestration policy set by
`isolation.py`, not a plugin choice (JobStore has one `cleanup_prefix`).

### Tool surface (18 tools, deterministic order)

Paid, sync (`task=True` when tasks enabled): `amicus_consult`, `amicus_review_changes`,
`amicus_delegate` (feature `delegate`), `amicus_adversarial_review` (feature
`adversarial_review`). Async twins: the four `_async` variants (add `idempotency_key`,
drop `timeout_seconds`/`detail`). Free: `amicus_dry_run`, `amicus_delegate_dry_run`,
`amicus_backends` (catalog + readiness probe + option applicability + legacy-env
warnings; optional `backend` filter; replaces per-backend `*_status`),
`amicus_models(backend)`, `amicus_capabilities` (error catalog, schemas on request,
fingerprint + surface digest, annotation policy). Jobs: `amicus_job_status`,
`amicus_job_result`, `amicus_job_consume_result`, `amicus_job_cancel`, `amicus_job_list`
(all backends; `backend` and `task_id` filters). Codex `transfer` deferred.

**Verb × backend parameter matrix** (`schemas/params.py`, written and tested before any
schema):

| Parameter | consult | review_changes | adversarial_review | delegate |
|---|---|---|---|---|
| `backend` (required enum), `workspace_root`, `model`, `reasoning_effort`, `timeout_seconds`, `detail`, `idempotency_key` (async only) | ✓ | ✓ | ✓ | ✓ |
| `extra_context` | ✓ | ✓ | ✓ | – |
| `instructions_append` (codex `developer_instructions`, claude `system_prompt_append`) | ✓ | ✓ | **–** (fixed critic stance is the product) | **–** (edits files) |
| `scope`, `base`, `commit`, `paths`, `untracked` | – | ✓ | ✓ (optional attached diff, as today) | – |
| `focus` | – | ✓ (as today) | ✓ | – |
| `target`, `evidence` | – | – | ✓ | – |
| `task` | – | – | – | ✓ |
| `backend_options` | ✓ | ✓ | ✓ | ✓ |

**`backend_options` is a closed superset object** (`schemas/options.py`,
`additionalProperties: false`): optional `isolation` (union enum), `config_mode`,
`access`, `max_budget_usd` (bounds), each described with which backends accept it;
applicability validated in `tools/_resolve.py` with `invalid_arguments` naming
`backend_options.<key>` and `allowed_values` for that backend; resolved values echoed by
`amicus_dry_run`. A new backend option changes the schema and bumps the fingerprint
deliberately. `OptionSpec` carries defaults and applicability, not the schema. ADR 0002.

Resources: `amicus://capabilities`, `amicus://backends/{backend}` (template +
completion), `amicus://error-envelope`, `amicus://result-meta`, `amicus://params`,
`amicus://models/{backend}`. No prompts; prompts capability suppressed.

### Plugin interface (`plugin.py`)

```python
PLUGIN_API_VERSION = 1; ENTRY_POINT_GROUP = "amicus.backends"
@dataclass(frozen=True) class OptionSpec: name, maps_to (RunRequest field), applies_to, default
@dataclass(frozen=True) class BackendPlugin:
    contract: BackendContract; backend: AgentBackend           # pontonier: facts + behavior
    options: tuple[OptionSpec, ...]; status: StatusProbe; models: ModelCatalogReader
    binary: BinaryResolver; help_probe: HelpProbe; vocabulary: BackendErrorVocabulary
    env: EnvNamespace; effects: AnnotationEffects
    repair_overrides: Mapping[str, RepairRule] = {}
    framing: FramingHook | None = None; local_codes: Mapping[str, RepairRule] = {}
    api_version: int = PLUGIN_API_VERSION
```

Outcome inspection is a pontonier capability on the `backend` object itself
(`OutcomeInspector`, Part 3 Task 3), so the plugin carries nothing extra for it.
`BackendRegistry.load()` reads `backends.IN_TREE` then
`importlib.metadata.entry_points(group="amicus.backends")`; in-tree ids are reserved; a
backend failing import, `api_version`, `conformance.check_contract` **and**
`conformance.check_backend`, or worktree-config validation is recorded in
`amicus_backends.unavailable` and never blocks startup.

### Orchestration: one loop, isolation as a strategy

`orchestration/run.py::run_request(spec, plugin, ...) -> dict`: gather diff for review
kinds (zero spend; `not_run` on empty scope) → compose framing → select site
(`WorktreeSite` for `delegate` and `IsolationPolicy.WORKTREE_ALL_TIERS`, else
`DirectSite`) → build `RunRequest` (with `sanitize_aliases`) → `validate_request` →
resolve binary → `async with backend.prepare()`: `runtime.run_async(...)`, read
`artifact_paths` inside the context → orphan sweep if needed →
`pontonier.backend.protocol.inspect_outcome(backend, outcome, request)` on every
completed process → `classify_failure` on nonzero exit / timeout / spawn failure /
inspection failure, else `finalize` → capture delegate diff inside the site →
`finalize.for_kind`. Loop-level `sanitize_echo_prose` is defense in depth only.

Adapter fixes made during the port, pinned by differential tests against each sibling's
current hot path: Kimi derives `last_message` from `artifact_texts["answer"]` / the
stream and passes a sanitizer built from `request.sanitize_aliases` into
`kimi.classify_failure`; Claude implements `OutcomeInspector` from
`normalize.normalize_envelope`'s failure branch; all three carry cache token fields.

### Jobs and tasks

One `JobStore` under `AMICUS_STATE_DIR`; `extra.backend` tags every record; the
idempotency arg hash includes `backend`. `RunSpec` splits into a public half
(`spec.json`) and an input half streamed over `stdin_text`, so amicus itself never
persists the prompt in the job record or on the worker's argv; each backend's own
carriers (Kimi handshake file, Codex/Claude system-prompt argv) are disclosed per
backend. `_worker.py` re-resolves the plugin by id and runs the same loop. Sync tools
keep codex-in-claude's model; `meta.job_id` is always stamped. `task=True` wraps the
same coroutine; the job store persists `task_id → job_id` at task creation,
`amicus_job_list` accepts a `task_id` filter, cancellation propagation is explicit
(a tasked call is always unkeyed, so `tasks/cancel` always cancels the job, per ADR
0011's amendment), legacy fallback is claimed only after a host capture. Gated by
`AMICUS_TASKS`. ADR 0004.

### Error envelope and codes

Adopt codex-in-claude's `ErrorInfo` (`code`, `message`, `temporary`, `retry_after_ms`
always present, single `repair {next_step, tool, arguments, alternative}`,
`details{field|fields, reason, allowed_values}`, `invalid_arguments[]`, `request_id`)
plus `backend: str | null`. `details.value` only for known-safe values, policy
disclosed on `amicus://error-envelope`. Rendering is backend-aware
(`errors.render_failure(plugin, failure, meta)`): pontonier `repair_rules()` are
defaults, `plugin.repair_overrides` win per code, backend-local codes are preserved,
`generalize()` rewrites only `<id>_not_found|_auth_required|_auth_indeterminate|_rate_limited`
→ `backend_*`, and machine fields the backend computed travel on the widened
`ClassifiedFailure` (M-1). Resource failures carry the same envelope in JSON-RPC
`error.data` with `machine_code`/`human_message`. Backend-specific meta lives under
`meta.backend_details`. ADR 0005.

### Annotations, lifecycle metadata, capability summary, workspace

- Worst *enabled* backend annotations (`[3.ap-mode-annotations]`); Claude enabled ⇒
  paid tools `destructiveHint: true`; codex/kimi-only profiles `false`; per-backend
  `effects` published; documented as a deliberate UX regression; host approval
  behaviour captured. Job reads `readOnlyHint: true` under the observable-scope reading.
  ADR 0001.
- `_meta["dev.bconnelly.amicus/lifecycle"]` on every tool and resource.
- Fingerprint = static `amicus/0.1/schema-N` + `surface_digest` (sha256 of the tool,
  resource and template records plus `instructions` — not the built manifest, whose
  stronger hash is pinned only in tests). ADR 0006.
- SEP-2549 cache hints: the four list methods and `server/discover` carry
  `ttlMs: 300000`/`cacheScope: private`; `resources/read` carries none, because the
  `backends`/`models` templates report live state. Both eras report
  `listChanged: false`. ADR 0018.
- `CAPABILITY_SUMMARY` is rules-then-context, serves as `instructions` and
  `amicus://capabilities`: does/does-not, spec target, error carriers, task `completed`
  is a delivery statement, when a task may be returned, `amicus_job_*` fallback and
  task→job recovery, handle TTLs, workspace resolution, per-backend egress and carriers.
- Workspace: explicit `workspace_root` → handshake-era file roots (ADR 0004 D5) →
  structured `invalid_workspace_root`. Server cwd only under an operator opt-in that
  discloses the path. ADR 0003.
- Host identity: normalized handshake-era `clientInfo.name`, `AMICUS_HOST_NAME`
  override, else neutral framing; persisted in `RunSpec`.
- tools/list budget measured in M0 on all 18 real schemas per profile; `ttlMs`/`cacheScope`
  populated deliberately.

### Config

`AMICUS_*` global and `AMICUS_<ID>_*` per-backend namespaces declared by `EnvNamespace`.
Legacy shim: legacy name read only when the amicus name is unset; conflict is an error;
every legacy read is a warning in `amicus_backends` with a removal version. `.mcp.json`
`env_vars` generated from declarations plus vendor auth variables. `docs/MIGRATION.md`
asserted equal to declarations by a test. `${VAR}` placeholder check kept.

### Testing architecture

Manifest snapshot; FINGERPRINT + `EXPECTED_CONTRACT_DIGEST`; wire-shape and
result-format snapshots via the real delivery chokepoint; tools/list ratchet per profile;
pair parity; annotation conformance per profile; `forced_error` per tool; per-backend
argv differentials; **sibling-hot-path result differentials** (raw `CommandRun`/events
fixtures → amicus envelope vs the sibling's normalized envelope, for success, zero-exit
error, auth, rate-limit, invalid-model, timeout, malformed JSON, cache counters);
`FakePlugin` via a test-only entry point; `check_contract` + `check_backend` per
plugin; live gates `integration_{codex,kimi,claude}` with `AMICUS_REQUIRE_LIVE`,
enforced in publish. Surface honesty scoped per backend plus a shared union. Eval
fixtures in `skills/collaborating-with-amicus/tests/`.

## Milestones

| M | Scope | Gate |
|---|---|---|
| M-1 | **pontonier 0.9.0**, additive only (Part 3): `Usage.cached_input_tokens` + `Usage.cache_creation_input_tokens`; `RepairHint` + defaulted `ClassifiedFailure.retryable/details/repair` (closes pontonier #24); optional `OutcomeInspector` capability + `inspect_outcome()` helper; `check_backend` probes inspector tolerance; `scripts/check_consumers.sh` reverse-dependency check | `./scripts/check.sh` green; `scripts/check_consumers.sh` green for all three siblings; release PR opened; **human publishes 0.9.0** |
| M0 | `~/projects/amicus` scaffold (tooling copied from codex-in-claude, ADR skeleton, vendored dev skills, spec copied to `docs/superpowers/specs/`); `plugin.py`, `registry.py`, `schemas/` incl. the parameter matrix and closed `BackendOptions`, `errors.py`, `middleware.py`, `config/`, `server.create_app`, discovery tools + resources, `FakePlugin`; **all 18 tools registered schema-only**; **tasks spike** with real `fastmcp[tasks]` | gate green; manifest snapshot + digest; discovery cost measured per profile, ratchet set; tasks spike report; `ttlMs`/`cacheScope` pinned |
| M1 | Codex end-to-end sync: `backends/codex/*`, `orchestration/*`, `jobs/lifecycle.py`, `_worker.py`, roots fallback, consult/review/delegate/dry-runs | argv + hot-path result differentials vs codex-in-claude; `integration_codex`; wire-shape + result-format fixtures |
| M2 | Jobs surface: `_async` twins, `amicus_job_*`, idempotency, task↔job mapping, delivery | keyed replay, cancel (keyed/unkeyed), hard-kill cleanup, restart-survival, task-id lookup |
| M3 | Kimi with adapter fixes, `WorktreeSite` all tiers, orphan sweep, pre-spend effort validation | hot-path differential vs moonbridge incl. sanitize-before-truncate; `check_backend` positive and perturbed; `integration_kimi` |
| M4 | Claude: outcome inspector, options, `amicus_adversarial_review(_async)`, repair overrides, framing hook | hot-path differential incl. zero-exit `is_error`; upstream golden envelope; feature gating; `integration_claude` non-skipping |
| M5 | `task=True` on the four paid sync tools behind `AMICUS_TASKS`; capability-summary wording; host captures | in-memory task-client tests; both host captures |
| M6 | Packaging, docs, eval fixtures, migration doc, annotation-friction capture | install smoke for the shipped command line on both hosts, Codex's own plugin loader unexercised (`docs/host-captures/install-smoke/codex/`); FakePlugin loads as a wheel via the entry point, but `config._profile` and the closed `BackendParam` mean it can be neither enabled nor called (ADR 0012); agent-friendly-mcp review walk |
| M7 | Release + deprecate siblings | AGENTS.md rules 20-21 (local pre-tag live-gate evidence, tag-protecting ruleset) and `docs/RELEASING.md`'s release procedure, since hosted CI has no authenticated backends to enforce a live gate itself; sibling differentials green; release lockstep CI |

## Verification (all milestones)

- Gate: `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest` at ≥95% branch coverage, plus `prek run --all-files` (pontonier: `./scripts/check.sh`).
- Negative-result rule: before trusting a clean gate, perturb the surface and confirm the gate fails.
- Snapshot or fingerprint regeneration is an isolated commit with per-diff justification.
- Paid smoke per backend milestone; end-to-end install into Claude Code and Codex with cold-start scenarios.

---
