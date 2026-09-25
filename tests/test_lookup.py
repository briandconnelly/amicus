"""jobs/lookup.py: what a job tool resolves and builds before and after touching the store."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from amicus import config
from amicus.jobs import lookup
from amicus.schemas.results import JobStatus


def _settings(tmp_path, **env):
    return config.settings({"AMICUS_STATE_DIR": str(tmp_path / "state"), **env})


def _row(**kw):
    base = {
        "job_id": "a" * 32,
        "kind": "consult",
        "status": "running",
        "started_at": "2026-09-06T00:00:00+00:00",
        "started_epoch": 0.0,
        "elapsed_ms": 5,
        "deadline_seconds": 1800,
        "completed_epoch": None,
        "expires_at": None,
        "result_available": False,
        "result_ok": None,
        "poll_after_ms": 1000,
        "ttl_seconds": 86400,
        "cleanup_warnings": [],
        "extra": {"result_format": 1, "backend": "codex", "tool": "amicus_consult_async"},
        "events_seen": 0,
        "last_event_at": None,
        "event_age_ms": None,
    }
    base.update(kw)
    return base


def test_backend_and_kind_readers_reject_foreign_rows():
    assert lookup.backend_of(_row()) == "codex"
    assert lookup.backend_of(_row(extra={})) is None
    assert lookup.backend_of(_row(extra={"backend": "Not Valid"})) is None
    assert lookup.backend_of(_row(extra="junk")) is None
    assert lookup.kind_of(_row()) == "consult" and lookup.kind_of(_row(kind="")) == ""


async def test_resolve_job_workspace_explicit_roots_and_errors(tmp_path):
    settings = _settings(tmp_path)
    cwd, source, roots_source, err = await lookup.resolve_job_workspace(
        settings, None, str(tmp_path)
    )
    assert cwd == str(tmp_path) and source == "param" and err is None
    assert roots_source == "not_negotiated"  # no ctx: no session, no roots capability
    cwd, source, roots_source, err = await lookup.resolve_job_workspace(settings, None, None)
    assert cwd is None and err["ok"] is False
    assert err["error"]["code"] == "invalid_workspace_root"
    assert err["error"]["details"]["field"] == "workspace_root"
    assert (
        err["meta"]["roots_source"] == "not_negotiated" and err["meta"]["timeout_seconds"] == 1800
    )
    _cwd, _source, _rs, err = await lookup.resolve_job_workspace(settings, None, "relative/path")
    assert err["error"]["code"] == "invalid_workspace_root"


async def test_job_workspace_errors_name_their_cause_in_details_reason(tmp_path):
    """Issue #214: the job path's workspace refusal carries the same reason token as the
    paid path's, so the causes are distinguishable there too."""
    for root, reason in (
        (None, "no_workspace"),
        ("relative/path", "not_absolute"),
        (str(tmp_path / "missing"), "not_a_directory"),
    ):
        *_, err = await lookup.resolve_job_workspace(_settings(tmp_path), None, root)
        assert err["error"]["code"] == "invalid_workspace_root"
        assert err["error"]["details"]["reason"] == reason


async def test_job_workspace_errors_carry_no_repair(tmp_path):
    for root in (None, "relative/path"):
        *_, err = await lookup.resolve_job_workspace(_settings(tmp_path), None, root)
        assert err["error"]["code"] == "invalid_workspace_root" and "repair" not in err["error"]


async def test_resolve_job_workspace_falls_back_to_cwd_only_when_allowed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    settings = _settings(tmp_path, AMICUS_ALLOW_CWD_WORKSPACE="1")
    cwd, source, _rs, err = await lookup.resolve_job_workspace(settings, None, None)
    assert err is None and source == "cwd" and cwd == str(tmp_path.resolve())
    assert lookup.workspace_of(cwd, source).workspace_warning


