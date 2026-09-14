#!/usr/bin/env python
"""Check that a tree — and, at release time, the tag that names it — is releasable.

This is the release predicate the publish workflow reads. It answers two different kinds of
question, and the difference matters more than the code:

1. **Release-state coherence** (`check_tree`). Every version literal AGENTS.md rule 19 names
   agrees with the version being released, `CHANGELOG.md` has exactly one dated section for
   that version with `## [Unreleased]` above it, `uv.lock` is current, and `.mcp.json`'s pin
   names a tag no newer than this release that resolves IN THIS CHECKOUT, every tool
   deprecation window (`DEPRECATED_TOOLS` in `src/amicus/tools/_meta.py`) contains this
   release, and no `EnvVar` still declares a legacy name once this release reaches
   `LEGACY_REMOVAL_VERSION` (`src/amicus/config/envspec.py`). These are facts of
   the tagged tree (and, for the pin, of this checkout), so a green result here *proves* them.
   Nothing self-asserts.

   "In this checkout" is the exact claim, and it is deliberately not "on the remote". A
   local-only tag would satisfy this check while being unfetchable by the users the pin exists
   to serve. That gap is closed by where the check runs rather than by the check itself: the
   `verify` job checks out from GitHub with `fetch-depth: 0`, so the tags it sees are the
   remote's. Read a local pass as "my checkout has it", and the CI pass as "GitHub has it".

   `.mcp.json`'s pin is deliberately NOT one of the version literals. Per ADR 0015 it names
   an ALREADY-PUBLISHED release rather than the one being released, because the
   manifest a fresh install reads lives on `main` and so cannot name an artifact that does
   not exist yet. What replaced the old equality is `check_mcp_pin_tag_exists`, which is
   worth more: the equality was true by construction on any tree a release PR had touched,
   whereas the tag either exists or it does not.

2. **The live-gate assertion** (`check_tag`). AGENTS.md rule 20's evidence record, carried in
   the annotated tag's own message. A green result here proves only that a well-formed record
   naming *this* commit exists and asserts three passing suites. It does NOT prove the runs
   happened: the maintainer writes that record, and `scripts/record_live_gate_evidence.py`
   says so in its own docstring. This is a machine-checked maintainer assertion, not an
   attestation, and every document that mentions it must say so.

What this script cannot check at all, and what no CI job could: rule 19's procedural clauses.
Two PRs, an ordinary merge commit, the maintainer merging rather than an agent, the tag pushed
immediately after the merge. Those are conventions plus platform controls (the `v*` ruleset of
rule 21, the `pypi` environment reviewer), and calling this script "rule 19 enforcement" would
be exactly the false confidence issue #25 was filed about.

The evidence rides the annotated tag's message rather than a git note or a side ref, because
the tag is the object the rule-21 ruleset protects and the object whose push triggers the
publish. A separate ref would be a second, separately-pushed, separately-mutable thing, and
the window between pushing it and pushing the tag would be one more sequencing convention.

Freshness is deliberately NOT checked here. `record_live_gate_evidence.validate` enforces a
24-hour window locally, before the tag exists; applying it after tagging would let queue time
or a slow deployment approval turn a legitimate, immutable tag into one that can never be
published.

Usage:
    # Before tagging: tree only, version taken from pyproject.toml.
    uv run python scripts/check_release_state.py

    # In the publish workflow: tree, tag object and the evidence it carries.
    uv run python scripts/check_release_state.py --tag v1.2.3 --commit "$GITHUB_SHA" \
        --summary "$GITHUB_STEP_SUMMARY"

Exits 0 when every check passes, 1 otherwise, printing each problem.

Pure stdlib (no deps): this script must run in a bare checkout without a synced environment.
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

REPO_ROOT = Path(__file__).resolve().parent.parent

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
TAG_RE = re.compile(r"^v(?P<version>\d+\.\d+\.\d+)$")
_INIT_VERSION_RE = re.compile(r'^__version__ = "(?P<version>[^"]+)"$', re.MULTILINE)
_MCP_SOURCE_RE = re.compile(
    r"^git\+https://github\.com/briandconnelly/amicus\.git@v(?P<version>\d+\.\d+\.\d+)$"
)

# A signature block, if the maintainer signs the tag, follows the message. Cut it off rather
# than fail to parse: rule 20 does not require a signature, but it must not forbid one either.
_SIGNATURE_RE = re.compile(r"^-----BEGIN (?:PGP|SSH) SIGNATURE-----$", re.MULTILINE)


def _load_evidence_module():
    """Import `record_live_gate_evidence` by path; `scripts/` is not an importable package."""
    path = Path(__file__).resolve().parent / "record_live_gate_evidence.py"
    spec = importlib.util.spec_from_file_location("record_live_gate_evidence", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def declared_version(repo_root: Path = REPO_ROOT) -> str:
    """The version `pyproject.toml` declares — the one every other literal must match."""
    data = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def _json_field(repo_root: Path, relative: str, field: str) -> object:
    return json.loads((repo_root / relative).read_text(encoding="utf-8"))[field]


def _parts(version: str) -> tuple[int, ...]:
    """`"0.10.0"` as `(0, 10, 0)`, so versions compare numerically rather than as strings."""
    return tuple(int(part) for part in version.split("."))


def mcp_pin(repo_root: Path = REPO_ROOT) -> tuple[str | None, list[str]]:
    """The version `.mcp.json`'s `--from` source pins, and any problem with that source.

    Per ADR 0015 this is NOT a rule-19 version literal: the manifest a fresh install reads
    lives on `main`, so it names an ALREADY-PUBLISHED release rather than the one
    being released. What is checkable here is its shape — this repo, over git, at some
    `vX.Y.Z`. `check_version_literals` bounds the version; `check_mcp_pin_tag_exists`
    proves the tag is real, where a checkout with tags is available.
    """
    server = json.loads((repo_root / ".mcp.json").read_text(encoding="utf-8"))
    args = server["mcpServers"]["amicus"]["args"]
    if "--from" not in args:
        return None, [".mcp.json must install from an explicit `--from` source"]
    index = args.index("--from") + 1
    # A manifest ending in a bare `--from`, or carrying a non-string there, is malformed. Report
    # it as a release-state problem: this script is the release gate, so it must not crash with
    # an IndexError or TypeError on exactly the input it exists to reject.
    if index >= len(args):
        return None, [".mcp.json has a trailing `--from` with no source after it"]
    source = args[index]
    if not isinstance(source, str):
        return None, [f".mcp.json's `--from` source is {source!r}, which is not a string"]
    match = _MCP_SOURCE_RE.match(source)
    if match is None:
        return None, [
            f".mcp.json installs {source!r}, which is not this repository at a vX.Y.Z tag"
        ]
    return match.group("version"), []


def check_mcp_pin_tag_exists(
    *,
    repo_root: Path = REPO_ROOT,
    git: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> list[str]:
    """The tag `.mcp.json` sends users to must actually exist. No exceptions.

    This is the check ADR 0015 gained in exchange for the equality it dropped, and it is worth
    more: the old `pin == version being released` was true by construction on any tree a
    release PR had touched, while this one is a fact about the world.

    There is deliberately no bootstrap exception. Two earlier attempts had one and both were
    unsound. Keying it on `pin == version being released` was too broad: a later release whose
    pin was mistakenly bumped would satisfy it, skip this check, and restore the very window
    ADR 0015 removes — and the publish workflow would not catch that either, because by then
    the tag has been pushed and does exist. Keying it on "this repository has no `v*` tags"
    was no better, because `git tag -l` sees only locally fetched tags: a `--no-tags` or
    shallow checkout is indistinguishable from a repository that has never released, and the
    pre-tag runbook step does not fetch before running this.

    The exception is also moot. 0.1.0 was tagged and published on 2026-09-09, so this
    repository can never legitimately bootstrap again, and the only way into that branch now
    would be a checkout too incomplete to trust. Requiring the tag unconditionally turns that
    case into a loud, actionable failure — fetch your tags — instead of a silent pass.

    A tagless checkout therefore FAILS here rather than passing, which is the intended
    behaviour and why `publish.yml` sets `fetch-depth: 0`.
    """
    pinned, problems = mcp_pin(repo_root)
    if pinned is None:
        return problems

    tag = f"v{pinned}"
    try:
        proc = git(
            ["git", "rev-parse", "--verify", "--quiet", f"refs/tags/{tag}"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:  # git missing: report it rather than silently skipping the check
        return [f"could not check whether {tag} exists: {exc}"]
    if proc.returncode != 0:
        return [
            f".mcp.json pins {tag}, which does not exist in this checkout; users installing "
            f"from this manifest would get an unresolvable ref. If {tag} is a real release, "
            "this checkout is missing its tags — fetch them and re-run."
        ]
    return []


def check_version_literals(version: str, *, repo_root: Path = REPO_ROOT) -> list[str]:
    """Every rule-19 literal must equal `version`, and `.mcp.json`'s pin must not exceed it.

    `tests/test_packaging.py` already asserts these agree with each other on every PR. This
    checks them against the version actually being released, on the tagged tree, in the
    workflow that publishes — which is the part CI never ran, because `ci.yml` triggers on
    pushes to `main` and on pull requests, never on a tag.

    `.mcp.json` is deliberately not among the literals; see `mcp_pin` and ADR 0015.
    """
    problems: list[str] = []

    declared = declared_version(repo_root)
    if declared != version:
        problems.append(f"pyproject.toml declares version {declared!r}, expected {version!r}")

    init_text = (repo_root / "src/amicus/__init__.py").read_text(encoding="utf-8")
    match = _INIT_VERSION_RE.search(init_text)
    if match is None:
        problems.append('src/amicus/__init__.py has no `__version__ = "..."` line')
    elif match.group("version") != version:
        problems.append(
            f"src/amicus/__init__.py declares {match.group('version')!r}, expected {version!r}"
        )

    for manifest in (".claude-plugin/plugin.json", ".codex-plugin/plugin.json"):
        found = _json_field(repo_root, manifest, "version")
        if found != version:
            problems.append(f"{manifest} declares {found!r}, expected {version!r}")

    pinned, pin_problems = mcp_pin(repo_root)
    problems += pin_problems
    if pinned is not None and _parts(pinned) > _parts(version):
        problems.append(
            f".mcp.json pins v{pinned}, which is newer than the {version} being released; "
            "the pin names an already-published release (ADR 0015) and so can never lead it"
        )

    return problems


def check_changelog(version: str, *, repo_root: Path = REPO_ROOT) -> list[str]:
    """`CHANGELOG.md` must carry exactly one dated section for `version`, below `Unreleased`.

    `docs/RELEASING.md` step 2 rolls `## [Unreleased]` into `## [X.Y.Z] - YYYY-MM-DD` and
    leaves a fresh empty `## [Unreleased]` above it, so "exactly one dated heading, with an
    Unreleased heading before it" is precisely the state that procedure produces. An empty
    Unreleased section is correct here and is not checked for content.
    """
    text = (repo_root / "CHANGELOG.md").read_text(encoding="utf-8")
    problems: list[str] = []

    heading = re.compile(rf"^## \[{re.escape(version)}\] - \d{{4}}-\d{{2}}-\d{{2}}$", re.MULTILINE)
    matches = list(heading.finditer(text))
    if not matches:
        problems.append(
            f"CHANGELOG.md has no dated `## [{version}] - YYYY-MM-DD` section for this release"
        )
    elif len(matches) > 1:
        problems.append(f"CHANGELOG.md has {len(matches)} dated sections for {version}, expected 1")

    unreleased = re.search(r"^## \[Unreleased\]$", text, re.MULTILINE)
    if unreleased is None:
        problems.append("CHANGELOG.md has no `## [Unreleased]` heading")
    elif matches and unreleased.start() > matches[0].start():
        problems.append("CHANGELOG.md's `## [Unreleased]` heading is below the released section")

    return problems


def check_lock(
    *,
    repo_root: Path = REPO_ROOT,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> list[str]:
    """`uv.lock` must already match `pyproject.toml`.

    AGENTS.md rule 19 makes regenerating the lock part of the release PR, and this is the one
    clause of that rule a tagged tree can actually prove.
    """
    try:
        proc = run(
            ["uv", "lock", "--check"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:  # uv missing: report it rather than silently skipping the check
        return [f"could not run `uv lock --check`: {exc}"]
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        tail = detail[-1] if detail else f"exit {proc.returncode}"
        return [f"`uv lock --check` failed: {tail}"]
    return []


DEPRECATIONS_PATH = "src/amicus/tools/_meta.py"
_DEPRECATIONS_TABLE = "DEPRECATED_TOOLS"


def _assigned_names(node: ast.stmt) -> list[str]:
    if isinstance(node, ast.Assign):
        return [target.id for target in node.targets if isinstance(target, ast.Name)]
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return [node.target.id]
    return []


def deprecation_windows(
    repo_root: Path = REPO_ROOT,
) -> tuple[dict[str, tuple[str, str]], list[str]]:
    """`{tool: (since, removal_at_or_after)}`, read statically from `DEPRECATED_TOOLS`.

    Statically, because the `verify` job runs this script with `--no-project`: amicus itself
    is not importable there. A test pins this read against the runtime table, so a table
    this parser cannot read fails there rather than passing here as "no deprecations"."""
    path = repo_root / DEPRECATIONS_PATH
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError) as exc:
        return {}, [f"could not read {DEPRECATIONS_PATH}: {exc}"]
    table = next(
        (
            node.value
            for node in tree.body
            if isinstance(node, (ast.Assign, ast.AnnAssign))
            and _DEPRECATIONS_TABLE in _assigned_names(node)
        ),
        None,
    )
    if not isinstance(table, ast.Dict):
        return {}, [f"{DEPRECATIONS_PATH} has no literal `{_DEPRECATIONS_TABLE}` dict"]
    windows: dict[str, tuple[str, str]] = {}
    problems: list[str] = []
    for key, value in zip(table.keys, table.values, strict=True):
        fields = {
            keyword.arg: keyword.value.value
            for keyword in (value.keywords if isinstance(value, ast.Call) else [])
            if isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str)
        }
        if not (
            isinstance(key, ast.Constant)
            and isinstance(key.value, str)
            and {"since", "removal_at_or_after"} <= fields.keys()
        ):
            problems.append(
                f"{DEPRECATIONS_PATH}: every `{_DEPRECATIONS_TABLE}` entry needs a literal tool "
                "name and literal `since` and `removal_at_or_after` strings"
            )
            continue
        windows[key.value] = (fields["since"], fields["removal_at_or_after"])
    return windows, problems


def check_deprecations(version: str, *, repo_root: Path = REPO_ROOT) -> list[str]:
    """Every shipped deprecation window must contain `version`: the deprecation took effect
    no later than this release, and this release is still before its removal.

    A `since` later than the release would publish, in fingerprint-covered metadata, a
    deprecation that never took effect. A release at or past `removal_at_or_after` with the
    entry still in the table ships the tool past the end its marker announced; amicus reads
    that field as the release that removes it. Both are fixed in an ordinary PR (move the
    window, or remove the tool), never in the release PR, which moves only version literals
    (AGENTS.md rule 19)."""
    windows, problems = deprecation_windows(repo_root)
    for name, (since, removal) in windows.items():
        if not (VERSION_RE.match(since) and VERSION_RE.match(removal)):
            problems.append(
                f"{name}: since {since!r} and removal_at_or_after {removal!r} must be X.Y.Z"
            )
            continue
        if _parts(since) > _parts(version):
            problems.append(
                f"{name} is marked deprecated since {since}, after the {version} being "
                "released; move its window to this release in an ordinary PR"
            )
        if _parts(version) >= _parts(removal):
            problems.append(
                f"{name} still ships at {version}, at or past its removal_at_or_after "
                f"{removal}; remove it in an ordinary PR before releasing"
            )
    return problems


LEGACY_ENV_SPEC_PATH = "src/amicus/config/envspec.py"
_LEGACY_REMOVAL_NAME = "LEGACY_REMOVAL_VERSION"
GLOBAL_ENV_PATH = "src/amicus/config/__init__.py"
BACKEND_ENV_GLOB = "src/amicus/backends/*/config.py"
_ENV_VAR_CALL = "EnvVar"
_LEGACY_POSITION = 3  # EnvVar(name, description, default, legacy)


def env_declaration_files(repo_root: Path = REPO_ROOT) -> list[Path]:
    """Every module that declares `EnvVar`s: the global namespace and each backend's."""
    return [repo_root / GLOBAL_ENV_PATH, *sorted(repo_root.glob(BACKEND_ENV_GLOB))]


