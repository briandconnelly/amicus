"""Tolerant stream-json parsing: final message, error text, usage, session id, structured."""

from __future__ import annotations

from amicus.backends.kimi import normalize

VERSION = '{"role":"meta","type":"system.version","version":"0.41.0"}\n'
RESUME = '{"role":"meta","type":"session.resume_hint","session_id":"session_abc"}\n'


def test_last_assistant_text_wins_and_tool_call_only_lines_are_skipped():
    events = (
        VERSION
        + '{"role":"assistant","tool_calls":[{"id":"Read:0"}]}\n'
        + '{"role":"tool","tool_call_id":"Read:0","content":"file body"}\n'
        + '{"role":"assistant","content":"first"}\n'
        + '{"role":"assistant","content":"  final  "}\n'
        + '{"role":"assistant","content":"","tool_calls":[]}\n'
        + '{"type":"goal.summary","tokensUsed":5}\n'
        + RESUME
    )
    assert normalize.extract_final_message(events) == "final"


def test_no_assistant_text_returns_none_and_garbage_is_skipped():
    assert normalize.extract_final_message(VERSION + RESUME) is None
    assert normalize.extract_final_message("{not json\n[1,2]\nplain text\n") is None
    assert normalize.extract_final_message("") is None


def test_session_id_and_usage_are_read_tolerantly():
    events = (
        VERSION
        + (
            '{"type":"token_count","usage":{"input_tokens":100,"output_tokens":20,'
            '"cached_input_tokens":80}}\n'
        )
        + RESUME
    )
    usage, session_id = normalize.parse_event_metadata(events)
    assert session_id == "session_abc"
    assert usage is not None
    assert (usage.input_tokens, usage.output_tokens, usage.cached_input_tokens) == (100, 20, 80)
    assert usage.total_tokens == 120  # derived: kimi emits no total
    explicit = '{"type":"x","usage":{"input_tokens":1,"output_tokens":1,"total_tokens":9}}\n'
    assert normalize.parse_event_metadata(explicit)[0].total_tokens == 9
    assert normalize.parse_event_metadata(VERSION + RESUME) == (None, "session_abc")
    assert normalize.parse_event_metadata("") == (None, None)


def test_error_message_is_unwrapped_from_error_events():
    events = '{"type":"turn.failed","message":"{\\"error\\": {\\"message\\": \\"inner text\\"}}"}\n'
    assert normalize.extract_error_message(events) == "inner text"
    plain = '{"type":"error","error":{"message":"plain"}}\n'
    assert normalize.extract_error_message(plain) == "plain"
    assert normalize.extract_error_message(VERSION) is None
    assert normalize.extract_error_message('{"type":"error","message":"{broken"}\n') == "{broken"


def test_parse_structured_accepts_fenced_objects_only():
    assert normalize.parse_structured('```json\n{"summary": "s"}\n```') == {"summary": "s"}
    assert normalize.parse_structured("[1, 2]") is None
    assert normalize.parse_structured("prose") is None
    assert normalize.parse_structured(None) is None


# --- lost_after_final_message (#198) ----------------------------------------------------
LOST = "[output truncated]\n"
CUT = '{"role":"assistant","content":"the true fin…[line truncated]\n'


def test_a_loss_before_the_final_message_leaves_it_trusted():
    """The capture keeps the head and tail: a middle cut leaves the final message whole."""
    events = VERSION + '{"role":"assistant","content":"early"}\n' + LOST
    events += '{"role":"assistant","content":"final"}\n' + RESUME
    assert normalize.extract_final_message(events) == "final"
    assert not normalize.lost_after_final_message(events)


def test_a_loss_after_the_final_message_means_a_later_one_may_be_what_was_lost():
    events = VERSION + '{"role":"assistant","content":"early"}\n' + LOST + RESUME
    assert normalize.extract_final_message(events) == "early", "control: an answer still parses"
    assert normalize.lost_after_final_message(events)


def test_a_cut_line_after_the_final_message_is_a_loss_too():
    """One line over the per-line cap is cut and no longer parses, so the message before it
    is what extract_final_message takes."""
    events = VERSION + '{"role":"assistant","content":"early"}\n' + CUT + RESUME
    assert normalize.extract_final_message(events) == "early"
    assert normalize.lost_after_final_message(events)


def test_a_loss_with_no_message_at_all_is_a_loss():
    assert normalize.lost_after_final_message(VERSION + LOST + RESUME)
    assert not normalize.lost_after_final_message(VERSION + RESUME), "control: nothing lost"


def test_tool_call_only_and_empty_assistant_lines_do_not_clear_a_loss():
    """They are not answers, so extract_final_message skips them, and they must not count
    as the answer line that follows the loss."""
    events = VERSION + '{"role":"assistant","content":"early"}\n' + LOST
    events += '{"role":"assistant","tool_calls":[{"id":"Read:0"}]}\n'
    events += '{"role":"assistant","content":"  "}\n' + RESUME
    assert normalize.extract_final_message(events) == "early"
    assert normalize.lost_after_final_message(events)
