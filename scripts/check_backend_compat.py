#!/usr/bin/env python
"""Check each backend CLI against what amicus was built for, without spending anything.

A release vouches for the `codex`, `kimi` and `claude` that were installed when its rule-20
evidence was recorded, and those CLIs release far more often than amicus does. This is the
mechanical half of the precondition in docs/RELEASING.md ("The backend CLIs are current and
checked"): for every in-tree backend it reports

    * whether the CLI is installed, its version, and the warnings `amicus_backends` would
      raise (an unsupported version, a flag amicus always sends that `--help` no longer
      lists, an invalid setting);
    * which long flags the live `--help` declares that the newest capture committed under
      `docs/<backend>-help/<version>/` does not, and the reverse. Flags, not text: claude
      wraps its help to the terminal width and a capture may have been trimmed, so a text
      diff reports a change on every run. `--diff` prints the text diff for a reader;
    * the latest upstream release, from `npm view` for all three. A lookup that fails is
      reported as unknown, never guessed, and fails the check unless `--offline` was given.

It runs `--version`, `--help` and each backend's free login probe, and nothing else: no
prompt is sent, so no quota is spent. It cannot do the other half of the precondition, the
rule-18 carrier re-check, because "no documented or observed way to avoid this carrier"
takes a reader; it prints the reminder instead.

Usage:
    uv run python scripts/check_backend_compat.py [--docs-root docs] [--write] [--offline]

    --write    save the live help as a new capture for any backend whose installed version
               has none, so the diff that prompted it is committed beside the support change
    --offline  do not ask npm for the latest release
    --diff     also print the text diff against the capture (noisy: see above)

Exit codes:
    0  every backend is installed, warning-free, and at the latest release that could be read
    1  at least one problem, each printed with the backend it belongs to
"""

from __future__ import annotations

import argparse
import difflib
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from amicus import backends as in_tree
from amicus.backends.claude import contract as claude_contract
from amicus.backends.codex import contract as codex_contract
from amicus.backends.kimi import contract as kimi_contract
from amicus.registry import BackendRegistry
from amicus.sdk.core import runtime

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Callable

BACKENDS: tuple[str, ...] = ("codex", "kimi", "claude")
# Where npm publishes each backend's CLI. Kimi Code updates itself through `kimi upgrade`,
# but it is published as an npm package too, which is what makes its latest readable.
NPM_PACKAGES: dict[str, str] = {
    "codex": "@openai/codex",
    "kimi": "@moonshot-ai/kimi-code",
    "claude": "@anthropic-ai/claude-code",
}
_SEMVER = re.compile(r"(\d+)\.(\d+)\.(\d+)")
# The same core with whatever semver prerelease or build suffix is attached to it. A product
# label (`2.1.278 (Claude Code)`) is set off by a space, so it is never part of the suffix.
_RELEASE = re.compile(r"(\d+\.\d+\.\d+)((?:-[0-9A-Za-z][0-9A-Za-z.-]*)?(?:\+[0-9A-Za-z.-]+)?)")
# An option ROW: a shallow indent, then the declaration column up to the gap before its
# description. codex indents rows by 2 or 6 and puts the description on the next line;
# kimi and claude indent by 2 and describe on the same line. Description text wraps at 10
# columns or deeper, and may itself begin with a flag, so the indent is what tells them apart.
_OPTION_ROW = re.compile(r"^ {1,8}(-\S.*?)(?: {2,}|$)", re.MULTILINE)
_LONG_FLAG = re.compile(r"(?<![\w-])--[A-Za-z][\w-]*")
CARRIER_REMINDER = (
    "Not checked here: AGENTS.md rule 18's carrier re-check. For each version above, confirm "
    "no documented or observed way to avoid that backend's native carriers has appeared "
    '(docs/RELEASING.md, "The backend CLIs are current and checked").'
)


@dataclass
class Report:
    backend: str
    installed: bool
    version: str | None = None
    authenticated: bool | None = None
    warnings: tuple[str, ...] = ()
    help_text: str = ""
    help_ok: bool = False  # the help command exited 0 and declared at least one option
    declared: frozenset[str] = frozenset()
    offline: bool = False
    builtin_supported: bool = False  # by the SHIPPED contract, whatever the environment says
    missing_flags: list[str] = field(default_factory=list)
    capture: Path | None = None
    capture_state: str = "none"  # none | identical | reworded | flags_differ
    flags_added: list[str] = field(default_factory=list)
    flags_removed: list[str] = field(default_factory=list)
    help_diff: list[str] = field(default_factory=list)
    latest: str | None = None


