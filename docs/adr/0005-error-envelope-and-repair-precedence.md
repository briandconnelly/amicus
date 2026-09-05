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
