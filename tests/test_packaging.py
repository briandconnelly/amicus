"""Packaging invariants: version literals agree, classifiers match the floor.

Also covers `amicus.packaging`: the committed `env_vars` list is asserted EQUAL to the
declarations. Nothing here writes the manifest -- the file is hand-maintained and this is
the check that keeps it from drifting.
"""

from __future__ import annotations

import json
import os
import re
import shutil
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


def test_mcp_json_env_vars_equal_the_declared_list():
    server = _read(".mcp.json")["mcpServers"]["amicus"]
    assert server["env_vars"] == packaging.env_vars_list()


def test_mcp_json_invokes_the_console_script():
    server = _read(".mcp.json")["mcpServers"]["amicus"]
    assert server["command"] == "uvx"
    assert server["args"][-1] == "amicus-mcp"


def test_mcp_json_installs_this_repo_at_a_published_release_tag():
    """The `--from` source was asserted by nothing, and could not have been.

    The slow smoke below substitutes any `git+` argument for a locally built wheel
    before it runs, so it proves the command line's SHAPE and never the source; the test
    above checks only `command` and the trailing console-script name. Rewriting the
    `--from` to a wrong owner, a wrong repo AND a wrong tag left the whole file green,
    confirmed by mutation. That is the one field a user installing from the committed
    manifest actually fetches, so pin its shape: this repo, over git, at some `vX.Y.Z`.

    What this does NOT assert is `pin == amicus.__version__`. Per ADR 0015 the pin names
    an ALREADY-PUBLISHED release, not the version this tree declares, because the
    manifest a fresh install reads lives on `main` and cannot name a tag that does not
    exist yet. Between releases the two are equal; from the release PR until the pin-move
    PR the pin trails by one, and that state is correct rather than a literal left behind.
    The pin must never LEAD the declared version, though -- that would send users to a
    release that has not happened, which is the bug ADR 0015 fixes.
    """
    args = _read(".mcp.json")["mcpServers"]["amicus"]["args"]
    assert "--from" in args, "the manifest must install from an explicit source"
    index = args.index("--from") + 1
    assert index < len(args), "`--from` must be followed by a source, not end the argv"
    source = args[index]
    match = re.fullmatch(
        r"git\+https://github\.com/briandconnelly/amicus\.git@v(\d+\.\d+\.\d+)", source
    )
    assert match, f"unexpected --from source {source!r}"

    def parts(version: str) -> tuple[int, ...]:
        return tuple(int(piece) for piece in version.split("."))

    assert parts(match.group(1)) <= parts(amicus.__version__), (
        f".mcp.json pins v{match.group(1)}, which is newer than the declared "
        f"{amicus.__version__}; the pin names an already-published release and cannot lead it"
    )


def test_readme_example_mirrors_the_mcp_json_pin():
    """README's "Any other MCP client" example is the same pin, and must move with it.

    The example exists to tell a user with some other client to run what the manifest runs,
    so a stale one advertises the PREVIOUS release under a heading that promises parity.
    Nothing bound the two: `docs/RELEASING.md` step 7 said the pin-move PR touches
    `.mcp.json` "and nothing else", and moving only that file left this file green -- which
    is how README kept `@v0.1.0` while the manifest moved on. Binding them here makes the
    runbook's claim checkable instead of a convention someone has to remember.

    This asserts the two agree, never what version they name: the pin trails the declared
    version between a release PR and its pin-move PR, and
    `test_mcp_json_installs_this_repo_at_a_published_release_tag` is what bounds it.
    """
    args = _read(".mcp.json")["mcpServers"]["amicus"]["args"]
    source = args[args.index("--from") + 1]
    readme = (REPO_ROOT / "README.md").read_text()
    pins = set(
        re.findall(r"git\+https://github\.com/briandconnelly/amicus\.git@v\d+\.\d+\.\d+", readme)
    )
    assert pins, "README no longer shows the install source; drop this test or update it"
    assert pins == {source}, (
        f"README pins {sorted(pins)} but .mcp.json pins {source!r}; the pin-move PR must "
        "move both (docs/RELEASING.md step 7)"
    )


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


