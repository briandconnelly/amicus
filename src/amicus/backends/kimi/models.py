"""Read Kimi's configured model aliases for `model` and `reasoning_effort` discovery
(ported from moonbridge `kimi_models.py`). `-m` takes an ALIAS from the user's config.toml,
so the catalog is `kimi provider list --json`, read live and cached briefly in-process.

**The source contains secrets**: its `providers` block carries `apiKey` and `baseUrl`.
`parse_catalog` is allowlist-shaped — it reads named fields off `models` only — so a new
secret-bearing field upstream cannot leak by default. Authoritative for the alias set
(kimi rejects an unknown alias); advisory for efforts (see `supported_efforts_for`)."""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

from pontonier.core import redaction, runtime

from amicus.backends.kimi import contract
from amicus.plugin import ModelEntry, ModelListing

if TYPE_CHECKING:  # pragma: no cover
    from amicus.backends.kimi.binary import KimiBinary
    from amicus.backends.kimi.config import KimiConfig

PROBE_TIMEOUT_SECONDS = 10


def _effort_token(value: object) -> str | None:
    """SHAPE only, never vocabulary: the catalog is what the model DECLARES."""
    if not isinstance(value, str) or not contract.REASONING_EFFORT_TOKEN_PATTERN.fullmatch(value):
        return None
    return value


def _supported_efforts(raw: object) -> tuple[str, ...] | None:
    """None = absent or unusable; () = an explicitly empty advertised set."""
    if not isinstance(raw, list):
        return None
    efforts: list[str] = []
    for entry in raw[: contract.SUPPORTED_EFFORTS_MAX_ENTRIES]:
        token = _effort_token(entry)
        if token is not None and token not in efforts:
            efforts.append(token)
    if raw and not efforts:
        return None
    return tuple(efforts)


def _label(value: object, cap: int) -> str | None:
    if not isinstance(value, str) or len(value) > cap:
        return None
    return redaction.sanitize_echo(value) or None


def parse_catalog(payload: object) -> list[ModelEntry] | None:
    """Model aliases from a `kimi provider list --json` payload, or None if it drifted.
    Reads ONLY the `models` map; the sibling `providers` map is never touched."""
    if not isinstance(payload, dict):
        return None
    entries = payload.get("models")
    if not isinstance(entries, dict):
        return None
    models: list[ModelEntry] = []
    for alias, entry in list(entries.items())[: contract.MODELS_CACHE_MAX_ENTRIES]:
        if not isinstance(alias, str) or not contract.MODEL_SLUG_PATTERN.match(alias):
            continue
        fields = entry if isinstance(entry, dict) else {}
        models.append(
            ModelEntry(
                slug=alias,
                display_name=_label(fields.get("displayName"), 128),
                default_reasoning_effort=_effort_token(fields.get("defaultEffort")),
                supported_reasoning_efforts=_supported_efforts(fields.get("supportEfforts")),
            )
        )
    return models or None


def probe_catalog(binary: str, timeout_seconds: int = PROBE_TIMEOUT_SECONDS) -> object | None:
    """The free provider-list probe's parsed payload, or None."""
    run = runtime.run_sync_capture(
        [binary, *contract.PROVIDER_LIST_ARGS], timeout_seconds=timeout_seconds
    )
    if run.binary_missing or run.timed_out or run.exit_code != 0:
        return None
    if len(run.stdout.encode("utf-8", "replace")) > contract.MODELS_CACHE_MAX_BYTES:
        return None
    try:
        return json.loads(run.stdout)
    except (json.JSONDecodeError, ValueError):
        return None


class KimiModels:
    """The plugin's ModelCatalogReader: live probe, cached for HELP_CACHE_TTL_SECONDS so a
    worker validates an effort and lists models with one spawn."""

    def __init__(self, config: KimiConfig, binary: KimiBinary) -> None:
        self._config = config
        self._binary = binary
        self._cache: tuple[float, ModelListing] | None = None

    def read(self, force: bool = False) -> ModelListing:
        now = time.monotonic()
        if not force and self._cache is not None:
            stamped, listing = self._cache
            if now - stamped < contract.HELP_CACHE_TTL_SECONDS:
                return listing
        binary = self._binary.resolve()
        parsed = parse_catalog(probe_catalog(binary)) if binary is not None else None
        listing = (
            ModelListing(models=tuple(parsed), source="live")
            if parsed
            else ModelListing(models=(), source="none")
        )
        self._cache = (now, listing)
        return listing


def supported_efforts_for(model: str | None, listing: ModelListing) -> tuple[str, ...] | None:
    """Efforts the named alias declares, or None for "cannot tell" (no model, absent
    catalog, unlisted alias, or an alias declaring nothing). Callers MUST treat None as
    "do not reject": kimi ignores an unrecognized effort, so refusing on a guess blocks a
    valid run while accepting on a guess only risks the effort being ignored."""
    if not model:
        return None
    for entry in listing.models:
        if entry.slug == model:
            return entry.supported_reasoning_efforts
    return None
