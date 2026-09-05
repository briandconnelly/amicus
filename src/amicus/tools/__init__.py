"""Tool registration in a fixed order (filled in by the tool modules)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from fastmcp import FastMCP

    from amicus.config import Settings
    from amicus.registry import BackendRegistry

TOOL_ORDER: tuple[str, ...] = ()


def register_all(app: FastMCP, settings: Settings, registry: BackendRegistry) -> None:
    """Register every tool in TOOL_ORDER (no tools yet in this task)."""
