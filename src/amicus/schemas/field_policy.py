"""Which agent-visible strings may carry a control character, and what happens when one
does. Machine identifiers are split by who can fix the value: caller inputs are REJECTED
at the MCP boundary by an advertised pattern; real filesystem/model identities are
PRESERVED byte-exact and escaped only where rendered. Never sanitize an identifier —
deleting a byte corrupts it into a different, valid-looking one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from amicus.schemas.params import (
    CONTROL_CHAR_FREE_PATTERN as CONTROL_CHAR_FREE_PATTERN,  # noqa: PLC0414 - deliberate re-export
)

if TYPE_CHECKING:  # pragma: no cover
    from fastmcp import FastMCP

REJECT_PARAMS: tuple[str, ...] = ("job_id", "base", "commit", "model", "task_id")

PRESERVE_CARRIERS: tuple[str, ...] = (
    "meta.cwd",
    "workspace.cwd",
    "error.repair.arguments.workspace_root",
    "error.candidate_roots",
    "findings[].file",
    "meta.session_id",
    "raw_response.session_id",
    "meta.model",
    "meta.base",
    "meta.commit",
    "meta.paths[]",
)


async def advertised_patterns(app: FastMCP) -> dict[str, str | None]:
    """Each tool parameter name → the `pattern` its inputSchema advertises. A parameter on
    several tools must advertise the same pattern everywhere; a disagreement resolves to
    None so a guard fails rather than passing on whichever tool was visited last."""
    found: dict[str, set[str | None]] = {}
    for tool in await app.list_tools():
        for name, schema in (tool.parameters or {}).get("properties", {}).items():
            branches = schema.get("anyOf", [schema])
            pattern = next((b.get("pattern") for b in branches if b.get("pattern")), None)
            found.setdefault(name, set()).add(pattern)
    return {n: ps.pop() if len(ps) == 1 else None for n, ps in found.items()}
