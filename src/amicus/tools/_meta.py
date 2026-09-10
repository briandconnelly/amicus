"""Per-tool metadata shared by every tool module: annotations (worst enabled backend,
ADR 0001), lifecycle _meta, stability tiers, and the base Meta for an envelope."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pontonier.conventions import annotations as ann
from pontonier.conventions.annotations import AnnotationEffects

from amicus.backends import KNOWN_EFFECTS
from amicus.schemas.envelope import Meta
from amicus.schemas.fingerprint import LIFECYCLE_META_KEY

if TYPE_CHECKING:  # pragma: no cover
    from amicus.config import Settings
    from amicus.schemas.results import ToolStability

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


def lifecycle_meta(name: str) -> dict[str, Any]:
    """The `<reverse-dns>/lifecycle` _meta block ([9.tier-metadata]); the deprecation
    marker is absent, which is the not-deprecated signal."""
    return {LIFECYCLE_META_KEY: {"stability": tool_stability(name)}}


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
