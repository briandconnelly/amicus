#!/usr/bin/env python
"""Check that a tree — and, at release time, the tag that names it — is releasable.

This is the release predicate the publish workflow reads. It answers two different kinds of
question, and the difference matters more than the code:

1. **Release-state coherence** (`check_tree`). Every version literal AGENTS.md rule 19 names
   agrees with the version being released, `CHANGELOG.md` has exactly one dated section for
   that version with `## [Unreleased]` above it, and `uv.lock` is current. These are facts of
   the tagged tree, so a green result here *proves* them. Nothing self-asserts.

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
_MCP_SOURCE = "git+https://github.com/briandconnelly/amicus.git@v{version}"

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


def check_version_literals(version: str, *, repo_root: Path = REPO_ROOT) -> list[str]:
    """Every rule-19 literal must equal `version`.

    `tests/test_packaging.py` already asserts these agree with each other on every PR. This
    checks them against the version actually being released, on the tagged tree, in the
    workflow that publishes — which is the part CI never ran, because `ci.yml` triggers on
    pushes to `main` and on pull requests, never on a tag.
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

    args = json.loads((repo_root / ".mcp.json").read_text(encoding="utf-8"))
    source = args["mcpServers"]["amicus"]["args"]
    expected = _MCP_SOURCE.format(version=version)
    if expected not in source:
        problems.append(f".mcp.json does not install {expected!r}; its args are {source!r}")

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


def check_tree(
    version: str,
    *,
    repo_root: Path = REPO_ROOT,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> list[str]:
    """Every release-state fact this tree can prove about `version`."""
    return [
        *check_version_literals(version, repo_root=repo_root),
        *check_changelog(version, repo_root=repo_root),
        *check_lock(repo_root=repo_root, run=run),
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
