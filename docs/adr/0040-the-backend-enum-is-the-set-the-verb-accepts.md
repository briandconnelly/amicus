# ADR 0040: the backend enum is the set the verb accepts

**Status:** Accepted (2026-09-24)

## Context

Five tools published a `backend` enum of `codex | kimi | claude` while always rejecting one or two of them: delegate and its async and dry-run forms accept codex and kimi, and adversarial review and its async form accept claude (#246).
Only description prose carried the restriction; a schema-driven caller, or a client that generates bindings from `inputSchema`, had no signal, and the wrong pick failed after resolution as `feature_unsupported` with a repair that looked up the backend that had just failed.
`[3.strict-types]` puts a fixed value set in the enum, and the server already knew the true sets in `amicus_capabilities.tool_details[].backends`.

## Decision

**Each paid verb's tools publish the enum of the backends that verb accepts.**
`schemas.codes.VERB_BACKENDS` is the table; `DelegateBackendParam` and `AdversarialBackendParam` are the narrowed `Literal`s, and `TOOL_DETAILS[...]["backends"]` derives from the same table, with a test holding the published enums equal to it.
The narrowing is in the Pydantic type, so the published enum, the boundary validation and `invalid_arguments.allowed_values` change together.
A one-value enum, adversarial review's `claude`, is published as `enum: ["claude"]` rather than JSON Schema `const`, so the published set and `invalid_arguments.allowed_values` read the same way on every tool.

**The enum narrows per verb, not per profile.**
A per-profile enum would make the profiles differ in more than annotations, which the manifest's byte-difference control pins, and the tool set is the same in every profile by design.
Every tool no enabled backend can serve stays listed.
The adversarial review description says so (its call is `backend_unavailable` unless `claude` is enabled); the delegate descriptions, already long, do not.

**`feature_unsupported` repairs to the unfiltered `amicus_backends` call.**
The code is now only a defensive check: it is returned if the named backend's declared features lack the verb, which no backend a tool's enum accepts does today.
A third-party backend cannot reach it either, because `config._profile` drops an id outside `BACKEND_IDS`, each tool's `backend` `Literal` rejects one, and the registry refuses an entry point that claims an in-tree id (`reserved_id`); such a call is `invalid_arguments`.
ADR 0021 forbids a repair whose `arguments` are not a complete call, and a correction that carries a prompt input cannot be echoed, so the repair lists every candidate rather than naming one.

## Consequences

- `amicus_delegate(backend="claude")` and its async and dry-run forms, and `amicus_adversarial_review(backend="codex"|"kimi")` and its async form, now fail at the boundary as `invalid_arguments` with `allowed_values`, where they failed after resolution as `feature_unsupported`: **Breaking**, since the code a caller read for that call changed.
- `amicus_models` and `amicus_backends` keep the whole set: they answer for any known backend.
- `FINGERPRINT` moves (with #245, to `schema-45`); `tools/list` grows by 134 bytes on every profile (`all`: 112683 to 112817), most of it the adversarial review description's clause that the tool stays listed in every profile: 27 bytes from the delegate tools dropping `claude` from their enum and rewording its description, and 107 bytes from the adversarial review tools narrowing to `claude` alone and gaining that description clause.
