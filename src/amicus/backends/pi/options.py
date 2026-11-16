"""The OptionSpec table: `max_budget_usd` is pi's one wire-visible option (#454); it and
`model` and `reasoning_effort` carry the AMICUS_PI_* defaults the tools resolve with. Pi has
no isolation option."""

from __future__ import annotations

from typing import TYPE_CHECKING

from amicus.plugin import OptionSpec

if TYPE_CHECKING:  # pragma: no cover
    from amicus.backends.pi.config import PiConfig

_PAID_VERBS = frozenset({"consult", "review_changes", "delegate"})


def options_for(config: PiConfig) -> tuple[OptionSpec, ...]:
    return (
        OptionSpec("max_budget_usd", "budget_usd", _PAID_VERBS, config.max_budget_usd),
        OptionSpec("model", "model", _PAID_VERBS, config.model),
        OptionSpec("reasoning_effort", "reasoning_effort", _PAID_VERBS, config.reasoning_effort),
    )
