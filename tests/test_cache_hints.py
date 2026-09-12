"""Guard: the SEP-2549 freshness hints, and the capability flags, as the SHIPPED
transport emits them (ADR 0018).

Every assertion here that names a wire value runs against a real `amicus-mcp` stdio
subprocess rather than the in-memory client. That is the point of the file: the in-memory
transport and the stdio transport derive `listChanged` from different inputs, and the
committed manifest — built in-memory — pinned a value for `resources.listChanged` that no
client has ever received (issue #45).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from mcp_types.methods import CACHEABLE_METHODS
from tests.conftest import NEVER_SPAWN_CODEX, spawned_server_env

from amicus import config, server
from amicus.registry import BackendRegistry
from amicus.tools.resources import STATIC_RESOURCE_URIS

FIXTURES = Path(__file__).parent / "fixtures"

# One instantiated template URI. `amicus://backends/{backend}` reports live install and
# auth state, which is the concrete reason `resources/read` carries no TTL.
VOLATILE_RESOURCE_URI = "amicus://backends/codex"

_ENVELOPE_FIELDS = ("resultType", "ttlMs", "cacheScope")


def _server_env() -> dict[str, str]:
    """`conftest.spawned_server_env`, which this file's tests were written against and
    which the discovery-cost instrument's tests now share."""
    return spawned_server_env()


def test_the_spawned_server_env_is_as_clean_as_clean_env(monkeypatch):
    """The subprocess environment strips what `clean_env` strips.

    Positive control on the instrument: a legacy alias is exported first, so a filter that
    only handled `AMICUS_` would leave it visible here.
    """
    monkeypatch.setenv("CODEX_IN_CLAUDE_LOG_FILE", "/nonexistent/amicus-test-leak.log")
    monkeypatch.setenv("AMICUS_ALLOW_CWD_WORKSPACE", "1")
    env = _server_env()
    assert "CODEX_IN_CLAUDE_LOG_FILE" not in env
    assert "AMICUS_ALLOW_CWD_WORKSPACE" not in env
    assert env["AMICUS_CODEX_BIN"] == NEVER_SPAWN_CODEX


def _stdio() -> StdioTransport:
    return StdioTransport(command=sys.executable, args=["-m", "amicus.server"], env=_server_env())


def _envelope(result: Any) -> dict[str, Any]:
    wire = result.model_dump(mode="json", by_alias=True)
    return {k: wire[k] for k in _ENVELOPE_FIELDS if k in wire}


def _caps(capabilities: Any) -> dict[str, Any]:
    return capabilities.model_dump(mode="json", by_alias=True, exclude_none=True)


def _snapshot(profile: str = "all") -> dict[str, Any]:
    return json.loads((FIXTURES / f"manifest_snapshot.{profile}.json").read_text())


def test_every_cacheable_method_is_hinted_or_deliberately_not():
    """The SDK's cacheable set is split by decision, with nothing left over.

    Written as a partition rather than a subset check so a method the SDK makes cacheable
    LATER fails here instead of silently inheriting `CATALOG_CACHE_TTL_MS` (if the map
    were derived) or silently staying at 0 (if this test only checked the named five).
    """
    hinted = set(server.CACHED_CATALOG_METHODS)
    assert len(hinted) == len(server.CACHED_CATALOG_METHODS), "duplicate method in the tuple"
    assert not hinted & server.UNCACHED_CACHEABLE_METHODS
    assert hinted | server.UNCACHED_CACHEABLE_METHODS == set(CACHEABLE_METHODS), (
        "the SDK's cacheable methods changed: add each new one to CACHED_CATALOG_METHODS "
        "or to UNCACHED_CACHEABLE_METHODS, deliberately"
    )


def test_the_installed_hint_map_matches_the_declared_split(clean_env):
    # The literal, not the constant. Every other assertion in this file reads
    # `server.CATALOG_CACHE_TTL_MS`, so changing the constant alone moves them all with it
    # and only the manifest fixture objects. ADR 0018 chose this number; a deliberate
    # change edits it here too, where the reason is readable.
    assert server.CATALOG_CACHE_TTL_MS == 300_000
    assert server.CATALOG_CACHE_SCOPE == "private"
    # `clean_env` before a bare `create_app()`, per `tests/test_server.py`: the hint map
    # does not depend on which backends load, but the developer's own AMICUS_BACKENDS
    # should not decide whether this test reaches the assertion at all.
    app = server.create_app()
    hints = app._mcp_server.cache_hints
    assert set(hints) == set(server.CACHED_CATALOG_METHODS)
    for method, hint in hints.items():
        assert hint.ttl_ms == server.CATALOG_CACHE_TTL_MS, method
        assert hint.scope == server.CATALOG_CACHE_SCOPE, method


