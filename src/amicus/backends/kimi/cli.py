"""Build the `kimi -p` invocation, stage the handshake files, run the free probes, and
classify a failed run into a pontonier ClassifiedFailure (ported from moonbridge `kimi.py`).

Two guarantees live here:

* Read-only runs really are read-only: a read-only run is given an --agent-file whose
  `tools:` list omits Bash and Write. That file is generated per run and is the ONLY thing
  standing between a consult and an unrestricted agent (the worktree is not a boundary),
  so `build_exec_command` refuses to build a read-only command without it.
* Gathered context never rides argv: the prompt is written to a handshake file OUTSIDE the
  workspace and argv carries a short pointer, because kimi ignores stdin and crashes past
  ~950k argv chars.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from pontonier.backend.protocol import ClassifiedFailure, RepairHint
from pontonier.conventions import preflight
from pontonier.core import redaction, runtime

from amicus.backends.kimi import contract, normalize

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Callable

    from pontonier.conventions.preflight import FlagSupport
    from pontonier.core.runtime import CommandRun


def read_only_agent_document() -> str:
    """The generated agent profile that makes a run read-only. Its `tools:` list is
    guarantee-bearing (contract.READ_ONLY_AGENT_TOOLS): Bash and Write are absent."""
    tools = "\n".join(f"  - {t}" for t in contract.READ_ONLY_AGENT_TOOLS)
    return (
        "---\n"
        f"name: {contract.READ_ONLY_AGENT_NAME}\n"
        "description: Read-only consultant with no shell or write tools.\n"
        "tools:\n"
        f"{tools}\n"
        "---\n"
        "You are a read-only consultant. Answer using only the tools you have. "
        "You cannot modify files, and you must not ask for permission to do so.\n"
    )


def schema_instruction(output_schema: dict) -> str:
    """The prompt-appended structured-output instruction (kimi has no --output-schema)."""
    return (
        "\n\n# Required output format\n"
        "Reply with a single JSON object and nothing else — no prose, no code fence. "
        "It must validate against this JSON Schema:\n\n"
        f"{json.dumps(output_schema, indent=2)}\n"
    )


def _gate_optional(tokens: list[str], fs: FlagSupport) -> tuple[list[str], list[str]]:
    kept: list[str] = []
    dropped: list[str] = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        takes_value = contract.HELP_GATED_FLAGS.get(token)
        if takes_value is not None and not preflight.is_supported(token, fs):
            dropped.append(token)
            i += 2 if takes_value else 1
            continue
        kept.append(token)
        i += 1
    return kept, dropped


def build_exec_command(
    *,
    kimi_bin: str,
    read_only: bool,
    prompt_pointer: str,
    model: str | None = None,
    agent_file_path: str | None = None,
    skills_dir: str | None = None,
    flag_support: FlagSupport,
) -> tuple[list[str], list[str]]:
    """The `kimi -p` invocation. Returns (argv, dropped_help_gated_flags). cwd is not a kimi
    flag; the runner sets it on the subprocess. --add-dir and the prompt-mode-incompatible
    flags are never sent."""
    if read_only and not agent_file_path:
        raise ValueError(
            "read-only runs require an agent file: the tools allowlist is the only thing "
            "enforcing read-only, and a worktree does not contain kimi"
        )
    if len(prompt_pointer) > contract.MAX_ARGV_PROMPT_CHARS:
        raise ValueError(
            f"argv prompt exceeds {contract.MAX_ARGV_PROMPT_CHARS} chars; "
            "write it to the handshake prompt file instead"
        )
    tokens = [kimi_bin, *contract.EXEC_SUBCOMMAND, contract.PROMPT_FLAG, prompt_pointer]
    tokens += [contract.OUTPUT_FORMAT_FLAG, contract.OUTPUT_FORMAT_JSON]
    if agent_file_path:
        tokens += [contract.AGENT_FILE_FLAG, agent_file_path]
    if skills_dir:
        tokens += [contract.SKILLS_DIR_FLAG, skills_dir]
    if model:
        tokens += [contract.MODEL_FLAG, model]
    return _gate_optional(tokens, flag_support)


def build_run_env(base: dict[str, str], reasoning_effort: str | None) -> dict[str, str]:
    """Child environment: effort rides an env var (no flag), and the output format is
    pinned so a user's KIMI_MODEL_OUTPUT_FORMAT=text cannot strip the event stream."""
    env = dict(base)
    if reasoning_effort is not None:
        env[contract.REASONING_EFFORT_ENV] = reasoning_effort
    env[contract.MODEL_OUTPUT_FORMAT_ENV] = contract.OUTPUT_FORMAT_JSON
    return env


