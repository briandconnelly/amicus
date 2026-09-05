"""BackendRegistry: load enabled backends from in-tree factories and entry points.

Never raises on a bad backend: an import error, a wrong api_version, an id mismatch, a
pontonier conformance violation (`check_contract` AND `check_backend`) or a factory
exception is recorded as UnavailableBackend and reported by amicus_backends."""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from importlib.metadata import EntryPoint, entry_points
from typing import TYPE_CHECKING, Any, Literal

from pontonier.core.redaction import exc_summary
from pontonier.testing import conformance

from amicus import backends as in_tree_backends
from amicus.plugin import ENTRY_POINT_GROUP, PLUGIN_API_VERSION, BackendPlugin

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Iterable, Mapping

Reason = Literal[
    "not_installed",
    "import_failed",
    "load_failed",
    "api_version",
    "id_mismatch",
    "reserved_id",
    "contract_violation",
    "backend_violation",
]


@dataclass(frozen=True)
class UnavailableBackend:
    backend_id: str
    reason: Reason
    detail: str


def _entry_points() -> Iterable[EntryPoint]:
    return entry_points(group=ENTRY_POINT_GROUP)


def _load_dotted(value: str) -> Any:
    module_name, _, attr = value.partition(":")
    module = importlib.import_module(module_name)
    return getattr(module, attr) if attr else module


def _materialize(obj: Any) -> BackendPlugin:
    if not isinstance(obj, BackendPlugin) and callable(obj):
        obj = obj()
    if not isinstance(obj, BackendPlugin):
        raise TypeError(f"expected a BackendPlugin, got {type(obj).__name__}")
    return obj


def _validate(backend_id: str, plugin: BackendPlugin) -> UnavailableBackend | None:
    if plugin.api_version != PLUGIN_API_VERSION:
        return UnavailableBackend(
            backend_id,
            "api_version",
            f"plugin api_version {plugin.api_version} != {PLUGIN_API_VERSION}",
        )
    if plugin.backend_id != backend_id:
        return UnavailableBackend(
            backend_id, "id_mismatch", f"plugin contract names {plugin.backend_id!r}"
        )
    violations = conformance.check_contract(plugin.contract)
    if violations:
        return UnavailableBackend(backend_id, "contract_violation", "; ".join(violations))
    violations = conformance.check_backend(plugin.contract, plugin.backend)
    if violations:
        return UnavailableBackend(backend_id, "backend_violation", "; ".join(violations))
    return None


class BackendRegistry:
    def __init__(
        self, available: dict[str, BackendPlugin], unavailable: dict[str, UnavailableBackend]
    ) -> None:
        self.available = available
        self.unavailable = unavailable

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(self.available)

    def get(self, backend_id: str) -> BackendPlugin | None:
        return self.available.get(backend_id)

    def unavailable_for(self, backend_id: str) -> UnavailableBackend | None:
        return self.unavailable.get(backend_id)

    @classmethod
    def load(
        cls,
        enabled: Iterable[str],
        *,
        in_tree: Mapping[str, str] | None = None,
        entry_points: Iterable[EntryPoint] | None = None,
    ) -> BackendRegistry:
        tree = in_tree_backends.IN_TREE if in_tree is None else in_tree
        eps = {ep.name: ep for ep in (_entry_points() if entry_points is None else entry_points)}
        available: dict[str, BackendPlugin] = {}
        unavailable: dict[str, UnavailableBackend] = {}
        for backend_id in enabled:
            source: str | EntryPoint | None
            if backend_id in tree:
                source = tree[backend_id]
            elif backend_id in eps:
                if backend_id in in_tree_backends.IN_TREE:
                    unavailable[backend_id] = UnavailableBackend(
                        backend_id,
                        "reserved_id",
                        f"{backend_id!r} is an in-tree backend id; an entry point may not claim it",
                    )
                    continue
                source = eps[backend_id]
            else:
                unavailable[backend_id] = UnavailableBackend(
                    backend_id,
                    "not_installed",
                    f"no in-tree factory or {ENTRY_POINT_GROUP} entry point named {backend_id!r}",
                )
                continue
            try:
                raw = _load_dotted(source) if isinstance(source, str) else source.load()
            except ImportError as exc:
                unavailable[backend_id] = UnavailableBackend(
                    backend_id, "import_failed", exc_summary(exc)
                )
                continue
            except Exception as exc:  # any failure is recorded, never raised
                unavailable[backend_id] = UnavailableBackend(
                    backend_id, "load_failed", exc_summary(exc)
                )
                continue
            try:
                plugin = _materialize(raw)
            except Exception as exc:
                unavailable[backend_id] = UnavailableBackend(
                    backend_id, "load_failed", exc_summary(exc)
                )
                continue
            problem = _validate(backend_id, plugin)
            if problem is not None:
                unavailable[backend_id] = problem
                continue
            available[backend_id] = plugin
        return cls(available, unavailable)
