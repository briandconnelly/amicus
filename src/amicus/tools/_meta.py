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

SERVER_STABILITY = "alpha"
# Tools more experimental than the server-wide tier; anything absent inherits it.
TOOL_STABILITY: dict[str, str] = {
    "amicus_consult_async": "experimental",
    "amicus_review_changes_async": "experimental",
    "amicus_adversarial_review_async": "experimental",
    "amicus_delegate_async": "experimental",
    "amicus_job_status": "experimental",
    "amicus_job_result": "experimental",
    "amicus_job_consume_result": "experimental",
    "amicus_job_cancel": "experimental",
    "amicus_job_list": "experimental",
}
# An enabled id the in-tree table does not know (a third-party plugin) is annotated for
# the worst case until its plugin declares otherwise.
_UNKNOWN_EFFECTS = AnnotationEffects(paid_calls_destructive=True, job_reads_read_only=True)

AnnotationKind = Literal["active", "free", "job_read", "job_consume", "job_cancel"]


def tool_stability(name: str) -> str:
    return TOOL_STABILITY.get(name, SERVER_STABILITY)


def lifecycle_meta(name: str) -> dict[str, Any]:
    """The `<reverse-dns>/lifecycle` _meta block ([9.tier-metadata]); the deprecation
    marker is absent, which is the not-deprecated signal."""
    return {LIFECYCLE_META_KEY: {"stability": tool_stability(name)}}


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
