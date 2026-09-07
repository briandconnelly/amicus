"""The advisory static model catalog for `model` discovery (ported from claude-in-codex
`claude_models.py`). Claude Code writes no model cache and has no free list command, so
the catalog is contract.KNOWN_MODELS; the CLI validates the real slug at run time."""

from __future__ import annotations

from typing import TYPE_CHECKING

from amicus.backends.claude import contract
from amicus.plugin import ModelEntry, ModelListing

if TYPE_CHECKING:  # pragma: no cover
    from amicus.backends.claude.config import ClaudeConfig

ADVISORY = (
    "Advisory model list for the `model` parameter — not authoritative. The claude CLI "
    "validates the slug at run time; an unlisted slug may still work and a listed one may be "
    "unavailable to your account. Prefer the aliases (opus, sonnet, haiku, fable), which track "
    "the latest model, over pinned full IDs that go stale."
)


class ClaudeModels:
    """The plugin's ModelCatalogReader: static, no filesystem, no spawn."""

    def __init__(self, config: ClaudeConfig) -> None:
        self._config = config

    def read(self, force: bool = False) -> ModelListing:  # noqa: ARG002
        return ModelListing(
            models=tuple(
                ModelEntry(slug=slug, display_name=name)
                for slug, name, _kind in contract.KNOWN_MODELS
            ),
            source="static",
        )
