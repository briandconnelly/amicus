"""Live tests against the real pi CLI: paid, opt in with

    AMICUS_REQUIRE_LIVE=1 AMICUS_PI_MODEL=<provider/id> uv run pytest -m integration --no-cov \\
        tests/test_pi_live.py

AMICUS_REQUIRE_LIVE=1 makes a missing pi, an unset AMICUS_PI_MODEL or a provider that is not
ready a failure (the publish gate). Every test asserts on the parsed envelope only; failure
messages carry counts and enums, never model prose (pinned by tests/test_live_suite_hygiene.py).
"""

from __future__ import annotations

import subprocess

import pytest
from fastmcp import Client

from amicus import config, server
from amicus.backends.pi import config as pi_config
from amicus.backends.pi import contract as pi_contract
from amicus.registry import BackendRegistry

pytestmark = pytest.mark.integration


def _app():
    settings = config.settings()
    return server.create_app(settings, BackendRegistry.load(("pi",), entry_points=()))


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _repo(path):
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "t@t.co")
    _git(path, "config", "user.name", "t")
    (path / "m.py").write_text("def f(xs):\n    return xs[0]\n")
    _git(path, "add", "-A")
    _git(path, "commit", "-qm", "init")


async def test_backends_reports_pi_ready_live(live_pi):
    async with Client(_app()) as c:
        body = (await c.call_tool("amicus_backends", {"backend": "pi"})).structured_content
    entry = body["backends"][0]
    assert entry["available"] is True and entry["status"]["installed"] is True
    assert entry["status"]["authenticated"] is True, entry["status"]
    # The evidence must vouch for the newest minor the contract claims, not merely a supported
    # one, so a release that adds a minor cannot ship on evidence taken on an older CLI.
    installed = pi_config.parse_version(entry["status"]["version"])
    assert installed == max(pi_contract.SUPPORTED_VERSIONS), entry["status"]
    assert entry["status"]["warnings"] == [], entry["status"]


async def test_consult_live(live_pi, tmp_path):
    _repo(tmp_path)
    async with Client(_app()) as c:
        res = await c.call_tool(
            "amicus_consult",
            {
                "backend": "pi",
                "question": "Reply in one sentence: what does DRY mean?",
                "workspace_root": str(tmp_path),
                "timeout_seconds": 150,
            },
            raise_on_error=False,
        )
    body = res.structured_content
    assert body["ok"] is True, body.get("error", {}).get("code")
    assert body["summary"]
    assert body["meta"]["backend"] == "pi"
    assert body["meta"]["usage"] is not None


async def test_review_changes_live(live_pi, tmp_path):
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
            {"backend": "pi", "workspace_root": str(tmp_path), "timeout_seconds": 150},
            raise_on_error=False,
        )
    body = res.structured_content
    assert body["ok"] is True, body.get("error", {}).get("code")
    assert body["review_status"] == "completed"
    assert body["verdict"] in ("concerns", "fail", "pass", "unknown")
    assert body["summary"]
    assert body["meta"]["backend"] == "pi"
    assert body["meta"]["usage"] is not None


async def test_delegate_live(live_pi, tmp_path):
    _repo(tmp_path)
    before = (tmp_path / "m.py").read_text()
    async with Client(_app()) as c:
        res = await c.call_tool(
            "amicus_delegate",
            {
                "backend": "pi",
                "task": "Create a file named hello.txt containing the word hello.",
                "workspace_root": str(tmp_path),
                "timeout_seconds": 180,
            },
            raise_on_error=False,
        )
    body = res.structured_content
    assert body["ok"] is True, body.get("error", {}).get("code")
    assert body["summary"]
    assert body["diff"] and (tmp_path / "m.py").read_text() == before
    assert not (tmp_path / "hello.txt").exists()
    assert body["meta"]["backend"] == "pi"
    assert body["meta"]["usage"] is not None
    listed = subprocess.run(
        ["git", "worktree", "list"], cwd=tmp_path, capture_output=True, text=True, check=True
    ).stdout
    assert listed.strip().count("\n") == 0
