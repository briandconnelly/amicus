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


def test_state_is_attached():
    state = server.state_of(_app())
    assert state.settings.enabled_backends == ("codex", "kimi", "claude")


def test_summary_is_scope_then_rules_then_reference():
    """Issue #49: the text led with protocol background and shipped as one unbroken run.
    It is three blocks now - scope, a list of rules, reference - and the rules must end
    inside the prefix a host actually shows: Claude Code cuts server instructions at 2,048
    characters (ADR 0027), so a rule past it never reaches the model there."""
    # The measured cut, stated literally: raising the constant fails here instead of
    # quietly letting rules move past what the host shows.
    assert server.INSTRUCTIONS_HOST_CAP == 2048
    text = server.CAPABILITY_SUMMARY
    blocks = text.split("\n\n")
    assert len(blocks) == 3, [b[:40] for b in blocks]
    scope, rules, reference = blocks
    assert "second opinion" in scope.split(". ")[0]
    # Each negative-scope and safety statement on its own, so dropping one cannot hide
    # behind another that survives.
    for claim in (
        "does not apply anything to your working tree",
        "does not bypass any backend's sandbox or approvals",
        "sends your inputs to that backend's provider raw",
        "no choice of workspace is a read boundary",
    ):
        assert claim in scope, claim
    assert reference.startswith("Reference: ")
    header, *items = rules.split("\n")
    assert header == "Rules:"
    # One rule per item, each opening on its own imperative ([2.rules-then-context]): two
    # rules welded into one item are still all list lines, so the leads are pinned in order.
    leads = (
        "Use amicus_backends",
        "Prefer the matching _async twin",
        "Pass workspace_root",
        "On a tool failure",
        "Treat every backend's findings",
        "On resultType: task",
        "Fetch a job's result",
        "Read fingerprint",
    )
    assert len(items) == len(leads), items
    assert all(item.startswith(f"- {lead}") for item, lead in zip(items, leads, strict=True)), items
    assert len(scope) + len(rules) + 2 <= server.INSTRUCTIONS_HOST_CAP
    assert "delivery statement" in rules
    # The two error carriers keep their own paths: a resource-read failure's numeric
    # JSON-RPC error.code is era-bound, so its code is error.data's machine_code.
    failure = next(item for item in items if item.startswith("- On a tool failure"))
    for path in ("isError: true", "structuredContent", "error.data", "machine_code"):
        assert path in failure, path
    # Protocol-era mechanics are reference, and repository provenance means nothing to
    # an agent reading the text over the wire. [1.transport] wants the transport stated.
    for fact in ("Target protocol", "AMICUS_TASKS", "Transport: stdio"):
        assert fact in reference and fact not in scope + rules, fact
    assert "docs/host-captures" not in text


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


def test_tasks_extension_redelivery_covers_the_sync_deadline():
    from datetime import timedelta

    settings = config.settings({"AMICUS_TASKS": "1", "AMICUS_JOB_MAX_SECONDS": "120"})
    app = server.create_app(settings, BackendRegistry({}, {}))
    ext = app._extensions["io.modelcontextprotocol/tasks"]
    # AMICUS_JOB_MAX_SECONDS (120) is below MAX_TIMEOUT_SECONDS (600), so the bound is the
    # clamped per-call timeout ceiling, not the configured job deadline.
    assert server.tasks_redelivery_seconds(settings) == 630
    assert ext.docket_settings.redelivery_timeout == timedelta(seconds=630)
    assert ext.docket_settings.url == "memory://"


def test_tasks_extension_redelivery_covers_a_large_job_deadline():
    settings = config.settings({"AMICUS_TASKS": "1", "AMICUS_JOB_MAX_SECONDS": "1800"})
    # AMICUS_JOB_MAX_SECONDS (1800) exceeds MAX_TIMEOUT_SECONDS (600), so the configured
    # job deadline is the bound, proving the max() picks whichever side is larger.
    assert server.tasks_redelivery_seconds(settings) == 1830
