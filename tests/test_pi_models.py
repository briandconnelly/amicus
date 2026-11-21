"""The pi model catalog: table parsing, exact lookup, the probe's argv. Never a real binary."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from amicus.backends import pi as pi_pkg
from amicus.backends.pi import contract, models
from amicus.plugin import ModelEntry, ModelListing, ModelPricing, PricingTier
from amicus.sdk.core import runtime
from amicus.sdk.core.runtime import CommandRun

CAPTURE = Path(__file__).parent.parent / "docs/pi-help/1.5.0/list-models-shape.txt"
CAPTURE_152 = Path(__file__).parent.parent / "docs/pi-help/1.5.2/list-models-shape.txt"
HEADER = "provider  model  context  max-out  thinking  images\n"


def _run(stdout="", exit_code=0, timed_out=False, **losses):
    return CommandRun(stdout, "", exit_code, 1, timed_out, **losses)


def _reply(models, success=True):
    reply = {"type": "response", "command": "get_available_models", "success": success}
    return json.dumps({**reply, "data": {"models": models}}) + "\n"


def _model(provider="p", model_id="m", **fields):
    row = {"provider": provider, "id": model_id, "contextWindow": 1024, "maxTokens": 512}
    return {**row, "cost": COST, **fields}


COST = {"input": 0.5, "output": 16, "cacheRead": 0.1, "cacheWrite": 0}
PRICE = ModelPricing(0.5, 16.0, 0.1, 0.0)


class _Binary:
    def __init__(self, path="/fake/pi"):
        self.path = path

    def resolve(self):
        return self.path


class _Calls(list):
    """The table probes' argv, with the RPC probes' (argv, kwargs) beside them on `.rpc`."""

    def __init__(self):
        super().__init__()
        self.rpc: list[tuple[list[str], dict]] = []


def _catalog(monkeypatch, runs, binary=None, rpc=None):
    """A PiModels whose table probes return `runs` in turn (the last one repeats) and whose
    RPC probes return `rpc` the same way: by default a failed run, so a test that is not
    about prices sees the table's rows unchanged."""
    calls = _Calls()
    queue = list(runs)
    rpc_queue = list(rpc) if rpc is not None else [_run(exit_code=1)]

    def fake(cmd, timeout_seconds, **kwargs):
        assert kwargs.get("cwd") == "/probe-cwd"  # never the server's own cwd
        if "--mode" in cmd:
            calls.rpc.append((cmd, kwargs))
            return rpc_queue.pop(0) if len(rpc_queue) > 1 else rpc_queue[0]
        assert "stdin_text" not in kwargs and "max_output_bytes" not in kwargs
        calls.append(cmd)
        return queue.pop(0) if len(queue) > 1 else queue[0]

    monkeypatch.setattr(runtime, "run_sync_capture", fake)
    monkeypatch.setattr(models, "probe_cwd", lambda config: "/probe-cwd")
    return models.PiModels(object(), binary or _Binary()), calls  # type: ignore[arg-type]


def test_parse_captured_table():
    listing = models.parse_table(CAPTURE.read_text())
    assert listing is not None and listing.source == "live"
    assert "openrouter/moonshotai/kimi-k3" in [m.slug for m in listing.models]


def test_slash_in_provider_joins_columns():
    listing = models.parse_table(HEADER + "gateway/team  m  128K  16K  no  no\n")
    assert listing is not None and listing.models[0].slug == "gateway/team/m"


def test_no_thinking_model_accepts_only_off():
    listing = models.parse_table(HEADER + "p  a  1K  1K  no  no\np  b  1K  1K  yes  no\n")
    assert listing is not None
    a, b = listing.models
    assert a.supported_reasoning_efforts == ("off",)
    assert b.supported_reasoning_efforts == contract.EFFORTS


@pytest.mark.parametrize(
    ("cell", "tokens"),
    [
        ("200K", 200_000),
        ("131.1K", 131_100),
        ("1M", 1_000_000),
        ("1.0M", 1_000_000),
        ("943.7K", 943_700),
        ("512", 512),
        ("0", 0),
        # Anything pi's formatter cannot have printed is unknown, never a guess.
        ("1.25M", None),
        ("1.5", None),
        ("1G", None),
        ("-1K", None),
        ("n/a", None),
        ("1e6", None),
        ("٣K", None),
        ("9" * 13, None),
    ],
)
def test_token_cells_parse_to_integers_or_none(cell, tokens):
    listing = models.parse_table(HEADER + f"p  m  {cell}  {cell}  no  no\n")
    assert listing is not None
    [entry] = listing.models
    assert entry.context_tokens == tokens
    assert entry.max_output_tokens == tokens


