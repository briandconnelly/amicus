"""Unit coverage for amicus.tools._meta: stability tiers, lifecycle _meta, annotations,
and the base Meta builder (exercised end-to-end once real tools land in Task 12)."""

from __future__ import annotations

from amicus import config
from amicus.schemas.fingerprint import LIFECYCLE_META_KEY
from amicus.tools import _meta


def test_tool_stability_falls_back_to_server_stability():
    assert _meta.tool_stability("amicus_job_status") == "experimental"
    assert _meta.tool_stability("amicus_consult") == _meta.SERVER_STABILITY


def test_lifecycle_meta_carries_the_stability_tier():
    assert _meta.lifecycle_meta("amicus_consult") == {LIFECYCLE_META_KEY: {"stability": "alpha"}}


def test_effects_for_is_destructive_when_any_enabled_backend_is():
    destructive = config.settings({"AMICUS_BACKENDS": "claude"})
    benign = config.settings({"AMICUS_BACKENDS": "codex,kimi"})
    assert _meta.effects_for(destructive).paid_calls_destructive is True
    assert _meta.effects_for(benign).paid_calls_destructive is False
    assert _meta.effects_for(benign).job_reads_read_only is True


def test_effects_for_treats_an_unknown_backend_as_worst_case():
    settings = config.settings({"AMICUS_BACKENDS": "codex"})
    object.__setattr__(settings, "enabled_backends", ("codex", "third_party"))
    assert _meta.effects_for(settings).paid_calls_destructive is True


def test_annotations_for_each_kind():
    settings = config.settings({"AMICUS_BACKENDS": "codex"})
    active = _meta.annotations_for("active", settings)
    free = _meta.annotations_for("free", settings)
    job_read = _meta.annotations_for("job_read", settings)
    job_consume = _meta.annotations_for("job_consume", settings)
    job_cancel = _meta.annotations_for("job_cancel", settings)
    assert active["destructiveHint"] is False
    assert free["readOnlyHint"] is True
    assert job_read["readOnlyHint"] is True
    assert job_consume["idempotentHint"] is False
    assert job_cancel["idempotentHint"] is True


def test_base_meta_carries_backend_and_timeout():
    settings = config.settings({"AMICUS_TIMEOUT_SECONDS": "42"})
    meta = _meta.base_meta(settings, backend="codex", model="gpt")
    assert meta.backend == "codex"
    assert meta.timeout_seconds == 42
    assert meta.model == "gpt"
