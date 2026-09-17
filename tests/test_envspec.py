"""Env declarations with a legacy shim: amicus name wins, legacy is read only when the
amicus name is unset (with a warning), a conflict is an error. A `removed` name is a
tombstone: its presence is reported, its value is never read."""

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
        es.EnvVar(
            "AMICUS_ISOLATION",
            "isolation",
            default="inherit",
            removed=("CODEX_IN_CLAUDE_ISOLATION", "MOONBRIDGE_ISOLATION"),
        ),
    ),
)


def test_namespace_validates_its_shape():
    with pytest.raises(ValueError, match="UPPER_SNAKE_"):
        es.EnvNamespace(prefix="amicus_", vars=())
    with pytest.raises(ValueError, match="must start with"):
        es.EnvNamespace(prefix="AMICUS_", vars=(es.EnvVar("OTHER_X", "d"),))
    assert NS.names() == ("AMICUS_TIMEOUT_SECONDS", "AMICUS_MODEL", "AMICUS_ISOLATION")


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


# --- tombstones: a removed name is reported, never read ------------------------------------


def test_a_removed_name_is_never_read_and_its_presence_is_a_warning():
    r = NS.resolve("AMICUS_ISOLATION", {"CODEX_IN_CLAUDE_ISOLATION": "ignore-rules"})
    # The default applies: the old value is not consulted, however different it is.
    assert (r.value, r.source) == ("inherit", "default")
    assert r.warning is not None
    assert "CODEX_IN_CLAUDE_ISOLATION" in r.warning and "AMICUS_ISOLATION" in r.warning
    assert es.SIBLING_ALIASES_REMOVED_IN in r.warning
    # The warning names the removal release, not the guard's (movable) window version.
    assert es.LEGACY_REMOVAL_VERSION not in r.warning.replace(es.SIBLING_ALIASES_REMOVED_IN, "")


def test_a_removed_name_beside_the_amicus_name_is_not_a_conflict():
    r = NS.resolve(
        "AMICUS_ISOLATION",
        {"AMICUS_ISOLATION": "inherit", "CODEX_IN_CLAUDE_ISOLATION": "ignore-rules"},
    )
    assert (r.value, r.source) == ("inherit", "env")
    assert r.warning and "CODEX_IN_CLAUDE_ISOLATION" in r.warning
    two = NS.resolve(
        "AMICUS_ISOLATION",
        {"CODEX_IN_CLAUDE_ISOLATION": "a", "MOONBRIDGE_ISOLATION": "b"},
    )
    # Two disagreeing removed names are not a conflict either: neither value is read.
    assert (two.value, two.source) == ("inherit", "default")
    assert two.warning and "CODEX_IN_CLAUDE_ISOLATION" in two.warning
    assert "MOONBRIDGE_ISOLATION" in two.warning


def test_a_removed_name_holding_a_placeholder_is_unset():
    r = NS.resolve("AMICUS_ISOLATION", {"CODEX_IN_CLAUDE_ISOLATION": "${ISOLATION}"})
    assert (r.value, r.source, r.warning) == ("inherit", "default", None)


def test_report_carries_a_removed_name_warning_beside_the_others():
    rep = NS.report({"MOONBRIDGE_TIMEOUT_SECONDS": "45", "MOONBRIDGE_ISOLATION": "x"})
    assert rep.errors == [] and rep.placeholders == []
    assert len(rep.warnings) == 2
    assert any("MOONBRIDGE_ISOLATION" in w and "not read" in w for w in rep.warnings)


def test_the_removal_release_is_a_fixed_version_literal():
    """`SIBLING_ALIASES_REMOVED_IN` is history and `LEGACY_REMOVAL_VERSION` is the guard's
    window for any alias declared later; a tombstone warning must quote the first, which
    never moves, so moving the second cannot make an old warning false."""
    import re

    assert re.fullmatch(r"\d+\.\d+\.\d+", es.SIBLING_ALIASES_REMOVED_IN)
    assert es.SIBLING_ALIASES_REMOVED_IN == "0.4.0"
