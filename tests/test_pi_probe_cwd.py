"""pi runs `runMigrations(cwd)` before it handles `--help` or `--list-models`, renaming a
project's `.pi/commands/` to `.pi/prompts/` when only the former exists. A free probe must
never do that to whatever directory the server happens to run in, so every probe spawns pi
from amicus's own state directory."""

from __future__ import annotations

import json
import os
from pathlib import Path

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


def _unwritable_state(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, so nothing can be created beneath it")
    return pi_config.PiConfig(
        bin_override=None,
        model=None,
        reasoning_effort=None,
        supported_versions=None,
        state_dir=str(blocker / "state"),
        warnings=(),
        errors=(),
    )


def test_an_unwritable_state_dir_falls_back_to_a_private_mkdtemp_directory(tmp_path, monkeypatch):
    import tempfile

    monkeypatch.setattr(pi_config, "_FALLBACK_PROBE_DIRS", [])
    cfg = _unwritable_state(tmp_path)
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.setattr(tempfile, "tempdir", None)
    got = pi_config.probe_cwd(cfg)
    assert got is not None and Path(got).is_dir()
    assert Path(got).name.startswith("amicus-pi-probe-")
    assert os.path.realpath(got) != os.path.realpath(Path.cwd())
    assert os.path.realpath(got) != os.path.realpath(tempfile.gettempdir())
    assert pi_config.probe_cwd(cfg) == got  # reused, not one directory per probe


def test_no_private_directory_means_no_probe_and_no_spawn_in_the_server_cwd(tmp_path, monkeypatch):
    import tempfile

    from amicus.backends.pi.binary import PiBinary
    from amicus.backends.pi.models import PiModels
    from amicus.backends.pi.status import PiStatus
    from amicus.sdk.conventions.preflight import HelpProbe
    from amicus.sdk.core.runtime import CommandRun

    monkeypatch.setattr(pi_config, "_FALLBACK_PROBE_DIRS", [])
    cfg = _unwritable_state(tmp_path)
    monkeypatch.chdir(tmp_path)

    def broken(*args, **kwargs):
        raise OSError("no temp")

    monkeypatch.setattr(tempfile, "mkdtemp", broken)
    spawns: list[tuple[list[str], object]] = []

    def record(cmd, timeout_seconds, **kwargs):
        spawns.append((list(cmd), kwargs.get("cwd")))
        return CommandRun("", "", 0, 1, False)

    monkeypatch.setattr(runtime, "run_sync_capture", record)
    assert pi_config.probe_cwd(cfg) is None
    binary = PiBinary(cfg)
    help_probe = HelpProbe(
        help_argv=("/PI", *contract.HELP_ARGS), probe_cwd=lambda: pi_config.probe_cwd(cfg)
    )
    assert help_probe.flag_support(force=True).help_parsed is False
    assert PiModels(cfg, binary).read(force=True).source == "none"
    assert PiModels(cfg, binary).lookup(MODEL) == "unreadable"
    assert PiStatus(cfg, binary, help_probe).probe().installed is False
    assert [s for s in spawns if s[1] is None or s[1] == str(Path.cwd())] == []
    assert spawns == []


def test_the_temp_root_being_the_server_cwd_is_refused(tmp_path, monkeypatch):
    import tempfile

    monkeypatch.setattr(pi_config, "_FALLBACK_PROBE_DIRS", [])
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(Path.cwd()))
    assert pi_config.probe_cwd(_unwritable_state(tmp_path)) is None
    assert list(tmp_path.glob("amicus-pi-probe-*")) == []


# --- a probe directory that is not a private, real directory is never used ------------------


def _state_with_symlinked_probe_dir(tmp_path):
    """`<state>/pi-probe-cwd` planted as a symlink to a workspace holding `.pi/commands/`."""
    ws = _workspace(tmp_path)
    state = tmp_path / "state"
    state.mkdir()
    (state / pi_config.PROBE_CWD_DIRNAME).symlink_to(ws, target_is_directory=True)
    return ws, state


def test_a_symlinked_probe_dir_is_refused_for_the_private_fallback(tmp_path, monkeypatch):
    import tempfile

    monkeypatch.setattr(pi_config, "_FALLBACK_PROBE_DIRS", [])
    monkeypatch.setenv("TMPDIR", str(tmp_path / "tmp"))
    (tmp_path / "tmp").mkdir()
    monkeypatch.setattr(tempfile, "tempdir", None)
    ws, state = _state_with_symlinked_probe_dir(tmp_path)
    got = pi_config.probe_cwd(pi_config.load_config({"AMICUS_STATE_DIR": str(state)}))
    assert got is not None and Path(got).name.startswith("amicus-pi-probe-")
    assert os.path.realpath(got) != os.path.realpath(ws)


def test_a_symlinked_probe_dir_never_lets_a_probe_migrate_the_workspace(
    fake_pi, tmp_path, monkeypatch
):
    monkeypatch.setattr(pi_config, "_FALLBACK_PROBE_DIRS", [])
    ws, state = _state_with_symlinked_probe_dir(tmp_path)
    log = tmp_path / "cwds.jsonl"
    monkeypatch.setenv("FAKE_PI_CWD_FILE", str(log))
    environ = {"AMICUS_PI_BIN": str(fake_pi), "AMICUS_PI_MODEL": MODEL}
    environ["AMICUS_STATE_DIR"] = str(state)
    plugin = pi_pkg.plugin(environ)

    plugin.status.probe()
    plugin.models.read(force=True)
    plugin.models.lookup(MODEL)

    records = _records(log)
    assert {kind for kind, _ in records} == {"--version", "auth", "--help", "--list-models"}
    assert os.path.realpath(ws) not in {os.path.realpath(cwd) for _, cwd in records}
    assert (ws / ".pi" / "commands").is_dir() and not (ws / ".pi" / "prompts").exists()


def test_a_group_or_world_writable_probe_dir_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(pi_config, "_FALLBACK_PROBE_DIRS", [])
    state = tmp_path / "state"
    shared = state / pi_config.PROBE_CWD_DIRNAME
    shared.mkdir(parents=True)
    shared.chmod(0o777)
    got = pi_config.probe_cwd(pi_config.load_config({"AMICUS_STATE_DIR": str(state)}))
    assert got is not None and os.path.realpath(got) != os.path.realpath(shared)


def test_a_probe_dir_owned_by_someone_else_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(pi_config, "_FALLBACK_PROBE_DIRS", [])
    state = tmp_path / "state"
    (state / pi_config.PROBE_CWD_DIRNAME).mkdir(parents=True)
    cfg = pi_config.load_config({"AMICUS_STATE_DIR": str(state)})
    someone_else = os.getuid() + 1
    with monkeypatch.context() as m:  # scoped to the call: pytest itself uses os
        m.setattr(pi_config.os, "getuid", lambda: someone_else)
        got = pi_config.probe_cwd(cfg)
    assert got is not None and Path(got).name.startswith("amicus-pi-probe-")


def test_positive_control_a_private_real_probe_dir_is_used_and_created_0700(tmp_path):
    state = tmp_path / "state"
    cfg = pi_config.load_config({"AMICUS_STATE_DIR": str(state)})
    got = pi_config.probe_cwd(cfg)
    expected = state / pi_config.PROBE_CWD_DIRNAME
    assert got == str(expected)
    assert expected.stat().st_mode & 0o777 == 0o700
    assert pi_config.probe_cwd(cfg) == got  # an existing private directory is reused
