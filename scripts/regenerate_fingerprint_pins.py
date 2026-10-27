"""Regenerate every pin a ``FINGERPRINT`` bump moves, in one run (#373).

AGENTS.md rule 10: a change that touches a ``FINGERPRINT_COVERS`` category bumps
``FINGERPRINT`` and regenerates the pins under ``tests/fixtures/`` in their own commit.
This script is that regeneration. It writes:

- ``tests/fixtures/manifest_snapshot.<profile>.json`` for every manifest profile;
- ``tests/fixtures/fingerprint_pins.json``: the fingerprint string, each profile's
  full-manifest hash and each profile's ``surface_digest``;
- ``tests/fixtures/wire_shape_snapshot.json``, when its rendered output changed.

It then prints a unified diff of every file it changed, for review before committing.

Usage::

    uv run python scripts/regenerate_fingerprint_pins.py            # write the pins
    uv run python scripts/regenerate_fingerprint_pins.py --check    # write nothing

Writing refuses (exit 2, nothing written) unless the working tree's ``FINGERPRINT`` has the
same name and major as the one at ``git merge-base HEAD <base>`` (default ``origin/main``)
and a strictly higher ``schema-N``; it also refuses when that base cannot be read. So it
cannot paper over a surface change nobody acknowledged with a bump.

``--check`` does not require an advance: it renders every pin, reports each stale one with
its diff, and exits 1 if any is stale, 0 if none is. It never touches git.

Stays manual, and is only reported here: whether a change touches ``FINGERPRINT_COVERS`` and
its Breaking vs Surface label; ``RESULT_FORMAT`` and ``tests/fixtures/
result_format_snapshot.json`` (rule 11's own decision); and the discovery-cost ``MEASURED`` /
``BUDGET`` in ``tests/test_discovery_cost.py``, which a PR raises deliberately and justifies.
Drift in either is printed as a warning and never changes the exit code; the gate's own tests
still fail on it.

No test runs this script against the real tree, and nothing runs it on a test failure.
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import difflib
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import amicus.schemas.fingerprint as fingerprint_module
from amicus import manifest, surface
from amicus import result_format_snapshot as rfs
from amicus import wire_shape_snapshot as wss
from amicus.schemas.fingerprint import parse_fingerprint

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

REPO = Path(__file__).resolve().parent.parent
FINGERPRINT_SOURCE = "src/amicus/schemas/fingerprint.py"
PINS = "tests/fixtures/fingerprint_pins.json"
WIRE_SHAPE = "tests/fixtures/wire_shape_snapshot.json"
RESULT_FORMAT_SNAPSHOT = "tests/fixtures/result_format_snapshot.json"
DISCOVERY_COST_TEST = "tests/test_discovery_cost.py"
DEFAULT_BASE = "origin/main"

EXIT_OK = 0
EXIT_STALE = 1
EXIT_REFUSED = 2

_LITERAL_RE = re.compile(r'^FINGERPRINT\s*=\s*"([^"\n]*)"', re.MULTILINE)


class Refusal(Exception):
    """A reason not to write anything; main() prints it and exits 2."""


def snapshot_path(profile: str) -> str:
    return f"tests/fixtures/manifest_snapshot.{profile}.json"


def fingerprint_literal(source: str, where: str) -> str:
    """The ``FINGERPRINT = "..."`` literal in ``source``, read as text so a working tree
    and a git revision are read the same way."""
    found = _LITERAL_RE.findall(source)
    if len(found) != 1:
        raise Refusal(f'found {len(found)} `FINGERPRINT = "..."` assignments in {where}, need 1')
    return found[0]


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8", check=False
    )
    if proc.returncode != 0:
        detail = proc.stderr.strip() or f"exit {proc.returncode}"
        raise Refusal(f"`git {' '.join(args)}` failed: {detail}")
    return proc.stdout


def base_fingerprint(root: Path, base_ref: str) -> tuple[str, str]:
    """``(merge-base sha, FINGERPRINT there)`` for ``HEAD`` against ``base_ref``."""
    sha = _git(root, "merge-base", "HEAD", base_ref).strip()
    source = _git(root, "show", f"{sha}:{FINGERPRINT_SOURCE}")
    return sha, fingerprint_literal(source, f"{FINGERPRINT_SOURCE} at {sha[:12]}")


def require_advance(current: str, base: str) -> None:
    """Refuse unless ``current`` is ``base`` with a strictly higher schema number."""
    parsed: list[tuple[str, str, int]] = []
    for label, value in (("working tree", current), ("base", base)):
        try:
            parsed.append(parse_fingerprint(value))
        except ValueError as exc:
            raise Refusal(f"{label} FINGERPRINT is malformed: {exc}") from exc
    (name, major, rev), (base_name, base_major, base_rev) = parsed
    if (name, major) != (base_name, base_major):
        raise Refusal(
            f"FINGERPRINT {current!r} changes name or major from the base's {base!r}; "
            "this tool regenerates pins only for a schema-N bump"
        )
    if rev <= base_rev:
        verb = "is unchanged from" if rev == base_rev else "is lower than"
        raise Refusal(
            f"FINGERPRINT {current!r} {verb} the base's {base!r}: bump schema-N in "
            f"{FINGERPRINT_SOURCE} first (AGENTS.md rule 10), or use --check to only report"
        )


def render_pins() -> dict[str, str]:
    """Every pinned file's text as the live tree renders it, keyed by repo-relative path."""

    async def per_profile() -> dict[str, tuple[str, str]]:
        out: dict[str, tuple[str, str]] = {}
        for profile in sorted(manifest.PROFILES):
            text = manifest.manifest_json(
                await manifest.build_manifest(manifest.app_for_profile(profile))
            )
            digest = await surface.surface_digest(manifest.app_for_profile(profile))
            out[profile] = (text, digest)
        return out

    profiles = asyncio.run(per_profile())
    files = {snapshot_path(p): text for p, (text, _) in profiles.items()}
    pins = {
        "fingerprint": fingerprint_module.FINGERPRINT,
        "manifest_hash": {
            p: hashlib.sha256(text.encode("utf-8")).hexdigest() for p, (text, _) in profiles.items()
        },
        "surface_digest": {p: digest for p, (_, digest) in profiles.items()},
    }
    files[PINS] = json.dumps(pins, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    files[WIRE_SHAPE] = wss.render()
    return files


def committed_measured(root: Path) -> dict[str, int]:
    """``MEASURED`` from the discovery-cost test, read as a literal, never imported."""
    tree = ast.parse((root / DISCOVERY_COST_TEST).read_text(encoding="utf-8"))
    for node in tree.body:
        target = node.target if isinstance(node, ast.AnnAssign) else None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
        if isinstance(target, ast.Name) and target.id == "MEASURED" and node.value is not None:
            return ast.literal_eval(node.value)
    raise ValueError(f"no MEASURED literal in {DISCOVERY_COST_TEST}")


def manual_drift(root: Path) -> list[str]:
    """Warnings for the two things this script deliberately does not regenerate."""
    warnings: list[str] = []
    committed = (root / RESULT_FORMAT_SNAPSHOT).read_text(encoding="utf-8")
    if rfs.render() != committed:
        warnings.append(
            f"{RESULT_FORMAT_SNAPSHOT} is stale. Not regenerated: decide whether RESULT_FORMAT "
            "moves (AGENTS.md rule 11), then `uv run python -m amicus.result_format_snapshot > "
            f"{RESULT_FORMAT_SNAPSHOT}`."
        )
    measured = committed_measured(root)
    for profile in sorted(manifest.PROFILES):
        size = manifest.tools_list_bytes(profile)
        if size != measured.get(profile):
            warnings.append(
                f"tools/list for {profile!r} is {size} bytes; {DISCOVERY_COST_TEST} MEASURED "
                f"says {measured.get(profile)}. Not regenerated: a raise moves MEASURED and "
                "BUDGET together with a paragraph saying why."
            )
    return warnings


def unified(path: str, old: str | None, new: str) -> str:
    return "".join(
        difflib.unified_diff(
            (old or "").splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"a/{path}" if old is not None else "/dev/null",
            tofile=f"b/{path}",
        )
    )


@dataclass(frozen=True)
class Outcome:
    code: int
    report: str


def run(
    root: Path,
    *,
    check: bool,
    base_ref: str = DEFAULT_BASE,
    render: Callable[[], Mapping[str, str]] = render_pins,
    drift: Callable[[Path], list[str]] = manual_drift,
) -> Outcome:
    lines: list[str] = []
    if not check:
        current = fingerprint_literal(
            (root / FINGERPRINT_SOURCE).read_text(encoding="utf-8"), FINGERPRINT_SOURCE
        )
        sha, base = base_fingerprint(root, base_ref)
        require_advance(current, base)
        lines.append(f"FINGERPRINT {base} -> {current} (base {base_ref} @ {sha[:12]})")

    stale: dict[str, str] = {}
    for path, text in render().items():
        target = root / path
        old = target.read_text(encoding="utf-8") if target.exists() else None
        if old != text:
            stale[path] = text
            lines.append(unified(path, old, text).rstrip("\n"))
            if not check:
                target.write_text(text, encoding="utf-8")

    if not stale:
        lines.append("every fingerprint pin is current")
    else:
        verb = "stale" if check else "regenerated"
        lines.append(f"{verb}: " + ", ".join(sorted(stale)))
        if not check:
            lines.append("review the diff above and commit these in their own commit (rule 10)")
    lines.extend(f"warning: {w}" for w in drift(root))
    code = EXIT_STALE if check and stale else EXIT_OK
    return Outcome(code, "\n".join(lines) + "\n")


def _assert_running_this_tree(root: Path) -> None:
    """Rendering imports ``amicus``; refuse if that is not this checkout's source, or if
    the imported FINGERPRINT disagrees with the file on disk."""
    fp = fingerprint_module
    expected = (root / FINGERPRINT_SOURCE).resolve()
    if Path(fp.__file__).resolve() != expected:
        raise Refusal(
            f"`amicus` imports from {fp.__file__}, not {expected}; run this with `uv run` "
            "from the checkout whose pins you are regenerating"
        )
    literal = fingerprint_literal(expected.read_text(encoding="utf-8"), FINGERPRINT_SOURCE)
    if literal != fp.FINGERPRINT:
        raise Refusal(f"imported FINGERPRINT {fp.FINGERPRINT!r} != {literal!r} on disk")


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - thin CLI
    parser = argparse.ArgumentParser(
        description="Regenerate every pin a FINGERPRINT bump moves (AGENTS.md rule 10)."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="write nothing; exit 1 if any pin is stale (no FINGERPRINT advance required)",
    )
    parser.add_argument(
        "--base",
        default=DEFAULT_BASE,
        help=f"FINGERPRINT must advance past its merge-base with HEAD (default {DEFAULT_BASE})",
    )
    args = parser.parse_args(argv)
    try:
        _assert_running_this_tree(REPO)
        outcome = run(REPO, check=args.check, base_ref=args.base)
    except Refusal as exc:
        sys.stderr.write(f"refused, nothing written: {exc}\n")
        return EXIT_REFUSED
    sys.stdout.write(outcome.report)
    return outcome.code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
