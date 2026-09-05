"""In-tree backend declarations. The packages themselves land per milestone (M1 codex,
M3 kimi, M4 claude); until then the registry records each as unavailable, which is the
honest state, never a startup failure."""

from __future__ import annotations

from pontonier.conventions.annotations import AnnotationEffects

# backend id -> "module:attribute" of a BackendPlugin or a zero-argument factory.
IN_TREE: dict[str, str] = {
    "codex": "amicus.backends.codex:plugin",
    "kimi": "amicus.backends.kimi:plugin",
    "claude": "amicus.backends.claude:plugin",
}

# Declared effects used to annotate the tool surface BEFORE a plugin is loaded (tool
# annotations are static per profile). `job_reads_read_only` is amicus policy for every
# backend (ADR 0001); `paid_calls_destructive` is each backend's fact. A test in each
# backend's milestone pins plugin.effects against this table.
KNOWN_EFFECTS: dict[str, AnnotationEffects] = {
    "codex": AnnotationEffects(paid_calls_destructive=False, job_reads_read_only=True),
    "kimi": AnnotationEffects(paid_calls_destructive=False, job_reads_read_only=True),
    "claude": AnnotationEffects(paid_calls_destructive=True, job_reads_read_only=True),
}

KNOWN_DISPLAY_NAMES: dict[str, str] = {"codex": "Codex", "kimi": "Kimi", "claude": "Claude Code"}
