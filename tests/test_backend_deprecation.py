"""A deprecated backend (#423): `kimi`, in favour of `pi`. Its marker lives in one table,
`amicus.backends.DEPRECATED_BACKENDS`; it rides the backend's amicus_backends entry at every
detail and `meta.deprecation` on every envelope whose meta.backend names it. Spend-free: the
envelopes come from the fake kimi and fake codex executables."""

from __future__ import annotations

import asyncio
import json
import subprocess
import time
from pathlib import Path

import pytest
from fastmcp import Client

from amicus import __version__, backends, config, server
from amicus.errors import make_error, serialize_error
from amicus.jobs import lifecycle
from amicus.jobs.delivery import finished_job_envelope
from amicus.registry import BackendRegistry
from amicus.schemas.codes import BACKEND_IDS
from amicus.schemas.envelope import ErrorResult, Meta, dump_success
from amicus.schemas.fingerprint import RESULT_FORMAT
from amicus.schemas.results import ConsultResult

KIMI_MARKER = {
    "since": "0.13.0",
    "removal_at_or_after": "0.15.0",
    "replaced_by": "pi",
    "migration": backends.DEPRECATED_BACKENDS["kimi"].migration,
}


def _version(text: str) -> tuple[int, int, int]:
    major, minor, micro = (int(part) for part in text.split("."))
    return major, minor, micro


# --- the table ---------------------------------------------------------------------------


def test_kimi_is_the_one_deprecated_backend_and_names_pi():
    assert set(backends.DEPRECATED_BACKENDS) == {"kimi"}
    marker = backends.backend_deprecation("kimi")
    assert marker is not None and marker.model_dump(mode="json") == KIMI_MARKER
    for needle in ("AMICUS_PI_MODEL", 'backend: "pi"', "provider/id", "AMICUS_BACKENDS"):
        assert needle in marker.migration, needle


@pytest.mark.parametrize("backend", [None, "codex", "claude", "pi", "not_a_backend"])
def test_every_other_backend_reads_as_not_deprecated(backend):
    assert backends.backend_deprecation(backend) is None


def test_every_backend_window_is_two_minor_releases_and_names_a_live_replacement():
    """The published deprecation_policy: discoverable for two minor releases, so a backend
    deprecated in x.y.0 is removed no earlier than x.(y+2).0, and its replacement is an
    in-tree backend that is not itself deprecated."""
    assert backends.DEPRECATED_BACKENDS, "known positive: the table is expected non-empty"
    for name, marker in backends.DEPRECATED_BACKENDS.items():
        assert name in BACKEND_IDS, name
        major, minor, micro = _version(marker.since)
        assert micro == 0 and _version(marker.removal_at_or_after) == (major, minor + 2, 0)
        assert marker.replaced_by in BACKEND_IDS
        assert marker.replaced_by not in backends.DEPRECATED_BACKENDS


def test_no_deprecated_backend_outlives_its_window():
    """The same ratchet `DEPRECATED_TOOLS` has (tests/test_meta.py): once the tree declares a
    version at or past removal_at_or_after, the backend must already be gone."""
    outlived = [
        name
        for name, marker in backends.DEPRECATED_BACKENDS.items()
        if _version(__version__) >= _version(marker.removal_at_or_after)
    ]
    assert outlived == [], "remove each backend and its DEPRECATED_BACKENDS entry"


# --- the wire ----------------------------------------------------------------------------


