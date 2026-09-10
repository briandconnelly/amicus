"""Wrap a tool so an unexpected exception becomes an internal_error envelope and an
`ok: false` envelope is an MCP error result on every delivery path."""

from __future__ import annotations

import functools
from typing import TYPE_CHECKING, Any

from fastmcp.tools import ToolResult

from amicus import obs
from amicus.errors import error_envelope
from amicus.tools._meta import base_meta

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Awaitable, Callable

    from amicus.config import Settings

GUARD_MARKER = "_amicus_guarded"


def as_tool_result(envelope: dict[str, Any]) -> dict[str, Any] | ToolResult:
    """An `ok: false` envelope becomes a `ToolResult` with `is_error=True`; anything else
    is returned unchanged for FastMCP's own conversion.

    FastMCP derives the text mirror of a `ToolResult` built from `structured_content` on
    the same path (`_convert_to_content`) it uses for a dict returned under an explicit
    output schema, so the wire shape equals the middleware-flipped result
    (`tests/test_guard.py` pins the parity). The flip has to be produced here, not only in
    `SemanticErrorMiddleware`: a task-augmented call (ADR 0004) never re-enters the
    middleware chain, and the tasks handler passes a `ToolResult` through with `isError`
    intact."""
    if envelope.get("ok") is False:
        return ToolResult(structured_content=envelope, is_error=True)
    return envelope


def guard(
    tool_name: str, settings: Settings
) -> Callable[
    [Callable[..., Awaitable[dict[str, Any]]]],
    Callable[..., Awaitable[dict[str, Any] | ToolResult]],
]:
    """Cancellation is a BaseException and propagates; only `Exception` is enveloped."""

    def decorator(
        fn: Callable[..., Awaitable[dict[str, Any]]],
    ) -> Callable[..., Awaitable[dict[str, Any] | ToolResult]]:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any] | ToolResult:
            try:
                return as_tool_result(await fn(*args, **kwargs))
            except Exception as exc:
                # Neither side gets the exception's text. The client-facing message names
                # the type because the text may carry caller-supplied content that failed
                # to redact cleanly; the LOG withholds it for a stricter reason — that
                # content may be an INPUT_FIELDS prompt input, which AGENTS.md rule 18
                # forbids writing to a log. `exc_summary` is not the safe form here: it
                # masks secrets and control characters, not prompt text. `exc_info` is
                # still passed, and `obs.PolicyFormatter` renders it as exception types
                # and source locations with no message text — the frames are the reason
                # to log this at all.
                obs.get_logger(__name__).exception(
                    "%s failed unexpectedly: %s", tool_name, type(exc).__name__
                )
                return as_tool_result(
                    error_envelope(
                        "internal_error",
                        f"{tool_name} failed unexpectedly: {type(exc).__name__}",
                        base_meta(settings, backend=kwargs.get("backend")),
                    )
                )

        setattr(wrapper, GUARD_MARKER, True)
        return wrapper

    return decorator
