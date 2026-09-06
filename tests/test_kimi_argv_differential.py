"""Differential: amicus's staged argv, agent document, schema instruction, run env and
prompts == moonbridge's (captured by scripts/capture_kimi_differentials.py), temp paths,
the binary token and the agent name aside."""

from __future__ import annotations

import pytest
from pontonier.backend.protocol import RunRequest
from pontonier.conventions.prompts import (
    build_consult_prompt,
    build_delegate_prompt,
    build_review_prompt,
    framings,
)
from tests.support import kimifixtures as kf

from amicus.backends.kimi import cli

SIBLING_HOST = "Claude Code"
FIXTURE = kf.load_fixture()


@pytest.mark.parametrize("case", sorted(FIXTURE["argv"]))
async def test_staged_argv_matches_the_sibling(pinned_kimi_bin, monkeypatch, tmp_path, case):
    entry = FIXTURE["argv"][case]
    req = entry["request"]
    environ = {"AMICUS_STATE_DIR": str(tmp_path / "state")}
    if req.get("skills_dir"):
        environ["AMICUS_KIMI_ISOLATION"] = "ignore-skills"
    _, backend = kf.make_backend(environ, flags=kf.NO_MODEL if entry["dropped"] else kf.ALL_FLAGS)
    request = RunRequest(
        kind=req["kind"],
        prompt="p",
        cwd=str(tmp_path),
        timeout_seconds=60,
        model=req.get("model"),
        access=None,  # kind decides: consult/review are read-only, delegate writes
    )
    async with backend.prepare(request) as prepared:
        ours = kf.normalize_argv(prepared.argv)
        assert list(prepared.dropped_flags) == entry["dropped"]
    assert ours == entry["argv"]


def test_agent_document_schema_instruction_and_env_match_the_sibling():
    theirs = FIXTURE["agent_document"].replace("moonbridge-readonly", "amicus-readonly")
    assert cli.read_only_agent_document() == theirs
    assert cli.schema_instruction({"type": "object"}) == FIXTURE["schema_instruction"]
    env = cli.build_run_env({}, "high")
    assert {k: v for k, v in env.items() if k.startswith("KIMI_MODEL_")} == FIXTURE["run_env"]


def test_user_turn_framings_are_byte_identical_for_the_sibling_host():
    f = framings(SIBLING_HOST)
    p = FIXTURE["prompts"]
    assert build_consult_prompt(f.consult, "Why?", "some context") == p["consult"]
    assert (
        build_review_prompt(f.review, "DIFF TEXT", "working_tree", "author intent") == p["review"]
    )
    assert build_delegate_prompt(f.delegate, "Do the thing.") == p["delegate"]
