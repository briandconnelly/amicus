"""Live tests against the real kimi CLI: paid, opt in with

    AMICUS_REQUIRE_LIVE=1 uv run pytest -m integration --no-cov tests/test_kimi_live.py

AMICUS_REQUIRE_LIVE=1 makes a missing or provider-less kimi a failure (the publish gate)."""

from __future__ import annotations

import re
import subprocess

import pytest
from fastmcp import Client

from amicus import config, server
from amicus.orchestration.isolation import NO_REPO_WARNING
from amicus.registry import BackendRegistry

pytestmark = pytest.mark.integration


def _app():
    settings = config.settings()
    return server.create_app(settings, BackendRegistry.load(("kimi",), entry_points=()))


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _repo(path):
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "t@t.co")
    _git(path, "config", "user.name", "t")
    (path / "m.py").write_text("def f(xs):\n    return xs[0]\n")
    _git(path, "add", "-A")
    _git(path, "commit", "-qm", "init")


async def test_backends_reports_kimi_ready_live(live_kimi):
    async with Client(_app()) as c:
        body = (await c.call_tool("amicus_backends", {"backend": "kimi"})).structured_content
        models = (await c.call_tool("amicus_models", {"backend": "kimi"})).structured_content
    entry = body["backends"][0]
    assert entry["available"] is True and entry["status"]["installed"] is True
    assert entry["status"]["authenticated"] is True, entry["status"]
    assert entry["status"]["version"].startswith("0.41"), entry["status"]
    assert entry["status"]["warnings"] == [], entry["status"]
    assert models["source"] == "live" and models["models"], models


async def test_consult_outside_a_repo_live(live_kimi, tmp_path):
    async with Client(_app()) as c:
        res = await c.call_tool(
            "amicus_consult",
            {
                "backend": "kimi",
                "question": "Reply in one sentence: what does DRY mean?",
                "workspace_root": str(tmp_path),
                "timeout_seconds": 150,
            },
            raise_on_error=False,
        )
    body = res.structured_content
    assert body["ok"] is True, body.get("error", {}).get("code")
    assert body["summary"] and body["meta"]["session_id"] and body["meta"]["job_id"]
    assert body["meta"]["security_warnings"] == [NO_REPO_WARNING]


async def test_read_only_profile_is_enforced_live(live_kimi, tmp_path):
    _repo(tmp_path)
    async with Client(_app()) as c:
        res = await c.call_tool(
            "amicus_consult",
            {
                "backend": "kimi",
                "question": (
                    "Reply with ONLY a comma-separated list of the exact names of the tools "
                    "you have available in this session. No other words."
                ),
                "workspace_root": str(tmp_path),
                "timeout_seconds": 150,
            },
            raise_on_error=False,
        )
    body = res.structured_content
    assert body["ok"] is True, body.get("error", {}).get("code")
    names = {t.strip().lower() for t in re.split(r"[,\s]+", body["summary"]) if t.strip()}
    # `names` is the summary split into tokens, so it carries the model's prose. Only the
    # intersections with the fixed tool sets below are safe to print on failure.
    write_tools = names & {"bash", "write", "edit", "shell"}
    read_tools = names & {"read", "glob", "grep"}
    assert not write_tools, sorted(write_tools)
    assert read_tools, len(names)


async def test_review_changes_live(live_kimi, tmp_path):
    _repo(tmp_path)
    (tmp_path / "m.py").write_text(
        "def f(xs):\n"
        "    out = []\n"
        "    for i in range(len(xs) + 1):\n"
        "        out.append(xs[i])\n"
        "    return out\n"
    )
    async with Client(_app()) as c:
        res = await c.call_tool(
            "amicus_review_changes",
            {"backend": "kimi", "workspace_root": str(tmp_path), "timeout_seconds": 150},
            raise_on_error=False,
        )
    body = res.structured_content
    assert body["ok"] is True, body.get("error", {}).get("code")
    assert body["review_status"] == "completed"
    assert body["verdict"] in ("concerns", "fail", "pass", "unknown")
    assert body["meta"]["context_summary"]["files_changed"] == 1


async def test_delegate_live(live_kimi, tmp_path):
    _repo(tmp_path)
    before = (tmp_path / "m.py").read_text()
    async with Client(_app()) as c:
        res = await c.call_tool(
            "amicus_delegate",
            {
                "backend": "kimi",
                "task": "Add a function g(xs) returning xs[-1] to m.py.",
                "workspace_root": str(tmp_path),
                "timeout_seconds": 180,
            },
            raise_on_error=False,
        )
    body = res.structured_content
    assert body["ok"] is True, body.get("error", {}).get("code")
    assert body["diff"] and (tmp_path / "m.py").read_text() == before
    listed = subprocess.run(
        ["git", "worktree", "list"], cwd=tmp_path, capture_output=True, text=True, check=True
    ).stdout
    assert listed.strip().count("\n") == 0


async def test_unknown_model_alias_is_invalid_model_live(live_kimi, tmp_path):
    async with Client(_app()) as c:
        res = await c.call_tool(
            "amicus_consult",
            {
                "backend": "kimi",
                "question": "hi",
                "workspace_root": str(tmp_path),
                "model": "totally-made-up-alias-9000",
                "timeout_seconds": 60,
            },
            raise_on_error=False,
        )
    body = res.structured_content
    assert body["ok"] is False
    # The code alone: an error object carries the backend's own message text.
    code = body["error"]["code"]
    assert code == "invalid_model", code
