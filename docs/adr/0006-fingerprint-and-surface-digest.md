# ADR 0006: Fingerprint plus surface digest; cache hints left at the SDK default

**Status:** Accepted (2026-09-04, M0)

## Context

The siblings pin a hand-bumped `FINGERPRINT` and guard it with a committed manifest snapshot.
A hand-bumped string cannot prove the surface changed; a digest cannot be read by a human.

## Decision

`amicus_capabilities` reports both: the static `FINGERPRINT` (`amicus/0.1/schema-N`, bumped by hand on any covered change) and `surface_digest`, the sha256 of the canonical manifest JSON computed from the live app.
The committed snapshot (`tests/fixtures/manifest_snapshot.<profile>.json`) and pinned hash guard both per profile.
`ttlMs`/`cacheScope` stay at the SDK default (`ttlMs: 0`, `cacheScope: "private"`): fastmcp applies one server-wide hint to every list and read result, and `amicus://models/{backend}` is volatile, so a positive TTL would be wrong for it.
The manifest pins the emitted values so a framework change is reviewed, not silent.

## Consequences

- `surface_digest` and `fingerprint` are excluded from the manifest capture (self-referential), as are release-variable versions.
- Revisit the TTL when fastmcp offers per-resource hints.
