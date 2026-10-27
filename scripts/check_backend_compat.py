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
    * the latest upstream release, npm's `latest` dist-tag for all three, and whether the
      installed CLI is behind it or ahead of it. A lookup that fails is reported as unknown,
      never guessed, and fails the check unless `--offline` was given.

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

Subcommands (a first argument naming one selects it; anything else is the check above):

    compare --backend codex --old-bin PATH --new-bin PATH [--docs-root docs] [--write]
            [--debug-models]

Collects the evidence docs/UPGRADING-CODEX.md step 2 compares, from two binaries driven by
absolute path, and runs step 3's zero-spend probe matrix on both (#376). Every run of
either binary happens in a fresh scratch HOME and CODEX_HOME with no credentials, under an
environment that carries PATH and nothing else from the caller's (so no OPENAI_API_KEY,
CODEX_API_KEY or CODEX_ACCESS_TOKEN). Before each `exec` probe, `login status` in that same
scratch home must report logged out, or the probe is not run. So the furthest any probe
can get is codex's unauthenticated 401: no turn can be billed. The only prompt is a
literal of this script, sent over stdin. See `codex_probes` for the matrix.

The old binary is authenticated first: its `exec --help` must match the capture committed
for its exact version under the whitespace policy in `hygiene` (the trailing-whitespace
and end-of-file hooks rewrite a capture as it is committed). A mismatch stops everything;
a missing capture is a failure but the comparison still runs. `codex debug models` needs
an account, so it is listed as not run unless `--debug-models` asks for it, and then it
runs under the caller's own environment and login and shows today's catalog for that
account, which is not a replay of the catalog any earlier comparison recorded. `--write`
saves the new binary's `exec --help` as docs/codex-help/<new-version>/ when that folder
does not exist yet.

The report has three sections, CHECKED, DIFFERED and NOT RUN, then a FAIL line per problem.
A difference is evidence to review, not by itself a failure.

    0  the old binary matched its capture, every surface was read, and every probe ended
       the way it must on both binaries
    1  at least one FAIL: a missing baseline, an unreadable surface, or a probe that did
       not end the way it must
    2  stopped before comparing: the old binary does not match its capture, or a
       binary's version or `exec --help` could not be read (argparse's usage errors too)
