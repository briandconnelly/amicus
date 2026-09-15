"""The surface-honesty test kit: phrase scanning against built wire surfaces."""

from __future__ import annotations

from amicus.sdk.testing import surface_honesty

PHRASES = ("kimi exec", "read-only sandbox")

WIRE = {
    "tools": [
        {"name": "kimi_consult", "description": "Runs kimi -p under a read-only agent profile."}
    ]
}


def test_clean_surface_passes():
    assert surface_honesty.find_forbidden_phrases(WIRE, PHRASES) == []


def test_forbidden_phrase_in_description_is_caught():
    dirty = {"tools": [{"name": "t", "description": "runs `kimi exec` in a read-only sandbox"}]}
    violations = surface_honesty.find_forbidden_phrases(dirty, PHRASES)
    assert len(violations) == 2
    assert "kimi exec" in violations[0]


def test_string_surface_accepted():
    assert surface_honesty.find_forbidden_phrases("plain wire text with kimi exec", PHRASES) != []


def test_matching_is_literal_and_case_sensitive():
    # "Kimi Exec" is not the banned phrase; the ban is exact vocabulary.
    assert surface_honesty.find_forbidden_phrases({"d": "Kimi Exec"}, PHRASES) == []


def test_contract_self_contradiction_check():
    violations = surface_honesty.find_contract_self_contradictions(
        PHRASES,
        {
            "readonly_honesty_statement": "read-only is enforced by a read-only sandbox",
            "implicit_context_disclosure": "clean",
        },
    )
    assert len(violations) == 1
    assert "readonly_honesty_statement" in violations[0]


def test_no_phrases_no_violations():
    assert surface_honesty.find_forbidden_phrases({"d": "anything"}, ()) == []
