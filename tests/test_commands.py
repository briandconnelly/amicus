"""Every command file names only tools that exist, and every paid verb has a command."""

from __future__ import annotations

import re
from pathlib import Path

from fastmcp import Client
from tests.support import fakeplugin

from amicus import config, server
from amicus.registry import BackendRegistry
from amicus.tools import PAIRS, TOOL_ORDER
from amicus.tools._meta import DEPRECATED_TOOLS

COMMANDS = Path(__file__).resolve().parents[1] / "commands" / "amicus"

# A command launches the tool its opening sentence names as "the `amicus_x` MCP tool";
# `dry-run.md` and `jobs.md` drive several tools and name none that way.
_LAUNCH = re.compile(r"`(amicus_[a-z_]+)`\s+MCP\s+tool")

# Async twins that get a command of their own rather than a pointer inside their verb's
# command. Delegation is the verb likeliest to outrun the sync deadline, where a sync call
# made without an idempotency key is terminated with its partial work lost (#67); the other
# twins stay reachable from their verb's command.
ASYNC_TWINS_WITH_A_COMMAND = frozenset({"amicus_delegate_async"})


def _opening_paragraph(path: Path) -> str:
    """The first paragraph after the frontmatter, so a later mention cannot count."""
    body = path.read_text().split("---", 2)[2]
    return body.strip().split("\n\n", 1)[0]


def _launched_tools() -> set[str]:
    return {
        match.group(1)
        for path in COMMANDS.glob("*.md")
        if (match := _LAUNCH.search(_opening_paragraph(path)))
    }


def test_every_referenced_tool_exists():
    referenced = set()
    for path in COMMANDS.glob("*.md"):
        referenced.update(re.findall(r"\bamicus_[a-z_]+\b", path.read_text()))
    unknown = referenced - set(TOOL_ORDER)
    assert not unknown, f"commands name tools that do not exist: {sorted(unknown)}"


def _referenced_tools() -> set[str]:
    referenced: set[str] = set()
    for path in COMMANDS.glob("*.md"):
        referenced.update(re.findall(r"\bamicus_[a-z_]+\b", path.read_text()))
    return referenced


def test_every_live_tool_is_reachable_from_some_command():
    """A deprecated alias is the one exemption: it stays listed for its window, but no
    command should lead anyone to it (#98)."""
    assert set(TOOL_ORDER) - set(DEPRECATED_TOOLS) - _referenced_tools() == set()


def test_no_command_names_a_deprecated_tool():
    assert DEPRECATED_TOOLS, "known positive: an empty table makes the check below vacuous"
    assert _referenced_tools() & set(DEPRECATED_TOOLS) == set()


def test_every_verb_and_listed_twin_has_a_command_that_launches_it():
    """Reachability let #67 through: `delegate.md` names `amicus_delegate_async` in
    prose, so the twin counted as reachable while no command started it."""
    assert {twin for _, twin in PAIRS} >= ASYNC_TWINS_WITH_A_COMMAND
    wanted = {verb for verb, _ in PAIRS} | ASYNC_TWINS_WITH_A_COMMAND
    missing = wanted - _launched_tools()
    assert not missing, f"no command launches {sorted(missing)}"


def test_every_command_is_listed_in_the_readme():
    """The README's slash-command table is kept by hand; a command it omits is one a
    reader never learns exists."""
    readme = (COMMANDS.parents[1] / "README.md").read_text()
    unlisted = sorted(p.stem for p in COMMANDS.glob("*.md") if f"`/amicus:{p.stem}`" not in readme)
    assert not unlisted, f"the README's command table omits {unlisted}"


# `status.md` says to check `status`, not just `enabled`, on an `amicus_backends` result.
# `status` is a real parameter name elsewhere on the surface (`amicus_job_list`'s filter),
# so the scan below sees it, but here it names a RESULT field of a tool the file does
# name. That is correct prose, not a call an agent could make and have rejected, so it is
# excused by file and token rather than by widening the scan.
KNOWN_NON_PARAMETER_TOKENS = {("status.md", "status")}


async def _params_by_tool() -> dict[str, set[str]]:
    """Every registered tool's real parameter names, keyed by tool name.

    All three backends are wired up so no tool is skipped as unavailable."""
    registry = BackendRegistry(
        {
            backend: fakeplugin.make_plugin(backend, egress="x", carriers="argv")
            for backend in ("codex", "kimi", "claude")
        },
        {},
    )
    app = server.create_app(config.settings({}), registry)
    async with Client(app) as client:
        tools = await client.list_tools()
    return {tool.name: set(tool.input_schema.get("properties", {})) for tool in tools}


async def test_no_command_names_a_parameter_its_own_tools_do_not_have():
    """A command file must not teach a call the server would reject.

    `tests/test_migration_doc.py` grew the same check after the migration guide shipped
    an `amicus_capabilities(backend=...)` call that no tool accepts; the command files
    never had one, and shipped two of their own — `amicus_adversarial_review` described
    as taking `question` (its required field is `target`) and `amicus_delegate` described
    as taking `extra_context` (it has no such parameter).

    The scan is deliberately narrow, so it flags call-shape errors and not vocabulary.
    A backticked bare snake_case token counts only if it is a real parameter name of SOME
    registered tool; that keeps result fields (`verdict`, `diff`), enum values
    (`working_tree`), and env names out of it. Such a token is then required to be a
    parameter of at least one `amicus_*` tool the same file names. A file that discusses
    a field a tool does NOT have should not write it as a code span at all, which is why
    the two fixed sentences say "takes no question argument" in prose."""
    params = await _params_by_tool()
    every_param = set().union(*params.values())
    offenders: dict[str, list[str]] = {}
    for path in sorted(COMMANDS.glob("*.md")):
        text = path.read_text()
        named = set(re.findall(r"\bamicus_[a-z_]+\b", text)) & set(params)
        allowed = set().union(*(params[name] for name in named)) if named else set()
        spans = set(re.findall(r"`([^`\n]+)`", text))
        cited = {s for s in spans if re.fullmatch(r"[a-z][a-z0-9_]*", s)} & every_param
        bad = sorted(
            token
            for token in cited - allowed
            if (path.name, token) not in KNOWN_NON_PARAMETER_TOKENS
        )
        if bad:
            offenders[path.name] = bad
    assert not offenders, f"command files cite parameters their own tools do not have: {offenders}"
