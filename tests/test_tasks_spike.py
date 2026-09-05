"""Tasks-extension spike (M0): prove the real `fastmcp[tasks]` extension runs in-process
against this server, that a task-augmented paid call delivers the same envelope, that the
task id is reachable inside the tool (for the task→job map), and record what a legacy-
era client gets. Findings are copied into docs/adr/0004-tasks-and-jobs.md."""

from __future__ import annotations

import pytest
from fastmcp import Client
from tests.support import fakeplugin

from amicus import config, server
from amicus.jobs.taskmap import TaskJobMap
from amicus.registry import BackendRegistry
from amicus.schemas.results import PAID_TOOLS

pytest.importorskip("fastmcp_tasks")
from fastmcp_tasks import call_tool_task
from fastmcp_tasks.context import get_task_context


def _app():
    settings = config.settings({"AMICUS_TASKS": "1", "AMICUS_TASKS_BACKEND_URL": "memory://"})
    reg = BackendRegistry({"codex": fakeplugin.make_plugin("codex")}, {})
    return server.create_app(settings, reg)


async def test_extension_is_advertised_and_capabilities_report_it():
    app = _app()
    assert server.state_of(app).tasks_active is True
    async with Client(app) as c:
        caps = c.server_capabilities.model_dump(by_alias=True, mode="json", exclude_none=True)
        assert "io.modelcontextprotocol/tasks" in caps["extensions"]
        assert "io.modelcontextprotocol/ui" not in caps["extensions"]
        payload = (await c.call_tool("amicus_capabilities", {})).structured_content
    assert payload["tasks"]["enabled"] is True
    assert payload["tasks"]["task_tools"] == list(PAID_TOOLS)


async def test_task_augmented_paid_call_delivers_the_same_envelope():
    app = _app()
    args = {"backend": "codex", "question": "q"}
    async with Client(app) as c:
        plain = await c.call_tool("amicus_consult", args, raise_on_error=False)
        task = await call_tool_task(c, "amicus_consult", args, raise_on_error=False)
        status = await task.status()
        result = await task.result()
    assert plain.structured_content["error"]["code"] == "not_implemented"
    assert result.structured_content["error"]["code"] == "not_implemented"
    # Spike finding: the semantic isError flip does NOT survive task delivery. A
    # task-augmented call is intercepted by TasksExtension before it reaches
    # SemanticErrorMiddleware's call_next (the server returns a CreateTaskResult
    # in place of the tool's ToolResult), and the eventual task result is produced
    # by the Docket worker invoking the tool directly, never re-entering the
    # middleware chain — so `ok: false` in the delivered structured_content is
    # never promoted to `isError: true` for a tasked call. See ADR 0004.
    assert result.is_error is False  # finding: the flip does not survive
    assert task.task_id and task.create_result.ttl_ms is not None
    assert status.status in {"working", "completed"}


async def test_task_id_is_reachable_inside_the_tool_and_persisted(tmp_path):
    app = _app()
    mapping = TaskJobMap(tmp_path / "tasks.json")

    @app.tool(name="spike_probe", task=True)
    async def spike_probe() -> dict:
        info = get_task_context()
        task_id = getattr(info, "task_id", None) if info is not None else None
        if task_id:
            mapping.record(task_id, "job-for-" + task_id)
        return {"ok": True, "task_id": task_id}

    async with Client(app) as c:
        task = await call_tool_task(c, "spike_probe", {})
        result = await task.result()
    seen = result.structured_content["task_id"]
    assert seen == task.task_id
    assert TaskJobMap(tmp_path / "tasks.json").job_for(task.task_id) == "job-for-" + task.task_id


async def test_legacy_era_client_still_gets_a_plain_result():
    app = _app()
    args = {"backend": "codex", "question": "q"}
    async with Client(app, mode="legacy") as c:
        res = await c.call_tool("amicus_consult", args, raise_on_error=False)
    assert res.structured_content["error"]["code"] == "not_implemented"


async def test_free_tools_are_unaffected_by_the_extension():
    async with Client(_app()) as c:
        res = await c.call_tool("amicus_backends", {})
    assert res.structured_content["ok"] is True
