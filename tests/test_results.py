"""Result models: discriminators, published schemas, and the opaque job-result union."""

from __future__ import annotations

import json

import pytest
from jsonschema import Draft202012Validator

from amicus.schemas import results as r
from amicus.schemas.envelope import Meta, Repair
from amicus.schemas.fingerprint import JSON_SCHEMA_DIALECT

ALL_SCHEMAS = {
    "CONSULT_RESULT_SCHEMA": r.CONSULT_RESULT_SCHEMA,
    "REVIEW_RESULT_SCHEMA": r.REVIEW_RESULT_SCHEMA,
    "ADVERSARIAL_RESULT_SCHEMA": r.ADVERSARIAL_RESULT_SCHEMA,
    "DELEGATE_RESULT_SCHEMA": r.DELEGATE_RESULT_SCHEMA,
    "JOB_STARTED_SCHEMA": r.JOB_STARTED_SCHEMA,
    "JOB_STATUS_SCHEMA": r.JOB_STATUS_SCHEMA,
    "JOB_RESULT_SCHEMA": r.JOB_RESULT_SCHEMA,
    "JOB_LIST_SCHEMA": r.JOB_LIST_SCHEMA,
    "DRY_RUN_SCHEMA": r.DRY_RUN_SCHEMA,
    "DELEGATE_DRY_RUN_SCHEMA": r.DELEGATE_DRY_RUN_SCHEMA,
    "BACKENDS_SCHEMA": r.BACKENDS_SCHEMA,
    "MODEL_CATALOG_SCHEMA": r.MODEL_CATALOG_SCHEMA,
    "CAPABILITIES_SCHEMA": r.CAPABILITIES_SCHEMA,
}


@pytest.mark.parametrize("name", sorted(ALL_SCHEMAS))
def test_every_published_schema_is_valid_and_carries_the_dialect(name):
    s = ALL_SCHEMAS[name]
    Draft202012Validator.check_schema(s)
    assert s["$schema"] == JSON_SCHEMA_DIALECT
    assert s["anyOf"][-1]["properties"]["ok"] == {"const": False}


@pytest.mark.parametrize("name", sorted(ALL_SCHEMAS))
def test_error_catalog_is_not_inlined_per_tool(name):
    assert "backend_auth_required" not in json.dumps(ALL_SCHEMAS[name])


def test_paid_tool_discriminators():
    assert r.PAID_TOOLS == (
        "amicus_consult",
        "amicus_review_changes",
        "amicus_adversarial_review",
        "amicus_delegate",
    )
    assert r.ConsultResult(summary="s", meta=Meta()).tool == "amicus_consult"
    assert r.DelegateResult(summary="s", diff=None, meta=Meta()).tool == "amicus_delegate"
    review = r.ReviewResult(summary="s", verdict="pass", confidence="high", meta=Meta())
    assert review.review_status == "completed"


def test_job_result_schema_is_an_opaque_union_over_the_paid_tools():
    branch = r.JOB_RESULT_SCHEMA["anyOf"][0]
    assert set(branch["properties"]["tool"]["enum"]) == set(r.PAID_TOOLS)
    assert r.JOB_RESULT_SCHEMA["$defs"] == {}


def test_success_payloads_validate_against_their_schemas():
    meta = Meta(backend="codex")
    cases = [
        (r.CONSULT_RESULT_SCHEMA, r.ConsultResult(summary="s", meta=meta)),
        (
            r.REVIEW_RESULT_SCHEMA,
            r.ReviewResult(summary="s", verdict="concerns", confidence="low", meta=meta),
        ),
        (
            r.ADVERSARIAL_RESULT_SCHEMA,
            r.AdversarialReviewResult(summary="s", verdict="fail", confidence="high", meta=meta),
        ),
        (r.DELEGATE_RESULT_SCHEMA, r.DelegateResult(summary="s", diff="d", meta=meta)),
        (
            r.JOB_STARTED_SCHEMA,
            r.JobStarted(
                job_id="a" * 32,
                backend="codex",
                kind="amicus_consult",
                started_at="2026-09-04T00:00:00Z",
                deadline_seconds=1800,
                poll_after_ms=1000,
                expires_at=None,
                follow_up=Repair(next_step="poll_job_status", tool="amicus_job_status"),
                meta=meta,
            ),
        ),
    ]
    for schema, model in cases:
        Draft202012Validator(schema).validate(model.model_dump(mode="json"))
    adv = r.AdversarialReviewResult(summary="s", verdict="fail", confidence="high", meta=meta)
    assert adv.review_status == "completed" and adv.context_summary is None
    not_run = r.AdversarialReviewResult(
        summary="s", verdict="unknown", confidence="low", review_status="not_run", meta=meta
    )
    assert not_run.review_status == "not_run"


def test_capabilities_schema_opaques_tool_details_and_keeps_error_codes_required():
    props = r.CAPABILITIES_SCHEMA["anyOf"][0]["properties"]
    assert props["tool_details"]["type"] == "array"
    assert "capabilities-result" in props["tool_details"]["description"]
    assert "error_codes" in r.CAPABILITIES_SCHEMA["anyOf"][0]["required"]
    assert "ToolCapability" in r.CAPABILITIES_RESULT_SCHEMA["$defs"]


def test_backends_result_shape():
    entry = r.BackendEntry(
        id="codex",
        display_name="Codex",
        enabled=True,
        available=False,
        features=[],
        effects=r.EffectsInfo(paid_calls_destructive=False, job_reads_read_only=True),
        options=[],
    )
    res = r.BackendsResult(backends=[entry], unavailable=[], env_warnings=[], config_errors=[])
    assert res.ok is True and res.backends[0].status is None
