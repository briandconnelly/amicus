"""Packaging invariants: version literals agree, classifiers match the floor.

Also covers `amicus.packaging`'s env-var generation: `env_vars` and the migration table are
generated from the declarations, never typed by hand.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import amicus
from amicus import packaging
from amicus.config import GLOBAL_ENV

ROOT = Path(__file__).resolve().parent.parent


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
