"""Tolerant JSONL/last-message parsing (ported from codex-in-claude tests/test_normalize.py)."""

from __future__ import annotations

import json

from amicus.backends.codex import normalize


def test_parse_event_metadata_usage_session_and_cached_tokens():
    events = "\n".join(
        [
            '{"type":"session.created","session_id":"sess-123"}',
            '{"type":"token_count","usage":{"input_tokens":100,"output_tokens":20,"cached_input_tokens":80}}',
            "not json",
            "",
        ]
    )
    usage, session_id = normalize.parse_event_metadata(events)
    assert session_id == "sess-123"
    assert usage is not None
    assert (usage.input_tokens, usage.output_tokens, usage.cached_input_tokens) == (100, 20, 80)
    assert usage.total_tokens == 120  # derived: input + output, cached is a subset of input


def test_explicit_total_wins_and_partial_usage_has_no_total():
    usage, _ = normalize.parse_event_metadata(
        '{"type":"token_count","usage":{"input_tokens":100,"output_tokens":20,"total_tokens":999}}'
    )
    assert usage is not None and usage.total_tokens == 999
    usage, _ = normalize.parse_event_metadata('{"type":"token_count","usage":{"input_tokens":100}}')
    assert usage is not None and usage.total_tokens is None


def test_nested_session_and_empty_stream():
    assert normalize.parse_event_metadata('{"type":"x","msg":{"thread_id":"t-9"}}')[1] == "t-9"
    assert normalize.parse_event_metadata("") == (None, None)


def test_replacement_bearing_session_ids_are_rejected_not_published():
    lossy = '{"thread_id":"01a05a8d-x�y"}'
    assert normalize.parse_event_metadata(lossy)[1] is None
    assert normalize.parse_event_metadata('{"msg":{"thread_id":"a�b"}}')[1] is None
    later = lossy + '\n{"thread_id":"01a05a8d-e1d9-75f2-99b8-d2549f463b71"}'
    assert normalize.parse_event_metadata(later)[1] == "01a05a8d-e1d9-75f2-99b8-d2549f463b71"


def test_parse_and_classify_structured():
    assert normalize.parse_structured('{"summary":"ok"}') == {"summary": "ok"}
    assert normalize.parse_structured('```json\n{"summary":"ok"}\n```') == {"summary": "ok"}
    assert normalize.parse_structured('"just a string"') is None
    assert normalize.parse_structured(None) is None
    assert normalize.classify_structured('{"summary":"ok"}') == ("ok", {"summary": "ok"})
    assert normalize.classify_structured("") == ("invalid_json", None)
    assert normalize.classify_structured("prose") == ("invalid_json", None)
    for scalar in ("[1]", "42", "null", "true"):
        assert normalize.classify_structured(scalar) == ("schema_violation", None)


def test_extract_error_message_unwraps_nested_json():
    assert (
        normalize.extract_error_message('{"type":"turn.failed","error":{"message":"boom"}}')
        == "boom"
    )
    inner = json.dumps({"error": {"message": "bad schema"}})
    assert (
        normalize.extract_error_message('{"type":"error","message":' + json.dumps(inner) + "}")
        == "bad schema"
    )
    assert normalize.extract_error_message('{"type":"turn.completed"}') is None
