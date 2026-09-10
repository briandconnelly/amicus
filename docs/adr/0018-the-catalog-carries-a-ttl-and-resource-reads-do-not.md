# ADR 0018: the discovery catalog carries a TTL; resource reads carry none

**Status:** Accepted (2026-09-09)

Supersedes the cache-hint clause of [ADR 0006](0006-fingerprint-and-surface-digest.md); the rest of that record stands.

## Context

ADR 0006 left `ttlMs`/`cacheScope` at the SDK default — `ttlMs: 0`, `cacheScope: "private"` — and gave a reason and an exit condition.
The reason: "fastmcp applies one server-wide hint to every list and read result, and `amicus://models/{backend}` is volatile, so a positive TTL would be wrong for it."
The exit condition: "Revisit the TTL when fastmcp offers per-resource hints."

Issue #45 asked for the revisit, on the grounds that the catalog is provably static for the life of the process and that `ttlMs: 0` therefore spends a `tools/list` re-walk on every re-read for nothing.
(The issue quoted 92.8 KB, from issue #41's measurement; `uv run python -m amicus.manifest --measure` on this tree reports 99,053 bytes for the `all` profile.)

Both halves of ADR 0006's reason are still true and the exit condition is still unmet.
FastMCP 4.0.3's `cache_ttl` constructor argument is uniform by construction: `build_cache_hints` returns `dict.fromkeys(get_args(CacheableMethod), hint)`.
FastMCP offers no per-resource hint, and it is not close to offering one.

What changed is a fact neither the ADR nor the issue had.
The SDK layer beneath FastMCP takes the hint map **per method** — `Server.cache_hints` is a `dict[CacheableMethod, CacheHint]`, read by `mcp.server.runner.Server._serialize` — and the volatility ADR 0006 was protecting is confined to exactly one method.
`amicus://models/{backend}` and `amicus://backends/{backend}` are read through `resources/read`, and nothing else amicus serves through that method needs a TTL.
So per-method granularity is sufficient here even though per-resource granularity is what ADR 0006 asked for, and the exit condition it wrote was stricter than its own reasoning required.

Two premises in issue #45 were wrong, and are recorded because the fix would have been shaped differently by either.

`amicus://capabilities` is not the volatile resource the issue and ADR 0006's successor reasoning might suggest.
`capabilities_payload` takes `registry` and `config_errors` and uses neither (both carry an explicit `noqa: ARG001`); it reports `enabled_backends` from settings, which is fixed per process.
The genuinely mutable reads are the two templates, which report install state, auth state and a fetched model catalog.
A `resources/read` exclusion aimed at `amicus://capabilities` would have protected the wrong payload and cached the live ones.

`surface_digest` is a catalog comparison token, not a revalidation token for this contract.
It covers the tool, resource and template records plus the instructions text — and nothing else.
It does not cover the `initialize` or `server/discover` capabilities, nor the cache envelope, so nothing this record decides would have moved it (see Consequences for the measurement, and for the one edit that did).
A caller re-reading it learns that the catalog is unchanged, which is what it is for; it is not evidence that the wider contract is unchanged, and this repository should not describe it as one.

The secondary half of issue #45 — `tools.listChanged` disagreeing across eras — is not an amicus defect in the way the issue framed it.
The SDK's `get_capabilities` is deliberately era-honest: at 2026-07-28 the flags derive from whether `subscriptions/listen` is served, and at handshake era from the `NotificationOptions` the transport supplies.
The overclaim is real all the same.
FastMCP's stdio path passes `NotificationOptions(tools_changed=True)`, amicus has no `notifications/*/list_changed` emission site, and FastMCP has none either — so a handshake client was told to expect a notification that cannot arrive.

Probing that turned up a third defect the issue did not name.
`manifest.py` builds the `initialize` block over the in-memory transport, where the SDK reads `LowLevelServer.notification_options` (all three flags true), while the shipped stdio transport passes only `tools_changed=True`.
The committed snapshot therefore pinned `initialize.capabilities.resources.listChanged: true`, a value no client has ever received, inside a category `FINGERPRINT_COVERS` names.

## Decision

**The four list methods and `server/discover` advertise `ttlMs: 300000`, `cacheScope: "private"`.**
The hint map is written onto the low-level server rather than through FastMCP's uniform `cache_ttl`, because the uniform form cannot express the exclusion below.
300s is a policy choice, not a measured optimum.
It is long enough to cover a burst of list calls within one turn, and short enough that a host which deliberately persists its cache self-heals within five minutes of a restart under a different `AMICUS_BACKENDS`.
That persistence takes deliberate host configuration: the default store is in-memory and its arm id is a fresh `uuid.uuid4()` per client, so entries cannot outlive the client that made them, and honoring is modern-era and opt-in besides.
`private` stays, and for the reason ADR 0006 gave: the catalog varies with `AMICUS_BACKENDS` through `annotations_for`.
It does not follow that `private` prevents configuration drift — scope separates authorization contexts, not launch configurations of the same server.

**`resources/read` carries no hint at all, which leaves it at the SDK's `ttlMs: 0`.**
The two template reads report live state, the SDK chooses per method, and there is no client-visible cost to leaving four small static reads uncached.

**The split is written out, not derived.**
`CACHED_CATALOG_METHODS` names the five and `UNCACHED_CACHEABLE_METHODS` names the one, and a test asserts the two partition the SDK's `CACHEABLE_METHODS` exactly.
A method the SDK makes cacheable later then fails that test rather than silently inheriting a TTL that was never considered for it.

**Both eras report `listChanged: false`, for tools and for resources.**
`_filter_capabilities` already existed to make the advertised capabilities honest; forcing the flag is one more thing it does.
A handshake client loses no notification it was ever going to be sent, and may refetch more often — which is the correct consequence of amicus not notifying.
`subscriptions/listen` is not implemented merely to make the flags true.

**The manifest's capability blocks are asserted against the shipped stdio transport.**
`tests/test_cache_hints.py` spawns a real `amicus-mcp` subprocess and compares both eras' capabilities to the committed snapshot.
Regenerating the fixture alone would have restored agreement today and lost it again silently on the next framework change, which is how the divergence arose in the first place.

## Consequences

`FINGERPRINT` moves to `schema-13`: `initialize_response`, `discover_response` and `modern_result_envelopes` all change.
`RESULT_FORMAT` does not move — no stored job-result shape changes.

`surface_digest` moves, and only because of the `instructions` edit.
Measured on this tree: revert that one clause and the digest returns to `30df43ec…` (`all` and `claude`) and `02bdc127…` (`codex-kimi`), the values pinned before this change, while the cache hints and the `listChanged` flags stay exactly as this ADR sets them.
That is the concrete demonstration of what the digest covers: `instructions` is inside it and the capability blocks and cache envelope are not, so a caller watching `surface_digest` alone would have seen nothing of the change this record is actually about.

The change is inert against every host observed to date: honoring requires a modern-era client that passes `cache=`, and neither captured host negotiates the modern era — `docs/host-captures/claude-code/2.1.263/connection.log` records `protocol=2025-11-25` and `docs/host-captures/codex/0.153.4/connection.log` records `protocol=2025-06-18`.
It is an honest advertisement now and a saving whenever a client starts honoring it, not a measured improvement to any host today.

ADR 0006's exit condition is retired rather than met.
The lesson is worth keeping: it named a specific upstream feature ("per-resource hints") as the trigger for a revisit, when the decision actually rested on a granularity requirement that a coarser mechanism turned out to satisfy.
An exit condition written as a capability to wait for outlives its usefulness faster than one written as the property the decision needs.