def semver(text: str | None) -> tuple[int, int, int] | None:
    match = _SEMVER.search(text or "")
    return (int(match[1]), int(match[2]), int(match[3])) if match else None


def release(text: str | None) -> tuple[str, str] | None:
    """(core, suffix): `0.155.1-beta.1` is ("0.155.1", "-beta.1"). Three integers cannot tell
    that build from the release it precedes, and the gate is about the published one (#208)."""
    match = _RELEASE.search(text or "")
    return (match[1], match[2]) if match else None


def builtin_supported(backend: str, version: str | None) -> bool:
    """Whether the contract amicus SHIPS names this version. `status.warnings` cannot say:
    it reads the effective configuration, so an ambient AMICUS_*_SUPPORTED_VERSIONS naming
    the installed version silences the warning (the hole #113 closed in the live gate). The
    contract modules are read at call time, not bound at import, so this sees what ships."""
    parsed = semver(version)
    if parsed is None:
        return False
    if backend == "claude":
        return parsed[0] in claude_contract.SUPPORTED_MAJORS
    shipped = {"codex": codex_contract, "kimi": kimi_contract}[backend].SUPPORTED_VERSIONS
    return parsed[:2] in shipped


def declared_flags(help_text: str) -> frozenset[str]:
    """The long flags `--help` DECLARES, from its option rows alone. The SDK's
    `parse_supported` takes every `--flag` token in the text, which suits a help-gated flag,
    where a stray match sends something harmless. Here it would hide a removal: claude's
    help names `--mcp-config` inside two other options' descriptions."""
    return frozenset(
        flag for row in _OPTION_ROW.findall(help_text) for flag in _LONG_FLAG.findall(row)
    )


