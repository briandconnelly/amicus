"""The poll hint amicus hands a client for a running job (#95).

pontonier 0.9.0 caps its own hint at MAX_POLL_AFTER_MS = 10000, sized for a delegate that
runs about twenty seconds, and JobStore takes no cap (briandconnelly/pontonier#29). amicus's
jobs run for minutes, so every site that hands a client a hint computes it here: the status
tool, the job_running repair, the keyed wait's timeout repair and a replayed start handle.
The formula stays pontonier's own; only the ceiling is amicus's."""

from __future__ import annotations

from typing import Any

from pontonier.core.jobs import DEFAULT_POLL_AFTER_MS, poll_backoff_ms

# "Wait about as long as it has already run", up to thirty seconds: a four-minute job is
# polled about thirteen times instead of about twenty-eight, and a finished job is noticed at
# most thirty seconds late. A sixty-second cap would save three of those polls and double that
# delay; a status read is free, while the host waiting on it is not.
POLL_HINT_CAP_MS = 30_000


def poll_hint_ms(rec: dict[str, Any]) -> int | None:
    """The hint for a store status record: None unless the job is running."""
    if rec["status"] != "running":
        return None
    return poll_backoff_ms(rec["elapsed_ms"], base=DEFAULT_POLL_AFTER_MS, cap=POLL_HINT_CAP_MS)


def job_status_arguments(job_id: str, workspace_root: str | None) -> dict[str, Any]:
    """The complete `amicus_job_status` call every poll repair and follow-up names (ADR
    0021). One builder, so every site agrees: `workspace_root` is present when the caller
    supplied one and absent, never null, when it did not."""
    arguments: dict[str, Any] = {"job_id": job_id}
    if workspace_root:
        arguments["workspace_root"] = workspace_root
    return arguments
