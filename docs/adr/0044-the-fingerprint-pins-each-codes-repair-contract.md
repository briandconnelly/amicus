# ADR 0044: the fingerprint pins each code's repair contract

**Status:** Accepted (2026-09-25)

Extends [ADR 0006](0006-fingerprint-and-surface-digest.md), whose committed manifest snapshot this widens.

## Context

An error's `temporary` and `repair` tell an agent what to do next: retry the same call, or start new work with the named tool.
The fingerprint guard pinned the error-code list and the `RepairStep` enum, but not which step, tool or `temporary` each code carries (#252).
Commit `1149fd6` flipped `timeout` from `temporary: true` / `retry_after_delay` to `temporary: false` / `start_new_job` for every backend, and no snapshot moved: the full gate passed on it.
A change a caller branches on could ship with no acknowledged fingerprint move, which is the case rule 10 exists to prevent.

## Decision

**The manifest gains a `repair_rules` section, covered by a new `FINGERPRINT_COVERS` category of the same name.**
It holds `errors.repair_contract()` under `default`, the table used when no plugin is known, and `errors.repair_contract(plugin)` under each in-tree backend's id, because `local_codes` and `repair_overrides` are per plugin and `repair_table` applies them.
Each table is full rather than a delta from `default`, so a reader sees every code's effective rule without reconstructing it.
Every profile carries every in-tree backend: no table depends on which backends a profile enables, and a profile that dropped one would leave its rules unpinned in that snapshot.

**Each code is pinned as `make_error` renders it with no per-call override.**
That is `temporary`, and `repair` as `{next_step, tool, arguments}`, or `null` for a code in `NO_CORRECTIVE_CALL`, with `complete_lookup` applied for that plugin's backend id.
A test compares it with `make_error`'s envelope for every code with and without each in-tree plugin, so the pin cannot drift from what an agent receives.

**`alternative` is left out on purpose.**
It is prose an agent reads rather than a field it branches on, and pinning it would move the fingerprint on every rewording.
Prose that must name a particular tool is held by its own tests, such as `tests/test_surface_honesty.py`.

**What a single failure changes at render time is not in the pin.**
`render_failure` lets a failure's own `retryable` and repair win over the table, names the verb's `_async` twin on a sync timeout, and makes a keyed run's temporary timeout non-temporary (ADR 0039).
Those depend on the call rather than the code, so a static per-code table cannot enumerate them; their unit tests hold them.

**The manifest builds each in-tree plugin with an empty environ.**
`repair_table` reads the plugin's own `local_codes` and `repair_overrides`, so the pin reads the mappings the factory passes rather than module constants a factory might not use.
A factory resolves its binary on PATH, which reaches no table: the committed snapshot is rendered outside pytest, where the real CLIs may be installed, and the golden test compares it under the conftest guard, where none is reachable.

## Consequences

- A change to any code's `temporary`, `next_step`, `tool` or lookup arguments, for any in-tree backend, fails `test_manifest_matches_golden` until `FINGERPRINT` moves and the snapshots are regenerated.
- The `fingerprint_covers` list on `amicus_capabilities` gains `repair_rules`, which is itself a fingerprint move (schema-50).
- `surface_digest` does not move: it hashes the tool, resource and template records and the instructions text, and none of them changed.
- A third-party plugin's table is not pinned; only in-tree backends are, as with every other manifest section.