def _write_exclusive(path: Path, text: str) -> None:
    """Create and write, refusing to follow a symlink or reuse an existing file: the dir is
    created fresh by this process, so anything already at the target is a plant."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)


def create_handshake_dir() -> str:
    """A fresh, private, server-owned directory for one run's handshake files, deliberately
    NOT inside the worktree (a repo tracking a symlink at the handshake path would redirect
    the writes). kimi reads the files by absolute path."""
    return tempfile.mkdtemp(prefix=contract.HANDSHAKE_DIR_PREFIX)


def write_handshake(run_dir: str, prompt_text: str, *, read_only: bool) -> dict[str, str]:
    """Write one run's handshake files and return their ABSOLUTE paths: `prompt` always,
    `agent` for a read-only run, `answer` (not yet existing) for a write-capable run."""
    base = Path(run_dir)
    base.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}
    prompt_path = base / contract.PROMPT_FILE_NAME
    _write_exclusive(prompt_path, prompt_text)
    paths["prompt"] = str(prompt_path)
    if read_only:
        agent_path = base / contract.AGENT_FILE_NAME
        _write_exclusive(agent_path, read_only_agent_document())
        # The agent file is the ONLY thing enforcing read-only: confirm its bytes.
        if agent_path.read_text(encoding="utf-8") != read_only_agent_document():
            raise ValueError("read-only agent file did not read back as written")
        paths["agent"] = str(agent_path)
    else:
        paths["answer"] = str(base / contract.ANSWER_FILE_NAME)
    return paths


def build_prompt_pointer(paths: dict[str, str], *, read_only: bool) -> str:
    prompt = paths["prompt"]
    if read_only:
        return (
            f"Read the file {prompt} and follow it exactly. "
            "Reply with your answer as your final message."
        )
    return (
        f"Read the file {prompt} and follow it exactly. "
        f"When you are done, write your final answer to {paths['answer']}."
    )


# --- free probes ------------------------------------------------------------------------------


def kimi_version(binary: str, timeout_seconds: int = 10) -> str | None:
    run = runtime.run_sync_capture(
        [binary, *contract.VERSION_ARGS], timeout_seconds=timeout_seconds
    )
    if run.binary_missing or run.exit_code != 0:
        return None
    return run.stdout.strip() or None


def login_status(binary: str, timeout_seconds: int = 10) -> tuple[bool | None, str | None]:
    """kimi has no `login status`; readiness is "at least one provider is configured", read
    from `kimi provider list --json`. The detail derives from the COUNT only — never the
    payload, which carries base URLs and may carry an API key."""
    run = runtime.run_sync_capture(
        [binary, *contract.PROVIDER_LIST_ARGS], timeout_seconds=timeout_seconds
    )
    if run.binary_missing or run.timed_out:
        return None, None
    if run.exit_code != 0:
        return False, "Kimi reports no usable provider configuration; run `kimi login`."
    count = _provider_count(run.stdout)
    if count is None:
        return None, None
    if count == 0:
        return False, "Kimi has no configured provider; run `kimi login`."
    return True, f"Kimi reports {count} configured provider(s)."


def _provider_count(stdout: str) -> int | None:
    try:
        data = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        return None
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        for key in ("providers", "items", "data"):
            value = data.get(key)
            if isinstance(value, (list, dict)):
                return len(value)
    return None


_ECHO_MAX_CHARS = 200
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences."""
    return _ANSI_ESCAPE.sub("", text)


