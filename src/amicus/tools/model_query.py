"""The `amicus_models` query as a pure function over catalog rows (#560, ADR 0053)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from amicus.schemas.results import ModelSelection

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Sequence

    from amicus.plugin import ModelEntry
    from amicus.schemas.params import ModelQuery


def _rate(entry: ModelEntry, side: str) -> float | None:
    """The highest `side` ("input" or "output") rate across the base rate and every tier, or
    None when the row's price is unknown."""
    pricing = entry.pricing
    if pricing is None:
        return None
    return max([getattr(pricing, side), *(getattr(tier, side) for tier in pricing.tiers)])


def select(
    rows: Sequence[ModelEntry], query: ModelQuery
) -> tuple[list[ModelEntry], ModelSelection]:
    """The rows `query` keeps, sorted and limited, and the counts of what it did not keep.
    A row is tested by prefix, then context, then input price, then output price, and counted
    once, at the first test that excludes it; an unknown value never passes a bound."""
    by_filter = unknown_context = unknown_pricing = 0
    matched: list[ModelEntry] = []
    for entry in rows:
        if query.slug_prefix is not None and not entry.slug.startswith(query.slug_prefix):
            by_filter += 1
            continue
        if query.min_context_tokens is not None:
            if entry.context_tokens is None:
                unknown_context += 1
                continue
            if entry.context_tokens < query.min_context_tokens:
                by_filter += 1
                continue
        excluded = False
        for side, bound in (("input", query.max_input_price), ("output", query.max_output_price)):
            if bound is None:
                continue
            rate = _rate(entry, side)
            if rate is None:
                unknown_pricing += 1
            elif rate > bound:
                by_filter += 1
            else:
                continue
            excluded = True
            break
        if not excluded:
            matched.append(entry)
    if query.sort_by == "slug":
        matched.sort(key=lambda e: e.slug)
    else:
        side = "input" if query.sort_by == "input_price" else "output"

        def key(entry: ModelEntry) -> tuple[bool, float, str]:
            rate = _rate(entry, side)
            return (rate is None, rate if rate is not None else 0.0, entry.slug)

        matched.sort(key=key)
    kept = matched[: query.limit]
    priced = (
        query.max_input_price is not None
        or query.max_output_price is not None
        or query.sort_by != "slug"
    )
    return kept, ModelSelection(
        examined=len(rows),
        excluded_by_filter=by_filter,
        excluded_unknown_context=unknown_context,
        excluded_unknown_pricing=unknown_pricing,
        omitted_by_limit=len(matched) - len(kept),
        price_basis="max_across_tiers" if priced else None,
    )