def _module_strings(tree: ast.Module) -> dict[str, str]:
    """Module-level `NAME = "literal"` assignments, for resolving `f"{PREFIX}BIN"`."""
    strings: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            value = node.value.value
            if isinstance(value, str):
                for name in _assigned_names(node):
                    strings[name] = value
    return strings


def _string_of(node: ast.expr, strings: dict[str, str]) -> str | None:
    """A string literal, or an f-string whose only placeholders are module-level string
    constants; None for anything else."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        out = ""
        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                out += part.value
            elif (
                isinstance(part, ast.FormattedValue)
                and isinstance(part.value, ast.Name)
                and part.value.id in strings
            ):
                out += strings[part.value.id]
            else:
                return None
        return out
    return None


def _declares_legacy(call: ast.Call) -> bool:
    """Whether an `EnvVar(...)` call carries a legacy tuple. Fails closed: only an absent
    argument or an empty tuple/list literal means "no legacy names"; `_legacy(...)`, a
    name, or any other expression counts as declaring some, because this script cannot
    evaluate it and the release predicate must not read an alias it cannot see as gone."""
    legacy: ast.expr | None = None
    if len(call.args) > _LEGACY_POSITION:
        legacy = call.args[_LEGACY_POSITION]
    for keyword in call.keywords:
        if keyword.arg == "legacy":
            legacy = keyword.value
    if legacy is None:
        return False
    return not (isinstance(legacy, (ast.Tuple, ast.List)) and not legacy.elts)


def legacy_env_state(
    repo_root: Path = REPO_ROOT,
) -> tuple[str | None, dict[str, bool], list[str]]:
    """`(removal_version, {env var name: declares legacy}, problems)`, read statically.

    Statically for the reason `deprecation_windows` is: the `verify` job cannot import
    amicus. A test pins this read against `packaging.declared_vars()`, so a declaration
    shape this parser misses fails there rather than passing here as "no aliases"."""
    problems: list[str] = []
    removal: str | None = None
    spec_path = repo_root / LEGACY_ENV_SPEC_PATH
    try:
        spec_tree = ast.parse(spec_path.read_text(encoding="utf-8"), filename=str(spec_path))
    except (OSError, SyntaxError) as exc:
        return None, {}, [f"could not read {LEGACY_ENV_SPEC_PATH}: {exc}"]
    removal = _module_strings(spec_tree).get(_LEGACY_REMOVAL_NAME)
    if removal is None:
        problems.append(f"{LEGACY_ENV_SPEC_PATH} has no literal `{_LEGACY_REMOVAL_NAME}` string")
    declared: dict[str, bool] = {}
    for path in env_declaration_files(repo_root):
        relative = path.relative_to(repo_root).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError) as exc:
            problems.append(f"could not read {relative}: {exc}")
            continue
        strings = _module_strings(tree)
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == _ENV_VAR_CALL
            ):
                continue
            name = _string_of(node.args[0], strings) if node.args else None
            if name is None:
                name = f"{relative}:{node.lineno}"
            if name in declared:
                # Fail closed on a name declared twice: the runtime resolves the FIRST
                # declaration, so a later alias-free duplicate must not hide an earlier
                # alias-bearing one (a Codex review finding, 2026-09-14).
                problems.append(f"{relative}:{node.lineno}: {name} is declared more than once")
            declared[name] = declared.get(name, False) or _declares_legacy(node)
    return removal, declared, problems


def check_legacy_env(version: str, *, repo_root: Path = REPO_ROOT) -> list[str]:
    """Once a release reaches `LEGACY_REMOVAL_VERSION`, no `EnvVar` may still declare a
    legacy name: the shim warns that the names are "removed in" that version, and a release
    that ships them anyway makes every such warning false. Fixed in an ordinary PR (drop the
    aliases, or move the version), never in the release PR (AGENTS.md rule 19)."""
    removal, declared, problems = legacy_env_state(repo_root)
    if removal is None:
        return problems
    if not VERSION_RE.match(removal):
        return [*problems, f"{_LEGACY_REMOVAL_NAME} {removal!r} must be X.Y.Z"]
    if _parts(version) < _parts(removal):
        return problems
    still = sorted(name for name, has_legacy in declared.items() if has_legacy)
    if still:
        problems.append(
            f"{version} is at or past {_LEGACY_REMOVAL_NAME} {removal} but "
            f"{len(still)} EnvVar(s) still declare legacy names ({', '.join(still)}); "
            "drop the aliases or move the version in an ordinary PR before releasing"
        )
    return problems


def check_tree(
    version: str,
    *,
    repo_root: Path = REPO_ROOT,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    git: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> list[str]:
    """Every release-state fact this tree can prove about `version`.

    `run` drives `uv lock --check` and `git` drives the tag lookup; they are separate
    parameters so a test can stub one without silently satisfying the other.
    """
    return [
        *check_version_literals(version, repo_root=repo_root),
        *check_changelog(version, repo_root=repo_root),
        *check_lock(repo_root=repo_root, run=run),
        *check_mcp_pin_tag_exists(repo_root=repo_root, git=git),
        *check_deprecations(version, repo_root=repo_root),
        *check_legacy_env(version, repo_root=repo_root),
    ]


def version_for_tag(tag: str) -> tuple[str | None, list[str]]:
    match = TAG_RE.match(tag)
    if match is None:
        return None, [f"tag {tag!r} is not of the form vX.Y.Z"]
    return match.group("version"), []


def evidence_from_tag_message(message: str) -> tuple[dict | None, list[str]]:
    """Parse the evidence record out of an annotated tag's message.

    Anything from a signature block onward is dropped, so signing the tag stays possible.
    """
    signature = _SIGNATURE_RE.search(message)
    body = message[: signature.start()] if signature else message
    body = body.strip()
    if not body:
        return None, ["the tag message is empty; it must carry the live-gate evidence record"]
    try:
        record = json.loads(body)
    except json.JSONDecodeError as exc:
        return None, [f"the tag message is not the JSON evidence record: {exc}"]
    if not isinstance(record, dict):
        return None, ["the tag message parsed as JSON but is not an object"]
    return record, []


def check_tag(
    tag: str,
    *,
    commit: str,
    object_type: str,
    peeled_commit: str,
    message: str,
) -> list[str]:
    """The tag must be annotated, name `commit`, and carry a usable rule-20 evidence record.

    `object_type` is what `git cat-file -t <tag>` reports: a lightweight tag reports `commit`
    and is refused, because it has no message and so can carry no evidence at all.
    """
    problems: list[str] = []

    if object_type != "tag":
        return [
            f"{tag} is a lightweight tag (git reports object type {object_type!r}); "
            "rule 20 requires an annotated tag whose message carries the evidence record"
        ]

    if peeled_commit != commit:
        problems.append(f"{tag} points at {peeled_commit!r}, but this run is for {commit!r}")

    record, parse_problems = evidence_from_tag_message(message)
    problems += parse_problems
    if record is None:
        return problems

    evidence = _load_evidence_module()
    problems += evidence.validate_record(record, head=commit, tree_clean=True)
    return problems


def _git(*args: str, repo_root: Path = REPO_ROOT) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo_root, capture_output=True, text=True, check=True
    ).stdout.strip()


def _write_summary(path: Path, *, tag: str | None, version: str, problems: list[str]) -> None:
    lines = ["## Release predicate", ""]
    lines.append(f"- version: `{version}`")
    if tag:
        lines.append(f"- tag: `{tag}`")
    lines.append("")
    if problems:
        lines.append("**FAILED** — the following must be fixed before this can be published:")
        lines += [f"- {problem}" for problem in problems]
    else:
        lines.append("**Release-state coherence: PASSED.** Every version literal, the changelog")
        lines.append("section and `uv.lock` agree with this tag, on this tree.")
        lines.append("")
        lines.append(
            "**Install manifest: PASSED.** `.mcp.json` pins an already-published release "
            "tag that resolves in this checkout and does not lead this version, so `main` "
            "is not sending fresh installs at a tag that does not exist (ADR 0015). This "
            "checkout is GitHub's, fetched with full tags, so the tag really is on the remote."
        )
        if tag:
            lines.append("")
            lines.append(
                "**Live-gate record: PRESENT and consistent.** The annotated tag carries a "
                "well-formed record naming this exact commit and asserting that all three live "
                "gates passed."
            )
            lines.append("")
            lines.append(
                "> This record is the maintainer's assertion, machine-checked for shape and "
                "for naming this commit. It is an honest-mistake guard, not an attestation: "
                "the runs happen on the maintainer's machine and the record is written there, "
                "so a green check here is not proof the three suites actually ran. Approve the "
                "deployment on that understanding."
            )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None, *, repo_root: Path = REPO_ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--tag",
        help="the annotated tag to check; omit to check only the tree, before tagging",
    )
    parser.add_argument(
        "--commit",
        help="the commit the tag must point at (GITHUB_SHA in the publish workflow)",
    )
    parser.add_argument("--summary", help="write a Markdown summary to this file")
    args = parser.parse_args(argv)

    problems: list[str] = []
    tag_is_well_formed = False

    if args.tag:
        parsed, tag_problems = version_for_tag(args.tag)
        problems += tag_problems
        tag_is_well_formed = parsed is not None
        version = parsed if parsed is not None else declared_version(repo_root)
    else:
        version = declared_version(repo_root)

    if not VERSION_RE.match(version):
        problems.append(f"version {version!r} is not X.Y.Z")

    problems += check_tree(version, repo_root=repo_root)

    if tag_is_well_formed:
        commit = args.commit or _git("rev-parse", "HEAD", repo_root=repo_root)
        try:
            object_type = _git("cat-file", "-t", args.tag, repo_root=repo_root)
            peeled = _git("rev-list", "-n", "1", args.tag, repo_root=repo_root)
            message = _git("tag", "-l", "--format=%(contents)", args.tag, repo_root=repo_root)
        except subprocess.CalledProcessError as exc:
            problems.append(f"could not read tag {args.tag!r}: {(exc.stderr or '').strip() or exc}")
        else:
            problems += check_tag(
                args.tag,
                commit=commit,
                object_type=object_type,
                peeled_commit=peeled,
                message=message,
            )

    if args.summary:
        _write_summary(Path(args.summary), tag=args.tag, version=version, problems=problems)

    if problems:
        print("the release predicate does NOT hold:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    print(f"release predicate holds for {args.tag or version}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
