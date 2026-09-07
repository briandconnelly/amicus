"""Wire prose must not contradict what amicus does: a shared union of bans in M0, refined
per backend when each plugin's contract lands (its forbidden_surface_phrases join here)."""

from __future__ import annotations

import json

import pytest
from pontonier.testing import surface_honesty

from amicus import manifest

# Cross-backend vocabulary that would teach an agent a mechanism amicus lacks.
FORBIDDEN_SURFACE_PHRASES: tuple[str, ...] = (
    "applies the diff to your working tree",
    "--dangerously-bypass",
    "codex exec",
    "kimi exec",
    "codex_consult",
    "claude_consult",
    "kimi_consult",
    "codex-in-claude",
    "moonbridge",
    "claude-in-codex",
    "read-only sandbox",
)


@pytest.fixture(scope="module")
def wire_text() -> str:
    import asyncio

    return json.dumps(
        asyncio.run(manifest.build_manifest(manifest.app_for_profile("all"))), ensure_ascii=False
    )


@pytest.mark.parametrize("phrase", FORBIDDEN_SURFACE_PHRASES)
def test_wire_prose_does_not_carry_sibling_vocabulary(wire_text, phrase):
    assert surface_honesty.find_forbidden_phrases(wire_text, (phrase,)) == []


def test_the_instrument_can_fail(wire_text):
    assert surface_honesty.find_forbidden_phrases(wire_text, ("amicus_consult",))
