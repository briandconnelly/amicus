"""published_schema: success branches plus one opaque error branch, noise stripped."""

from __future__ import annotations

from typing import Literal

import pytest
from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field

from amicus.schemas import publish
from amicus.schemas.envelope import Meta, SuccessBase


class Inner(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str  # a real field named `title` must survive the title-strip
    n: int = Field(default=0, description="generated noise to strip")


class One(SuccessBase):
    tool: Literal["one"] = "one"
    summary: str
    inner: Inner | None = None


class Two(SuccessBase):
    tool: Literal["two"] = "two"
    summary: str
    items: list[Inner] = Field(default_factory=list)


def test_single_model_schema_shape():
    s = publish.published_schema(One)
    assert s["$schema"] == publish.JSON_SCHEMA_DIALECT
    assert s["required"] == ["ok"]
    assert s["anyOf"][-1] == publish.OPAQUE_ERROR_BRANCH
    success = s["anyOf"][0]
    assert success["properties"]["meta"] == publish.OPAQUE_META
    assert "Meta" not in s["$defs"]
    assert "Inner" in s["$defs"]
    # Property NAMES named like annotation keywords survive; annotations are stripped.
    assert "title" in s["$defs"]["Inner"]["properties"]
    assert "description" not in s["$defs"]["Inner"]["properties"]["n"]
    assert "default" not in s["$defs"]["Inner"]["properties"]["n"]
    Draft202012Validator.check_schema(s)


def test_union_schema_keeps_both_success_branches():
    s = publish.published_schema(One, Two)
    assert len(s["anyOf"]) == 3
    assert {b["properties"]["tool"]["const"] for b in s["anyOf"][:2]} == {"one", "two"}


def test_opaque_fields_replace_named_properties_and_prune_their_defs():
    stub = {"type": "array", "description": "elsewhere"}
    publish.KEPT_DESCRIPTIONS.add("elsewhere")
    s = publish.published_schema(Two, opaque_fields={"items": stub})
    assert s["anyOf"][0]["properties"]["items"] == stub
    assert "Inner" not in s["$defs"]


def test_error_envelope_validates_against_any_published_schema():
    s = publish.published_schema(One)
    env = {
        "ok": False,
        "error": {
            "code": "internal_error",
            "message": "m",
            "temporary": True,
            "retry_after_ms": None,
        },
        "meta": {},
    }
    Draft202012Validator(s).validate(env)
    with pytest.raises(Exception, match="is not valid"):
        Draft202012Validator(s).validate({"ok": True})


def test_success_payload_validates():
    s = publish.published_schema(One)
    payload = One(summary="s", meta=Meta()).model_dump(mode="json")
    Draft202012Validator(s).validate(payload)
