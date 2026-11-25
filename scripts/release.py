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

`preflight --pr N --version X.Y.Z` runs in the release PR's worktree immediately before the
live-gate evidence (RELEASING step 3), and spends nothing. It checks that this checkout is a
linked worktree rather than the main checkout, that `HEAD` is PR N's head commit on GitHub, that
PR N is open against `main`, that the tree is clean (untracked files included, whatever
`status.showUntrackedFiles` says), that `pyproject.toml` declares X.Y.Z, that no tag `vX.Y.Z`
exists on `origin` or locally, that `check_release_state.check_tree_pre_tag` holds, and that
`scripts/check_backend_compat.py` passes. On success it prints the evidence command, and never
runs it: that spends live quota, which only the maintainer authorizes (AGENTS.md rules 5
and 20). It also requires every rule-2 gate job CI ran on the release commit to have passed,
as `ci` below checks, so a failing gate stops the release before anything is spent.
`--fix` is for a release that ships an important bug or security fix: it refuses unless the
release's CHANGELOG.md section holds only `### Fixed` and `### Security` entries, and runs
`check_backend_compat.py --fix`, which lets a backend whose npm `latest` the shipped contract
does not support yet stay on the newest stable release it does (docs/RELEASING.md, "Bug-fix and
security releases"). `--override-fix-changelog`, only with `--fix`, turns a failed category
check into a warning; the release PR then says why the other changes ship with the fix.

`session --pr N --version X.Y.Z [--worktree PATH]` is RELEASING step 3 as one command, for
the maintainer at a terminal. It refuses unless stdin and stdout are a terminal, `CI` is unset
and `AMICUS_PI_MODEL` is set. It creates the release worktree beside this checkout, detached
at PR N's head as GitHub reports it, or reuses a clean one and moves it to that head. It shows
the installs `check_backend_compat.py print-updates --json` names and runs them on a yes, asks
whether the rule-18 carrier re-check is in the PR, then runs `policy`, `preflight` and
`check_pi_pricing.py` in the worktree, stopping at the first failure. It prints the note
RELEASING asks for about pi's `models.json`, with values only for keys that cannot carry a
secret. Only then, and only once the maintainer types `spend X.Y.Z`, does it run the evidence
script, which spends live quota on every backend: typing that phrase is the authorization in
the session that AGENTS.md rule 20 and RELEASING step 3 require, and a passing preflight is
not. On success it prints the notes for the PR and the rest of the release, as `preflight`
does. It never tags, merges or pushes. `--fix` plans the installs with `print-updates --json
--fix` and passes `--fix`, and `--override-fix-changelog` when given, to `preflight`.

`ci --sha SHA` reads, read-only, the check runs GitHub reports for SHA and passes only when
every job of the AGENTS.md rule-2 gate CI runs (`.github/workflows/test.yml`'s `gate` job, once
for each Python version in its matrix, called from `ci.yml`) completed with success, and when
origin's `main`, which it fetches, is in SHA's history: CI on a pull request tests the head
merged with `main`, and only then is that SHA's own tree. Only check runs GitHub Actions
created count. `preflight` runs the same check before the evidence, and the block it prints
after the evidence opens with it again, in place of running the gate by hand: CI already ran
it on the release commit, on every supported Python.

`post-merge --release-sha SHA --version X.Y.Z` runs in the same worktree after the release PR
merges (RELEASING step 5). It fetches `main` from `origin` first and fails if it cannot, then
checks that `origin/main`'s tip is either an ordinary merge commit whose second parent is SHA
or SHA itself (the fast-forward RELEASING allows), that its tree is SHA's tree, that SHA is in
`origin/main`'s history, that `HEAD` is SHA on a clean tree, and that the local tag `vX.Y.Z` is
annotated, peels to SHA and carries `.release-evidence/live-gates.json` byte for byte; then it
runs `check_release_state.py --tag vX.Y.Z --commit SHA`. It never tags, pushes or merges. A
pass says the tag carries the record the maintainer wrote; it is not proof the live gates ran
(AGENTS.md rule 23).

`post-publish --version X.Y.Z` runs once the tag is pushed and the publish workflow has
completed (RELEASING "Post-tag completion checks"). It reads PyPI and GitHub and installs into
temporary directories; it spends nothing and changes nothing in the checkout. It checks that
PyPI's `releases` lists files for exactly X.Y.Z (the project's metadata alone says nothing
about this version), that the canonical repository has the annotated tag `vX.Y.Z` and its
peeled commit and `origin` reports exactly the same, that
installing the tag exactly as a user would, `uvx --from git+...@vX.Y.Z amicus-mcp` with a fresh
`UV_CACHE_DIR` and `UV_TOOL_DIR`, an allowlisted environment and a `PATH` that holds no other
`amicus-mcp`, answers an MCP
`initialize` as `amicus` X.Y.Z, and that the same install of a tag that cannot exist fails
with git's diagnostic that the remote has no such ref: the negative control that proves the
positive one was not answered by a cache or by some other binary.

`pointer --version X.Y.Z` makes the edit of the marketplace pointer PR (RELEASING step 7,
AGENTS.md rule 24). It runs `post-publish` first, in the same invocation, and refuses unless
it passed; then it fetches `main` and exactly the tag `vX.Y.Z` from `origin`, requires the
tag to be annotated and to be, object and peeled commit, what `origin` reported, writes `ref`
and the peeled `sha` into `.claude-plugin/marketplace.json` without reformatting it, and runs
`check_release_state.check_pull_request` against `origin/main`, the check CI runs on the PR.
If that check fails it puts the file back. It refuses a dirty tree and the `main` branch. It
never commits, tags, pushes, merges or opens the PR.

`policy` reads back, read-only, the two repository controls RELEASING's preconditions name:
every tag ruleset, and the `pypi` environment. It needs one active ruleset that restricts
creation, update and deletion of `refs/tags/v*` with no exclusions, no `Integration` bypass
actor on any tag ruleset (a broader pattern covers `v*` too), an environment with a required
reviewer, and exactly one deployment policy, typed `tag` and named `v*`. A response without
`bypass_actors` is reported UNKNOWN and fails: GitHub omits the key for a requester without
permission on the ruleset, the agent App token among them, and an absent key is not an empty
list (AGENTS.md rule 21). It prints `current_user_can_bypass` as what it is, an answer about
whoever's token ran it. Only the maintainer's own token can make it pass.

Usage:
    uv run python scripts/release.py prepare X.Y.Z [--check]
    uv run python scripts/release.py preflight --pr N --version X.Y.Z
                                               [--fix [--override-fix-changelog]]
    uv run python scripts/release.py session --pr N --version X.Y.Z [--worktree PATH]
                                             [--fix [--override-fix-changelog]]
    uv run python scripts/release.py ci --sha SHA
    uv run python scripts/release.py post-merge --release-sha SHA --version X.Y.Z
    uv run python scripts/release.py post-publish --version X.Y.Z [--timeout SECONDS]
    uv run python scripts/release.py pointer --version X.Y.Z [--timeout SECONDS]
    uv run python scripts/release.py policy

Exits 0 on success, 1 on a refusal or a failed check, printing each problem.
Pure stdlib, like `check_release_state.py`; it runs `git`, `gh`, `uv` and `uvx`, and
`session` also runs the installs `print-updates` names.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import difflib
import fnmatch
import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

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


def _http_get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=30) as response:
        return response.read()


@dataclass
class Context:
    """What every subcommand runs against. Tests replace the runners and the clock."""

    repo_root: Path = REPO_ROOT
    git: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run
    today: Callable[[], dt.date] = field(default=lambda: utc_date(dt.datetime.now(dt.UTC)))
    http_get: Callable[[str], bytes] = _http_get
    # The repository users install from: the marketplace pointer's `url` and the install's.
    canonical_url: str = release_state.MARKETPLACE_URL
    # `session` only: it asks before it installs or spends, so it needs a person at a terminal.
    ask: Callable[[str], str] = input
    interactive: Callable[[], bool] = field(
        default=lambda: sys.stdin.isatty() and sys.stdout.isatty()
    )
    environ: Mapping[str, str] = field(default_factory=lambda: os.environ)
    home: Callable[[], Path] = Path.home

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
    if not release_state.VERSION_RE.fullmatch(version):
        raise Refusal(f"version {version!r} is not X.Y.Z")
    declared = release_state.declared_version(ctx.repo_root)
    if not release_state.VERSION_RE.fullmatch(declared):
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
    status = ctx.git_out(
        "status", "--porcelain", "--untracked-files=all", "--ignore-submodules=none"
    )
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

    declared = release_state.declared_version(ctx.repo_root)
    for edit in edits:
        (ctx.repo_root / edit.path).write_text(edit.after, encoding="utf-8")
        print(f"  {edit.path}: {edit.summary}")

    problems: list[str] = []
    lock_path = ctx.repo_root / "uv.lock"
    lock_before = lock_path.read_text(encoding="utf-8") if lock_path.exists() else None
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
            if lock_before is not None:
                after = lock_path.read_text(encoding="utf-8")
                _warn_on_lock_churn(lock_before, after, declared, version)

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
    print("  - paste `uv run python scripts/check_backend_compat.py release-brief` into the PR:")
    print("    it drafts the backend versions and the rule-18 carrier re-check, whose codex")
    print("    verdict is yours to write")
    print("  - then everything from RELEASING step 3 on: `release.py session` runs it in one go")
    return 0


def _warn_on_lock_churn(before: str, after: str, old: str, new: str) -> None:
    """Warn when `uv lock` changed more than amicus's own version line.

    On a tree whose lock was current, that line is all a release should move. Anything else
    is usually a different `uv` rewriting the file: uv 0.13 rewrote the revision-3 lock 0.11.0
    shipped as revision 5 with new markers, which is why 0.11.1's release PR moved only the
    version line by hand. A warning, not a refusal: the lock still passes `uv lock --check`,
    and what the release PR carries is the maintainer's call.
    """
    expected = before.replace(
        f'name = "amicus"\nversion = "{old}"\n', f'name = "amicus"\nversion = "{new}"\n', 1
    )
    if after != expected:
        print(
            "warning: `uv lock` changed uv.lock beyond amicus's own version line, which a "
            "different uv release can do; review `git diff uv.lock` before committing.",
            file=sys.stderr,
        )


# --- preflight: before the live-gate evidence spends anything -------------------------------

EVIDENCE_PATH = ".release-evidence/live-gates.json"
EVIDENCE_SCRIPT = "scripts/record_live_gate_evidence.py"
_FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SIGNATURE_BYTES_RE = re.compile(rb"^-----BEGIN (?:PGP|SSH) SIGNATURE-----$", re.MULTILINE)


def _version_problems(version: str) -> list[str]:
    if release_state.VERSION_RE.fullmatch(version):
        return []
    return [f"version {version!r} is not X.Y.Z"]


FIX_CATEGORIES = ("Fixed", "Security")
_CATEGORY_RE = re.compile(r"^### +(?P<name>.+?)[ \t]*$")
# What ends a release's section: the next release's heading, or the link definitions below.
_SECTION_END_RE = re.compile(r"^(?:## \[|\[[^\]]+\]: )", re.MULTILINE)


