"""Read pi's model catalog from `pi --list-models`, a whitespace-aligned table with the header
`provider model context max-out thinking images`. The probe is free and offline.

`lookup` passes the full model string as pi's search term and then requires an exact row: the
search is fuzzy, so a hit is not a match. A provider may contain "/", but it is still one
column, so rows are split on whitespace and the slug is the first two columns joined.

The `context` and `max-out` cells are display strings, not counts: pi 1.5.2's
`formatTokenCount` prints a count below 1000 as is, and otherwise divides by 1000 (`K`) or
1 000 000 (`M`) and keeps one decimal unless the quotient is whole. `tokens` reverses that, so
a `K` value is within 50 tokens of pi's own figure and an `M` value within 50 000, and a
cell of any other shape is None rather than a guess.

The table has no prices. `read` therefore asks pi a second time, over its RPC mode
(`contract.RPC_MODELS_ARGS`), whose `get_available_models` reply carries each model's full
definition: `cost` in USD per million tokens and the exact `contextWindow` and `maxTokens`.
That reply only ENRICHES the table's rows, matched by slug. The table stays the authority
on which rows exist and in what order, because the two sources order rows differently (the
table sorts, RPC does not), and the cut must not move.

`read` scans up to MAX_SCAN_ENTRIES rows so that an `amicus_models` query can examine rows
past the plain listing's cut, and marks the listing's `display_limit` as MAX_ENTRIES: a plain
listing still shows the first MAX_ENTRIES rows (ADR 0053). `truncated` is true only when the
scan bound cut the table. A row the reply does not
describe, or describes twice, keeps the table's values and no price, and so does every row
when the second probe fails. `lookup`, the pre-spend gate, never uses it.

A price is published only where it says something. pi reports a model with no catalog price
as costing 0, exactly as it reports a free one, so a `cost` whose four rates are all 0 and
that has no tiers is None (unknown), never a zero price. One malformed number makes that
row's price None and leaves the row.

The reply also says which reasoning levels a model maps, published as
`advertised_reasoning_efforts` and never checked pre-spend (ADR 0052). `advertised_efforts`
mirrors `getSupportedThinkingLevels` in pi 1.6.0's `pi-ai/dist/models.js`. The table stays the
authority on whether a model thinks: a `thinking: no` row advertises only `off`, and a
`thinking: yes` row takes the reply's levels only when its RPC row's `reasoning` is literally
true, and is None (unknown) otherwise."""

from __future__ import annotations

import dataclasses
import json
import math
import re
import time
from typing import TYPE_CHECKING, Literal, NamedTuple

from amicus.backends.pi import contract
from amicus.backends.pi.config import probe_cwd
from amicus.plugin import ModelEntry, ModelListing, ModelPricing, PricingTier
from amicus.sdk.core import runtime

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Mapping

    from amicus.backends.pi.binary import PiBinary
    from amicus.backends.pi.config import PiConfig

PROBE_TIMEOUT_SECONDS = 10
HELP_CACHE_TTL_SECONDS = 300
MODELS_CACHE_MAX_BYTES = 1_048_576
MAX_ENTRIES = 1024
# How many rows `read` examines for a query; the plain listing shows MAX_ENTRIES of them. At
# pi 1.6.0's sizes this many rows fit both byte caps below unchanged.
MAX_SCAN_ENTRIES = 4096
# The RPC reply is one JSON line of about 0.6 KB a model (753 KB for 1 332 models on pi 1.6.0
# with every provider credentialed), captured under this cap while pi runs. A reply cut at
# it is discarded whole.
RPC_MAX_BYTES = 4 * 1_048_576
# pi 1.6.0's catalog has at most two tiers on a row; a row with more than this has no price.
MAX_PRICING_TIERS = 8
# How long a listing whose prices could not be read is cached before the next `read` asks
# again, so one failed probe does not hide prices for the whole HELP_CACHE_TTL_SECONDS.
PRICING_RETRY_SECONDS = 30
_HEADER = ["provider", "model", "context", "max-out", "thinking", "images"]
# The three shapes pi's formatter prints: `512`, `200K` or `1M`, `131.1K` or `1.0M`.
_TOKEN_CELL = re.compile(r"(?P<whole>[0-9]{1,12})(?:(?:\.(?P<tenth>[0-9]))?(?P<unit>[KM]))?")
_UNIT = {"K": 1_000, "M": 1_000_000}