@pytest.fixture
def app(tmp_path, fake_kimi, fake_codex, monkeypatch):
    monkeypatch.setenv("AMICUS_KIMI_BIN", str(fake_kimi))
    monkeypatch.setenv("AMICUS_CODEX_BIN", str(fake_codex))
    monkeypatch.setenv("AMICUS_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("FAKE_KIMI_ARGV_FILE", str(tmp_path / "kimi-argv.jsonl"))
    monkeypatch.setenv("FAKE_KIMI_PROMPT_FILE", str(tmp_path / "kimi-prompt.txt"))
    monkeypatch.setenv("FAKE_CODEX_ARGV_FILE", str(tmp_path / "codex-argv.jsonl"))
    monkeypatch.setenv("FAKE_CODEX_STDIN_FILE", str(tmp_path / "codex-prompt.txt"))
    for key in (
        "FAKE_KIMI_EXIT",
        "FAKE_KIMI_STDERR",
        "FAKE_KIMI_ANSWER",
        "FAKE_KIMI_WRITE",
        "FAKE_KIMI_EVENTS",
        "FAKE_KIMI_EVENTS_FILE",
        "FAKE_KIMI_PROVIDERS",
        "FAKE_KIMI_SLEEP",
        "FAKE_KIMI_ANSWER_MODE",
        "FAKE_KIMI_VERSION",
        "FAKE_CODEX_EXIT",
        "FAKE_CODEX_STDERR",
        "FAKE_CODEX_ANSWER",
        "FAKE_CODEX_WRITE",
        "FAKE_CODEX_EVENTS",
        "FAKE_CODEX_SLEEP",
        "AMICUS_BACKENDS",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(lifecycle, "SYNC_POLL_INTERVAL_S", 0.02)
    settings = config.settings()
    registry = BackendRegistry.load(settings.enabled_backends, entry_points=())
    return server.create_app(settings, registry)


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


@pytest.mark.parametrize("detail", ["summary", "full"])
async def test_amicus_backends_carries_the_marker_at_every_detail(app, detail):
    async with Client(app) as c:
        res = await c.call_tool("amicus_backends", {"detail": detail})
    body = res.structured_content
    entries = {e["id"]: e for e in body["backends"]}
    assert set(entries) >= set(BACKEND_IDS)
    assert entries["kimi"]["deprecation"] == KIMI_MARKER
    for backend_id, entry in entries.items():
        if backend_id != "kimi":
            # Present and null, not absent: null is the not-deprecated statement.
            assert "deprecation" in entry and entry["deprecation"] is None, backend_id
    assert "deprecation" not in body["omitted_fields"]


async def test_the_backend_resource_carries_the_marker_too(app):
    async with Client(app) as c:
        contents = await c.read_resource("amicus://backends/kimi")
    entry = json.loads(contents[0].text)
    assert entry["id"] == "kimi" and entry["deprecation"] == KIMI_MARKER


async def test_every_kimi_result_carries_meta_deprecation(app, repo, monkeypatch):
    async with Client(app) as c:
        consult = await c.call_tool(
            "amicus_consult", {"backend": "kimi", "question": "q", "workspace_root": str(repo)}
        )
        (repo / "a.py").write_text("x = 2\n")
        review = await c.call_tool(
            "amicus_review_changes", {"backend": "kimi", "workspace_root": str(repo)}
        )
        dry = await c.call_tool(
            "amicus_review_changes_dry_run", {"backend": "kimi", "workspace_root": str(repo)}
        )
        monkeypatch.setenv("FAKE_KIMI_WRITE", "b.py")
        delegate = await c.call_tool(
            "amicus_delegate", {"backend": "kimi", "task": "add b.py", "workspace_root": str(repo)}
        )
    for name, res in (
        ("consult", consult),
        ("review", review),
        ("dry_run", dry),
        ("delegate", delegate),
    ):
        body = res.structured_content
        assert body["ok"] is True, name
        assert body["meta"]["backend"] == "kimi", name
        assert body["meta"]["deprecation"] == KIMI_MARKER, name


async def _finished_kimi_job(c, app, repo) -> tuple[str, Path]:
    handle = (
        await c.call_tool(
            "amicus_consult_async",
            {"backend": "kimi", "question": "q", "workspace_root": str(repo)},
        )
    ).structured_content
    job_id = handle["job_id"]
    store = lifecycle.job_store(server.state_of(app).settings)
    cwd = str(repo.resolve())
    deadline = time.monotonic() + 15
    while store.status(cwd, job_id)["status"] == "running":
        assert time.monotonic() < deadline, "job did not finish"
        await asyncio.sleep(0.05)
    return job_id, store._job_dir(cwd, job_id) / "result.json"


async def test_the_marker_is_delivered_but_never_stored(app, repo):
    """Delivery-only, like `consume`: result.json on disk has no `deprecation` (so
    RESULT_FORMAT did not move), while amicus_job_result and amicus_job_consume_result both
    deliver it, attached from meta.backend."""
    async with Client(app) as c:
        job_id, result_json = await _finished_kimi_job(c, app, repo)
        raw = result_json.read_text()
        stored = json.loads(raw)
        delivered = (
            await c.call_tool("amicus_job_result", {"job_id": job_id, "workspace_root": str(repo)})
        ).structured_content
        consumed = (
            await c.call_tool(
                "amicus_job_consume_result", {"job_id": job_id, "workspace_root": str(repo)}
            )
        ).structured_content
    assert stored["ok"] is True and stored["meta"]["backend"] == "kimi"
    assert "deprecation" not in stored["meta"] and "deprecation" not in raw
    assert delivered["ok"] is True and delivered["meta"]["deprecation"] == KIMI_MARKER
    assert consumed["ok"] is True and consumed["meta"]["deprecation"] == KIMI_MARKER
    assert consumed["meta"]["consume"]["discard_outcome"] == "removed"


def _stored_consult(backend: str, **meta_extra) -> dict:
    payload = dump_success(
        ConsultResult(
            summary="s", meta=Meta(backend=backend, cwd="/repo", timeout_seconds=1, elapsed_ms=1)
        )
    )
    payload["meta"].update(meta_extra)
    return json.loads(json.dumps(payload))


def _deliver(payload: dict) -> tuple[dict, bool]:
    rec = {"status": "done", "extra": {"result_format": RESULT_FORMAT}}
    return finished_job_envelope(rec, payload, "0" * 32, "consult", Meta(), "summary", None)


def test_a_result_stored_before_the_change_is_delivered_with_the_marker():
    """A kimi result 0.12.0 stored carries no `deprecation` key, exactly as one stored now;
    the delivering server attaches the marker it holds today."""
    payload = _stored_consult("kimi")
    assert "deprecation" not in payload["meta"]
    envelope, delivered = _deliver(payload)
    assert delivered and envelope["meta"]["deprecation"] == KIMI_MARKER


def test_a_stored_marker_is_never_trusted_over_the_delivering_server():
    """A `deprecation` key a stored record carries anyway (a hand-edited file) is dropped,
    and replaced only by this server's own marker for the backend."""
    forged = {
        "since": "0.1.0",
        "removal_at_or_after": "0.3.0",
        "replaced_by": None,
        "migration": "m",
    }
    envelope, delivered = _deliver(_stored_consult("codex", deprecation=forged))
    assert delivered and "deprecation" not in envelope["meta"]
    envelope, delivered = _deliver(_stored_consult("kimi", deprecation=forged))
    assert delivered and envelope["meta"]["deprecation"] == KIMI_MARKER


def test_dump_never_carries_the_marker():
    meta = Meta(backend="kimi", deprecation=backends.backend_deprecation("kimi"))
    assert "deprecation" not in meta.model_dump(mode="json")
    assert (
        "deprecation"
        not in serialize_error(ErrorResult(error=make_error("internal_error", "m"), meta=meta))[
            "meta"
        ]
    )


async def test_a_kimi_error_envelope_carries_it_like_the_rest_of_its_meta(app, repo, monkeypatch):
    """Error envelopes carry the same meta a success would (nulls dropped), so a failed
    kimi call states the deprecation too: a host learns of it on the first call either way."""
    monkeypatch.setenv("FAKE_KIMI_EXIT", "1")
    monkeypatch.setenv("FAKE_KIMI_STDERR", "Error: 401 Unauthorized")
    async with Client(app) as c:
        res = await c.call_tool(
            "amicus_consult",
            {"backend": "kimi", "question": "q", "workspace_root": str(repo)},
            raise_on_error=False,
        )
    body = res.structured_content
    assert body["ok"] is False and body["error"]["backend"] == "kimi"
    assert body["meta"]["deprecation"] == KIMI_MARKER


async def test_a_kimi_refusal_before_spend_carries_it_too(app, repo):
    async with Client(app) as c:
        res = await c.call_tool(
            "amicus_consult",
            {"backend": "kimi", "question": "q", "workspace_root": str(repo / "missing")},
            raise_on_error=False,
        )
    body = res.structured_content
    assert body["ok"] is False and body["error"]["code"] == "invalid_workspace_root"
    assert body["meta"]["deprecation"] == KIMI_MARKER


async def test_a_codex_result_has_no_deprecation_key(app, repo, monkeypatch):
    """The negative: a non-deprecated backend's meta has no `deprecation` key at all (the
    slim-meta rule drops a null), on a success and on a failure."""
    async with Client(app) as c:
        ok = await c.call_tool(
            "amicus_consult", {"backend": "codex", "question": "q", "workspace_root": str(repo)}
        )
        monkeypatch.setenv("FAKE_CODEX_EXIT", "1")
        failed = await c.call_tool(
            "amicus_consult",
            {"backend": "codex", "question": "q", "workspace_root": str(repo)},
            raise_on_error=False,
        )
    assert ok.structured_content["ok"] is True
    assert ok.structured_content["meta"]["backend"] == "codex"
    assert "deprecation" not in ok.structured_content["meta"]
    assert failed.structured_content["ok"] is False
    assert "deprecation" not in failed.structured_content["meta"]


async def test_a_task_delivered_kimi_result_carries_it(tmp_path, fake_kimi, monkeypatch):
    """The task path never re-enters the middleware chain; the guard still attaches it."""
    pytest.importorskip("fastmcp_tasks")
    from fastmcp_tasks import call_tool_task

    monkeypatch.setenv("AMICUS_KIMI_BIN", str(fake_kimi))
    monkeypatch.setenv("AMICUS_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("AMICUS_TASKS", "1")
    monkeypatch.setenv("AMICUS_TASKS_BACKEND_URL", "memory://")
    monkeypatch.setenv("FAKE_KIMI_ARGV_FILE", str(tmp_path / "kimi-argv.jsonl"))
    monkeypatch.setenv("FAKE_KIMI_PROMPT_FILE", str(tmp_path / "kimi-prompt.txt"))
    for key in ("FAKE_KIMI_EXIT", "FAKE_KIMI_STDERR", "FAKE_KIMI_ANSWER", "AMICUS_BACKENDS"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(lifecycle, "SYNC_POLL_INTERVAL_S", 0.02)
    settings = config.settings()
    app = server.create_app(
        settings, BackendRegistry.load(settings.enabled_backends, entry_points=())
    )
    async with Client(app) as c:
        task = await call_tool_task(
            c,
            "amicus_consult",
            {"backend": "kimi", "question": "q", "workspace_root": str(tmp_path)},
        )
        result = await task.result()
    body = result.structured_content
    assert body["ok"] is True and body["meta"]["task_id"] == task.task_id
    assert body["meta"]["deprecation"] == KIMI_MARKER
