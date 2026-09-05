"""Read Codex's on-disk models cache for advisory slug discovery (ported from
codex-in-claude `codex_models.py`). Cache → bundled static list → none."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from pontonier.core import redaction
from pontonier.core.jsoncache import read_bounded_json

from amicus.backends.codex import contract
from amicus.plugin import ModelEntry, ModelListing

if TYPE_CHECKING:  # pragma: no cover
    from amicus.backends.codex.config import CodexConfig


def codex_home() -> Path | None:
    """$CODEX_HOME if set, else ~/.codex; None when the path cannot be expanded."""
    env = os.environ.get("CODEX_HOME")
    try:
        return Path(env).expanduser() if env else Path.home() / ".codex"
    except RuntimeError:
        return None


def _effort_token(value: object) -> str | None:
    if not isinstance(value, str) or not contract.REASONING_EFFORT_TOKEN_PATTERN.match(value):
        return None
    return value


def _supported_efforts(raw: object) -> tuple[str, ...] | None:
    if not isinstance(raw, list):
        return None
    efforts: list[str] = []
    for entry in raw[: contract.SUPPORTED_EFFORTS_MAX_ENTRIES]:
        token = _effort_token(entry.get("effort")) if isinstance(entry, dict) else None
        if token is not None and token not in efforts:
            efforts.append(token)
    if raw and not efforts:
        return None
    return tuple(efforts)


def _label(value: object, cap: int) -> str | None:
    if not isinstance(value, str) or len(value) > cap:
        return None
    return redaction.sanitize_echo(value) or None


def parse_models(raw: object) -> tuple[list[ModelEntry], str | None] | None:
    """(entries, fetched_at) from the cache's expected shape, or None when it drifted."""
    if not isinstance(raw, dict):
        return None
    entries = raw.get("models")
    if not isinstance(entries, list):
        return None
    models: list[ModelEntry] = []
    for entry in entries[: contract.MODELS_CACHE_MAX_ENTRIES]:
        if not isinstance(entry, dict):
            continue
        slug = entry.get("slug")
        if not isinstance(slug, str) or not contract.MODEL_SLUG_PATTERN.match(slug):
            continue
        models.append(
            ModelEntry(
                slug=slug,
                display_name=_label(entry.get("display_name"), 128),
                default_reasoning_effort=_effort_token(entry.get("default_reasoning_level")),
                supported_reasoning_efforts=_supported_efforts(
                    entry.get("supported_reasoning_levels")
                ),
            )
        )
    if not models:
        return None
    return models, _label(raw.get("fetched_at"), 64)


class CodexModels:
    def __init__(self, config: CodexConfig) -> None:
        self._config = config

    def read(self) -> ModelListing:
        home = codex_home()
        raw = (
            read_bounded_json(
                home / contract.MODELS_CACHE_FILENAME, contract.MODELS_CACHE_MAX_BYTES
            )
            if home is not None
            else None
        )
        parsed = parse_models(raw) if raw is not None else None
        if parsed is not None:
            models, fetched_at = parsed
            return ModelListing(models=tuple(models), source="cache", fetched_at=fetched_at)
        if contract.KNOWN_MODEL_SLUGS:
            return ModelListing(
                models=tuple(ModelEntry(slug=s) for s in contract.KNOWN_MODEL_SLUGS),
                source="static",
            )
        return ModelListing(models=(), source="none")