def tokens(cell: str) -> int | None:
    """The token count a `context` or `max-out` cell displays, or None when the cell is not
    one of the shapes pi's formatter prints. Approximate for a `K` or `M` cell: see the
    module docstring."""
    match = _TOKEN_CELL.fullmatch(cell)
    if match is None:
        return None
    unit = _UNIT.get(match["unit"] or "", 1)
    return int(match["whole"]) * unit + int(match["tenth"] or 0) * unit // 10


def is_batch_only(slug: str) -> bool:
    """True for an OpenRouter ":batch" id: OpenRouter serves those only on its batch
    endpoint, and pi calls chat/completions, where they fail with a 404."""
    return slug.startswith("openrouter/") and slug.endswith(":batch")


def parse_table(stdout: str, *, max_entries: int = MAX_ENTRIES) -> ModelListing | None:
    """The listing from a `--list-models` table, or None without the header (including pi's
    `No models matching ...` message). At most `max_entries` rows are read, and `truncated`
    is true only when an eligible row lay past them."""
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
        slug = f"{cols[0]}/{cols[1]}"
        if is_batch_only(slug):
            continue
        if len(entries) >= max_entries:
            truncated = True
            break
        thinks = cols[4] == "yes"
        entries.append(
            ModelEntry(
                slug=slug,
                supported_reasoning_efforts=contract.EFFORTS if thinks else ("off",),
                advertised_reasoning_efforts=None if thinks else ("off",),
                context_tokens=tokens(cols[2]),
                max_output_tokens=tokens(cols[3]),
            )
        )
    return ModelListing(models=tuple(entries), source="live", truncated=truncated)


class ModelDetail(NamedTuple):
    """What the RPC reply adds to one table row. None means the reply did not say."""

    context_tokens: int | None
    max_output_tokens: int | None
    pricing: ModelPricing | None
    advertised_reasoning_efforts: tuple[str, ...] | None = None


_ABSENT = object()
# The levels pi supports without a mapping; `xhigh` and `max` need one.
_UNMAPPED_SUPPORTED = frozenset({"off", "minimal", "low", "medium", "high"})


def advertised_efforts(reasoning: object, row: Mapping[str, object]) -> tuple[str, ...] | None:
    """The levels one RPC row says its model maps, in `contract.EFFORTS` order, or None when
    `reasoning` is not literally true or the row's `thinkingLevelMap` is present and not an
    object. An explicit null marks a level unsupported; an omitted one is supported from `off`
    through `high` and not for `xhigh` or `max`; any other value marks it supported. No map at
    all reads as an empty one."""
    if reasoning is not True:
        return None
    level_map = row.get("thinkingLevelMap", _ABSENT)
    if level_map is _ABSENT:
        level_map = {}
    if not isinstance(level_map, dict):
        return None
    advertised = []
    for level in contract.EFFORTS:
        mapped = level_map.get(level, _ABSENT)
        if mapped is None:
            continue
        if mapped is _ABSENT and level not in _UNMAPPED_SUPPORTED:
            continue
        advertised.append(level)
    return tuple(advertised)


def _rate(value: object) -> float | None:
    """A USD-per-million-tokens rate: a finite, non-negative JSON number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        rate = float(value)
    except OverflowError:  # an integer too large for a float
        return None
    return rate if math.isfinite(rate) and rate >= 0 else None


def _count(value: object) -> int | None:
    """A token count: a non-negative JSON integer."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value >= 0 else None