def test_an_unreadable_token_cell_keeps_the_row_and_the_other_cell():
    listing = models.parse_table(HEADER + "p  m  ???  16.4K  yes  no\n")
    assert listing is not None
    [entry] = listing.models
    assert entry.slug == "p/m"
    assert entry.context_tokens is None
    assert entry.max_output_tokens == 16_400
    assert entry.supported_reasoning_efforts == contract.EFFORTS


def test_the_captured_table_carries_token_limits():
    listing = models.parse_table(CAPTURE_152.read_text())
    assert listing is not None
    [k3] = [m for m in listing.models if m.slug == "openrouter/moonshotai/kimi-k3"]
    assert (k3.context_tokens, k3.max_output_tokens) == (1_000_000, 943_700)


def test_openrouter_batch_rows_are_dropped():
    # OpenRouter serves ":batch" ids only on its batch endpoint; pi calls chat/completions,
    # where they 404, so the catalog never offers them. Other providers' ":batch" ids stay.
    table = (
        HEADER
        + "openrouter  z-ai/glm-5.3  1M  1M  yes  no\n"
        + "openrouter  z-ai/glm-5.3:batch  1M  1M  yes  no\n"
        + "other  m:batch  1K  1K  no  no\n"
    )
    listing = models.parse_table(table)
    assert listing is not None
    assert [m.slug for m in listing.models] == ["openrouter/z-ai/glm-5.3", "other/m:batch"]


def test_no_matches_message_is_none():
    assert models.parse_table('No models matching "x"\n') is None
    assert models.parse_table("") is None


def test_lookup_is_exact_not_fuzzy(monkeypatch):
    table = (
        HEADER
        + "or  moonshotai/kimi-k3  1M  1M  yes  yes\n"
        + "or  moonshotai/kimi-k3:batch  1M  1M  yes  yes\n"
    )
    cat, _ = _catalog(monkeypatch, [_run(table)])
    assert cat.lookup("moonshotai/kimi-k3") is None
    found = cat.lookup("or/moonshotai/kimi-k3")
    assert found != "unreadable" and found is not None and found.slug == "or/moonshotai/kimi-k3"


def test_lookup_no_matches_is_none(monkeypatch):
    cat, _ = _catalog(monkeypatch, [_run('No models matching "x"\n')])
    assert cat.lookup("x") is None


@pytest.mark.parametrize(
    "run",
    [_run(exit_code=1), _run(timed_out=True), _run("x" * (models.MODELS_CACHE_MAX_BYTES + 1))],
)
def test_lookup_unreadable_when_probe_fails(monkeypatch, run):
    cat, _ = _catalog(monkeypatch, [run])
    assert cat.lookup("a/b") == "unreadable"


def test_lookup_unreadable_when_binary_unresolved(monkeypatch):
    cat, calls = _catalog(monkeypatch, [_run()], binary=_Binary(None))
    assert cat.lookup("a/b") == "unreadable"
    assert calls == []


def test_probe_argv_carries_suppression_flags(monkeypatch):
    cat, calls = _catalog(monkeypatch, [_run(HEADER + "p  m  1K  1K  yes  no\n")])
    cat.lookup("p/m")
    cat.read(force=True)
    assert calls[0] == ["/fake/pi", *contract.LIST_MODELS_ARGS, "p/m", *contract.SUPPRESSION_FLAGS]
    assert calls[1] == ["/fake/pi", *contract.LIST_MODELS_ARGS, *contract.SUPPRESSION_FLAGS]


def test_read_caches_and_force_refreshes(monkeypatch):
    cat, calls = _catalog(monkeypatch, [_run(HEADER + "p  m  1K  1K  yes  no\n")])
    assert cat.read().models[0].slug == "p/m"
    cat.read()
    assert len(calls) == 1
    cat.read(force=True)
    assert len(calls) == 2


def test_read_failure_is_none_source_and_uncached(monkeypatch):
    cat, calls = _catalog(monkeypatch, [_run(exit_code=1)])
    assert cat.read().source == "none" and cat.read().models == ()
    assert len(calls) == 2


def test_read_caps_entries(monkeypatch):
    rows = "".join(f"p  m{i}  1K  1K  no  no\n" for i in range(models.MAX_ENTRIES + 5))
    cat, _ = _catalog(monkeypatch, [_run(HEADER + rows)])
    listing = cat.read()
    assert len(listing.models) == models.MAX_ENTRIES and listing.truncated is True


