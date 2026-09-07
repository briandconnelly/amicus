"""Shared helpers for the claude plugin tests: pinned flag support, a backend built from an
explicit environ (binary pinned to /CLAUDE), envelope builders, argv normalization against the
sibling capture, and a scripted runtime that records what it was asked to spawn."""

from __future__ import annotations

import json
from pathlib import Path

from pontonier.conventions.preflight import FlagSupport, HelpProbe
from pontonier.core.runtime import CommandRun

from amicus.backends import claude as claude_pkg
from amicus.backends.claude import contract
from amicus.backends.claude.adapter import ClaudeBackend

ALL_FLAGS = FlagSupport(
    supported=frozenset(set(contract.ALWAYS_SEND_FLAGS) | set(contract.HELP_GATED_FLAGS)),
    help_parsed=True,
)
NO_MODEL = FlagSupport(
    supported=frozenset(set(contract.ALWAYS_SEND_FLAGS) | {"--effort", "--disallowed-tools"}),
    help_parsed=True,
)
_FIXTURES = Path(__file__).parent.parent / "fixtures"
GOLDEN = (_FIXTURES / "claude_golden_envelope.json").read_text()
STRUCTURED = json.dumps(
    {
        "summary": "Looks fine",
        "verdict": "pass",
        "confidence": "high",
        "findings": [],
        "questions": [],
        "assumptions": [],
        "next_steps": [],
    }
)


def load_fixture() -> dict:
    return json.loads((_FIXTURES / "claude_differentials.json").read_text())


def envelope(
    result: str = STRUCTURED, *, subtype: str | None = "success", is_error: bool = False, **extra
) -> str:
    """A `claude -p --output-format json` envelope as the CLI prints it."""
    body: dict = {"type": "result", "is_error": is_error, "result": result, "session_id": "sess-1"}
    if subtype is not None:
        body["subtype"] = subtype
    body.update(extra)
    return json.dumps(body)


def make_backend(environ: dict | None = None, flags: FlagSupport = ALL_FLAGS):
    """(plugin, backend) with the help probe pinned and the binary pinned to /CLAUDE."""
    env = {"AMICUS_CLAUDE_BIN": "/CLAUDE", **(environ or {})}
    plugin = claude_pkg.plugin(env)
    probe: HelpProbe = plugin.help_probe
    probe.flag_support = lambda force=False: flags  # type: ignore[method-assign]
    backend = plugin.backend
    assert isinstance(backend, ClaudeBackend)
    return plugin, backend


SYSTEM_PROMPT_MASK = "<SYSTEM_PROMPT>"


def normalize_argv(argv) -> list[str]:
    """The sibling's shape: `claude` as argv[0] and the --append-system-prompt VALUE masked
    (amicus carries host-neutral guardrails, the sibling carried Codex-named ones)."""
    out: list[str] = []
    mask_next = False
    for i, tok in enumerate(argv):
        if i == 0:
            out.append("claude")
            continue
        if mask_next:
            out.append(SYSTEM_PROMPT_MASK)
            mask_next = False
            continue
        out.append(tok)
        mask_next = tok == contract.APPEND_SYSTEM_PROMPT_FLAG
    return out


def scripted_run_async(
    *,
    stdout: str = "",
    stderr: str = "",
    exit_code: int = 0,
    timed_out: bool = False,
    calls: list | None = None,
):
    """A `runtime.run_async` stand-in for claude: records the call (argv, cwd, stdin, env)
    and returns the scripted CommandRun."""

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
                    "orphan_marker": orphan_marker,
                }
            )
        if on_stdout_line is not None:
            for line in stdout.splitlines():
                on_stdout_line(line)
        return CommandRun(stdout, stderr, exit_code, 12, timed_out)

    return fake
