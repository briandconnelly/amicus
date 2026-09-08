"""A conforming third-party backend plugin, built and installed as a real wheel.

This is the out-of-tree twin of `tests/support/fakeplugin.py`: same conforming shape, but
registered through a genuinely installed distribution's `amicus.backends` entry point
rather than a same-repo import path, so `tests/test_wheel_seam.py` can exercise the seam
`amicus.registry` promises to third parties end-to-end."""

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
    BackendPlugin,
    ModelEntry,
    ModelListing,
    OptionSpec,
    StatusReport,
)

BACKEND_ID = "fakebackend"

CONTRACT = BackendContract(
    backend_id=BACKEND_ID,
    display_name=BACKEND_ID.title(),
    bin_name=BACKEND_ID,
    env_prefix=f"AMICUS_{BACKEND_ID.upper()}_",
    exec_argv_prefix=(),
    always_send_flags=("--json",),
    help_gated_flags=("--model",),
    forbidden_surface_phrases=("applies the diff to your working tree",),
    supported_features=frozenset({"consult"}),
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
            yield PreparedRun(
                argv=(BACKEND_ID,), env={}, cwd=request.cwd, stdin_text=request.prompt
            )

        return _cm()

    def finalize(self, outcome: RunOutcome, request: RunRequest) -> ExecResult:
        return ExecResult(answer=outcome.run.stdout)

    def classify_failure(self, outcome: RunOutcome, request: RunRequest) -> ClassifiedFailure:
        return ClassifiedFailure(code="nonzero_exit", detail=outcome.run.stderr[:80])

    def list_models(self) -> tuple[str, ...]:
        return ("fakebackend-1",)

    def auth_probe(self) -> bool | None:
        return True

    def scrub_env(self, env: dict[str, str], config_mode: str | None) -> dict[str, str]:
        return dict(env)


class _Status:
    def probe(self) -> StatusReport:
        return StatusReport(installed=True, version="fakebackend 1.0", authenticated=True)


class _Models:
    def read(self) -> ModelListing:
        return ModelListing(models=(ModelEntry(slug="fakebackend-1"),), source="static")


class _Binary:
    def resolve(self) -> str | None:
        return "/usr/bin/true"


plugin = BackendPlugin(
    contract=CONTRACT,
    backend=FakeBackend(),
    options=(OptionSpec("isolation", "isolation", frozenset({"consult"}), "inherit"),),
    status=_Status(),
    models=_Models(),
    binary=_Binary(),
    help_probe=HelpProbe(help_argv=("true", "--help")),
    vocabulary=BackendErrorVocabulary(
        BACKEND_ID,
        BACKEND_ID.title(),
        "Install fakebackend.",
        "Log in to fakebackend.",
        "amicus_backends",
    ),
    env=EnvNamespace(prefix=f"AMICUS_{BACKEND_ID.upper()}_", vars=()),
    effects=AnnotationEffects(paid_calls_destructive=False, job_reads_read_only=True),
    api_version=API_VERSION_PLACEHOLDER,  # noqa: F821 -- substituted by tests/test_wheel_seam.py
)