# --- the RPC reply: prices and exact limits -------------------------------------------------


def test_rpc_reply_gives_exact_limits_and_the_price():
    details = models.parse_rpc_models(_reply([_model()]))
    assert details == {"p/m": models.ModelDetail(1024, 512, PRICE)}


def test_rpc_reply_reads_only_the_fields_it_names():
    row = _model(baseUrl="https://example.invalid", apiKey="k", compat={"x": 1}, name="M")
    assert models.parse_rpc_models(_reply([row])) == {"p/m": models.ModelDetail(1024, 512, PRICE)}


def test_an_empty_catalog_is_a_reply_not_a_failure():
    assert models.parse_rpc_models(_reply([])) == {}


@pytest.mark.parametrize(
    "stdout",
    [
        "",  # pi exits 0 in silence when stdin held no request
        "not json\n",
        '{"type":"response","command":"parse","success":false}\n',
        _reply([_model()], success=False),
        _reply([_model()]) + _reply([_model()]),  # two replies: which one is ambiguous
        '{"type":"response","command":"get_available_models","success":true}\n',
        '{"type":"response","command":"get_available_models","success":true,"data":[]}\n',
        json.dumps(
            {
                "type": "response",
                "command": "get_available_models",
                "success": True,
                "data": {"models": {}},
            }
        ),
        "[" * 100_000,  # nesting deep enough to exhaust the JSON reader
    ],
)
def test_anything_but_the_one_successful_reply_is_none(stdout):
    assert models.parse_rpc_models(stdout) is None


def test_lines_that_are_not_the_reply_are_ignored():
    stdout = '{"type":"event"}\nnoise\n' + _reply([_model()]) + '{"type":"extension_ui"}\n'
    assert models.parse_rpc_models(stdout) == {"p/m": models.ModelDetail(1024, 512, PRICE)}


@pytest.mark.parametrize("separator", ["\u2028", "\u2029", "\x85"])
def test_a_line_separator_inside_a_string_does_not_cut_the_reply(separator):
    # pi frames with LF alone and JSON leaves these three unescaped in a string (the C0
    # separators splitlines also breaks at are always escaped), so one model's name must not
    # cost every row its price. The control: splitlines does cut this reply.
    rows = [_model(name=f"before{separator}after"), _model("p", "other")]
    reply = {"type": "response", "command": "get_available_models", "success": True}
    stdout = json.dumps({**reply, "data": {"models": rows}}, ensure_ascii=False) + "\n"
    assert separator in stdout and len(stdout.splitlines()) > 1
    detail = models.ModelDetail(1024, 512, PRICE)
    assert models.parse_rpc_models(stdout) == {"p/m": detail, "p/other": detail}


def test_a_slash_in_the_provider_joins_as_the_table_does():
    details = models.parse_rpc_models(_reply([_model("gateway/team", "v/m")]))
    assert details is not None and list(details) == ["gateway/team/v/m"]


def test_a_slug_two_rows_share_describes_neither():
    rows = [_model(), _model(contextWindow=9), _model(), _model("p", "other")]
    details = models.parse_rpc_models(_reply(rows))
    assert details is not None and list(details) == ["p/other"]


@pytest.mark.parametrize(
    "row",
    [None, "x", [], {"id": "m"}, {"provider": "p"}, {"provider": "", "id": "m"}, {"provider": 1}],
)
def test_a_row_without_a_provider_and_an_id_is_skipped(row):
    details = models.parse_rpc_models(_reply([row, _model()]))
    assert details is not None and list(details) == ["p/m"]


@pytest.mark.parametrize("bad", [None, "1024", 1.5, -1, True, [1]])
def test_a_limit_that_is_not_a_count_is_unknown_and_keeps_the_price(bad):
    details = models.parse_rpc_models(_reply([_model(contextWindow=bad)]))
    assert details == {"p/m": models.ModelDetail(None, 512, PRICE)}


def test_all_zero_rates_with_no_tier_are_unknown_not_free():
    zero = {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0}
    assert models.parse_pricing(zero) is None
    assert models.parse_pricing({**zero, "tiers": []}) is None
    # One non-zero rate, or one tier, is a statement about price.
    assert models.parse_pricing({**zero, "cacheRead": 0.25}) == ModelPricing(0, 0, 0.25, 0)
    tier = {"inputTokensAbove": 200_000, **COST}
    assert models.parse_pricing({**zero, "tiers": [tier]}) == ModelPricing(
        0, 0, 0, 0, tiers=(PricingTier(200_000, 0.5, 16.0, 0.1, 0.0),)
    )


