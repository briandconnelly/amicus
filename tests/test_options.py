"""backend_options: closed schema, per-backend applicability, allowed values (ADR 0002)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from amicus.schemas import options as o


def test_schema_is_closed_and_lists_every_option():
    schema = o.BackendOptions.model_json_schema()
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == {"isolation", "config_mode", "access", "max_budget_usd"}
    with pytest.raises(ValidationError):
        o.BackendOptions(sandbox="read-only")


def test_applicability_table():
    assert o.OPTION_ALLOWED_VALUES["isolation"] == {
        "codex": ("inherit", "ignore-config", "ignore-rules"),
        "kimi": ("inherit", "ignore-skills"),
    }
    assert o.OPTION_ALLOWED_VALUES["config_mode"] == {
        "claude": ("inherit", "scoped", "safe", "bare")
    }
    assert o.OPTION_ALLOWED_VALUES["access"] == {"claude": ("toolless", "readonly")}
    assert o.OPTION_ALLOWED_VALUES["max_budget_usd"] == {"claude": None}


def test_no_options_is_no_violation():
    assert o.option_violations("codex", None) == []
    assert o.option_violations("codex", o.BackendOptions()) == []
    assert o.resolved_options("codex", None) == {}


def test_inapplicable_key_names_the_key_and_the_backends_that_accept_it():
    [v] = o.option_violations("codex", o.BackendOptions(config_mode="safe"))
    assert v.field == "backend_options.config_mode"
    assert v.allowed_values is None
    assert "claude" in v.reason
    assert "codex" in v.reason


def test_wrong_value_for_this_backend_lists_its_allowed_values():
    [v] = o.option_violations("kimi", o.BackendOptions(isolation="ignore-rules"))
    assert v.field == "backend_options.isolation"
    assert v.allowed_values == ["inherit", "ignore-skills"]


def test_budget_bounds_are_in_the_schema_and_enforced():
    props = o.BackendOptions.model_json_schema()["properties"]["max_budget_usd"]
    branch = next(b for b in props["anyOf"] if b.get("type") == "number")
    assert (branch["minimum"], branch["maximum"]) == o.MAX_BUDGET_BOUNDS
    assert o.MAX_BUDGET_BOUNDS == (0.01, 5.0)
    with pytest.raises(ValidationError):
        o.BackendOptions(max_budget_usd=0)
    assert o.option_violations("claude", o.BackendOptions(max_budget_usd=1.5)) == []
    [v] = o.option_violations("kimi", o.BackendOptions(max_budget_usd=1.5))
    assert v.field == "backend_options.max_budget_usd"


def test_resolved_options_echo_only_set_keys():
    opts = o.BackendOptions(isolation="ignore-config")
    assert o.resolved_options("codex", opts) == {"isolation": "ignore-config"}


def test_several_violations_are_all_reported_in_field_order():
    fields = [
        v.field
        for v in o.option_violations(
            "kimi", o.BackendOptions(config_mode="safe", access="readonly")
        )
    ]
    assert fields == ["backend_options.config_mode", "backend_options.access"]
