"""Shared error taxonomy for agent bridges: codes and symbolic repair rules.

This module owns WHAT can go wrong and what the machine-actionable next step is.
It deliberately does NOT own wire serialization: the bridges' ``ErrorInfo``
shapes are incompatible closed contracts (one uses ``repair: str`` +
``retryable`` + a typed ``action``; the others use ``temporary`` + a structured
repair object), so each consumer keeps its own serializer and builds it from
these rules.

Three code tiers:

* UNIVERSAL_CODES — the verified intersection across all bridges.
* backend codes — minted per backend id (``{id}_not_found``, ``{id}_auth_required``,
  ``{id}_auth_indeterminate``, ``{id}_rate_limited``).
* feature codes — minted only when the backend declares the feature
  (``transfer`` -> ``transfer_*``; ``model_validation`` -> ``invalid_model``;
  ``empty_response_detection`` -> ``empty_response``).

Repair prose that must name a bridge's own tools or commands is parameterized
through :class:`BackendErrorVocabulary` so the minted rules match each bridge's
existing wire text.
"""

from __future__ import annotations

from dataclasses import dataclass

# Symbolic next steps shared across bridges. ``install_backend`` and
# ``authenticate`` are the generic forms; a consumer whose wire vocabulary spells
# a backend-specific step (codex-in-claude emits ``install_codex``) maps the
# symbol in its serializer — the WIRE value is the consumer's contract, the
# symbol is the shared taxonomy's.
REPAIR_STEPS = frozenset(
    {
        "retry_after_delay",
        "correct_arguments",
        "use_allowed_value",
        "reduce_input",
        "use_workspace_in_roots",
        "poll_job_status",
        "list_jobs",
        "list_resources",
        "start_new_job",
        "authenticate",
        "install_backend",
        "install_git",
        "init_git_repo",
        "update_plugin",
        "correct_config",
        "inspect_and_retry",
        "retry_then_report",
        "use_new_idempotency_key",
    }
)


@dataclass(frozen=True)
class RepairRule:
    """The machine-actionable recovery for one error code.

    ``temporary``: True only when re-issuing the IDENTICAL call may succeed
    later. ``tool``: the tool a repair should steer to, when one is fixed per
    code (None otherwise). ``alternative``: default human/agent prose.
    """

    next_step: str
    tool: str | None
    temporary: bool
    alternative: str

    def __post_init__(self) -> None:
        if self.next_step not in REPAIR_STEPS:
            raise ValueError(f"unknown repair step {self.next_step!r}")


@dataclass(frozen=True)
class BackendErrorVocabulary:
    """The backend-specific words the minted rules need.

    ``install_hint``/``login_hint`` are complete sentences (they carry the URL or
    command); ``status_tool`` is the bridge's readiness tool name, referenced by
    several rules' prose.
    """

    backend_id: str
    display_name: str
    install_hint: str
    login_hint: str
    status_tool: str


def backend_codes(backend_id: str) -> frozenset[str]:
    """The per-backend code names minted for ``backend_id``."""
    return frozenset(
        {
            f"{backend_id}_not_found",
            f"{backend_id}_auth_required",
            f"{backend_id}_auth_indeterminate",
            f"{backend_id}_rate_limited",
        }
    )


# Features a BackendContract may declare that carry their own error codes.
FEATURE_CODES: dict[str, frozenset[str]] = {
    "transfer": frozenset({"transfer_unsupported", "transfer_failed", "transfer_incomplete"}),
    "model_validation": frozenset({"invalid_model"}),
    "empty_response_detection": frozenset({"empty_response"}),
}


def feature_codes(features: frozenset[str]) -> frozenset[str]:
    """Codes minted for the declared feature set. Unknown features mint nothing —
    they may be consumer-local concepts the taxonomy does not govern."""
    out: set[str] = set()
    for feature in features:
        out |= FEATURE_CODES.get(feature, frozenset())
    return frozenset(out)