def version_display(version: str | None) -> str | None:
    """The bounded, sanitized DISPLAY copy of a version string; None when nothing survives."""
    if version is None:
        return None
    stripped = _strip_ansi(version)
    sanitized = redaction.sanitize_echo(stripped)
    return sanitized[:_ECHO_MAX_CHARS] or None


# --- classification --------------------------------------------------------------------------

_UNRESOLVED_DEFAULT_MODEL_DETAIL = (
    "Kimi could not resolve the `default_model` in its config.toml — the alias names no "
    '`[models."..."]` section. This is the CONFIGURED DEFAULT, not the `model` you passed, '
    "so overriding or omitting `model` will not help."
)


def classify_failure(
    run: CommandRun,
    *,
    last_message: str | None,
    events: str | None,
    reasoning_effort: str | None,
    sanitize: Callable[[str], str] | None,
) -> ClassifiedFailure:
    """Map a non-success run into the shared taxonomy. Order (pontonier's shared one):
    binary missing → timeout → drift → auth → rate limit → invalid model → nonzero_exit.
    There is no effort branch: kimi silently ignores an unrecognized effort, so a rejection
    never reaches here (the adapter refuses pre-spend). `sanitize` replaces the generic
    branch's sanitizer and runs BEFORE the 300-char cut, so a secret or worktree path that
    straddles the cut cannot leak a prefix."""
    if run.binary_missing:
        return ClassifiedFailure(
            code="kimi_not_found",
            detail="The `kimi` CLI was not found; run amicus_backends for the resolution detail.",
        )
    if run.timed_out:
        return ClassifiedFailure(code="timeout", detail="kimi exceeded the timeout.")
    _ = reasoning_effort
    event_error = normalize.extract_error_message(events) if events else None
    if contract.is_contract_drift(run.stderr, run.stdout, event_error):
        return ClassifiedFailure(
            code="cli_contract_changed",
            detail=(
                "kimi rejected a flag or value amicus sent — its CLI contract likely changed "
                "for your installed version."
            ),
        )
    if contract.is_auth_failure(run.stderr, run.stdout, last_message, event_error):
        return ClassifiedFailure(
            code="kimi_auth_required",
            detail="kimi is not authenticated: the configured provider rejected the credentials.",
        )
    if contract.is_rate_limited(run.stderr, run.stdout, last_message, event_error):
        retry_after = contract.parse_retry_after_ms(
            run.stderr, run.stdout, last_message, event_error
        )
        if retry_after is None:
            retry_after = contract.RATE_LIMIT_DEFAULT_BACKOFF_MS
        return ClassifiedFailure(
            code="kimi_rate_limited",
            detail="kimi hit a usage/rate limit.",
            retry_after_ms=retry_after,
        )
    if contract.is_invalid_model(run.stderr, run.stdout, last_message, event_error):
        if contract.is_unresolved_default_model(run.stderr, run.stdout, last_message, event_error):
            return ClassifiedFailure(
                code="invalid_model",
                detail=_UNRESOLVED_DEFAULT_MODEL_DETAIL,
                repair=RepairHint(
                    next_step="correct_config",
                    tool=None,
                    alternative=(
                        "Correct `default_model` in kimi's config.toml (or add the matching "
                        '`[models."..."]` section), then retry.'
                    ),
                ),
            )
        return ClassifiedFailure(
            code="invalid_model",
            detail=(
                "Kimi does not have that model alias configured. `model` takes an alias "
                "defined in kimi's config.toml, not a raw provider model id."
            ),
            details={"field": "model"},
            repair=RepairHint(
                next_step="correct_arguments",
                tool="amicus_models",
                alternative=(
                    "Pass one of the aliases amicus_models lists for kimi, or omit model to "
                    "use the configured default_model."
                ),
            ),
        )
    raw = (event_error or run.stderr or run.stdout).strip()
    stripped_ansi = _strip_ansi(raw)
    sanitized = (
        sanitize(stripped_ansi)
        if sanitize is not None
        else redaction.sanitize_echo_prose(stripped_ansi)
    )
    detail = sanitized[:300]
    return ClassifiedFailure(code="nonzero_exit", detail=f"kimi exited {run.exit_code}: {detail}")
