"""Guard: the persisted result-format snapshot moves with RESULT_FORMAT (ported, #305)."""

from __future__ import annotations

import json
from pathlib import Path

from amicus import __version__
from amicus import result_format_snapshot as rfs
from amicus.schemas.fingerprint import FINGERPRINT, RESULT_FORMAT

_FIXTURE = Path(__file__).parent / "fixtures" / "result_format_snapshot.json"
_REGEN = (
    "persisted result-format surface changed — review the diff, then in the SAME commit bump "
    "RESULT_FORMAT (schemas/fingerprint.py) if an older reader could reject the new shape, and "
    "regenerate (`uv run python -m amicus.result_format_snapshot > "
    "tests/fixtures/result_format_snapshot.json`)."
)


def test_result_format_snapshot_matches_golden():
    assert rfs.render() == _FIXTURE.read_text(encoding="utf-8"), _REGEN


def test_snapshot_embeds_result_format_and_normalizes_release_variables():
    snap = rfs.build_snapshot()
    assert snap["result_format"] == RESULT_FORMAT
    text = rfs.render()
    assert FINGERPRINT not in text and '"description"' not in text and __version__ not in text


def test_snapshot_pins_null_retention_asymmetry_and_covers_every_type():
    snap = rfs.build_snapshot()
    assert "verdict" not in snap["serialized"]["consult_success"]
    assert snap["serialized"]["delegate_success"]["diff"] is None
    assert "session_id" not in snap["serialized"]["error"]["meta"]
    assert set(snap["schemas"]) == {
        "ConsultResult",
        "ReviewResult",
        "DelegateResult",
        "ErrorResult",
    }
    assert set(snap["serialized"]) == {
        "consult_success",
        "review_success",
        "delegate_success",
        "error",
        "error_user_config_rejected",
    }


def test_render_is_deterministic_and_sensitive():
    assert rfs.render() == rfs.render() and rfs.render().endswith("\n")
    snap = rfs.build_snapshot()
    mutated = json.loads(json.dumps(snap))
    mutated["schemas"]["ConsultResult"]["properties"]["field_from_the_future"] = {"type": "string"}
    assert mutated != snap