def _rates(blob: dict) -> tuple[float, float, float, float] | None:
    inp, out = _rate(blob.get("input")), _rate(blob.get("output"))
    read, write = _rate(blob.get("cacheRead")), _rate(blob.get("cacheWrite"))
    if inp is None or out is None or read is None or write is None:
        return None
    return inp, out, read, write


def _tiers(raw: object) -> tuple[PricingTier, ...] | None:
    """The tiers by rising threshold, () for none, or None when the list is malformed, too
    long, or names one threshold twice."""
    if raw is None:
        return ()
    if not isinstance(raw, list) or len(raw) > MAX_PRICING_TIERS:
        return None
    tiers: list[PricingTier] = []
    for item in raw:
        if not isinstance(item, dict):
            return None
        above, rates = _count(item.get("inputTokensAbove")), _rates(item)
        if above is None or rates is None:
            return None
        tiers.append(PricingTier(above, *rates))
    if len({tier.input_tokens_above for tier in tiers}) != len(tiers):
        return None
    return tuple(sorted(tiers, key=lambda tier: tier.input_tokens_above))


def parse_pricing(cost: object) -> ModelPricing | None:
    """The price in one model's `cost`, or None when it is absent, malformed in any part, or
    all zeros with no tier (pi's spelling of both free and unpriced)."""
    if not isinstance(cost, dict):
        return None
    rates, tiers = _rates(cost), _tiers(cost.get("tiers"))
    if rates is None or tiers is None:
        return None
    if not tiers and not any(rates):
        return None
    return ModelPricing(*rates, tiers=tiers)


def _reply_models(stdout: str) -> list | None:
    """The `models` array of the one successful reply to the request, else None: no reply
    (pi exits 0 in silence when stdin held no request), a failed one, or more than one."""
    replies = []
    # pi frames its replies with LF alone. str.splitlines also breaks at U+2028, U+2029 and
    # other separators, which JSON carries unescaped inside a string (a model's name, say),
    # and one such character would cut the reply in two and cost every row its price.
    for line in stdout.split("\n"):
        try:
            blob = json.loads(line)
        except (ValueError, RecursionError):
            continue
        if (
            isinstance(blob, dict)
            and blob.get("type") == "response"
            and blob.get("command") == contract.RPC_MODELS_COMMAND
        ):
            replies.append(blob)
    if len(replies) != 1 or replies[0].get("success") is not True:
        return None
    data = replies[0].get("data")
    rows = data.get("models") if isinstance(data, dict) else None
    return rows if isinstance(rows, list) else None


def parse_rpc_models(stdout: str) -> dict[str, ModelDetail] | None:
    """Each model's detail by slug, from the reply to `contract.RPC_MODELS_REQUEST`, or None
    when stdout is not that reply. An empty array is a reply (pi has no credentialed
    provider), so it is {} and not None. A row without a provider and an id is skipped, and
    a slug two rows share describes neither. Only the fields named here, `reasoning` and
    `thinkingLevelMap` among them, are read: the reply also carries each model's endpoint URL,
    which goes no further."""
    rows = _reply_models(stdout)
    if rows is None:
        return None
    details: dict[str, ModelDetail] = {}
    repeated: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        provider, model_id = row.get("provider"), row.get("id")
        if not (isinstance(provider, str) and provider and isinstance(model_id, str) and model_id):
            continue
        slug = f"{provider}/{model_id}"
        if slug in details or slug in repeated:
            repeated.add(slug)
            details.pop(slug, None)
            continue
        details[slug] = ModelDetail(
            _count(row.get("contextWindow")),
            _count(row.get("maxTokens")),
            parse_pricing(row.get("cost")),
            advertised_efforts(row.get("reasoning"), row),
        )
    return details


