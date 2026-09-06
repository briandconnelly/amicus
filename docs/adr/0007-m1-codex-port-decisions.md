# ADR 0007: What the M1 Codex port kept, changed, and dropped

**Status:** Accepted (2026-09-05, M1)

## Context

M1 ports codex-in-claude's adapter, CLI contract, orchestration and job lifecycle behind the M0 plugin seam.
The sibling's surface and amicus's M0 surface disagree in a few places; each is decided here rather than left implicit.

## Decisions

- No `coverage` object on `ReviewResult`: the coverage rule survives (a model `pass` over a partially reviewed diff is delivered as `verdict: unknown`, `confidence: low`, with a summary caveat), and `meta.truncated`, `meta.truncation_hint`, `meta.redacted_paths` carry the machine signal.
- Review scope (`scope`, `base`, `commit`, `paths`) is not echoed in `Meta`; it lives in the job's public `spec.json` for the M2 lifecycle tools and is echoed by `amicus_dry_run`.
- The developer-turn framing carried in Codex's `-c developer_instructions` is host-neutral ("another coding agent"); the user-turn framing names the host from `clientInfo.name` or `AMICUS_HOST_NAME`, falling back to "Caller".
- `Meta.instructions_append` is a `{sha256, bytes}` fingerprint, never the text.
- Backend-specific run facts ride `meta.backend_details` (`{"isolation": ...}` for Codex).
- The per-run `codex --version` provenance stamp is not ported; `amicus_backends` reports the installed version.
- `transfer`, the app-server and quota reads are not ported; Codex declares `{"delegate", "usage_accounting"}`.
- `user_config_rejected` is a Codex-local code in the catalog (fingerprint schema-2), preserved verbatim and never generalized.
- Prompt inputs never touch disk or argv on the amicus side: `RunSpec.public()` is `spec.json`; the input half streams over the worker's stdin. Codex's own carriers (stdin prompt; `-c developer_instructions` on argv) are disclosed on `amicus_backends`.
- The worktree prefix `amicus-wt-` and the baseline identity `amicus <amicus@local>` are orchestration policy.
- `tests/test_codex_result_differential.py` carries `KNOWN_TEMPORARY_DEVIATIONS = {"nonzero_exit": (False, True)}`: for a plain non-zero exit the sibling marked the failure non-retryable while pontonier's default classification marks it retryable; amicus keeps pontonier's default and pins the difference until the sibling and pontonier agree.
- The effort-rejection check runs inside the CLI-drift gate (a rejected `reasoning_effort` is only reported as such when the CLI's help output still matches the pinned contract); `invalid_reasoning_effort` is the code amicus itself emits for it (`src/amicus/backends/codex/cli.py`), shared with the sibling.

## Consequences

- M3/M4 plugins reuse the loop unchanged; their adapter fixes are the only backend-specific work.
- The argv and result differentials in `tests/fixtures/codex_differentials.json` pin the port against the sibling at the recorded commit; re-capture when the sibling's hot path changes.

## Known upstream observation

pontonier 0.9.0's `JobStore` can lose a cancel's terminal status if another caller polls `status()`/`list_jobs()` on the same job during `cancel()`; amicus never polls and cancels one job concurrently, so it is not affected in M1.