def latest_upstream(backend: str) -> str | None:
    """The newest published release, or None when it cannot be read. Never a guess."""
    package = NPM_PACKAGES.get(backend)
    if package is None:
        return None
    try:
        done = subprocess.run(
            ["npm", "view", package, "version"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    found = semver(done.stdout)
    return ".".join(map(str, found)) if done.returncode == 0 and found else None


def newest_capture(docs_root: Path, backend: str) -> Path | None:
    """The committed capture with the highest VERSION, which is not the last by name."""
    root = docs_root / f"{backend}-help"
    if not root.is_dir():
        return None
    versioned = [(semver(p.name), p) for p in root.iterdir() if p.is_dir()]
    dated = [(v, p) for v, p in versioned if v and (p / f"{backend}-help.txt").is_file()]
    return max(dated)[1] if dated else None


def check_backend(
    backend: str,
    docs_root: Path,
    *,
    latest: Callable[[str], str | None] = latest_upstream,
    help_text: str | None = None,
    offline: bool = False,
) -> Report:
    """`help_text` stands in for the live probe, so a test can show a dropped flag."""
    plugin = BackendRegistry.load((backend,), in_tree=in_tree.IN_TREE, entry_points=()).get(backend)
    if plugin is None:
        return Report(backend, installed=False, warnings=("the backend plugin did not load",))
    status = plugin.status.probe()
    report = Report(
        backend,
        installed=status.installed,
        version="".join(release(status.version) or ()) or status.version,
        authenticated=status.authenticated,
        warnings=tuple(status.warnings),
        offline=offline,
    )
    if not status.installed:
        return report
    report.builtin_supported = builtin_supported(backend, report.version)
    probe_ok = True
    if help_text is None:
        run = runtime.run_sync_capture(list(plugin.help_probe.help_argv), timeout_seconds=15)
        probe_ok = not run.binary_missing and not run.timed_out and run.exit_code == 0
        help_text = run.stdout if probe_ok else ""
    report.help_text = help_text
    report.declared = declared_flags(help_text)
    # Fail closed: help that could not be read declares nothing, and "nothing is missing"
    # from nothing is how an unreadable probe used to pass.
    report.help_ok = probe_ok and bool(report.declared)
    if report.help_ok:
        always = plugin.help_probe.always_send_flags
        report.missing_flags = sorted(f for f in always if f not in report.declared)
    report.capture = newest_capture(docs_root, backend)
    if report.capture is not None:
        committed = (report.capture / f"{backend}-help.txt").read_text(encoding="utf-8")
        report.help_diff = list(
            difflib.unified_diff(
                committed.splitlines(),
                help_text.splitlines(),
                f"{report.capture.name} (committed)",
                f"{report.version} (installed)",
                lineterm="",
            )
        )
        before, after = declared_flags(committed), report.declared
        report.flags_added = sorted(after - before)
        report.flags_removed = sorted(before - after)
        if report.flags_added or report.flags_removed:
            report.capture_state = "flags_differ"
        elif committed.split() != help_text.split():
            report.capture_state = "reworded"  # the words changed; re-wrapping alone does not count
        else:
            report.capture_state = "identical"
    report.latest = latest(backend)
    return report


def check_all(
    docs_root: Path,
    *,
    latest: Callable[[str], str | None] = latest_upstream,
    offline: bool = False,
) -> list[Report]:
    return [
        check_backend(backend, docs_root, latest=latest, offline=offline) for backend in BACKENDS
    ]


def problems(report: Report) -> list[str]:
    if not report.installed:
        return [f"{report.backend}: not installed, so nothing about it was checked"]
    found = [f"{report.backend}: warning: {w}" for w in report.warnings]
    if not report.builtin_supported:
        found.append(
            f"{report.backend}: installed {report.version} is outside the built-in contract's "
            "supported versions, whatever AMICUS_*_SUPPORTED_* says in this environment; "
            "support it in its own PR first"
        )
    if report.authenticated is not True:
        found.append(
            f"{report.backend}: not authenticated ({report.authenticated}); the evidence run "
            "needs every backend logged in"
        )
    if not report.help_ok:
        found.append(
            f"{report.backend}: --help could not be read (it failed, timed out, or declared no "
            "option), so no flag was checked"
        )
    found += [
        f"{report.backend}: amicus always sends {flag}, which --help no longer lists"
        for flag in report.missing_flags
    ]
    if (release(report.version) or ("", ""))[1]:
        found.append(
            f"{report.backend}: installed {report.version} is a prerelease or development "
            "build, not a published stable release; install the release before recording "
            "release evidence"
        )
    elif report.latest and release(report.version) != release(report.latest):
        found.append(
            f"{report.backend}: installed {report.version} is not the latest release "
            f"({report.latest}); upgrade before recording release evidence"
        )
    elif report.latest is None and report.backend in NPM_PACKAGES and not report.offline:
        # Every backend is on npm, so an unreadable latest is a lookup that failed, and a
        # lookup that failed must not look like a version that matched.
        found.append(
            f"{report.backend}: the latest release could not be read from npm, so whether "
            f"{report.version} is current is unknown; rerun online, or pass --offline to say "
            "the check was skipped"
        )
    return found


def write_capture(report: Report, docs_root: Path) -> Path:
    folder = docs_root / f"{report.backend}-help" / str(report.version)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{report.backend}-help.txt").write_text(report.help_text, encoding="utf-8")
    (folder / f"{report.backend}-version.txt").write_text(f"{report.version}\n", encoding="utf-8")
    return folder


def _describe(report: Report, *, show_diff: bool = False) -> list[str]:
    if not report.installed:
        return [f"{report.backend}: NOT INSTALLED"]
    latest = report.latest or (
        "not looked up (--offline)" if report.offline else "unknown (not readable from here)"
    )
    lines = [
        f"{report.backend}: installed {report.version}, latest {latest}, "
        f"authenticated={report.authenticated}"
    ]
    name = report.capture.name if report.capture else None
    if report.capture_state == "none":
        lines.append("    no committed help capture to compare against")
    elif report.capture_state == "identical":
        lines.append(f"    same flags and words as the {name} capture")
    elif report.capture_state == "reworded":
        lines.append(f"    same flags as the {name} capture; its wording changed (--diff shows it)")
    else:
        lines.append(f"    FLAGS DIFFER from the {name} capture:")
        lines += [f"      + {flag}" for flag in report.flags_added]
        lines += [f"      - {flag}" for flag in report.flags_removed]
    if show_diff:
        lines += [f"    {line}" for line in report.help_diff]
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--docs-root", type=Path, default=Path("docs"))
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--diff", action="store_true")
    args = parser.parse_args(argv)
    latest = (lambda _backend: None) if args.offline else latest_upstream
    reports = check_all(args.docs_root, latest=latest, offline=args.offline)
    found: list[str] = []
    for report in reports:
        print("\n".join(_describe(report, show_diff=args.diff)))
        found += problems(report)
        has_own = report.capture is not None and report.capture.name == report.version
        stable = not (release(report.version) or ("", "x"))[1]
        if args.write and report.installed and report.help_text and not has_own and stable:
            print(f"    wrote {write_capture(report, args.docs_root)}")
    print()
    for problem in found:
        print(f"FAIL {problem}")
    print(CARRIER_REMINDER)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
