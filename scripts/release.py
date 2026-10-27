#!/usr/bin/env python
"""Script the mechanical parts of `docs/RELEASING.md`, one subcommand per step.

`prepare X.Y.Z` makes the edits of the rule-19 release PR (AGENTS.md rule 19, RELEASING step 2):

- every version literal moves to X.Y.Z: `pyproject.toml`, `src/amicus/__init__.py`, both
  `plugin.json` files, `.mcp.json`'s `--from` pin (to `vX.Y.Z`, ADR 0031) and README's
  "Any other MCP client" example, which mirrors that pin;
- `CHANGELOG.md`'s `## [Unreleased]` section becomes `## [X.Y.Z] - <UTC date>` under a fresh
  empty `## [Unreleased]`, and the footer follows the roll: `[Unreleased]` compares
  `vX.Y.Z...HEAD` and a new `[X.Y.Z]` compares the previous release's tag with `vX.Y.Z` (#211);
- `uv lock` regenerates `uv.lock`, which mirrors the version rather than declaring it;
- then `check_release_state.check_tree_pre_tag` reports on the result: every check the release
  predicate runs on the tree, except that the pinned tag exists, which it cannot yet.

It refuses a version that is not strictly greater than the declared one, a dirty tree, the
`main` branch, and an empty `## [Unreleased]` section. `--check` prints the planned edits and
writes nothing.

What it never does: touch `.claude-plugin/marketplace.json` (rules 19 and 24; it asserts the
file is byte-identical afterwards), create or push a tag, commit, push or merge. Choosing the
version, the release notes, README's prose naming the current release, `docs/MIGRATION.md`,
the rule-18 carrier re-check and the live gates stay with the maintainer.

Usage:
    uv run python scripts/release.py prepare X.Y.Z [--check]

Exits 0 on success, 1 on a refusal or a failed check, printing each problem.
Pure stdlib, like `check_release_state.py`; it runs `git` and `uv`.
"""

from __future__ import annotations

