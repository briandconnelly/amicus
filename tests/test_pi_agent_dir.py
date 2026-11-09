"""PI_CODING_AGENT_DIR is pi's own variable, and pi 1.5.0 resolves a relative value against
its cwd (`getAgentDir` in config.js). The free probes run from amicus's probe directory and a
paid run from the workspace, so a relative value would make them read different auth.json and
models.json: it is refused pre-spend, reported on amicus_backends, and no probe runs with it.
pi expands a leading `~` or `~/` against the home directory, which no cwd changes."""

from __future__ import annotations

import pytest
from tests.support import pifixtures as pf

from amicus.backends import pi as pi_pkg
from amicus.backends.pi import cli
from amicus.backends.pi import config as pi_config
from amicus.sdk.backend.protocol import RunRequest
from amicus.sdk.core import runtime

VAR = "PI_CODING_AGENT_DIR"
RELATIVE = ("agentdir", "./agentdir", "../up/agentdir", "~someone/agent")


def _req(**kw) -> RunRequest:
    base = dict(
        kind="consult", prompt="why?", cwd="/repo/some/where", timeout_seconds=60, model=pf.MODEL
    )
    base.update(kw)
    return RunRequest(**base)


@pytest.fixture
def spawns(monkeypatch):
    seen: list = []

    def record(cmd, timeout_seconds, **kwargs):  # pragma: no cover - reaching it fails a test
        seen.append(list(cmd))
        raise AssertionError(f"unexpected spawn: {cmd!r}")

    monkeypatch.setattr(runtime, "run_sync_capture", record)
    return seen


@pytest.mark.parametrize("value", RELATIVE)
def test_a_relative_agent_dir_is_an_error_that_never_echoes_the_value(value):
    error = pi_config.agent_dir_error({VAR: value})
    assert error is not None and VAR in error and value not in error
    assert pi_config.load_config({VAR: value}).agent_dir_error == error


@pytest.mark.parametrize("value", ["/abs/agent", "~", "~/.pi/agent", ""])
def test_an_absolute_home_relative_or_empty_agent_dir_is_accepted(value):
    assert pi_config.agent_dir_error({VAR: value}) is None
    assert pi_config.agent_dir_error({}) is None


@pytest.mark.parametrize("value", RELATIVE)
def test_a_relative_agent_dir_is_refused_pre_spend_with_no_probe(value):
    calls: list = []
    backend = pf.make_backend({VAR: value}, calls=calls)
    failure = backend.validate_request(_req())
    assert failure is not None and failure.code == "user_config_rejected"
    assert VAR in failure.detail and value not in failure.detail
    assert "No model call was made" in failure.detail
    assert failure.repair is not None and failure.repair.next_step == "correct_config"
    assert calls == []  # neither `pi auth check` nor the catalog was asked


def test_a_relative_agent_dir_is_refused_by_prepare_too():
    import asyncio

    backend = pf.make_backend({VAR: "agentdir"})

    async def go():
        async with backend.prepare(_req()):
            pass  # pragma: no cover - prepare must refuse

    with pytest.raises(ValueError, match=VAR):
        asyncio.run(go())


def test_an_absolute_agent_dir_passes_validation_and_reaches_the_run_unchanged(monkeypatch):
    calls: list = []
    backend = pf.make_backend({VAR: "/abs/agent"}, calls=calls)
    assert backend.validate_request(_req()) is None
    assert calls == [("auth", "/PI", pf.MODEL), ("lookup", pf.MODEL)]
    assert cli.build_run_env({VAR: "/abs/agent", "PATH": "/bin"})[VAR] == "/abs/agent"
    assert backend.scrub_env({VAR: "/abs/agent"}, None)[VAR] == "/abs/agent"


def test_a_relative_agent_dir_is_a_status_warning_and_no_probe_spawns(fake_pi, tmp_path, spawns):
    environ = {"AMICUS_PI_BIN": str(fake_pi), "AMICUS_PI_MODEL": pf.MODEL, VAR: "agentdir"}
    environ["AMICUS_STATE_DIR"] = str(tmp_path / "state")
    plugin = pi_pkg.plugin(environ)
    rep = plugin.status.probe()
    assert rep.installed is True  # the binary resolves; nothing was run to ask it
    assert rep.version is None and rep.authenticated is None
    assert sum(VAR in w for w in rep.warnings) == 1
    assert all("agentdir" not in w for w in rep.warnings)
    assert pi_config.probe_cwd(pi_config.load_config(environ)) is None
    assert plugin.models.read(force=True).source == "none"
    assert plugin.models.lookup(pf.MODEL) == "unreadable"
    assert plugin.help_probe.flag_support(force=True).help_parsed is False
    assert plugin.backend.auth_probe() is None
    assert spawns == []


def test_positive_control_an_absolute_agent_dir_still_probes(fake_pi, tmp_path):
    environ = {"AMICUS_PI_BIN": str(fake_pi), "AMICUS_PI_MODEL": pf.MODEL}
    environ[VAR] = str(tmp_path / "agent")
    environ["AMICUS_STATE_DIR"] = str(tmp_path / "state")
    rep = pi_pkg.plugin(environ).status.probe()
    assert rep.installed is True and rep.version is not None
    assert all(VAR not in w for w in rep.warnings)
