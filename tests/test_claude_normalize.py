"""Tolerant envelope reads: the failure test, answer, usage with cache counters, session id,
denials, structured answer. CLI drift degrades metadata rather than raising."""

from __future__ import annotations

import json

from amicus.backends.claude import normalize


def _env(**fields):
    base = {"type": "result", "subtype": "success", "is_error": False, "result": "hi"}
    base.update(fields)
    return json.dumps(base)


def test_parse_envelope_tolerates_garbage():
    assert normalize.parse_envelope("") is None
    assert normalize.parse_envelope("not json") is None
    assert normalize.parse_envelope("[1, 2]") is None
    assert normalize.parse_envelope('"a string"') is None
    assert normalize.parse_envelope(_env())["result"] == "hi"


def test_failure_detection_follows_is_error_or_subtype():
    assert normalize.is_failure_envelope(json.loads(_env())) is False
    assert normalize.is_failure_envelope({"result": "x"}) is False  # no subtype: legacy success
    assert normalize.is_failure_envelope(json.loads(_env(is_error=True))) is True
    assert normalize.is_failure_envelope(json.loads(_env(subtype="error_max_budget_usd"))) is True
    assert normalize.is_failure_envelope(json.loads(_env(subtype="error", is_error=False))) is True


def test_answer_is_a_string_or_empty():
    assert normalize.extract_answer(json.loads(_env(result="hello"))) == "hello"
    assert normalize.extract_answer(json.loads(_env(result={"a": 1}))) == ""
    assert normalize.extract_answer(json.loads(_env(result=None))) == ""
    assert normalize.extract_answer({}) == ""


def test_usage_maps_cache_counters_and_cost_and_tolerates_a_bad_block():
    env = json.loads(
        _env(
            total_cost_usd=0.0123,
            usage={
                "input_tokens": 100,
                "output_tokens": 50,
                "cache_read_input_tokens": 10,
                "cache_creation_input_tokens": 5,
            },
        )
    )
    usage = normalize.extract_usage(env)
    assert usage is not None
    assert (usage.input_tokens, usage.output_tokens) == (100, 50)
    assert (usage.cached_input_tokens, usage.cache_creation_input_tokens) == (10, 5)
    assert usage.cost_usd == 0.0123 and usage.total_tokens is None
    assert normalize.extract_usage(json.loads(_env())) is None
    only_cost = normalize.extract_usage(json.loads(_env(total_cost_usd=0.5, usage="nope")))
    assert only_cost is not None and only_cost.cost_usd == 0.5 and only_cost.input_tokens is None
    assert normalize.extract_usage(json.loads(_env(total_cost_usd=True))) is None
    weird = normalize.extract_usage(json.loads(_env(usage={"input_tokens": "100"})))
    assert weird is not None and weird.input_tokens is None


def test_session_id_and_denials():
    assert normalize.extract_session_id(json.loads(_env(session_id="s-1"))) == "s-1"
    assert normalize.extract_session_id(json.loads(_env(session_id=7))) is None
    assert normalize.extract_session_id({}) is None
    denials = normalize.extract_denials(json.loads(_env(permission_denials=[{"tool": "Bash"}])))
    assert denials == [{"tool": "Bash"}]
    assert normalize.extract_denials(json.loads(_env(permission_denials="x"))) == []
    assert normalize.extract_denials({}) == []


def test_denials_are_sanitized():
    raw = [{"tool": "Bash", "input": "export KEY=sk-" + "c" * 32 + "\x1b[31m"}]
    [denial] = normalize.extract_denials(json.loads(_env(permission_denials=raw)))
    assert "sk-" + "c" * 32 not in json.dumps(denial) and "\x1b" not in json.dumps(denial)


def test_structured_answer_parses_a_json_object_or_nothing():
    assert normalize.parse_structured('{"summary": "s"}') == {"summary": "s"}
    assert normalize.parse_structured('```json\n{"summary": "s"}\n```') == {"summary": "s"}
    assert normalize.parse_structured("prose") is None
    assert normalize.parse_structured("[1]") is None
    assert normalize.parse_structured(None) is None


