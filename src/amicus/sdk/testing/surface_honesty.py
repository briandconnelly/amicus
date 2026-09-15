"""The surface-honesty check: wire prose must not contradict the CLI contract.

Origin: moonbridge began as a port of a Codex plugin, and vestiges of that
origin survived onto the wire — prose describing an ``exec`` subcommand and a
"read-only sandbox" that its CLI does not have. Every other gate stayed green
because the CODE was right and only the DESCRIPTION was wrong; description-only
defects teach agents a mechanism that does not exist. The ban therefore lives
next to the facts that justify it (``BackendContract.forbidden_surface_phrases``)
and is enforced against the BUILT wire surface, not source text, so a fix that
only edits a comment cannot satisfy it.
"""

from __future__ import annotations

import json
from typing import Any


def render_wire_text(surface: Any) -> str:
    """The agent-visible surface as one searchable string. Accepts the built
    manifest dict (preferred) or any JSON-serializable surface object."""
    if isinstance(surface, str):
        return surface
    return json.dumps(surface, ensure_ascii=False)


def find_forbidden_phrases(surface: Any, phrases: tuple[str, ...]) -> list[str]:
    """Violations: each forbidden phrase found in the wire surface. Matching is
    case-sensitive and literal — the phrases are exact vocabulary bans, not
    patterns."""
    text = render_wire_text(surface)
    return [
        f"forbidden phrase {phrase!r} appears in the agent-visible surface"
        for phrase in phrases
        if phrase in text
    ]


def find_contract_self_contradictions(
    phrases: tuple[str, ...], contract_strings: dict[str, str]
) -> list[str]:
    """Violations: a contract's own wire-visible prose fields contain a phrase
    the same contract bans. Run this against readonly_honesty_statement,
    implicit_context_disclosure, and any other prose the contract carries."""
    out: list[str] = []
    for field_name, text in contract_strings.items():
        for phrase in phrases:
            if phrase in text:
                out.append(
                    f"contract field {field_name!r} contains its own forbidden phrase {phrase!r}"
                )
    return out
