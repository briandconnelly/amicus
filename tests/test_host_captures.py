"""The host captures (M5): each v1 host connected to amicus with AMICUS_TASKS=1 and called the
free amicus_backends; the connection line amicus logged is the evidence behind the capability
summary's claim that a handshake-era host always gets the plain result."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from mcp.types.version import MODERN_PROTOCOL_VERSIONS

CAPTURES = Path("docs/host-captures")
HOSTS = ["claude-code"]  # Task 7 adds "codex"
LINE = re.compile(
    r"tools/call amicus_backends: protocol=(?P<protocol>\S+) client=(?P<client>\S+) "
    r"tasks_negotiated=(?P<tasks>True|False)$"
)


def _capture_dir(host: str) -> Path:
    [version_dir] = [p for p in (CAPTURES / host).iterdir() if p.is_dir()]
    return version_dir


@pytest.mark.parametrize("host", HOSTS)
def test_each_host_capture_shows_a_handshake_era_plain_call(host):
    version_dir = _capture_dir(host)
    assert (version_dir / "FINDINGS.md").exists()
    matches = [
        m
        for m in (
            LINE.search(line) for line in (version_dir / "connection.log").read_text().splitlines()
        )
        if m
    ]
    assert matches, f"{host}: no tools/call line for amicus_backends in connection.log"
    for m in matches:
        assert m["protocol"] not in MODERN_PROTOCOL_VERSIONS, m.group(0)
        assert m["tasks"] == "False", m.group(0)
        assert not m["client"].startswith("unknown/"), m.group(0)


def test_the_capture_regex_accepts_a_known_positive_and_rejects_a_modern_tasked_line():
    good = (
        "2026-09-07 12:00:00,000 DEBUG amicus.middleware: tools/call amicus_backends: "
        "protocol=2025-06-18 client=claude-code/2.1.263 tasks_negotiated=False"
    )
    m = LINE.search(good)
    assert m and m["protocol"] not in MODERN_PROTOCOL_VERSIONS and m["tasks"] == "False"
    modern = (
        "tools/call amicus_backends: protocol=2026-07-28 client=unknown/unknown "
        "tasks_negotiated=True"
    )
    m2 = LINE.search(modern)
    assert m2 and m2["protocol"] in MODERN_PROTOCOL_VERSIONS and m2["tasks"] == "True"
