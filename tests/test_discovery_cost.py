"""Wire-size ratchet for tools/list, per profile.

The least-capable realistic client preloads every tool definition, so the serialized
catalog is a per-session token tax. The budget is a ceiling; the target is the last
deliberate measurement so a failure message shows the drift. Raising a budget is a
reviewed decision — say why in the PR body.

Measured 2026-09-04 at schema-1 (18 tools, schema-only): see MEASURED.
"""

from __future__ import annotations

import pytest

from amicus import manifest

MEASURED: dict[str, int] = {"all": 90441, "codex-kimi": 90449, "claude": 90441}
BUDGET: dict[str, int] = {p: ((n // 1000) + 1) * 1000 for p, n in MEASURED.items()}
# ceil(bytes/4): a dependency-free, conservative token proxy (~4.13 bytes per token).
TOKEN_PROXY_BUDGET: dict[str, int] = {p: -(-b // 4) for p, b in BUDGET.items()}


def _token_proxy(wire_bytes: int) -> int:
    return -(-wire_bytes // 4)


@pytest.mark.parametrize("profile", sorted(manifest.PROFILES))
async def test_tools_list_wire_size_budget(profile):
    size = await manifest.tools_list_bytes(manifest.app_for_profile(profile))
    assert size <= BUDGET[profile], (
        f"[{profile}] tools/list is {size} bytes (target {MEASURED[profile]}), over the "
        f"{BUDGET[profile]} budget. Compact a description or schema, or raise the budget "
        "deliberately."
    )
    assert _token_proxy(size) <= TOKEN_PROXY_BUDGET[profile]


def test_measured_values_are_real():
    assert all(n > 0 for n in MEASURED.values())
    assert MEASURED["codex-kimi"] != MEASURED["claude"] or MEASURED["all"] == MEASURED["claude"]
