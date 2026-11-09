"""The pi model catalog: table parsing, exact lookup, the probe's argv. Never a real binary."""

from __future__ import annotations

from pathlib import Path

import pytest

from amicus.backends.pi import contract, models
from amicus.sdk.core import runtime
from amicus.sdk.core.runtime import CommandRun

CAPTURE = Path(__file__).parent.parent / "docs/pi-help/1.5.0/list-models-shape.txt"
HEADER = "provider  model  context  max-out  thinking  images\n"


def _run(stdout="", exit_code=0, timed_out=False):
    return CommandRun(stdout, "", exit_code, 1, timed_out)


class _Binary:
    def __init__(self, path="/fake/pi"):
        self.path = path

    def resolve(self):
        return self.path


def _catalog(monkeypatch, runs, binary=None):
    calls: list[list[str]] = []
    queue = list(runs)

    def fake(cmd, timeout_seconds, **kwargs):
        assert kwargs.get("cwd") == "/probe-cwd"  # never the server's own cwd
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
