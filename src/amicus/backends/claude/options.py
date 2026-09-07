"""The OptionSpec table: config_mode, access and max_budget_usd are the wire-visible Claude
options; model and reasoning_effort carry the AMICUS_CLAUDE_* defaults the tools resolve with.
Every entry applies to the three verbs Claude runs (never delegate)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from amicus.plugin import OptionSpec

if TYPE_CHECKING:  # pragma: no cover
    from amicus.backends.claude.config import ClaudeConfig

_PAID_VERBS = frozenset({"consult", "review_changes", "adversarial_review"})


def options_for(config: ClaudeConfig) -> tuple[OptionSpec, ...]:
    return (
        OptionSpec("config_mode", "config_mode", _PAID_VERBS, config.config_mode),
        OptionSpec("access", "access", _PAID_VERBS, config.access),
        OptionSpec("max_budget_usd", "budget_usd", _PAID_VERBS, config.max_budget_usd),
        OptionSpec("model", "model", _PAID_VERBS, config.model),
        OptionSpec("reasoning_effort", "reasoning_effort", _PAID_VERBS, config.reasoning_effort),
    )
