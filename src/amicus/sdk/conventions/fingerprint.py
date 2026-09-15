"""The surface-fingerprint pattern: pin the agent-visible surface to a digest.

Every bridge stamps its results with a ``FINGERPRINT`` like
``"codex-in-claude/0.1/schema-75"`` and keeps a committed snapshot of its
agent-visible surface (tools, schemas, error codes, resources). The invariant:
the surface digest may only change together with a fingerprint bump — an
acknowledged, reviewed change — never silently.

This module is the shared mechanics of that pattern. It is
framework-agnostic: checks return a :class:`SurfaceCheck` describing any
violation instead of asserting, so a consumer's test suite (or a non-pytest
harness) decides how to fail.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

_FINGERPRINT_RE = re.compile(
    r"^(?P<name>[a-z0-9][a-z0-9-]*)/(?P<major>\d+\.\d+)/schema-(?P<rev>\d+)$"
)


def parse_fingerprint(fingerprint: str) -> tuple[str, str, int]:
    """Split ``name/major/schema-N`` into its parts; raises ValueError on any
    other shape so a malformed fingerprint cannot slip onto the wire."""
    m = _FINGERPRINT_RE.match(fingerprint)
    if m is None:
        raise ValueError(f"fingerprint {fingerprint!r} must look like 'name/1.0/schema-42'")
    return m.group("name"), m.group("major"), int(m.group("rev"))


def canonical_digest(surface: object) -> str:
    """A stable sha256 over the JSON-serializable surface. Key order, unicode,
    and whitespace are normalized so the digest changes only when the surface
    does."""
    payload = json.dumps(surface, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SurfaceCheck:
    """Outcome of comparing a built surface against its committed snapshot."""

    ok: bool
    reason: str | None  # None when ok
    current_digest: str
    snapshot_digest: str | None
    fingerprint: str


def check_surface(
    surface: object,
    *,
    fingerprint: str,
    snapshot_digest: str | None,
    snapshot_fingerprint: str | None,
) -> SurfaceCheck:
    """Enforce the pattern's invariant.

    * A missing snapshot (first run) fails with instructions to commit one.
    * A digest change without a fingerprint bump fails — the surface changed
      silently.
    * A fingerprint bump without a digest change fails — the bump is either
      stale or the snapshot was regenerated needlessly; both deserve a look.
    """
    parse_fingerprint(fingerprint)
    current = canonical_digest(surface)
    if snapshot_digest is None or snapshot_fingerprint is None:
        return SurfaceCheck(
            ok=False,
            reason="no committed snapshot; commit the current digest and fingerprint",
            current_digest=current,
            snapshot_digest=None,
            fingerprint=fingerprint,
        )
    digest_changed = current != snapshot_digest
    fingerprint_changed = fingerprint != snapshot_fingerprint
    if digest_changed and not fingerprint_changed:
        return SurfaceCheck(
            ok=False,
            reason=(
                "the agent-visible surface changed but the fingerprint did not; "
                "review the change, bump the fingerprint, and regenerate the snapshot "
                "in a dedicated commit"
            ),
            current_digest=current,
            snapshot_digest=snapshot_digest,
            fingerprint=fingerprint,
        )
    if fingerprint_changed and not digest_changed:
        return SurfaceCheck(
            ok=False,
            reason=(
                "the fingerprint changed but the surface digest did not; either the "
                "bump is premature or the snapshot regeneration was unnecessary"
            ),
            current_digest=current,
            snapshot_digest=snapshot_digest,
            fingerprint=fingerprint,
        )
    if digest_changed and fingerprint_changed:
        return SurfaceCheck(
            ok=False,
            reason=(
                "surface and fingerprint both changed; regenerate the committed "
                "snapshot to acknowledge the new pair"
            ),
            current_digest=current,
            snapshot_digest=snapshot_digest,
            fingerprint=fingerprint,
        )
    return SurfaceCheck(
        ok=True,
        reason=None,
        current_digest=current,
        snapshot_digest=snapshot_digest,
        fingerprint=fingerprint,
    )
