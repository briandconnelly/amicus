"""Live tests against the real claude CLI: paid, opt in with

    AMICUS_REQUIRE_LIVE=1 uv run pytest -m integration --no-cov tests/test_claude_live.py

AMICUS_REQUIRE_LIVE=1 makes a missing or logged-out claude a failure (the publish gate). Every
test asserts on the parsed envelope only; failure messages carry counts, enums and tool names,
never model prose (pinned by tests/test_claude_live_hygiene.py)."""

from __future__ import annotations

import re
import subprocess

import pytest
from fastmcp import Client

from amicus import config, server
from amicus.registry import BackendRegistry

pytestmark = pytest.mark.integration

_VERDICTS = ("pass", "concerns", "fail", "unknown")

# Issue #62. The gate pins a lower reasoning effort than the product default
# (`contract.DEFAULT_EFFORT`, xhigh) because at xhigh these calls are not bounded: a 37-57s median
# with a tail that runs away rather than finishing late. On 2026-09-13 (claude 2.1.270) one xhigh
# consult ran 535s and stopped only at its $1.00 budget, having spent $1.66. The same consult and
# review at medium went 10 for 10 in 15-40s at about $0.09 each, with findings every time. This
# gate proves amicus's plumbing against the real CLI, not the model's depth; the default
# `--effort xhigh` token is pinned hermetically by tests/test_claude_adapter.py.
_LIVE_EFFORT = "medium"
# 4.5x the slowest medium run measured (40.0s): room for a slow draw, and still a bound on a
# runaway, which is what a live budget is for.
_TIMEOUT_S = 180


_SHAPE_KEYS = ("findings", "questions", "next_steps", "verdict", "confidence", "review_status")


def _shape(body):
    """Envelope-only failure diagnostics: list lengths and enums, never the model's prose."""
    return {k: (len(v) if isinstance(v, list) else v) for k, v in body.items() if k in _SHAPE_KEYS}


def _app():
    settings = config.settings()
    return server.create_app(settings, BackendRegistry.load(("claude",), entry_points=()))


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _repo(path):
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "t@t.co")
    _git(path, "config", "user.name", "t")
    (path / "m.py").write_text("def average(values):\n    return sum(values) / len(values)\n")
    _git(path, "add", "-A")
    _git(path, "commit", "-qm", "init")


async def test_backends_reports_claude_ready_live(live_claude):
    async with Client(_app()) as c:
        body = (await c.call_tool("amicus_backends", {"backend": "claude"})).structured_content
        models = (await c.call_tool("amicus_models", {"backend": "claude"})).structured_content
    entry = body["backends"][0]
    assert entry["available"] is True and entry["status"]["installed"] is True
    assert entry["status"]["authenticated"] is True, entry["status"]
    assert entry["status"]["version"].startswith("2."), entry["status"]
    assert entry["status"]["warnings"] == [], entry["status"]
    assert models["source"] == "static" and models["models"]


async def test_consult_in_a_repo_spends_and_reports_it_live(live_claude, tmp_path):
    _repo(tmp_path)
    async with Client(_app()) as c:
        res = await c.call_tool(
            "amicus_consult",
            {
                "backend": "claude",
                "question": (
                    "Review this function for correctness. Callers require it to return 0.0 for "
                    "an empty list.\n\ndef average(values):\n    return sum(values) / len(values)\n"
                ),
                "workspace_root": str(tmp_path),
                "timeout_seconds": _TIMEOUT_S,
                "reasoning_effort": _LIVE_EFFORT,
            },
            raise_on_error=False,
        )
    body = res.structured_content
    assert body["ok"] is True, body.get("error", {}).get("code")
    assert body["meta"]["reasoning_effort"] == _LIVE_EFFORT
    assert body["summary"] and body["meta"]["session_id"] and body["meta"]["job_id"]
    cost = body["meta"]["usage"]["cost_usd"]
    assert cost > 0, cost  # a real run really spent
    assert body["meta"]["backend_details"] == {
        "config_mode": "inherit",
        "access": "toolless",
        "max_budget_usd": 1.0,
    }
    assert body["findings"] or body["next_steps"] or body["questions"], _shape(body)


