"""The _async twins end to end, spend-free: MCP client → twin → keyed/unkeyed detached
worker → real codex plugin → the fake codex executable → a recoverable job record."""

from __future__ import annotations

import asyncio
import json
import subprocess
import time

import pytest
from fastmcp import Client
from jsonschema import Draft202012Validator

from amicus import config, server
from amicus.jobs import lifecycle
from amicus.registry import BackendRegistry


@pytest.fixture
def app(tmp_path, fake_codex, monkeypatch):
    monkeypatch.setenv("AMICUS_CODEX_BIN", str(fake_codex))
    monkeypatch.setenv("AMICUS_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("FAKE_CODEX_ARGV_FILE", str(tmp_path / "argv.jsonl"))
    monkeypatch.setenv("FAKE_CODEX_STDIN_FILE", str(tmp_path / "prompt.txt"))
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
def store(app):
    return lifecycle.job_store(server.state_of(app).settings)


def _argv_lines(tmp_path):
    p = tmp_path / "argv.jsonl"
    return p.read_text().splitlines() if p.exists() else []


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
    return r


async def _wait_done(store, cwd, job_id, timeout=15.0):
    deadline = time.monotonic() + timeout
    while True:
        rec = store.status(str(cwd), job_id)
        assert rec is not None, "record vanished"
        if rec["status"] != "running":
            return rec
        assert time.monotonic() < deadline, "job did not finish"
        await asyncio.sleep(0.05)


async def test_consult_async_returns_a_handle_and_the_job_completes(app, store, tmp_path):
    async with Client(app) as c:
        res = await c.call_tool(
            "amicus_consult_async",
            {"backend": "codex", "question": "why?", "workspace_root": str(tmp_path)},
        )
        tool = next(t for t in await c.list_tools() if t.name == "amicus_consult_async")
    body = res.structured_content
    Draft202012Validator(tool.output_schema).validate(body)
    assert res.is_error is False and body["ok"] is True and body["status"] == "running"
    assert body["backend"] == "codex" and body["kind"] == "consult"
    assert body["deadline_seconds"] == 1800 and body["meta"]["timeout_seconds"] == 1800
    assert body["meta"]["job_id"] == body["job_id"] and body["task_id"] is None
    assert body["follow_up"]["arguments"] == {
        "job_id": body["job_id"],
        "workspace_root": str(tmp_path),
    }
    rec = await _wait_done(store, tmp_path, body["job_id"])
    assert rec["status"] == "done" and rec["result_ok"] is True
    assert rec["extra"] == {"result_format": 5, "backend": "codex", "tool": "amicus_consult_async"}
    _rec, payload = store.result_payload(str(tmp_path), body["job_id"])
    assert payload["ok"] is True and payload["summary"] == "Looks fine"
    assert "why?" in (tmp_path / "prompt.txt").read_text()
    spec_on_disk = json.loads(
        (store._job_dir(str(tmp_path), body["job_id"]) / "spec.json").read_text()
    )
    assert "why?" not in json.dumps(spec_on_disk) and spec_on_disk["timeout_seconds"] == 1800


async def test_keyed_consult_async_replays_and_conflicts(app, store, tmp_path):
    args = {
        "backend": "codex",
        "question": "why?",
        "workspace_root": str(tmp_path),
        "idempotency_key": "abc",
    }
    async with Client(app) as c:
        first = (await c.call_tool("amicus_consult_async", args)).structured_content
        await _wait_done(store, tmp_path, first["job_id"])
        again = (await c.call_tool("amicus_consult_async", args)).structured_content
        other = await c.call_tool(
            "amicus_consult_async", {**args, "question": "why not?"}, raise_on_error=False
        )
    assert first["meta"]["idempotency_replayed"] is None  # a handle keeps null meta keys
    assert again["ok"] is True and again["job_id"] == first["job_id"]
    assert again["meta"]["idempotency_replayed"] is True and again["status"] == "done"
    assert other.is_error and other.structured_content["error"]["code"] == "idempotency_conflict"
    assert other.structured_content["error"]["repair"]["tool"] == "amicus_consult_async"
    assert len(_argv_lines(tmp_path)) == 1


async def test_review_and_delegate_async_run_in_the_background(
    app, store, repo, tmp_path, monkeypatch
):
    (repo / "a.py").write_text("x = 2\n")
    async with Client(app) as c:
        rev = (
            await c.call_tool(
                "amicus_review_changes_async",
                {"backend": "codex", "workspace_root": str(repo), "focus": "locking"},
            )
        ).structured_content
        # Set only now: review runs directly against `repo` (DirectSite), so a write here
        # would land in the real repo; delegate runs in its own throwaway worktree.
        monkeypatch.setenv("FAKE_CODEX_WRITE", "b.py")
        dele = (
            await c.call_tool(
                "amicus_delegate_async",
                {"backend": "codex", "task": "add b", "workspace_root": str(repo)},
            )
        ).structured_content
    assert rev["ok"] is True and rev["kind"] == "review_changes"
    assert dele["ok"] is True and dele["kind"] == "delegate"
    rec = await _wait_done(store, repo, rev["job_id"])
    _r, payload = store.result_payload(str(repo), rev["job_id"])
    # A stored result's `tool` is the result KIND's sync name (the models pin it as a
    # Literal); the twin that started the job is on the record's extra.tool.
    assert rec["result_ok"] is True and payload["tool"] == "amicus_review_changes"
    assert rec["extra"]["tool"] == "amicus_review_changes_async"
    assert payload["review_status"] == "completed"
    rec = await _wait_done(store, repo, dele["job_id"])
    _r, payload = store.result_payload(str(repo), dele["job_id"])
    assert rec["result_ok"] is True and "b.py" in (payload["diff"] or "")
    assert not (repo / "b.py").exists()


async def test_async_pre_spend_refusals_never_spawn(app, tmp_path):
    async with Client(app) as c:
        blank = await c.call_tool(
            "amicus_consult_async",
            {"backend": "codex", "question": "  ", "workspace_root": str(tmp_path)},
            raise_on_error=False,
        )
        opts = await c.call_tool(
            "amicus_review_changes_async",
            {
                "backend": "codex",
                "workspace_root": str(tmp_path),
                "backend_options": {"access": "readonly"},
            },
            raise_on_error=False,
        )
        norepo = await c.call_tool(
            "amicus_delegate_async",
            {"backend": "codex", "task": "t", "workspace_root": str(tmp_path)},
            raise_on_error=False,
        )
        claude = await c.call_tool(
            "amicus_consult_async",
            {"backend": "claude", "question": "q", "workspace_root": str(tmp_path)},
            raise_on_error=False,
        )
        sessionless = await c.call_tool(
            "amicus_consult_async", {"backend": "codex", "question": "q"}, raise_on_error=False
        )
    assert blank.structured_content["error"]["code"] == "invalid_arguments"
    assert opts.structured_content["error"]["code"] == "invalid_arguments"
    assert norepo.structured_content["error"]["code"] == "not_a_git_repo"
    body = claude.structured_content
    assert body["ok"] is True and body["backend"] == "claude" and body["job_id"]
    assert sessionless.structured_content["error"]["code"] == "invalid_workspace_root"
    assert _argv_lines(tmp_path) == []
