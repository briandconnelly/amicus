"""The poll hint amicus hands a client for a running job (#95, #101).

Every site that hands a client a hint computes it here — the status tool, the job_running
repair, the keyed wait's timeout repair and a replayed start handle — so they agree on the
one rule the store itself has no opinion about: a terminal job is not polled at all, so its
hint is null rather than the flat base the record carries (#101).

The ceiling is `store.MAX_POLL_AFTER_MS`, which amicus owns now that the store does (#118).
Before that the store stopped at 10 s (briandconnelly/pontonier#29) and this module re-capped
the hint on its way out."""

from __future__ import annotations

from typing import Any

from amicus.jobs.store import DEFAULT_POLL_AFTER_MS, poll_backoff_ms


def poll_hint_ms(rec: dict[str, Any]) -> int | None:
    """The hint for a store status record: None unless the job is running."""
    if rec["status"] != "running":
        return None
    return poll_backoff_ms(rec["elapsed_ms"], base=DEFAULT_POLL_AFTER_MS)


def job_status_arguments(job_id: str, workspace_root: str | None) -> dict[str, Any]:
    """The complete `amicus_job_status` call every poll repair and follow-up names (ADR
    0021). One builder, so every site agrees: `workspace_root` is present when the caller
    supplied one and absent, never null, when it did not."""
    arguments: dict[str, Any] = {"job_id": job_id}
    if workspace_root:
        arguments["workspace_root"] = workspace_root
    return arguments