async def test_toolless_is_enforced_live(live_claude, tmp_path):
    _repo(tmp_path)
    async with Client(_app()) as c:
        res = await c.call_tool(
            "amicus_consult",
            {
                "backend": "claude",
                "question": (
                    "Reply with ONLY a comma-separated list of the exact names of the tools "
                    "available to you in this session, or the single word NONE if you have no "
                    "tools. No other words."
                ),
                "workspace_root": str(tmp_path),
                "timeout_seconds": _TIMEOUT_S,
                "reasoning_effort": _LIVE_EFFORT,
            },
            raise_on_error=False,
        )
    body = res.structured_content
    assert body["ok"] is True, body.get("error", {}).get("code")
    assert body["meta"]["reasoning_effort"] == _LIVE_EFFORT
    names = {t.strip().lower() for t in re.split(r"[,\s]+", body["summary"]) if t.strip()}
    leaked = names & {"bash", "write", "edit", "read", "glob", "grep", "shell"}
    assert not leaked, sorted(leaked)


async def test_review_changes_live(live_claude, tmp_path):
    _repo(tmp_path)
    (tmp_path / "m.py").write_text(
        "def average(values):\n    if not values:\n        return 0\n"
        "    return sum(values) / len(values)\n"
    )
    async with Client(_app()) as c:
        res = await c.call_tool(
            "amicus_review_changes",
            {
                "backend": "claude",
                "workspace_root": str(tmp_path),
                "timeout_seconds": _TIMEOUT_S,
                "reasoning_effort": _LIVE_EFFORT,
            },
            raise_on_error=False,
        )
    body = res.structured_content
    assert body["ok"] is True, body.get("error", {}).get("code")
    assert body["meta"]["reasoning_effort"] == _LIVE_EFFORT
    assert body["review_status"] == "completed" and body["verdict"] in _VERDICTS
    assert body["meta"]["context_summary"]["files_changed"] == 1


async def test_adversarial_review_live(live_claude, tmp_path):
    async with Client(_app()) as c:
        res = await c.call_tool(
            "amicus_adversarial_review",
            {
                "backend": "claude",
                "target": (
                    "We will ship the payment webhook handler without idempotency keys because "
                    "the provider promises at-most-once delivery."
                ),
                "evidence": "The provider's docs say retries happen only on a non-2xx response.",
                "workspace_root": str(tmp_path),
                "timeout_seconds": _TIMEOUT_S,
                "reasoning_effort": _LIVE_EFFORT,
            },
            raise_on_error=False,
        )
    body = res.structured_content
    assert body["ok"] is True, body.get("error", {}).get("code")
    assert body["meta"]["reasoning_effort"] == _LIVE_EFFORT
    assert body["tool"] == "amicus_adversarial_review" and body["review_status"] == "completed"
    assert body["verdict"] in _VERDICTS and body["summary"]
    assert body["context_summary"] is None and body["meta"].get("instructions_append") is None
    assert body["findings"] or body["questions"] or body["next_steps"], _shape(body)


async def test_safe_mode_consult_live(live_claude, tmp_path):
    _repo(tmp_path)
    async with Client(_app()) as c:
        res = await c.call_tool(
            "amicus_consult",
            {
                "backend": "claude",
                "question": "Reply in one sentence: what does DRY mean?",
                "workspace_root": str(tmp_path),
                "timeout_seconds": _TIMEOUT_S,
                "reasoning_effort": _LIVE_EFFORT,
                "backend_options": {"config_mode": "safe"},
            },
            raise_on_error=False,
        )
    body = res.structured_content
    assert body["ok"] is True, body.get("error", {}).get("code")
    assert body["meta"]["reasoning_effort"] == _LIVE_EFFORT
    assert body["summary"] and body["meta"]["backend_details"]["config_mode"] == "safe"
