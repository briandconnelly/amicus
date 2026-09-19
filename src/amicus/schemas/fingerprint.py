"""Surface identity: the hand-bumped FINGERPRINT, what it covers (ADR 0006), and the
mechanics that turn a surface into a digest and read a fingerprint back apart.

The fingerprint pattern: the server stamps its results with a ``FINGERPRINT`` like
``"amicus/0.1/schema-30"`` and keeps a committed snapshot of its agent-visible surface
(tools, schemas, error codes, resources). The invariant is that the surface digest may only
change together with a fingerprint bump — an acknowledged, reviewed change — never silently.
``tests/test_manifest.py`` is where amicus enforces it.

The mechanics below came from ``amicus.sdk.conventions.fingerprint`` (ADR 0030); they are
framework-agnostic, so :func:`check_surface` returns a :class:`SurfaceCheck` describing any
violation instead of asserting, and a consumer's harness decides how to fail.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

# Bump on any externally observable change to a category below; the committed manifest
# snapshot (tests/test_manifest.py) fails on drift and its message says to bump this.
FINGERPRINT = "amicus/0.1/schema-35"

# Persisted result-format version stamped into job records (M2); moves only when a
# stored result.json shape an older reader's closed schema could reject changes.
# 2 (M4): AdversarialReviewResult gained review_status and context_summary.
# 3 (#38): every model result gained findings_diagnostics. A 2 record must NOT be read as
# a 3: its null would assert that no finding was lost on a run that never measured loss.
# 4 (#53): confidence gained `unknown`. A 3 reader's closed enum REJECTS a 4 record that
# carries it - which is the point: the alternative was a 3-valid `medium` amicus invented.
# 5 (#65): review results gained a required `coverage`. A 4 record has none, and a default
# would claim, for a run that never measured it, that nothing in scope was left out.
# 6 (#52): consult, review and adversarial results gained lists_diagnostics. A 5 record's
# defaulted null would assert that every prose list was carried intact by a run that never
# measured it.
# 7 (#139): review_status gained `unstructured`. A 6 reader's closed enum REJECTS a 7 record
# that carries it, which is the point: a 6 reader has no way to know that nothing was parsed.
# 8 (#140): findings_diagnostics.reasons gained `backend_artifact_reference_removed`. A 7
# reader's closed enum REJECTS an 8 record that carries it, as with 4 and 7.
RESULT_FORMAT: int = 8

JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
PROTOCOL_REVISION = "2026-07-28"

# Namespaced _meta keys (convention extensions, per the agent-friendly-mcp native-vs-
# convention rule). `lifecycle` carries {stability, deprecation} on every tool and
# resource record ([9.tier-metadata]); `triage` carries size metadata on resources.
LIFECYCLE_META_KEY = "dev.bconnelly.amicus/lifecycle"
TRIAGE_META_KEY = "dev.bconnelly.amicus/triage"

FINGERPRINT_COVERS: tuple[str, ...] = (
    "tool_names",
    "tool_input_schemas",
    "tool_output_schemas",
    "tool_descriptions",
    "tool_annotations",
    "tool_lifecycle_meta",
    "error_codes",
    "value_enums",
    "resource_metadata",
    "resource_templates",
    "prompts",
    "initialize_response",
    "discover_response",
    "modern_result_envelopes",
    "error_envelope_schema",
    "result_meta_schema",
    "capabilities_result_schema",
    "parameter_contracts",
    "capabilities_payload",
    "capability_guarantees",
)

FINGERPRINT_COVERS_DESC = (
    "A contract-semantic change in any listed category changes the fingerprint; nothing "
    "outside them does. Release identity is excluded: serverInfo.version, version, "
    "server_version change every release WITHOUT moving the fingerprint. surface_digest "
    "is the sha256 of the server-side tool, resource and template records plus the "
    "instructions text; the full-manifest hash is pinned separately in tests and moves "
    "with the fingerprint, never alone."
)


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
