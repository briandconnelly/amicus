"""In-tree backend declarations. The packages themselves land per milestone (M1 codex,
M3 kimi, M4 claude, M9 pi); until then the registry records each as unavailable, which is the
honest state, never a startup failure."""

from __future__ import annotations

from amicus.schemas.envelope import ToolDeprecation
from amicus.sdk.conventions.annotations import AnnotationEffects

# backend id -> "module:attribute" of a BackendPlugin or a zero-argument factory.
IN_TREE: dict[str, str] = {
    "codex": "amicus.backends.codex:plugin",
    "kimi": "amicus.backends.kimi:plugin",
    "claude": "amicus.backends.claude:plugin",
    "pi": "amicus.backends.pi:plugin",
}

# Declared effects used to annotate the tool surface BEFORE a plugin is loaded (tool
# annotations are static per profile). `job_reads_read_only` is amicus policy for every
# backend (ADR 0001); `paid_calls_destructive` is each backend's fact. A test in each
# backend's milestone pins plugin.effects against this table.
KNOWN_EFFECTS: dict[str, AnnotationEffects] = {
    "codex": AnnotationEffects(paid_calls_destructive=False, job_reads_read_only=True),
    "kimi": AnnotationEffects(paid_calls_destructive=True, job_reads_read_only=True),
    "claude": AnnotationEffects(paid_calls_destructive=True, job_reads_read_only=True),
    "pi": AnnotationEffects(paid_calls_destructive=True, job_reads_read_only=True),
}

# Why each backend above with paid_calls_destructive=True makes the paid tools destructive,
# as amicus_capabilities.annotations_reading states it (#442). One clause per destructive
# backend, no trailing period; a test fails a destructive backend without one.
DESTRUCTIVE_REASONS: dict[str, str] = {
    "kimi": "its delegate runs shell commands and writes files with no sandbox",
    "claude": "its config modes may run workspace hooks",
    "pi": "its delegate runs unsandboxed shell commands",
}

KNOWN_DISPLAY_NAMES: dict[str, str] = {
    "codex": "Codex",
    "kimi": "Kimi",
    "claude": "Claude Code",
    "pi": "Pi",
}

# Backends inside their deprecation window, keyed by backend id. A deprecated backend stays
# enabled, in every backend enum and working; its marker rides its amicus_backends entry and
# the meta of every envelope it produces. Read it through `backend_deprecation()` rather than
# importing this table (the #43 trap). scripts/check_release_state.py reads this literal
# statically, so keep every entry's `since` and `removal_at_or_after` literal strings.
DEPRECATED_BACKENDS: dict[str, ToolDeprecation] = {
    "kimi": ToolDeprecation(
        since="0.13.0",
        removal_at_or_after="0.15.0",
        replaced_by="pi",
        migration=(
            "Install the pi CLI and give it the provider's credentials (pi's own /login or "
            "the provider's API-key variable), enable pi (the default profile includes it; an "
            "explicit AMICUS_BACKENDS must name it), set AMICUS_PI_MODEL to the exact "
            "provider/id the kimi config used (for example openrouter/moonshotai/kimi-k3), "
            "confirm amicus_backends reports pi installed and authenticated, then pass backend: "
            '"pi". pi serves consult, review_changes and delegate as kimi does.'
        ),
    ),
}


def backend_deprecation(backend: str | None) -> ToolDeprecation | None:
    """The deprecation marker for `backend`, or None when it is not deprecated (or None)."""
    return None if backend is None else DEPRECATED_BACKENDS.get(backend)
