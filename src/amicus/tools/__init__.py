"""Tool registration in a FIXED order: the wire order is contract ([9.deterministic-order])."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from fastmcp import FastMCP

    from amicus.appstate import AppState
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

# The tools that declare no workspace_root. Every inputSchema is additionalProperties:
# false, so passing one to these fails as invalid_arguments — which is why the sessionless
# prerequisite below names them instead of saying "every call" (issue #40). The manifest
# test binds this tuple to the live schemas, so it cannot drift from them silently.
WORKSPACELESS_TOOLS: tuple[str, ...] = (
    "amicus_backends",
    "amicus_models",
    "amicus_capabilities",
)
_WORKSPACELESS_PROSE = ", ".join(WORKSPACELESS_TOOLS[:-1]) + f" and {WORKSPACELESS_TOOLS[-1]}"

# Stated once and rendered on every surface that states it: the server instructions
# (initialize_response) and amicus_capabilities.prerequisites (capabilities_payload).
WORKSPACE_PREREQUISITE: str = (
    "Pass workspace_root from a sessionless (2026-07-28) client on every call that declares "
    f"the parameter, and on no other: {_WORKSPACELESS_PROSE} declare none and reject one."
)
PAIRS: tuple[tuple[str, str], ...] = (
    ("amicus_consult", "amicus_consult_async"),
    ("amicus_review_changes", "amicus_review_changes_async"),
    ("amicus_delegate", "amicus_delegate_async"),
    ("amicus_adversarial_review", "amicus_adversarial_review_async"),
)


def register_all(
    app: FastMCP, settings: Settings, registry: BackendRegistry, state: AppState
) -> None:
    from amicus.tools import consult, delegate, discovery, dry_run, jobs, review  # noqa: PLC0415

    registered: tuple[str, ...] = ()
    registered += consult.register(app, settings, registry)
    registered += review.register_review_changes(app, settings, registry)
    registered += delegate.register(app, settings, registry)
    registered += review.register_adversarial(app, settings, registry)
    registered += dry_run.register(app, settings, registry)
    registered += discovery.register(app, settings, registry, state)
    registered += jobs.register(app, settings, registry)
    if registered != TOOL_ORDER:
        raise RuntimeError(f"tool registration order drifted: {registered} != {TOOL_ORDER}")
