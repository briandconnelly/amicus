"""A conforming fake backend plugin for the registry, discovery and forced-error tests.

Loaded through the real entry-point path (`amicus.registry`) by pointing an EntryPoint at
`tests.support.fakeplugin:plugin`, so the loading code is exercised end-to-end."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from typing import Any

from pontonier.backend.contract import BackendContract, IsolationPolicy, ModelCatalog
from pontonier.backend.protocol import (
    ClassifiedFailure,
    ExecResult,
    PreparedRun,
    RunOutcome,
    RunRequest,
)
from pontonier.conventions.annotations import AnnotationEffects
from pontonier.conventions.envelope import BackendErrorVocabulary
from pontonier.conventions.preflight import HelpProbe

from amicus.config.envspec import EnvNamespace
from amicus.plugin import (
    PLUGIN_API_VERSION,
    BackendPlugin,
    ModelEntry,
    ModelListing,
    OptionSpec,
    StatusReport,
)


def make_contract(
    backend_id: str = "fake", features: frozenset[str] = frozenset()
) -> BackendContract:
    return BackendContract(
        backend_id=backend_id,
        display_name=backend_id.title(),
        bin_name=backend_id,
        env_prefix=f"AMICUS_{backend_id.upper()}_",
        exec_argv_prefix=(),
        always_send_flags=("--json",),
        help_gated_flags=("--model",),
        forbidden_surface_phrases=("applies the diff to your working tree",),
        supported_features=features,
        readonly_honesty_statement="Read-only bounds writes, not reads.",
        implicit_context_disclosure="Auto-loads nothing.",
        structured_output="prompt_append",
        model_catalog=ModelCatalog("static", "advisory", "advisory"),
        isolation_policy=IsolationPolicy.SANDBOX_FLAG,
        needs_orphan_sweep=False,
        effort_silently_ignored_upstream=False,
    )


class FakeBackend:
    def validate_request(self, request: RunRequest) -> ClassifiedFailure | None:
        return None

    def prepare(self, request: RunRequest) -> Any:
        @contextlib.asynccontextmanager
        async def _cm() -> AsyncIterator[PreparedRun]:
            yield PreparedRun(argv=("fake",), env={}, cwd=request.cwd)

        return _cm()

    def finalize(self, outcome: RunOutcome, request: RunRequest) -> ExecResult:
        return ExecResult(answer=outcome.run.stdout)

    def classify_failure(self, outcome: RunOutcome, request: RunRequest) -> ClassifiedFailure:
        return ClassifiedFailure(code="nonzero_exit", detail=outcome.run.stderr[:80])

    def list_models(self) -> tuple[str, ...]:
        return ("fake-1",)

    def auth_probe(self) -> bool | None:
        return True

    def scrub_env(self, env: dict[str, str], config_mode: str | None) -> dict[str, str]:
        return dict(env)


class _Status:
    def probe(self) -> StatusReport:
        return StatusReport(installed=True, version="fake 1.0", authenticated=True)


class _Models:
    def read(self) -> ModelListing:
        return ModelListing(models=(ModelEntry(slug="fake-1"),), source="static")


class _Binary:
    def resolve(self) -> str | None:
        return "/usr/bin/true"


def make_plugin(backend_id: str = "fake", **overrides: Any) -> BackendPlugin:
    fields: dict[str, Any] = {
        "contract": make_contract(backend_id, overrides.pop("features", frozenset({"delegate"}))),
        "backend": FakeBackend(),
        "options": (OptionSpec("isolation", "isolation", frozenset({"consult"}), "inherit"),),
        "status": _Status(),
        "models": _Models(),
        "binary": _Binary(),
        "help_probe": HelpProbe(help_argv=("true", "--help")),
        "vocabulary": BackendErrorVocabulary(
            backend_id, backend_id.title(), "Install fake.", "Log in to fake.", "amicus_backends"
        ),
        "env": EnvNamespace(prefix=f"AMICUS_{backend_id.upper()}_", vars=()),
        "effects": AnnotationEffects(paid_calls_destructive=False, job_reads_read_only=True),
        "api_version": PLUGIN_API_VERSION,
    }
    fields.update(overrides)
    return BackendPlugin(**fields)


plugin = make_plugin()