def fix_changelog_problems(repo_root: Path, version: str) -> list[str]:
    """Why `version`'s CHANGELOG.md section is not a fix release's, or [] when it is: at least
    one entry, and every entry under `### Fixed` or `### Security` (docs/RELEASING.md,
    "Bug-fix and security releases"). The lead paragraph before the first category is allowed.
    A heading says nothing about whether an entry under it is a fix; that stays the
    maintainer's reading."""
    try:
        text = (repo_root / "CHANGELOG.md").read_text(encoding="utf-8")
    except OSError as exc:
        return [
            f"CHANGELOG.md could not be read, so whether {version} ships only fixes is "
            f"unknown: {exc}"
        ]
    heading = re.search(
        rf"^## \[{re.escape(version)}\] - \d{{4}}-\d{{2}}-\d{{2}}[ \t]*$", text, re.MULTILINE
    )
    if heading is None:
        return [
            f"CHANGELOG.md has no dated section for {version}, so whether it ships only "
            "fixes is unknown"
        ]
    after = _SECTION_END_RE.search(text, heading.end() + 1)
    body = text[heading.end() : after.start() if after else len(text)]
    problems: list[str] = []
    category: str | None = None
    entries = 0
    for line in body.splitlines():
        found = _CATEGORY_RE.match(line)
        if found:
            category = found["name"]
            if category not in FIX_CATEGORIES:
                problems.append(
                    f"CHANGELOG.md's {version} section has `### {category}`; a fix release has "
                    "only `### Fixed` and `### Security`"
                )
        elif line.startswith("- "):
            if category is None:
                problems.append(
                    f"CHANGELOG.md's {version} section has an entry under no `###` category"
                )
            elif category in FIX_CATEGORIES:
                entries += 1
    if not entries:
        problems.append(
            f"CHANGELOG.md's {version} section has no entry under `### Fixed` or `### Security`"
        )
    return problems


def _fix_mode_problems(
    ctx: Context, version: str, *, fix: bool, override: bool
) -> tuple[list[str], list[str]]:
    """`--fix`'s eligibility: the problems that stop it, and the warnings an override leaves."""
    if override and not fix:
        return ["--override-fix-changelog applies only with --fix"], []
    if not fix or _version_problems(version):
        return [], []
    found = fix_changelog_problems(ctx.repo_root, version)
    if not found:
        return [], []
    if override:
        return [], found
    return [
        *found,
        "--fix is for a release that ships an important bug or security fix; if other changes "
        "must ship with it, pass --override-fix-changelog and say why in the release PR "
        "(docs/RELEASING.md)",
    ], []


def _stderr_line(proc: subprocess.CompletedProcess) -> str:
    text = proc.stderr if isinstance(proc.stderr, str) else (proc.stderr or b"").decode()
    lines = text.strip().splitlines()
    return lines[-1].strip() if lines else f"exit status {proc.returncode}"


def _rev(ctx: Context, revision: str) -> str | None:
    """The full SHA `revision` names, or None when it names nothing."""
    proc = ctx.git_out("rev-parse", "--verify", "--quiet", revision)
    return proc.stdout.strip() if proc.returncode == 0 else None


def _linked_worktree_problems(ctx: Context) -> list[str]:
    """The checkout must be a linked worktree: its git dir differs from the common one.

    The main checkout's git dir IS the common dir, and the main checkout is where the
    evidence was recorded by mistake for 0.3.0, 0.6.0 and 0.7.0 (#241).
    """
    proc = ctx.git_out("rev-parse", "--path-format=absolute", "--git-dir", "--git-common-dir")
    dirs = proc.stdout.split("\n")[:2] if proc.returncode == 0 else []
    if len(dirs) != 2 or not all(dirs):
        return [f"could not tell which checkout {ctx.repo_root} is: {_stderr_line(proc)}"]
    git_dir, common_dir = (Path(d).resolve() for d in dirs)
    if git_dir == common_dir:
        return [
            f"{ctx.repo_root} is the main checkout, not a linked worktree; run this in the "
            "release PR's worktree (`git worktree add`), never in the main checkout (#241)"
        ]
    return []


def _clean_tree_problems(ctx: Context) -> list[str]:
    # Explicit flags, because plain `--porcelain` honours `status.showUntrackedFiles` (#385).
    status = ctx.git_out(
        "status", "--porcelain", "--untracked-files=all", "--ignore-submodules=none"
    )
    if status.returncode != 0:
        return [f"could not read the tree's status: {_stderr_line(status)}"]
    if status.stdout.strip():
        paths = ", ".join(line[3:] for line in status.stdout.splitlines()[:5])
        return [f"the tree is not clean ({paths}); the evidence must cover a commit, not a tree"]
    return []


def _pull_request(ctx: Context, number: int) -> tuple[dict | None, list[str]]:
    cmd = [
        "gh",
        "pr",
        "view",
        str(number),
        "--json",
        "headRefOid,headRefName,state,baseRefName,isCrossRepository",
    ]
    try:
        proc = ctx.run(cmd, cwd=ctx.repo_root, capture_output=True, text=True, check=False)
    except OSError as exc:
        return None, [f"could not run `gh pr view {number}`: {exc}"]
    if proc.returncode != 0:
        return None, [f"`gh pr view {number}` failed: {_stderr_line(proc)}"]
    try:
        pr = json.loads(proc.stdout)
        head = pr["headRefOid"]
        if not (isinstance(head, str) and _FULL_SHA_RE.fullmatch(head)):
            raise ValueError(f"headRefOid {head!r} is not a commit SHA")
    except (ValueError, KeyError, TypeError) as exc:
        return None, [f"could not read PR #{number} from `gh pr view`: {exc}"]
    problems = []
    if pr.get("state") != "OPEN":
        problems.append(
            f"PR #{number} is {pr.get('state')}, not OPEN; preflight runs before the release "
            "PR merges"
        )
    if pr.get("baseRefName") != "main":
        problems.append(f"PR #{number} targets {pr.get('baseRefName')!r}, not main")
    if pr.get("isCrossRepository") is not False:
        # A fork's head is code nobody with write access pushed; session runs scripts from it.
        problems.append(
            f"PR #{number}'s head is not a branch of this repository; a release PR never comes "
            "from a fork"
        )
    return pr, problems


def _remote_tag_problems(ctx: Context, tag: str) -> list[str]:
    # `--exit-code` makes absence its own status, 2, so a failed lookup cannot read as absent.
    proc = ctx.git_out("ls-remote", "--exit-code", "--tags", "origin", f"refs/tags/{tag}")
    if proc.returncode == 2:
        return []
    if proc.returncode == 0:
        return [f"{tag} already exists on origin; that version is released, choose another"]
    return [f"could not ask origin whether {tag} exists: {_stderr_line(proc)}"]


def _local_tag_problems(ctx: Context, tag: str) -> list[str]:
    # `rev-parse -q --verify` exits 1 for a missing ref; anything else is not an answer.
    proc = ctx.git_out("rev-parse", "-q", "--verify", f"refs/tags/{tag}")
    if proc.returncode == 1:
        return []
    if proc.returncode == 0:
        return [
            f"a local tag {tag} exists, which the evidence script refuses; if it is from an "
            f"earlier attempt that was never pushed, `git tag -d {tag}` and rerun"
        ]
    return [f"could not tell whether a local tag {tag} exists: {_stderr_line(proc)}"]


def _script_problems(ctx: Context, script: str, *args: str) -> list[str]:
    """Run one of this checkout's scripts, its report on the terminal; a non-zero exit fails."""
    cmd = [sys.executable, str(ctx.repo_root / script), *args]
    shown = " ".join(["python", script, *args])
    try:
        proc = ctx.run(cmd, cwd=ctx.repo_root, check=False)
    except OSError as exc:
        return [f"could not run `{shown}`: {exc}"]
    if proc.returncode != 0:
        return [f"`{shown}` failed (exit status {proc.returncode}); its report is above"]
    return []


def evidence_command(repo_root: Path, version: str) -> str:
    return (
        f"cd {shlex.quote(str(repo_root))} && "
        f"AMICUS_REQUIRE_LIVE=1 uv run python {EVIDENCE_SCRIPT} --version {version}"
    )


def _print_fix_notes(*, fix: bool, warnings: list[str]) -> None:
    """What a passing `preflight --fix` adds: the PR's disclosure, and an override's warning."""
    if fix:
        print("This is a fix release: a backend whose latest the shipped contract does not")
        print("support stays on the newest release it does (`print-updates --fix` names it).")
        print("Name each held backend and the latest it skipped in the release PR.")
    if warnings:
        print(
            "WARNING: --override-fix-changelog: this fix release ships more than fixes:",
            file=sys.stderr,
        )
        for warning in warnings:
            print(f"  - {warning}", file=sys.stderr)
        print("Say in the release PR why these changes ship with the fix.", file=sys.stderr)