def test_the_directories_both_manifests_point_at_exist():
    """Both manifests name `./skills/` and `./commands/`; nothing checked they are there.

    Deleting `skills/` failed no test, because every assertion about it compared strings
    inside the JSON to strings in the test. A manifest that points at a directory the
    distribution does not carry is a broken plugin at install time, not at test time."""
    assert (ROOT / "skills").is_dir(), ".claude-plugin/plugin.json points at ./skills/"
    assert (ROOT / "commands").is_dir(), "both manifests point at ./commands/"


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


def _minimal_subprocess_path(command: str) -> str:
    """An allowlisted `PATH`: only the directory holding the resolved `command` binary, plus
    the core system directories `uvx` itself may need (e.g. to exec a system shell).

    A blocklist (stripping only this repo's own `.venv` off the ambient `PATH`) fixes the one
    leak we happened to find, but leaves every OTHER pre-existing `amicus-mcp` install on
    PATH — `~/.local/bin` via `uv tool install amicus`, a pipx install, anything a developer
    did while testing the CLI by hand — able to satisfy the subprocess just as silently. An
    allowlist closes the whole class: the only way `amicus-mcp` can resolve is out of the
    ephemeral environment `uvx` builds from the substituted `--from` source, because nothing
    else is reachable on `PATH` at all."""
    resolved = shutil.which(command)
    assert resolved, f"{command!r} must be resolvable on the ambient PATH to run this test"
    return os.pathsep.join([str(Path(resolved).parent), "/usr/bin", "/bin"])


@pytest.mark.slow
async def test_the_committed_manifest_command_starts_a_real_server(tmp_path):
    """Smoke the manifest's own command line, not an in-process app.

    This substitutes a locally built wheel for the ONE `--from` field and asserts every
    other field — command, console script, arg order — exactly as committed, so it proves
    the command line's shape offline and in a few seconds, without a network fetch.

    It deliberately does not resolve the pinned source. That is not the same limitation it
    used to be: under ADR 0015 the pin names an already-published tag, so `check_release_state`
    can and does prove the tag exists, and `docs/RELEASING.md` step 3 rehearses the real git
    transport pre-tag by substituting the release commit's SHA — verified to resolve. What
    remains unproven here is only that a resolvable ref is reachable from THIS test, which is
    a deliberate trade for a fast, offline, hermetic check.

    `PATH` is reduced to an allowlist (see `_minimal_subprocess_path`) so a broken
    substitution cannot pass by silently resolving some OTHER pre-existing `amicus-mcp`
    install anywhere on the ambient `PATH` instead of the one the substituted `--from`
    source provides."""
    server = json.loads((REPO_ROOT / ".mcp.json").read_text())["mcpServers"]["amicus"]
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(tmp_path), str(REPO_ROOT)],
        check=True,
        capture_output=True,
    )
    wheel = next(tmp_path.glob("*.whl"))
    args = [str(wheel) if a.startswith("git+") else a for a in server["args"]]
    assert args[-1] == "amicus-mcp", "the console script name must survive substitution"
    env = {"PATH": _minimal_subprocess_path(server["command"]), "HOME": str(tmp_path)}
    transport = StdioTransport(command=server["command"], args=args, env=env)
    async with Client(transport) as client:
        tools = await client.list_tools()
    assert len(tools) == 18


def unreleased_section(text: str) -> tuple[str, bool]:
    """The `## [Unreleased]` section's body, and whether a dated section follows it.

    The body stops at the next `## ` heading, so a dated section's own `### Added` can
    never stand in for content the Unreleased stub does not have.
    """
    rest = text.split("\n## [Unreleased]\n", 1)[1]
    next_heading = rest.find("\n## ")
    if next_heading == -1:
        return rest, False
    return rest[:next_heading], True


def unreleased_problems(section: str, *, dated_section_follows: bool) -> list[str]:
    """What is wrong with an Unreleased section, given whether a release follows it."""
    if not section.strip():
        if dated_section_follows:
            return []  # the state `docs/RELEASING.md` step 2 leaves behind
        return ["the Unreleased section is empty and no release has been cut"]
    if "\n### " not in section:
        return ["the Unreleased section has content but no `### ` subsection"]
    return []


