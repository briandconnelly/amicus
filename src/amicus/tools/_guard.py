"""Wrap a tool so an unexpected exception becomes an internal_error envelope."""

from __future__ import annotations

import functools
from typing import TYPE_CHECKING, Any

from pontonier.core.redaction import exc_summary

from amicus import obs
from amicus.errors import error_envelope
from amicus.tools._meta import base_meta

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Awaitable, Callable

    from amicus.config import Settings

GUARD_MARKER = "_amicus_guarded"


def guard(
    tool_name: str, settings: Settings
) -> Callable[[Callable[..., Awaitable[dict[str, Any]]]], Callable[..., Awaitable[dict[str, Any]]]]:
    """Cancellation is a BaseException and propagates; only `Exception` is enveloped."""

    def decorator(
        fn: Callable[..., Awaitable[dict[str, Any]]],
    ) -> Callable[..., Awaitable[dict[str, Any]]]:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
            try:
                return await fn(*args, **kwargs)
            except Exception as exc:
                # Full detail (exc_summary) goes to the log only; the client-facing
                # message names the exception type but never echoes its text, which may
                # carry caller-supplied content that failed to redact cleanly.
                obs.get_logger(__name__).exception(
                    "%s failed unexpectedly: %s", tool_name, exc_summary(exc)
                )
                return error_envelope(
                    "internal_error",
                    f"{tool_name} failed unexpectedly: {type(exc).__name__}",
                    base_meta(settings, backend=kwargs.get("backend")),
                )

        setattr(wrapper, GUARD_MARKER, True)
        return wrapper

    return decorator
