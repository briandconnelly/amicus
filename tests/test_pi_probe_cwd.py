"""pi runs `runMigrations(cwd)` before it handles `--help` or `--list-models`, renaming a
project's `.pi/commands/` to `.pi/prompts/` when only the former exists. A free probe must
never do that to whatever directory the server happens to run in, so every probe spawns pi
from amicus's own state directory."""

from __future__ import annotations

import json
import os

from amicus.backends import pi as pi_pkg
from amicus.backends.pi import config as pi_config
from amicus.backends.pi import contract
from amicus.sdk.core import runtime

MODEL = "openrouter/moonshotai/kimi-k3"


def _records(path) -> list[tuple[str, str]]:
    return [tuple(json.loads(line)) for line in path.read_text().splitlines()]


def _workspace(tmp_path):
    ws = tmp_path / "ws"
    (ws / ".pi" / "commands").mkdir(parents=True)
    return ws


def test_every_free_probe_runs_from_the_state_dir_not_the_server_cwd(
    fake_pi, tmp_path, monkeypatch
):
    ws = _workspace(tmp_path)
    state = tmp_path / "state"
    log = tmp_path / "cwds.jsonl"
    monkeypatch.setenv("FAKE_PI_CWD_FILE", str(log))
    monkeypatch.chdir(ws)
    environ = {"AMICUS_PI_BIN": str(fake_pi), "AMICUS_PI_MODEL": MODEL}
    environ["AMICUS_STATE_DIR"] = str(state)
    plugin = pi_pkg.plugin(environ)

    plugin.status.probe()  # --version, auth check, --help
    plugin.models.read(force=True)  # --list-models
    plugin.models.lookup(MODEL)  # --list-models <model>
    assert plugin.backend.auth_probe() is True  # auth check through the adapter's seam

    records = _records(log)
    assert {kind for kind, _ in records} == {"--version", "auth", "--help", "--list-models"}
    expected = os.path.realpath(state / pi_config.PROBE_CWD_DIRNAME)
    assert {os.path.realpath(cwd) for _, cwd in records} == {expected}
    assert (ws / ".pi" / "commands").is_dir() and not (ws / ".pi" / "prompts").exists()


def test_a_removed_probe_dir_is_recreated_rather_than_reported_as_a_missing_pi(
    fake_pi, tmp_path, monkeypatch
):
    state = tmp_path / "state"
    environ = {"AMICUS_PI_BIN": str(fake_pi), "AMICUS_PI_MODEL": MODEL}
    environ["AMICUS_STATE_DIR"] = str(state)
    plugin = pi_pkg.plugin(environ)
    probe_dir = state / pi_config.PROBE_CWD_DIRNAME
    if probe_dir.exists():
        probe_dir.rmdir()
    assert plugin.help_probe.flag_support(force=True).help_parsed is True
    assert plugin.status.probe().installed is True


def test_positive_control_the_fake_records_and_migrates_a_probe_run_in_a_workspace(
    fake_pi, tmp_path, monkeypatch
):
    """Without the neutral cwd, the same probe records the workspace and migrates it: the
    instrument above can see the failure it guards against."""
    ws = _workspace(tmp_path)
    log = tmp_path / "cwds.jsonl"
    monkeypatch.setenv("FAKE_PI_CWD_FILE", str(log))
    run = runtime.run_sync_capture([str(fake_pi), *contract.HELP_ARGS], 10, cwd=str(ws))
    assert run.exit_code == 0
    assert [(k, os.path.realpath(c)) for k, c in _records(log)] == [
        ("--help", os.path.realpath(ws))
    ]
    assert (ws / ".pi" / "prompts").is_dir() and not (ws / ".pi" / "commands").exists()
