"""The pi backend: the pi coding-agent CLI behind the `BackendPlugin` seam. `plugin()`
assembles the SDK contract, the adapter, and the amicus-side facts from the AMICUS_PI_*
environment."""

from __future__ import annotations

from typing import TYPE_CHECKING

from amicus.backends.pi import config as pi_config
from amicus.backends.pi import contract
from amicus.backends.pi.adapter import PiBackend
from amicus.backends.pi.binary import PiBinary
from amicus.backends.pi.models import HELP_CACHE_TTL_SECONDS, PiModels
from amicus.backends.pi.options import options_for
from amicus.backends.pi.status import PiStatus
from amicus.plugin import BackendPlugin
from amicus.sdk.conventions.annotations import AnnotationEffects
from amicus.sdk.conventions.envelope import BackendErrorVocabulary
from amicus.sdk.conventions.preflight import HelpProbe

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Mapping

VOCABULARY = BackendErrorVocabulary(
    backend_id="pi",
    display_name="Pi",
    install_hint="Install the pi coding agent (https://pi.dev), then rerun amicus_backends.",
    login_hint=contract.LOGIN_HINT,
    status_tool="amicus_backends",
)
EGRESS = contract.EGRESS
CARRIERS = contract.CARRIERS


def plugin(environ: Mapping[str, str] | None = None) -> BackendPlugin:
    cfg = pi_config.load_config(environ)
    binary = PiBinary(cfg)
    # resolve() is None only for an unusable AMICUS_PI_BIN override; probe that same
    # already-known-unusable value rather than a PATH-searched "pi".
    token = binary.resolve() or cfg.bin_override or contract.PI_BIN
    help_probe = HelpProbe(
        help_argv=(token, *contract.HELP_ARGS),
        always_send_flags=contract.CONTRACT.always_send_flags,
        cache_ttl_seconds=HELP_CACHE_TTL_SECONDS,
        probe_cwd=lambda: pi_config.probe_cwd(cfg),
    )
    catalog = PiModels(cfg, binary)
    return BackendPlugin(
        contract=contract.CONTRACT,
        backend=PiBackend(cfg, binary, help_probe, catalog),
        options=options_for(cfg),
        status=PiStatus(cfg, binary, help_probe),
        models=catalog,
        binary=binary,
        help_probe=help_probe,
        vocabulary=VOCABULARY,
        env=pi_config.ENV,
        effects=AnnotationEffects(paid_calls_destructive=True, job_reads_read_only=True),
        egress=EGRESS,
        carriers=CARRIERS,
    )
