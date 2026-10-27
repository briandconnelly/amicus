"""`scripts/capture_codex_wire_tools.py` (#380): the zero-spend wire-tool probe.

Every binary here is `tests/support/fake_codex_wire.py`, which POSTs a canned request to the
script's fake Responses server. No real codex is ever run."""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

from amicus.backends.codex import contract as codex_contract

_SCRIPT = Path(__file__).parent.parent / "scripts" / "capture_codex_wire_tools.py"
_spec = importlib.util.spec_from_file_location("capture_codex_wire_tools", _SCRIPT)
assert _spec is not None and _spec.loader is not None
wire = importlib.util.module_from_spec(_spec)
sys.modules["capture_codex_wire_tools"] = wire
_spec.loader.exec_module(wire)

_FAKE = Path(__file__).parent / "support" / "fake_codex_wire.py"

CLASSIC, CODE_MODE = "gpt-classic", "gpt-code-mode"
ALL_FEATURES = ["goals", "remote_plugin", "sleep_tool"]
GATED = {"sleep_tool": ["sleep"], "goals": ["create_goal", "get_goal", "update_goal"]}


def _fn(name: str, description: str = "") -> dict:
    return {"type": "function", "name": name, "description": description, "parameters": {}}


def _goal_tools() -> list[dict]:
    return [_fn("create_goal"), _fn("get_goal"), _fn("update_goal")]


def _classic(*, update_plan: bool, goals: bool) -> list[dict]:
    tools = [_fn("exec_command"), _fn("write_stdin")]
    if update_plan:
        tools.append(_fn("update_plan"))
    if goals:
        tools += _goal_tools()
    return [*tools, {"type": "web_search"}]


def _code_mode(*, clock: bool, nested: tuple[str, ...] = ("exec_command",)) -> list[dict]:
    declared = "\n".join(
        f"declare const tools: {{ {n}(args: {{}}): Promise<unknown>; }};" for n in nested
    )
    tools = [
        {
            "type": "namespace",
            "name": "functions",
            "description": "",
            "tools": [{"type": "custom", "name": "exec", "description": declared}, _fn("wait")],
        }
    ]
    if clock:
        tools.append(
            {"type": "namespace", "name": "clock", "description": "", "tools": [_fn("sleep")]}
        )
    return tools


def _bundled() -> list[dict]:
    return [
        {"slug": CLASSIC, "tool_mode": None, "base_instructions": "never persisted"},
        {
            "slug": CODE_MODE,
            "tool_mode": "code_mode_only",
            "experimental_supported_tools": ["clock"],
            "base_instructions": "never persisted",
        },
    ]


def _fake(root: Path, name: str, **spec) -> Path:
    folder = root / name
    folder.mkdir()
    exe = folder / "codex"
    shutil.copy(_FAKE, exe)
    exe.chmod(0o755)
    spec.setdefault("bundled", _bundled())
    spec.setdefault("gated", GATED)
    (folder / "codex.json").write_text(json.dumps(spec))
    return exe


def _validated_spec(version: str, log: Path) -> dict:
    return {
        "version": version,
        "features": ALL_FEATURES,
        "tools": {CLASSIC: _classic(update_plan=False, goals=True)},
        "additional": {CODE_MODE: _code_mode(clock=True)},
        "log": str(log),
    }


def _run(old: Path, new: Path, *extra: str) -> list[str]:
    return [
        "--old-bin",
        str(old),
        "--new-bin",
        str(new),
        "--model",
        CLASSIC,
        "--model",
        CODE_MODE,
        *extra,
    ]


