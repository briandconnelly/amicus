"""`backend_options`: one closed superset object with per-backend applicability (ADR 0002)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from amicus.schemas.envelope import InvalidArgument

MAX_BUDGET_BOUNDS: tuple[float, float] = (0.01, 5.0)

# option -> backend -> allowed values (None: a numeric option bounded by the schema).
# The backends absent for an option do not accept it.
OPTION_ALLOWED_VALUES: dict[str, dict[str, tuple[str, ...] | None]] = {
    "isolation": {
        "codex": ("inherit", "ignore-config", "ignore-rules"),
        "kimi": ("inherit", "ignore-skills"),
    },
    "config_mode": {"claude": ("inherit", "scoped", "safe", "bare")},
    "access": {"claude": ("toolless", "readonly")},
    "max_budget_usd": {"claude": None},
}


class BackendOptions(BaseModel):
    """The union of every backend's options; applicability is validated pre-spend."""

    model_config = ConfigDict(extra="forbid")
    isolation: Literal["inherit", "ignore-config", "ignore-rules", "ignore-skills"] | None = Field(
        default=None,
        description=(
            "codex: inherit|ignore-config|ignore-rules; kimi: inherit|ignore-skills. "
            "Omit for the backend default (inherit)."
        ),
    )
    config_mode: Literal["inherit", "scoped", "safe", "bare"] | None = Field(
        default=None,
        description="claude only: inherit|scoped|safe|bare. Omit for the server default.",
    )
    access: Literal["toolless", "readonly"] | None = Field(
        default=None, description="claude only: toolless|readonly. Omit for the server default."
    )
    max_budget_usd: float | None = Field(
        default=None,
        ge=MAX_BUDGET_BOUNDS[0],
        le=MAX_BUDGET_BOUNDS[1],
        description=(
            "claude only: per-call best-effort spend cap in USD, 0.01–5.00. Omit for the "  # noqa: RUF001
            "server default (AMICUS_CLAUDE_MAX_BUDGET_USD, 1.00)."
        ),
    )


def _set_items(options: BackendOptions | None) -> list[tuple[str, Any]]:
    if options is None:
        return []
    return [(k, v) for k, v in options.model_dump().items() if v is not None]


def option_violations(backend: str, options: BackendOptions | None) -> list[InvalidArgument]:
    """Every key the selected backend does not accept, or whose value it does not accept,
    as `invalid_arguments` entries naming `backend_options.<key>`."""
    out: list[InvalidArgument] = []
    for key, value in _set_items(options):
        accepted = OPTION_ALLOWED_VALUES[key]
        if backend not in accepted:
            out.append(
                InvalidArgument(
                    field=f"backend_options.{key}",
                    reason=(
                        f"{key} is not accepted by backend {backend!r}; it applies to "
                        f"{', '.join(sorted(accepted))}"
                    ),
                )
            )
            continue
        allowed = accepted[backend]
        if allowed is not None and value not in allowed:
            out.append(
                InvalidArgument(
                    field=f"backend_options.{key}",
                    reason=f"{key} must be one of the allowed values for backend {backend!r}",
                    allowed_values=list(allowed),
                )
            )
    return out


def resolved_options(backend: str, options: BackendOptions | None) -> dict[str, Any]:
    """The set keys, for echoing in previews. Assumes `option_violations` was empty."""
    return {k: v for k, v in _set_items(options) if backend in OPTION_ALLOWED_VALUES[k]}