# The verified intersection across codex-in-claude, moonbridge, and (for the
# codes it models) claude-in-codex. Prose that names a bridge tool is filled in
# by ``repair_rules`` from the vocabulary.
UNIVERSAL_CODES = frozenset(
    {
        "internal_error",
        "invalid_arguments",
        "invalid_scope",
        "invalid_base",
        "invalid_commit",
        "invalid_paths",
        "invalid_workspace_root",
        "workspace_outside_roots",
        "unexpanded_env_placeholder",
        "unsupported_tier",
        "unsupported_sandbox",
        "unsupported_isolation",
        "unsupported_detail",
        "invalid_reasoning_effort",
        "input_too_large",
        "context_too_large",
        "not_a_git_repo",
        "git_unavailable",
        "worktree_error",
        "timeout",
        "nonzero_exit",
        "resource_not_found",
        "invalid_json",
        "schema_violation",
        "cli_contract_changed",
        "extra_args_rejected",
        "job_not_found",
        "job_running",
        "job_cancelled",
        "job_timeout",
        "job_failed",
        "job_result_incompatible",
        "idempotency_conflict",
        "idempotency_result_unavailable",
        "idempotency_in_progress",
    }
)


def repair_rules(
    vocab: BackendErrorVocabulary, features: frozenset[str] = frozenset()
) -> dict[str, RepairRule]:
    """The full code -> RepairRule table for one bridge: universal codes, this
    backend's minted codes, and the declared features' codes."""
    b = vocab.backend_id
    status = vocab.status_tool
    rules: dict[str, RepairRule] = {
        # --- backend-minted ---------------------------------------------------
        f"{b}_not_found": RepairRule("install_backend", None, False, vocab.install_hint),
        f"{b}_auth_required": RepairRule("authenticate", None, False, vocab.login_hint),
        f"{b}_auth_indeterminate": RepairRule(
            # NOT `authenticate`: the caller may well be logged in — the probe,
            # not the session, failed to answer, so steering to login would be a
            # false repair. temporary=True is load-bearing: emission sites must
            # rule a missing binary out first (that is `{b}_not_found`), leaving
            # "the probe didn't answer in time" — which clears itself.
            "inspect_and_retry",
            None,
            True,
            f"The auth probe did not complete, so auth could not be confirmed. "
            f"Run {status} to check, then retry.",
        ),
        f"{b}_rate_limited": RepairRule(
            "retry_after_delay",
            None,
            True,
            f"{vocab.display_name} reports a rate limit; wait and retry, honoring "
            "retry_after_ms when present.",
        ),
        # --- universal --------------------------------------------------------
        "internal_error": RepairRule(
            "retry_then_report", None, True, "Retry; if it persists, report a bug."
        ),
        "invalid_arguments": RepairRule(
            "correct_arguments", None, False, "Correct the listed argument(s) and retry."
        ),
        "invalid_scope": RepairRule(
            "correct_arguments", None, False, "Correct the scope argument."
        ),
        "invalid_base": RepairRule("correct_arguments", None, False, "Correct the base argument."),
        "invalid_commit": RepairRule(
            "correct_arguments", None, False, "Correct the commit argument."
        ),
        "invalid_paths": RepairRule(
            "correct_arguments", None, False, "Correct the paths argument."
        ),
        "invalid_workspace_root": RepairRule(
            "correct_arguments", None, False, "Pass an existing directory as workspace_root."
        ),
        "workspace_outside_roots": RepairRule(
            "use_workspace_in_roots",
            None,
            False,
            "Pass a workspace_root inside one of the client's advertised roots.",
        ),
        "unexpanded_env_placeholder": RepairRule(
            "update_plugin",
            None,
            False,
            "Set the referenced environment variable, or fix the plugin config.",
        ),
        "unsupported_tier": RepairRule(
            "use_allowed_value", None, False, "Pass one of the tier's allowed_values."
        ),
        "unsupported_sandbox": RepairRule(
            "use_allowed_value", None, False, "Pass one of the sandbox's allowed_values."
        ),
        "unsupported_isolation": RepairRule(
            "use_allowed_value", None, False, "Pass one of the isolation's allowed_values."
        ),
        "unsupported_detail": RepairRule(
            "use_allowed_value", None, False, "Pass one of the detail's allowed_values."
        ),
        "invalid_reasoning_effort": RepairRule(
            "use_allowed_value",
            None,
            False,
            "Pass a reasoning effort the selected model supports.",
        ),
        "input_too_large": RepairRule(
            "reduce_input", None, False, "Shorten the input below the byte limit and retry."
        ),
        "context_too_large": RepairRule(
            "reduce_input",
            None,
            False,
            "Narrow the diff scope (paths/base) so the gathered context fits the limit.",
        ),
        "not_a_git_repo": RepairRule(
            "init_git_repo",
            None,
            False,
            "Run inside a git repository, or pass a workspace_root that is one.",
        ),
        "git_unavailable": RepairRule(
            "install_git", None, False, "Install git and ensure it is on PATH."
        ),
        "worktree_error": RepairRule(
            "inspect_and_retry",
            None,
            True,
            "Creating or seeding the throwaway worktree failed; inspect the detail and retry.",
        ),
        "timeout": RepairRule(
            "retry_after_delay",
            None,
            True,
            "The run exceeded its deadline; retry, raise timeout_seconds, or use the "
            "async variant.",
        ),
        "nonzero_exit": RepairRule(
            "inspect_and_retry",
            None,
            True,
            f"The CLI exited nonzero; inspect the detail, run {status}, then retry.",
        ),
        "resource_not_found": RepairRule(
            "list_resources", None, False, "List the server's resources for valid URIs."
        ),
        "invalid_json": RepairRule(
            "retry_then_report", None, True, "Retry; if it persists, report a bug."
        ),
        "schema_violation": RepairRule(
            "retry_then_report",
            None,
            True,
            "The model's output did not match the schema; retry, then report a bug.",
        ),
        "cli_contract_changed": RepairRule(
            "update_plugin",
            None,
            False,
            f"The installed CLI no longer matches this plugin's contract. Run {status} "
            "and update the plugin or pin a supported CLI version.",
        ),
        "extra_args_rejected": RepairRule(
            "correct_config",
            None,
            False,
            "Fix the operator-configured extra args; values are never echoed.",
        ),
        # --- jobs -------------------------------------------------------------
        "job_not_found": RepairRule(
            "list_jobs", None, False, "List jobs to recover a valid job_id."
        ),
        "job_running": RepairRule(
            "poll_job_status", None, True, "Poll job status until result_available."
        ),
        "job_cancelled": RepairRule("start_new_job", None, False, "Start a new job."),
        "job_timeout": RepairRule("start_new_job", None, False, "Start a new job."),
        "job_failed": RepairRule(
            "inspect_and_retry", None, False, "Inspect the stored failure, then start a new job."
        ),
        "job_result_incompatible": RepairRule(
            "start_new_job",
            None,
            False,
            "The stored result predates this server version; start a new job.",
        ),
        "idempotency_conflict": RepairRule(
            "use_new_idempotency_key",
            None,
            False,
            "This key was used with different arguments; pass a new idempotency_key.",
        ),
        "idempotency_result_unavailable": RepairRule(
            "use_new_idempotency_key",
            None,
            False,
            "The original result is no longer retained; retry with a new idempotency_key.",
        ),
        "idempotency_in_progress": RepairRule(
            "poll_job_status", None, True, "The original run is still active; poll its job."
        ),
    }
    if "transfer" in features:
        rules["transfer_unsupported"] = RepairRule(
            "update_plugin",
            None,
            False,
            "This CLI/account does not support session transfer.",
        )
        rules["transfer_failed"] = RepairRule(
            "inspect_and_retry", None, True, "The transfer did not complete; inspect and retry."
        )
        rules["transfer_incomplete"] = RepairRule(
            "inspect_and_retry",
            None,
            True,
            "The transfer imported partially; inspect the detail before relying on it.",
        )
    if "model_validation" in features:
        rules["invalid_model"] = RepairRule(
            "use_allowed_value",
            None,
            False,
            "Pass a model the backend's catalog lists.",
        )
    if "empty_response_detection" in features:
        rules["empty_response"] = RepairRule(
            "retry_then_report",
            None,
            True,
            "The backend returned no answer; retry, then report a bug.",
        )
    return rules


def all_codes(
    vocab: BackendErrorVocabulary, features: frozenset[str] = frozenset()
) -> frozenset[str]:
    """Every code a bridge with this vocabulary/features can emit under the
    shared taxonomy. Consumers may extend with local codes; they may not
    redefine these."""
    return UNIVERSAL_CODES | backend_codes(vocab.backend_id) | feature_codes(features)
