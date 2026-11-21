"""The `amicus_models` query as a pure function (#560, ADR 0053): every row is built from this
file's own literals."""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from amicus.plugin import ModelEntry, ModelPricing, PricingTier
from amicus.schemas.params import ModelQuery
from amicus.tools.model_query import select


def _price(inp, out, *tiers):
    return ModelPricing(
        inp, out, 0.0, 0.0, tiers=tuple(PricingTier(t[0], t[1], t[2], 0.0, 0.0) for t in tiers)
    )


def _row(slug, context=100_000, pricing=None):
    return ModelEntry(slug=slug, context_tokens=context, pricing=pricing)


def _slugs(rows):
    return [r.slug for r in rows]


# One mixed catalog. Bounds used below: prefix "or/", min context 50_000, max input 2.0,
# max output 8.0, sort by input price, limit 3.
MIXED = [
    _row("xx/prefix-miss", pricing=_price(1.0, 1.0)),
    # Null context and a failing price: counted as unknown context, the first test to exclude.
    _row("or/null-context", context=None, pricing=_price(99.0, 99.0)),
    _row("or/null-pricing", pricing=None),
    _row("or/output-fails", pricing=_price(1.0, 9.0)),
    _row("or/tier-fails", pricing=_price(1.0, 4.0, (200_000, 3.0, 4.0))),
    _row("or/tier-cheaper", pricing=_price(1.5, 4.0, (200_000, 0.5, 2.0))),
    _row("or/equal-b", pricing=_price(0.5, 1.0)),
    _row("or/equal-a", pricing=_price(0.5, 1.0)),
    _row("or/at-bounds", context=50_000, pricing=_price(2.0, 8.0)),
    _row("or/small-context", context=49_999, pricing=_price(0.1, 0.1)),
    _row("or/cheapest", pricing=_price(0.25, 0.25)),
]
MIXED_QUERY = ModelQuery(
    slug_prefix="or/",
    min_context_tokens=50_000,
    max_input_price=2.0,
    max_output_price=8.0,
    sort_by="input_price",
    limit=3,
)


def test_one_mixed_catalog_gives_exact_rows_and_exact_counts():
    rows, sel = select(MIXED, MIXED_QUERY)
    # Matches by input rate then slug: cheapest 0.25, equal-a 0.5, equal-b 0.5, tier-cheaper
    # 1.5 (its max across tiers), at-bounds 2.0; the limit keeps three.
    assert _slugs(rows) == ["or/cheapest", "or/equal-a", "or/equal-b"]
    assert sel.examined == 11
    assert sel.excluded_by_filter == 4  # prefix-miss, small-context, output-fails, tier-fails
    assert sel.excluded_unknown_context == 1
    assert sel.excluded_unknown_pricing == 1
    assert sel.omitted_by_limit == 2
    assert sel.price_basis == "max_across_tiers"


def test_the_mixed_catalog_without_a_limit_keeps_rows_at_the_bounds():
    rows, sel = select(MIXED, MIXED_QUERY.model_copy(update={"limit": 1024}))
    assert _slugs(rows) == [
        "or/cheapest",
        "or/equal-a",
        "or/equal-b",
        "or/tier-cheaper",
        "or/at-bounds",
    ]
    assert sel.omitted_by_limit == 0


def test_a_known_zero_price_passes_a_bound():
    rows, sel = select([_row("p/free", pricing=_price(0.0, 0.0))], ModelQuery(max_input_price=0))
    assert _slugs(rows) == ["p/free"] and sel.excluded_unknown_pricing == 0


def test_a_price_sort_without_a_bound_puts_unknown_prices_last():
    catalog = [
        _row("p/a"),
        _row("p/b", pricing=_price(5.0, 1.0)),
        _row("p/c", pricing=_price(1.0, 9.0)),
    ]
    rows, sel = select(catalog, ModelQuery(sort_by="output_price"))
    assert _slugs(rows) == ["p/b", "p/c", "p/a"]
    assert sel.excluded_unknown_pricing == 0 and sel.price_basis == "max_across_tiers"


def test_a_prefix_is_case_sensitive_and_matches_the_whole_slug_start():
    catalog = [
        _row("openrouter/google/gemini/x"),
        _row("openrouter/Google/gemini"),
        _row("other/openrouter/google/y"),
    ]
    rows, sel = select(catalog, ModelQuery(slug_prefix="openrouter/google/"))
    assert _slugs(rows) == ["openrouter/google/gemini/x"]
    assert sel.excluded_by_filter == 2


@pytest.mark.parametrize(
    "query",
    [
        ModelQuery(),
        MIXED_QUERY,
        ModelQuery(max_output_price=1.0, limit=1),
        ModelQuery(min_context_tokens=60_000, sort_by="output_price"),
        ModelQuery(slug_prefix="or/e", limit=1),
        ModelQuery(max_input_price=0.0),
    ],
)
def test_the_counts_always_sum(query):
    rows, sel = select(MIXED, query)
    assert sel.examined == len(MIXED)
    assert sel.examined == (
        len(rows)
        + sel.excluded_by_filter
        + sel.excluded_unknown_context
        + sel.excluded_unknown_pricing
        + sel.omitted_by_limit
    )


def test_an_empty_query_returns_the_first_fifty_by_slug():
    catalog = [_row(f"p/m{i:03d}") for i in reversed(range(60))]
    rows, sel = select(catalog, ModelQuery())
    assert _slugs(rows) == [f"p/m{i:03d}" for i in range(50)]
    assert sel.omitted_by_limit == 10 and sel.price_basis is None


def test_price_basis_is_null_without_a_price_bound_or_price_sort():
    _, sel = select(MIXED, ModelQuery(slug_prefix="or/", min_context_tokens=1))
    assert sel.price_basis is None
    _, sel = select(MIXED, ModelQuery(max_output_price=1))
    assert sel.price_basis == "max_across_tiers"


# --- validation ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        {"max_input_price": math.nan},
        {"max_input_price": math.inf},
        {"max_output_price": -0.01},
        {"max_input_price": True},
        {"max_output_price": "1"},
        {"limit": 0},
        {"limit": 1025},
        {"limit": True},
        {"slug_prefix": ""},
        {"slug_prefix": "a\x00b"},
        {"min_context_tokens": 0},
        {"sort_by": "quality"},
        {"sort": "slug"},
    ],
)
def test_a_malformed_query_is_rejected(raw):
    with pytest.raises(ValidationError):
        ModelQuery.model_validate(raw)


def test_an_integer_price_is_accepted():
    assert ModelQuery.model_validate({"max_input_price": 1}).max_input_price == 1.0
