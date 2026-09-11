"""The backend plugin API: what a backend package hands amicus (pure data + protocols).

A plugin bundles pontonier's frozen contract and adapter with the amicus-side facts the
server needs: option specs, a status probe, a model-catalog reader, a binary resolver,
a help probe, the error vocabulary, an env namespace and the annotation effects. Outcome
inspection is a pontonier capability on `backend` itself (OutcomeInspector), so the
plugin carries nothing extra for it. Third-party backends register an entry point in
the `amicus.backends` group whose value is a BackendPlugin or a zero-argument factory.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Mapping

    from pontonier.backend.contract import BackendContract
    from pontonier.backend.protocol import AgentBackend
    from pontonier.conventions.annotations import AnnotationEffects
    from pontonier.conventions.envelope import BackendErrorVocabulary, RepairRule
    from pontonier.conventions.preflight import HelpProbe

    from amicus.config.envspec import EnvNamespace

PLUGIN_API_VERSION = 1
ENTRY_POINT_GROUP = "amicus.backends"


@dataclass(frozen=True)
class OptionSpec:
    """One backend option: its `backend_options` key, the RunRequest field it maps to,
    the verbs it applies to, and the backend's default. The SCHEMA lives in
    amicus.schemas.options; this carries defaults and applicability only (ADR 0002).
    Repeated names must have disjoint applies_to sets and the same maps_to field.
    Consumers resolving a call must filter by verb before indexing by name."""

    name: str
    maps_to: str
    applies_to: frozenset[str]
    default: Any = None


@dataclass(frozen=True)
class StatusReport:
    installed: bool
    version: str | None = None
    authenticated: bool | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ModelEntry:
    slug: str
    display_name: str | None = None
    default_reasoning_effort: str | None = None
    supported_reasoning_efforts: tuple[str, ...] | None = None


@dataclass(frozen=True)
class ModelListing:
    models: tuple[ModelEntry, ...]
    source: Literal["cache", "static", "live", "none"]
    fetched_at: str | None = None


@runtime_checkable
class StatusProbe(Protocol):
    def probe(self) -> StatusReport: ...


@runtime_checkable
class ModelCatalogReader(Protocol):
    def read(self) -> ModelListing: ...


@runtime_checkable
class BinaryResolver(Protocol):
    def resolve(self) -> str | None: ...


@runtime_checkable
class FramingHook(Protocol):
    def frame(self, verb: str, framing: str, host_name: str) -> str: ...


@dataclass(frozen=True)
class BackendPlugin:
    contract: BackendContract
    backend: AgentBackend
    options: tuple[OptionSpec, ...]
    status: StatusProbe
    models: ModelCatalogReader
    binary: BinaryResolver
    help_probe: HelpProbe
    vocabulary: BackendErrorVocabulary
    env: EnvNamespace
    effects: AnnotationEffects
    repair_overrides: Mapping[str, RepairRule] = field(default_factory=dict)
    framing: FramingHook | None = None
    local_codes: Mapping[str, RepairRule] = field(default_factory=dict)
    # Agent-facing disclosures the contract does not carry: what a paid call sends where,
    # and which carriers (argv, handshake file) hold the prompt on this backend.
    egress: str = ""
    carriers: str = ""
    api_version: int = PLUGIN_API_VERSION

    @property
    def backend_id(self) -> str:
        return self.contract.backend_id
