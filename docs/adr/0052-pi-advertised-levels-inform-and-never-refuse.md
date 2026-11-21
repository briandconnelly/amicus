# ADR 0052: pi's advertised reasoning levels inform and never refuse

**Status:** Accepted (2026-11-21)

Supersedes only the "Reasoning efforts are not narrowed" paragraph of [ADR 0051](0051-pi-catalog-prices-enrich-the-table-and-never-replace-it.md), and extends its "Only named fields are read" list; the pre-spend check of [ADR 0047](0047-pi-backend-validates-an-exact-model-and-fails-closed.md) is unchanged.

## Context

`amicus_models(backend="pi")` listed pi's whole effort vocabulary for every thinking model, because the `pi --list-models` table says only whether a model thinks (issue #559).
Since ADR 0051, `PiModels.read` also reads pi's RPC `get_available_models` reply, whose rows carry `reasoning` and, for most reasoning models, `thinkingLevelMap`, an object from pi's level names to the provider value sent for each.
So amicus held the information to say which levels a model maps, and did not publish it.

The listed set is not only advisory.
`PiBackend.validate_request` refuses, before any spend, an effort outside the row's `supported_reasoning_efforts`, and `invalid_reasoning_effort` repairs with that list.
ADR 0047 lets pi clamp an effort the model does not map, and warns when the reported level differs.
`PiModels.lookup`, which the check uses, reads the targeted table search and never the RPC reply.

## Decision

**The levels are advisory metadata only, in a separate field.**
`advertised_reasoning_efforts` on `ModelEntry` and on the published `ModelInfo` carries them, and nothing new is refused pre-spend.
`supported_reasoning_efforts` keeps its values; for pi it is redescribed as the vocabulary amicus accepts before spending.
`PiModels.lookup` and `PiBackend.validate_request` are unchanged and never read the RPC reply.

**The reading rule is pi's own.**
It mirrors `getSupportedThinkingLevels` in pi 1.6.0's `pi-ai/dist/models.js`, read on the maintainer's machine.
An explicit `null` marks a level unsupported.
A level the map omits is supported from `off` through `high` and unsupported for `xhigh` and `max`.
Any other mapped value marks the level supported.
A row with no map at all reads as an empty map.
A `thinkingLevelMap` that is present and not an object, `null` included, gives `null`, which is unknown.

**The table stays the authority on whether a model thinks.**
A `thinking: no` table row advertises `["off"]`, with or without the RPC reply.
A `thinking: yes` row takes the RPC row's levels only when that row's `reasoning` is literally `true`, and is `null` otherwise, including when the reply does not describe the row or describes it twice.

**`[]` and `null` are never merged.**
`[]` is a known empty set, a model whose map marks every level unsupported, and `null` is unknown.

**The "may run another" caveat stays.**
pi's clamp, `clampThinkingLevel`, searches upward from the requested level and then downward, so the level that runs need not be the nearest one.
The rule above is pi's source, not an observed provider call, so the field's description says pi can run another level and that the result warns when a different level is reported.
Codex and Claude rows carry `null`.

## Alternatives rejected

Narrowing `supported_reasoning_efforts` in place was rejected, because that list is what `validate_request` enforces and what `invalid_reasoning_effort` repairs with, so a narrowed list would either disagree with the check or change it.
Enforcing the map pre-spend was rejected, because it would turn calls that run today, clamped and warned about, into refusals, which is a breaking change, and because `lookup` would have to read the RPC reply and decide what an unavailable reply means.

## Consequences

The field is **Surface**: the published schema gains a key and the fingerprint moves, and no call that ran before is refused.
The RPC parser reads two more named fields, `reasoning` and `thinkingLevelMap`, and nothing else new; the map's provider values are not kept.
A pi release that changed the map's meaning would make the field wrong without failing anything, so it is a snapshot and its description says so.
The skill routes an effort from `advertised_reasoning_efforts` when it is a list, passes none when that list is empty, and falls back to `supported_reasoning_efforts` when it is `null`.
