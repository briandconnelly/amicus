"""Backend-neutral structured-output classification (`amicus.schemas.structured`).

A JSON object that repeats a key does not denote one value: plain `json.loads` keeps the
last member silently, so a populated `findings` followed by `findings: []` would reach
`coerce_findings` as empty with nothing for `findings_diagnostics` to see (#51). The
classifier refuses it instead."""

from __future__ import annotations

from amicus.schemas.structured import classify_structured

_FINDING = '{"title":"t","severity":"high","file":"a.py","line":3,"evidence":"e"}'


def test_object_without_a_repeated_key_is_ok():
    status, parsed = classify_structured(f'{{"summary":"s","findings":[{_FINDING}]}}')
    assert status == "ok" and parsed is not None and len(parsed["findings"]) == 1


def test_repeated_top_level_key_is_invalid_json_not_last_value_wins():
    text = f'{{"summary":"s","findings":[{_FINDING}],"findings":[]}}'
    assert classify_structured(text) == ("invalid_json", None)


def test_repeated_key_nested_inside_a_finding_is_invalid_json():
    text = '{"summary":"s","findings":[{"title":"a","title":"b"}]}'
    assert classify_structured(text) == ("invalid_json", None)


def test_repeated_key_inside_a_code_fence_is_still_refused():
    text = '```json\n{"summary":"a","summary":"b"}\n```'
    assert classify_structured(text) == ("invalid_json", None)


def test_same_key_in_sibling_objects_is_not_a_repeat():
    text = f'{{"summary":"s","findings":[{_FINDING},{_FINDING}]}}'
    status, parsed = classify_structured(text)
    assert status == "ok" and parsed is not None and len(parsed["findings"]) == 2


def test_escaped_spelling_of_a_key_is_the_same_key():
    # Identity is judged after string decoding, so "findings" repeats "findings".
    text = f'{{"findings":[{_FINDING}],"\\u0066indings":[]}}'
    assert classify_structured(text) == ("invalid_json", None)


def test_one_object_enclosed_in_prose_is_read():
    # #139: a preamble, a fence mid-message, or a sign-off no longer loses the object.
    for text in (
        'Here is the review:\n{"summary":"s"}',
        '{"summary":"s"}\nLet me know if you need more.',
        'Review:\n```json\n{"summary":"s"}\n```\nDone.',
    ):
        assert classify_structured(text) == ("ok", {"summary": "s"}), text


def test_a_truncated_answer_never_promotes_a_nested_object():
    # The outer object never closes, so the span from the first `{` is unparseable; a
    # complete finding inside it must not be read as the whole answer.
    text = f'{{"summary":"s","findings":[{_FINDING}'
    assert classify_structured(text) == ("invalid_json", None)
    text = f'Sure.\n{{"summary":"s","findings":[{_FINDING}]'
    assert classify_structured(text) == ("invalid_json", None)


def test_two_enclosed_objects_are_not_read_as_one():
    text = 'First {"summary":"a"} then {"summary":"b"}'
    assert classify_structured(text) == ("invalid_json", None)


def test_a_repeated_key_is_refused_inside_prose_too():
    text = 'Here:\n{"summary":"a","summary":"b"}\nDone.'
    assert classify_structured(text) == ("invalid_json", None)


def test_a_brace_in_the_surrounding_prose_is_refused_not_guessed_around():
    text = '{"summary":"s"}\nNote: set {timeout} higher.'
    assert classify_structured(text) == ("invalid_json", None)


def test_an_enclosed_non_object_is_not_read():
    assert classify_structured("Answer: [1, 2]") == ("invalid_json", None)
