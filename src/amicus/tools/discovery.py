"""Stub, filled in by Task 13."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from fastmcp import FastMCP

    from amicus.config import Settings
    from amicus.registry import BackendRegistry


def register(_app: FastMCP, _settings: Settings, _registry: BackendRegistry) -> tuple[str, ...]:
    """No tools yet in this task."""
    return ()
