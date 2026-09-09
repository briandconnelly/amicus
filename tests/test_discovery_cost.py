"""Wire-size ratchet for tools/list, per profile.

The least-capable realistic client preloads every tool definition, so the serialized
catalog is a per-session token tax. The budget is a ceiling; the target is the last
deliberate measurement so a failure message shows the drift. Raising a budget is a
reviewed decision — say why in the PR body.

What this ratchet does and does not cover, scoped against captured host evidence rather
than assumed. It bounds the TOKEN COST of discovery. It is not a measure of first-call
success, and a green run here is no evidence that an agent picks the right tool.

The preloading client this budget is written for is real but is not universal. Codex CLI
0.153.4 preloads the catalog, so the tax is paid per session there. Claude Code 2.1.263
does not: it defers MCP tool definitions behind a ToolSearch lookup, so the wire size is a
smaller tax on that host than the budget assumes
(docs/host-captures/install-smoke/claude-code/2.1.263/notes.md). The budget stays the
worst-case ceiling for the clients that do preload.

Measured 2026-09-09 at schema-10 (18 tools; every model result carries
findings_diagnostics, and both review tools publish what `confidence` means): see MEASURED.

The schema-8 -> schema-9 raise (+5160 bytes) is deliberate, and most of it is prose. The
`findings_diagnostics` object itself costs ~1250 bytes across four paid tools' output
schemas, which the published schemas inline rather than $ref. The rest is the semantics
of the field, kept through _strip_schema_noise on purpose: `dropped: 0` does not mean
nothing was lost, and `dropped: null` means the count was unknowable. An MCP-only caller
has no skill file to read, so a field whose whole purpose is to prevent a misreading has
to carry that meaning on the wire or it will be misread (issue #38).

The schema-9 -> schema-10 raise (+1130 bytes) is the same trade on a smaller field. Adding
`unknown` to the confidence enum costs a dozen bytes; the rest is one description carried
byte-identically on both review tools, which is the duplication issue #41 is about. It is
kept because `confidence` is now two things - the backend's own rating, and the `low` amicus
substitutes where it also withholds the verdict - and it has two misreadings to prevent, both
of which invert the value: `unknown` read as a low rating, and a high rating read as evidence
that coverage was complete (issue #53).
"""

from __future__ import annotations

import pytest

from amicus import manifest

MEASURED: dict[str, int] = {"all": 98947, "codex-kimi": 98955, "claude": 98947}
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
