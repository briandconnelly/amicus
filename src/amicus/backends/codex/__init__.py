"""The Codex backend plugin (M1): `plugin()` assembles the frozen pontonier contract, the
adapter, and the amicus-side facts from the AMICUS_CODEX_* environment."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pontonier.conventions.annotations import AnnotationEffects
from pontonier.conventions.envelope import BackendErrorVocabulary, RepairRule
from pontonier.conventions.preflight import HelpProbe

from amicus.backends.codex import config as codex_config
from amicus.backends.codex import contract
from amicus.backends.codex.adapter import CodexBackend
from amicus.backends.codex.binary import CodexBinary
from amicus.backends.codex.models import CodexModels
from amicus.backends.codex.options import options_for
from amicus.backends.codex.status import CodexStatus
from amicus.plugin import BackendPlugin

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Mapping

VOCABULARY = BackendErrorVocabulary(
    backend_id="codex",
    display_name="Codex",
    install_hint=(
        "Install the codex CLI (`npm install -g @openai/codex`), then rerun amicus_backends."
    ),
    login_hint="Run `codex login`, then rerun amicus_backends.",
    status_tool="amicus_backends",
)
LOCAL_CODES: dict[str, RepairRule] = {
    "user_config_rejected": RepairRule(
        "correct_config",
        None,
        False,
        "The codex CLI refused to start because of a key or value in your own Codex config; "
        "the message names it. Fix that setting (or pass backend_options.isolation="
        "'ignore-config' to skip your config file for one run), then retry. No model call "
        "was made.",
    ),
}
EGRESS = (
    "Sends your question/task, extra_context and instructions_append raw, and the "
    f"secret-redacted diff for reviews, to OpenAI via the codex CLI. {contract.READ_SCOPE_FACT} "
    f"{contract.IMPLICIT_CONTEXT_DISCLOSURE} {contract.WORKSPACE_WRITE_SCOPE_FACT}"
)
CARRIERS = (
    "The prompt (framing, question/task/diff, extra_context) rides the codex process's "
    "stdin; instructions_append rides the command line as the `-c developer_instructions` "
    "config override, so it is visible in local process listings for the run's duration."
)


def plugin(environ: Mapping[str, str] | None = None) -> BackendPlugin:
    cfg = codex_config.load_config(environ)
    binary = CodexBinary(cfg)
    # resolve() is None only for an unusable AMICUS_CODEX_BIN override (codex_bin() raises
    # exactly then), which always means bin_override is set; probe that same
    # already-known-unusable value rather than falling back to a PATH-searched "codex",
    # which would silently ignore the operator's override and spawn the real CLI.
    token = binary.resolve() or cfg.bin_override or contract.CODEX_BIN
    help_probe = HelpProbe(
        help_argv=(token, *contract.EXEC_HELP_ARGS),
        always_send_flags=contract.CONTRACT.always_send_flags,
        cache_ttl_seconds=contract.HELP_CACHE_TTL_SECONDS,
    )
    return BackendPlugin(
        contract=contract.CONTRACT,
        backend=CodexBackend(cfg, binary, help_probe),
        options=options_for(cfg),
        status=CodexStatus(cfg, binary, help_probe),
        models=CodexModels(cfg),
        binary=binary,
        help_probe=help_probe,
        vocabulary=VOCABULARY,
        env=codex_config.ENV,
        effects=AnnotationEffects(paid_calls_destructive=False, job_reads_read_only=True),
        local_codes=LOCAL_CODES,
        egress=EGRESS,
        carriers=CARRIERS,
    )
