"""Differential: amicus's staged argv == claude-in-codex's (captured by
scripts/capture_claude_differentials.py), the binary token and the --append-system-prompt
VALUE aside; the guardrail text is compared separately with the host neutralized."""

from __future__ import annotations

import pytest
from pontonier.backend.protocol import RunRequest
from tests.support import claudefixtures as cf

from amicus.backends.claude import adversarial

FIXTURE = cf.load_fixture()


@pytest.mark.parametrize("case", sorted(FIXTURE["argv"]))
async def test_staged_argv_matches_the_sibling(pinned_claude_bin, monkeypatch, tmp_path, case):
    entry = FIXTURE["argv"][case]
    req = entry["request"]
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")  # bare needs one; login modes strip it
    _, backend = cf.make_backend(flags=cf.NO_MODEL if entry["dropped"] else cf.ALL_FLAGS)
    request = RunRequest(
        kind="consult",
        prompt="p",
        cwd=str(tmp_path),
        timeout_seconds=60,
        model=req["model"],
        reasoning_effort=req["effort"],
        budget_usd=req["budget"],
        config_mode=req["config_mode"],
        access=req["access"],
    )
    async with backend.prepare(request) as prepared:
        assert cf.normalize_argv(prepared.argv) == entry["argv"]
        assert list(prepared.dropped_flags) == entry["dropped"]
        assert prepared.stdin_text == "p"


def test_guardrails_are_the_siblings_with_the_host_neutralized():
    theirs = FIXTURE["guardrails"]
    assert "Codex" in theirs
    neutral = theirs.replace("Codex's", "the requesting agent's").replace(
        "Codex", "the requesting agent"
    )
    assert neutral == adversarial.CRITIC_GUARDRAILS


async def test_the_persona_carrier_is_the_one_documented_deviation(pinned_claude_bin):
    """The sibling folded instructions_append into the argv system prompt; amicus composes it
    into the stdin prompt (ADR 0010 decision 2). Pin the deviation so it cannot regress
    silently in either direction."""
    _, backend = cf.make_backend()
    request = RunRequest(
        kind="consult",
        prompt="p",
        cwd="/repo",
        timeout_seconds=60,
        instructions_append="Focus on locking.",
    )
    async with backend.prepare(request) as prepared:
        idx = prepared.argv.index("--append-system-prompt")
        assert prepared.argv[idx + 1] == adversarial.CRITIC_GUARDRAILS
        assert "Focus on locking." not in " ".join(prepared.argv)
        assert prepared.stdin_text is not None and "Focus on locking." in prepared.stdin_text
