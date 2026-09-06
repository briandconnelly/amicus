"""The OptionSpec table: `isolation` is the one wire-visible backend option; `model` and
`reasoning_effort` entries carry the AMICUS_KIMI_* defaults the tools resolve with."""

from __future__ import annotations

from typing import TYPE_CHECKING

from amicus.plugin import OptionSpec

if TYPE_CHECKING:  # pragma: no cover
    from amicus.backends.kimi.config import KimiConfig

_PAID_VERBS = frozenset({"consult", "review_changes", "delegate"})


def options_for(config: KimiConfig) -> tuple[OptionSpec, ...]:
    return (
        OptionSpec("isolation", "isolation", _PAID_VERBS, config.isolation),
        OptionSpec("model", "model", _PAID_VERBS, config.model),
        OptionSpec("reasoning_effort", "reasoning_effort", _PAID_VERBS, config.reasoning_effort),
    )