def test_job_meta_and_not_found(tmp_path):
    settings = _settings(tmp_path)
    meta = lookup.job_meta(settings, "/repo", "param", "client", backend="codex", kind="delegate")
    assert meta.backend == "codex" and meta.job_kind == "delegate" and meta.cwd == "/repo"
    assert meta.timeout_seconds == 1800 and meta.roots_source == "client"
    bare = lookup.job_meta(settings, None, None, "not_negotiated")
    assert bare.backend is None and bare.job_kind is None and bare.cwd is None
    with pytest.raises(ValidationError):
        lookup.job_meta(settings, None, None, "none")
    env = lookup.job_not_found("b" * 32, meta, "/repo")
    assert env["error"]["code"] == "job_not_found" and "b" * 32 in env["error"]["message"]
    assert env["error"]["repair"]["tool"] == "amicus_job_list"
    assert env["error"]["repair"]["arguments"] == {"workspace_root": "/repo"}
    assert env["error"]["details"]["field"] == "job_id"
    # Resolved from roots, the workspace needs no argument: amicus_job_list({}) resolves the
    # same one, so the lookup call is complete rather than tool-only (issue #42).
    assert lookup.job_not_found("b" * 32, meta, None)["error"]["repair"]["arguments"] == {}


def test_a_long_running_status_keeps_growing_its_poll_hint(tmp_path):
    # pontonier's own row hint saturates at 10000 at four minutes; amicus's does not (#95).
    settings = _settings(tmp_path)
    ws = lookup.workspace_of("/repo", "param")
    meta = lookup.job_meta(settings, "/repo", "param", "client", backend="codex", kind="consult")
    running = lookup.status_model(_row(elapsed_ms=240_000, poll_after_ms=10000), ws, None, meta)
    assert running["poll_after_ms"] == 30000


def test_status_and_summary_models_carry_backend_task_and_detail(tmp_path):
    settings = _settings(tmp_path)
    ws = lookup.workspace_of("/repo", "param")
    meta = lookup.job_meta(settings, "/repo", "param", "client", backend="codex", kind="consult")
    running = lookup.status_model(_row(), ws, None, meta)
    JobStatus.model_validate(running)
    assert running["backend"] == "codex" and running["status"] == "running"
    assert running["poll_after_ms"] == 1000 and running["task_id"] is None
    assert running["workspace"]["cwd"] == "/repo" and running["cleanup_warnings"] == []
    assert running["meta"]["job_kind"] == "consult" and running["meta"]["timeout_seconds"] == 1800
    cancelled = lookup.status_model(
        _row(status="cancelled", cleanup_warnings=["/tmp/x"]), ws, "t-1", meta
    )
    assert cancelled["task_id"] == "t-1" and cancelled["cleanup_warnings"] == ["/tmp/x"]
    assert cancelled["poll_after_ms"] is None and cancelled["meta"]["task_id"] == "t-1"
    summary = lookup.summary_model(
        _row(status="done", result_available=True, result_ok=False), "t-2"
    )
    assert summary.result_ok is False and summary.task_id == "t-2" and summary.backend == "codex"
    with pytest.raises(ValueError):
        lookup.status_model(_row(extra={}), ws, None, meta)


def test_task_map_lives_under_the_state_dir(tmp_path):
    settings = _settings(tmp_path)
    tm = lookup.task_map(settings)
    tm.record("task-1", "c" * 32)
    assert (tmp_path / "state" / "tasks.json").exists()
    assert lookup.task_map(settings).job_for("task-1") == "c" * 32
    assert lookup.task_map(settings).task_for("c" * 32) == "task-1"


async def test_a_missing_client_root_is_refused_on_the_job_path_too(tmp_path, monkeypatch):
    async def roots(_ctx):
        return [str(tmp_path / "gone")], "client"

    monkeypatch.setattr(lookup.ws, "roots_from_ctx", roots)
    *_, err = await lookup.resolve_job_workspace(_settings(tmp_path), object(), None)
    assert err["error"]["code"] == "invalid_workspace_root"
    assert err["error"]["details"]["reason"] == "root_not_a_directory"
