"""The five amicus_job_* tools end to end through the fake codex: status, result, consume,
cancel, list, the filters, the task-id echo, and the workspace and not-found envelopes."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
from pathlib import Path

import pytest
from fastmcp import Client
from jsonschema import Draft202012Validator

from amicus import config, server
from amicus.jobs import delivery, lifecycle, lookup
from amicus.jobs.store import DiscardOutcome, JobStore
from amicus.registry import BackendRegistry


def _make_app(tmp_path, fake_codex, monkeypatch, **env: str):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
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
def app(tmp_path, fake_codex, monkeypatch):
    return _make_app(tmp_path, fake_codex, monkeypatch)


@pytest.fixture
def cwd_app(tmp_path, fake_codex, monkeypatch):
    """The same server with the operator opt-in that makes the process cwd a workspace."""
    return _make_app(tmp_path, fake_codex, monkeypatch, AMICUS_ALLOW_CWD_WORKSPACE="1")


@pytest.fixture
def gone_cwd(tmp_path, monkeypatch):
    """Issue #170: the server process's cwd is a directory that no longer exists, as
    after the Claude Code worktree it was started in is removed. Requested AFTER `app`
    so every other fixture is built from a live cwd; `tempfile`'s cached tempdir is
    cleared so the first temp-dir use inside the test recomputes it under the gone cwd."""
    saved = Path.cwd()
    doomed = tmp_path / "doomed"
    doomed.mkdir()
    os.chdir(doomed)
    try:
        # Everything after the chdir is inside the finally, so a failure here cannot
        # leave the rest of the session in a deleted directory.
        doomed.rmdir()
        with pytest.raises(FileNotFoundError):
            Path.cwd()
        monkeypatch.setattr(tempfile, "tempdir", None)
        yield
    finally:
        os.chdir(saved)


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
        assert [k for k, v in status["meta"].items() if v is None] == []  # #47
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
        assert "consume" not in body["meta"], "only a consume reports a disposition"
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
        assert consumed["meta"]["consume"] == {"discard_outcome": "removed"}
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
        assert stored.structured_content["meta"]["consume"] == {"discard_outcome": "removed"}
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


async def test_consume_reports_a_record_already_gone_as_missing(app, store, tmp_path, monkeypatch):
    """MISSING is a record the store dropped before this call's discard (a racing consume,
    or expiry): a repeat call returns job_not_found, as consume promises, but this call did
    not delete it, so the outcome says missing rather than removed. Delivery still
    happens (#44)."""
    real_discard = JobStore.discard

    def raced(self, cwd, job_id, **kw):
        assert real_discard(self, cwd, job_id, **kw) is DiscardOutcome.REMOVED
        return real_discard(self, cwd, job_id, **kw)

    monkeypatch.setattr(JobStore, "discard", raced)
    ws = {"workspace_root": str(tmp_path)}
    async with Client(app) as c:
        job_id = await _start(c, tmp_path)
        await _wait_done(store, tmp_path, job_id)
        consumed = (
            await c.call_tool("amicus_job_consume_result", {"job_id": job_id, **ws})
        ).structured_content
        assert consumed["ok"] is True and consumed["summary"] == "Looks fine"
        assert consumed["meta"]["consume"] == {"discard_outcome": "missing"}
        again = await c.call_tool(
            "amicus_job_consume_result", {"job_id": job_id, **ws}, raise_on_error=False
        )
        assert again.structured_content["error"]["code"] == "job_not_found"


@pytest.mark.parametrize("outcome", [DiscardOutcome.DELETE_FAILED, DiscardOutcome.STATE_CHANGED])
async def test_consume_reports_a_retained_record_and_a_follow_up_that_resolves_it(
    app, store, tmp_path, monkeypatch, outcome
):
    """An outcome that leaves the record still delivers, and meta.consume says so with a
    follow_up whose own call shows the record; a record still `done` is then deleted by a
    retried consume, as the follow_up's alternative says (#44)."""
    real_discard = JobStore.discard
    calls: list[str] = []

    def first_call_keeps_it(self, cwd, job_id, **kw):
        calls.append(job_id)
        return outcome if len(calls) == 1 else real_discard(self, cwd, job_id, **kw)

    monkeypatch.setattr(JobStore, "discard", first_call_keeps_it)
    ws = {"workspace_root": str(tmp_path)}
    async with Client(app) as c:
        job_id = await _start(c, tmp_path)
        await _wait_done(store, tmp_path, job_id)
        consumed = (
            await c.call_tool("amicus_job_consume_result", {"job_id": job_id, **ws})
        ).structured_content
        assert consumed["ok"] is True and consumed["summary"] == "Looks fine"
        follow_up = {
            "next_step": "inspect_and_retry",
            "tool": "amicus_job_status",
            "arguments": {"job_id": job_id, **ws},
            "alternative": delivery.CONSUME_FOLLOW_UP,
        }
        assert consumed["meta"]["consume"] == {
            "discard_outcome": outcome.value,
            "follow_up": follow_up,
        }
        checked = (await c.call_tool(follow_up["tool"], follow_up["arguments"])).structured_content
        assert checked["status"] == "done", "the record was retained"
        retried = (
            await c.call_tool("amicus_job_consume_result", {"job_id": job_id, **ws})
        ).structured_content
        assert retried["meta"]["consume"] == {"discard_outcome": "removed"}
        gone = await c.call_tool(
            "amicus_job_status", {"job_id": job_id, **ws}, raise_on_error=False
        )
        assert gone.structured_content["error"]["code"] == "job_not_found"


async def test_a_real_failed_delete_is_reported_and_leaves_the_record_consumable(
    app, store, tmp_path, monkeypatch
):
    """A real failure, not a faked outcome: the job directory's rmdir is refused. The store
    restores the whole record, so the follow_up's own call shows it still done, and a
    consume retried once the failure clears delivers it again and deletes it, as the
    follow_up's alternative says (#44, #124)."""
    ws = {"workspace_root": str(tmp_path)}
    async with Client(app) as c:
        job_id = await _start(c, tmp_path)
        await _wait_done(store, tmp_path, job_id)
        target = store._job_dir(str(tmp_path), job_id)
        refused: list[Path] = []
        real_rmdir = Path.rmdir

        def refuse_the_job_dir(self):
            if self == target:
                refused.append(self)
                raise OSError("rmdir refused")
            return real_rmdir(self)

        monkeypatch.setattr(Path, "rmdir", refuse_the_job_dir)
        consumed = (
            await c.call_tool("amicus_job_consume_result", {"job_id": job_id, **ws})
        ).structured_content
        assert refused, "control: the failure was injected"
        assert consumed["ok"] is True and consumed["summary"] == "Looks fine"
        disposition = consumed["meta"]["consume"]
        assert disposition["discard_outcome"] == "delete_failed"
        follow_up = disposition["follow_up"]
        checked = (await c.call_tool(follow_up["tool"], follow_up["arguments"])).structured_content
        assert checked["status"] == "done" and checked["result_available"] is True
        monkeypatch.undo()
        again = (
            await c.call_tool("amicus_job_consume_result", {"job_id": job_id, **ws})
        ).structured_content
        assert again["ok"] is True and again["summary"] == "Looks fine"
        assert again["meta"]["consume"] == {"discard_outcome": "removed"}
        assert not target.exists()


async def _terminal_error_job(c, store, tmp_path, monkeypatch, state):
    """A job left in `state` the way the store derives it: `cancelled` by a real cancel,
    `timeout` by a deadline already past at the next read, and `failed` as a finished record
    with no result.json and no terminal stamp, as a worker that exited without one leaves."""
    cwd = str(tmp_path)
    if state == "failed":
        job_id = await _start(c, tmp_path)
        await _wait_done(store, tmp_path, job_id)
        jd = store._job_dir(cwd, job_id)
        (jd / "result.json").unlink()
        meta = json.loads((jd / "meta.json").read_text(encoding="utf-8"))
        meta["terminal_status"] = None
        (jd / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    else:
        monkeypatch.setenv("FAKE_CODEX_SLEEP", "30")
        job_id = await _start(c, tmp_path)
        jd = store._job_dir(cwd, job_id)
        deadline = time.monotonic() + 10
        while not (jd / "worker.lock").exists() and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        assert (jd / "worker.lock").exists()
        if state == "cancelled":
            await c.call_tool("amicus_job_cancel", {"job_id": job_id, "workspace_root": cwd})
        else:
            meta = json.loads((jd / "meta.json").read_text(encoding="utf-8"))
            meta["deadline_epoch"] = 0
            (jd / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    assert store.status(cwd, job_id)["status"] == state, "control: the state was built"
    return job_id


@pytest.mark.parametrize(
    ("state", "code"),
    [("failed", "job_failed"), ("cancelled", "job_cancelled"), ("timeout", "job_timeout")],
)
async def test_consume_on_a_terminal_error_job_returns_the_error_and_deletes_it(
    app, store, tmp_path, monkeypatch, state, code
):
    """A failed, cancelled or timed-out job has no stored envelope, so a consume returns its
    terminal error, discards the record in the state it read, and reports that in
    meta.consume; a repeat call is job_not_found (#126). Before #126 it deleted nothing (#94),
    because the store had no delete safe for a `failed` record."""
    discards: list[tuple[str, str]] = []
    real_discard = JobStore.discard

    def counted(self, cwd, job_id, *, expected="done"):
        discards.append((job_id, expected))
        return real_discard(self, cwd, job_id, expected=expected)

    monkeypatch.setattr(JobStore, "discard", counted)
    ws = {"workspace_root": str(tmp_path)}
    async with Client(app) as c:
        schemas = await _schemas(c)
        job_id = await _terminal_error_job(c, store, tmp_path, monkeypatch, state)
        res = await c.call_tool(
            "amicus_job_consume_result", {"job_id": job_id, **ws}, raise_on_error=False
        )
        body = res.structured_content
        schemas["amicus_job_consume_result"].validate(body)
        assert res.is_error and body["error"]["code"] == code
        assert body["meta"]["consume"] == {"discard_outcome": "removed"}
        assert discards == [(job_id, state)]
        assert store.status(str(tmp_path), job_id) is None
        again = await c.call_tool(
            "amicus_job_consume_result", {"job_id": job_id, **ws}, raise_on_error=False
        )
        assert again.structured_content["error"]["code"] == "job_not_found"


async def test_consume_keeps_a_failed_record_whose_result_appears_before_the_discard(
    app, store, tmp_path, monkeypatch
):
    """The race #126 exists for: `failed` is derived on every read, never stamped, so a
    result.json that appears between the consume's read and its discard turns the record
    done. The discard must keep it and say state_changed, and the follow_up leads to a
    retried consume that delivers the result it would otherwise have destroyed."""
    real_discard = JobStore.discard
    stored: dict[str, bytes] = {}

    def result_appears_first(self, cwd, job_id, **kw):
        if stored:
            (self._job_dir(cwd, job_id) / "result.json").write_bytes(stored.pop("result"))
        return real_discard(self, cwd, job_id, **kw)

    ws = {"workspace_root": str(tmp_path)}
    async with Client(app) as c:
        job_id = await _start(c, tmp_path)
        await _wait_done(store, tmp_path, job_id)
        jd = store._job_dir(str(tmp_path), job_id)
        stored["result"] = (jd / "result.json").read_bytes()
        (jd / "result.json").unlink()
        meta = json.loads((jd / "meta.json").read_text(encoding="utf-8"))
        meta["terminal_status"] = None
        (jd / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        assert store.status(str(tmp_path), job_id)["status"] == "failed", "control"
        monkeypatch.setattr(JobStore, "discard", result_appears_first)
        res = await c.call_tool(
            "amicus_job_consume_result", {"job_id": job_id, **ws}, raise_on_error=False
        )
        body = res.structured_content
        assert res.is_error and body["error"]["code"] == "job_failed"
        assert not stored, "control: the result appeared before the discard"
        disposition = body["meta"]["consume"]
        assert disposition["discard_outcome"] == "state_changed"
        follow_up = disposition["follow_up"]
        checked = (await c.call_tool(follow_up["tool"], follow_up["arguments"])).structured_content
        assert checked["status"] == "done" and checked["result_available"] is True
        retried = (
            await c.call_tool("amicus_job_consume_result", {"job_id": job_id, **ws})
        ).structured_content
        assert retried["ok"] is True and retried["summary"] == "Looks fine"
        assert retried["meta"]["consume"] == {"discard_outcome": "removed"}


async def test_cancel_running_then_terminal_is_idempotent(app, store, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CODEX_SLEEP", "30")
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
        # #47: a job-lifecycle success is as sparse as a delivered paid one.
        assert [k for k, v in listed["meta"].items() if v is None] == []
        assert [j["job_id"] for j in listed["jobs"]] == [second, first]
        assert listed["truncated"] is False and listed["truncation_hint"] is None
        assert listed["jobs"][1]["task_id"] == "task-xyz" and listed["jobs"][0]["task_id"] is None
        assert listed["jobs"][0]["backend"] == "codex" and listed["jobs"][0]["result_ok"] is True
        limited = (await c.call_tool("amicus_job_list", {"limit": 1, **ws})).structured_content
        assert [j["job_id"] for j in limited["jobs"]] == [second] and limited["truncated"] is True
        assert "cursor" in limited["truncation_hint"] and limited["next_cursor"]
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


async def test_two_tasks_on_one_job_report_the_first_task_on_every_surface(
    app, store, settings, tmp_path
):
    """A keyed sync replay from another task records a further forward association (#66,
    ADR 0020). The job's task_id is the FIRST association on status, result and list
    alike (not a claim about which task created it), and a list filtered by either task
    finds the job."""
    ws = {"workspace_root": str(tmp_path)}
    async with Client(app) as c:
        job = await _start(c, tmp_path)
        await _wait_done(store, tmp_path, job)
        task_map = lookup.task_map(settings)
        task_map.record("task-first", job)
        task_map.record("task-second", job)
        listed = (await c.call_tool("amicus_job_list", ws)).structured_content
        by_second = (
            await c.call_tool("amicus_job_list", {"task_id": "task-second", **ws})
        ).structured_content
        status = (await c.call_tool("amicus_job_status", {"job_id": job, **ws})).structured_content
        result = (await c.call_tool("amicus_job_result", {"job_id": job, **ws})).structured_content
    assert [j["task_id"] for j in listed["jobs"]] == ["task-first"]
    assert [(j["job_id"], j["task_id"]) for j in by_second["jobs"]] == [(job, "task-first")]
    assert status["task_id"] == "task-first" and result["meta"]["task_id"] == "task-first"


async def test_a_failed_expiry_cleanup_during_consume_is_delete_failed(
    app, store, tmp_path, monkeypatch
):
    """Codex's review of #44: a record that expires between the read and the discard is
    cleaned up inside the discard. When that cleanup fails, the files remain, so the
    outcome is delete_failed, not missing (#125). The follow_up's call answers
    job_not_found, the branch of its alternative that says the store no longer serves the
    record, because an expired record is dropped on every read; a repeat consume agrees."""
    ws = {"workspace_root": str(tmp_path)}
    async with Client(app) as c:
        job_id = await _start(c, tmp_path)
        await _wait_done(store, tmp_path, job_id)
        target = store._job_dir(str(tmp_path), job_id)
        expired = [False]
        refused: list[Path] = []
        real_discard = JobStore.discard
        real_rmdir = Path.rmdir

        def expire_then_discard(self, cwd, jid, **kw):
            expired[0] = True
            return real_discard(self, cwd, jid, **kw)

        def refuse_the_job_dir(self):
            if self == target:
                refused.append(self)
                raise OSError("rmdir refused")
            return real_rmdir(self)

        monkeypatch.setattr(JobStore, "_expired", lambda self, meta: expired[0])
        monkeypatch.setattr(JobStore, "discard", expire_then_discard)
        monkeypatch.setattr(Path, "rmdir", refuse_the_job_dir)
        consumed = (
            await c.call_tool("amicus_job_consume_result", {"job_id": job_id, **ws})
        ).structured_content
        assert refused, "control: the expiry cleanup ran and failed"
        assert consumed["ok"] is True and consumed["summary"] == "Looks fine"
        disposition = consumed["meta"]["consume"]
        assert disposition["discard_outcome"] == "delete_failed"
        assert target.exists(), "files the failed cleanup left remain"
        follow_up = disposition["follow_up"]
        checked = await c.call_tool(follow_up["tool"], follow_up["arguments"], raise_on_error=False)
        assert checked.structured_content["error"]["code"] == "job_not_found"
        again = await c.call_tool(
            "amicus_job_consume_result", {"job_id": job_id, **ws}, raise_on_error=False
        )
        assert again.structured_content["error"]["code"] == "job_not_found"


async def test_an_explicit_root_survives_a_deleted_server_cwd(app, store, tmp_path, gone_cwd):
    """Issue #170: with the process cwd gone, every job tool and a paid call that named
    its workspace still work; before the fix each raised FileNotFoundError into the
    guard's retryable internal_error, which sent the caller into a retry loop."""
    ws = {"workspace_root": str(tmp_path)}
    async with Client(app) as c:
        listed = (await c.call_tool("amicus_job_list", ws)).structured_content
        assert listed["ok"] is True and listed["jobs"] == []
        missing = await c.call_tool(
            "amicus_job_status", {"job_id": "a" * 32, **ws}, raise_on_error=False
        )
        assert missing.structured_content["error"]["code"] == "job_not_found"
        job_id = await _start(c, tmp_path)
        await _wait_done(store, tmp_path, job_id)
        result = (
            await c.call_tool("amicus_job_result", {"job_id": job_id, **ws})
        ).structured_content
        assert result["ok"] is True and result["tool"] == "amicus_consult"
        # A synchronous paid call prepares the backend in the server process itself, so
        # its temp files and the spawn happen under the deleted cwd.
        sync = (
            await c.call_tool("amicus_consult", {"backend": "codex", "question": "why?", **ws})
        ).structured_content
        assert sync["ok"] is True and sync["meta"]["cwd"] == str(tmp_path)


async def test_a_needed_but_deleted_cwd_is_a_workspace_error_not_internal(
    cwd_app, tmp_path, gone_cwd
):
    """Issue #170: under AMICUS_ALLOW_CWD_WORKSPACE=1 with no root named, the deleted cwd
    is the workspace the call would use. That is reported as a non-temporary
    invalid_workspace_root with no repair (no call can mint the directory) on both the
    job path and the paid path, and no backend runs."""
    async with Client(cwd_app) as c:
        for tool, args in (
            ("amicus_job_list", {}),
            ("amicus_consult", {"backend": "codex", "question": "why?"}),
        ):
            res = await c.call_tool(tool, args, raise_on_error=False)
            assert res.is_error, tool
            err = res.structured_content["error"]
            assert err["code"] == "invalid_workspace_root", tool
            assert err["temporary"] is False and "repair" not in err, tool
            assert err["details"]["field"] == "workspace_root", tool
            assert "no longer exists" in err["message"] and "restart" in err["message"], tool
            assert err["details"]["reason"] == "cwd_gone", tool
    assert not (tmp_path / "argv.jsonl").exists(), "the fake codex was spawned"


async def test_a_live_cwd_still_resolves_under_the_opt_in(cwd_app, tmp_path, monkeypatch):
    """Positive control for the test above: the same server and call, from a cwd that
    exists, resolves the workspace from it and says so."""
    live = tmp_path / "live"
    live.mkdir()
    monkeypatch.chdir(live)
    async with Client(cwd_app) as c:
        listed = (await c.call_tool("amicus_job_list", {})).structured_content
    assert listed["ok"] is True and listed["meta"]["workspace_source"] == "cwd"
    assert listed["meta"]["cwd"] == str(live.resolve()) and listed["meta"]["workspace_warning"]


async def test_a_full_cap_refuses_a_paid_call_until_the_result_is_fetched(
    tmp_path, fake_codex, monkeypatch
):
    """Issue #244 end to end: with AMICUS_JOB_MAX_COUNT=1, a finished result nobody has
    fetched is never evicted to make room. A new paid call is refused pre-spend with
    job_cap_reached until amicus_job_result returns the result once; a status read or a
    list does not count as returning it."""
    app = _make_app(tmp_path, fake_codex, monkeypatch, AMICUS_JOB_MAX_COUNT="1")
    store = lifecycle.job_store(server.state_of(app).settings)
    ws = {"workspace_root": str(tmp_path)}
    async with Client(app) as c:
        first = await _start(c, tmp_path)
        await _wait_done(store, tmp_path, first)
        await c.call_tool("amicus_job_status", {"job_id": first, **ws})
        await c.call_tool("amicus_job_list", ws)
        argv_file = tmp_path / "argv.jsonl"
        runs_before = argv_file.read_text().count("\n")
        refused = await c.call_tool(
            "amicus_consult_async",
            {"backend": "codex", "question": "again?", **ws},
            raise_on_error=False,
        )
        assert refused.is_error is True
        err = refused.structured_content["error"]
        assert err["code"] == "job_cap_reached" and err["temporary"] is True
        assert err["repair"]["tool"] == "amicus_job_list" and err["repair"]["arguments"] == ws
        assert argv_file.read_text().count("\n") == runs_before  # nothing was spent
        body = (await c.call_tool("amicus_job_result", {"job_id": first, **ws})).structured_content
        assert body["ok"] is True
        second = await _start(c, tmp_path)
        await _wait_done(store, tmp_path, second)
        listed = (await c.call_tool("amicus_job_list", ws)).structured_content
        assert [j["job_id"] for j in listed["jobs"]] == [second]


async def test_list_pages_by_cursor_and_survives_a_consumed_anchor(app, store, tmp_path):
    """#249: limit=1 walks three jobs in three pages; the second page still resolves after
    its anchor (the first page's last job) was consumed, because the cursor is the anchor's
    (started_epoch, job_id) rather than a position; the last page carries no cursor."""
    ws = {"workspace_root": str(tmp_path)}
    async with Client(app) as c:
        schemas = await _schemas(c)
        ids = []
        for _ in range(3):
            job_id = await _start(c, tmp_path)
            await _wait_done(store, tmp_path, job_id)
            ids.append(job_id)
        first = (await c.call_tool("amicus_job_list", {"limit": 1, **ws})).structured_content
        schemas["amicus_job_list"].validate(first)
        assert [j["job_id"] for j in first["jobs"]] == [ids[2]]
        assert first["truncated"] is True and first["next_cursor"]
        assert "cursor" in first["truncation_hint"]
        await c.call_tool("amicus_job_consume_result", {"job_id": ids[2], **ws})
        second = (
            await c.call_tool("amicus_job_list", {"limit": 1, "cursor": first["next_cursor"], **ws})
        ).structured_content
        assert [j["job_id"] for j in second["jobs"]] == [ids[1]] and second["truncated"] is True
        third = (
            await c.call_tool(
                "amicus_job_list", {"limit": 1, "cursor": second["next_cursor"], **ws}
            )
        ).structured_content
        assert [j["job_id"] for j in third["jobs"]] == [ids[0]]
        assert third["truncated"] is False and third["next_cursor"] is None
        assert third["truncation_hint"] is None
        # A cursor with a filter keeps the filter; omitting limit after a cursor returns the rest.
        rest = (
            await c.call_tool("amicus_job_list", {"cursor": first["next_cursor"], **ws})
        ).structured_content
        assert [j["job_id"] for j in rest["jobs"]] == [ids[1], ids[0]]
        filtered = (
            await c.call_tool(
                "amicus_job_list", {"cursor": first["next_cursor"], "status": "running", **ws}
            )
        ).structured_content
        assert filtered["jobs"] == [] and filtered["next_cursor"] is None


async def test_list_rejects_a_cursor_it_did_not_issue(app, tmp_path):
    ws = {"workspace_root": str(tmp_path)}
    async with Client(app) as c:
        for bad in ("nope", "1.5:short", "x:" + "a" * 32, ":" + "a" * 32):
            res = await c.call_tool("amicus_job_list", {"cursor": bad, **ws}, raise_on_error=False)
            err = res.structured_content["error"]
            assert err["code"] == "invalid_arguments", bad
            assert (
                err["details"]["field"] == "cursor" and err["repair"]["tool"] == "amicus_job_list"
            )
            assert "cursor" in err["repair"]["alternative"]
