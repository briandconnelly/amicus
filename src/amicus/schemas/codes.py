"""Closed value sets: backend ids, verbs, the error-code catalog, repair steps.

The catalog is DERIVED from pontonier's shared taxonomy so it cannot drift from it:
universal codes, the four per-backend codes generalized to ``backend_*`` (the concrete
backend rides ``error.backend``), the feature codes some v1 backend declares, and the
amicus-local codes. A backend-LOCAL code (codex's ``user_config_rejected``) joins this
catalog when its backend is ported, as a deliberate fingerprint bump.
"""

from __future__ import annotations

from typing import Literal

from pontonier.conventions import envelope as _pe

BACKEND_IDS: tuple[str, ...] = ("codex", "kimi", "claude")
BackendId = Literal["codex", "kimi", "claude"]

VERBS: tuple[str, ...] = ("consult", "review_changes", "adversarial_review", "delegate")
Verb = Literal["consult", "review_changes", "adversarial_review", "delegate"]

# The four codes pontonier mints per backend, generalized so the catalog stays closed.
_MINTED_SUFFIXES = ("_not_found", "_auth_required", "_auth_indeterminate", "_rate_limited")
GENERALIZED_BACKEND_CODES = frozenset(f"backend{s}" for s in _MINTED_SUFFIXES)

# Feature codes for the features the v1 backends declare (kimi: model_validation and
# empty_response_detection). Codex's `transfer` is deferred, so its codes are not minted.
_FEATURE_CODES = _pe.feature_codes(frozenset({"model_validation", "empty_response_detection"}))

LOCAL_CODES = frozenset(
    {
        # The tool is registered but its backend has not landed in this release.
        "not_implemented",
        # The registry recorded the backend as unavailable (import, conformance, config).
        "backend_unavailable",
        # The backend does not declare the feature this verb needs (e.g. claude+delegate).
        "feature_unsupported",
        # Codex-local (M1): the user's own CLI config carries a key or value the installed
        # CLI refuses at startup; zero spend. Preserved verbatim, never generalized.
        "user_config_rejected",
    }
)

ERROR_CODES: tuple[str, ...] = tuple(
    sorted(_pe.UNIVERSAL_CODES | GENERALIZED_BACKEND_CODES | _FEATURE_CODES | LOCAL_CODES)
)
ErrorCode = Literal[
    "backend_auth_indeterminate",
    "backend_auth_required",
    "backend_not_found",
    "backend_rate_limited",
    "backend_unavailable",
    "cli_contract_changed",
    "context_too_large",
    "empty_response",
    "extra_args_rejected",
    "feature_unsupported",
    "git_unavailable",
    "idempotency_conflict",
    "idempotency_in_progress",
    "idempotency_result_unavailable",
    "input_too_large",
    "internal_error",
    "invalid_arguments",
    "invalid_base",
    "invalid_commit",
    "invalid_json",
    "invalid_model",
    "invalid_paths",
    "invalid_reasoning_effort",
    "invalid_scope",
    "invalid_workspace_root",
    "job_cancelled",
    "job_failed",
    "job_not_found",
    "job_result_incompatible",
    "job_running",
    "job_timeout",
    "nonzero_exit",
    "not_a_git_repo",
    "not_implemented",
    "resource_not_found",
    "schema_violation",
    "timeout",
    "unexpanded_env_placeholder",
    "unsupported_detail",
    "unsupported_isolation",
    "unsupported_sandbox",
    "unsupported_tier",
    "user_config_rejected",
    "workspace_outside_roots",
    "worktree_error",
]

REPAIR_STEPS: tuple[str, ...] = tuple(sorted(_pe.REPAIR_STEPS))
RepairStep = Literal[
    "authenticate",
    "correct_arguments",
    "correct_config",
    "init_git_repo",
    "inspect_and_retry",
    "install_backend",
    "install_git",
    "list_jobs",
    "list_resources",
    "poll_job_status",
    "reduce_input",
    "retry_after_delay",
    "retry_then_report",
    "start_new_job",
    "update_plugin",
    "use_allowed_value",
    "use_new_idempotency_key",
    "use_workspace_in_roots",
]


def generalize_code(code: str, backend_id: str) -> str:
    """Rewrite ``<backend_id><suffix>`` to ``backend<suffix>`` for the four minted codes.

    Every other code — universal, feature, or backend-local — is returned verbatim."""
    for suffix in _MINTED_SUFFIXES:
        if code == f"{backend_id}{suffix}":
            return f"backend{suffix}"
    return code
