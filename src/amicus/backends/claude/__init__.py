"""The Claude Code backend plugin (M4): `plugin()` assembles the frozen pontonier contract, the
adapter, and the amicus-side facts from the AMICUS_CLAUDE_* environment."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pontonier.conventions.annotations import AnnotationEffects
from pontonier.conventions.envelope import BackendErrorVocabulary, RepairRule
from pontonier.conventions.preflight import HelpProbe

from amicus.backends.claude import cli, contract
from amicus.backends.claude import config as claude_config
from amicus.backends.claude.adapter import ClaudeBackend
from amicus.backends.claude.adversarial import ClaudeFraming
from amicus.backends.claude.binary import ClaudeBinary
from amicus.backends.claude.models import ClaudeModels
from amicus.backends.claude.options import options_for
from amicus.backends.claude.status import ClaudeStatus
from amicus.plugin import BackendPlugin

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Mapping

VOCABULARY = BackendErrorVocabulary(
    backend_id="claude",
    display_name="Claude Code",
    install_hint=(
        "Install Claude Code (`npm install -g @anthropic-ai/claude-code`), then rerun "
        "amicus_backends."
    ),
    login_hint=(
        "Run `claude /login` (or set ANTHROPIC_API_KEY for backend_options.config_mode='bare'), "
        "then rerun amicus_backends."
    ),
    status_tool="amicus_backends",
)
# Claude-local codes (M4): joined the closed catalog as a deliberate fingerprint bump; these
# rules override the neutral ones in errors._LOCAL_RULES for Claude failures.
LOCAL_CODES: dict[str, RepairRule] = {
    "budget_exceeded": RepairRule("reduce_input", None, False, cli.BUDGET_REPAIR),
    "claude_permission_error": RepairRule("correct_arguments", None, False, cli.PERMISSION_REPAIR),
    "api_key_invalid": RepairRule(
        "authenticate",
        "amicus_backends",
        False,
        "ANTHROPIC_API_KEY was rejected by Anthropic. Set a valid key (config_mode=bare) or use "
        "a login mode after `claude /login`; amicus_backends reports the key posture.",
    ),
    "api_key_missing": RepairRule(
        "correct_config",
        "amicus_backends",
        False,
        "config_mode=bare runs only on ANTHROPIC_API_KEY, which is unset for the server process. "
        "Set it, or use backend_options.config_mode inherit/scoped/safe. No model call was made.",
    ),
}
# The first repair_overrides entry in amicus: a Claude timeout MAY have been charged and a
# replay may double-charge, so it is not temporary and the next step is a new (async) job.
REPAIR_OVERRIDES: dict[str, RepairRule] = {
    "timeout": RepairRule("start_new_job", None, False, cli.TIMEOUT_REPAIR),
}
EGRESS = (
    "Sends your question/target/evidence, extra_context and instructions_append raw, and the "
    "secret-redacted diff for reviews and critiques, to Anthropic via the claude CLI, using "
    "your Claude login (config_mode inherit/scoped/safe) or ANTHROPIC_API_KEY (bare). "
    f"{contract.READ_ONLY_HONESTY} {contract.IMPLICIT_CONTEXT_DISCLOSURE}"
)
CARRIERS = (
    "The prompt (framing, question/target/evidence/diff, extra_context, and instructions_append "
    "as a leading caller-instructions section) rides the claude process's stdin. argv carries "
    "only constant text and flags: the independent-critic guardrails on --append-system-prompt "
    "(fixed text, never composed with caller input), the config-mode and access flags, the "
    "budget, and the help-gated --effort/--model. Nothing you type rides argv."
)


def plugin(environ: Mapping[str, str] | None = None) -> BackendPlugin:
    cfg = claude_config.load_config(environ)
    binary = ClaudeBinary(cfg)
    # resolve() is None only for an unusable AMICUS_CLAUDE_BIN override; probe that same
    # already-known-unusable value rather than a PATH-searched "claude".
    token = binary.resolve() or cfg.bin_override or contract.CLAUDE_BIN
    help_probe = HelpProbe(
        help_argv=(token, *contract.HELP_ARGS),
        always_send_flags=contract.CONTRACT.always_send_flags,
        cache_ttl_seconds=contract.HELP_CACHE_TTL_SECONDS,
    )
    return BackendPlugin(
        contract=contract.CONTRACT,
        backend=ClaudeBackend(cfg, binary, help_probe),
        options=options_for(cfg),
        status=ClaudeStatus(cfg, binary, help_probe),
        models=ClaudeModels(cfg),
        binary=binary,
        help_probe=help_probe,
        vocabulary=VOCABULARY,
        env=claude_config.ENV,
        # ADR 0001: Claude's inherit/scoped modes can run workspace hooks (shell) outside the
        # tool allowlist, so its paid calls advertise destructiveHint: true.
        effects=AnnotationEffects(paid_calls_destructive=True, job_reads_read_only=True),
        repair_overrides=REPAIR_OVERRIDES,
        framing=ClaudeFraming(),
        local_codes=LOCAL_CODES,
        egress=EGRESS,
        carriers=CARRIERS,
    )
