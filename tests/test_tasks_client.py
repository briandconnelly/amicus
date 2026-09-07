"""In-memory task-client tests (M5 gate): the paid sync tools behind AMICUS_TASKS=1 driven
through fastmcp[tasks] against the real codex plugin and the fake codex executable. Proves
delivery parity, isError on the tasked path, task-map recording and recovery through
amicus_job_list(task_id=...), cancel propagation to the job record, the legacy-era plain
result, the task result window and the redelivery guard."""

from __future__ import annotations

import asyncio
import logging
import subprocess
import time
from datetime import timedelta

import pytest
from fastmcp import Client, FastMCP

from amicus import config, server
from amicus.jobs import lifecycle, lookup
from amicus.registry import BackendRegistry
from amicus.schemas.results import PAID_TOOLS

pytest.importorskip("fastmcp_tasks")
from fastmcp_tasks import TasksExtension, call_tool_task

TASKS = "io.modelcontextprotocol/tasks"


@pytest.fixture
def app(tmp_path, fake_codex, monkeypatch):
    monkeypatch.setenv("AMICUS_CODEX_BIN", str(fake_codex))
    monkeypatch.setenv("AMICUS_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("FAKE_CODEX_ARGV_FILE", str(tmp_path / "argv.jsonl"))
    monkeypatch.setenv("AMICUS_HOST_NAME", "TestHost")
    monkeypatch.setenv("AMICUS_TASKS", "1")
    monkeypatch.setenv("AMICUS_TASKS_BACKEND_URL", "memory://")
    for key in (
        "FAKE_CODEX_EXIT",
        "FAKE_CODEX_STDERR",
        "FAKE_CODEX_ANSWER",
        "FAKE_CODEX_WRITE",
        "FAKE_CODEX_EVENTS",
        "FAKE_CODEX_SLEEP",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(lifecycle, "SYNC_POLL_INTERVAL_S", 0.02)
    settings = config.settings()
    return server.create_app(
        settings, BackendRegistry.load(settings.enabled_backends, entry_points=())
    )


@pytest.fixture
def settings(app):
    return server.state_of(app).settings


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@t.co")
    _git(r, "config", "user.name", "t")
    (r / "a.py").write_text("x = 1\n")
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "init")
    (r / "a.py").write_text("x = 2\n")
    return r


async def _wait(predicate, timeout=15.0):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "condition not met in time"
        await asyncio.sleep(0.05)


async def test_tasked_consult_delivers_the_plain_envelope_plus_task_id(
    app, settings, tmp_path, caplog
):
    args = {"backend": "codex", "question": "why?", "workspace_root": str(tmp_path)}
    with caplog.at_level(logging.DEBUG, logger="amicus.middleware"):
        async with Client(app) as c:
            task = await call_tool_task(c, "amicus_consult", args)
            result = await task.result()
            status = await task.status()
    body = result.structured_content
    assert result.is_error is False and body["ok"] is True and body["summary"] == "Looks fine"
    assert body["meta"]["task_id"] == task.task_id and body["meta"]["job_id"]
    assert status.status == "completed"
    assert lookup.task_map(settings).job_for(task.task_id) == body["meta"]["job_id"]
    assert any(
        "tools/call amicus_consult: " in r.getMessage()
        and "tasks_negotiated=True" in r.getMessage()
        for r in caplog.records
    )


async def test_tasked_failure_is_an_error_result_with_the_task_id(app, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CODEX_EXIT", "1")
    monkeypatch.setenv("FAKE_CODEX_STDERR", "Error: not logged in; run `codex login`")
    args = {"backend": "codex", "question": "q", "workspace_root": str(tmp_path)}
    async with Client(app) as c:
        task = await call_tool_task(c, "amicus_consult", args, raise_on_error=False)
        result = await task.result()
    assert result.is_error is True  # the M0 finding, closed by the guard
    body = result.structured_content
    assert body["error"]["code"] == "backend_auth_required"
    assert body["meta"]["task_id"] == task.task_id and body["meta"]["job_id"]


async def test_zero_spend_refusal_is_an_error_result_and_records_no_task(app, settings, tmp_path):
    async with Client(app) as c:
        task = await call_tool_task(
            c, "amicus_consult", {"backend": "codex", "question": "q"}, raise_on_error=False
        )
        result = await task.result()
    assert result.is_error is True
    assert result.structured_content["error"]["code"] == "invalid_workspace_root"
    assert lookup.task_map(settings).entries() == {}
    assert not (tmp_path / "argv.jsonl").exists()


async def test_job_list_recovers_the_job_behind_a_task(app, tmp_path):
    ws = {"workspace_root": str(tmp_path)}
    async with Client(app) as c:
        task = await call_tool_task(
            c, "amicus_consult", {"backend": "codex", "question": "q", **ws}
        )
        body = (await task.result()).structured_content
        job_id = body["meta"]["job_id"]
        listed = (
            await c.call_tool("amicus_job_list", {"task_id": task.task_id, **ws})
        ).structured_content
        assert [j["job_id"] for j in listed["jobs"]] == [job_id]
        assert listed["jobs"][0]["task_id"] == task.task_id
        status = (
            await c.call_tool("amicus_job_status", {"job_id": job_id, **ws})
        ).structured_content
        assert status["task_id"] == task.task_id
        stored = (
            await c.call_tool("amicus_job_result", {"job_id": job_id, **ws})
        ).structured_content
        assert stored["ok"] is True and stored["meta"]["task_id"] == task.task_id
        none = (await c.call_tool("amicus_job_list", {"task_id": "nope", **ws})).structured_content
        assert none["jobs"] == []


async def test_cancelling_a_task_cancels_its_job(app, settings, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CODEX_SLEEP", "30")
    store = lifecycle.job_store(settings)
    task_map = lookup.task_map(settings)
    ws = {"workspace_root": str(tmp_path)}
    async with Client(app) as c:
        task = await call_tool_task(
            c, "amicus_consult", {"backend": "codex", "question": "q", **ws}, raise_on_error=False
        )
        await _wait(lambda: task_map.job_for(task.task_id) is not None)
        job_id = task_map.job_for(task.task_id)
        assert store.status(str(tmp_path), job_id)["status"] == "running"
        await task.cancel()
        await _wait(lambda: store.status(str(tmp_path), job_id)["status"] == "cancelled")
        final = await task.status()
        assert final.status == "cancelled"
        listed = (
            await c.call_tool("amicus_job_list", {"task_id": task.task_id, **ws})
        ).structured_content
        assert listed["jobs"][0]["status"] == "cancelled"


async def test_tasked_review_runs_the_second_verb(app, repo):
    async with Client(app) as c:
        task = await call_tool_task(
            c,
            "amicus_review_changes",
            {"backend": "codex", "workspace_root": str(repo), "scope": "working_tree"},
        )
        result = await task.result()
    body = result.structured_content
    assert result.is_error is False and body["ok"] is True
    assert body["review_status"] == "completed" and body["meta"]["task_id"] == task.task_id


async def test_all_four_paid_sync_tools_are_task_tools_and_nothing_else_is(app):
    for name in PAID_TOOLS:
        assert (await app.get_tool(name)).task_config.supports_tasks(), name
        assert not (await app.get_tool(f"{name}_async")).task_config.supports_tasks(), name
    for name in ("amicus_backends", "amicus_capabilities", "amicus_dry_run", "amicus_job_list"):
        assert not (await app.get_tool(name)).task_config.supports_tasks(), name


async def test_legacy_era_client_gets_a_plain_result(app, tmp_path, caplog):
    with caplog.at_level(logging.DEBUG, logger="amicus.middleware"):
        async with Client(app, mode="legacy") as c:
            res = await c.call_tool(
                "amicus_consult",
                {"backend": "codex", "question": "q", "workspace_root": str(tmp_path)},
            )
    body = res.structured_content
    assert body["ok"] is True and "task_id" not in body["meta"]
    assert any("tasks_negotiated=False" in r.getMessage() for r in caplog.records)


async def test_task_result_window_is_docket_execution_ttl(app, settings, tmp_path):
    async with Client(app) as c:
        task = await call_tool_task(
            c,
            "amicus_consult",
            {"backend": "codex", "question": "q", "workspace_root": str(tmp_path)},
        )
        await task.result()
    # Docket's execution_ttl default; TasksExtension 4.0.x cannot set it. The job record
    # outlives the task result (AMICUS_JOB_TTL), which the capability summary says.
    assert task.create_result.ttl_ms == 15 * 60 * 1000
    assert settings.job_ttl_seconds * 1000 > task.create_result.ttl_ms


def test_redelivery_timeout_is_the_sync_deadline_plus_grace(app, settings):
    ext = app._extensions[TASKS]
    assert ext.docket_settings.redelivery_timeout == timedelta(
        seconds=settings.job_max_seconds + lifecycle.SYNC_AWAIT_GRACE_S
    )


async def test_a_live_task_outlasting_redelivery_timeout_runs_once():
    """Docket renews a running task's lease, so a run longer than redelivery_timeout is not
    re-executed (which would be double spend). If this ever fails, lease renewal regressed:
    keep the server-side redelivery_timeout override and record the finding in ADR 0011."""
    scratch = FastMCP(name="scratch")
    scratch.add_extension(
        TasksExtension(url="memory://", redelivery_timeout=timedelta(milliseconds=300))
    )
    runs: list[float] = []

    @scratch.tool(name="slow", task=True)
    async def slow() -> dict:
        runs.append(time.monotonic())
        await asyncio.sleep(1.2)
        return {"ok": True}

    async with Client(scratch) as c:
        task = await call_tool_task(c, "slow", {})
        result = await task.result()
    assert result.structured_content == {"ok": True} and len(runs) == 1