@pytest.mark.parametrize(
    "cost",
    [
        None,
        "free",
        [],
        {},
        {**COST, "input": -1},
        {**COST, "output": "16"},
        {**COST, "cacheRead": True},
        {**COST, "cacheWrite": None},
        {**COST, "input": 10**400},  # an integer no float can hold
        {k: v for k, v in COST.items() if k != "output"},
        {**COST, "tiers": {}},
        {**COST, "tiers": ["x"]},
        {**COST, "tiers": [{"inputTokensAbove": 1.5, **COST}]},
        {**COST, "tiers": [{"inputTokensAbove": 1, **COST, "output": -2}]},
        {**COST, "tiers": [{**COST}]},
        {**COST, "tiers": [{"inputTokensAbove": 1, **COST}, {"inputTokensAbove": 1, **COST}]},
        {
            **COST,
            "tiers": [{"inputTokensAbove": i, **COST} for i in range(models.MAX_PRICING_TIERS + 1)],
        },
    ],
)
def test_a_malformed_price_is_none_and_keeps_the_row(cost):
    assert models.parse_pricing(cost) is None
    details = models.parse_rpc_models(_reply([_model(cost=cost)]))
    assert details == {"p/m": models.ModelDetail(1024, 512, None)}


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
def test_a_non_finite_rate_is_none(token):
    stdout = _reply([_model()]).replace('"input": 0.5', f'"input": {token}')
    assert token in stdout
    assert models.parse_rpc_models(stdout) == {"p/m": models.ModelDetail(1024, 512, None)}


def test_tiers_are_ordered_by_threshold():
    tiers = [{"inputTokensAbove": n, **COST, "input": n / 1000} for n in (272_000, 128_000)]
    pricing = models.parse_pricing({**COST, "tiers": tiers})
    assert pricing is not None
    assert [(t.input_tokens_above, t.input) for t in pricing.tiers] == [
        (128_000, 128.0),
        (272_000, 272.0),
    ]


def test_enrich_keeps_the_tables_rows_order_and_truncation():
    table = ModelListing(
        models=(
            ModelEntry(slug="z/last", context_tokens=1_000, max_output_tokens=2_000),
            ModelEntry(slug="a/first", context_tokens=3_000, max_output_tokens=None),
            ModelEntry(slug="m/table-only", context_tokens=4_000),
        ),
        source="live",
        truncated=True,
    )
    details = {
        "a/first": models.ModelDetail(3_072, 4_096, PRICE),
        "z/last": models.ModelDetail(None, None, None),
        "not/listed": models.ModelDetail(1, 1, PRICE),
    }
    enriched = models.enrich(table, details)
    assert enriched.truncated is True and enriched.source == "live"
    assert enriched.models == (
        # A limit the reply does not state keeps the table's rounded figure.
        ModelEntry(slug="z/last", context_tokens=1_000, max_output_tokens=2_000),
        ModelEntry(slug="a/first", context_tokens=3_072, max_output_tokens=4_096, pricing=PRICE),
        ModelEntry(slug="m/table-only", context_tokens=4_000),
    )


TABLE = HEADER + "p  m  1K  1K  yes  no\np  other  2K  2K  no  no\n"


def test_read_asks_rpc_once_with_the_fixed_request_and_a_cap(monkeypatch):
    cat, calls = _catalog(monkeypatch, [_run(TABLE)], rpc=[_run(_reply([_model()]))])
    listing = cat.read()
    assert [(m.slug, m.context_tokens, m.max_output_tokens, m.pricing) for m in listing.models] == [
        ("p/m", 1024, 512, PRICE),
        ("p/other", 2_000, 2_000, None),
    ]
    [(argv, kwargs)] = calls.rpc
    assert argv == ["/fake/pi", "--mode", "rpc", "--no-session", *contract.SUPPRESSION_FLAGS]
    assert kwargs == {
        "cwd": "/probe-cwd",
        "stdin_text": '{"type":"get_available_models"}\n',
        "max_output_bytes": models.RPC_MAX_BYTES,
    }
    # No prompt input can reach the request: it is a literal the contract owns.
    assert kwargs["stdin_text"] is contract.RPC_MODELS_REQUEST


