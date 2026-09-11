"""The OptionSpec table: config_mode, access and max_budget_usd are the wire-visible Claude
options; model and reasoning_effort carry the AMICUS_CLAUDE_* defaults the tools resolve with.
Entries apply only to the verbs Claude runs (never delegate); config_mode has a
separate default for adversarial reviews."""

from __future__ import annotations

from typing import TYPE_CHECKING

from amicus.plugin import OptionSpec

if TYPE_CHECKING:  # pragma: no cover
    from amicus.backends.claude.config import ClaudeConfig

_PAID_VERBS = frozenset({"consult", "review_changes", "adversarial_review"})


def adversarial_config_mode(config: ClaudeConfig) -> str:
    """Isolate critic runs by default while preserving an API-key-only setup."""
    return "bare" if config.config_mode == "bare" else "safe"


def options_for(config: ClaudeConfig) -> tuple[OptionSpec, ...]:
    return (
        OptionSpec(
            "config_mode",
            "config_mode",
            frozenset({"consult", "review_changes"}),
            config.config_mode,
        ),
        OptionSpec(
            "config_mode",
            "config_mode",
            frozenset({"adversarial_review"}),
            adversarial_config_mode(config),
        ),
        OptionSpec("access", "access", _PAID_VERBS, config.access),
        OptionSpec("max_budget_usd", "budget_usd", _PAID_VERBS, config.max_budget_usd),
        OptionSpec("model", "model", _PAID_VERBS, config.model),
        OptionSpec("reasoning_effort", "reasoning_effort", _PAID_VERBS, config.reasoning_effort),
    )
