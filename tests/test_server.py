"""create_app: capability suppression on both eras, instructions, main()."""

from __future__ import annotations

import pytest
from fastmcp import Client

from amicus import config, server
from amicus.registry import BackendRegistry


def _app():
    return server.create_app(config.settings({}), BackendRegistry({}, {}))


async def test_initialize_does_not_advertise_prompts_or_the_ui_extension():
    async with Client(_app(), mode="legacy") as c:
        caps = c.initialize_result.capabilities
        assert c.initialize_result.instructions == server.CAPABILITY_SUMMARY
    wire = caps.model_dump(by_alias=True, mode="json", exclude_none=True)
    assert "prompts" not in wire and "extensions" not in wire
    assert caps.tools is not None and caps.resources is not None


async def test_discover_does_not_advertise_prompts_or_the_ui_extension():
    async with Client(_app()) as c:
        assert c.protocol_version == "2026-07-28"
        caps = c.server_capabilities
    wire = caps.model_dump(by_alias=True, mode="json", exclude_none=True)
    assert "prompts" not in wire and "extensions" not in wire


async def test_ui_filter_preserves_other_extensions(monkeypatch):
    app = _app()
    original = app._mcp_server.get_capabilities

    def fake(*args, **kwargs):
        caps = original(*args, **kwargs)
        return caps.model_copy(
            update={"extensions": {server.UI_EXTENSION_ID: {}, "io.example/x": {"a": 1}}}
        )

    monkeypatch.setattr(app._mcp_server, "get_capabilities", server._filter_capabilities(fake))
    async with Client(app) as c:
        wire = c.server_capabilities.model_dump(by_alias=True, mode="json", exclude_none=True)
    assert wire["extensions"] == {"io.example/x": {"a": 1}}


def test_state_of_raises_on_an_app_create_app_did_not_build():
    from fastmcp import FastMCP

    with pytest.raises(RuntimeError, match="_amicus_state"):
        server.state_of(FastMCP(name="bare"))


def test_state_is_attached_and_summary_is_rules_then_context():
    app = _app()
    state = server.state_of(app)
    assert state.settings.enabled_backends == ("codex", "kimi", "claude")
    lead = server.CAPABILITY_SUMMARY.split(". ")[0]
    assert "second opinion" in lead
    assert "does not" in server.CAPABILITY_SUMMARY[:400]
    assert server.CAPABILITY_SUMMARY.index("Use amicus_backends") < server.CAPABILITY_SUMMARY.index(
        "Background:"
    )
    assert "isError: true" in server.CAPABILITY_SUMMARY
    assert (
        "completed" in server.CAPABILITY_SUMMARY
        and "delivery statement" in server.CAPABILITY_SUMMARY
    )


def test_create_app_defaults_to_process_settings(clean_env):
    clean_env.setenv("AMICUS_BACKENDS", "codex")
    app = server.create_app()
    assert server.state_of(app).settings.enabled_backends == ("codex",)


def test_tasks_flag_without_the_extension_is_a_config_error(clean_env, monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("fastmcp_tasks"):
            raise ImportError("no fastmcp_tasks")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    app = server.create_app(config.settings({"AMICUS_TASKS": "1"}), BackendRegistry({}, {}))
    state = server.state_of(app)
    assert state.tasks_active is False
    assert any("fastmcp[tasks]" in e for e in state.config_errors)


def test_main_handles_disconnects_and_crashes(monkeypatch, clean_env):
    calls = []

    class FakeApp:
        def __init__(self, exc):
            self.exc = exc

        def run(self):
            calls.append("run")
            if self.exc:
                raise self.exc

    monkeypatch.setattr(server, "create_app", lambda *a, **k: FakeApp(KeyboardInterrupt()))
    server.main()
    monkeypatch.setattr(server, "create_app", lambda *a, **k: FakeApp(None))
    server.main()
    monkeypatch.setattr(server, "create_app", lambda *a, **k: FakeApp(RuntimeError("boom")))
    with pytest.raises(SystemExit) as exc:
        server.main()
    assert exc.value.code == 1
    monkeypatch.setattr(server, "create_app", lambda *a, **k: FakeApp(SystemExit(3)))
    with pytest.raises(SystemExit) as exc:
        server.main()
    assert exc.value.code == 3
    assert calls == ["run"] * 4


def test_main_refuses_non_posix(monkeypatch, clean_env):
    with pytest.raises(SystemExit):
        server._enforce_posix_platform("nt")
    server._enforce_posix_platform("posix")
    clean_env.setenv("AMICUS_ALLOW_UNSUPPORTED_PLATFORM", "1")
    server._enforce_posix_platform("nt")  # downgraded to a warning