"""

from __future__ import annotations

import argparse
import concurrent.futures
import contextlib
import difflib
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from amicus import backends as in_tree
from amicus.backends.claude import contract as claude_contract
from amicus.backends.codex import cli as codex_cli
from amicus.backends.codex import contract as codex_contract
from amicus.backends.kimi import contract as kimi_contract
from amicus.registry import BackendRegistry
from amicus.sdk.conventions.preflight import FlagSupport
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
# The dist-tag read as "the latest release". npm also publishes builds under other tags
# (claude's `next`), and a CLI that self-updates can land on one of those, ahead of this (#323).
NPM_DIST_TAG = "latest"
# How to install one exact release, where that is known. Claude Code's native installer pins
# with `claude install`; an npm upgrade does not move the native install. Kimi Code updates
# itself through `kimi upgrade`, which takes no version, so it gets prose, not a command.
PIN_COMMANDS: dict[str, str] = {
    "codex": "npm install -g @openai/codex@{version}",
    "claude": "claude install {version}",
}
_SEMVER = re.compile(r"(\d+)\.(\d+)\.(\d+)")
# The same core with whatever semver prerelease or build suffix is attached to it. A product
# label (`2.1.278 (Claude Code)`) is set off by a space, so it is never part of the suffix.
_RELEASE = re.compile(r"(\d+\.\d+\.\d+)((?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?)")
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
    """The release npm's `latest` dist-tag names, or None when it cannot be read. Never a
    guess. Not necessarily the newest published build: another tag such as `next` can be
    ahead of it, and `latest` is the one a release vouches for (#323)."""
    package = NPM_PACKAGES.get(backend)
    if package is None:
        return None
    try:
        done = subprocess.run(
            ["npm", "view", f"{package}@{NPM_DIST_TAG}", "version"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    found = release(done.stdout)
    return "".join(found) if done.returncode == 0 and found else None


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
        found.append(not_latest(report))
    elif report.latest is None and report.backend in NPM_PACKAGES and not report.offline:
        # Every backend is on npm, so an unreadable latest is a lookup that failed, and a
        # lookup that failed must not look like a version that matched.
        found.append(
            f"{report.backend}: the latest release could not be read from npm, so whether "
            f"{report.version} is current is unknown; rerun online, or pass --offline to say "
            "the check was skipped"
        )
    return found


def not_latest(report: Report) -> str:
    """Which way the installed CLI is off npm's latest, since the fix is opposite (#323):
    behind, upgrade; ahead, the build came from another dist-tag, so pin back or wait."""
    installed, latest = semver(report.version), semver(report.latest)
    head = f"{report.backend}: installed {report.version}"
    tag = f"npm's `{NPM_DIST_TAG}` dist-tag ({report.latest})"
    command = PIN_COMMANDS.get(report.backend)
    install = (
        f"`{command.format(version=report.latest)}`"
        if command
        else f"installing {report.latest} however this CLI was installed"
    )
    if installed is not None and latest is not None and installed > latest:
        return (
            f"{head} is ahead of {tag}, so it is not the latest release (a build from another "
            f"dist-tag, such as `next`); pin back with {install}, or wait for `{NPM_DIST_TAG}` "
            "to advance, then rerun before recording release evidence"
        )
    if installed is not None and latest is not None and installed < latest:
        return f"{head} is behind {tag}; upgrade with {install} before recording release evidence"
    return (
        f"{head} does not match {tag}; install the release `{NPM_DIST_TAG}` names before "
        "recording release evidence"
    )


def write_capture(report: Report, docs_root: Path) -> Path:
    return write_help_capture(docs_root, report.backend, str(report.version), report.help_text)


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


# --- compare: two binaries of one backend, side by side (#376) ------------------------------

COMPARE_TIMEOUT_SECONDS = 120
# The only prompt a probe carries: a literal of this script, over stdin (AGENTS.md rule 18).
# No probe gets far enough to show it to a model, because no credential is reachable.
SYNTHETIC_PROMPT = "Reply with the single word OK.\n"
SYNTHETIC_INSTRUCTIONS = "Answer in one word."
# Names no codex release uses, so each rejection is the one the probe is looking for.
PROBE_OVERRIDE_KEY = "amicus_probe_unknown_override_key"
PROBE_FILE_KEY = "amicus_probe_unknown_file_key"
PROBE_UNKNOWN_FLAG = "--amicus-probe-unknown-flag"
PROBE_UNKNOWN_FEATURE = "amicus_probe_unknown_feature"
PROBE_BAD_SANDBOX = "amicus-probe-sandbox"
# docs/UPGRADING-CODEX.md step 3's examples of an invalid value and of a retired setting.
INVALID_VALUE_KEY, INVALID_VALUE = "sandbox_mode", '"yolo"'
RETIRED_SETTING_KEY, RETIRED_SETTING = "approval_policy", '"untrusted"'
# Every surface docs/UPGRADING-CODEX.md step 2 compares, as (name, argv after the binary).
CODEX_SURFACES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("--help", ("--help",)),
    ("exec --help", codex_contract.EXEC_HELP_ARGS),
    ("exec review --help", ("exec", "review", "--help")),
    ("login --help", ("login", "--help")),
    ("features list", ("features", "list")),
)
# How a probe run ended. Only UNAUTHENTICATED means codex got past config loading, and it
# is as far as any run can get with no credential.
CONFIG_REJECTED = "rejected its configuration"
ARGS_REJECTED = "rejected its arguments"
UNAUTHENTICATED = "got past config loading to the unauthenticated failure"
# What codex-cli 0.163.0 and 0.164.0 print, exit 1, when a request reaches the server with no
# credential at all: on stderr, or inside the JSONL on stdout under `--json`. Only this counts
# as getting past config loading. amicus's own `is_auth_failure` is broader on purpose (it
# also matches a local `Not logged in` or a failed token refresh), and neither of those
# shows that the run got as far as a request.
MISSING_CREDENTIALS_401 = (
    "unexpected status 401 Unauthorized: Missing bearer or basic authentication in header"
)
# After SIGTERM to a timed-out or interrupted run's process group, how long to wait before
# SIGKILL.
KILL_GRACE_SECONDS = 2
CODEX_NOT_RUN = (
    "the model-facing tool catalog: this script has no instrument for it "
    "(docs/UPGRADING-CODEX.md step 2)",
    "logged-in `login status` forms: a scratch home has no login, and yours is never read",
    "step 3's checks that spend: the effort rejection and the network and writable-roots pins",
    "step 3's judgment checks: release notes, upstream source, flag meaning and carriers",
)
_FEATURE_ROW = re.compile(r"^(\S+) {2,}(\S.*?) {2,}(\S+)[ \t]*$", re.MULTILINE)
_COMMAND_ROW = re.compile(r"^  ([a-z][\w-]*)(?: {2,}|$)", re.MULTILINE)


def hygiene(text: str) -> str:
    """The whitespace policy for a committed capture: what the trailing-whitespace and
    end-of-file-fixer hooks leave of it. No line keeps trailing whitespace, and the text
    ends in exactly one newline (an empty text stays empty). codex's help pads blank lines
    with spaces, so a raw capture never matches the committed one byte for byte."""
    body = "\n".join(line.rstrip() for line in text.splitlines()).rstrip("\n")
    return body + "\n" if body else ""


@dataclass(frozen=True)
class Run:
    argv: tuple[str, ...]
    exit_code: int | None  # None: it did not start, or it timed out
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False


def _text(value: str | bytes | None) -> str:
    return value.decode(errors="replace") if isinstance(value, bytes) else value or ""


def _run(
    argv: list[str],
    *,
    env: dict[str, str] | None,
    cwd: Path,
    stdin_text: str = "",
    timeout: int = COMPARE_TIMEOUT_SECONDS,
) -> Run:
    """One run with stdin closed after `stdin_text`, so nothing can wait on a terminal.

    The run gets its own session, so its process group holds everything it starts. npm's
    `codex` is a Node entry point that spawns the native binary, and killing only the entry
    point would leave that child running while its scratch directories are deleted. On a
    timeout or an interrupt the whole group gets SIGTERM, then SIGKILL after a short grace,
    and is reaped before this returns or re-raises."""
    try:
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            env=env,
            cwd=cwd,
            start_new_session=True,
        )
    except OSError as exc:
        return Run(tuple(argv), None, "", f"could not start: {exc}")
    try:
        stdout, stderr = proc.communicate(stdin_text, timeout=timeout)
    except subprocess.TimeoutExpired:
        stdout, stderr = _kill_group(proc)
        return Run(tuple(argv), None, stdout, stderr, timed_out=True)
    except BaseException:
        _kill_group(proc)
        raise
    return Run(tuple(argv), proc.returncode, stdout, stderr)


def _signal_group(proc: subprocess.Popen[str], sig: int) -> None:
    # The group id is the leader's pid, which stays reserved until the leader is reaped.
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(proc.pid, sig)


def _kill_group(proc: subprocess.Popen[str]) -> tuple[str, str]:
    """SIGTERM the run's process group, SIGKILL it after the grace, and reap the leader."""
    _signal_group(proc, signal.SIGTERM)
    try:
        stdout, stderr = proc.communicate(timeout=KILL_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        _signal_group(proc, signal.SIGKILL)
        stdout, stderr = proc.communicate()
    _signal_group(proc, signal.SIGKILL)  # anything that outlived its leader
    return _text(stdout), _text(stderr)


class Scratch:
    """A throwaway HOME, CODEX_HOME, TMPDIR and working directory, and an environment that
    carries PATH and nothing else from the caller's: no API key, no access token, no
    CODEX_HOME of the caller's own. One per run, so no run sees another's state."""

    def __init__(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="amicus-compare-")
        self.raw = self._tmp.name
        self.root = Path(self.raw).resolve()
        self.home, self.codex_home = self.root / "home", self.root / "codex-home"
        self.work, self.tmp = self.root / "work", self.root / "tmp"
        for folder in (self.home, self.codex_home, self.work, self.tmp):
            folder.mkdir()
        self.env = {
            "PATH": os.environ.get("PATH", os.defpath),
            "HOME": str(self.home),
            "CODEX_HOME": str(self.codex_home),
            "TMPDIR": str(self.tmp),
        }

    def __enter__(self) -> Scratch:
        return self

    def __exit__(self, *_exc: object) -> None:
        shutil.rmtree(self.root, ignore_errors=True)
        self._tmp.cleanup()

    def scrub(self, text: str) -> str:
        """Text with this scratch directory's paths replaced, so two runs compare."""
        return text.replace(str(self.root), "<scratch>").replace(self.raw, "<scratch>")

    def run(self, argv: list[str], *, stdin_text: str = "") -> Run:
        return _run(argv, env=self.env, cwd=self.work, stdin_text=stdin_text)


# What `login status` prints in a CODEX_HOME with no credentials, observed on codex-cli
# 0.163.0 and 0.164.0: exactly this line on stderr, nothing on stdout, exit 1.
LOGGED_OUT_STDERR = "Not logged in"
LOGGED_OUT_EXIT = 1


def logged_out(run: Run) -> bool:
    """`login status` affirmatively said no login: the observed logged-out diagnostic and
    exit status, and nothing else. An argument error, a crash, a signal, a credential-store
    failure or any unfamiliar output proves nothing about the login, so it is inconclusive
    and no probe runs on it."""
    return (
        run.exit_code == LOGGED_OUT_EXIT
        and not run.timed_out
        and run.stdout.strip() == ""
        and run.stderr.strip() == LOGGED_OUT_STDERR
    )


def login_diagnostic(run: Run) -> str:
    """What an inconclusive `login status` did, for the report."""
    if run.timed_out:
        return "it timed out"
    shown = " | ".join(line for line in (run.stdout + run.stderr).strip().splitlines()[:3])
    return f"exit {run.exit_code}, output {shown[:300]!r}"


def ended(run: Run) -> str:
    """How a probe run ended, read from stderr the way amicus reads a failed run."""
    if run.timed_out:
        return "timed out"
    if run.exit_code is None:
        return "did not start"
    if run.exit_code == 0:
        return "exited 0"
    if codex_contract.STRICT_CONFIG_ERROR_PREFIX in run.stderr:
        return CONFIG_REJECTED
    if codex_contract.parse_unsupported_config_setting(run.stderr) is not None:
        return CONFIG_REJECTED
    if codex_contract.is_contract_drift(run.stderr):
        return ARGS_REJECTED
    if run.exit_code == 1 and MISSING_CREDENTIALS_401 in run.stdout + run.stderr:
        return UNAUTHENTICATED
    return f"exited {run.exit_code} some other way"


@dataclass(frozen=True)
class Probe:
    """One row of docs/UPGRADING-CODEX.md step 3's zero-spend matrix."""

    name: str
    must: str  # what the report says it must do
    ends: str  # how it must end
    args: Callable[[str, Scratch], list[str]]  # the whole argv, for one binary and home
    parses: Callable[[str], bool] | None = None  # a check its stderr must pass
    config_toml: str | None = None  # written to the scratch CODEX_HOME after the login guard
    # Compare the two binaries' stderr. Not for a run that reaches the 401, whose stderr
    # carries timestamps and request ids that differ on every run.
    same_text: bool = True


def _exec(*args: str) -> Callable[[str, Scratch], list[str]]:
    return lambda binary, _scratch: [
        binary,
        *codex_contract.EXEC_SUBCOMMAND,
        "--skip-git-repo-check",
        "--ephemeral",
        *args,
        codex_contract.STDIN_PROMPT,
    ]


_PINNED_RUN = {
    "sandbox": codex_contract.SANDBOX_WORKSPACE_WRITE,
    "reasoning_effort": "low",
    "developer_instructions": SYNTHETIC_INSTRUCTIONS,
}


def pinned_keys() -> frozenset[str]:
    """The `-c` keys the pins probe sends, which must be every plugin-owned key."""
    return codex_cli.plugin_config_keys_for(**_PINNED_RUN)


def _pinned_argv(binary: str, scratch: Scratch) -> list[str]:
    """The argv amicus itself builds for a workspace-write run with effort and instructions:
    all four pins, every disable, and `--strict-config`."""
    argv, _dropped = codex_cli.build_exec_command(
        codex_bin=binary,
        cwd=str(scratch.work),
        isolation="inherit",
        output_last_message_path=str(scratch.tmp / "last-message.txt"),
        skip_git_repo_check=True,
        flag_support=FlagSupport(supported=frozenset(), help_parsed=False),
        **_PINNED_RUN,
    )
    return argv


def _rejects(origin: str, key: str) -> Callable[[str], bool]:
    def check(stderr: str) -> bool:
        found = codex_contract.parse_strict_config_rejection(stderr)
        if found is None or found.origin != origin or found.key != key:
            return False
        phrase = codex_contract.STRICT_CONFIG_OVERRIDE_ORIGIN_PHRASE
        return origin != "override" or phrase in stderr

    return check


def _invalid_value(stderr: str) -> bool:
    found = codex_contract.parse_invalid_config_value(stderr)
    return found is not None and found.key == INVALID_VALUE_KEY


def _retired_setting(stderr: str) -> bool:
    found = codex_contract.parse_unsupported_config_setting(stderr)
    return found is not None and found.key == RETIRED_SETTING_KEY


def codex_probes() -> tuple[Probe, ...]:
    """docs/UPGRADING-CODEX.md step 3, "Zero-spend checks", one probe per case. Each run
    ends at a config or argument rejection before any request, or, for the two that must
    get past config loading, at codex's unauthenticated failure. `ended` names which."""
    bad_file = f"{PROBE_FILE_KEY} = 1\n"
    strict = codex_contract.STRICT_CONFIG_FLAG
    return (
        Probe(
            "pins and disables",
            "carry every plugin-owned -c pin and MODEL_RUN_DISABLED_FEATURES --disable under "
            "--strict-config past config loading",
            UNAUTHENTICATED,
            _pinned_argv,
            same_text=False,
        ),
        Probe(
            "strict-config override",
            "reject an unknown -c key in the grammar parse_strict_config_rejection reads, "
            "naming the override origin",
            CONFIG_REJECTED,
            _exec(strict, "-c", f"{PROBE_OVERRIDE_KEY}=1"),
            _rejects("override", PROBE_OVERRIDE_KEY),
        ),
        Probe(
            "strict-config file",
            "reject an unknown config.toml key in the grammar parse_strict_config_rejection reads",
            CONFIG_REJECTED,
            _exec(strict),
            _rejects("file", PROBE_FILE_KEY),
            config_toml=bad_file,
        ),
        Probe(
            "strict-config file, ignored",
            "get past config loading beside that same file under --strict-config "
            "--ignore-user-config (the positive control)",
            UNAUTHENTICATED,
            _exec(strict, "--ignore-user-config"),
            config_toml=bad_file,
            same_text=False,
        ),
        Probe(
            "invalid value",
            f"reject -c {INVALID_VALUE_KEY}={INVALID_VALUE} in the grammar "
            "parse_invalid_config_value reads",
            CONFIG_REJECTED,
            _exec(strict, "-c", f"{INVALID_VALUE_KEY}={INVALID_VALUE}"),
            _invalid_value,
        ),
        Probe(
            "retired setting",
            f"reject -c {RETIRED_SETTING_KEY}={RETIRED_SETTING} in the grammar "
            "parse_unsupported_config_setting reads",
            CONFIG_REJECTED,
            _exec(strict, "-c", f"{RETIRED_SETTING_KEY}={RETIRED_SETTING}"),
            _retired_setting,
        ),
        Probe(
            "unknown flag",
            "reject an unknown flag in a wording is_contract_drift matches",
            ARGS_REJECTED,
            _exec(PROBE_UNKNOWN_FLAG),
        ),
        Probe(
            "invalid --sandbox",
            "reject an invalid --sandbox value in a wording is_contract_drift matches",
            ARGS_REJECTED,
            _exec("--sandbox", PROBE_BAD_SANDBOX),
        ),
        Probe(
            "unknown --disable",
            "reject an unknown --disable name as `Unknown feature flag`, which "
            "is_contract_drift matches",
            ARGS_REJECTED,
            _exec(codex_contract.DISABLE_FEATURE_FLAG, PROBE_UNKNOWN_FEATURE),
            lambda stderr: "Unknown feature flag" in stderr,
        ),
    )


@dataclass(frozen=True)
class ProbeResult:
    ended: str
    met: bool
    text: str = ""  # stderr, scrubbed of scratch paths
    ran: bool = True  # False: the login guard refused it


def run_probe(probe: Probe, binary: str) -> ProbeResult:
    """Run one probe in its own scratch home, after confirming that home has no login."""
    with Scratch() as scratch:
        guard = scratch.run([binary, *codex_contract.LOGIN_STATUS_ARGS])
        if not logged_out(guard):
            return ProbeResult(
                "was not run: `login status` in its scratch home did not report logged out "
                f"({scratch.scrub(login_diagnostic(guard))})",
                met=False,
                ran=False,
            )
        if probe.config_toml is not None:
            (scratch.codex_home / "config.toml").write_text(probe.config_toml, encoding="utf-8")
        run = scratch.run(probe.args(binary, scratch), stdin_text=SYNTHETIC_PROMPT)
        how = ended(run)
        met = how == probe.ends and (probe.parses is None or probe.parses(run.stderr))
        if how == probe.ends and not met:
            how += ", but not in the wording the contract parses"
        return ProbeResult(how, met, scratch.scrub(run.stderr))


def read_version(binary: str) -> str | None:
    with Scratch() as scratch:
        run = scratch.run([binary, *codex_contract.VERSION_ARGS])
    found = release(run.stdout) if run.exit_code == 0 else None
    return "".join(found) if found else None


def collect_surfaces(binary: str) -> dict[str, Run]:
    with Scratch() as scratch:
        return {name: scratch.run([binary, *args]) for name, args in CODEX_SURFACES}


def surface_ok(run: Run) -> bool:
    return run.exit_code == 0 and bool(run.stdout.strip())


def feature_rows(text: str) -> dict[str, tuple[str, str]]:
    """`features list` as {name: (stage, default)}; a stage can hold a space."""
    return {m[1]: (m[2], m[3]) for m in _FEATURE_ROW.finditer(text)}


def commands(help_text: str) -> frozenset[str]:
    """The subcommand names in a help text's `Commands:` section."""
    section = re.search(r"^Commands:\n(.*?)(?:\n[ \t]*\n|\Z)", help_text, re.MULTILINE | re.DOTALL)
    return frozenset(_COMMAND_ROW.findall(section[1])) if section else frozenset()


def _diff(before: str, after: str, old: str, new: str) -> list[str]:
    return list(
        difflib.unified_diff(before.splitlines(), after.splitlines(), old, new, lineterm="")
    )


def surface_change(name: str, before: str, after: str, labels: tuple[str, str]) -> list[str]:
    """What changed in one surface: the parsed rows first, then the text diff."""
    lines = [f"{name}: differs"]
    if name.endswith("--help"):
        old_flags, new_flags = declared_flags(before), declared_flags(after)
        lines += [f"    + flag {flag}" for flag in sorted(new_flags - old_flags)]
        lines += [f"    - flag {flag}" for flag in sorted(old_flags - new_flags)]
        old_cmds, new_cmds = commands(before), commands(after)
        lines += [f"    + command {cmd}" for cmd in sorted(new_cmds - old_cmds)]
        lines += [f"    - command {cmd}" for cmd in sorted(old_cmds - new_cmds)]
    if name == "features list":
        old_rows, new_rows = feature_rows(before), feature_rows(after)
        for feature in sorted(old_rows.keys() | new_rows.keys()):
            was, now = old_rows.get(feature), new_rows.get(feature)
            if was is None and now is not None:
                lines.append(f"    + feature {feature}: {now[0]}, default {now[1]}")
            elif now is None and was is not None:
                lines.append(f"    - feature {feature} (was {was[0]}, default {was[1]})")
            elif was != now and was is not None and now is not None:
                lines.append(
                    f"    ~ feature {feature}: {was[0]}, default {was[1]} -> "
                    f"{now[0]}, default {now[1]}"
                )
    lines += [f"    {line}" for line in _diff(before, after, *labels)]
    return lines


@dataclass
class Comparison:
    backend: str
    old_bin: str
    new_bin: str
    old_version: str | None = None
    new_version: str | None = None
    checked: list[str] = field(default_factory=list)
    differed: list[list[str]] = field(default_factory=list)
    not_run: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    stopped: list[str] = field(default_factory=list)  # why it stopped, then any diff
    new_exec_help: str = ""


def _authenticate_baseline(c: Comparison, old_exec: str, docs_root: Path) -> None:
    """The old binary must be the build checked last time: its `exec --help` must match
    the capture committed for its exact version, under `hygiene`."""
    baseline = docs_root / "codex-help" / str(c.old_version) / "codex-help.txt"
    if not baseline.is_file():
        newest = newest_capture(docs_root, "codex")
        c.problems.append(
            f"baseline: no capture is committed for the old version {c.old_version} "
            f"({baseline} does not exist), so the old binary is not authenticated; compare "
            f"it with the newest capture ({newest.name if newest else 'none exists'}) by "
            "hand and say so in the PR"
        )
        c.not_run.append(f"baseline authentication: no capture is committed for {c.old_version}")
        return
    committed = baseline.read_text(encoding="utf-8")
    if hygiene(old_exec) != hygiene(committed):
        c.stopped = [
            f"the old binary's exec --help does not match {baseline}, even under the "
            "whitespace policy, so it may not be the build checked last time; reconcile "
            "that before comparing",
            *_diff(hygiene(committed), hygiene(old_exec), f"{baseline} (committed)", c.old_bin),
        ]
        return
    how = "byte for byte" if old_exec == committed else "after the whitespace policy"
    c.checked.append(f"baseline: the old binary's exec --help matches {baseline} ({how})")


def _compare_probes(c: Comparison) -> None:
    probes = codex_probes()
    missing = codex_contract.PLUGIN_OWNED_CONFIG_KEYS - pinned_keys()
    if missing:
        c.problems.append(
            f"the pins probe does not send every plugin-owned key: {', '.join(sorted(missing))}"
        )
    jobs = [(probe, side) for probe in probes for side in ("old", "new")]
    binary = {"old": c.old_bin, "new": c.new_bin}
    version = {"old": c.old_version, "new": c.new_version}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = {job: pool.submit(run_probe, job[0], binary[job[1]]) for job in jobs}
        login = {side: pool.submit(_login_status, binary[side]) for side in ("old", "new")}
        results = {job: future.result() for job, future in futures.items()}
        login_runs = {side: future.result() for side, future in login.items()}
    for probe in probes:
        old, new = results[probe, "old"], results[probe, "new"]
        for side, result in (("old", old), ("new", new)):
            if not result.met:
                c.problems.append(
                    f"probe {probe.name} on the {side} binary ({version[side]}): it must "
                    f"{probe.must}; it {result.ended}"
                    + (f"\n    stderr: {result.text.strip()[-600:]}" if result.text else "")
                )
        if old.met and new.met:
            same = "; their stderr is identical" if probe.same_text and old.text == new.text else ""
            c.checked.append(f"probe {probe.name}: both binaries {probe.must}{same}")
        if probe.same_text and old.ran and new.ran and old.text != new.text:
            c.differed.append(
                [
                    f"probe {probe.name}: stderr differs",
                    *(f"    {line}" for line in _diff(old.text, new.text, *_labels(c))),
                ]
            )
    for side, (run, _text) in login_runs.items():
        if not logged_out(run):
            c.problems.append(
                f"login status on the {side} binary did not report logged out in a scratch "
                f"home with no credentials ({login_diagnostic(run)})"
            )
    old_text, new_text = login_runs["old"][1], login_runs["new"][1]
    if old_text == new_text:
        c.checked.append("login status: logged-out output identical")
    else:
        c.differed.append(
            [
                "login status: logged-out output differs",
                *(f"    {line}" for line in _diff(old_text, new_text, *_labels(c))),
            ]
        )


def _login_status(binary: str) -> tuple[Run, str]:
    with Scratch() as scratch:
        run = scratch.run([binary, *codex_contract.LOGIN_STATUS_ARGS])
        return run, scratch.scrub(run.stdout + run.stderr)


def _labels(c: Comparison) -> tuple[str, str]:
    return f"{c.old_version} (old)", f"{c.new_version} (new)"


def _compare_models(c: Comparison) -> None:
    """`codex debug models` under the caller's own environment and login, by request only."""
    runs = {}
    with tempfile.TemporaryDirectory(prefix="amicus-compare-") as cwd:
        for side, binary in (("old", c.old_bin), ("new", c.new_bin)):
            runs[side] = _run([binary, "debug", "models"], env=None, cwd=Path(cwd))
    bad = [side for side, run in runs.items() if not surface_ok(run)]
    if bad:
        c.problems.append(f"debug models: could not be read from the {' or '.join(bad)} binary")
        return
    note = "under your login, as served today; not a replay of an earlier catalog"
    if runs["old"].stdout == runs["new"].stdout:
        c.checked.append(f"debug models: identical ({note})")
    else:
        c.differed.append(
            [
                f"debug models: differs ({note})",
                *(
                    f"    {line}"
                    for line in _diff(runs["old"].stdout, runs["new"].stdout, *_labels(c))
                ),
            ]
        )


def compare_codex(
    old_bin: str, new_bin: str, docs_root: Path, *, debug_models: bool = False
) -> Comparison:
    c = Comparison("codex", old_bin, new_bin)
    c.old_version, c.new_version = read_version(old_bin), read_version(new_bin)
    for side, binary, version in (("old", old_bin, c.old_version), ("new", new_bin, c.new_version)):
        if version is None:
            c.stopped = [f"the {side} binary ({binary}) printed no release for --version"]
            return c
    old = collect_surfaces(old_bin)
    if not surface_ok(old["exec --help"]):
        c.stopped = [
            "the old binary's exec --help could not be read, so it cannot be authenticated"
        ]
        return c
    _authenticate_baseline(c, old["exec --help"].stdout, docs_root)
    if c.stopped:
        return c
    new = collect_surfaces(new_bin)
    if not surface_ok(new["exec --help"]):
        c.stopped = ["the new binary's exec --help could not be read, so nothing was compared"]
        return c
    for name, _args in CODEX_SURFACES:
        unread = [side for side, got in (("old", old), ("new", new)) if not surface_ok(got[name])]
        if unread:
            c.problems.append(f"{name}: could not be read from the {' or '.join(unread)} binary")
            c.not_run.append(f"{name}: not compared, because it could not be read")
        elif hygiene(old[name].stdout) == hygiene(new[name].stdout):
            c.checked.append(f"{name}: identical")
        else:
            c.differed.append(
                surface_change(
                    name, hygiene(old[name].stdout), hygiene(new[name].stdout), _labels(c)
                )
            )
    c.new_exec_help = new["exec --help"].stdout
    own = docs_root / "codex-help" / str(c.new_version) / "codex-help.txt"
    if own.is_file():
        if hygiene(own.read_text(encoding="utf-8")) == hygiene(c.new_exec_help):
            c.checked.append(f"the new binary's exec --help matches {own}")
        else:
            c.problems.append(
                f"the new binary's exec --help does not match {own}, the capture already "
                "committed for its version"
            )
    _compare_probes(c)
    if debug_models:
        _compare_models(c)
    else:
        c.not_run.append(
            "`codex debug models`: it needs an account; --debug-models runs it under your own "
            "login, showing today's catalog for your account, never a replay of an earlier one"
        )
    c.not_run += CODEX_NOT_RUN
    return c


# Per-backend comparison collectors; `compare --backend` offers exactly these.
COLLECTORS: dict[str, Callable[..., Comparison]] = {"codex": compare_codex}


def describe_comparison(c: Comparison) -> list[str]:
    lines = [
        f"{c.backend}: old {c.old_version or 'unknown'} ({c.old_bin}), "
        f"new {c.new_version or 'unknown'} ({c.new_bin})"
    ]
    if c.stopped:
        return [*lines, f"STOPPED: {c.stopped[0]}", *(f"    {line}" for line in c.stopped[1:])]
    lines.append("CHECKED")
    lines += [f"  {item}" for item in c.checked]
    lines.append("DIFFERED" + ("" if c.differed else " (nothing)"))
    for item in c.differed:
        lines += [f"  {item[0]}", *(f"  {line}" for line in item[1:])]
    lines.append("NOT RUN")
    lines += [f"  {item}" for item in c.not_run]
    lines += [f"FAIL {problem}" for problem in c.problems]
    return lines


def write_help_capture(docs_root: Path, backend: str, version: str, help_text: str) -> Path:
    folder = docs_root / f"{backend}-help" / version
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{backend}-help.txt").write_text(help_text, encoding="utf-8")
    (folder / f"{backend}-version.txt").write_text(f"{version}\n", encoding="utf-8")
    return folder


def compare_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="check_backend_compat.py compare",
        description="Compare two binaries of one backend at zero spend (docs/UPGRADING-CODEX.md).",
    )
    parser.add_argument("--backend", required=True, choices=sorted(COLLECTORS))
    parser.add_argument("--old-bin", required=True, type=Path)
    parser.add_argument("--new-bin", required=True, type=Path)
    parser.add_argument("--docs-root", type=Path, default=Path("docs"))
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--debug-models", action="store_true")
    args = parser.parse_args(argv)
    c = COLLECTORS[args.backend](
        str(args.old_bin.absolute()),
        str(args.new_bin.absolute()),
        args.docs_root,
        debug_models=args.debug_models,
    )
    print("\n".join(describe_comparison(c)))
    if c.stopped:
        return 2
    stable = not (release(c.new_version) or ("", "x"))[1]
    has_own = (args.docs_root / f"{c.backend}-help" / str(c.new_version)).exists()
    if args.write and c.new_exec_help and stable and not has_own:
        folder = write_help_capture(
            args.docs_root, c.backend, str(c.new_version), hygiene(c.new_exec_help)
        )
        print(f"wrote {folder}")
    return 1 if c.problems else 0


SUBCOMMANDS: dict[str, Callable[[list[str]], int]] = {"compare": compare_main}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in SUBCOMMANDS:
        return SUBCOMMANDS[argv[0]](argv[1:])
    return check_main(argv)


def check_main(argv: list[str]) -> int:
    """The default invocation: every in-tree backend against its newest capture."""
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
