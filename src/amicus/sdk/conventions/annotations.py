"""MCP tool-annotation builders, parameterized by each bridge's declared effects.

The bridges disagree on annotation values DELIBERATELY, not accidentally:

* claude-in-codex marks paid tools ``destructiveHint: true`` because its
  inherit/scoped config modes may execute arbitrary workspace hooks, and marks
  job pollers non-read-only because polling performs lazy deadline-kill/TTL
  maintenance.
* codex-in-claude and moonbridge mark paid tools ``destructiveHint: false``
  because writes stay inside a throwaway worktree, and advertise job reads as
  read-only.

A universal constant dict would silently change someone's wire. These builders
make the POLICY explicit instead: a bridge declares its observable effects once
(:class:`AnnotationEffects`, normally derived from its BackendContract) and
derives every annotation set from that declaration, which a conformance check
can then compare against what the server actually registered.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AnnotationEffects:
    """One bridge's declared observable effects, from which annotations follow.

    ``paid_calls_destructive``: True when a paid call can trigger side effects
    outside the bridge's own state (e.g. workspace hooks running arbitrary
    commands); False when writes are confined to a throwaway worktree.

    ``job_reads_read_only``: True to advertise job status/result/list as
    read-only even though polling performs lazy maintenance (deadline kill, TTL
    deletion); False to advertise that maintenance as a mutation. Both positions
    are defensible — the point is that each bridge PINS one and the conformance
    check holds it to its declaration.
    """

    paid_calls_destructive: bool
    job_reads_read_only: bool


def free_read() -> dict[str, bool]:
    """Free, local-only inspection tools (status, capabilities, models, dry runs)."""
    return {"readOnlyHint": True, "openWorldHint": False}


def active(effects: AnnotationEffects) -> dict[str, bool]:
    """Paid model-bearing tools — sync and async starts alike. Every call spends
    and reaches an external service, so never read-only, always open-world, and
    non-idempotent."""
    return {
        "readOnlyHint": False,
        "openWorldHint": True,
        "destructiveHint": effects.paid_calls_destructive,
        "idempotentHint": False,
    }


def job_read(effects: AnnotationEffects) -> dict[str, bool]:
    """Job status/result/list. Closed-world always (they touch only this server's
    job state); read-only per the bridge's declared position on lazy maintenance."""
    if effects.job_reads_read_only:
        return {"readOnlyHint": True, "openWorldHint": False}
    return {
        "readOnlyHint": False,
        "openWorldHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
    }


def job_mutate(*, idempotent: bool) -> dict[str, bool]:
    """Job consume/cancel: closed-world state mutations. ``consume`` deletes the
    retained record (a repeat returns not-found — a different response), so it is
    non-idempotent; ``cancel`` re-validates concurrent completion and returns a
    terminal job unchanged, so a retry after a lost response has no additional
    effect."""
    return {
        "readOnlyHint": False,
        "openWorldHint": False,
        "destructiveHint": False,
        "idempotentHint": idempotent,
    }


def free_write() -> dict[str, bool]:
    """Free tools with a persistent local side effect (e.g. session transfer
    creating a backend thread): no model call, no network egress, additive only,
    and a new artifact per call."""
    return {
        "readOnlyHint": False,
        "openWorldHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
    }
