"""Env declarations with a legacy shim: amicus name wins, legacy is read only when the
amicus name is unset (with a warning), a conflict is an error."""

from __future__ import annotations

import pytest

from amicus.config import envspec as es

NS = es.EnvNamespace(
    prefix="AMICUS_",
    vars=(
        es.EnvVar(
            "AMICUS_TIMEOUT_SECONDS",
            "deadline",
            default="300",
            legacy=("CODEX_IN_CLAUDE_TIMEOUT_SECONDS", "MOONBRIDGE_TIMEOUT_SECONDS"),
        ),
        es.EnvVar("AMICUS_MODEL", "model", legacy=()),
    ),
)


def test_namespace_validates_its_shape():
    with pytest.raises(ValueError, match="UPPER_SNAKE_"):
        es.EnvNamespace(prefix="amicus_", vars=())
    with pytest.raises(ValueError, match="must start with"):
        es.EnvNamespace(prefix="AMICUS_", vars=(es.EnvVar("OTHER_X", "d"),))
    assert NS.names() == ("AMICUS_TIMEOUT_SECONDS", "AMICUS_MODEL")


def test_amicus_name_wins_and_default_applies():
    r = NS.resolve("AMICUS_TIMEOUT_SECONDS", {"AMICUS_TIMEOUT_SECONDS": "60"})
    assert (r.value, r.source, r.warning) == ("60", "env", None)
    r = NS.resolve("AMICUS_TIMEOUT_SECONDS", {})
    assert (r.value, r.source) == ("300", "default")
    r = NS.resolve("AMICUS_MODEL", {})
    assert (r.value, r.source) == (None, "unset")


def test_legacy_is_read_only_when_amicus_is_unset_with_a_warning():
    r = NS.resolve("AMICUS_TIMEOUT_SECONDS", {"MOONBRIDGE_TIMEOUT_SECONDS": "45"})
    assert (r.value, r.source) == ("45", "legacy")
    assert "MOONBRIDGE_TIMEOUT_SECONDS" in r.warning
    assert es.LEGACY_REMOVAL_VERSION in r.warning
    # Both set and equal: the amicus value is used; the legacy copy is noted, not an error.
    r = NS.resolve(
        "AMICUS_TIMEOUT_SECONDS",
        {"AMICUS_TIMEOUT_SECONDS": "45", "MOONBRIDGE_TIMEOUT_SECONDS": "45"},
    )
    assert (r.value, r.source) == ("45", "env")
    assert r.warning and "ignored" in r.warning


def test_conflict_is_an_error():
    with pytest.raises(es.EnvConflictError, match="AMICUS_TIMEOUT_SECONDS"):
        NS.resolve(
            "AMICUS_TIMEOUT_SECONDS",
            {"AMICUS_TIMEOUT_SECONDS": "60", "CODEX_IN_CLAUDE_TIMEOUT_SECONDS": "45"},
        )
    with pytest.raises(es.EnvConflictError):
        NS.resolve(
            "AMICUS_TIMEOUT_SECONDS",
            {"CODEX_IN_CLAUDE_TIMEOUT_SECONDS": "1", "MOONBRIDGE_TIMEOUT_SECONDS": "2"},
        )


def test_unknown_name_is_a_programming_error():
    with pytest.raises(KeyError):
        NS.resolve("AMICUS_NOPE", {})


def test_placeholders():
    assert es.is_env_placeholder("${FOO}")
    assert es.is_env_placeholder(" ${FOO_bar1} ")
    assert not es.is_env_placeholder("$FOO")
    assert not es.is_env_placeholder("${1BAD}")
    assert not es.is_env_placeholder(None)


def test_report_collects_warnings_errors_and_placeholders():
    rep = NS.report(
        {
            "AMICUS_TIMEOUT_SECONDS": "60",
            "CODEX_IN_CLAUDE_TIMEOUT_SECONDS": "45",
            "AMICUS_MODEL": "${MODEL}",
        }
    )
    assert rep.placeholders == ["AMICUS_MODEL"]
    assert any("AMICUS_TIMEOUT_SECONDS" in e for e in rep.errors)
    assert rep.warnings == []
    rep = NS.report({"MOONBRIDGE_TIMEOUT_SECONDS": "45"})
    assert len(rep.warnings) == 1 and rep.errors == []
