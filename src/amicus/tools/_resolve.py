"""Pre-spend resolution shared by every paid tool: blank input, backend_options
applicability, backend availability, feature gating. Zero spend; cheapest check first."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from amicus.errors import error_envelope
from amicus.schemas.envelope import InvalidArgument
from amicus.schemas.options import BackendOptions, option_violations, resolved_options
from amicus.tools._meta import base_meta

if TYPE_CHECKING:  # pragma: no cover
    from amicus.config import Settings
    from amicus.plugin import BackendPlugin
    from amicus.registry import BackendRegistry

PAID_MARKER = "PAID — spends the selected backend's quota on every new call."
FREE_MARKER = "Free — no model call."
FEATURE_FOR_VERB: dict[str, str] = {
    "delegate": "delegate",
    "adversarial_review": "adversarial_review",
}


def blank_input_error(
    value: str, field: str, tool_name: str, settings: Settings, backend: str
) -> dict[str, Any] | None:
    if value.strip():
        return None
    reason = f"{field} must not be empty or whitespace-only."
    return error_envelope(
        "invalid_arguments",
        f"{tool_name}: 1 invalid argument(s): {field} — {reason}",
        base_meta(settings, backend=backend),
        repair_tool=tool_name,
        repair_alternative=f"Supply a {field} with actual content, then retry.",
        invalid_arguments=[InvalidArgument(field=field, reason=reason)],
    )


def resolve_paid_call(
    *,
    registry: BackendRegistry,
    settings: Settings,
    tool_name: str,
    verb: str,
    backend: str,
    backend_options: BackendOptions | None,
) -> tuple[BackendPlugin, dict[str, Any]] | dict[str, Any]:
    """The plugin and resolved options for a paid call, or a ready error envelope."""
    meta = base_meta(settings, backend=backend)
    violations = option_violations(backend, backend_options)
    if violations:
        first = violations[0]
        return error_envelope(
            "invalid_arguments",
            f"{tool_name}: {len(violations)} invalid argument(s): {first.field} — {first.reason}",
            meta,
            repair_tool=tool_name,
            invalid_arguments=violations,
        )
    plugin = registry.get(backend)
    if plugin is None:
        why = registry.unavailable_for(backend)
        detail = f"{why.reason}: {why.detail}" if why else "not enabled in AMICUS_BACKENDS"
        return error_envelope(
            "backend_unavailable",
            f"backend {backend!r} is unavailable ({detail})",
            meta,
            backend=backend,
        )
    feature = FEATURE_FOR_VERB.get(verb)
    if feature is not None and feature not in plugin.contract.supported_features:
        return error_envelope(
            "feature_unsupported",
            f"backend {backend!r} does not support {feature}",
            meta,
            plugin=plugin,
            repair_arguments={"backend": backend},
        )
    return plugin, resolved_options(backend, backend_options)


def not_implemented(tool_name: str, settings: Settings, backend: str) -> dict[str, Any]:
    return error_envelope(
        "not_implemented",
        f"{tool_name} is registered but backend {backend!r} has not landed in this release",
        base_meta(settings, backend=backend),
    )
