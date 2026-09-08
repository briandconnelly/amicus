"""The migration doc's env table is asserted equal to the declarations (spec: Config)."""

from __future__ import annotations

import re
from pathlib import Path

from fastmcp import Client
from tests.support import fakeplugin

from amicus import config, packaging, server
from amicus.config.envspec import LEGACY_REMOVAL_VERSION
from amicus.registry import BackendRegistry
from amicus.tools import TOOL_ORDER

DOC = Path(__file__).resolve().parents[1] / "docs" / "MIGRATION.md"

# Backticks are optional: a call form written as bare prose is just as capable of naming a
# parameter a tool does not have, and requiring the span be a code span let one escape.
_CALL_RE = re.compile(r"`?\b(amicus_[a-z_]+)\(([^)]*)\)")
_KWARG_RE = re.compile(r"(\w+)=")


def _referenced_tool_names() -> set[str]:
    return set(re.findall(r"\bamicus_[a-z_]+\b", DOC.read_text()))


async def _tool_param_names() -> dict[str, set[str]]:
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
    async with Client(app) as c:
        tools = await c.list_tools()
    return {t.name: set(t.input_schema.get("properties", {})) for t in tools}


def _table_rows() -> dict[str, set[str]]:
    """Parse the env table: amicus name -> the legacy names it lists."""
    rows: dict[str, set[str]] = {}
    for line in DOC.read_text().splitlines():
        match = re.match(r"^\|\s*`(AMICUS_[A-Z0-9_]+)`\s*\|([^|]*)\|", line)
        if match:
            legacy = set(re.findall(r"`([A-Z0-9_]+)`", match.group(2)))
            rows[match.group(1)] = legacy
    return rows


def _table_defaults() -> dict[str, str | None]:
    """Parse the env table's third column: amicus name -> the doc's default cell.

    A literal `—` (no default) parses to None so it compares directly against
    `EnvVar.default`, which is None for the same case.
    """
    defaults: dict[str, str | None] = {}
    for line in DOC.read_text().splitlines():
        match = re.match(
            r"^\|\s*`(AMICUS_[A-Z0-9_]+)`\s*\|([^|]*)\|([^|]*)\|",
            line,
        )
        if match:
            cell = match.group(3).strip()
            default_match = re.match(r"^`(.*)`$", cell)
            defaults[match.group(1)] = default_match.group(1) if default_match else None
    return defaults


def test_every_declared_var_appears_in_the_table():
    rows = _table_rows()
    for var in packaging.declared_vars():
        assert var.name in rows, f"{var.name} is declared but missing from MIGRATION.md"


def test_no_invented_vars_in_the_table():
    declared = {v.name for v in packaging.declared_vars()}
    assert set(_table_rows()) <= declared


def test_legacy_names_match_the_declarations_exactly():
    rows = _table_rows()
    for var in packaging.declared_vars():
        assert rows[var.name] == set(var.legacy), (
            f"{var.name}: doc lists {rows[var.name]}, declarations say {set(var.legacy)}"
        )


def test_default_column_matches_the_declarations_exactly():
    """The generation script also emits a `default` column; verify it too.

    The brief's parser only checks names and legacy aliases, leaving `default`
    unverified and free to drift. This closes that gap.
    """
    defaults = _table_defaults()
    for var in packaging.declared_vars():
        assert defaults[var.name] == var.default, (
            f"{var.name}: doc lists default {defaults[var.name]!r}, "
            f"declarations say {var.default!r}"
        )


def test_removal_version_is_stated():
    assert LEGACY_REMOVAL_VERSION in DOC.read_text()


def test_every_sibling_tool_prefix_is_mapped():
    text = DOC.read_text()
    for prefix in ("codex_", "kimi_", "claude_"):
        assert prefix in text, f"no tool map for {prefix}*"


def test_every_referenced_amicus_tool_exists():
    """Every `amicus_*` name mentioned in the doc must be a real, registered tool.

    Catches a mapping row that names a tool that was never registered (see
    `amicus.tools.TOOL_ORDER`), the same class of error as a prior review finding
    where `*_status` rows named a non-existent `amicus_capabilities(backend=...)`
    call."""
    unknown = _referenced_tool_names() - set(TOOL_ORDER)
    assert not unknown, f"MIGRATION.md names tools that do not exist: {sorted(unknown)}"


async def test_call_form_kwargs_are_real_tool_parameters():
    """Every keyword shown in a `tool_name(kw=..., ...)` call form in the doc must
    be a real parameter of that tool's registered schema.

    This is deliberately narrow: it only checks named `kw=` arguments actually
    written in the doc (e.g. `backend="codex"`), not positional args or the
    trailing `...` placeholder, and it only inspects tools the doc names in call
    form at all. That is enough to catch the `amicus_capabilities(backend=...)`
    class of bug (a plausible-looking call to a real tool with a parameter that
    tool does not have) cheaply, without hand-listing every tool's full signature
    here for the parser to duplicate and drift from."""
    params_by_tool = await _tool_param_names()
    for tool_name, args in _CALL_RE.findall(DOC.read_text()):
        if tool_name not in params_by_tool:
            continue  # covered by test_every_referenced_amicus_tool_exists
        for kwarg in _KWARG_RE.findall(args):
            assert kwarg in params_by_tool[tool_name], (
                f"{tool_name}({kwarg}=...) in MIGRATION.md: {kwarg!r} is not a real "
                f"parameter (real params: {sorted(params_by_tool[tool_name])})"
            )


# The hand-written prose around the generated table is not covered by the table
# assertions above, and shipped a claim that contradicted them: it said
# `AMICUS_CODEX_BIN` had "no legacy alias" while the table two lines earlier, and the
# declaration, both carry `CODEX_IN_CLAUDE_CODEX_BIN`.
_NO_ALIAS_CLAIM_RE = re.compile(r"no legacy alias|no sibling equivalent")


def test_prose_no_alias_claims_agree_with_the_declarations():
    """A prose sentence claiming a var has no legacy name must be true of the declaration.

    Only the negative claim is bound, and only per line. Rule 16 puts one sentence on one
    line under `docs/`, so a line carrying "no legacy alias" or "no sibling equivalent"
    is exactly one claim, and every `AMICUS_*` name written on it is inside that claim's
    scope. Positive prose ("`AMICUS_CODEX_BIN` does have one") is deliberately left to
    the generated table, which already asserts every alias exactly; binding free-form
    positive prose would need a parser for how a sentence attributes an alias to a name,
    which is the kind of check that ends up unable to fail."""
    declarations = {var.name: var for var in packaging.declared_vars()}
    checked: list[str] = []
    for line in DOC.read_text().splitlines():
        if line.startswith("|") or not _NO_ALIAS_CLAIM_RE.search(line):
            continue
        for name in re.findall(r"`(AMICUS_[A-Z0-9_]+)`", line):
            assert name in declarations, f"prose names undeclared var {name}"
            checked.append(name)
            assert not declarations[name].legacy, (
                f"MIGRATION.md prose says {name} has no legacy alias, but the "
                f"declaration carries {declarations[name].legacy}"
            )
    assert checked, (
        "known positive for the scan above: no prose no-alias claim was found at all, so "
        "a passing run would prove nothing. Either the sentences were reworded or the "
        "regex no longer matches them."
    )