def cmd_preflight(ctx: Context, args: argparse.Namespace) -> int:
    version: str = args.version
    tag = f"v{version}"
    problems = _version_problems(version)
    fix_problems, fix_warnings = _fix_mode_problems(
        ctx, version, fix=args.fix, override=args.override_fix_changelog
    )
    problems += fix_problems
    problems += _linked_worktree_problems(ctx)
    head = _rev(ctx, "HEAD")
    if head is None:
        problems.append("could not resolve HEAD")
    pr, pr_problems = _pull_request(ctx, args.pr)
    problems += pr_problems
    if pr is not None and head is not None and head != pr["headRefOid"]:
        problems.append(
            f"HEAD is {head}, but PR #{args.pr}'s head on GitHub is {pr['headRefOid']} "
            f"({pr.get('headRefName')}); the evidence must cover the commit the PR will merge, "
            "so check out and pull that branch, or push what is here"
        )
    problems += _clean_tree_problems(ctx)
    declared = release_state.declared_version(ctx.repo_root)
    if declared != version:
        problems.append(f"pyproject.toml declares {declared!r}, not {version!r}")
    if not _version_problems(version):
        problems += _remote_tag_problems(ctx, tag)
        problems += _local_tag_problems(ctx, tag)
        # The release-state checks `prepare` ran, re-run on what will be tagged: a problem
        # found after the evidence would mean fixing it and spending the quota again.
        problems += release_state.check_tree_pre_tag(
            version, repo_root=ctx.repo_root, run=ctx.run, git=ctx.git
        )
    compat = ["scripts/check_backend_compat.py", *(["--fix"] if args.fix else [])]
    if pr is None or pr_problems:
        # A PR that cannot be read, or that comes from a fork, gets none of its checkout's
        # scripts run on its behalf.
        print("skipping scripts/check_backend_compat.py until the PR checks pass", flush=True)
    else:
        print(f"running {' '.join(compat)} (spends nothing):", flush=True)
        problems += _script_problems(ctx, *compat)
        if head is not None and head == pr["headRefOid"]:
            # The gate CI ran on the release commit: a failure found after the evidence would
            # mean a new commit and spending the quota again.
            print(f"reading the rule-2 gate's check runs on {head} (read-only):", flush=True)
            problems += ci_problems(ctx, head)[1]

    if problems:
        print(f"preflight for {version} does NOT hold; do not record evidence:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    print(f"preflight holds for {version} at {head} (PR #{args.pr}, {pr and pr['headRefName']}).")
    print(f"Record that SHA: it is the release commit, the one {tag} will point at.")
    print("Still yours before the evidence run (docs/RELEASING.md step 3): the backend CLIs at")
    print("npm's latest with Claude Code's autoupdater held, and the rule-18 carrier re-check.")
    _print_fix_notes(fix=args.fix, warnings=fix_warnings)
    print("The evidence run spends live quota on all three backends (codex, claude and pi)")
    print("and needs the maintainer's authorization in the session that runs it. This script")
    print("never runs it. The command:")
    print(f"  {evidence_command(ctx.repo_root, version)}")
    print()
    print("Then, if every suite passed, the rest of the release with this commit filled in.")
    print("Run it the same day as the evidence (its freshness window is 24 hours); each block")
    print("stops at its first failure, and the second waits for your pypi approval:")
    for block in next_steps(ctx.repo_root, version, args.pr, head or ""):
        print()
        print("  " + " &&\\\n  ".join(block))
    return 0


def next_steps(repo_root: Path, version: str, pr: int, release_sha: str) -> list[list[str]]:
    """RELEASING steps 3 (after the evidence) through the post-tag checks, as commands to copy.

    Each inner list is one block, printed joined with `&&` so a failing check stops everything
    after it; the blocks break only where the maintainer must act between them. Printed, never
    run: tagging, merging and pushing are the maintainer's alone.

    The first block opens with `ci`, the AGENTS.md rule-2 gate as CI ran it on the release
    commit, so a gate still running or failing stops it before anything is tagged, and the
    block can simply be run again. The gate is not run again locally: CI is authoritative for
    it, on every supported Python, where a local run covers one.
    """
    tag = f"v{version}"
    record = shlex.quote(str(repo_root / EVIDENCE_PATH))
    handshake = shlex.quote(
        '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":'
        '"2025-06-18","capabilities":{},"clientInfo":{"name":"rehearsal","version":"0"}}}'
    )
    expect = shlex.quote(
        "import json,sys; info=json.loads(sys.stdin.readline())['result']['serverInfo']; "
        f"assert (info['name'], info['version']) == ('amicus', '{version}'), info; "
        "print('rehearsal answered', info)"
    )
    pkg = f"git+https://github.com/briandconnelly/amicus.git@{release_sha}"
    return [
        [
            f"uv run python scripts/release.py ci --sha {release_sha}",
            f'grep -q \'"commit": "{release_sha}"\' {record}',
            "AMICUS_RELEASE_CHECK=1 uv run pytest tests/test_release_evidence.py -v --no-cov",
            f"git tag -a {tag} --cleanup=verbatim -F {record} {release_sha}",
            f"uv run python scripts/check_release_state.py --tag {tag} --commit {release_sha}",
            f"printf '%s\\n' {handshake} | UV_CACHE_DIR=\"$(mktemp -d)\" "
            f"uvx --from {pkg} amicus-mcp | python3 -c {expect}",
            f"gh pr merge {pr} --merge",
            f"uv run python scripts/release.py post-merge --release-sha {release_sha} "
            f"--version {version}",
            f"git push origin {tag}",
        ],
        [
            f"uv run python scripts/release.py post-publish --version {version}",
        ],
    ]


# --- session: RELEASING step 3 as one command, asking before it installs or spends -------

PI_MODEL_ENV = "AMICUS_PI_MODEL"
# The backends `print-updates` plans an install for: check_backend_compat.BACKENDS, which this
# stdlib script cannot import; tests/test_release_session.py holds the two equal.
SESSION_BACKENDS = ("codex", "claude", "pi")
UPDATES_COMMAND = (
    "uv",
    "run",
    "python",
    "scripts/check_backend_compat.py",
    "print-updates",
    "--json",
)
PI_PRICING_COMMAND = ("uv", "run", "python", "scripts/check_pi_pricing.py")
# Values recorded from pi's models.json: what shapes the gate and cannot carry a secret.
# Every other key is named with its value left out, and a value that starts with `!`
# (a shell command) or `$` (an environment variable) is never printed (RELEASING step 3).
MODELS_JSON_VALUES = frozenset({"api", "reasoning", "input", "contextWindow", "maxTokens"})


def default_worktree(repo_root: Path, version: str) -> Path:
    """A sibling of the checkout, named as RELEASING names it: `amicus-wt-release-X-Y-Z`."""
    return repo_root.parent / f"amicus-wt-release-{version.replace('.', '-')}"


def _common_dir(ctx: Context) -> Path | None:
    proc = ctx.git_out("rev-parse", "--path-format=absolute", "--git-common-dir")
    return Path(proc.stdout.strip()).resolve() if proc.returncode == 0 else None


def _fetch_pr_head(ctx: Context, pr: int, head: str) -> list[str]:
    """Fetch PR N's head into FETCH_HEAD, never into a branch, and require GitHub's SHA."""
    proc = ctx.git_out("fetch", "--quiet", "--no-tags", "origin", f"refs/pull/{pr}/head")
    if proc.returncode != 0:
        return [f"could not fetch PR #{pr}'s head from origin: {_stderr_line(proc)}"]
    fetched = _rev(ctx, "FETCH_HEAD")
    if fetched != head:
        return [
            f"origin's refs/pull/{pr}/head is {fetched}, but GitHub reports PR #{pr}'s head as "
            f"{head}; rerun once they agree"
        ]
    return []


def _release_worktree(ctx: Context, path: Path, pr: int, head: str) -> tuple[Context, list[str]]:
    """The release PR's worktree at `path`, detached at PR N's head.

    A missing path is created with `git worktree add --detach`: detached, because the PR's
    branch is usually checked out in the main checkout, and git refuses a second checkout
    of a branch. An existing path must be a clean linked worktree of this repository; one
    left at an earlier head of the PR is moved to the current one, since a review's push
    means the evidence has to cover the new tip (RELEASING step 3).
    """
    worktree = dataclasses.replace(ctx, repo_root=path)
    if not path.exists():
        problems = _fetch_pr_head(ctx, pr, head)
        if problems:
            return worktree, problems
        proc = ctx.git_out("worktree", "add", "--quiet", "--detach", str(path), head)
        if proc.returncode != 0:
            return worktree, [f"could not create the worktree {path}: {_stderr_line(proc)}"]
        print(f"created the release worktree {path}, detached at PR #{pr}'s head {head}")
        return worktree, []
    if _common_dir(worktree) is None or _common_dir(worktree) != _common_dir(ctx):
        return worktree, [f"{path} exists and is not a worktree of {ctx.repo_root}"]
    toplevel = worktree.git_out("rev-parse", "--show-toplevel")
    if toplevel.returncode != 0 or Path(toplevel.stdout.strip()).resolve() != path.resolve():
        # A subdirectory passes the checks above, which git answers for the enclosing
        # worktree, and moving it would move that worktree.
        return worktree, [f"{path} is not the top of a worktree; name the worktree itself"]
    problems = _linked_worktree_problems(worktree) + _clean_tree_problems(worktree)
    if problems:
        return worktree, [f"{path}: {problem}" for problem in problems]
    current = _rev(worktree, "HEAD")
    if current == head:
        print(f"using the release worktree {path}, at PR #{pr}'s head {head}")
        return worktree, []
    problems = _fetch_pr_head(ctx, pr, head)
    if problems:
        return worktree, problems
    proc = worktree.git_out("checkout", "--quiet", "--detach", head)
    if proc.returncode != 0:
        return worktree, [f"could not move {path} to {head}: {_stderr_line(proc)}"]
    print(f"moved the clean worktree {path} from {current} to PR #{pr}'s head {head}")
    return worktree, []


def _yes(ctx: Context, question: str) -> bool:
    try:
        return ctx.ask(question).strip().lower() in ("y", "yes")
    except EOFError:
        return False


def _shown(cmd: list[str] | tuple[str, ...], env: Mapping[str, str] | None = None) -> str:
    return shlex.join([*(f"{k}={v}" for k, v in (env or {}).items()), *cmd])


def _run_step(ctx: Context, cwd: Path, cmd: list[str], extra_env: Mapping[str, str]) -> list[str]:
    """Run one command in `cwd` with its output on the terminal; a non-zero exit fails."""
    print(f"$ {_shown(cmd, extra_env)}", flush=True)
    try:
        proc = ctx.run(cmd, cwd=cwd, env={**ctx.environ, **extra_env}, check=False)
    except OSError as exc:
        return [f"could not run `{_shown(cmd)}`: {exc}"]
    if proc.returncode != 0:
        return [f"`{_shown(cmd)}` failed (exit status {proc.returncode}); its report is above"]
    return []


def _update_plan(ctx: Context, cwd: Path, *, fix: bool = False) -> tuple[list[dict], list[str]]:
    """`print-updates --json` (with `--fix` for a fix release) from the worktree's own script,
    checked for shape."""
    cmd = [*UPDATES_COMMAND, *(["--fix"] if fix else [])]
    try:
        proc = ctx.run(
            cmd, cwd=cwd, env=dict(ctx.environ), capture_output=True, text=True, check=False
        )
        payload = json.loads(proc.stdout)
        updates, failed = payload["updates"], payload["failed"]
        for update in updates:
            argv, env = update["argv"], update["env"]
            if not (
                isinstance(update["backend"], str)
                and isinstance(update["version"], str)
                and isinstance(argv, list)
                and argv
                and all(isinstance(part, str) for part in argv)
                and isinstance(env, dict)
                and all(isinstance(k, str) and isinstance(v, str) for k, v in env.items())
                and isinstance(update.get("held_below"), str | None)
            ):
                raise TypeError(f"malformed update {update!r}")
        if not isinstance(failed, list):
            raise TypeError(f"malformed failures {failed!r}")
    except OSError as exc:
        return [], [f"could not run `{_shown(cmd)}`: {exc}"]
    except (ValueError, KeyError, TypeError) as exc:
        return [], [f"could not read `{_shown(cmd)}`'s output: {exc}"]
    if failed:
        return updates, [str(problem) for problem in failed]
    if proc.returncode != 0:
        return [], [f"`{_shown(cmd)}` failed (exit status {proc.returncode}): {_stderr_line(proc)}"]
    planned = [update["backend"] for update in updates]
    if sorted(planned) != sorted(SESSION_BACKENDS):
        return [], [
            f"`{_shown(cmd)}` planned installs for {planned}, not one each for "
            f"{list(SESSION_BACKENDS)}"
        ]
    return updates, []


def _origin_only(url: str) -> str | None:
    """`scheme://host[:port]`, so no path, query or userinfo, which can hold a key, is kept."""
    if url[:1] in ("!", "$"):
        return None
    try:
        parts = urllib.parse.urlsplit(url)
        port = f":{parts.port}" if parts.port else ""
    except ValueError:
        return None
    if not parts.scheme or not parts.hostname:
        return None
    rest = "" if parts.path in ("", "/") and not parts.query else " (path not recorded)"
    return f"`{parts.scheme}://{parts.hostname}{port}`{rest}"


# pi's API families are lowercase words joined by hyphens (`openai-completions`); a value with
# a digit, an underscore or a capital is not one, and is the shape a key or token has.
_MODELS_JSON_API = re.compile(r"[a-z]{2,24}(?:-[a-z]{2,24}){0,4}")
# The input modalities pi accepts for a model.
_MODELS_JSON_INPUTS = frozenset({"text", "image"})


def _recordable(key: str, value: object) -> str | None:
    """The value to note for one models.json key, or None to name the key alone.

    Each recorded key's value is checked for the shape pi documents, so a path, a pasted key
    or a command under one of those keys is named, never printed.
    """
    if key == "baseUrl" and isinstance(value, str):
        return _origin_only(value)
    if key == "reasoning" and isinstance(value, bool):
        return f"`{json.dumps(value)}`"
    if key in ("contextWindow", "maxTokens") and type(value) is int and value >= 0:
        return f"`{value}`"
    if key == "api" and isinstance(value, str) and _MODELS_JSON_API.fullmatch(value):
        return f"`{value}`"
    if (
        key == "input"
        and isinstance(value, list)
        and all(isinstance(item, str) and item in _MODELS_JSON_INPUTS for item in value)
    ):
        return f"`{json.dumps(value)}`"
    return None


def _described(fields: dict) -> str:
    if not fields:
        return "no keys"
    parts = []
    for key in sorted(fields):
        value = _recordable(key, fields[key])
        parts.append(f"`{key}` (value not recorded)" if value is None else f"`{key}` {value}")
    return ", ".join(parts)


def models_json_note(environ: Mapping[str, str], home: Path) -> list[str]:
    """What RELEASING step 3 asks the release PR to say about pi's models.json, as Markdown.

    Whether the file is present where pi reads it (`$PI_CODING_AGENT_DIR`, else
    `~/.pi/agent`), and which keys apply to AMICUS_PI_MODEL's provider and model: values only
    for the keys in MODELS_JSON_VALUES and a baseUrl's origin, every other key by name alone,
    so no credential, header value or `!command` is ever printed. The path is shown in that
    symbolic form, never as the absolute path, which names the account.
    """
    model = environ.get(PI_MODEL_ENV, "")
    provider, _, model_id = model.partition("/")
    head = f"pi `models.json` for the pi gate's `{model}`:"
    agent_dir = environ.get("PI_CODING_AGENT_DIR")
    if not agent_dir:  # empty is unset, to pi as to amicus
        path, where = home / ".pi" / "agent" / "models.json", "~/.pi/agent/models.json"
    else:
        # pi expands a leading `~` or `~/` against the home directory, as
        # `amicus.backends.pi.config.agent_dir_error` describes; amicus refuses anything else
        # that is not absolute, so the gate could not have run with it.
        base = home if agent_dir == "~" else Path(agent_dir)
        if agent_dir.startswith("~/"):
            base = home / agent_dir[2:]
        if not base.is_absolute():
            return [f"{head} unknown, because `$PI_CODING_AGENT_DIR` is not absolute."]
        path, where = base / "models.json", "$PI_CODING_AGENT_DIR/models.json"
    if not path.exists():
        return [f"{head} absent at `{where}`, so no override applied."]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [f"{head} present at `{where}` but not JSON, so which keys applied is unknown."]
    providers = data.get("providers") if isinstance(data, dict) else None
    entry = providers.get(provider) if isinstance(providers, dict) else None
    if not isinstance(entry, dict):
        return [f"{head} present at `{where}`, with no entry for provider `{provider}`."]
    own = {k: v for k, v in entry.items() if k not in ("models", "modelOverrides")}
    models = entry.get("models")
    listed = models if isinstance(models, list) else []
    match = next((m for m in listed if isinstance(m, dict) and m.get("id") == model_id), None)
    overrides = entry.get("modelOverrides")
    override = overrides.get(model_id) if isinstance(overrides, dict) else None
    model_keys = {k: v for k, v in match.items() if k != "id"} if match else None
    return [
        f"{head} present at `{where}`.",
        f"  - provider `{provider}`: {_described(own)}",
        f"  - `models` entry `{model_id}`: "
        f"{'none' if model_keys is None else _described(model_keys)}",
        f"  - `modelOverrides` entry `{model_id}`: "
        f"{_described(override) if isinstance(override, dict) else 'none'}",
    ]


def _record_note(worktree: Path) -> list[str]:
    """The evidence record's commit, time and CLI versions, for the release PR."""
    try:
        record = json.loads((worktree / EVIDENCE_PATH).read_text(encoding="utf-8"))
        backends = record["backends"]
        versions = ", ".join(f"{b} `{backends[b]['cli_version']}`" for b in backends)
        return [
            f"Live-gate evidence recorded {record['recorded_at']} for `{record['commit']}` on "
            f"{versions}."
        ]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return [f"(could not read {EVIDENCE_PATH}: {exc}; copy the versions from it by hand)"]


def _stop(problems: list[str], *, spent: bool = False) -> int:
    print("session stopped:", file=sys.stderr)
    for problem in problems:
        print(f"  - {problem}", file=sys.stderr)
    if not spent:
        print("Nothing was spent.", file=sys.stderr)
    return 1


def _session_refusals(
    ctx: Context, version: str, *, fix: bool = False, override: bool = False
) -> list[str]:
    """What stops a session before it touches anything. The changelog check `--fix` needs runs
    in the preflight, on the release worktree's own CHANGELOG.md."""
    problems = _version_problems(version)
    if override and not fix:
        problems.append("--override-fix-changelog applies only with --fix")
    if not ctx.interactive():
        problems.append(
            "session asks before it installs or spends, so it runs only with stdin and stdout "
            "at a terminal; use `preflight` and the commands it prints instead"
        )
    if ctx.environ.get("CI"):
        problems.append("CI is set; the evidence run spends live quota and never runs in CI")
    if not ctx.environ.get(PI_MODEL_ENV):
        problems.append(
            f"{PI_MODEL_ENV} is not set; the pi gate needs an exact provider/id whose provider "
            "is ready, or it fails rather than skips"
        )
    return problems


def _session_updates(ctx: Context, cwd: Path, *, fix: bool = False) -> tuple[list[dict], list[str]]:
    """Step 1: show the installs of npm's `latest`, or a fix release's, and run them on a yes."""
    heading = "for a fix release" if fix else "at npm's latest"
    print(f"\n== 1. Backend CLIs {heading} ==")
    updates, problems = _update_plan(ctx, cwd, fix=fix)
    if problems:
        return updates, problems
    for update in updates:
        print(f"  {_shown(update['argv'], update['env'])}")
    for update in updates:
        if update.get("held_below"):
            print(
                f"{update['backend']} stays on {update['version']}: npm's latest "
                f"{update['held_below']} is outside the shipped contract, and this release "
                "ships only fixes."
            )
    print("Close every other Claude Code session first, or restart it with DISABLE_AUTOUPDATER=1,")
    print("so nothing moves Claude Code between these installs and the evidence run.")
    if not _yes(ctx, "Run these installs now? [y/N] "):
        target = "these versions" if fix else "npm's latest"
        print(f"Skipped. The preflight below fails if a CLI is not at {target}.")
        return updates, []
    for update in updates:
        problems = _run_step(ctx, cwd, update["argv"], update["env"])
        if problems:
            return updates, problems
    return updates, []


def _session_checks(
    ctx: Context, cwd: Path, pr: int, version: str, *, fix: bool = False, override: bool = False
) -> list[str]:
    """Step 3: the policy read-back, the preflight and pi's pricing check, which spend nothing."""
    print("\n== 3. Checks that spend nothing ==")
    script = ["uv", "run", "python", "scripts/release.py"]
    preflight = [*script, "preflight", "--pr", str(pr), "--version", version]
    for cmd in (
        [*script, "policy"],
        [
            *preflight,
            *(["--fix"] if fix else []),
            *(["--override-fix-changelog"] if override else []),
        ],
        list(PI_PRICING_COMMAND),
    ):
        problems = _run_step(ctx, cwd, cmd, {})
        if problems:
            return problems
    return []


def _session_evidence(ctx: Context, cwd: Path, version: str, head: str) -> list[str] | None:
    """Step 5: the evidence run, only on a typed confirmation. None when it was declined."""
    print("\n== 5. The live-gate evidence ==")
    print(f"It runs every live suite the release gate requires at {head} and spends real quota")
    print("on each backend. A failed suite means a new run, and new spending, once it is fixed.")
    phrase = f"spend {version}"
    try:
        answer = ctx.ask(f"Type `{phrase}` to run it now; anything else stops here: ")
    except EOFError:
        answer = ""
    if answer.strip() != phrase:
        return None
    cmd = ["uv", "run", "python", EVIDENCE_SCRIPT, "--version", version]
    return _run_step(ctx, cwd, cmd, {"AMICUS_REQUIRE_LIVE": "1"})


def _versions(updates: list[dict]) -> dict[str, tuple[str, str | None]]:
    """Each backend's planned version and, for a fix release, the `latest` it is held below,
    so a moved `latest` is noticed even when the held version stays the same."""
    return {update["backend"]: (update["version"], update.get("held_below")) for update in updates}


def _named(updates: list[dict]) -> str:
    return ", ".join(
        f"{u['backend']} {u['version']}"
        + (f" (held below {u['held_below']})" if u.get("held_below") else "")
        for u in updates
    )


def cmd_session(ctx: Context, args: argparse.Namespace) -> int:
    version: str = args.version
    pr: int = args.pr
    fix: bool = args.fix
    override: bool = args.override_fix_changelog
    problems = _session_refusals(ctx, version, fix=fix, override=override)
    if problems:
        return _stop(problems)
    pr_info, problems = _pull_request(ctx, pr)
    if pr_info is None or problems:
        return _stop(problems)
    head: str = pr_info["headRefOid"]
    path = Path(args.worktree or default_worktree(ctx.repo_root, version)).expanduser()
    worktree, problems = _release_worktree(ctx, path.resolve(), pr, head)
    if problems:
        return _stop(problems)
    cwd = worktree.repo_root

    updates, problems = _session_updates(ctx, cwd, fix=fix)
    if problems:
        return _stop(problems)

    print("\n== 2. Rule-18 carrier re-check ==")
    print(f"The evidence will vouch for {_named(updates)}.")
    brief = "check_backend_compat.py release-brief" + (" --fix" if fix else "")
    print(f"`uv run python scripts/{brief}` drafts the re-check.")
    if not _yes(ctx, f"Is the re-check for these versions in PR #{pr}'s description? [y/N] "):
        return _stop(["write the carrier re-check into the release PR first (RELEASING step 3)"])

    problems = _session_checks(ctx, cwd, pr, version, fix=fix, override=override)
    if problems:
        return _stop(problems)

    # npm's `latest` can move between the plan confirmed above and the preflight; the
    # preflight checks the installs against the newer one, so the re-check would name
    # versions the evidence does not run on.
    replanned, problems = _update_plan(ctx, cwd, fix=fix)
    if problems:
        return _stop(problems)
    moved = _versions(replanned) != _versions(updates)
    if moved:
        return _stop(
            [
                f"npm's latest moved from {_named(updates)} to {_named(replanned)} after you "
                "confirmed the carrier re-check; rerun the session for the new versions"
            ]
        )

    print("\n== 4. pi's models.json ==")
    models_note = models_json_note(ctx.environ, ctx.home())
    print("\n".join(models_note))

    problems = _session_evidence(ctx, cwd, version, head)
    if problems is None:
        return _stop(["you did not confirm the evidence run"])
    if problems:
        print(f"Do not tag {version}: the evidence did not pass.", file=sys.stderr)
        return _stop(problems, spent=True)

    print(f"\n== 6. For PR #{pr}'s description ==")
    for line in [*_record_note(cwd), models_note[0]]:
        print(f"- {line}")
    print("\n".join(models_note[1:]))

    print("\n== 7. The rest of the release ==")
    print("Run it today (the record's freshness window is 24 hours). Each block stops at its")
    print("first failure, and the second waits for your pypi approval. This script never tags,")
    print("merges or pushes; those are yours. Each block starts by moving into the worktree,")
    print("because its checks read the record there, not in the checkout you started from:")
    enter = f"cd {shlex.quote(str(cwd))}"
    for block in next_steps(cwd, version, pr, head):
        print()
        print("  " + " &&\\\n  ".join([enter, *block]))
    return 0


# --- post-merge: before the tag is pushed -----------------------------------------------


def _is_ancestor(ctx: Context, ancestor: str, descendant: str) -> bool | None:
    """`merge-base --is-ancestor`: 0 is yes, 1 is no, and anything else is no answer."""
    proc = ctx.git_out("merge-base", "--is-ancestor", ancestor, descendant)
    return {0: True, 1: False}.get(proc.returncode)


FAST_FORWARD = "fast-forward: main's tip is the release commit"
ORDINARY_MERGE = "ordinary merge: main's tip merges the release commit as its second parent"


def _merge_shape(ctx: Context, tip: str, release: str) -> tuple[str | None, list[str]]:
    """How `origin/main`'s tip holds the release commit, or the problems that say it does not.

    Two shapes hold: the ordinary merge commit step 4 prescribes, whose second parent is
    exactly the release commit, and the documented fast-forward alternative, where the tip IS
    the release commit. Anything else means main does not hold what the evidence names.
    """
    if tip == release:
        return FAST_FORWARD, []
    proc = ctx.git_out("rev-list", "--parents", "-n", "1", tip)
    if proc.returncode != 0:
        problem = f"could not read the parents of origin/main's tip {tip}: {_stderr_line(proc)}"
        return None, [problem]
    parents = proc.stdout.split()[1:]
    if len(parents) == 2 and parents[1] == release:
        return ORDINARY_MERGE, []
    return None, _merge_shape_problems(ctx, tip, release, parents)


def _merge_shape_problems(ctx: Context, tip: str, release: str, parents: list[str]) -> list[str]:
    if len(parents) < 2 and _is_ancestor(ctx, release, tip):
        return [
            f"origin/main's tip {tip} is a later commit than the release commit {release}, "
            "not a merge of it: main was fast-forwarded past it, or work landed on top. This is "
            "not a squash or rebase. The evidence does not cover main's tip; stop the release"
        ]
    if len(parents) < 2:
        return [
            f"origin/main's tip {tip} is not a merge commit, so the release PR was squashed or "
            f"rebased: {release} is not what main merged and the evidence covers nothing in "
            "main; stop the release (RELEASING step 4 forbids both)"
        ]
    if len(parents) > 2:
        return [f"origin/main's tip {tip} is an octopus merge of {len(parents)} parents; stop"]
    first, second = parents
    if _is_ancestor(ctx, release, first):
        return [
            f"origin/main's tip {tip} merges {second}, not the release commit: other work "
            "merged after the release merge, so main no longer holds the tree the tag names; "
            "stop the release (rule 19: the tag push is the only work that follows the merge)"
        ]
    return [
        f"origin/main's tip {tip} is an ordinary merge, but of {second}, not of the release "
        f"commit {release}: the PR branch gained a commit after the evidence was recorded. "
        "This is not a squash or rebase. The evidence does not cover what merged; stop the "
        "release"
    ]


def _tag_message(ctx: Context, tag: str) -> bytes | None:
    """The annotated tag's message, raw bytes, with any signature block dropped."""
    proc = ctx.git(
        ["git", "cat-file", "tag", f"refs/tags/{tag}"],
        cwd=ctx.repo_root,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        return None
    # Run without `text=True`, so stdout is bytes whatever `Context.git`'s annotation says.
    raw = cast("bytes", proc.stdout)
    _headers, _, message = raw.partition(b"\n\n")
    signature = _SIGNATURE_BYTES_RE.search(message)
    return message[: signature.start()] if signature else message


def _tag_problems(ctx: Context, tag: str, release: str) -> list[str]:
    kind = ctx.git_out("cat-file", "-t", f"refs/tags/{tag}")
    if kind.returncode != 0:
        return [f"there is no local tag {tag}; step 3 creates it, annotated, before the merge"]
    if kind.stdout.strip() != "tag":
        return [
            f"{tag} is a lightweight tag (git reports {kind.stdout.strip()!r}); rule 20 requires "
            "an annotated tag whose message is the evidence record"
        ]
    problems = []
    peeled = _rev(ctx, f"refs/tags/{tag}^{{commit}}")
    if peeled != release:
        problems.append(f"{tag} points at {peeled}, not the release commit {release}")
    record_path = ctx.repo_root / EVIDENCE_PATH
    try:
        record = record_path.read_bytes()
    except OSError as exc:
        return [*problems, f"could not read {EVIDENCE_PATH} in this checkout: {exc}"]
    message = _tag_message(ctx, tag)
    if message is None:
        problems.append(f"could not read {tag}'s message")
    elif message != record:
        problems.append(
            f"{tag}'s message is not {record_path} byte for byte; it was tagged from another "
            "record (0.3.0 was first tagged with 0.2.0's). Recreate the unpushed tag with "
            "`--cleanup=verbatim -F` and that file's absolute path"
        )
    return problems


def cmd_post_merge(ctx: Context, args: argparse.Namespace) -> int:
    version: str = args.version
    tag = f"v{version}"

    def fail(problems: list[str]) -> int:
        print(f"post-merge checks for {version} do NOT hold; do not push {tag}:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    problems = _version_problems(version)
    release = _rev(ctx, f"{args.release_sha}^{{commit}}")
    if release is None:
        problems.append(f"{args.release_sha!r} names no commit in this checkout")
    # `gh pr merge` moves GitHub, not this checkout's origin/main; a stale ref passes
    # every check below while meaning nothing, so a failed fetch stops everything.
    fetch = ctx.git_out("fetch", "--no-tags", "origin", "+refs/heads/main:refs/remotes/origin/main")
    if fetch.returncode != 0:
        problems.append(
            f"`git fetch origin` failed, so origin/main may be stale: {_stderr_line(fetch)}"
        )
    if problems:
        return fail(problems)
    assert release is not None
    tip = _rev(ctx, "refs/remotes/origin/main^{commit}")
    if tip is None:
        return fail(["could not resolve origin/main after fetching it"])

    shape, shape_problems = _merge_shape(ctx, tip, release)
    problems += shape_problems
    if _rev(ctx, f"{tip}^{{tree}}") != _rev(ctx, f"{release}^{{tree}}"):
        problems.append(
            f"origin/main's tree differs from the release commit's; something else is in main, "
            f"see `git diff --stat {release} origin/main`"
        )
    ancestor = _is_ancestor(ctx, release, tip)
    if ancestor is None:
        problems.append(f"could not tell whether {release} is in origin/main's history")
    elif not ancestor:
        problems.append(f"the release commit {release} is not in origin/main's history")
    head = _rev(ctx, "HEAD")
    if head != release:
        problems.append(
            f"HEAD is {head}, not the release commit; run this in the release PR's worktree, "
            "whose files the release-state check below reads"
        )
    problems += _clean_tree_problems(ctx)
    if not _version_problems(version):
        problems += _tag_problems(ctx, tag, release)
        print(f"running scripts/check_release_state.py --tag {tag} --commit {release}:", flush=True)
        problems += _script_problems(
            ctx, "scripts/check_release_state.py", "--tag", tag, "--commit", release
        )
    if problems:
        return fail(problems)
    print(f"post-merge checks hold: origin/main is {tip}, a {shape}.")
    print(f"Its tree is the release commit {release}'s, and {tag} is annotated, points at it")
    print("and carries")
    print(f"{EVIDENCE_PATH} verbatim. That record is the maintainer's assertion that the")
    print("live gates passed, checked here for shape and commit; it is not proof they ran.")
    print(f"Pushing {tag} is yours (docs/RELEASING.md step 6): git push origin {tag}")
    return 0


# --- post-publish: after the publish workflow, before the pointer moves -----------------

# The version-specific document, not the project one: right after an upload PyPI's CDN can
# serve the project JSON stale while this one already lists the files (#464).
PYPI_VERSION_JSON_URL = "https://pypi.org/pypi/amicus/{version}/json"
SERVER_NAME = "amicus"
CONSOLE_SCRIPT = "amicus-mcp"
# A tag no release can carry: not X.Y.Z, so no release tooling makes it, and the `v*` ruleset
# (AGENTS.md rule 21) stops anyone without bypass from creating it.
NEGATIVE_CONTROL_REF = "v0.0.0-amicus-negative-control"
DEFAULT_INSTALL_TIMEOUT = 300.0
_INITIALIZE = json.dumps(
    {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "amicus-post-publish", "version": "0"},
        },
    }
)
# Git's own diagnostic for a ref the remote does not have, which uv 0.13.6 relays under
#   cause: failed to fetch branch or tag `v0.0.0-amicus-negative-control`
#   fatal: couldn't find remote ref refs/tags/v0.0.0-amicus-negative-control
# Only the second line counts: uv's wrapper on the first is the same for a DNS, auth or TLS
# failure (observed with an unresolvable host), so it says nothing about the ref.
_MISSING_REF_RE = re.compile(r"couldn't find remote ref (?:refs/(?:tags|heads)/)?(?P<ref>\S+)")
# What the install's PATH may hold besides uv's own directory (see `_isolated_path`).
_SYSTEM_PATH = ("/usr/bin", "/bin")
# The only ambient variables the install inherits (see `_install_env`): locale, TLS trust
# and proxies, which decide whether the network works, and nothing that steers Python, a
# virtual environment or uv's project and index resolution.
INSTALL_ENV_NAMES = frozenset(
    {
        "LANG",
        "USER",
        "LOGNAME",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "GIT_SSL_CAINFO",
        "GIT_SSL_CAPATH",
        *(f"{name}_PROXY" for name in ("HTTP", "HTTPS", "ALL", "NO")),
        *(f"{name}_proxy" for name in ("http", "https", "all", "no")),
    }
)


@dataclass(frozen=True)
class RemoteTag:
    """What a remote says `vX.Y.Z` is: the tag object and the commit it peels to."""

    tag: str
    obj: str
    commit: str


def _install_source(ctx: Context, ref: str) -> str:
    return f"git+{ctx.canonical_url}@{ref}"


def _pypi_problems(ctx: Context, version: str) -> list[str]:
    """PyPI's version document must exist and list files in `urls`: the project page alone
    proves only that some version of amicus was ever published, and its JSON can lag the
    upload on PyPI's CDN (#464). The version document 404s for a version PyPI lacks.
    """
    url = PYPI_VERSION_JSON_URL.format(version=version)
    try:
        data = json.loads(ctx.http_get(url))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return [f"PyPI has no release {version}; has the publish workflow's `pypi` job run?"]
        return [f"could not read {url}: {exc}"]
    except (OSError, ValueError) as exc:
        return [f"could not read {url}: {exc}"]
    files = data.get("urls") if isinstance(data, dict) else None
    if not isinstance(files, list):
        return [f"{url} carries no `urls` list"]
    if not files:
        return [f"PyPI lists {version} with no files; the upload did not land"]
    return []


def _ls_remote_tag(
    ctx: Context, remote: str, where: str, tag: str
) -> tuple[RemoteTag | None, list[str]]:
    """`remote`'s `tag` and its peeled commit; a lightweight tag has no peeled line."""
    ref = f"refs/tags/{tag}"
    proc = ctx.git_out("ls-remote", "--exit-code", remote, ref, f"{ref}^{{}}")
    if proc.returncode == 2:
        return None, [f"{where} has no tag {tag}; push it (RELEASING step 6) before this"]
    if proc.returncode != 0:
        return None, [f"could not ask {where} for {tag}: {_stderr_line(proc)}"]
    refs: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        sha, _, name = line.partition("\t")
        refs[name.strip()] = sha.strip()
    obj, commit = refs.get(ref), refs.get(f"{ref}^{{}}")
    if obj is None:
        return None, [f"{where}'s answer for {tag} does not name {ref}: {proc.stdout.strip()!r}"]
    if commit is None:
        return None, [
            f"{where}'s {tag} is a lightweight tag (no peeled `^{{}}` entry); a release tag is "
            "annotated and carries the evidence record (AGENTS.md rule 20)"
        ]
    if not (_FULL_SHA_RE.fullmatch(obj) and _FULL_SHA_RE.fullmatch(commit)):
        return None, [f"{where}'s answer for {tag} is not two SHAs: {proc.stdout.strip()!r}"]
    return RemoteTag(tag, obj, commit), []


def _remote_tag(ctx: Context, version: str) -> tuple[RemoteTag | None, list[str]]:
    """The tag as the canonical repository has it, which `origin` must match exactly.

    The install and the marketplace pointer both name the canonical repository, while the
    pointer's tag is fetched from `origin`, which may be a fork or a mirror; a tag object or
    commit there that differs would put a `sha` in the pointer that users do not install.
    """
    tag = f"v{version}"
    canonical, problems = _ls_remote_tag(
        ctx, ctx.canonical_url, f"the canonical repository {ctx.canonical_url}", tag
    )
    mirror, origin_problems = _ls_remote_tag(ctx, "origin", "origin", tag)
    problems += origin_problems
    if canonical is None or mirror is None:
        return None, problems
    if mirror != canonical:
        return None, [
            f"origin's {tag} (tag object {mirror.obj}, commit {mirror.commit}) does not match "
            f"the canonical repository's (tag object {canonical.obj}, commit {canonical.commit})"
        ]
    return canonical, []


def _isolated_path(bin_dir: Path) -> str:
    """A `PATH` on which no `amicus-mcp` but the installed package's can be found.

    When the package `--from` names lacks the console script, uv runs whatever `amicus-mcp`
    its `PATH` finds instead (observed on uv 0.13.6), and under `uv run` that includes this
    checkout's `.venv/bin`, whose server reports the checkout's version. So the install sees
    an allowlist, as `tests/test_packaging.py::_minimal_subprocess_path` does: `bin_dir`,
    holding links to `uvx`, `uv` and `git` (uv fetches git sources with it), then the core
    system directories, each checked to hold no `amicus-mcp`.
    """
    for program in ("uvx", "uv", "git"):
        found = shutil.which(program)
        if found is None:
            raise OSError(f"`{program}` is not on PATH")
        (bin_dir / program).symlink_to(Path(found).resolve())
    entries = [str(bin_dir), *(d for d in _SYSTEM_PATH if Path(d).is_dir())]
    for entry in entries[1:]:
        if (Path(entry) / CONSOLE_SCRIPT).exists():
            raise OSError(f"{entry} holds an `{CONSOLE_SCRIPT}` that could answer for the tag")
    return os.pathsep.join(entries)


def _install_env(root: Path) -> dict[str, str]:
    """The install's whole environment, built from an allowlist rather than inherited.

    An inherited `PYTHONPATH` naming a checkout's `src` would let the installed console
    script import the checkout's `amicus` ahead of the installed one (Python searches it
    before site-packages), so a broken tag could pass; `PYTHONHOME`, `VIRTUAL_ENV`,
    `UV_PROJECT*`, `UV_PYTHON` or an index override could steer the install the same way.
    So nothing Python-, venv- or uv-related is passed on: only `INSTALL_ENV_NAMES` and
    `LC_*`, with `PATH` from `_isolated_path`, the real `HOME` (uv keeps its managed Pythons
    under it), and fresh `TMPDIR`, `UV_CACHE_DIR` and `UV_TOOL_DIR`. Git reads no global or
    system config, whose `url.<base>.insteadOf` could fetch the tag from somewhere else.
    """
    env = {
        name: value
        for name, value in os.environ.items()
        if name in INSTALL_ENV_NAMES or name.startswith("LC_")
    }
    env.update(
        {
            "PATH": _isolated_path(root / "bin"),
            "HOME": os.environ.get("HOME") or str(Path.home()),
            "TMPDIR": str(root / "tmp"),
            "UV_CACHE_DIR": str(root / "cache"),
            "UV_TOOL_DIR": str(root / "tools"),
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
        }
    )
    return env


def _uvx(ctx: Context, ref: str, timeout: float) -> subprocess.CompletedProcess[str]:
    """Install `ref` as a user would and send it one `initialize`, with nothing cached.

    A fresh `UV_CACHE_DIR` and `UV_TOOL_DIR` are the point: `uvx` reuses a cached tool
    environment without resolving anything, so a warm cache can answer from a build already
    on this machine. It runs in an empty directory so that no project file there steers uv.
    Raises `subprocess.TimeoutExpired` and `OSError` for the caller to report.
    """
    with tempfile.TemporaryDirectory(prefix="amicus-post-publish-") as scratch:
        root = Path(scratch)
        for name in ("cache", "tools", "cwd", "bin", "tmp"):
            (root / name).mkdir()
        env = _install_env(root)
        return ctx.run(
            [str(root / "bin" / "uvx"), "--from", _install_source(ctx, ref), CONSOLE_SCRIPT],
            cwd=root / "cwd",
            env=env,
            input=_INITIALIZE + "\n",
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )


def _server_info(stdout: str) -> dict | None:
    """The `serverInfo` of the reply to request 1, or None when there is no such reply."""
    for line in stdout.splitlines():
        try:
            message = json.loads(line)
        except ValueError:
            continue
        if isinstance(message, dict) and message.get("id") == 1:
            result = message.get("result")
            info = result.get("serverInfo") if isinstance(result, dict) else None
            return info if isinstance(info, dict) else None
    return None


def _install_problems(ctx: Context, version: str, timeout: float) -> list[str]:
    tag = f"v{version}"
    try:
        proc = _uvx(ctx, tag, timeout)
    except subprocess.TimeoutExpired:
        return [f"installing {tag} and initializing it did not finish within {timeout:g}s"]
    except OSError as exc:
        return [f"could not run `uvx`: {exc}"]
    info = _server_info(proc.stdout or "")
    if info is None:
        return [
            f"installing {tag} gave no `initialize` reply (exit status {proc.returncode}): "
            f"{_stderr_line(proc)}"
        ]
    problems = []
    if info.get("name") != SERVER_NAME:
        problems.append(f"{tag}'s server calls itself {info.get('name')!r}, not {SERVER_NAME!r}")
    if info.get("version") != version:
        problems.append(f"{tag}'s server reports version {info.get('version')!r}, not {version!r}")
    return problems


def _negative_control_problems(ctx: Context, timeout: float) -> list[str]:
    """The same install of a tag that cannot exist must fail, and fail to resolve.

    A success means something other than the requested tag answered, so the positive check
    proves nothing. A timeout or any other failure is no control either: it would fail the
    same way whether or not resolution works.
    """
    ref = NEGATIVE_CONTROL_REF
    try:
        proc = _uvx(ctx, ref, timeout)
    except subprocess.TimeoutExpired:
        return [
            f"negative control: installing {ref} timed out after {timeout:g}s instead of "
            "failing to resolve, so it controls nothing"
        ]
    except OSError as exc:
        return [f"negative control: could not run `uvx`: {exc}"]
    if proc.returncode == 0:
        return [
            f"negative control: installing {ref}, which cannot exist, succeeded; something "
            "other than the requested tag is answering, so the install check proves nothing"
        ]
    stderr = proc.stderr or ""
    if ref not in {match["ref"] for match in _MISSING_REF_RE.finditer(stderr)}:
        return [
            f"negative control: installing {ref} failed, but not with uv's resolution error "
            f"(git's `couldn't find remote ref` for that ref), so it controls nothing: "
            f"{_stderr_line(proc)}"
        ]
    return []


def post_publish(ctx: Context, version: str, timeout: float) -> tuple[RemoteTag | None, list[str]]:
    """Every post-publish check; the remote tag when it resolves, and every problem."""
    problems = _version_problems(version)
    if problems:
        return None, problems
    print(f"checking PyPI for amicus {version}", flush=True)
    problems += _pypi_problems(ctx, version)
    print(f"resolving v{version} in the canonical repository and on origin", flush=True)
    remote, tag_problems = _remote_tag(ctx, version)
    problems += tag_problems
    print(f"installing v{version} with empty uv caches and initializing it", flush=True)
    problems += _install_problems(ctx, version, timeout)
    print(
        f"negative control: installing {NEGATIVE_CONTROL_REF}, which must not resolve", flush=True
    )
    problems += _negative_control_problems(ctx, timeout)
    return remote, problems


def cmd_post_publish(ctx: Context, args: argparse.Namespace) -> int:
    version: str = args.version
    remote, problems = post_publish(ctx, version, args.timeout)
    if problems:
        print(f"post-publish checks for {version} do NOT hold:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    assert remote is not None
    print(f"post-publish checks hold for {version}: PyPI lists its files, origin's {remote.tag}")
    print(f"peels to {remote.commit}, a fresh install of it answers `initialize` as")
    print(f"{SERVER_NAME} {version}, and a tag that cannot exist fails to resolve.")
    print("Next (docs/RELEASING.md step 7), on a fresh branch off main:")
    print(f"  uv run python scripts/release.py pointer --version {version}")
    return 0


# --- pointer: the marketplace pointer PR's edit ----------------------------------------------

_POINTER_FIELD_RE = '("{key}"\\s*:\\s*")[^"]*(")'


def _set_pointer_field(text: str, key: str, value: str) -> str:
    pattern = re.compile(_POINTER_FIELD_RE.format(key=key))
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise Refusal(f'{MARKETPLACE_PATH} has {len(matches)} "{key}" fields, expected 1')
    match = matches[0]
    return text[: match.start()] + match[1] + value + match[2] + text[match.end() :]


def pointer_text(text: str, tag: str, sha: str) -> str:
    """`text` with the pointer's `ref` and `sha` replaced and every other byte kept."""
    edited = _set_pointer_field(_set_pointer_field(text, "ref", tag), "sha", sha)
    source = json.loads(edited)["plugins"][0]["source"]
    if not isinstance(source, dict) or (source.get("ref"), source.get("sha")) != (tag, sha):
        raise Refusal(f"{MARKETPLACE_PATH}'s pointer did not take ref {tag} and sha {sha}")
    return edited


def _fetched_tag_problems(ctx: Context, remote: RemoteTag) -> list[str]:
    """Fetch exactly `remote.tag`, then require the local tag to be what origin reported.

    No `+` on the refspec: a local tag of that name that differs from origin's makes the
    fetch fail rather than be overwritten, and that conflict is reported, not resolved.
    """
    tag, ref = remote.tag, f"refs/tags/{remote.tag}"
    fetch = ctx.git_out("fetch", "--no-tags", "origin", f"{ref}:{ref}")
    if fetch.returncode != 0:
        return [
            f"could not fetch {tag} from origin: {_stderr_line(fetch)}. A local {tag} that "
            f"differs from origin's is not yours to keep; inspect it (`git show {tag}`) "
            "before deleting it"
        ]
    kind = ctx.git_out("cat-file", "-t", ref)
    if kind.stdout.strip() != "tag":
        return [f"the local {tag} is not an annotated tag (git reports {kind.stdout.strip()!r})"]
    problems = []
    obj = _rev(ctx, ref)
    if obj != remote.obj:
        problems.append(f"the local {tag} is tag object {obj}, but origin's is {remote.obj}")
    peeled = _rev(ctx, f"{ref}^{{commit}}")
    if peeled != remote.commit:
        problems.append(f"the local {tag} peels to {peeled}, but origin's peels to {remote.commit}")
    return problems


def cmd_pointer(ctx: Context, args: argparse.Namespace) -> int:
    version: str = args.version
    tag = f"v{version}"

    def fail(problems: list[str], *, written: bool = False) -> int:
        state = "put back as it was" if written else "not written"
        print(f"pointer for {version} refused; {MARKETPLACE_PATH} is {state}:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    problems = _version_problems(version)
    branch = ctx.git_out("symbolic-ref", "--quiet", "--short", "HEAD")
    if branch.returncode == 0 and branch.stdout.strip() == "main":
        problems.append("on branch main; make the pointer PR on its own branch (AGENTS.md rule 8)")
    problems += _clean_tree_problems(ctx)
    if problems:
        return fail(problems)

    # Rule 24 and RELEASING step 7: the pointer names only a release whose install was just
    # checked, so the checks run here rather than being trusted from an earlier invocation.
    remote, problems = post_publish(ctx, version, args.timeout)
    if problems:
        return fail(["post-publish checks failed, so the pointer stays:", *problems])
    assert remote is not None

    refresh = ctx.git_out(
        "fetch", "--no-tags", "origin", "+refs/heads/main:refs/remotes/origin/main"
    )
    if refresh.returncode != 0:
        stale = (
            f"`git fetch origin main` failed, so origin/main may be stale: {_stderr_line(refresh)}"
        )
        return fail([stale])
    problems = _fetched_tag_problems(ctx, remote)
    if problems:
        return fail(problems)

    path = ctx.repo_root / MARKETPLACE_PATH
    before = path.read_text(encoding="utf-8")
    try:
        after = pointer_text(before, tag, remote.commit)
    except (Refusal, ValueError, KeyError, IndexError, TypeError) as exc:
        return fail([f"could not edit {MARKETPLACE_PATH}: {exc}"])
    path.write_text(after, encoding="utf-8")
    problems = release_state.check_pull_request(
        "refs/remotes/origin/main", repo_root=ctx.repo_root, git=ctx.git
    )
    if problems:
        path.write_text(before, encoding="utf-8")
        return fail(problems, written=True)

    if after == before:
        print(f"{MARKETPLACE_PATH} already points at {tag} ({remote.commit}); nothing changed.")
    else:
        print(f"{MARKETPLACE_PATH}: ref -> {tag}, sha -> {remote.commit} (the peeled commit)")
    print("marketplace pointer check holds against origin/main, as CI will run it.")
    print("Yours to do (docs/RELEASING.md step 7): commit it as")
    print(f"  chore(release): point the marketplace at {tag}")
    print("and open the PR. A release is not complete until that PR merges.")
    return 0


# --- policy: the `v*` ruleset and the `pypi` environment, read back ---------------------------

REPOSITORY = "briandconnelly/amicus"
TAG_REF_PATTERN = "refs/tags/v*"
TAG_RESTRICTIONS = ("creation", "update", "deletion")
# A tag name a release could carry, matched against other rulesets' patterns.
RELEASE_TAG_SAMPLE = "refs/tags/v0.0.0"
PYPI_ENVIRONMENT = "pypi"
# The one deployment policy the environment may carry (RELEASING, "The `pypi` environment").
PYPI_POLICY = {"name": "v*", "type": "tag"}


class ApiError(Exception):
    """`gh api` gave no usable answer; a check that needed it cannot pass."""


def _gh_api(ctx: Context, path: str, *, paginate: bool = False) -> object:
    cmd = ["gh", "api", *(["--paginate", "--slurp"] if paginate else []), path]
    try:
        proc = ctx.run(cmd, cwd=ctx.repo_root, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise ApiError(f"could not run `gh api {path}`: {exc}") from exc
    if proc.returncode != 0:
        raise ApiError(f"`gh api {path}` failed: {_stderr_line(proc)}")
    try:
        return json.loads(proc.stdout)
    except ValueError as exc:
        raise ApiError(f"`gh api {path}` did not return JSON: {exc}") from exc


@dataclass
class PolicyReport:
    """A read-back's three outcomes. Anything in `problems` or `unknown` fails it."""

    problems: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _ref_name(ruleset: dict, key: str) -> list:
    return ((ruleset.get("conditions") or {}).get("ref_name") or {}).get(key) or []


def _may_block_release_tags(ruleset: dict) -> bool:
    """Whether an active ruleset that restricts creation could match a `v*` tag.

    Exclusions are ignored, so this errs towards reporting a lockout that is not there.
    """
    if ruleset.get("enforcement") != "active":
        return False
    if "creation" not in {rule.get("type") for rule in ruleset.get("rules") or []}:
        return False
    return any(
        pattern == "~ALL"
        or pattern.startswith("refs/tags/v")
        or fnmatch.fnmatchcase(RELEASE_TAG_SAMPLE, pattern)
        for pattern in _ref_name(ruleset, "include")
        if isinstance(pattern, str)
    )


def _bypass_findings(name: str, ruleset: dict, report: PolicyReport) -> None:
    if "bypass_actors" not in ruleset:
        report.unknown.append(
            f"{name}: the response has no `bypass_actors` key, so whether an agent identity may "
            "bypass it is unknown, not 'nobody'; GitHub omits the key for a requester without "
            "permission on the ruleset, such as the agent App token. Rerun under the "
            "maintainer's own token"
        )
        return
    actors = ruleset["bypass_actors"] or []
    integrations = [a for a in actors if a.get("actor_type") == "Integration"]
    if integrations:
        ids = ", ".join(str(a.get("actor_id")) for a in integrations)
        report.problems.append(
            f"{name} lets an Integration bypass it (actor_id {ids}); rule 21 permits no agent "
            "identity to bypass a ruleset on tags"
        )
    elif not actors and _may_block_release_tags(ruleset):
        report.problems.append(
            f"{name} restricts creation of tags a release may use and has an empty bypass list: "
            "nobody, the maintainer included, can create a v* tag, so the release is blocked; "
            "add the repository admin role, never an agent identity"
        )
    else:
        listed = ", ".join(f"{a.get('actor_type')} {a.get('actor_id')}" for a in actors)
        report.notes.append(f"{name} bypass list: {listed or 'empty'}")


def check_tag_rulesets(rulesets: list[dict], report: PolicyReport) -> None:
    """Rule 21 on full ruleset records, each from `rulesets/<id>` (the list omits the rules).

    A ruleset qualifies when it targets tags, includes `refs/tags/v*`, excludes nothing, is
    `active`, and restricts creation, update and deletion. Every ruleset targeting tags is held
    to the bypass rule, whatever its patterns, because a broader one (`refs/tags/*`, `~ALL`)
    covers `v*` too; an absent `bypass_actors` key is unknown, never an empty list. Any active
    one that restricts creation of tags a release may use must let someone bypass it, or the
    maintainer cannot push the tag either.
    """
    tag_rulesets = [r for r in rulesets if r.get("target") == "tag"]
    if not any(TAG_REF_PATTERN in _ref_name(r, "include") for r in tag_rulesets):
        report.problems.append(f"no ruleset targets {TAG_REF_PATTERN} (AGENTS.md rule 21)")
    qualified = False
    for ruleset in tag_rulesets:
        name = f"ruleset {ruleset.get('name')!r} ({ruleset.get('id')})"
        qualifies = False
        if TAG_REF_PATTERN in _ref_name(ruleset, "include"):
            shortfalls = []
            if ruleset.get("enforcement") != "active":
                shortfalls.append(
                    f"its enforcement is {ruleset.get('enforcement')!r}, not 'active'"
                )
            if exclude := _ref_name(ruleset, "exclude"):
                shortfalls.append(f"it excludes {exclude}")
            types = {rule.get("type") for rule in ruleset.get("rules") or []}
            if missing := [kind for kind in TAG_RESTRICTIONS if kind not in types]:
                shortfalls.append(f"it does not restrict {', '.join(missing)}")
            if shortfalls:
                report.notes.append(f"{name} covers {TAG_REF_PATTERN} but {'; '.join(shortfalls)}")
            qualifies = not shortfalls
        qualified = qualified or qualifies
        _bypass_findings(name, ruleset, report)
        report.notes.append(
            f"{name}: current_user_can_bypass is {ruleset.get('current_user_can_bypass')!r}, "
            "which describes whoever's token ran this read-back, not the repository"
        )
    if tag_rulesets and not qualified:
        report.problems.append(
            f"no active ruleset covering {TAG_REF_PATTERN} restricts "
            f"{', '.join(TAG_RESTRICTIONS)} with no exclusions (AGENTS.md rule 21)"
        )


def check_pypi_environment(environment: dict, policies: dict, report: PolicyReport) -> None:
    """The environment's reviewer gate, and its one deployment policy: a tag policy `v*`."""
    reviewers = [
        reviewer
        for rule in environment.get("protection_rules") or []
        if rule.get("type") == "required_reviewers"
        for reviewer in rule.get("reviewers") or []
    ]
    if not reviewers:
        report.problems.append(
            f"the {PYPI_ENVIRONMENT!r} environment has no required_reviewers rule with a reviewer"
        )
    scope = environment.get("deployment_branch_policy")
    if not (isinstance(scope, dict) and scope.get("custom_branch_policies") is True):
        report.problems.append(
            f"the {PYPI_ENVIRONMENT!r} environment's deployment_branch_policy is {scope!r}; it "
            "must use custom policies, or its deployment policies do not apply"
        )
    entries = policies.get("branch_policies")
    if not isinstance(entries, list):
        report.unknown.append("the deployment-branch-policies response has no branch_policies")
        return
    if policies.get("total_count") != len(entries):
        report.unknown.append(
            f"the deployment-branch-policies response lists {len(entries)} of "
            f"{policies.get('total_count')} policies"
        )
    found = [{"name": e.get("name"), "type": e.get("type")} for e in entries]
    if PYPI_POLICY not in found:
        report.problems.append(
            f"the {PYPI_ENVIRONMENT!r} environment has no deployment policy typed 'tag' named "
            "'v*'; a 'branch' policy of that name blocks every release, which is made from a tag"
        )
    for entry in found:
        if entry != PYPI_POLICY:
            report.problems.append(
                f"the {PYPI_ENVIRONMENT!r} environment also allows {entry['type']} "
                f"{entry['name']!r}; its only deployment policy must be tag 'v*'"
            )


def policy_report(ctx: Context) -> PolicyReport:
    """Read back rule 21's rulesets and the `pypi` environment under whatever token `gh` has."""
    report = PolicyReport()
    base = f"repos/{REPOSITORY}"
    try:
        pages = cast(
            "list[list[dict]]", _gh_api(ctx, f"{base}/rulesets?per_page=100", paginate=True)
        )
        rulesets = [
            cast("dict", _gh_api(ctx, f"{base}/rulesets/{summary['id']}"))
            for page in pages
            for summary in page
            if summary.get("target") == "tag"
        ]
        check_tag_rulesets(rulesets, report)
    except (ApiError, AttributeError, KeyError, TypeError) as exc:
        report.unknown.append(f"could not read the rulesets: {exc}")
    try:
        environment = _gh_api(ctx, f"{base}/environments/{PYPI_ENVIRONMENT}")
        policies = _gh_api(
            ctx, f"{base}/environments/{PYPI_ENVIRONMENT}/deployment-branch-policies?per_page=100"
        )
        check_pypi_environment(cast("dict", environment), cast("dict", policies), report)
    except (ApiError, AttributeError, KeyError, TypeError) as exc:
        report.unknown.append(f"could not read the {PYPI_ENVIRONMENT!r} environment: {exc}")
    return report


def cmd_policy(ctx: Context, _args: argparse.Namespace) -> int:
    report = policy_report(ctx)
    for note in report.notes:
        print(f"  {note}", flush=True)
    if report.problems or report.unknown:
        print("the release policy read-back does NOT hold:", file=sys.stderr)
        for problem in report.problems:
            print(f"  - {problem}", file=sys.stderr)
        for unknown in report.unknown:
            print(f"  - UNKNOWN: {unknown}", file=sys.stderr)
        return 1
    print(
        f"the release policy read-back holds: an active ruleset restricts creation, update and "
        f"deletion of {TAG_REF_PATTERN}, no Integration may bypass any tag ruleset, and "
        f"the {PYPI_ENVIRONMENT!r} environment requires a reviewer and deploys only from tag "
        "'v*'. Whether you can push the tag is current_user_can_bypass above, under your token."
    )
    return 0


# --- ci: the rule-2 gate as CI ran it on the release commit ----------------------------

CI_WORKFLOW = ".github/workflows/ci.yml"
GATE_WORKFLOW = ".github/workflows/test.yml"
GATE_JOB = "gate"
GITHUB_ACTIONS_APP = "github-actions"
_CALLER_RE = re.compile(
    r"^  (?P<job>[A-Za-z0-9_-]+):\n    uses: \./" + re.escape(GATE_WORKFLOW) + r"[ \t]*$",
    re.MULTILINE,
)
# A job's key under `jobs:`; a two-space key with nothing after its colon ends the job above it.
_JOB_KEY_RE = re.compile(r"^  (?P<job>[A-Za-z0-9_-]+):[ \t]*$", re.MULTILINE)
_GATE_NAME_RE = re.compile(r"^    name: (?P<name>.+?)[ \t]*$", re.MULTILINE)
_MATRIX_RE = re.compile(r"^ +python-version: \[(?P<versions>[^\]]*)\][ \t]*$", re.MULTILINE)
# `include` can add a job the version list does not name, so a matrix with either is refused
# rather than read short.
_MATRIX_EDIT_RE = re.compile(r"^ +-? *(?:include|exclude):", re.MULTILINE)
_MATRIX_SLOT = "${{ matrix.python-version }}"


def _job_text(workflow: str, job: str) -> str:
    """The lines of `job` in a workflow, from its key to the next job's, or "" when absent."""
    keys = list(_JOB_KEY_RE.finditer(workflow))
    for here, after in zip(keys, [*keys[1:], None], strict=True):
        if here["job"] == job:
            return workflow[here.start() : after.start() if after else len(workflow)]
    return ""


def gate_checks(repo_root: Path) -> list[str]:
    """The check-run name of every rule-2 gate job CI runs: `ci.yml`'s job that calls
    `test.yml`, then the `gate` job's name for each Python version in its matrix, as GitHub
    names the check run of a called workflow's job. Raises ValueError when the workflows no
    longer have the shape this reads, so a change to them cannot pass unseen."""
    ci = (repo_root / CI_WORKFLOW).read_text(encoding="utf-8")
    gate = _job_text((repo_root / GATE_WORKFLOW).read_text(encoding="utf-8"), GATE_JOB)
    if _MATRIX_EDIT_RE.search(gate):
        raise ValueError(
            f"the `{GATE_JOB}` job's matrix in {GATE_WORKFLOW} has an include or exclude, which "
            "this does not read, so it cannot tell which gate jobs CI runs"
        )
    callers = _CALLER_RE.findall(ci)
    names = _GATE_NAME_RE.findall(gate)[:1]
    matrices = _MATRIX_RE.findall(gate)
    if len(callers) != 1 or len(names) != 1 or len(matrices) != 1:
        raise ValueError(
            f"expected one job in {CI_WORKFLOW} calling {GATE_WORKFLOW}, and one `{GATE_JOB}` "
            f"job with one python-version matrix in it; found {len(callers)}, {len(names)} and "
            f"{len(matrices)}"
        )
    versions = [v.strip().strip("\"'") for v in matrices[0].split(",") if v.strip()]
    if not versions or _MATRIX_SLOT not in names[0]:
        raise ValueError(f"could not read the `{GATE_JOB}` job's matrix from {GATE_WORKFLOW}")
    return [f"{callers[0]} / {names[0].replace(_MATRIX_SLOT, v)}" for v in versions]


def _tested_tree_problems(ctx: Context, sha: str) -> list[str]:
    """Whether CI's runs on `sha` tested `sha`'s own tree. On a pull request CI checks out the
    head merged with `main` as `main` stood at the push, not the head alone. When origin's
    `main`, freshly fetched, is in `sha`'s history, so was every earlier `main`, and merging an
    ancestor leaves `sha`'s tree as it is; otherwise CI may have passed on code `sha` lacks."""
    fetch = ctx.git_out("fetch", "--no-tags", "origin", "+refs/heads/main:refs/remotes/origin/main")
    if fetch.returncode != 0:
        return [
            f"`git fetch origin` failed, so whether CI tested {sha}'s own tree is unknown: "
            f"{_stderr_line(fetch)}"
        ]
    tip = _rev(ctx, "refs/remotes/origin/main^{commit}")
    if tip is None:
        return ["could not resolve origin/main after fetching it"]
    contained = _is_ancestor(ctx, tip, sha)
    if contained is None:
        return [f"could not tell whether origin/main ({tip}) is in {sha}'s history"]
    if not contained:
        return [
            f"origin/main ({tip}) is not in {sha}'s history, so CI tested the release merged "
            "with commits it lacks rather than its own tree; bring the release branch up to "
            "date with main, which makes a new release commit and needs new evidence"
        ]
    return []


def ci_problems(ctx: Context, sha: str) -> tuple[list[str], list[str]]:
    """Whether every rule-2 gate job passed on `sha`, from GitHub's check runs, on `sha`'s own
    tree. Returns the jobs that passed and the problems; a job that has not run, is still
    running, or ended any way but success is a problem. The newest run of a job decides, so a
    rerun that passed replaces a failure."""
    if not _FULL_SHA_RE.fullmatch(sha):
        return [], [f"{sha!r} is not a full commit SHA"]
    try:
        expected = gate_checks(ctx.repo_root)
    except (OSError, ValueError) as exc:
        return [], [f"could not tell which jobs are the gate: {exc}"]
    tree_problems = _tested_tree_problems(ctx, sha)
    try:
        pages = cast(
            "list[dict]",
            _gh_api(
                ctx, f"repos/{REPOSITORY}/commits/{sha}/check-runs?per_page=100", paginate=True
            ),
        )
        runs = [run for page in pages for run in page["check_runs"]]
        newest: dict[str, dict] = {}
        for run in sorted(runs, key=lambda run: run["id"]):
            # A check run any other app created can carry the same name; only CI's counts.
            if (run.get("app") or {}).get("slug") == GITHUB_ACTIONS_APP:
                newest[run["name"]] = run
    except (ApiError, KeyError, TypeError) as exc:
        return [], [*tree_problems, f"could not read the check runs on {sha}: {exc}"]
    passed, problems = [], list(tree_problems)
    for name in expected:
        run = newest.get(name)
        if run is None:
            problems.append(f"{name}: has not run on {sha}")
        elif run.get("status") != "completed":
            problems.append(f"{name}: still {run.get('status')}; wait for it, then run this again")
        elif run.get("conclusion") != "success":
            problems.append(f"{name}: {run.get('conclusion')} ({run.get('html_url')})")
        else:
            passed.append(name)
    return passed, problems


def cmd_ci(ctx: Context, args: argparse.Namespace) -> int:
    passed, problems = ci_problems(ctx, args.sha)
    if problems:
        print(f"the rule-2 gate has NOT passed in CI on {args.sha}:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print(f"the rule-2 gate passed in CI on {args.sha}: {', '.join(passed)}.")
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

    preflight = commands.add_parser(
        "preflight",
        help="check the release worktree before the live-gate evidence (RELEASING step 3)",
        description="Check the release PR's worktree; print, never run, the evidence command.",
    )
    preflight.add_argument("--pr", type=int, required=True, help="the release PR's number")
    preflight.add_argument("--version", required=True, help="the version being released, X.Y.Z")
    preflight.add_argument(
        "--fix",
        action="store_true",
        help="a release that ships an important bug or security fix: its CHANGELOG.md section "
        "has only Fixed and Security entries, and a backend whose npm latest the shipped "
        "contract does not support yet stays on the newest one it does (docs/RELEASING.md)",
    )
    preflight.add_argument(
        "--override-fix-changelog",
        action="store_true",
        help="with --fix: warn rather than fail when the CHANGELOG.md section has other "
        "entries; say why in the release PR",
    )
    preflight.set_defaults(handler=cmd_preflight)

    session = commands.add_parser(
        "session",
        help="run RELEASING step 3 in one go, asking before it installs or spends",
        description="Make or reuse the release worktree, update the backend CLIs, run the "
        "checks that spend nothing, note pi's models.json, and run the evidence only after "
        "a typed confirmation. Never tags, merges or pushes.",
    )
    session.add_argument("--pr", type=int, required=True, help="the release PR's number")
    session.add_argument("--version", required=True, help="the version being released, X.Y.Z")
    session.add_argument(
        "--worktree",
        type=Path,
        help="the release worktree (default: amicus-wt-release-X-Y-Z beside this checkout)",
    )
    session.add_argument(
        "--fix",
        action="store_true",
        help="a release that ships an important bug or security fix: its CHANGELOG.md section "
        "has only Fixed and Security entries, and a backend whose npm latest the shipped "
        "contract does not support yet stays on the newest one it does (docs/RELEASING.md)",
    )
    session.add_argument(
        "--override-fix-changelog",
        action="store_true",
        help="with --fix: warn rather than fail when the CHANGELOG.md section has other "
        "entries; say why in the release PR",
    )
    session.set_defaults(handler=cmd_session)

    ci = commands.add_parser(
        "ci",
        help="check that CI ran the rule-2 gate on the release commit and it passed",
        description="Read the release commit's check runs from GitHub; read-only.",
    )
    ci.add_argument("--sha", required=True, help="the release commit")
    ci.set_defaults(handler=cmd_ci)

    post_merge = commands.add_parser(
        "post-merge",
        help="check the merge and the local tag before pushing it (RELEASING step 5)",
        description="Fetch origin's main, then check its merge of the release commit and the tag.",
    )
    post_merge.add_argument(
        "--release-sha", required=True, help="the release commit: the PR's tip the evidence names"
    )
    post_merge.add_argument("--version", required=True, help="the version being released, X.Y.Z")
    post_merge.set_defaults(handler=cmd_post_merge)

    timeout_help = "seconds to allow each install-and-initialize (default %(default)g)"
    post_publish_parser = commands.add_parser(
        "post-publish",
        help="check PyPI, the remote tag and a fresh install after publishing (post-tag checks)",
        description="Check the published release; read-only, spends nothing.",
    )
    post_publish_parser.add_argument("--version", required=True, help="the released version")
    post_publish_parser.add_argument(
        "--timeout", type=float, default=DEFAULT_INSTALL_TIMEOUT, help=timeout_help
    )
    post_publish_parser.set_defaults(handler=cmd_post_publish)

    pointer = commands.add_parser(
        "pointer",
        help="advance the marketplace pointer to a published tag (RELEASING step 7)",
        description="Run post-publish, then write the tag's ref and peeled sha into the pointer.",
    )
    pointer.add_argument("--version", required=True, help="the published version, X.Y.Z")
    pointer.add_argument(
        "--timeout", type=float, default=DEFAULT_INSTALL_TIMEOUT, help=timeout_help
    )
    pointer.set_defaults(handler=cmd_pointer)

    policy = commands.add_parser(
        "policy",
        help="read back the v* tag ruleset and the pypi environment (RELEASING preconditions)",
        description="Read back rule 21's ruleset and the pypi environment; read-only.",
    )
    policy.set_defaults(handler=cmd_policy)
    return parser


def main(argv: list[str] | None = None, *, context: Context | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.handler(context or Context(), args)


if __name__ == "__main__":
    raise SystemExit(main())
