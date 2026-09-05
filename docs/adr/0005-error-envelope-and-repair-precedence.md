# ADR 0005: One error envelope, backend-aware repair precedence

**Status:** Accepted (2026-09-04, M0)

## Context

pontonier owns the code taxonomy and default `RepairRule`s but not wire serialization.
claude-in-codex's `ErrorInfo` uses `retryable` plus a typed `action`; codex-in-claude and moonbridge use `temporary` plus a structured `repair` object.

## Decision

Adopt the codex-in-claude shape: `code`, `message`, `backend`, `temporary`, `retry_after_ms` (always present), one `repair {next_step, tool, arguments, alternative}`, `details {field|fields, reason, allowed_values}`, `invalid_arguments[]`, `request_id`.
`details.value` is emitted only for known-safe values; the policy is disclosed on `amicus://error-envelope`.
Rendering precedence: a plugin's `repair_overrides` win per code, then pontonier's `repair_rules()` defaults, then amicus-local rules; backend-local codes are preserved verbatim; `generalize()` rewrites only `<id>_not_found`, `<id>_auth_required`, `<id>_auth_indeterminate`, `<id>_rate_limited` to `backend_*` so the catalog stays closed while `error.backend` names the backend.
A non-`None` `ClassifiedFailure.retryable` overrides the rule's `temporary`.
Resource-read failures carry the same envelope in JSON-RPC `error.data` with `machine_code`/`human_message`.

## Consequences

- One serializer (`amicus.errors`) is the only producer of the wire shape.
- `RepairStep` is pontonier's `REPAIR_STEPS` vocabulary; a new symbol is added upstream, never invented here.

## Numeric code on the handshake era

amicus emits `-32002` for resource-not-found on a 2025-11-25 connection.
It emits `-32602` for the same failure on a 2026-07-28 connection.
This knowingly overrides the vendored checklist's `[6.jsonrpc-code-allocation]` rule, "never emit the retired -32002".
The override is for era fidelity, not oversight.
A handshake-era client — Claude Code and Codex CLI today — was built against the era that defines `-32002`, and matches on that numeric.
`error.data.machine_code` is the stable discriminator on both eras, so no client needs the numeric to classify the failure correctly.
Emitting the checklist-preferred `-32602` on a handshake-era connection would be spec-correct for 2026-07-28 and wrong for the client actually connected.