def _log(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def _exec_runs(path: Path) -> list[dict]:
    return [e for e in _log(path) if e["argv"][:1] == ["exec"]]


@pytest.fixture
def replay(tmp_path):
    """A 0.151 -> 0.152-like pair: the old binary has no sleep_tool feature and still offers
    update_plan; the new one drops update_plan and offers a gated clock.sleep."""
    log = tmp_path / "calls.jsonl"
    old = _fake(
        tmp_path,
        "old",
        version="0.151.0",
        features=["goals", "remote_plugin"],
        tools={CLASSIC: _classic(update_plan=True, goals=False)},
        additional={CODE_MODE: _code_mode(clock=False, nested=("exec_command", "update_plan"))},
        log=str(log),
    )
    new = _fake(
        tmp_path,
        "new",
        version="0.152.0",
        features=ALL_FEATURES,
        tools={CLASSIC: _classic(update_plan=False, goals=False)},
        additional={CODE_MODE: _code_mode(clock=True)},
        log=str(log),
    )
    return old, new, log


def test_a_replay_shows_update_plan_removed_and_clock_sleep_added(replay, capsys):
    old, new, log = replay
    code = wire.main(_run(old, new))
    out = capsys.readouterr().out
    assert "    - update_plan" in out
    assert "    - exec/update_plan (nested; may only be deferred)" in out
    assert "    + clock.sleep" in out
    assert "old 0.151.0: unsupported on this binary, not sent: sleep_tool" in out
    assert "new 0.152.0: sleep_tool: passed: clock.sleep offered by gpt-code-mode" in out
    # No goal tool anywhere, so that control has nothing to prove: not validated.
    assert "goals: unobserved" in out
    assert "NOT VALIDATED" in out
    assert "FAIL" not in out
    assert code == 3


def test_the_old_binary_gets_only_the_disables_it_lists(tmp_path, capsys):
    log_old, log_new = tmp_path / "old.jsonl", tmp_path / "new.jsonl"
    old = _fake(
        tmp_path,
        "old",
        version="0.151.0",
        features=["goals", "remote_plugin"],
        default_tools=[_fn("exec_command")],
        log=str(log_old),
    )
    new = _fake(
        tmp_path,
        "new",
        features=ALL_FEATURES,
        default_tools=[_fn("exec_command")],
        log=str(log_new),
    )
    wire.main(_run(old, new))
    capsys.readouterr()

    def disables(path: Path) -> set[tuple[str, ...]]:
        return {
            tuple(e["argv"][i + 1] for i, t in enumerate(e["argv"]) if t == "--disable")
            for e in _exec_runs(path)
        }

    assert disables(log_old) == {(), ("remote_plugin", "goals")}
    assert disables(log_new) == {(), codex_contract.MODEL_RUN_DISABLED_FEATURES}


def test_both_controls_applied_on_both_binaries_is_validated(tmp_path, capsys):
    log = tmp_path / "calls.jsonl"
    old = _fake(tmp_path, "old", **_validated_spec("0.163.0", log))
    new = _fake(tmp_path, "new", **_validated_spec("0.164.0", log))
    code = wire.main(_run(old, new))
    out = capsys.readouterr().out
    assert "DIFFERED (nothing)" in out
    for side in ("old 0.163.0", "new 0.164.0"):
        assert f"{side}: sleep_tool: passed" in out
        assert f"{side}: goals: passed" in out
    assert "VALIDATED: every control was applied" in out
    assert "8 of 8 runs: exactly one request" in out
    assert code == 0


def test_omit_disables_makes_every_applicable_control_fail(tmp_path, capsys):
    """The negative control: with no --disable sent, the positive control must fail loudly."""
    log = tmp_path / "calls.jsonl"
    old = _fake(tmp_path, "old", **_validated_spec("0.163.0", log))
    new = _fake(tmp_path, "new", **_validated_spec("0.164.0", log))
    code = wire.main(_run(old, new, "--omit-disables"))
    out = capsys.readouterr().out
    assert all("--disable" not in e["argv"] for e in _exec_runs(log))
    assert "sleep_tool: FAILED on gpt-code-mode: the disabled run still offers clock.sleep" in out
    assert "goals: FAILED on gpt-classic" in out
    assert "FAIL positive control sleep_tool failed on the new binary" in out
    assert "NOT VALIDATED" in out
    assert code == 1


def test_a_binary_that_ignores_its_disables_fails_the_control(tmp_path, capsys):
    log = tmp_path / "calls.jsonl"
    old = _fake(tmp_path, "old", **_validated_spec("0.163.0", log))
    new = _fake(tmp_path, "new", **_validated_spec("0.164.0", log), ignore_disables=True)
    code = wire.main(_run(old, new))
    out = capsys.readouterr().out
    assert "old 0.163.0: sleep_tool: passed" in out
    assert "new 0.164.0: sleep_tool: FAILED" in out
    assert "new 0.164.0: goals: FAILED" in out
    assert code == 1


def test_an_empty_capture_is_a_failure_not_an_empty_catalog(tmp_path, capsys):
    log = tmp_path / "calls.jsonl"
    old = _fake(tmp_path, "old", **_validated_spec("0.163.0", log))
    new = _fake(
        tmp_path, "new", version="0.164.0", features=ALL_FEATURES, default_tools=[], log=str(log)
    )
    code = wire.main(_run(old, new))
    out = capsys.readouterr().out
    assert "new 0.164.0 gpt-classic baseline: empty: the request carried no tools at all" in out
    assert "new 0.164.0: sleep_tool: unobserved" in out
    assert code == 1


def test_a_startup_failure_is_never_an_empty_catalog(tmp_path, capsys):
    log = tmp_path / "calls.jsonl"
    old = _fake(tmp_path, "old", **_validated_spec("0.163.0", log))
    new = _fake(tmp_path, "new", **_validated_spec("0.164.0", log), no_request=True)
    code = wire.main(_run(old, new))
    out = capsys.readouterr().out
    assert "new 0.164.0 gpt-classic baseline: no-request: exit 1 before any request" in out
    assert "could not start the session" in out
    assert "new 0.164.0 gpt-classic baseline: no-request" in out
    assert code == 1


def test_a_disable_rejected_at_startup_is_unsupported_not_empty(tmp_path, capsys):
    log = tmp_path / "calls.jsonl"
    old = _fake(tmp_path, "old", **_validated_spec("0.163.0", log))
    new = _fake(tmp_path, "new", **_validated_spec("0.164.0", log), reject_features=["goals"])
    code = wire.main(_run(old, new))
    out = capsys.readouterr().out
    assert (
        "new 0.164.0 gpt-classic disabled: unsupported: Error: Unknown feature flag: goals" in out
    )
    assert code == 1


def test_outbound_hosts_are_refused_and_reported(tmp_path, capsys):
    log = tmp_path / "calls.jsonl"
    old = _fake(tmp_path, "old", **_validated_spec("0.163.0", log), connect=["chatgpt.com"])
    new = _fake(tmp_path, "new", **_validated_spec("0.164.0", log), connect=["github.com"])
    code = wire.main(_run(old, new))
    out = capsys.readouterr().out
    assert "OUTBOUND (refused by the probe's proxy): chatgpt.com, github.com" in out
    assert code == 0


def test_an_attempt_on_the_model_host_fails(tmp_path, capsys):
    log = tmp_path / "calls.jsonl"
    old = _fake(tmp_path, "old", **_validated_spec("0.163.0", log))
    new = _fake(tmp_path, "new", **_validated_spec("0.164.0", log), connect=["api.openai.com"])
    code = wire.main(_run(old, new))
    out = capsys.readouterr().out
    assert "tried to reach api.openai.com through the proxy (refused)" in out
    assert code == 1


def test_runs_are_isolated_and_keep_nothing_raw(tmp_path, capsys, monkeypatch):
    """No credential reaches a run; the prompt rides stdin only; the record and the report
    carry names and hashes, never the request's text, instructions or headers."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-key")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "real-home"))
    log = tmp_path / "calls.jsonl"
    old = _fake(tmp_path, "old", **_validated_spec("0.163.0", log))
    new = _fake(tmp_path, "new", **_validated_spec("0.164.0", log))
    record = tmp_path / "record.json"
    assert wire.main(_run(old, new, "--out", str(record))) == 0
    out = capsys.readouterr().out
    runs = _exec_runs(log)
    assert runs
    for entry in runs:
        assert "OPENAI_API_KEY" not in entry["env"]
        assert "HTTPS_PROXY" in entry["env"]
        assert entry["stdin"] == wire.SYNTHETIC_PROMPT
        assert wire.SYNTHETIC_PROMPT.strip() not in " ".join(entry["argv"])
        assert "--sandbox" in entry["argv"] and codex_contract.SANDBOX_READ_ONLY in entry["argv"]
        assert any(a.startswith("model_catalog_json=") for a in entry["argv"])
    text = record.read_text()
    for raw in (
        wire.SYNTHETIC_PROMPT.strip(),
        "fake instructions",
        "must-not-leak",
        "never persisted",
    ):
        assert raw not in text
        assert raw not in out
    data = json.loads(text)
    tools = data["sides"]["new"]["captures"][f"{CODE_MODE} baseline"]["tools"]
    assert set(tools) == {
        "namespace:functions",
        "exec",
        "exec/exec_command",
        "wait",
        "namespace:clock",
        "clock.sleep",
    }
    assert tools["exec/exec_command"] is None
    assert all(len(v) == wire.HASH_CHARS for k, v in tools.items() if v is not None)
    assert data["validated"] is True


def test_fallback_metadata_and_models_missing_from_the_catalog_are_reported(tmp_path, capsys):
    log = tmp_path / "calls.jsonl"
    old = _fake(tmp_path, "old", **_validated_spec("0.163.0", log), fallback=True)
    new = _fake(tmp_path, "new", **_validated_spec("0.164.0", log), bundled=[_bundled()[1]])
    wire.main(_run(old, new))
    out = capsys.readouterr().out
    assert "gpt-classic baseline: old 6, new 6 (old 0.163.0 ran on fallback metadata)" in out
    assert "captured on codex's fallback metadata, not the model's own: gpt-classic" in out
    assert "in the catalog in use: gpt-code-mode" in out


def test_blind_spots_are_reported_as_unobserved(tmp_path, capsys):
    log = tmp_path / "calls.jsonl"
    old = _fake(tmp_path, "old", **_validated_spec("0.163.0", log))
    new = _fake(tmp_path, "new", **_validated_spec("0.164.0", log))
    wire.main(_run(old, new))
    unobserved = capsys.readouterr().out.split("UNOBSERVED")[1]
    assert "remote_plugin: the plugin-tool family never appears in a scratch home" in unobserved
    assert "code_mode_only models' nested tools" in unobserved
    assert "the served model catalog" in unobserved


def test_catalog_own_sends_no_shared_catalog(tmp_path, capsys):
    log = tmp_path / "calls.jsonl"
    old = _fake(tmp_path, "old", **_validated_spec("0.163.0", log))
    new = _fake(tmp_path, "new", **_validated_spec("0.164.0", log))
    wire.main(_run(old, new, "--catalog", "own"))
    assert "each binary's own bundled catalog" in capsys.readouterr().out
    assert all(
        not any(a.startswith("model_catalog_json=") for a in e["argv"]) for e in _exec_runs(log)
    )


def test_catalog_bin_supplies_the_shared_catalog(tmp_path, capsys):
    log = tmp_path / "calls.jsonl"
    old = _fake(tmp_path, "old", **_validated_spec("0.163.0", log))
    new = _fake(tmp_path, "new", **_validated_spec("0.164.0", log))
    third = _fake(tmp_path, "third", version="0.170.0", bundled=[_bundled()[0]])
    record = tmp_path / "record.json"
    wire.main(_run(old, new, "--catalog-bin", str(third), "--out", str(record)))
    out = capsys.readouterr().out
    assert f"the bundled catalog of {third}, applied to both" in out
    assert "fallback metadata, not the model's own: gpt-code-mode" in out
    assert json.loads(record.read_text())["catalog_bin_version"] == "0.170.0"


def test_an_unreadable_catalog_stops_before_capturing(tmp_path, capsys):
    log = tmp_path / "calls.jsonl"
    old = _fake(tmp_path, "old", **_validated_spec("0.163.0", log))
    spec = _validated_spec("0.164.0", log)
    new = _fake(tmp_path, "new", **spec)
    (new.parent / "codex.json").write_text(json.dumps(spec | {"gated": GATED}))  # no `bundled`
    assert wire.main(_run(old, new)) == 2
    assert "STOPPED: `debug models --bundled` could not be read" in capsys.readouterr().out
    assert _exec_runs(log) == []


def test_an_unreadable_version_or_feature_list_stops(tmp_path, capsys):
    log = tmp_path / "calls.jsonl"
    old = _fake(tmp_path, "old", **_validated_spec("0.163.0", log))
    new = _fake(tmp_path, "new", **_validated_spec("0.164.0", log) | {"features": []})
    assert wire.main(_run(old, new)) == 2
    assert (
        "STOPPED: `features list` could not be read from the new binary" in capsys.readouterr().out
    )
    assert wire.main(_run(old, tmp_path / "missing" / "codex")) == 2
    assert "printed no release" in capsys.readouterr().out


def test_catalog_of_reads_both_carriers_and_code_mode_nesting():
    body = {
        "tools": [
            _fn("exec_command"),
            {"type": "namespace", "name": "multi_agent_v1", "tools": [_fn("spawn_agent")]},
            {"type": "web_search"},
        ],
        "input": [
            {
                "type": "additional_tools",
                "tools": _code_mode(clock=True, nested=("clock__curr_time",)),
            },
            {"type": "message", "role": "user", "content": "ignored"},
        ],
    }
    catalog = wire.catalog_of(body)
    assert catalog is not None
    assert set(catalog) == {
        "namespace:multi_agent_v1",
        "namespace:functions",
        "namespace:clock",
        "exec_command",
        "multi_agent_v1.spawn_agent",
        "web_search",
        "exec",
        "exec/clock__curr_time",
        "wait",
        "clock.sleep",
    }
    assert wire.leaf("exec/clock__curr_time") == "clock.curr_time"
    assert wire.catalog_of({"tools": []}) == {}
    assert wire.catalog_of([1]) is None
    changed = wire.catalog_of({"tools": [_fn("exec_command", "a new description")]})
    assert changed is not None and changed["exec_command"] != catalog["exec_command"]


def test_catalog_diff_marks_nested_removals_as_possibly_deferred():
    lines = wire.catalog_diff({"a": "1", "exec/x": None, "b": "2"}, {"a": "1", "b": "3", "c": "4"})
    assert lines == [
        "+ c",
        "- exec/x (nested; may only be deferred)",
        "~ b (definition hash 2 -> 3)",
    ]


# --- regressions from the review of #388 ----------------------------------------------------


def test_one_goal_tool_does_not_validate_the_goals_control(tmp_path, capsys):
    """Every controlled tool needs its own observed baseline, not just one of them."""
    log = tmp_path / "calls.jsonl"
    partial = {CLASSIC: [_fn("exec_command"), _fn("create_goal")]}
    old = _fake(tmp_path, "old", **_validated_spec("0.163.0", log) | {"tools": partial})
    new = _fake(tmp_path, "new", **_validated_spec("0.164.0", log) | {"tools": partial})
    code = wire.main(_run(old, new))
    out = capsys.readouterr().out
    assert "goals: unobserved: no authoritative baseline offers get_goal, update_goal" in out
    assert "NOT VALIDATED" in out
    assert code == 3


def test_a_nested_disappearance_alone_does_not_pass_a_control(tmp_path, capsys):
    """A tool seen only in exec's description may just be deferred, so its disappearance
    there cannot pass the control."""
    log = tmp_path / "calls.jsonl"
    nested = _code_mode(
        clock=True, nested=("exec_command", "create_goal", "get_goal", "update_goal")
    )
    spec = {
        "features": ALL_FEATURES,
        "tools": {CLASSIC: _classic(update_plan=False, goals=False)},
        "additional": {CODE_MODE: nested},
        "log": str(log),
    }
    old = _fake(tmp_path, "old", version="0.163.0", **spec)
    new = _fake(tmp_path, "new", version="0.164.0", **spec)
    code = wire.main(_run(old, new))
    out = capsys.readouterr().out
    assert "goals: passed" not in out
    assert (
        "goals: unobserved: no authoritative baseline offers create_goal, get_goal, update_goal"
        in out
    )
    assert code == 3


def test_a_nested_tool_still_declared_after_its_disable_fails(tmp_path, capsys):
    log = tmp_path / "calls.jsonl"
    nested = _code_mode(clock=True, nested=("exec_command", "create_goal"))
    spec = _validated_spec("0.164.0", log) | {"additional": {CODE_MODE: nested}}
    old = _fake(tmp_path, "old", **_validated_spec("0.163.0", log))
    new = _fake(
        tmp_path,
        "new",
        **spec | {"gated": {"sleep_tool": ["sleep"], "goals": ["get_goal", "update_goal"]}},
    )
    code = wire.main(_run(old, new))
    out = capsys.readouterr().out
    assert (
        "new 0.164.0: goals: FAILED on gpt-code-mode: the disabled run still offers "
        "exec/create_goal" in out
    )
    assert code == 1


def test_a_namespace_change_of_its_own_moves_a_hash():
    def ns(description: str) -> dict:
        return {
            "tools": [
                {
                    "type": "namespace",
                    "name": "clock",
                    "description": description,
                    "tools": [_fn("sleep")],
                }
            ]
        }

    before, after = wire.catalog_of(ns("Sleep up to 12h.")), wire.catalog_of(ns("Sleep up to 24h."))
    assert before is not None and after is not None
    assert before != after
    assert wire.catalog_diff(before, after) != []


def test_catalog_own_keeps_each_binarys_facts(tmp_path, capsys):
    log = tmp_path / "calls.jsonl"
    old = _fake(tmp_path, "old", **_validated_spec("0.163.0", log) | {"bundled": [_bundled()[1]]})
    new = _fake(tmp_path, "new", **_validated_spec("0.164.0", log))
    record = tmp_path / "record.json"
    wire.main(_run(old, new, "--catalog", "own", "--out", str(record)))
    out = capsys.readouterr().out
    assert (
        "on the old binary (0.163.0), not in its own bundled catalog, so captured on codex's "
        "fallback metadata, not the model's own: gpt-classic" in out
    )
    assert "on the new binary (0.164.0), not in its own bundled catalog" not in out
    facts = json.loads(record.read_text())["sides"]
    assert facts["old"]["catalog_facts"][CLASSIC] is None
    assert facts["new"]["catalog_facts"][CLASSIC] is not None


def test_the_run_summary_counts_failed_captures_as_failed(tmp_path, capsys):
    log = tmp_path / "calls.jsonl"
    old = _fake(tmp_path, "old", **_validated_spec("0.163.0", log))
    new = _fake(tmp_path, "new", **_validated_spec("0.164.0", log), no_request=True)
    wire.main(_run(old, new))
    assert "4 of 8 runs: exactly one request" in capsys.readouterr().out


# --- regressions from Copilot's review of #388 ------------------------------------------------


def test_a_controlled_tool_surviving_where_the_baseline_lacked_it_fails(tmp_path, capsys):
    """A disabled run that still offers a controlled tool fails the control, even when that
    model's baseline did not show it and another model's removal would pass the control."""
    log = tmp_path / "calls.jsonl"
    leaky = _code_mode(clock=True, nested=("exec_command", "create_goal"))
    old = _fake(tmp_path, "old", **_validated_spec("0.163.0", log))
    new = _fake(
        tmp_path, "new", **_validated_spec("0.164.0", log), when_disabled={CODE_MODE: leaky}
    )
    code = wire.main(_run(old, new))
    out = capsys.readouterr().out
    assert (
        "new 0.164.0: goals: FAILED on gpt-code-mode: the disabled run still offers "
        "exec/create_goal" in out
    )
    assert "NOT VALIDATED" in out
    assert code == 1


@pytest.mark.parametrize(
    ("spec", "status"),
    [({"exit_after": 1}, "exited 1 after its request"), ({"requests": 2}, "sent 2 requests")],
)
def test_a_capture_needs_exactly_one_request_and_exit_0(tmp_path, capsys, spec, status):
    log = tmp_path / "calls.jsonl"
    old = _fake(tmp_path, "old", **_validated_spec("0.163.0", log))
    new = _fake(tmp_path, "new", **_validated_spec("0.164.0", log) | spec)
    code = wire.main(_run(old, new))
    out = capsys.readouterr().out
    assert f"new 0.164.0 gpt-classic baseline: unclean: {status}" in out
    assert "4 of 8 runs: exactly one request" in out
    assert "NOT VALIDATED" in out
    assert code == 1


def test_omit_disables_records_no_disable_sent(tmp_path, capsys):
    log = tmp_path / "calls.jsonl"
    old = _fake(tmp_path, "old", **_validated_spec("0.163.0", log))
    new = _fake(tmp_path, "new", **_validated_spec("0.164.0", log))
    record = tmp_path / "record.json"
    wire.main(_run(old, new, "--omit-disables", "--out", str(record)))
    capsys.readouterr()
    sides = json.loads(record.read_text())["sides"]
    assert sides["old"]["disables_sent"] == sides["new"]["disables_sent"] == []
    assert sides["new"]["disables_supported"] == list(codex_contract.MODEL_RUN_DISABLED_FEATURES)
