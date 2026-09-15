"""Annotation builders: parity with each bridge's CURRENT wire values.

The literal dicts below are copied from the three servers' source. They pin the
M2/M3/M4 guarantee: a bridge declaring its actual effects derives its existing
annotations exactly, so adopting the builder changes nothing on the wire.
"""

from __future__ import annotations

from amicus.sdk.conventions import annotations

# codex-in-claude / moonbridge position: writes stay in a throwaway worktree;
# job reads advertised read-only despite lazy maintenance.
WORKTREE_BRIDGE = annotations.AnnotationEffects(
    paid_calls_destructive=False, job_reads_read_only=True
)

# claude-in-codex position: inherit/scoped config modes may run workspace hooks
# (arbitrary commands), so paid calls are destructive; job pollers perform lazy
# deadline-kill/TTL maintenance and are advertised non-read-only.
HOOKS_BRIDGE = annotations.AnnotationEffects(paid_calls_destructive=True, job_reads_read_only=False)


def test_active_matches_codex_in_claude_propose():
    # codex-in-claude server.py _ACTIVE_PROPOSE (== _ACTIVE_ASYNC)
    assert annotations.active(WORKTREE_BRIDGE) == {
        "readOnlyHint": False,
        "openWorldHint": True,
        "destructiveHint": False,
        "idempotentHint": False,
    }


def test_active_matches_claude_in_codex_paid():
    # claude-in-codex server.py _PAID_ANNOTATIONS
    assert annotations.active(HOOKS_BRIDGE) == {
        "readOnlyHint": False,
        "openWorldHint": True,
        "destructiveHint": True,
        "idempotentHint": False,
    }


def test_free_read_matches_both():
    # _FREE_READ in codex-in-claude; _FREE_READ_ANNOTATIONS in claude-in-codex
    assert annotations.free_read() == {"readOnlyHint": True, "openWorldHint": False}


def test_job_read_read_only_position_omits_meaningless_hints():
    # codex-in-claude _JOB_READ: destructive/idempotent omitted because MCP gives
    # them meaning only when readOnlyHint is false.
    assert annotations.job_read(WORKTREE_BRIDGE) == {
        "readOnlyHint": True,
        "openWorldHint": False,
    }


def test_job_read_maintenance_position_is_mutating():
    out = annotations.job_read(HOOKS_BRIDGE)
    assert out["readOnlyHint"] is False
    assert out["openWorldHint"] is False


def test_job_mutate_consume_vs_cancel_idempotency():
    # codex-in-claude: _JOB_MUTATE (consume, non-idempotent) vs _JOB_CANCEL
    # (idempotent) differ only in idempotentHint.
    consume = annotations.job_mutate(idempotent=False)
    cancel = annotations.job_mutate(idempotent=True)
    assert consume == {
        "readOnlyHint": False,
        "openWorldHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
    }
    assert cancel == {**consume, "idempotentHint": True}


def test_free_write_matches_codex_transfer():
    # codex-in-claude _FREE_WRITE (codex_transfer)
    assert annotations.free_write() == {
        "readOnlyHint": False,
        "openWorldHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
    }
