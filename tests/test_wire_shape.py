"""Guard: the DELIVERED success-envelope shape is pinned (ported from codex-in-claude #334)."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from amicus import wire_shape_snapshot as wss
from amicus.schemas.envelope import RESULT_META_SCHEMA, Meta

_FIXTURE = Path(__file__).parent / "fixtures" / "wire_shape_snapshot.json"
_REGEN = (
    "the DELIVERED envelope shape changed — review the snapshot diff, then in a DEDICATED commit "
    "bump FINGERPRINT if the agent-visible surface moved and regenerate "
    "(`uv run python -m amicus.wire_shape_snapshot > tests/fixtures/wire_shape_snapshot.json`)."
)


def test_wire_shape_snapshot_matches_golden():
    assert wss.render() == _FIXTURE.read_text(encoding="utf-8"), _REGEN


def test_render_is_deterministic():
    assert wss.render() == wss.render() and wss.render().endswith("\n")


def test_delivered_meta_carries_no_nulls_and_something_was_omitted():
    snap = wss.build_snapshot()
    for detail, envelopes in snap["delivered"].items():
        for name, env in envelopes.items():
            assert [k for k, v in env["meta"].items() if v is None] == [], f"{detail}/{name}"
    omitted = snap["omitted_meta_keys"]
    assert omitted and all(keys for keys in omitted.values())
    assert "context_summary" in omitted["consult"]


def test_populated_optionals_survive_and_every_producible_optional_is_populated_somewhere():
    snap = wss.build_snapshot()
    for detail in ("summary", "full"):
        consult = snap["delivered"][detail]["consult"]["meta"]
        assert (
            consult["model"] == "a-model"
            and consult["session_id"] == "sess-1"
            and consult["command_exit_code"] == 0
        )
        assert (
            consult["usage"]["cached_input_tokens"] == 3
            and consult["instructions_append"]["bytes"] == 5
        )
        assert (
            consult["backend_details"] == {"isolation": "inherit"} and consult["job_id"] == "0" * 32
        )
    impossible = {"job_kind", "idempotency_replayed", "task_id"}
    optional = {n for n, f in Meta.model_fields.items() if f.default is None}
    assert impossible < optional
    populated = {k for env in snap["delivered"]["summary"].values() for k in env["meta"]}
    assert optional - impossible <= populated


def test_one_envelope_stays_sparse_and_payload_keys_survive():
    snap = wss.build_snapshot()
    sparse = snap["delivered"]["summary"]["delegate_no_changes"]["meta"]
    assert not {"model", "session_id", "usage", "roots_source"} & set(sparse)
    assert len(snap["omitted_meta_keys"]["delegate_no_changes"]) > len(
        snap["omitted_meta_keys"]["review"]
    )
    for detail in ("summary", "full"):
        assert "diff" in snap["delivered"][detail]["delegate_no_changes"]
        for env in snap["delivered"][detail].values():
            assert set(env["raw_response"]) == {"text", "session_id", "model"}
    for name in snap["delivered"]["summary"]:
        assert snap["delivered"]["summary"][name]["raw_response"]["text"] is None
        assert snap["delivered"]["full"][name]["raw_response"]["text"] == "RAW MODEL TEXT"


def test_delivered_meta_validates_against_the_published_contract_and_the_validator_is_not_blind():
    validator = Draft202012Validator(RESULT_META_SCHEMA)
    snap = wss.build_snapshot()
    for envelopes in snap["delivered"].values():
        for name, env in envelopes.items():
            assert [e.message for e in validator.iter_errors(env["meta"])] == [], name
    meta = dict(snap["delivered"]["summary"]["consult"]["meta"])
    assert validator.is_valid(meta)
    meta["elapsed_ms"] = "not an int"
    assert not validator.is_valid(meta)


def test_snapshot_is_sensitive_to_key_loss():
    snap = wss.build_snapshot()
    mutated = json.loads(json.dumps(snap))
    del mutated["delivered"]["summary"]["consult"]["summary"]
    assert mutated != snap