def test_usage_prefers_model_usage_and_sums_it_across_models():
    """claude's own result schema names `modelUsage` as the accounting field and calls the
    top-level `usage` block main-loop-only; a budget stop zeroes the block beside a nonzero
    cost (#158). The conflicting top-level counts here are ignored, not merged."""
    env = json.loads(
        _env(
            total_cost_usd=0.03,
            usage={
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
            },
            modelUsage={
                "claude-a": {
                    "inputTokens": 4000,
                    "outputTokens": 50,
                    "cacheReadInputTokens": 300,
                    "cacheCreationInputTokens": 20,
                    "costUSD": 0.02,
                },
                "claude-b": {
                    "inputTokens": 700,
                    "outputTokens": 3,
                    "cacheReadInputTokens": 10,
                    "cacheCreationInputTokens": 1,
                    "costUSD": 0.01,
                },
            },
        )
    )
    usage = normalize.extract_usage(env)
    assert usage is not None
    assert (usage.input_tokens, usage.output_tokens) == (4700, 53)
    assert (usage.cached_input_tokens, usage.cache_creation_input_tokens) == (310, 21)
    assert usage.cost_usd == 0.03 and usage.total_tokens is None


def test_usage_never_reports_a_partial_model_sum_or_mixes_in_the_main_loop_block():
    """A field one model entry leaves out is None, never the sum of the entries that state it,
    and never the top-level block's number: the two blocks count different scopes."""
    env = json.loads(
        _env(
            total_cost_usd=0.01,
            usage={"input_tokens": 100, "output_tokens": 50, "cache_read_input_tokens": 10},
            modelUsage={
                "claude-a": {"inputTokens": 100, "outputTokens": 50},
                "claude-b": {"outputTokens": 7},
            },
        )
    )
    usage = normalize.extract_usage(env)
    assert usage is not None
    assert usage.input_tokens is None and usage.output_tokens == 57
    assert usage.cached_input_tokens is None and usage.cache_creation_input_tokens is None
    assert usage.cost_usd == 0.01
    # A sibling entry that is not a dict is a model whose counts cannot be read: modelUsage
    # stays the source (the block is still not consulted) and every count is None.
    mixed = normalize.extract_usage(
        json.loads(
            _env(
                total_cost_usd=0.01,
                usage={"input_tokens": 100, "output_tokens": 50},
                modelUsage={"claude-a": {"inputTokens": 100, "outputTokens": 50}, "b": "x"},
            )
        )
    )
    assert mixed is not None and mixed.cost_usd == 0.01
    assert (mixed.input_tokens, mixed.output_tokens, mixed.cached_input_tokens) == (
        None,
        None,
        None,
    )


def test_usage_falls_back_to_the_main_loop_block_only_without_a_usable_model_entry():
    """No dict-shaped model entry at all: the top-level block is read as before, and an
    explicit zero there is a zero, not a missing value."""
    block = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 4}
    for unusable in ("nope", [], {}, {"claude-a": "x"}, {"claude-a": 3}, None):
        usage = normalize.extract_usage(json.loads(_env(usage=block, modelUsage=unusable)))
        assert usage is not None, unusable
        assert (usage.input_tokens, usage.output_tokens) == (0, 0), unusable
        assert usage.cached_input_tokens == 4, unusable
    # A dict-shaped entry is usable even when its values are not ints: they read as None
    # rather than handing the field back to the block (bool is not an int here either).
    weird = normalize.extract_usage(
        json.loads(
            _env(
                usage=block,
                modelUsage={"claude-a": {"inputTokens": True, "outputTokens": "5"}},
            )
        )
    )
    assert weird is not None
    assert (weird.input_tokens, weird.output_tokens, weird.cached_input_tokens) == (
        None,
        None,
        None,
    )
    assert normalize.extract_usage(json.loads(_env(modelUsage={"claude-a": {}}))) is not None
    assert normalize.extract_usage(json.loads(_env(modelUsage={}))) is None
