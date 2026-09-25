# ADR 0041: static resource reads carry the catalog TTL

**Status:** Accepted (2026-09-25)

Amends [ADR 0018](0018-the-catalog-carries-a-ttl-and-resource-reads-do-not.md): its "resources/read carries no hint at all" clause is superseded; the rest stands.

## Context

ADR 0018 left `resources/read` unhinted because the SDK chooses a hint per method and two template reads report live install, auth and model-catalog state.
`amicus://error-envelope`, `amicus://result-meta` and `amicus://params` change only when the fingerprint moves, yet every read of them said `ttlMs: 0` while `resources/list` said `300000` (#250 item 2, `[8.cacheable-results]`).
The SDK applies a method hint only to the fields a handler did not set, so a hint can be stamped per URI on the read result; FastMCP 4.0.5 offers no per-resource hint of its own.

## Decision

**The three static bodies carry `CATALOG_CACHE_TTL_MS` on their read results, per URI.**
`server._install_static_read_ttl` re-registers the low-level `resources/read` handler with a wrapper that stamps the TTL and scope on those three URIs and passes every other result through.
`resources/read` stays out of the method hint map, so `amicus://capabilities`, which embeds the live env report and `surface_digest`, and the two templates keep `ttlMs: 0`.

**The set is written out.**
`STATIC_READ_TTL_URIS` names the three; a test holds it equal to the manifest's static URIs, and the stdio test asserts the TTL on each of them and its absence on the capabilities and template reads.

## Consequences

- `modern_result_envelopes` moves for the three reads, so `FINGERPRINT` moves (with the rest of #250).
- A host that honours `ttlMs` re-reads the three bodies at most every five minutes; a fingerprint move within that window is visible on `amicus_capabilities`, which is not cached.
- The same handler re-registration is how `_meta.fastmcp` is stripped from the three list results (`_install_meta_strip`), because FastMCP adds that key after every transform and middleware has run.
