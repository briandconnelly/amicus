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
exists on `origin` or locally, and that `scripts/check_backend_compat.py` passes. On success it
prints the evidence command, and never runs it: that spends live quota, which only the
maintainer authorizes (AGENTS.md rules 5 and 20).

`post-merge --release-sha SHA --version X.Y.Z` runs in the same worktree after the release PR
merges (RELEASING step 5). It fetches `main` from `origin` first and fails if it cannot, then
checks that `origin/main`'s tip is an ordinary merge commit whose second parent is SHA, that its
tree is SHA's tree, that SHA is in `origin/main`'s history, that `HEAD` is SHA on a clean tree,
and that the local tag `vX.Y.Z` is annotated, peels to SHA and carries
`.release-evidence/live-gates.json` byte for byte; then it runs
`check_release_state.py --tag vX.Y.Z --commit SHA`. It never tags, pushes or merges. A pass
says the tag carries the record the maintainer wrote; it is not proof the live gates ran
(AGENTS.md rule 23).

Usage:
    uv run python scripts/release.py prepare X.Y.Z [--check]
    uv run python scripts/release.py preflight --pr N --version X.Y.Z
    uv run python scripts/release.py post-merge --release-sha SHA --version X.Y.Z

Exits 0 on success, 1 on a refusal or a failed check, printing each problem.
Pure stdlib, like `check_release_state.py`; it runs `git`, `gh` and `uv`.
"""

from __future__ import annotations

import argparse
import datetime as dt
import difflib
import importlib.util
import json
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, cast

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
    print("  - the rule-18 carrier re-check and everything from RELEASING step 3 on")
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


def _stderr_line(proc: subprocess.CompletedProcess) -> str:
    text = proc.stderr if isinstance(proc.stderr, str) else (proc.stderr or b"").decode()
    lines = text.strip().splitlines()
    return lines[-1] if lines else f"exit status {proc.returncode}"


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
    cmd = ["gh", "pr", "view", str(number), "--json", "headRefOid,headRefName,state,baseRefName"]
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
        problems.append(f"PR #{number} is {pr.get('state')}, not OPEN; the release PR is unmerged")
    if pr.get("baseRefName") != "main":
        problems.append(f"PR #{number} targets {pr.get('baseRefName')!r}, not main")
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


def cmd_preflight(ctx: Context, args: argparse.Namespace) -> int:
    version: str = args.version
    tag = f"v{version}"
    problems = _version_problems(version)
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
    print("running scripts/check_backend_compat.py (spends nothing):", flush=True)
    problems += _script_problems(ctx, "scripts/check_backend_compat.py")

    if problems:
        print(f"preflight for {version} does NOT hold; do not record evidence:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    print(f"preflight holds for {version} at {head} (PR #{args.pr}, {pr and pr['headRefName']}).")
    print(f"Record that SHA: it is the release commit, the one {tag} will point at.")
    print("Still yours before the evidence run (docs/RELEASING.md step 3): the backend CLIs at")
    print("npm's latest with Claude Code's autoupdater held, and the rule-18 carrier re-check.")
    print("The evidence run spends live quota on all three backends and needs the maintainer's")
    print("authorization in the session that runs it. This script never runs it. The command:")
    print(f"  {evidence_command(ctx.repo_root, version)}")
    return 0


# --- post-merge: before the tag is pushed -----------------------------------------------


def _is_ancestor(ctx: Context, ancestor: str, descendant: str) -> bool | None:
    """`merge-base --is-ancestor`: 0 is yes, 1 is no, and anything else is no answer."""
    proc = ctx.git_out("merge-base", "--is-ancestor", ancestor, descendant)
    return {0: True, 1: False}.get(proc.returncode)


def _merge_shape_problems(ctx: Context, tip: str, release: str) -> list[str]:
    """`origin/main`'s tip must be the ordinary merge commit of exactly the release commit."""
    proc = ctx.git_out("rev-list", "--parents", "-n", "1", tip)
    if proc.returncode != 0:
        return [f"could not read the parents of origin/main's tip {tip}: {_stderr_line(proc)}"]
    parents = proc.stdout.split()[1:]
    if len(parents) == 2 and parents[1] == release:
        return []
    if tip == release:
        return [
            f"origin/main's tip is the release commit {release} itself: main was "
            "fast-forwarded, not merged with the ordinary merge commit step 4 prescribes, and "
            "this check covers only that path"
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

    problems += _merge_shape_problems(ctx, tip, release)
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
    print(f"post-merge checks hold: origin/main ({tip}) is the ordinary merge of {release},")
    print(f"with an identical tree, and {tag} is annotated, points at it and carries")
    print(f"{EVIDENCE_PATH} verbatim. That record is the maintainer's assertion that the")
    print("live gates passed, checked here for shape and commit; it is not proof they ran.")
    print(f"Pushing {tag} is yours (docs/RELEASING.md step 6): git push origin {tag}")
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
    preflight.set_defaults(handler=cmd_preflight)

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
    return parser


def main(argv: list[str] | None = None, *, context: Context | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.handler(context or Context(), args)


if __name__ == "__main__":
    raise SystemExit(main())
