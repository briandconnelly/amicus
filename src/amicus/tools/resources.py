"""Resource registration (filled in by Task 13)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from fastmcp import FastMCP

    from amicus.config import Settings
    from amicus.registry import BackendRegistry


def register_resources(app: FastMCP, settings: Settings, registry: BackendRegistry) -> None:
    """No resources yet in this task."""
