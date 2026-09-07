"""Shared helpers for the kimi plugin tests: pinned flag support, a backend built from an
explicit environ (binary pinned to /KIMI, catalog optionally pinned), argv normalization
against the sibling capture, and a scripted runtime that honours the handshake pointer."""

from __future__ import annotations

import json
import re
from pathlib import Path

from pontonier.conventions.preflight import FlagSupport, HelpProbe
from pontonier.core.runtime import CommandRun

from amicus.backends import kimi as kimi_pkg
from amicus.backends.kimi import contract
from amicus.backends.kimi.adapter import KimiBackend
from amicus.plugin import ModelEntry, ModelListing

ALL_FLAGS = FlagSupport(
    supported=frozenset(set(contract.ALWAYS_SEND_FLAGS) | set(contract.HELP_GATED_FLAGS)),
    help_parsed=True,
)
NO_MODEL = FlagSupport(supported=frozenset(contract.ALWAYS_SEND_FLAGS), help_parsed=True)
K3 = ModelListing(
    models=(
        ModelEntry(
            slug="k3",
            display_name="Kimi K3",
            default_reasoning_effort="medium",
            supported_reasoning_efforts=("low", "medium", "high"),
        ),
        ModelEntry(slug="bare"),
    ),
    source="live",
)
SILENT = ModelListing(models=(), source="none")


def load_fixture() -> dict:
    return json.loads(
        (Path(__file__).parent.parent / "fixtures" / "kimi_differentials.json").read_text()
    )


def make_backend(
    environ: dict | None = None,
    flags: FlagSupport = ALL_FLAGS,
    catalog: ModelListing | None = SILENT,
):
    """(plugin, backend) with the help probe pinned, the binary pinned to /KIMI and the
    model catalog pinned (default: silent). `catalog=None` leaves the live reader alone."""
    env = {"AMICUS_KIMI_BIN": "/KIMI", **(environ or {})}
    plugin = kimi_pkg.plugin(env)
    probe: HelpProbe = plugin.help_probe
    probe.flag_support = lambda force=False: flags  # type: ignore[method-assign]
    if catalog is not None:
        plugin.models.read = lambda force=False: catalog  # type: ignore[method-assign]
    backend = plugin.backend
    assert isinstance(backend, KimiBackend)
    return plugin, backend


_HANDSHAKE = re.compile(r"/[^\s]*amicus-kimi-handshake-[^/\s]+/")
_SKILLS = re.compile(r"/[^\s]*/empty-skills")


def normalize_argv(argv) -> list[str]:
    """The sibling's shape: `kimi` as argv[0], temp paths as /TMP/, the agent name theirs."""
    out = []
    for i, tok in enumerate(argv):
        normalized = _SKILLS.sub("/TMP/empty-skills", _HANDSHAKE.sub("/TMP/", tok))
        out.append("kimi" if i == 0 else normalized)
    return out


_ANSWER_POINTER = re.compile(r"write your final answer to (\S+?)\.?$")


def scripted_run_async(
    *,
    stdout: str = "",
    stderr: str = "",
    exit_code: int = 0,
    timed_out: bool = False,
    answer_file: str | None = None,
    calls: list | None = None,
    write_in_cwd: dict[str, str] | None = None,
):
    """A `runtime.run_async` stand-in for kimi: records the call, substitutes `{WT}` in
    stdout/stderr with the run's cwd (the worktree path), writes the answer file the
    pointer names when `answer_file` is given, writes files into cwd (delegate), and
    returns the scripted CommandRun."""

    async def fake(
        cmd,
        cwd,
        timeout_seconds,
        stdin_text=None,
        *,
        env=None,
        on_stdout_line=None,
        max_output_bytes=0,
        orphan_marker=None,
    ):
        pointer = cmd[cmd.index("--prompt") + 1] if "--prompt" in cmd else ""
        if calls is not None:
            calls.append(
                {
                    "cmd": list(cmd),
                    "cwd": cwd,
                    "stdin_text": stdin_text,
                    "env": env,
                    "timeout": timeout_seconds,
                    "orphan_marker": orphan_marker,
                    "pointer": pointer,
                }
            )
        m = _ANSWER_POINTER.search(pointer)
        if answer_file is not None and m is not None:
            Path(m.group(1)).write_text(answer_file, encoding="utf-8")
        for name, content in (write_in_cwd or {}).items():
            Path(cwd, name).write_text(content, encoding="utf-8")
        out = stdout.replace("{WT}", cwd)
        err = stderr.replace("{WT}", cwd)
        if on_stdout_line is not None:
            for line in out.splitlines():
                on_stdout_line(line)
        return CommandRun(out, err, exit_code, 12, timed_out)

    return fake
