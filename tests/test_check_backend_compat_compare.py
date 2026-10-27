"""`check_backend_compat.py compare` (#376), driven by fake binaries only.

`compare` takes its binaries by explicit path, so the guard in tests/conftest.py that makes
AMICUS_CODEX_BIN unusable does not cover it. Every binary here is a copy of
tests/support/fake_codex_compare.py in a temporary directory; never pass a real codex."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from amicus.backends.codex import contract as codex_contract

_SCRIPT = Path(__file__).parent.parent / "scripts" / "check_backend_compat.py"
_spec = importlib.util.spec_from_file_location("check_backend_compat", _SCRIPT)
assert _spec is not None and _spec.loader is not None
compat = importlib.util.module_from_spec(_spec)
sys.modules["check_backend_compat"] = compat
_spec.loader.exec_module(compat)

_FAKE = Path(__file__).parent / "support" / "fake_codex_compare.py"
_NEW_FEATURES = {
    "goals": ["stable", "true"],
    "remote_plugin": ["stable", "true"],
    "sleep_tool": ["stable", "true"],
    "some_feature": ["stable", "true"],
    "new_feature": ["under development", "false"],
}


def _fake(root: Path, name: str, **spec) -> Path:
    folder = root / name
    folder.mkdir()
    exe = folder / "codex"
    shutil.copy(_FAKE, exe)
    exe.chmod(0o755)
    (folder / "codex.json").write_text(json.dumps(spec))
    return exe


def _exec_help(exe: Path) -> str:
    return subprocess.run(
        [exe, "exec", "--help"], capture_output=True, text=True, check=True
    ).stdout


def _commit_capture(docs: Path, version: str, text: str) -> Path:
    folder = docs / "codex-help" / version
    folder.mkdir(parents=True)
    (folder / "codex-help.txt").write_text(compat.hygiene(text))
    return folder


def _log(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def _exec_runs(entries: list[dict]) -> list[dict]:
    """Every `exec` run that is a probe, not the `exec --help` surface."""
    return [e for e in entries if e["argv"][:1] == ["exec"] and "--help" not in e["argv"]]


@pytest.fixture
def pair(tmp_path):
    """An old binary with its committed capture and a new one with a 0.164-like change set:
    one subcommand added, one feature promoted, one added, exec --help unchanged."""
    log = tmp_path / "calls.jsonl"
    old = _fake(tmp_path, "old", version="0.163.0", log=str(log))
    new = _fake(
        tmp_path,
        "new",
        version="0.164.0",
        commands=["exec", "login", "features", "migrate-nfs-db", "debug"],
        features=_NEW_FEATURES,
        log=str(log),
    )
    docs = tmp_path / "docs"
    _commit_capture(docs, "0.163.0", _exec_help(old))
    return old, new, docs, log


def _compare(old: Path, new: Path, docs: Path, *extra: str) -> list[str]:
    return [
        "compare",
        "--backend",
        "codex",
        "--old-bin",
        str(old),
        "--new-bin",
        str(new),
        "--docs-root",
        str(docs),
        *extra,
    ]


def _section(out: str, name: str) -> str:
    """One section of the report, up to the next section heading or FAIL line."""
    lines = out.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(name))
    end = next(
        (
            i
            for i in range(start + 1, len(lines))
            if lines[i].split(" ")[0] in {"CHECKED", "DIFFERED", "NOT", "FAIL"}
        ),
        len(lines),
    )
    return "\n".join(lines[start:end])


def test_a_replay_reports_each_difference_and_passes(pair, capsys):
    old, new, docs, _log_path = pair
    assert compat.main(_compare(old, new, docs)) == 0
    out = capsys.readouterr().out
    checked, differed, not_run = (_section(out, s) for s in ("CHECKED", "DIFFERED", "NOT RUN"))
    assert "FAIL" not in out, out
    # The fake pads blank help lines with spaces and the committed capture does not.
    assert "matches" in checked and "after the whitespace policy" in checked
    for surface in ("exec --help", "exec review --help", "login --help"):
        assert f"{surface}: identical" in checked
    assert "+ command migrate-nfs-db" in differed
    assert "~ feature some_feature: under development, default false -> stable, default true" in (
        differed
    )
    assert "+ feature new_feature: under development, default false" in differed
    for probe in compat.codex_probes():
        assert f"probe {probe.name}: both binaries" in checked, probe.name
    assert "login status: logged-out output identical" in checked
    assert "debug models" in not_run and "tool catalog" in not_run


def test_an_old_binary_that_does_not_match_its_capture_stops_everything(pair, capsys):
    old, new, docs, log = pair
    capture = docs / "codex-help" / "0.163.0" / "codex-help.txt"
    capture.write_text(capture.read_text() + "      --only-in-the-capture\n")
    assert compat.main(_compare(old, new, docs)) == 2
    out = capsys.readouterr().out
    assert "STOPPED" in out and "--only-in-the-capture" in out
    assert "CHECKED" not in out
    assert _exec_runs(_log(log)) == [], "no probe runs once the baseline is refused"


def test_whitespace_beyond_the_policy_is_a_mismatch(pair, capsys):
    """The policy forgives what the hooks strip, trailing whitespace and the final
    newlines, and nothing else: an indent change is a different text."""
    old, new, docs, _log_path = pair
    capture = docs / "codex-help" / "0.163.0" / "codex-help.txt"
    capture.write_text(capture.read_text().replace("      --json", "       --json"))
    assert compat.main(_compare(old, new, docs)) == 2


def test_a_missing_baseline_is_a_failure_and_the_comparison_still_runs(pair, capsys):
    old, new, docs, _log_path = pair
    shutil.rmtree(docs / "codex-help" / "0.163.0")
    _commit_capture(docs, "0.162.1", "an older capture\n")
    assert compat.main(_compare(old, new, docs)) == 1
    out = capsys.readouterr().out
    assert "FAIL baseline: no capture is committed for the old version 0.163.0" in out
    assert "newest capture (0.162.1)" in out
    assert "baseline authentication" in _section(out, "NOT RUN")
    assert "probe pins and disables: both binaries" in _section(out, "CHECKED")


def test_no_credential_and_no_ambient_state_reaches_any_run(pair, capsys, monkeypatch, tmp_path):
    old, new, docs, log = pair
    for key in ("OPENAI_API_KEY", "CODEX_API_KEY", "CODEX_ACCESS_TOKEN", "AMICUS_TEST_CANARY"):
        monkeypatch.setenv(key, "must-not-arrive")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "callers-codex-home"))
    assert compat.main(_compare(old, new, docs)) == 0
    entries = _log(log)
    assert entries, "control: the fakes did log their runs"
    for entry in entries:
        for key in ("OPENAI_API_KEY", "CODEX_API_KEY", "CODEX_ACCESS_TOKEN", "AMICUS_TEST_CANARY"):
            assert key not in entry["env"], entry
        assert entry["codex_home"] != str(tmp_path / "callers-codex-home")
    probes = _exec_runs(entries)
    assert len(probes) == 2 * len(compat.codex_probes())
    homes = [e["codex_home"] for e in probes]
    assert len(set(homes)) == len(homes), "each probe gets a fresh scratch home"
    guarded = {e["codex_home"] for e in entries if e["argv"] == ["login", "status"]}
    assert set(homes) <= guarded, "each probe's home was checked for a login first"
    for entry in probes:
        # Rule 18: the one prompt is the script's own literal, over stdin and never argv.
        assert entry["stdin"] == compat.SYNTHETIC_PROMPT
        assert not any(compat.SYNTHETIC_PROMPT.strip() in arg for arg in entry["argv"])


def test_the_pins_probe_sends_what_amicus_sends(pair, capsys):
    old, new, docs, log = pair
    assert compat.main(_compare(old, new, docs)) == 0
    pinned = [e["argv"] for e in _exec_runs(_log(log)) if "workspace-write" in e["argv"]]
    assert len(pinned) == 2
    for argv in pinned:
        keys = {argv[i + 1].split("=")[0] for i, arg in enumerate(argv) if arg == "-c"}
        assert keys == codex_contract.PLUGIN_OWNED_CONFIG_KEYS
        disabled = [argv[i + 1] for i, arg in enumerate(argv) if arg == "--disable"]
        assert disabled == list(codex_contract.MODEL_RUN_DISABLED_FEATURES)
        assert codex_contract.STRICT_CONFIG_FLAG in argv


def test_a_contract_key_the_pins_probe_does_not_send_is_a_failure(pair, capsys, monkeypatch):
    old, new, docs, _log_path = pair
    monkeypatch.setattr(
        codex_contract,
        "PLUGIN_OWNED_CONFIG_KEYS",
        codex_contract.PLUGIN_OWNED_CONFIG_KEYS | {"a_new_pin"},
    )
    assert compat.main(_compare(old, new, docs)) == 1
    assert "does not send every plugin-owned key: a_new_pin" in capsys.readouterr().out


def test_a_scratch_home_that_reports_a_login_runs_no_probe(tmp_path, capsys):
    log = tmp_path / "calls.jsonl"
    old = _fake(tmp_path, "old", version="0.163.0")
    new = _fake(tmp_path, "new", version="0.164.0", logged_in=True, log=str(log))
    docs = tmp_path / "docs"
    _commit_capture(docs, "0.163.0", _exec_help(old))
    assert compat.main(_compare(old, new, docs)) == 1
    out = capsys.readouterr().out
    for probe in compat.codex_probes():
        assert f"FAIL probe {probe.name} on the new binary (0.164.0)" in out
    assert "did not report logged out" in out
    assert _exec_runs(_log(log)) == [], "the guard refused every exec run on that binary"


def test_a_grammar_drift_fails_its_probe_and_shows_the_stderr_diff(tmp_path, capsys):
    old = _fake(tmp_path, "old", version="0.163.0")
    new = _fake(tmp_path, "new", version="0.164.0", override_wording="from an override")
    docs = tmp_path / "docs"
    _commit_capture(docs, "0.163.0", _exec_help(old))
    assert compat.main(_compare(old, new, docs)) == 1
    out = capsys.readouterr().out
    assert "FAIL probe strict-config override on the new binary" in out
    assert "not in the wording the contract parses" in out
    assert "FAIL probe strict-config override on the old binary" not in out
    differed = _section(out, "DIFFERED")
    assert "probe strict-config override: stderr differs" in differed
    assert "+Error loading config.toml" in differed and "from an override" in differed


@pytest.mark.parametrize(
    ("spec", "probe", "how"),
    [
        # The positive control fails loudly: a pin the binary no longer knows.
        ({"reject_keys": ["model_reasoning_effort"]}, "pins and disables", "configuration"),
        # A rejection that no longer happens is caught by how far the run got.
        ({"accept_unknown_feature": True}, "unknown --disable", "past config loading"),
        # A run that exits 0 got further than any credential-free run can.
        ({"exec_exit": 0}, "pins and disables", "exited 0"),
    ],
)
def test_a_probe_that_ends_the_wrong_way_is_a_failure(tmp_path, capsys, spec, probe, how):
    old = _fake(tmp_path, "old", version="0.163.0")
    new = _fake(tmp_path, "new", version="0.164.0", **spec)
    docs = tmp_path / "docs"
    _commit_capture(docs, "0.163.0", _exec_help(old))
    assert compat.main(_compare(old, new, docs)) == 1
    fails = [line for line in capsys.readouterr().out.splitlines() if line.startswith("FAIL")]
    assert any(f"probe {probe} on the new binary" in f and how in f for f in fails), fails
    assert not any("old binary" in f for f in fails), fails


def test_debug_models_runs_only_when_asked_and_under_the_callers_environment(
    tmp_path, capsys, monkeypatch
):
    log = tmp_path / "calls.jsonl"
    old = _fake(tmp_path, "old", version="0.163.0", models="model-a\n", log=str(log))
    new = _fake(tmp_path, "new", version="0.164.0", models="model-b\n", log=str(log))
    docs = tmp_path / "docs"
    _commit_capture(docs, "0.163.0", _exec_help(old))
    monkeypatch.setenv("AMICUS_TEST_CANARY", "the-callers-environment")
    assert compat.main(_compare(old, new, docs)) == 0
    assert "debug models" in _section(capsys.readouterr().out, "NOT RUN")
    assert not [e for e in _log(log) if e["argv"] == ["debug", "models"]]
    assert compat.main(_compare(old, new, docs, "--debug-models")) == 0
    out = capsys.readouterr().out
    assert "debug models: differs" in _section(out, "DIFFERED")
    assert "not a replay" in out
    models = [e for e in _log(log) if e["argv"] == ["debug", "models"]]
    assert len(models) == 2 and all("AMICUS_TEST_CANARY" in e["env"] for e in models)


def test_write_saves_the_new_capture_as_it_will_be_committed(pair, capsys):
    old, new, docs, _log_path = pair
    assert compat.main(_compare(old, new, docs, "--write")) == 0
    folder = docs / "codex-help" / "0.164.0"
    assert f"wrote {folder}" in capsys.readouterr().out
    saved = (folder / "codex-help.txt").read_text()
    raw = _exec_help(new)
    assert saved != raw and saved == compat.hygiene(raw), "control: the raw help has padding"
    assert (folder / "codex-version.txt").read_text() == "0.164.0\n"
    # Next time, that capture is compared rather than overwritten.
    assert compat.main(_compare(old, new, docs, "--write")) == 0
    out = capsys.readouterr().out
    assert "wrote" not in out and f"matches {folder / 'codex-help.txt'}" in out


def test_write_skips_a_prerelease(tmp_path, capsys):
    old = _fake(tmp_path, "old", version="0.163.0")
    new = _fake(tmp_path, "new", version="0.164.0-alpha.1")
    docs = tmp_path / "docs"
    _commit_capture(docs, "0.163.0", _exec_help(old))
    assert compat.main(_compare(old, new, docs, "--write")) == 0
    assert "wrote" not in capsys.readouterr().out
    assert not (docs / "codex-help" / "0.164.0-alpha.1").exists()


def test_a_binary_without_a_readable_version_stops(tmp_path, capsys):
    old = _fake(tmp_path, "old", version="0.163.0")
    new = _fake(tmp_path, "new", version="nightly")
    assert compat.main(_compare(old, new, tmp_path / "docs")) == 2
    assert "STOPPED: the new binary" in capsys.readouterr().out


def test_an_unsupported_backend_is_a_usage_error(tmp_path):
    with pytest.raises(SystemExit) as exc:
        compat.main(["compare", "--backend", "kimi", "--old-bin", "x", "--new-bin", "y"])
    assert exc.value.code == 2


@pytest.mark.parametrize(
    ("raw", "want"),
    [
        ("a  \n\n   \nb\t\n", "a\n\n\nb\n"),
        ("a\n\n\n", "a\n"),
        ("a", "a\n"),
        ("  \n\n", ""),
        ("", ""),
        ("  indented stays\n", "  indented stays\n"),
    ],
)
def test_the_whitespace_policy_is_what_the_commit_hooks_leave(raw, want):
    assert compat.hygiene(raw) == want


def test_the_rows_a_report_reads_from_codex_output():
    help_text = (
        "Commands:\n"
        "  exec              Run Codex\n"
        "  apply             Apply the latest diff produced by Codex agent as a `git apply` to\n"
        "                    working tree [aliases: a]\n"
        "  migrate-nfs-db    [experimental] Migrate\n"
        "\n"
        "Arguments:\n"
        "  [PROMPT]\n"
    )
    assert compat.commands(help_text) == {"exec", "apply", "migrate-nfs-db"}
    features = (
        "goals                                    stable             true\n"
        "incremental_tools                        under development  false\n"
    )
    assert compat.feature_rows(features) == {
        "goals": ("stable", "true"),
        "incremental_tools": ("under development", "false"),
    }


_LOGGED_OUT = {"stderr": "Not logged in\n", "exit": 1}


@pytest.mark.parametrize(
    "status",
    [
        pytest.param({"stderr": "error: unrecognized subcommand 'status'\n", "exit": 2}, id="arg"),
        pytest.param({"stderr": "thread 'main' panicked\n", "exit": 101}, id="crash"),
        pytest.param({"signal": 9}, id="signal"),
        pytest.param(
            {"stderr": "Error: failed to read credentials from keyring: denied\n", "exit": 1},
            id="credential-store",
        ),
        pytest.param({"stdout": "Status unknown\n", "exit": 1}, id="unknown-output"),
        pytest.param({"stderr": "Not logged in\nwarning: odd\n", "exit": 1}, id="extra-output"),
        pytest.param({"stderr": "Not logged in\n", "exit": 2}, id="wrong-exit"),
    ],
)
def test_an_inconclusive_login_status_runs_no_probe(tmp_path, capsys, status):
    """Only codex's observed logged-out answer (0.163.0 and 0.164.0: `Not logged in` on
    stderr, nothing on stdout, exit 1) lets a probe run. Any other failure says nothing about
    whether a credential is reachable, so it must not count as logged out."""
    log = tmp_path / "calls.jsonl"
    old = _fake(tmp_path, "old", version="0.163.0")
    new = _fake(tmp_path, "new", version="0.164.0", login_status=status, log=str(log))
    docs = tmp_path / "docs"
    _commit_capture(docs, "0.163.0", _exec_help(old))
    assert compat.main(_compare(old, new, docs)) == 1
    out = capsys.readouterr().out
    for probe in compat.codex_probes():
        assert f"FAIL probe {probe.name} on the new binary (0.164.0): it must" in out
    assert "did not report logged out (exit " in out or "timed out" in out
    assert _exec_runs(_log(log)) == [], "no exec run follows an inconclusive guard"


def test_the_observed_logged_out_answer_is_the_control(tmp_path, capsys):
    old = _fake(tmp_path, "old", version="0.163.0")
    new = _fake(tmp_path, "new", version="0.164.0", login_status=_LOGGED_OUT)
    docs = tmp_path / "docs"
    _commit_capture(docs, "0.163.0", _exec_help(old))
    assert compat.main(_compare(old, new, docs)) == 0, capsys.readouterr().out


def test_an_unreadable_new_exec_help_stops_before_any_probe(pair, capsys, tmp_path):
    old, _new, docs, log = pair
    new = _fake(tmp_path, "broken", version="0.164.0", exec_help_exit=1, log=str(log))
    assert compat.main(_compare(old, new, docs)) == 2
    out = capsys.readouterr().out
    assert "STOPPED: the new binary's exec --help could not be read" in out
    assert _exec_runs(_log(log)) == []