import argparse
import datetime as dt
import difflib
import importlib.util
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_release_state():
    """Import `check_release_state` by path; `scripts/` is not an importable package."""
    path = Path(__file__).resolve().parent / "check_release_state.py"
    spec = importlib.util.spec_from_file_location("check_release_state", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


release_state = _load_release_state()

MARKETPLACE_PATH = release_state.MARKETPLACE_PATH
CHANGELOG_PATH = "CHANGELOG.md"
README_PATH = "README.md"
PLUGIN_MANIFESTS = (".claude-plugin/plugin.json", ".codex-plugin/plugin.json")

_PYPROJECT_VERSION_RE = re.compile(r'^version = "(?P<version>[^"]+)"$', re.MULTILINE)
_INIT_VERSION_RE = re.compile(r'^__version__ = "(?P<version>[^"]+)"$', re.MULTILINE)
_MANIFEST_VERSION_RE = re.compile(r'"version":\s*"(?P<version>[^"]+)"')
_PIN_RE = re.compile(
    r"git\+https://github\.com/briandconnelly/amicus\.git@v(?P<version>\d+\.\d+\.\d+)"
)
_UNRELEASED_RE = re.compile(r"^## \[Unreleased\][ \t]*$", re.MULTILINE)
_NEXT_HEADING_RE = re.compile(r"^## ", re.MULTILINE)
_LINK_DEFINITION_RE = re.compile(
    r"^ {0,3}\[(?P<label>[^\]]+)\]:[ \t]*(?P<url>\S+)[ \t]*$", re.MULTILINE
)


class Refusal(Exception):
    """A precondition the release PR does not meet; nothing has been written."""


def utc_date(moment: dt.datetime) -> dt.date:
    """The UTC calendar date of an aware `moment`: the changelog's date, never the local one.

    The tag, the publish run and the PyPI record are all stamped in UTC (RELEASING step 2).
    """
    if moment.tzinfo is None:
        raise ValueError("utc_date needs an aware datetime; a naive one has no UTC date")
    return moment.astimezone(dt.UTC).date()


@dataclass
class Context:
    """What every subcommand runs against. Tests replace the runners and the clock."""

    repo_root: Path = REPO_ROOT
    git: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run
    today: Callable[[], dt.date] = field(default=lambda: utc_date(dt.datetime.now(dt.UTC)))

    def git_out(self, *args: str) -> subprocess.CompletedProcess[str]:
        return self.git(
            ["git", *args], cwd=self.repo_root, capture_output=True, text=True, check=False
        )


@dataclass(frozen=True)
class FileEdit:
    path: str
    before: str
    after: str
    summary: str


# --- prepare: the edits -----------------------------------------------------------------


def _sub_one(pattern: re.Pattern[str], text: str, replacement: str, *, where: str) -> str:
    """Replace the single match of `pattern`; anything else is a refusal, not a guess."""
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise Refusal(f"{where}: expected exactly one version literal, found {len(matches)}")
    match = matches[0]
    return text[: match.start()] + replacement + text[match.end() :]


def _pin(version: str) -> str:
    return f"git+https://github.com/briandconnelly/amicus.git@v{version}"


def _literal_edits(ctx: Context, old: str, new: str) -> list[FileEdit]:
    edits: list[FileEdit] = []

    def read(relative: str) -> str:
        return (ctx.repo_root / relative).read_text(encoding="utf-8")

    text = read("pyproject.toml")
    edits.append(
        FileEdit(
            "pyproject.toml",
            text,
            _sub_one(_PYPROJECT_VERSION_RE, text, f'version = "{new}"', where="pyproject.toml"),
            f'version = "{old}" -> "{new}"',
        )
    )
    relative = "src/amicus/__init__.py"
    text = read(relative)
    edits.append(
        FileEdit(
            relative,
            text,
            _sub_one(_INIT_VERSION_RE, text, f'__version__ = "{new}"', where=relative),
            f'__version__ = "{old}" -> "{new}"',
        )
    )
    for relative in PLUGIN_MANIFESTS:
        text = read(relative)
        edits.append(
            FileEdit(
                relative,
                text,
                _sub_one(_MANIFEST_VERSION_RE, text, f'"version": "{new}"', where=relative),
                f'"version": "{old}" -> "{new}"',
            )
        )
    text = read(".mcp.json")
    edits.append(
        FileEdit(
            ".mcp.json",
            text,
            _sub_one(_PIN_RE, text, _pin(new), where=".mcp.json's --from pin"),
            f"--from pin -> {_pin(new)}",
        )
    )
    # README's example mirrors the pin (tests/test_packaging.py binds the two), so every
    # pin README shows moves; prose naming the current release is the maintainer's to edit.
    text = read(README_PATH)
    pins = _PIN_RE.findall(text)
    if not pins:
        raise Refusal(f"{README_PATH} shows no install pin to move")
    edits.append(
        FileEdit(
            README_PATH,
            text,
            _PIN_RE.sub(_pin(new), text),
            f"{len(pins)} install pin(s) -> {_pin(new)}",
        )
    )
    return edits


def _link_key(label: str) -> str:
    return " ".join(label.split()).casefold()


def roll_changelog(text: str, version: str, date: dt.date) -> str:
    """`text` with `## [Unreleased]` rolled into `## [version] - date` and the footer moved.

    The previous release is the first dated heading below Unreleased, which is exactly where
    `check_release_state._check_changelog_links` looks for it.
    """
    headings = list(_UNRELEASED_RE.finditer(text))
    if len(headings) != 1:
        raise Refusal(
            f"{CHANGELOG_PATH} has {len(headings)} `## [Unreleased]` headings, expected 1"
        )
    heading = headings[0]
    # The section ends at the next heading or, for a first release, at the footer.
    ends = [
        match.start()
        for match in (
            _NEXT_HEADING_RE.search(text, heading.end()),
            _LINK_DEFINITION_RE.search(text, heading.end()),
        )
        if match
    ]
    body_end = min(ends, default=len(text))
    body = text[heading.end() : body_end]
    if not body.strip():
        raise Refusal(
            f"{CHANGELOG_PATH}'s `## [Unreleased]` section is empty; there is nothing to release"
        )

    dated = f"## [{version}] - {date.isoformat()}"
    rolled = text[: heading.end()] + "\n\n" + dated + "\n\n" + body.lstrip("\n") + text[body_end:]

    previous = release_state._DATED_HEADING_RE.search(rolled, rolled.index(dated) + len(dated))
    repo = release_state.CHANGELOG_REPO_URL
    release_url = (
        f"{repo}/compare/v{previous['version']}...v{version}"
        if previous
        else f"{repo}/releases/tag/v{version}"
    )

    definitions = list(_LINK_DEFINITION_RE.finditer(rolled))
    for match in definitions:
        if _link_key(match["label"]) == _link_key(version):
            raise Refusal(f"{CHANGELOG_PATH} already defines a `[{version}]:` link")
    unreleased = [m for m in definitions if _link_key(m["label"]) == "unreleased"]
    if len(unreleased) != 1:
        raise Refusal(
            f"{CHANGELOG_PATH} has {len(unreleased)} `[Unreleased]:` link definitions, expected 1"
        )
    link = unreleased[0]
    footer = f"[Unreleased]: {repo}/compare/v{version}...HEAD\n[{version}]: {release_url}"
    return rolled[: link.start()] + footer + rolled[link.end() :]


def plan_prepare(ctx: Context, version: str) -> list[FileEdit]:
    """Every edit `prepare` would write, computed without writing anything.

    Raises `Refusal` for a precondition the tree itself fails; `_refuse_repository_state`
    covers the ones that need git.
    """
    if not release_state.VERSION_RE.match(version):
        raise Refusal(f"version {version!r} is not X.Y.Z")
    declared = release_state.declared_version(ctx.repo_root)
    if not release_state.VERSION_RE.match(declared):
        raise Refusal(f"pyproject.toml declares {declared!r}, which is not X.Y.Z")
    if release_state._parts(version) <= release_state._parts(declared):
        raise Refusal(
            f"{version} is not greater than the declared {declared}; a release PR only moves "
            "the version forward"
        )
    edits = _literal_edits(ctx, declared, version)
    text = (ctx.repo_root / CHANGELOG_PATH).read_text(encoding="utf-8")
    date = ctx.today()
    edits.append(
        FileEdit(
            CHANGELOG_PATH,
            text,
            roll_changelog(text, version, date),
            f"## [Unreleased] -> ## [{version}] - {date.isoformat()} (UTC), footer links moved",
        )
    )
    assert all(edit.path != MARKETPLACE_PATH for edit in edits), "rule 24: never the pointer"
    return edits


def _refuse_repository_state(ctx: Context) -> None:
    branch = ctx.git_out("symbolic-ref", "--quiet", "--short", "HEAD")
    if branch.returncode == 0 and branch.stdout.strip() == "main":
        raise Refusal("on branch main; prepare the release on its own branch (AGENTS.md rule 8)")
    status = ctx.git_out("status", "--porcelain")
    if status.returncode != 0:
        raise Refusal(f"could not read the tree's status: {status.stderr.strip()}")
    if status.stdout.strip():
        raise Refusal(
            "the tree is not clean; commit or stash first, so the release PR holds only "
            "the release edits"
        )


# --- prepare: the command ---------------------------------------------------------------


def cmd_prepare(ctx: Context, args: argparse.Namespace) -> int:
    version: str = args.version
    marketplace = ctx.repo_root / MARKETPLACE_PATH
    marketplace_before = marketplace.read_bytes()
    try:
        _refuse_repository_state(ctx)
        edits = plan_prepare(ctx, version)
    except Refusal as exc:
        print(f"refusing to prepare {version}: {exc}", file=sys.stderr)
        return 1

    if args.check:
        print(f"prepare {version} would make these edits (--check: nothing written):")
        for edit in edits:
            sys.stdout.writelines(
                difflib.unified_diff(
                    edit.before.splitlines(keepends=True),
                    edit.after.splitlines(keepends=True),
                    f"a/{edit.path}",
                    f"b/{edit.path}",
                    n=1,
                )
            )
        print("then run `uv lock` and the pre-tag release-state checks.")
        return 0

    for edit in edits:
        (ctx.repo_root / edit.path).write_text(edit.after, encoding="utf-8")
        print(f"  {edit.path}: {edit.summary}")

    problems: list[str] = []
    try:
        lock = ctx.run(
            ["uv", "lock"], cwd=ctx.repo_root, capture_output=True, text=True, check=False
        )
    except OSError as exc:
        problems.append(f"could not run `uv lock`: {exc}")
    else:
        if lock.returncode != 0:
            detail = (lock.stderr or lock.stdout or "").strip().splitlines()
            problems.append(f"`uv lock` failed: {detail[-1] if detail else lock.returncode}")
        else:
            print("  uv.lock: regenerated with `uv lock`")

    if not problems:
        problems += release_state.check_tree_pre_tag(
            version, repo_root=ctx.repo_root, run=ctx.run, git=ctx.git
        )
    if marketplace.read_bytes() != marketplace_before:
        problems.append(f"{MARKETPLACE_PATH} changed; rule 24 forbids a release PR touching it")

    if problems:
        print(f"prepared {version}, but the tree does NOT hold:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    print(
        f"release-state checks hold for {version}, except that v{version} exists, which "
        "`check_release_state.py --tag` checks once RELEASING step 3 creates the tag."
    )
    print(f"{MARKETPLACE_PATH} is byte-identical, as rule 24 requires.")
    print("Still yours to do before committing (docs/RELEASING.md step 2):")
    print("  - review README.md's prose naming the current release (`Status and known limits`)")
    print("  - write the release section's lead, and docs/MIGRATION.md's upgrade section")
    print("  - the rule-18 carrier re-check and everything from RELEASING step 3 on")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    prepare = commands.add_parser(
        "prepare",
        help="make the rule-19 release PR's edits (RELEASING step 2)",
        description="Move every version literal, roll CHANGELOG.md, run `uv lock`, and check.",
    )
    prepare.add_argument("version", help="the version being released, X.Y.Z")
    prepare.add_argument(
        "--check", action="store_true", help="print the planned edits and write nothing"
    )
    prepare.set_defaults(handler=cmd_prepare)
    return parser


def main(argv: list[str] | None = None, *, context: Context | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.handler(context or Context(), args)


if __name__ == "__main__":
    raise SystemExit(main())