def enrich(listing: ModelListing, details: dict[str, ModelDetail]) -> ModelListing:
    """`listing` with each row the reply describes given its exact limits and its price,
    and, on a row the table says thinks, the levels the reply advertises. Rows, order,
    truncation and `supported_reasoning_efforts` are the table's."""

    def one(entry: ModelEntry) -> ModelEntry:
        detail = details.get(entry.slug)
        if detail is None:
            return entry
        return dataclasses.replace(
            entry,
            context_tokens=(
                detail.context_tokens if detail.context_tokens is not None else entry.context_tokens
            ),
            max_output_tokens=(
                detail.max_output_tokens
                if detail.max_output_tokens is not None
                else entry.max_output_tokens
            ),
            pricing=detail.pricing,
            advertised_reasoning_efforts=(
                detail.advertised_reasoning_efforts
                if entry.supported_reasoning_efforts == contract.EFFORTS
                else entry.advertised_reasoning_efforts
            ),
        )

    return dataclasses.replace(listing, models=tuple(one(entry) for entry in listing.models))


def _probe_details(binary: str, cwd: str) -> dict[str, ModelDetail] | None:
    run = runtime.run_sync_capture(
        [binary, *contract.RPC_MODELS_ARGS, *contract.SUPPRESSION_FLAGS],
        timeout_seconds=PROBE_TIMEOUT_SECONDS,
        cwd=cwd,
        stdin_text=contract.RPC_MODELS_REQUEST,
        max_output_bytes=RPC_MAX_BYTES,
    )
    if run.binary_missing or run.timed_out or run.exit_code != 0:
        return None
    if (
        run.output_truncated
        or run.stdout_truncated
        or run.capture_failed
        or run.stdout_capture_failed
    ):
        return None
    return parse_rpc_models(run.stdout)


def _probe(binary: str, *terms: str, cwd: str) -> str | None:
    run = runtime.run_sync_capture(
        [binary, *contract.LIST_MODELS_ARGS, *terms, *contract.SUPPRESSION_FLAGS],
        timeout_seconds=PROBE_TIMEOUT_SECONDS,
        cwd=cwd,
    )
    if run.binary_missing or run.timed_out or run.exit_code != 0:
        return None
    if len(run.stdout.encode("utf-8", "replace")) > MODELS_CACHE_MAX_BYTES:
        return None
    return run.stdout


class PiModels:
    """The plugin's ModelCatalogReader: live probes, cached for HELP_CACHE_TTL_SECONDS, or
    for PRICING_RETRY_SECONDS when the table was read and its prices were not. A `read` runs
    up to two probes, so it can take twice PROBE_TIMEOUT_SECONDS."""

    def __init__(self, config: PiConfig, binary: PiBinary) -> None:
        self._config = config
        self._binary = binary
        self._cache: tuple[float, float, ModelListing] | None = None

    def read(self, force: bool = False) -> ModelListing:
        now = time.monotonic()
        if not force and self._cache is not None:
            stamped, ttl, listing = self._cache
            if now - stamped < ttl:
                return listing
        binary = self._binary.resolve()
        cwd = probe_cwd(self._config)
        if binary is None or cwd is None:
            return ModelListing(models=(), source="none")
        out = _probe(binary, cwd=cwd)
        listing = parse_table(out, max_entries=MAX_SCAN_ENTRIES) if out is not None else None
        if listing is None:
            # A failed probe is transient; do not cache "none" for the whole TTL.
            return ModelListing(models=(), source="none")
        listing = dataclasses.replace(listing, display_limit=MAX_ENTRIES)
        ttl: float = HELP_CACHE_TTL_SECONDS
        if listing.models:
            details = _probe_details(binary, cwd)
            if details is None:
                ttl = PRICING_RETRY_SECONDS
            else:
                listing = enrich(listing, details)
        self._cache = (now, ttl, listing)
        return listing

    def lookup(self, model: str) -> ModelEntry | Literal["unreadable"] | None:
        """The row whose joined slug equals `model`; None when the listing was read and has
        no such row; "unreadable" when the probe could not run or its output was unusable."""
        binary = self._binary.resolve()
        cwd = probe_cwd(self._config)
        out = _probe(binary, model, cwd=cwd) if binary is not None and cwd is not None else None
        if out is None:
            return "unreadable"
        listing = parse_table(out)
        if listing is None:
            return None
        return next((e for e in listing.models if e.slug == model), None)
