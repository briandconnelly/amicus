"""The Kimi backend plugin (M3): `plugin()` assembles the frozen pontonier contract, the
adapter, and the amicus-side facts from the AMICUS_KIMI_* environment."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pontonier.conventions.annotations import AnnotationEffects
from pontonier.conventions.envelope import BackendErrorVocabulary
from pontonier.conventions.preflight import HelpProbe

from amicus.backends.kimi import config as kimi_config
from amicus.backends.kimi import contract
from amicus.backends.kimi.adapter import KimiBackend
from amicus.backends.kimi.binary import KimiBinary
from amicus.backends.kimi.models import KimiModels
from amicus.backends.kimi.options import options_for
from amicus.backends.kimi.status import KimiStatus
from amicus.plugin import BackendPlugin

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Mapping

VOCABULARY = BackendErrorVocabulary(
    backend_id="kimi",
    display_name="Kimi",
    install_hint="Install the kimi CLI (Kimi Code), then rerun amicus_backends.",
    login_hint=(
        "Run `kimi login` or configure a provider in kimi's config.toml, then rerun "
        "amicus_backends."
    ),
    status_tool="amicus_backends",
)
EGRESS = (
    "Sends your question/task, extra_context and instructions_append raw, and the "
    "secret-redacted diff for reviews, to your configured Kimi provider (Moonshot or any "
    "OpenAI-compatible endpoint named in kimi's config.toml) via the kimi CLI. "
    f"{contract.REDACTION_LIMIT_FACT} {contract.SKILLS_DISCOVERY_FACT_FULL} "
    f"{contract.SKILLS_ISOLATION_NOTE}"
)
CARRIERS = (
    "The prompt (framing, question/task/diff, extra_context, and instructions_append as a "
    "leading caller-instructions section) is written to a private handshake file under a "
    "temp dir outside the workspace; argv carries only a short pointer naming that file's "
    "path, the stream-json output flag and, for consult and review, the path of the "
    "generated read-only agent profile. Nothing you type rides argv, and kimi ignores stdin."
)


def plugin(environ: Mapping[str, str] | None = None) -> BackendPlugin:
    cfg = kimi_config.load_config(environ)
    binary = KimiBinary(cfg)
    # resolve() is None only for an unusable AMICUS_KIMI_BIN override; probe that same
    # already-known-unusable value rather than a PATH-searched "kimi".
    token = binary.resolve() or cfg.bin_override or contract.KIMI_BIN
    help_probe = HelpProbe(
        help_argv=(token, *contract.HELP_ARGS),
        always_send_flags=contract.CONTRACT.always_send_flags,
        cache_ttl_seconds=contract.HELP_CACHE_TTL_SECONDS,
    )
    catalog = KimiModels(cfg, binary)
    return BackendPlugin(
        contract=contract.CONTRACT,
        backend=KimiBackend(cfg, binary, help_probe, catalog),
        options=options_for(cfg),
        status=KimiStatus(cfg, binary, help_probe),
        models=catalog,
        binary=binary,
        help_probe=help_probe,
        vocabulary=VOCABULARY,
        env=kimi_config.ENV,
        effects=AnnotationEffects(paid_calls_destructive=False, job_reads_read_only=True),
        egress=EGRESS,
        carriers=CARRIERS,
    )
