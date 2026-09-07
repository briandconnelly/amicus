"""Packaging invariants: version literals agree, classifiers match the floor.

Also covers `amicus.packaging`'s env-var generation: `env_vars` and the migration table are
generated from the declarations, never typed by hand.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tomllib
from pathlib import Path

import pytest
from fastmcp import Client
from fastmcp.client.transports import StdioTransport

import amicus
from amicus import packaging
from amicus.config import GLOBAL_ENV
from amicus.server import create_app

ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = ROOT


def _read(relative: str) -> dict:
    return json.loads((REPO_ROOT / relative).read_text())


def _pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_version_literal_matches_package():
    assert _pyproject()["project"]["version"] == amicus.__version__
    assert re.fullmatch(r"\d+\.\d+\.\d+", amicus.__version__)


def test_python_floor_matches_classifiers():
    project = _pyproject()["project"]
    floor = project["requires-python"]
    assert floor == ">=3.11"
    minors = sorted(
        int(c.rsplit(".", 1)[1])
        for c in project["classifiers"]
        if c.startswith("Programming Language :: Python :: 3.")
    )
    assert minors[0] == 11
    assert minors == list(range(minors[0], minors[-1] + 1))


def test_runtime_dependencies_are_exactly_the_spec_set():
    deps = _pyproject()["project"]["dependencies"]
    names = sorted(re.split(r"[<>=!\[]", d, maxsplit=1)[0] for d in deps)
    assert names == ["anyio", "fastmcp", "mcp", "pontonier", "pydantic"]
    assert "pontonier==0.9.0" in deps


def test_console_script_points_at_server_main():
    assert _pyproject()["project"]["scripts"] == {"amicus-mcp": "amicus.server:main"}


def test_declared_names_cover_the_global_namespace():
    names = packaging.declared_env_names()
    for name in GLOBAL_ENV.names():
        assert name in names


def test_declared_names_cover_every_in_tree_backend():
    names = packaging.declared_env_names()
    for expected in ("AMICUS_CODEX_BIN", "AMICUS_KIMI_BIN", "AMICUS_CLAUDE_BIN"):
        assert expected in names


def test_declared_names_are_sorted_and_unique():
    names = packaging.declared_env_names()
    assert list(names) == sorted(set(names))


def test_vendor_auth_includes_the_claude_credentials():
    assert packaging.vendor_auth_env_names() == ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")


EXPECTED_ENV_VARS = [
    # Pinned by review, not derived: comparing a generated file to its own generator is not an
    # oracle. This list is the independent expectation; the generator must reproduce it exactly.
    # 35 declared (16 global + 6 codex + 6 kimi + 7 claude) + 2 vendor = 37.
    "AMICUS_ALLOW_CWD_WORKSPACE",
    "AMICUS_BACKENDS",
    "AMICUS_CLAUDE_ACCESS",
    "AMICUS_CLAUDE_BIN",
    "AMICUS_CLAUDE_CONFIG_MODE",
    "AMICUS_CLAUDE_MAX_BUDGET_USD",
    "AMICUS_CLAUDE_MODEL",
    "AMICUS_CLAUDE_REASONING_EFFORT",
    "AMICUS_CLAUDE_SUPPORTED_MAJORS",
    "AMICUS_CODEX_BIN",
    "AMICUS_CODEX_EXTRA_ARGS",
    "AMICUS_CODEX_ISOLATION",
    "AMICUS_CODEX_MODEL",
    "AMICUS_CODEX_REASONING_EFFORT",
    "AMICUS_CODEX_SUPPORTED_VERSIONS",
    "AMICUS_GIT_TIMEOUT_SECONDS",
    "AMICUS_HOST_NAME",
    "AMICUS_JOB_MAX_COUNT",
    "AMICUS_JOB_MAX_SECONDS",
    "AMICUS_JOB_TTL",
    "AMICUS_KIMI_BIN",
    "AMICUS_KIMI_EXTRA_ARGS",
    "AMICUS_KIMI_ISOLATION",
    "AMICUS_KIMI_MODEL",
    "AMICUS_KIMI_REASONING_EFFORT",
    "AMICUS_KIMI_SUPPORTED_VERSIONS",
    "AMICUS_LOG_FILE",
    "AMICUS_LOG_LEVEL",
    "AMICUS_MAX_DELEGATE_DIFF_BYTES",
    "AMICUS_MAX_INPUT_BYTES",
    "AMICUS_MAX_OUTPUT_BYTES",
    "AMICUS_STATE_DIR",
    "AMICUS_TASKS",
    "AMICUS_TASKS_BACKEND_URL",
    "AMICUS_TIMEOUT_SECONDS",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
]


def test_env_vars_list_matches_the_pinned_expectation():
    """The independent oracle. If this fails, a declaration changed: review the diff and
    update the pin deliberately — never regenerate the pin from the generator."""
    assert packaging.env_vars_list() == EXPECTED_ENV_VARS


def test_env_vars_list_is_declared_plus_vendor():
    combined = set(packaging.declared_env_names()) | set(packaging.vendor_auth_env_names())
    assert set(packaging.env_vars_list()) == combined
    assert packaging.env_vars_list() == sorted(combined)


def test_declared_names_are_all_amicus_namespaced():
    """Declared names are AMICUS_*; vendor credentials are a separate, deliberate list.

    Keeping the two apart is the point: a vendor name silently entering `declared_env_names()`
    would put a credential in the migration table as if amicus declared it."""
    assert all(name.startswith("AMICUS_") for name in packaging.declared_env_names())
    assert not any(n.startswith("AMICUS_") for n in packaging.vendor_auth_env_names())


def test_mcp_json_env_vars_equal_the_generated_list():
    server = _read(".mcp.json")["mcpServers"]["amicus"]
    assert server["env_vars"] == packaging.env_vars_list()


def test_mcp_json_invokes_the_console_script():
    server = _read(".mcp.json")["mcpServers"]["amicus"]
    assert server["command"] == "uvx"
    assert server["args"][-1] == "amicus-mcp"


def test_mcp_json_has_no_unexpanded_placeholders():
    """The ${VAR} check the spec keeps: env_vars is a passthrough list, not a value map."""
    raw = (REPO_ROOT / ".mcp.json").read_text()
    assert "${" not in raw


def test_both_plugin_manifests_point_at_the_one_mcp_json():
    assert _read(".claude-plugin/plugin.json")["mcpServers"] == "./.mcp.json"
    assert _read(".codex-plugin/plugin.json")["mcpServers"] == "./.mcp.json"


def test_plugin_manifest_version_matches_the_package():
    from importlib.metadata import version

    package_version = version("amicus")
    assert _read(".claude-plugin/plugin.json")["version"] == package_version
    assert _read(".codex-plugin/plugin.json")["version"] == package_version


def test_claude_manifest_declares_skills_and_commands():
    manifest = _read(".claude-plugin/plugin.json")
    assert manifest["skills"] == "./skills/"
    assert manifest["commands"] == "./commands/"


async def test_server_boots_in_process_with_no_amicus_env_set(monkeypatch):
    """A server-unit boot test: the app comes up and lists 18 tools with no AMICUS_* set.

    This does NOT test the manifest. It reads no `.mcp.json`, starts no `uvx`, and applies no
    `env_vars` list. Step 8 is the test that covers the manifest; this one only rules out an
    in-process regression first, because it is the cheaper of the two to diagnose."""
    for name in packaging.declared_env_names():
        monkeypatch.delenv(name, raising=False)
    async with Client(create_app()) as client:
        tools = await client.list_tools()
    assert len(tools) == 18


def _path_without_repo_venv() -> str:
    """The ambient `PATH` with every entry under this checkout stripped out.

    `uv run pytest` prepends this repo's dev `.venv/bin` to `PATH`, and that `.venv` already
    has a real `amicus-mcp` installed (the dev/editable install this repo's own tooling
    uses). If the subprocess below inherited that PATH unfiltered, a broken `--from`
    substitution — wrong wheel, wrong console script, wrong package entirely — could still
    resolve `amicus-mcp` by falling through to the dev venv's copy on PATH, and the test
    would pass for the wrong reason. Stripping those entries forces the only possible
    `amicus-mcp` to be the one `uvx` builds from the substituted `--from` source."""
    repo_root = REPO_ROOT.resolve()
    kept = [
        entry
        for entry in os.environ["PATH"].split(os.pathsep)
        if entry and not Path(entry).resolve().is_relative_to(repo_root)
    ]
    return os.pathsep.join(kept)


@pytest.mark.slow
async def test_the_committed_manifest_command_starts_a_real_server(tmp_path):
    """Smoke the manifest's own command line, not an in-process app.

    The committed `--from` names a git tag that does not exist until release, so this
    substitutes a locally built wheel for that ONE field and asserts every other field —
    command, console script, arg order — exactly as committed. What stays unproven until
    release is the tag's resolvability; that is the release workflow's gate, and Task 10's
    ADR records it as a known limit of the M6 claim.

    `PATH` is stripped of this repo's own dev `.venv` (see `_path_without_repo_venv`) so a
    broken substitution cannot pass by silently resolving the dev venv's already-installed
    `amicus-mcp` instead of the one the substituted `--from` source provides."""
    server = json.loads((REPO_ROOT / ".mcp.json").read_text())["mcpServers"]["amicus"]
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(tmp_path), str(REPO_ROOT)],
        check=True,
        capture_output=True,
    )
    wheel = next(tmp_path.glob("*.whl"))
    args = [str(wheel) if a.startswith("git+") else a for a in server["args"]]
    assert args[-1] == "amicus-mcp", "the console script name must survive substitution"
    env = {"PATH": _path_without_repo_venv(), "HOME": str(tmp_path)}
    transport = StdioTransport(command=server["command"], args=args, env=env)
    async with Client(transport) as client:
        tools = await client.list_tools()
    assert len(tools) == 18
