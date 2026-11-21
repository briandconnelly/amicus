"""Behavior contract for scripts/check_pi_pricing.py, the zero-spend release check that
amicus still reads prices from pi (ADR 0051).

The script lives under scripts/ (not the package), so coverage doesn't track it. These
tests drive it against the fake pi: a catalog that returns what the script wrote passes,
and each way the real reply could go wrong is reported. It is loaded by path, mirroring
tests/test_check_sentence_per_line.py. The run against a real pi is the release step in
docs/RELEASING.md, never the gate."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "check_pi_pricing.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("check_pi_pricing", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check = _load_script()

TABLE = (
    "provider  model  context  max-out  thinking  images\n"
    f"{check.PROVIDER}  priced  123.5K  7.9K  no  no\n"
    f"{check.PROVIDER}  unpriced  128K  16.4K  no  no\n"
)
ZERO = {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0}


def _rpc_rows():
    """What pi 1.6.0 replies for the script's models.json: the priced model as written, and
    the model with no cost as four zero rates."""
    # A deep copy: the tests below edit these rows, and the script's own constant must not move.
    priced, unpriced = copy.deepcopy(check.MODELS_JSON["providers"][check.PROVIDER]["models"])
    return [
        {"provider": check.PROVIDER, **priced},
        {"provider": check.PROVIDER, **unpriced, "contextWindow": 128000, "cost": ZERO},
    ]


@pytest.fixture
def run(fake_pi, tmp_path, monkeypatch):
    def _run(rows=None, **env):
        monkeypatch.setenv("AMICUS_PI_BIN", str(fake_pi))
        monkeypatch.setenv("FAKE_PI_MODELS", TABLE)
        monkeypatch.setenv("FAKE_PI_RPC_MODELS", json.dumps(_rpc_rows() if rows is None else rows))
        for name, value in {**check.prepare(tmp_path), **env}.items():
            monkeypatch.setenv(name, value)
        return check.verify()

    return _run


def test_prepare_writes_a_scratch_agent_dir_and_points_pi_at_it(tmp_path):
    env = check.prepare(tmp_path)
    assert set(env) == {"PI_CODING_AGENT_DIR", "AMICUS_STATE_DIR"}
    assert all(Path(value).is_absolute() and Path(value).is_dir() for value in env.values())
    written = json.loads((Path(env["PI_CODING_AGENT_DIR"]) / "models.json").read_text())
    assert written == check.MODELS_JSON


def test_a_catalog_that_returns_what_was_written_passes(run):
    assert run() == []


def test_a_reply_amicus_cannot_read_is_reported_as_a_missing_price(run):
    [problem] = run(FAKE_PI_RPC_REPLY="")
    assert check.PRICED in problem and "no price" in problem


def test_a_reply_without_cost_is_reported(run):
    rows = _rpc_rows()
    del rows[0]["cost"]
    [problem] = run(rows)
    assert "no price" in problem


@pytest.mark.parametrize(
    ("change", "said"),
    [
        (lambda row: row["cost"].update(output=99), "price is"),
        (lambda row: row["cost"].pop("tiers"), "price is"),
        (lambda row: row.update(contextWindow=1), "limits are"),
    ],
)
def test_a_price_or_limit_that_differs_from_what_was_written_is_reported(run, change, said):
    rows = _rpc_rows()
    change(rows[0])
    [problem] = run(rows)
    assert said in problem


def test_an_unpriced_model_that_comes_back_priced_is_reported(run):
    rows = _rpc_rows()
    rows[1]["cost"] = {**ZERO, "output": 1}
    [problem] = run(rows)
    assert check.UNPRICED in problem and "came back priced" in problem


def test_a_model_the_table_does_not_list_is_reported(run, monkeypatch):
    problems = run(FAKE_PI_MODELS="provider  model  context  max-out  thinking  images\n")
    assert len(problems) == 2 and all("does not list" in problem for problem in problems)


def test_an_unreadable_table_is_reported_once(run):
    [problem] = run(AMICUS_PI_BIN="/nonexistent/pi")
    assert "could not read pi's model table" in problem


def test_main_exits_0_with_ok_and_1_with_fail(run, monkeypatch, capsys):
    run()  # sets the fake binary and its catalog; main() then prepares its own scratch dir
    assert check.main() == 0
    assert capsys.readouterr().out.startswith("OK  :")
    monkeypatch.setenv("FAKE_PI_RPC_REPLY", "")
    assert check.main() == 1
    assert capsys.readouterr().out.startswith("FAIL:")
