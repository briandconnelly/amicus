# ADR 0002: `backend_options` is a closed superset object

**Status:** Accepted (2026-09-04, M0)

## Context

Codex, Kimi and Claude each have backend-specific knobs (`isolation`, `config_mode`, `access`, `max_budget_usd`).
An open `dict` parameter would let a misspelled key pass validation and silently reach a paid run.

## Decision

`backend_options` is one Pydantic model with `additionalProperties: false` whose fields are the union of every backend's options, each described with the backends that accept it and its allowed values.
Applicability is validated pre-spend in `amicus.tools._resolve`: a key or value the selected backend does not accept fails as `invalid_arguments` with `details.field = "backend_options.<key>"` and `allowed_values` for that backend.
`amicus_dry_run` and `amicus_delegate_dry_run` echo the resolved values.
Adding a backend option changes the schema and bumps the fingerprint deliberately.

## Consequences

- First-call correctness: an agent reads one closed schema and cannot send a key that is silently dropped.
- `OptionSpec` on the plugin carries defaults and applicability, not the schema; the schema is owned by `amicus.schemas.options`.
