# ADR 0010: What the M4 Claude Code port kept, changed, and dropped

**Status:** Accepted (2026-09-07, M4)

## Context

M4 ports claude-in-codex's Claude Code adapter, CLI contract, config-mode and access flags, envelope normalizer, classifier and auth probe behind the M0 plugin seam, onto the M1 orchestration loop, and makes `amicus_adversarial_review(_async)` real.
Claude differs from Codex and Kimi in three ways that shape every decision below: its errors ride a zero-exit JSON envelope, read-only is a tool allowlist rather than a sandbox, and its login modes must not see a direct API key.
The maintainer approved decisions 1–4 in the M4 planning session.

## Decisions

- The live gate ran once, at the end of the milestone, under the maintainer's authorization; `config_mode=bare` was not live-tested because no `ANTHROPIC_API_KEY` is set on the maintainer's machine.
- `instructions_append` rides the stdin prompt as a leading caller-instructions section (`schemas.instructions.compose`), never argv; only the constant, host-neutral critic guardrails ride `--append-system-prompt`.
  claude-in-codex folded the caller's persona into the argv system prompt; amicus deviates so AGENTS.md rule 18 holds literally and argv is constant per configuration.
- Four Claude-local codes joined the catalog (`budget_exceeded`, `claude_permission_error`, `api_key_invalid`, `api_key_missing`) with repair rules in `errors._LOCAL_RULES` and in the plugin's `local_codes`; rate limits are minted `claude_rate_limited` and generalized to `backend_rate_limited` where the sibling returned a retryable `nonzero_exit`.
  `FINGERPRINT` moved to `amicus/0.1/schema-4`.
- An attached `scope` that gathers nothing returns `review_status=not_run` with zero spend; `AdversarialReviewResult` gained `review_status` and `context_summary`, and `RESULT_FORMAT` moved to `2` (rule 11), although no release before M4 ever stored an adversarial result.
- The framing hook is the user-turn seam: `orchestration.prompts.framing_for` builds the shared base framing and hands it to `plugin.framing.frame(verb, framing, host_name)`; Claude's hook prepends the sibling's independent-critic stance, host-named, to consult, review and adversarial framings.
  The system turn stays host-neutral because an adapter is built once per process while the host is per-connection.
- The adversarial framing, prompt and output schema live in `orchestration/prompts.py` (the verb is amicus's, not Claude's); the output schema is the review schema and the result shape is the review shape.
- The zero-exit envelope is an outcome inspection: `ClaudeBackend.inspect_outcome` returns `invalid_json` for a non-JSON zero-exit stdout, classifies an `is_error`/non-success envelope through the same classifier the process-failure path uses, and returns `claude_permission_error` for denials with no answer.
- `finalize` returns the workspace hook warning as `ExecResult.warnings`, and `orchestration.finalize.apply_exec` copies backend warnings onto `meta.security_warnings` (a loop change every backend may use).
- Timeout is the first `repair_overrides` entry (`start_new_job`, not temporary); the classifier marks the failure `retryable=False` too.
- Pre-spend refusals in `validate_request`: effort outside the enumerated levels, `config_mode`/`access` outside the vocabulary, budget outside 0.01–5.00, `bare` without `ANTHROPIC_API_KEY` (`api_key_missing`), any `extra_args`, and the shared `instructions_append` rules for consult and review only.
- `backend_options.max_budget_usd` is bounded 0.01–5.00 on the wire (the sibling's ceiling) and refused pre-spend outside it; the sibling's configured/effective budget meta is not carried.
- Names: `AMICUS_CLAUDE_{BIN,CONFIG_MODE,ACCESS,MODEL,REASONING_EFFORT,MAX_BUDGET_USD,SUPPORTED_MAJORS}` with `CLAUDE_IN_CODEX_` twins for all but `BIN`; defaults inherit, toolless, xhigh, 1.00, {2}; no extra-args variable.
- Claude Code 2.1.263 is supported on the captured evidence in `docs/claude-help/2.1.263/`; the sibling's recorded real envelope is `tests/fixtures/claude_golden_envelope.json`.
- `FORBIDDEN_SURFACE_PHRASES` is re-derived without the sibling's `kimi`/`moonbridge` canaries.
- Not ported: the argv persona carrier, `meta.cost_usd` (cost rides `meta.usage.cost_usd`), `raw_response.model` from `modelUsage`, `permission_denials` on meta, the sibling's output bounds and truncation block, the sibling's finding shape (`risk`/`recommendation`; amicus asks for `evidence`/`suggestion`), the per-tool timeout/input/git/job env knobs (global `AMICUS_*` twins exist), and `empty_response_detection`.
- Differentials against claude-in-codex (`tests/fixtures/claude_differentials.json`, captured at the sibling commit the fixture names) compare a projection: argv with the system-prompt value masked, the guardrail text with `Codex` neutralized, envelope codes after generalization, `temporary`, `retry_after_ms`, usage on amicus's field names, summary/verdict/confidence, and two leak checks; known deviations are keyed by case in `tests/test_claude_result_differential.py`.

## Consequences

- Every backend now runs through the framing hook and the backend-warning seam; Codex and Kimi declare neither, so their prompts and metas are unchanged.
- A Claude release that changes a flag shows up as `cli_contract_changed` at run time and as a failed evidence test once the new help is captured under `docs/claude-help/<version>/`.
- A stored M3-era job result is delivered as `job_result_incompatible` after this upgrade (`RESULT_FORMAT` 1 → 2); no released amicus wrote one.
- Claude enabled ⇒ every paid tool advertises `destructiveHint: true` (ADR 0001); the codex-kimi profile keeps `false`.
