"""Host naming, framings, prompt builders, and the model-facing output schemas."""

from __future__ import annotations

import pytest
from jsonschema import Draft202012Validator

from amicus.orchestration import prompts as p


@pytest.mark.parametrize(
    ("client", "override", "expected"),
    [
        ("claude-code", None, "Claude Code"),
        ("Claude Code", None, "Claude Code"),
        ("codex-cli", None, "Codex"),
        ("codex", None, "Codex"),
        ("kimi-code", None, "Kimi"),
        ("Some IDE", None, "Some IDE"),
        ("weird\x1bname", None, "weirdname"),
        ("x" * 100, None, "x" * 64),
        (None, None, p.NEUTRAL_HOST_NAME),
        ("   ", None, p.NEUTRAL_HOST_NAME),
        ("claude-code", "MyHost", "MyHost"),
    ],
)
def test_host_display_name(client, override, expected):
    assert p.host_display_name(client, override) == expected


def test_prompts_name_the_host_and_frame_untrusted_data():
    consult = p.consult_prompt("Claude Code", "Why?", "some context")
    assert consult.startswith("You are giving Claude Code an independent second opinion")
    assert "## Question\nWhy?" in consult and (
        "## Context (untrusted data)\nsome context" in consult
    )
    review = p.review_prompt("Codex", "DIFF", p.review_label("branch", "main", None), "")
    assert "Diff under review (branch main...HEAD)" in review and ("Author-provided" not in review)
    delegate = p.delegate_prompt("Caller", "Do it.")
    assert (
        delegate.startswith("Caller is delegating a coding task") and "## Task\nDo it." in delegate
    )
    assert p.review_label("commit", None, "abc") == "commit abc" and (
        p.review_label("working_tree", None, None) == "working_tree"
    )


def test_output_schemas_are_strict_and_match_the_finding_model():
    for schema in (p.CONSULT_OUTPUT_SCHEMA, p.REVIEW_OUTPUT_SCHEMA):
        Draft202012Validator.check_schema(schema)
        assert schema["additionalProperties"] is False
        assert set(schema["properties"]) == set(schema["required"])
        item = schema["properties"]["findings"]["items"]
        assert set(item["properties"]) == {
            "title",
            "severity",
            "file",
            "line",
            "evidence",
            "suggestion",
        }
        assert (
            set(item["required"]) == set(item["properties"])
            and item["additionalProperties"] is False
        )
    assert "verdict" in p.REVIEW_OUTPUT_SCHEMA["properties"] and (
        "verdict" not in p.CONSULT_OUTPUT_SCHEMA["properties"]
    )
    assert p.REVIEW_OUTPUT_SCHEMA["properties"]["verdict"]["enum"] == [
        "pass",
        "concerns",
        "fail",
        "unknown",
    ]


@pytest.mark.parametrize(
    ("focus", "extra_context", "expected"),
    [
        (None, None, None),
        ("", "", None),
        ("   ", "   ", None),
        ("locking", None, "Focus this review on: locking"),
        ("locking", "", "Focus this review on: locking"),
        (None, "some context", "some context"),
        ("", "some context", "some context"),
        ("locking", "some context", "Focus this review on: locking\n\nsome context"),
    ],
)
def test_review_caller_text_combinations(focus, extra_context, expected):
    assert p.review_caller_text(focus, extra_context) == expected


def test_review_caller_text_strips_focus_and_context():
    assert p.review_caller_text("  locking  ", "  ctx  ") == "Focus this review on: locking\n\nctx"
