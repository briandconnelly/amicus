"""Read pi's model catalog from `pi --list-models`, a whitespace-aligned table with the header
`provider model context max-out thinking images`. The probe is free and offline.

`lookup` passes the full model string as pi's search term and then requires an exact row: the
search is fuzzy, so a hit is not a match. A provider may contain "/", but it is still one
column, so rows are split on whitespace and the slug is the first two columns joined."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Literal

from amicus.backends.pi import contract
from amicus.plugin import ModelEntry, ModelListing
from amicus.sdk.core import runtime

if TYPE_CHECKING:  # pragma: no cover
    from amicus.backends.pi.binary import PiBinary
    from amicus.backends.pi.config import PiConfig

PROBE_TIMEOUT_SECONDS = 10
HELP_CACHE_TTL_SECONDS = 300
MODELS_CACHE_MAX_BYTES = 1_048_576
MAX_ENTRIES = 1024
_HEADER = ["provider", "model", "context", "max-out", "thinking", "images"]


def parse_table(stdout: str) -> ModelListing | None:
    """The listing from a `--list-models` table, or None without the header (including pi's
    `No models matching ...` message). At most MAX_ENTRIES rows are read."""
    lines = stdout.splitlines()
    start = next((i for i, line in enumerate(lines) if line.split() == _HEADER), None)
    if start is None:
        return None
    entries: list[ModelEntry] = []
    truncated = False
    for line in lines[start + 1 :]:
        cols = line.split()
        if len(cols) < len(_HEADER):
            continue
        if len(entries) >= MAX_ENTRIES:
            truncated = True
            break
        efforts = contract.EFFORTS if cols[4] == "yes" else ("off",)
        entries.append(ModelEntry(slug=f"{cols[0]}/{cols[1]}", supported_reasoning_efforts=efforts))
    return ModelListing(models=tuple(entries), source="live", truncated=truncated)


def _probe(binary: str, *terms: str) -> str | None:
    run = runtime.run_sync_capture(
        [binary, *contract.LIST_MODELS_ARGS, *terms, *contract.SUPPRESSION_FLAGS],
        timeout_seconds=PROBE_TIMEOUT_SECONDS,
    )
    if run.binary_missing or run.timed_out or run.exit_code != 0:
        return None
    if len(run.stdout.encode("utf-8", "replace")) > MODELS_CACHE_MAX_BYTES:
        return None
    return run.stdout


class PiModels:
    """The plugin's ModelCatalogReader: live probe, cached for HELP_CACHE_TTL_SECONDS."""

    def __init__(self, config: PiConfig, binary: PiBinary) -> None:
        self._config = config
        self._binary = binary
        self._cache: tuple[float, ModelListing] | None = None

    def read(self, force: bool = False) -> ModelListing:
        now = time.monotonic()
        if not force and self._cache is not None:
            stamped, listing = self._cache
            if now - stamped < HELP_CACHE_TTL_SECONDS:
                return listing
        binary = self._binary.resolve()
        out = _probe(binary) if binary is not None else None
        listing = parse_table(out) if out is not None else None
        if listing is not None:
            self._cache = (now, listing)
            return listing
        # A failed probe is transient; do not cache "none" for the whole TTL.
        return ModelListing(models=(), source="none")

    def lookup(self, model: str) -> ModelEntry | Literal["unreadable"] | None:
        """The row whose joined slug equals `model`; None when the listing was read and has
        no such row; "unreadable" when the probe could not run or its output was unusable."""
        binary = self._binary.resolve()
        out = _probe(binary, model) if binary is not None else None
        if out is None:
            return "unreadable"
        listing = parse_table(out)
        if listing is None:
            return None
        return next((e for e in listing.models if e.slug == model), None)
