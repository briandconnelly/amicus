"""`AppState`: the per-app mutable state `create_app` builds and tools/resources read.

Lives outside `amicus.server` so tool and resource modules can import the type without
importing the server module itself (see the import-linter contract forbidding
`amicus.tools` -> `amicus.server`)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from amicus.config import Settings
    from amicus.registry import BackendRegistry


@dataclass
class AppState:
    settings: Settings
    registry: BackendRegistry
    tasks_active: bool = False
    config_errors: list[str] = field(default_factory=list)
