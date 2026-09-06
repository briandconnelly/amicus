"""Shared helpers for the codex plugin tests: the sibling fixture, pinned flag support, a
backend built from an explicit environ, and the temp-path normalizer."""

from __future__ import annotations

import json
import re
from pathlib import Path

from pontonier.conventions.preflight import FlagSupport, HelpProbe
from pontonier.core.runtime import CommandRun

from amicus.backends import codex as codex_pkg
from amicus.backends.codex import contract
from amicus.backends.codex.adapter import CodexBackend

FIXTURE = json.loads(
    (Path(__file__).parent.parent / "fixtures" / "codex_differentials.json").read_text()
)
ALL_FLAGS = FlagSupport(
    supported=frozenset(contract.ALWAYS_SEND_FLAGS | set(contract.HELP_GATED_FLAGS)),
    help_parsed=True,
)
NO_MODEL = FlagSupport(supported=frozenset(contract.ALWAYS_SEND_FLAGS), help_parsed=True)


def make_backend(environ: dict | None = None, flags: FlagSupport = ALL_FLAGS):
    """(plugin, backend) with the help probe pinned and the binary pinned to /CODEX."""
    env = {"AMICUS_CODEX_BIN": "/CODEX", **(environ or {})}
    plugin = codex_pkg.plugin(env)
    probe: HelpProbe = plugin.help_probe
    probe.flag_support = lambda force=False: flags  # type: ignore[method-assign]
    backend = plugin.backend
    assert isinstance(backend, CodexBackend)
    return plugin, backend


def normalize_argv(argv) -> list[str]:
    return [re.sub(r"/[^\s]*amicus-codex-[^/]+/", "/TMP/", tok) for tok in argv]


def scripted_run_async(
    *,
    stdout: str = "",
    stderr: str = "",
    exit_code: int = 0,
    last_message: str | None = None,
    timed_out: bool = False,
    capture_failed: bool = False,
    calls: list | None = None,
    write_in_cwd: dict[str, str] | None = None,
):
    """A `runtime.run_async` stand-in: records the call, writes the last-message artifact
    (and optionally files into cwd, for delegate), and returns the scripted CommandRun."""

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
        if calls is not None:
            calls.append(
                {
                    "cmd": list(cmd),
                    "cwd": cwd,
                    "stdin_text": stdin_text,
                    "env": env,
                    "timeout": timeout_seconds,
                }
            )
        if last_message is not None and "--output-last-message" in cmd:
            Path(cmd[cmd.index("--output-last-message") + 1]).write_text(
                last_message, encoding="utf-8"
            )
        for name, content in (write_in_cwd or {}).items():
            Path(cwd, name).write_text(content, encoding="utf-8")
        if on_stdout_line is not None:
            for line in stdout.splitlines():
                on_stdout_line(line)
        return CommandRun(stdout, stderr, exit_code, 12, timed_out, capture_failed=capture_failed)

    return fake
