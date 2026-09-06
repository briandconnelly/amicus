"""The five amicus_job_* tools end to end through the fake codex: status, result, consume,
cancel, list, the filters, the task-id echo, and the workspace and not-found envelopes."""

from __future__ import annotations

import asyncio
import time

import pytest
from fastmcp import Client
from jsonschema import Draft202012Validator
from pontonier.core.jobs import JobStore

from amicus import config, server
from amicus.jobs import lifecycle, lookup
from amicus.registry import BackendRegistry


@pytest.fixture
def app(tmp_path, fake_codex, monkeypatch):
    monkeypatch.setenv("AMICUS_CODEX_BIN", str(fake_codex))
    monkeypatch.setenv("AMICUS_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("FAKE_CODEX_ARGV_FILE", str(tmp_path / "argv.jsonl"))
    monkeypatch.setenv("AMICUS_HOST_NAME", "TestHost")
    for key in (
        "FAKE_CODEX_EXIT",
        "FAKE_CODEX_STDERR",
        "FAKE_CODEX_ANSWER",
        "FAKE_CODEX_WRITE",
        "FAKE_CODEX_EVENTS",
        "FAKE_CODEX_SLEEP",
    ):
        monkeypatch.delenv(key, raising=False)
    settings = config.settings()
    return server.create_app(
        settings, BackendRegistry.load(settings.enabled_backends, entry_points=())
    )


@pytest.fixture
def settings(app):
    return server.state_of(app).settings


@pytest.fixture
def store(settings):
    return lifecycle.job_store(settings)


async def _schemas(c):
    return {t.name: Draft202012Validator(t.output_schema) for t in await c.list_tools()}


async def _start(c, tmp_path, **extra):
    body = (
        await c.call_tool(
            "amicus_consult_async",
            {"backend": "codex", "question": "why?", "workspace_root": str(tmp_path), **extra},
        )
    ).structured_content
    assert body["ok"] is True
    return body["job_id"]


async def _wait_done(store, cwd, job_id, timeout=15.0):
    deadline = time.monotonic() + timeout
    while store.status(str(cwd), job_id)["status"] == "running":
        assert time.monotonic() < deadline
        await asyncio.sleep(0.05)


async def test_status_result_and_consume_lifecycle(app, store, tmp_path):
    ws = {"workspace_root": str(tmp_path)}
    async with Client(app) as c:
        schemas = await _schemas(c)
        job_id = await _start(c, tmp_path)
        status = (
            await c.call_tool("amicus_job_status", {"job_id": job_id, **ws})
        ).structured_content
        schemas["amicus_job_status"].validate(status)
        assert status["ok"] is True and status["backend"] == "codex" and status["kind"] == "consult"
        assert status["status"] in ("running", "done") and status["task_id"] is None
        assert (
            status["workspace"]["cwd"] == str(tmp_path)
            and status["workspace"]["workspace_source"] == "param"
        )
        early = await c.call_tool(
            "amicus_job_result", {"job_id": job_id, **ws}, raise_on_error=False
        )
        if early.is_error:  # the fake finishes in milliseconds; either branch is legitimate
            err = early.structured_content["error"]
            assert err["code"] == "job_running" and err["retry_after_ms"] >= 1000
            assert err["repair"]["arguments"] == {"job_id": job_id, "workspace_root": str(tmp_path)}
            assert early.structured_content["meta"]["job_kind"] == "consult"
        await _wait_done(store, tmp_path, job_id)
        done = (await c.call_tool("amicus_job_status", {"job_id": job_id, **ws})).structured_content
        assert (
            done["status"] == "done"
            and done["result_available"] is True
            and done["result_ok"] is True
        )
        assert done["poll_after_ms"] is None and done["expires_at"]
        res = await c.call_tool("amicus_job_result", {"job_id": job_id, **ws})
        body = res.structured_content
        schemas["amicus_job_result"].validate(body)
        assert res.is_error is False and body["ok"] is True and body["tool"] == "amicus_consult"
        assert body["summary"] == "Looks fine" and body["raw_response"]["text"] is None
        assert body["meta"]["job_id"] == job_id and "idempotency_replayed" not in body["meta"]
        full = (
            await c.call_tool("amicus_job_result", {"job_id": job_id, "detail": "full", **ws})
        ).structured_content
        assert full["raw_response"]["text"]
        again = (
            await c.call_tool("amicus_job_result", {"job_id": job_id, **ws})
        ).structured_content
        assert again["ok"] is True, "a plain read retains the record"
        consumed = (
            await c.call_tool("amicus_job_consume_result", {"job_id": job_id, **ws})
        ).structured_content
        assert consumed["ok"] is True and consumed["summary"] == "Looks fine"
        gone = await c.call_tool(
            "amicus_job_result", {"job_id": job_id, **ws}, raise_on_error=False
        )
        assert gone.is_error and gone.structured_content["error"]["code"] == "job_not_found"
        assert gone.structured_content["error"]["repair"]["arguments"] == ws
        twice = await c.call_tool(
            "amicus_job_consume_result", {"job_id": job_id, **ws}, raise_on_error=False
        )
        assert twice.structured_content["error"]["code"] == "job_not_found"


async def test_consume_keeps_a_record_it_could_not_deliver(app, store, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CODEX_EXIT", "7")
    monkeypatch.setenv("FAKE_CODEX_STDERR", "boom")
    ws = {"workspace_root": str(tmp_path)}
    async with Client(app) as c:
        job_id = await _start(c, tmp_path)
        await _wait_done(store, tmp_path, job_id)
        status = (
            await c.call_tool("amicus_job_status", {"job_id": job_id, **ws})
        ).structured_content
        assert status["result_available"] is True and status["result_ok"] is False
        stored = await c.call_tool(
            "amicus_job_consume_result", {"job_id": job_id, **ws}, raise_on_error=False
        )
        assert stored.is_error and stored.structured_content["ok"] is False
        assert stored.structured_content["meta"]["job_id"] == job_id
        assert store.status(str(tmp_path), job_id) is None, "a delivered stored error is consumed"
        # A corrupt payload is described, not delivered, so it survives a consume.
        job2 = await _start(c, tmp_path)
        await _wait_done(store, tmp_path, job2)
        (store._job_dir(str(tmp_path), job2) / "result.json").write_text(
            '{"ok": true, "tool": "x"}'
        )
        corrupt = await c.call_tool(
            "amicus_job_consume_result", {"job_id": job2, **ws}, raise_on_error=False
        )
        assert corrupt.structured_content["error"]["code"] == "internal_error"
        assert store.status(str(tmp_path), job2) is not None


async def test_cancel_running_then_terminal_is_idempotent(app, store, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CODEX_SLEEP", "30")
    # The tools build a fresh JobStore per call, so patch the class default, not `store`.
    monkeypatch.setattr(JobStore, "terminate_grace_seconds", 2.0)
    ws = {"workspace_root": str(tmp_path)}
    async with Client(app) as c:
        schemas = await _schemas(c)
        job_id = await _start(c, tmp_path)
        # The worker takes worker.lock before it reads the spec; wait for that, not for
        # backend events (the fake codex prints its events only after its sleep).
        lock = store._job_dir(str(tmp_path), job_id) / "worker.lock"
        deadline = time.monotonic() + 10
        while not lock.exists() and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        assert lock.exists()
        t0 = time.monotonic()
        cancelled = (
            await c.call_tool("amicus_job_cancel", {"job_id": job_id, **ws})
        ).structured_content
        schemas["amicus_job_cancel"].validate(cancelled)
        assert cancelled["ok"] is True and cancelled["status"] == "cancelled"
        assert cancelled["result_available"] is False and cancelled["cleanup_warnings"] == []
        assert time.monotonic() - t0 < 10
        again = (
            await c.call_tool("amicus_job_cancel", {"job_id": job_id, **ws})
        ).structured_content
        assert again["status"] == "cancelled" and again["elapsed_ms"] == cancelled["elapsed_ms"]
        res = await c.call_tool("amicus_job_result", {"job_id": job_id, **ws}, raise_on_error=False)
        assert res.structured_content["error"]["code"] == "job_cancelled"
        missing = await c.call_tool(
            "amicus_job_cancel", {"job_id": "f" * 32, **ws}, raise_on_error=False
        )
        assert missing.structured_content["error"]["code"] == "job_not_found"


async def test_list_filters_and_the_task_id_lookup(app, store, settings, tmp_path):
    ws = {"workspace_root": str(tmp_path)}
    async with Client(app) as c:
        schemas = await _schemas(c)
        first = await _start(c, tmp_path)
        await _wait_done(store, tmp_path, first)
        second = await _start(c, tmp_path)
        await _wait_done(store, tmp_path, second)
        lookup.task_map(settings).record("task-xyz", first)
        listed = (await c.call_tool("amicus_job_list", ws)).structured_content
        schemas["amicus_job_list"].validate(listed)
        assert [j["job_id"] for j in listed["jobs"]] == [second, first]
        assert listed["truncated"] is False and "truncation_hint" not in listed
        assert listed["jobs"][1]["task_id"] == "task-xyz" and listed["jobs"][0]["task_id"] is None
        assert listed["jobs"][0]["backend"] == "codex" and listed["jobs"][0]["result_ok"] is True
        limited = (await c.call_tool("amicus_job_list", {"limit": 1, **ws})).structured_content
        assert [j["job_id"] for j in limited["jobs"]] == [second] and limited["truncated"] is True
        assert "omit `limit`" in limited["truncation_hint"]
        by_task = (
            await c.call_tool("amicus_job_list", {"task_id": "task-xyz", **ws})
        ).structured_content
        assert [j["job_id"] for j in by_task["jobs"]] == [first]
        no_task = (
            await c.call_tool("amicus_job_list", {"task_id": "nope", **ws})
        ).structured_content
        assert no_task["ok"] is True and no_task["jobs"] == [] and no_task["truncated"] is False
        by_status = (
            await c.call_tool("amicus_job_list", {"status": "running", **ws})
        ).structured_content
        assert by_status["jobs"] == []
        by_backend = (
            await c.call_tool("amicus_job_list", {"backend": "kimi", **ws})
        ).structured_content
        assert by_backend["jobs"] == []
        status = (
            await c.call_tool("amicus_job_status", {"job_id": first, **ws})
        ).structured_content
        assert status["task_id"] == "task-xyz"
        result = (
            await c.call_tool("amicus_job_result", {"job_id": first, **ws})
        ).structured_content
        assert result["meta"]["task_id"] == "task-xyz"


async def test_foreign_and_malformed_records_are_not_found(app, store, tmp_path):
    ws = {"workspace_root": str(tmp_path)}
    async with Client(app) as c:
        job_id = await _start(c, tmp_path)
        await _wait_done(store, tmp_path, job_id)
        meta_path = store._job_dir(str(tmp_path), job_id) / "meta.json"
        meta = meta_path.read_text().replace('"backend": "codex"', '"backend": "Not Ours"')
        meta_path.write_text(meta)
        for tool in (
            "amicus_job_status",
            "amicus_job_result",
            "amicus_job_consume_result",
            "amicus_job_cancel",
        ):
            res = await c.call_tool(tool, {"job_id": job_id, **ws}, raise_on_error=False)
            assert res.structured_content["error"]["code"] == "job_not_found", tool
        listed = (await c.call_tool("amicus_job_list", ws)).structured_content
        assert listed["jobs"] == []
        assert store.status(str(tmp_path), job_id) is not None, "never deleted, only hidden"


async def test_workspace_rules_apply_to_every_job_tool(app, tmp_path):
    async with Client(app) as c:
        for tool, args in (
            ("amicus_job_status", {"job_id": "a" * 32}),
            ("amicus_job_result", {"job_id": "a" * 32}),
            ("amicus_job_consume_result", {"job_id": "a" * 32}),
            ("amicus_job_cancel", {"job_id": "a" * 32}),
            ("amicus_job_list", {}),
        ):
            res = await c.call_tool(tool, args, raise_on_error=False)
            err = res.structured_content["error"]
            assert (
                err["code"] == "invalid_workspace_root"
                and err["details"]["field"] == "workspace_root"
            ), tool
            assert res.structured_content["meta"]["roots_source"] in ("not_negotiated", "client")
            res = await c.call_tool(
                tool, {**args, "workspace_root": str(tmp_path)}, raise_on_error=False
            )
            if tool == "amicus_job_list":
                assert res.structured_content["ok"] is True and res.structured_content["jobs"] == []
            else:
                assert res.structured_content["error"]["code"] == "job_not_found", tool
