"""BackendContract: the static facts about one backend CLI, as pure data.

Behavior lives in the :class:`~amicus.sdk.backend.protocol.AgentBackend`
implementation; everything here is declarative and inspectable — the material
capability output, conformance checks, and the shared failure classifier are
driven by. Each bridge's ``cli_contract.py`` collapses into one instance of
this plus whatever backend-local constants remain.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

Authority = Literal["advisory", "authoritative"]
# How a backend's pre-spend effort validation works (0.3.0, from the Kimi adapter):
# "enumerated" — a fixed value set is checked locally; "token_floor_plus_catalog" —
# a universal token vocabulary is the floor and the live catalog refines it,
# failing OPEN when the catalog cannot answer; "shape_only" — only argv-hostile
# shapes are refused locally because upstream rejects bad values loudly itself.
EffortValidation = Literal["enumerated", "token_floor_plus_catalog", "shape_only"]
CatalogStrategy = Literal["static", "cache_with_static_fallback", "live_probe"]
StructuredOutputStrategy = Literal["argv_flag", "prompt_append"]


class IsolationPolicy(Enum):
    """How read-only/write postures are actually enforced for this backend."""

    SANDBOX_FLAG = "sandbox_flag"  # a real CLI sandbox flag (codex --sandbox)
    TOOL_ALLOWLIST = "tool_allowlist"  # generated agent profile / --tools list
    WORKTREE_ALL_TIERS = "worktree_all_tiers"  # no CLI mechanism; every tier isolated


@dataclass(frozen=True)
class ModelCatalog:
    """Where model identifiers come from and how much to trust them.

    Authority is FIELD-SCOPED because it genuinely differs per field: Kimi's
    alias set is authoritative (an unknown alias is rejected outright) while its
    effort metadata is advisory (a bad effort is silently ignored upstream).
    """

    strategy: CatalogStrategy
    model_identifier_authority: Authority
    effort_metadata_authority: Authority


@dataclass(frozen=True)
class ExtraArgsPolicy:
    """Typed operator extra-args policy — not a flat allowlist.

    ``allowed_option_forms``: exact option spellings an operator may pass
    (e.g. ``-c``/``--config``, ``-p``/``--profile``). Empty means every
    configured value is refused loudly (the Kimi policy) rather than silently
    dropped. ``forbidden_config_roots``/``forbidden_features`` name the config
    roots and feature toggles that may never be reached even through an allowed
    form (sandbox, approvals, connector suppression). ``reserved_keys`` are
    config keys owned by first-class parameters (model, effort) so extra args
    cannot shadow them.
    """

    allowed_option_forms: tuple[str, ...] = ()
    forbidden_config_roots: frozenset[str] = frozenset()
    forbidden_features: frozenset[str] = frozenset()
    reserved_keys: frozenset[str] = frozenset()


@dataclass(frozen=True)
class FailureSignatures:
    """Regex tables the shared classifier consumes; the predicate functions in
    today's ``cli_contract.py`` files become this data. All patterns are matched
    against the run's combined diagnostics (stderr and, where the backend hook
    says so, event/envelope text)."""

    auth: tuple[str, ...] = ()
    contract_drift: tuple[str, ...] = ()
    invalid_model: tuple[str, ...] = ()
    rate_limited: tuple[str, ...] = ()
    retry_after_ms: str | None = None  # one capture group holding milliseconds

    def compiled(self) -> dict[str, list[re.Pattern[str]]]:
        return {
            "auth": [re.compile(p) for p in self.auth],
            "contract_drift": [re.compile(p) for p in self.contract_drift],
            "invalid_model": [re.compile(p) for p in self.invalid_model],
            "rate_limited": [re.compile(p) for p in self.rate_limited],
        }


@dataclass(frozen=True)
class Limits:
    """Transport bounds that shape prompt delivery."""

    max_argv_prompt_chars: int | None = None  # None: prompt never rides argv
    handshake_dir_name: str | None = None  # None: no handshake-file transport
    answer_file_name: str | None = None  # None: no answer-file channel


@dataclass(frozen=True)
class BackendContract:
    """The static contract for one backend CLI."""

    backend_id: str  # "codex" | "kimi" | "claude" | ...
    display_name: str
    bin_name: str
    env_prefix: str  # e.g. "MOONBRIDGE_" — the BRIDGE's env namespace
    exec_argv_prefix: tuple[str, ...]  # subcommand shape: ("exec",) / () / ("-p",)
    always_send_flags: tuple[str, ...]  # guarantee-bearing; never help-gated
    help_gated_flags: tuple[str, ...]  # depth/cosmetic; dropped when --help lacks them
    forbidden_surface_phrases: tuple[str, ...]  # wire prose that would contradict this contract
    supported_features: frozenset[str]  # {"delegate","transfer","sessions","usage_accounting",...}
    readonly_honesty_statement: str  # what read-only DOES and DOES NOT guarantee here
    implicit_context_disclosure: str  # what the CLI auto-loads that isolation cannot suppress
    structured_output: StructuredOutputStrategy
    model_catalog: ModelCatalog
    isolation_policy: IsolationPolicy
    needs_orphan_sweep: bool
    effort_silently_ignored_upstream: bool  # True => validate_request MUST check effort pre-spend
    effort_validation: EffortValidation = "enumerated"  # how that pre-spend check works
    usage_event_markers: tuple[str, ...] = ()  # empty: this backend emits no usage events
    extra_args: ExtraArgsPolicy = field(default_factory=ExtraArgsPolicy)
    failure_signatures: FailureSignatures = field(default_factory=FailureSignatures)
    limits: Limits = field(default_factory=Limits)

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", self.backend_id):
            raise ValueError(f"backend_id {self.backend_id!r} must be a lowercase identifier")
        if not self.env_prefix.endswith("_") or not self.env_prefix.isupper():
            raise ValueError(f"env_prefix {self.env_prefix!r} must be UPPER_SNAKE_ ending in _")
        if not self.readonly_honesty_statement.strip():
            raise ValueError("readonly_honesty_statement must state the actual guarantee")
        if not self.implicit_context_disclosure.strip():
            raise ValueError("implicit_context_disclosure must state what the CLI auto-loads")
