"""Surface identity: the hand-bumped FINGERPRINT, what it covers (ADR 0006), and the
mechanics that turn a surface into a digest and read a fingerprint back apart.

The fingerprint pattern: the server stamps its results with a ``FINGERPRINT`` like
``"amicus/0.1/schema-30"`` and keeps a committed snapshot of its agent-visible surface
(tools, schemas, error codes, resources). The invariant is that the surface digest may only
change together with a fingerprint bump — an acknowledged, reviewed change — never silently.
``tests/test_manifest.py`` and ``tests/test_fingerprint.py`` are where amicus enforces it,
and ``tests/test_fingerprint.py`` also holds ``FINGERPRINT`` to the ``amicus/0.1/schema-N``
shape through :func:`parse_fingerprint`.

The mechanics below came from ``amicus.sdk.conventions.fingerprint`` (ADR 0030).
"""

from __future__ import annotations

import hashlib
import json
import re

# Bump on any externally observable change to a category below; the committed manifest
# snapshot (tests/test_manifest.py) fails on drift and its message says to bump this.
FINGERPRINT = "amicus/0.1/schema-54"

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
# 9 (#162): error.code gained `answer_unavailable`. An 8 reader's closed enum REJECTS a 9
# record that carries it, as with 4, 7 and 8.
# (#244's `job_cap_reached` did not move it: the code refuses a start before any job record
# exists, so no stored result can carry it.)
RESULT_FORMAT: int = 9

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
    "repair_rules",
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


# Integers are canonical ASCII (no leading zero, a revision of at least 1), so one revision has
# exactly one spelling.
_FINGERPRINT_RE = re.compile(
    r"(?P<name>[a-z0-9][a-z0-9-]*)/(?P<major>(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*))"
    r"/schema-(?P<rev>[1-9][0-9]*)"
)


def parse_fingerprint(fingerprint: str) -> tuple[str, str, int]:
    """Split ``name/major/schema-N`` into its parts; raises ValueError on any other
    shape. ``tests/test_fingerprint.py`` runs it on ``FINGERPRINT``, so a malformed
    hand bump fails the gate instead of reaching the wire."""
    m = _FINGERPRINT_RE.fullmatch(fingerprint)
    if m is None:
        raise ValueError(f"fingerprint {fingerprint!r} must look like 'name/1.0/schema-42'")
    return m.group("name"), m.group("major"), int(m.group("rev"))


def canonical_digest(surface: object) -> str:
    """A stable sha256 over the JSON-serializable surface. Key order, unicode,
    and whitespace are normalized so the digest changes only when the surface
    does."""
    payload = json.dumps(surface, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
