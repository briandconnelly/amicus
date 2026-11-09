"""Tolerant reading of pi's `--mode json` event stream (synthetic, in the #423 probe's shape)."""

from __future__ import annotations

import json

from amicus.backends.pi import normalize


def _line(obj: dict) -> str:
    return json.dumps(obj) + "\n"


def _usage(inp=10, out=5, cr=0, cw=0, total=None, cost=0.001, from_provider=True) -> dict:
    return {
        "input": inp,
        "output": out,
        "cacheRead": cr,
        "cacheWrite": cw,
        "reasoning": 0,
        "totalTokens": inp + out + cr + cw if total is None else total,
        "cost": {"total": cost, "totalFromProvider": from_provider},
    }


def _assistant(content, usage=None, **extra) -> dict:
    message = {"role": "assistant", "content": content, "thinkingLevel": "medium"}
    message["stopReason"] = "stop"
    if usage is not None:
        message["usage"] = usage
    message.update(extra)
    return message


def _text(text: str) -> list[dict]:
    return [{"type": "text", "text": text}]


def _end(message: dict) -> str:
    return _line({"type": "message_end", "message": message})


SESSION = _line({"type": "session", "id": "sess-1", "version": 3, "cwd": "/w"})
SYSTEM = _end({"role": "system", "content": _text("sys")})
USER = _end({"role": "user", "content": _text("hi")})

TOOL_TURN = _assistant(
    [{"type": "text", "text": "looking"}, {"type": "toolCall", "id": "t1", "name": "read"}],
    _usage(123, 45, total=168),
    stopReason="toolUse",
)
FINAL_TURN = _assistant(_text("the answer"), _usage(200, 60, total=260))
STREAM = (
    SESSION
    + SYSTEM
    + USER
    + _line({"type": "agent_start"})
    + _end(TOOL_TURN)
    + _line({"type": "turn_end", "message": TOOL_TURN})
    + _end({"role": "toolResult", "content": _text("file")})
    + _end(FINAL_TURN)
    + _line({"type": "turn_end", "message": FINAL_TURN})
    + _line({"type": "agent_end", "messages": [TOOL_TURN, FINAL_TURN], "willRetry": False})
    + _line({"type": "agent_settled", "aborted": False})
)

ERROR_TURN = _assistant([], None, stopReason="error", errorMessage="Connection error.")
RETRIED_ERROR_STREAM = (
    SESSION
    + USER
    + _end(ERROR_TURN)
    + _line({"type": "auto_retry_start"})
    + _end(ERROR_TURN)
    + _line({"type": "auto_retry_start"})
    + _end(ERROR_TURN)
    + _line({"type": "agent_settled", "aborted": False})
)


def test_answer_is_last_assistant_text_after_tool_turns():
    assert normalize.extract_final_message(STREAM) == "the answer"
    assert normalize.final_assistant(STREAM) == FINAL_TURN


def test_text_parts_only_form_the_answer():
    parts = [
        {"type": "text", "text": "one"},
        {"type": "toolCall", "id": "x"},
        {"type": "text", "text": "two"},
    ]
    assert normalize.extract_final_message(_end(_assistant(parts))) == "one\ntwo"


def test_no_assistant_text_returns_none():
    assert normalize.extract_final_message(SESSION + USER) is None
    assert normalize.final_assistant(SESSION + USER) is None
    assert normalize.extract_final_message(RETRIED_ERROR_STREAM) is None
    assert normalize.extract_final_message("") is None


def test_usage_counts_each_response_once():
    usage, _ = normalize.parse_event_metadata(STREAM)
    assert usage is not None
    assert (usage.input_tokens, usage.output_tokens) == (123 + 200, 45 + 60)
    assert usage.total_tokens == 168 + 260


def test_total_falls_back_to_input_plus_output():
    message = _assistant(_text("x"), _usage(7, 3))
    del message["usage"]["totalTokens"]
    usage, _ = normalize.parse_event_metadata(_end(message))
    assert usage is not None and usage.total_tokens == 10


def test_cost_only_when_from_provider():
    paid = _end(_assistant(_text("a"), _usage(cost=0.5, from_provider=True)))
    paid2 = _end(_assistant(_text("b"), _usage(cost=0.25, from_provider=True)))
    own = _end(_assistant(_text("c"), _usage(cost=0.1, from_provider=False)))
    usage, _ = normalize.parse_event_metadata(paid + paid2)
    assert usage is not None and usage.cost_usd == 0.75
    usage, _ = normalize.parse_event_metadata(paid + own)
    assert usage is not None and usage.cost_usd is None, "one computed cost voids the sum"


def test_cache_tokens_map_to_cached_input_and_cache_creation():
    stream = _end(_assistant(_text("a"), _usage(cr=30, cw=4))) + _end(
        _assistant(_text("b"), _usage(cr=20, cw=1))
    )
    usage, _ = normalize.parse_event_metadata(stream)
    assert usage is not None
    assert usage.cached_input_tokens == 50
    assert usage.cache_creation_input_tokens == 5


def test_no_usage_gives_none():
    usage, session_id = normalize.parse_event_metadata(SESSION + _end(_assistant(_text("a"))))
    assert usage is None
    assert session_id == "sess-1"


def test_error_stop_reason_exposes_message():
    assert normalize.final_error(RETRIED_ERROR_STREAM) == "Connection error."
    assert normalize.final_error(STREAM) is None, "control: a successful run has no error"


def test_session_id_from_session_event():
    _, session_id = normalize.parse_event_metadata(STREAM)
    assert session_id == "sess-1"


def test_thinking_level_is_the_final_assistants():
    stream = _end(_assistant(_text("a"), thinkingLevel="low")) + _end(
        _assistant(_text("b"), thinkingLevel="high")
    )
    assert normalize.thinking_level(stream) == "high"
    assert normalize.thinking_level(SESSION) is None


def test_garbage_lines_degrade_metadata_not_the_answer():
    stream = "{not json\n[1,2]\nplain\n" + STREAM + '{"type":"message_end","message":7}\n'
    stream += '{"type":"message_end","message":{"role":"assistant","content":"str"}}\n'
    assert normalize.extract_final_message(STREAM + "{not json\n") == "the answer"
    usage, _ = normalize.parse_event_metadata("{bad\n" + STREAM)
    assert usage is not None and usage.input_tokens == 323
    # A malformed trailing assistant entry is not text parts: no answer, no crash.
    assert normalize.extract_final_message(stream) is None


def test_unknown_event_types_are_ignored():
    stream = _line({"type": "entry_appended", "entry": {}}) + STREAM + _line({"type": "novel"})
    assert normalize.extract_final_message(stream) == "the answer"


def test_parse_structured():
    assert normalize.parse_structured('{"a": 1}') == {"a": 1}
    assert normalize.parse_structured("prose") is None
    assert normalize.parse_structured(None) is None


LOST = "[output truncated]\n"


def test_a_loss_before_the_final_message_leaves_it_trusted():
    stream = _end(_assistant(_text("early"))) + LOST + _end(_assistant(_text("final")))
    assert normalize.extract_final_message(stream) == "final"
    assert not normalize.lost_after_final_message(stream)


def test_a_loss_after_the_final_message_is_flagged():
    stream = _end(_assistant(_text("early"))) + LOST + _line({"type": "agent_settled"})
    assert normalize.extract_final_message(stream) == "early", "control: an answer still parses"
    assert normalize.lost_after_final_message(stream)


def test_a_loss_with_no_message_is_a_loss():
    assert normalize.lost_after_final_message(SESSION + LOST)
    assert not normalize.lost_after_final_message(SESSION), "control: nothing lost"
