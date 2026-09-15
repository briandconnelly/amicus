"""BackendContract: construction validation and signature compilation."""

from __future__ import annotations

import pytest

from amicus.sdk.backend.contract import (
    BackendContract,
    ExtraArgsPolicy,
    FailureSignatures,
    IsolationPolicy,
    Limits,
    ModelCatalog,
)


def make_contract(**overrides) -> BackendContract:
    base = {
        "backend_id": "fake",
        "display_name": "Fake",
        "bin_name": "fakecli",
        "env_prefix": "FAKEBRIDGE_",
        "exec_argv_prefix": (),
        "always_send_flags": ("--prompt",),
        "help_gated_flags": ("--model",),
        "forbidden_surface_phrases": ("fake exec",),
        "supported_features": frozenset({"delegate"}),
        "readonly_honesty_statement": "Read-only is a tool allowlist, not confinement.",
        "implicit_context_disclosure": "The CLI auto-loads AGENTS.md from the workspace.",
        "structured_output": "prompt_append",
        "model_catalog": ModelCatalog(
            strategy="live_probe",
            model_identifier_authority="authoritative",
            effort_metadata_authority="advisory",
        ),
        "isolation_policy": IsolationPolicy.WORKTREE_ALL_TIERS,
        "needs_orphan_sweep": True,
        "effort_silently_ignored_upstream": True,
    }
    base.update(overrides)
    return BackendContract(**base)


def test_valid_contract_constructs():
    c = make_contract()
    assert c.backend_id == "fake"
    assert c.extra_args == ExtraArgsPolicy()
    assert c.limits == Limits()


@pytest.mark.parametrize("bad_id", ["Fake", "9lives", "with-dash", ""])
def test_backend_id_must_be_lowercase_identifier(bad_id: str):
    with pytest.raises(ValueError, match="lowercase identifier"):
        make_contract(backend_id=bad_id)


@pytest.mark.parametrize("bad_prefix", ["fake_", "FAKE", "Fake_"])
def test_env_prefix_shape_enforced(bad_prefix: str):
    with pytest.raises(ValueError, match="UPPER_SNAKE_"):
        make_contract(env_prefix=bad_prefix)


def test_empty_honesty_statement_rejected():
    with pytest.raises(ValueError, match="actual guarantee"):
        make_contract(readonly_honesty_statement="   ")


def test_empty_disclosure_rejected():
    with pytest.raises(ValueError, match="auto-loads"):
        make_contract(implicit_context_disclosure="")


def test_failure_signatures_compile():
    sigs = FailureSignatures(
        auth=(r"not logged in", r"401"),
        contract_drift=(r"unknown option",),
        rate_limited=(r"rate limit",),
        retry_after_ms=r"retry after (\d+)ms",
    )
    compiled = sigs.compiled()
    assert len(compiled["auth"]) == 2
    assert compiled["contract_drift"][0].search("error: unknown option '--sandbox'")


def test_contract_is_frozen():
    c = make_contract()
    with pytest.raises(AttributeError):
        c.backend_id = "other"  # type: ignore[misc]