async def test_the_catalog_methods_advertise_the_ttl_on_the_wire():
    """The four list methods and `server/discover`, over stdio, at the modern era."""
    expected = {
        "resultType": "complete",
        "ttlMs": server.CATALOG_CACHE_TTL_MS,
        "cacheScope": server.CATALOG_CACHE_SCOPE,
    }
    async with Client(_stdio()) as client:
        assert client.protocol_version == "2026-07-28"
        discover = client.session.discover_result.model_dump(mode="json", by_alias=True)
        assert {k: discover[k] for k in ("ttlMs", "cacheScope")} == {
            "ttlMs": server.CATALOG_CACHE_TTL_MS,
            "cacheScope": server.CATALOG_CACHE_SCOPE,
        }
        for call in ("list_tools_mcp", "list_resources_mcp", "list_resource_templates_mcp"):
            assert _envelope(await getattr(client, call)()) == expected, call
        assert _envelope(await client.list_prompts_mcp()) == expected


async def test_resource_reads_carry_no_ttl_static_or_volatile():
    """`resources/read` is cacheable and deliberately unhinted.

    The volatile template read is asserted alongside the static ones because it is the
    reason for the exclusion: the SDK chooses a hint per METHOD, so a TTL on
    `resources/read` would have covered a live install-and-auth report too.
    """
    uncached = {"resultType": "complete", "ttlMs": 0, "cacheScope": "private"}
    async with Client(_stdio()) as client:
        for uri in (*STATIC_RESOURCE_URIS, VOLATILE_RESOURCE_URI):
            assert _envelope(await client.read_resource_mcp(uri)) == uncached, uri


@pytest.mark.parametrize("mode", ["legacy", None])
async def test_both_eras_report_list_changed_false(mode):
    """amicus has no `notifications/*/list_changed` emission site, so neither era claims
    one. Without the `_filter_capabilities` override the stdio handshake path advertises
    `tools.listChanged: true`, from FastMCP's hardcoded `NotificationOptions`."""
    kwargs = {"mode": mode} if mode is not None else {}
    async with Client(_stdio(), **kwargs) as client:
        caps = (
            _caps(client.initialize_result.capabilities)
            if mode == "legacy"
            else _caps(client.session.discover_result.capabilities)
        )
    assert caps["tools"]["listChanged"] is False
    assert caps["resources"]["listChanged"] is False
    assert caps["resources"]["subscribe"] is False


@pytest.mark.parametrize("env", [{}, {"AMICUS_TASKS": "1"}], ids=["default", "tasks"])
def test_forcing_list_changed_false_is_not_hiding_a_served_subscription(env):
    """The override is honest only while amicus serves no `subscriptions/listen`.

    At 2026-07-28 the SDK derives `listChanged` and `resources.subscribe` from whether that
    method is served, so the day amicus serves it the modern flags become genuinely true
    and `_filter_capabilities` would be suppressing a real capability. Asserted with the
    tasks extension on as well, because that is the one configuration that adds request
    handlers after `create_app` has built the surface.
    """
    app = server.create_app(config.settings(env), BackendRegistry({}, {}))
    handlers = app._mcp_server._request_handlers
    # Positive control: a bare `not in` against a renamed or empty map would pass for the
    # wrong reason, and this is the assertion's whole instrument.
    assert "tools/list" in handlers, "the request-handler map is not what this test reads"
    assert "subscriptions/listen" not in handlers, (
        "amicus now serves subscriptions/listen: revisit ADR 0018's listChanged decision "
        "instead of continuing to force the flag false"
    )


async def test_the_manifest_pins_the_capabilities_the_shipped_transport_sends():
    """Transport parity: the in-memory manifest and the stdio wire agree.

    `manifest.py` builds `initialize` over the in-memory transport, where the SDK reads
    `LowLevelServer.notification_options` (all three flags true); the stdio path passes
    `NotificationOptions(tools_changed=True)` instead. Before ADR 0018 the two disagreed
    on `resources.listChanged` and the snapshot pinned the value no client receives. This
    asserts the agreement rather than trusting that a regenerated fixture restored it.
    """
    snapshot = _snapshot()
    async with Client(_stdio(), mode="legacy") as legacy:
        wire_initialize = _caps(legacy.initialize_result.capabilities)
    async with Client(_stdio()) as modern:
        wire_discover = _caps(modern.session.discover_result.capabilities)
    assert wire_initialize == snapshot["initialize"]["capabilities"]
    assert wire_discover == snapshot["discover"]["capabilities"]
    assert wire_initialize == wire_discover, (
        "the two eras derive listChanged differently; _filter_capabilities exists to make "
        "them agree, so a divergence here is that override having stopped working"
    )
