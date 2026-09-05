"""Tool registration in a FIXED order: the wire order is contract ([9.deterministic-order])."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from fastmcp import FastMCP

    from amicus.config import Settings
    from amicus.registry import BackendRegistry

ACTIVE_TOOLS: tuple[str, ...] = (
    "amicus_consult",
    "amicus_consult_async",
    "amicus_review_changes",
    "amicus_review_changes_async",
    "amicus_delegate",
    "amicus_delegate_async",
    "amicus_adversarial_review",
    "amicus_adversarial_review_async",
)
FREE_TOOLS: tuple[str, ...] = (
    "amicus_dry_run",
    "amicus_delegate_dry_run",
    "amicus_backends",
    "amicus_models",
    "amicus_capabilities",
)
JOB_TOOLS: tuple[str, ...] = (
    "amicus_job_status",
    "amicus_job_result",
    "amicus_job_consume_result",
    "amicus_job_cancel",
    "amicus_job_list",
)
TOOL_ORDER: tuple[str, ...] = ACTIVE_TOOLS + FREE_TOOLS + JOB_TOOLS
PAIRS: tuple[tuple[str, str], ...] = (
    ("amicus_consult", "amicus_consult_async"),
    ("amicus_review_changes", "amicus_review_changes_async"),
    ("amicus_delegate", "amicus_delegate_async"),
    ("amicus_adversarial_review", "amicus_adversarial_review_async"),
)


def register_all(app: FastMCP, settings: Settings, registry: BackendRegistry) -> None:
    from amicus.tools import consult, delegate, discovery, dry_run, jobs, review  # noqa: PLC0415

    registered: tuple[str, ...] = ()
    registered += consult.register(app, settings, registry)
    registered += review.register_review_changes(app, settings, registry)
    registered += delegate.register(app, settings, registry)
    registered += review.register_adversarial(app, settings, registry)
    registered += dry_run.register(app, settings, registry)
    registered += discovery.register(app, settings, registry)
    registered += jobs.register(app, settings, registry)
    if registered != TOOL_ORDER:
        raise RuntimeError(f"tool registration order drifted: {registered} != {TOOL_ORDER}")