@pytest.mark.parametrize(
    "rpc",
    [
        _run(exit_code=1),
        _run(timed_out=True),
        _run(""),
        _run(_reply([_model()]), stdout_truncated=True),
        _run(_reply([_model()]), output_truncated=True),
        _run(_reply([_model()]), capture_failed=True),
        _run(_reply([_model()]), stdout_capture_failed=True),
        CommandRun("", runtime.BINARY_NOT_FOUND, 127, 1, False),
    ],
)
def test_a_failed_rpc_probe_leaves_the_tables_rows_without_prices(monkeypatch, rpc):
    cat, _ = _catalog(monkeypatch, [_run(TABLE)], rpc=[rpc])
    listing = cat.read()
    assert listing.source == "live"
    assert [(m.slug, m.context_tokens, m.pricing) for m in listing.models] == [
        ("p/m", 1_000, None),
        ("p/other", 2_000, None),
    ]


def test_prices_that_could_not_be_read_are_asked_for_again_sooner(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(models.time, "monotonic", lambda: clock[0])
    cat, calls = _catalog(
        monkeypatch, [_run(TABLE)], rpc=[_run(exit_code=1), _run(_reply([_model()]))]
    )
    assert cat.read().models[0].pricing is None
    clock[0] += models.PRICING_RETRY_SECONDS - 1
    assert cat.read().models[0].pricing is None  # still cached
    assert (len(calls), len(calls.rpc)) == (1, 1)
    clock[0] += 2
    assert cat.read().models[0].pricing == PRICE
    # A listing with its prices is kept for the full TTL.
    clock[0] += models.HELP_CACHE_TTL_SECONDS - 1
    cat.read()
    assert (len(calls), len(calls.rpc)) == (2, 2)
    clock[0] += 2
    cat.read()
    assert (len(calls), len(calls.rpc)) == (3, 3)


def test_no_rpc_probe_without_a_table_or_without_rows(monkeypatch):
    cat, calls = _catalog(monkeypatch, [_run(exit_code=1)])
    assert cat.read().source == "none"
    empty, empty_calls = _catalog(monkeypatch, [_run(HEADER)])
    assert empty.read().models == ()
    unresolved, none_calls = _catalog(monkeypatch, [_run(TABLE)], binary=_Binary(None))
    assert unresolved.read().source == "none"
    assert calls.rpc == [] and empty_calls.rpc == [] and none_calls.rpc == []
    assert none_calls == []


def test_lookup_never_asks_rpc(monkeypatch):
    cat, calls = _catalog(monkeypatch, [_run(TABLE)], rpc=[_run(_reply([_model()]))])
    found = cat.lookup("p/m")
    assert found == ModelEntry(
        slug="p/m",
        supported_reasoning_efforts=contract.EFFORTS,
        context_tokens=1_000,
        max_output_tokens=1_000,
    )
    assert calls.rpc == []


# --- end to end against the fake binary: a real spawn, stdin EOF and the bounded capture ----

SLUG = "openrouter/moonshotai/kimi-k3"


def _fake_plugin(fake_pi, tmp_path):
    environ = {"AMICUS_PI_BIN": str(fake_pi), "AMICUS_STATE_DIR": str(tmp_path / "state")}
    return pi_pkg.plugin(environ)


def test_the_fake_binary_listing_carries_its_price(fake_pi, tmp_path):
    [entry] = _fake_plugin(fake_pi, tmp_path).models.read(force=True).models
    assert entry == ModelEntry(
        slug=SLUG,
        supported_reasoning_efforts=contract.EFFORTS,
        context_tokens=1_048_576,
        max_output_tokens=943_718,
        pricing=ModelPricing(0.5, 16.0, 0.1, 0.0),
    )


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("FAKE_PI_RPC_REPLY", ""),  # no reply at all
        ("FAKE_PI_RPC_REPLY", '{"type":"response","command":"parse","success":false}'),
        ("FAKE_PI_RPC_EXIT", "1"),
        ("FAKE_PI_RPC_MODELS", "[]"),
    ],
)
def test_the_fake_binary_listing_survives_an_unusable_rpc_reply(
    fake_pi, tmp_path, monkeypatch, name, value
):
    monkeypatch.setenv(name, value)
    [entry] = _fake_plugin(fake_pi, tmp_path).models.read(force=True).models
    assert (entry.slug, entry.context_tokens, entry.max_output_tokens, entry.pricing) == (
        SLUG,
        1_000_000,
        943_700,
        None,
    )


def test_a_reply_larger_than_the_cap_is_discarded_whole(fake_pi, tmp_path, monkeypatch):
    monkeypatch.setattr(models, "RPC_MAX_BYTES", 256)
    [entry] = _fake_plugin(fake_pi, tmp_path).models.read(force=True).models
    assert (entry.context_tokens, entry.pricing) == (1_000_000, None)
