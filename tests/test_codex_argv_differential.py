"""Differential: amicus's staged argv, prompts and developer turn == codex-in-claude's
(captured by scripts/capture_codex_differentials.py), temp paths and the one deliberate
host-neutral phrase aside."""

from __future__ import annotations

import tomllib

import pytest
from pontonier.backend.protocol import RunRequest
from pontonier.conventions.prompts import (
    build_consult_prompt,
    build_delegate_prompt,
    build_review_prompt,
    framings,
)
from tests.support import codexfixtures as cf

from amicus.backends.codex import contract
from amicus.schemas import instructions as ins

SIBLING_HOST = "Claude Code"


def _decode_di(argv: list[str]) -> tuple[list[str], str | None]:
    """Strip the developer_instructions token (compared separately) and return its value."""
    out: list[str] = []
    value = None
    skip = False
    for i, tok in enumerate(argv):
        if skip:
            skip = False
            continue
        if (
            tok == "-c"
            and i + 1 < len(argv)
            and argv[i + 1].startswith(f"{contract.DEVELOPER_INSTRUCTIONS_CONFIG_KEY}=")
        ):
            value = tomllib.loads(f"v = {argv[i + 1].partition('=')[2]}")["v"]
            skip = True
            continue
        out.append(tok)
    return out, value


@pytest.mark.parametrize("case", sorted(cf.FIXTURE["argv"]))
async def test_staged_argv_matches_the_sibling(pinned_codex_bin, monkeypatch, case):
    entry = cf.FIXTURE["argv"][case]
    req = entry["request"]
    environ = {}
    if req.get("extra_args"):
        environ["AMICUS_CODEX_EXTRA_ARGS"] = " ".join(req["extra_args"])
    _, backend = cf.make_backend(environ, flags=cf.NO_MODEL if entry["dropped"] else cf.ALL_FLAGS)
    request = RunRequest(
        kind=req["kind"],
        prompt="p",
        cwd="/repo",
        timeout_seconds=60,
        schema={"type": "object"} if req["schema"] else None,
        model=req.get("model"),
        reasoning_effort=req.get("reasoning_effort"),
        isolation=req.get("isolation"),
        instructions_append=req.get("developer_instructions"),
    )
    async with backend.prepare(request) as prepared:
        ours, our_di = _decode_di(cf.normalize_argv(prepared.argv))
        assert list(prepared.dropped_flags) == entry["dropped"]
    theirs, their_di = _decode_di(entry["argv"])
    assert ours == theirs
    if their_di is not None:
        assert our_di == their_di.replace(SIBLING_HOST, "another coding agent")


def test_user_turn_framings_are_byte_identical_for_the_sibling_host():
    f = framings(SIBLING_HOST)
    p = cf.FIXTURE["prompts"]
    assert build_consult_prompt(f.consult, "Why?", "some context") == p["consult"]
    assert (
        build_review_prompt(f.review, "DIFF TEXT", "working_tree", "author intent") == p["review"]
    )
    assert build_delegate_prompt(f.delegate, "Do the thing.") == p["delegate"]


def test_developer_turn_differs_only_by_the_host_phrase():
    theirs = cf.FIXTURE["prompts"]["developer_instructions"]
    assert ins.compose("Focus on locking.") == theirs.replace(SIBLING_HOST, "another coding agent")
