"""Per-tool metadata shared by every tool module: annotations (worst enabled backend,
ADR 0001), lifecycle _meta, stability tiers, and the base Meta for an envelope."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from amicus.backends import KNOWN_EFFECTS
from amicus.schemas.envelope import Meta
from amicus.schemas.fingerprint import LIFECYCLE_META_KEY
from amicus.sdk.conventions import annotations as ann
from amicus.sdk.conventions.annotations import AnnotationEffects

if TYPE_CHECKING:  # pragma: no cover
    from amicus.config import Settings
    from amicus.schemas.results import ToolDeprecation, ToolStability

# The server-wide tier, published on every tool, resource and template. Typed as
# ToolStability so the checker rejects a value outside the closed set [9.stability-tiers]
# closes on; it was a bare `str` holding "alpha", which no agent could interpret (#43).
SERVER_STABILITY: ToolStability = "experimental"
# Per-tool tiers that differ from the server-wide one; anything absent inherits it.
# Empty while the server sits at the least mature tier the closed set offers: nothing can
# be more experimental than `experimental`, so every tool inherits. It fills again when
# the server reaches `preview` or `stable` and individual tools lag behind it.
TOOL_STABILITY: dict[str, ToolStability] = {}
# An enabled id the in-tree table does not know (a third-party plugin) is annotated for
# the worst case until its plugin declares otherwise.
_UNKNOWN_EFFECTS = AnnotationEffects(paid_calls_destructive=True, job_reads_read_only=True)

AnnotationKind = Literal["active", "free", "job_read", "job_consume", "job_cancel"]


def tool_stability(name: str) -> ToolStability:
    return TOOL_STABILITY.get(name, SERVER_STABILITY)


# Tools inside their deprecation window, keyed by the deprecated name. Each marker rides
# the tool's lifecycle _meta and its amicus_capabilities row, so read it through
# `tool_deprecation()` rather than importing this table (the #43 trap).
# Empty since 0.5.0: `amicus_dry_run`, the first entry (#98, 0.3.0 to 0.5.0), was removed at
# the end of its window (#204, ADR 0028). The mechanism stays, because the policy does.
DEPRECATED_TOOLS: dict[str, ToolDeprecation] = {}


def tool_deprecation(name: str) -> ToolDeprecation | None:
    return DEPRECATED_TOOLS.get(name)


def deprecation_marker(name: str) -> dict[str, Any] | None:
    """The marker as every surface publishes it: all four fields, a null `replaced_by`
    included, which an `exclude_none` dump would drop."""
    deprecation = tool_deprecation(name)
    return None if deprecation is None else deprecation.model_dump(mode="json")


def lifecycle_meta(name: str) -> dict[str, Any]:
    """The `<reverse-dns>/lifecycle` _meta block ([9.tier-metadata]): the stability tier,
    and beside it the deprecation marker only for a deprecated tool. Its absence is the
    not-deprecated signal ([9.deprecation-marker])."""
    block: dict[str, Any] = {"stability": tool_stability(name)}
    marker = deprecation_marker(name)
    if marker is not None:
        block["deprecation"] = marker
    return {LIFECYCLE_META_KEY: block}


def server_stability() -> ToolStability:
    """The server-wide tier. Read it through this rather than importing the constant: a
    `from ... import SERVER_STABILITY` binds a copy at the importer's import time, and
    then one module can publish a stale tier while the others move (see the mutation
    control in tests/test_discovery.py, which is what caught that)."""
    return SERVER_STABILITY


def server_lifecycle_meta() -> dict[str, Any]:
    """The lifecycle block for a resource or template, which carries the server-wide
    tier; `lifecycle_meta` is the per-tool form."""
    return {LIFECYCLE_META_KEY: {"stability": server_stability()}}


def effects_for(settings: Settings) -> AnnotationEffects:
    destructive = any(
        KNOWN_EFFECTS.get(b, _UNKNOWN_EFFECTS).paid_calls_destructive
        for b in settings.enabled_backends
    )
    return AnnotationEffects(paid_calls_destructive=destructive, job_reads_read_only=True)


def annotations_for(kind: AnnotationKind, settings: Settings) -> dict[str, bool]:
    effects = effects_for(settings)
    if kind == "active":
        return ann.active(effects)
    if kind == "free":
        return ann.free_read()
    if kind == "job_read":
        return ann.job_read(effects)
    if kind == "job_consume":
        return ann.job_mutate(idempotent=False)
    return ann.job_mutate(idempotent=True)


def base_meta(settings: Settings, *, backend: str | None = None, **fields: Any) -> Meta:
    return Meta(backend=backend, timeout_seconds=settings.timeout_seconds, **fields)