def test_changelog_has_an_unreleased_section():
    """PR C rolls `## [Unreleased]` into a dated section, so that heading must exist.

    The release procedure in `docs/RELEASING.md` edits this heading by exact text. A
    renamed or missing heading turns that step into a silent no-op, which is how a
    release ships with an empty changelog entry. So the heading itself is asserted
    unconditionally, spelled exactly as step 2 edits it.

    Whether that section must carry content depends on where in the release cycle the
    file is, and the two states are told apart by whether a dated section follows:

    - No dated section below it: no release has been cut, every change since the last
      one lives here, and an empty stub means someone landed work without a changelog
      entry. That must fail.
    - A dated section below it: `docs/RELEASING.md` step 2 has just rolled Unreleased
      into that section and left "a fresh empty `## [Unreleased]` above it". Empty is
      then the correct state, and asserting otherwise would fail every release PR --
      which is what happened when the 0.1.0 release PR first ran this gate.

    The slice must stop at the next `\n## ` heading either way. A prior version sliced
    to the end of the file, so the dated section's own `### Added` satisfied the
    non-empty check for an Unreleased stub that was genuinely empty. A later version
    computed the slice boundary and then never used it, so the whole
    dated-section-follows branch asserted nothing at all.

    What is NOT asserted, deliberately: that Unreleased is empty when a dated section
    follows. That is true only in the moment after the rollover. Development resumes
    immediately afterwards and legitimately fills Unreleased while the dated section
    sits below it, and the two states are indistinguishable from this file's structure
    alone. Asserting emptiness there would fail every ordinary PR after a release.
    """
    text = (Path(__file__).resolve().parent.parent / "CHANGELOG.md").read_text()
    assert text.startswith("# Changelog\n"), "the file must open with the Keep a Changelog title"
    assert "\n## [Unreleased]\n" in text, "the rollover target heading is missing"
    section, dated_section_follows = unreleased_section(text)
    for problem in unreleased_problems(section, dated_section_follows=dated_section_follows):
        raise AssertionError(problem)


_ROLLED_OVER = (
    "# Changelog\n\n## [Unreleased]\n\n## [0.1.0] - 2026-09-08\n\n### Added\n\n- A thing.\n"
)
_IN_DEVELOPMENT = "# Changelog\n\n## [Unreleased]\n\n### Added\n\n- A thing.\n"
_DEVELOPMENT_AFTER_A_RELEASE = _ROLLED_OVER.replace(
    "## [Unreleased]\n", "## [Unreleased]\n\n### Fixed\n\n- Later work.\n"
)


def test_the_unreleased_slice_stops_at_the_next_section():
    """The regression that started this: a dated section's content is not Unreleased's."""
    section, follows = unreleased_section(_ROLLED_OVER)
    assert follows is True
    assert section.strip() == ""
    assert "### Added" not in section


def test_a_freshly_rolled_over_changelog_is_accepted():
    section, follows = unreleased_section(_ROLLED_OVER)
    assert unreleased_problems(section, dated_section_follows=follows) == []


def test_an_unreleased_section_with_entries_is_accepted_before_and_after_a_release():
    """Development after a release legitimately fills Unreleased above the dated section."""
    for text in (_IN_DEVELOPMENT, _DEVELOPMENT_AFTER_A_RELEASE):
        section, follows = unreleased_section(text)
        assert unreleased_problems(section, dated_section_follows=follows) == [], text


def test_an_empty_unreleased_section_with_no_release_is_rejected():
    """Work landed with no changelog entry, and no release to have rolled it away."""
    text = "# Changelog\n\n## [Unreleased]\n\n[x]: http://e.invalid\n"
    section, follows = unreleased_section(text)
    assert follows is False
    assert unreleased_problems(section, dated_section_follows=follows) != []


@pytest.mark.parametrize("dated_section_follows", [True, False])
def test_unreleased_content_without_a_subsection_is_rejected(dated_section_follows):
    problems = unreleased_problems(
        "\n- A bare bullet.\n", dated_section_follows=dated_section_follows
    )
    assert problems and "subsection" in problems[0]
