"""The closed code catalog is derived from pontonier's taxonomy, not restated."""

from __future__ import annotations

from typing import get_args

from pontonier.backend.contract import BackendContract  # noqa: F401 - import smoke
from pontonier.conventions import envelope as pe

from amicus.schemas import codes, fingerprint


def test_backend_ids_are_the_v1_set_in_order():
    assert codes.BACKEND_IDS == ("codex", "kimi", "claude")
    assert get_args(codes.BackendId) == codes.BACKEND_IDS


def test_verbs_are_the_four_paid_kinds():
    assert codes.VERBS == ("consult", "review_changes", "adversarial_review", "delegate")


def test_error_codes_cover_the_universal_taxonomy_and_generalized_backend_codes():
    catalog = set(codes.ERROR_CODES)
    assert catalog >= pe.UNIVERSAL_CODES
    assert (
        frozenset(
            {
                "backend_not_found",
                "backend_auth_required",
                "backend_auth_indeterminate",
                "backend_rate_limited",
            }
        )
        == codes.GENERALIZED_BACKEND_CODES
    )
    assert catalog >= codes.GENERALIZED_BACKEND_CODES
    # Feature codes for features some v1 backend declares.
    assert {"invalid_model", "empty_response"} <= catalog
    # amicus-local codes.
    assert (
        frozenset(
            {
                "backend_unavailable",
                "feature_unsupported",
                "user_config_rejected",
                "budget_exceeded",
                "claude_permission_error",
                "api_key_invalid",
                "api_key_missing",
            }
        )
        == codes.LOCAL_CODES
    )
    assert catalog >= codes.LOCAL_CODES
    # No per-backend minted code leaks into the closed catalog.
    for backend in codes.BACKEND_IDS:
        assert pe.backend_codes(backend).isdisjoint(catalog)
    assert tuple(sorted(catalog)) == codes.ERROR_CODES
    assert set(get_args(codes.ErrorCode)) == catalog


def test_repair_steps_are_pontoniers_vocabulary():
    assert set(codes.REPAIR_STEPS) == pe.REPAIR_STEPS
    assert tuple(sorted(pe.REPAIR_STEPS)) == codes.REPAIR_STEPS
    assert set(get_args(codes.RepairStep)) == pe.REPAIR_STEPS


def test_generalize_rewrites_only_the_four_minted_codes():
    assert codes.generalize_code("codex_not_found", "codex") == "backend_not_found"
    assert codes.generalize_code("kimi_rate_limited", "kimi") == "backend_rate_limited"
    assert codes.generalize_code("claude_auth_indeterminate", "claude") == (
        "backend_auth_indeterminate"
    )
    assert codes.generalize_code("claude_auth_required", "claude") == "backend_auth_required"
    # A backend-local code is preserved verbatim.
    assert codes.generalize_code("user_config_rejected", "codex") == "user_config_rejected"
    # Another backend's minted code is not this backend's to rewrite.
    assert codes.generalize_code("codex_not_found", "kimi") == "codex_not_found"


def test_fingerprint_constants():
    assert fingerprint.FINGERPRINT == "amicus/0.1/schema-15"
    assert fingerprint.RESULT_FORMAT == 4
    assert fingerprint.JSON_SCHEMA_DIALECT == "https://json-schema.org/draft/2020-12/schema"
    assert fingerprint.LIFECYCLE_META_KEY == "dev.bconnelly.amicus/lifecycle"
    assert fingerprint.PROTOCOL_REVISION == "2026-07-28"
    assert "tool_names" in fingerprint.FINGERPRINT_COVERS
    assert "Release identity is excluded:" in fingerprint.FINGERPRINT_COVERS_DESC


def test_user_config_rejected_is_a_cataloged_local_code():
    from amicus.schemas.codes import ERROR_CODES, LOCAL_CODES

    assert "user_config_rejected" in LOCAL_CODES
    assert "user_config_rejected" in ERROR_CODES


def test_claude_local_codes_are_cataloged_and_never_generalized():
    for code in (
        "budget_exceeded",
        "claude_permission_error",
        "api_key_invalid",
        "api_key_missing",
    ):
        assert code in codes.LOCAL_CODES and code in codes.ERROR_CODES
        assert codes.generalize_code(code, "claude") == code
    assert codes.generalize_code("claude_rate_limited", "claude") == "backend_rate_limited"
