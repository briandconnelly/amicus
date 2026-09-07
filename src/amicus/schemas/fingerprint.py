"""Surface identity: the hand-bumped FINGERPRINT and what it covers (ADR 0006)."""

from __future__ import annotations

# Bump on any externally observable change to a category below; the committed manifest
# snapshot (tests/test_manifest.py) fails on drift and its message says to bump this.
FINGERPRINT = "amicus/0.1/schema-5"

# Persisted result-format version stamped into job records (M2); moves only when a
# stored result.json shape an older reader's closed schema could reject changes.
# 2 (M4): AdversarialReviewResult gained review_status and context_summary.
RESULT_FORMAT: int = 2

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
