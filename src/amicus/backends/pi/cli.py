"""Build the `pi -p --mode json` invocation and child environment, run the free probes, and
classify a failed run into an SDK ClassifiedFailure.

The prompt never rides argv: it travels on the worker's stdin. argv carries only the fixed
`PI_SYSTEM_PROMPT` literal, the tool allowlist, the model and an optional effort.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Literal

from amicus.backends.pi import contract
from amicus.sdk.backend.protocol import ClassifiedFailure, RepairHint
from amicus.sdk.core import redaction, runtime

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Callable

    from amicus.sdk.core.runtime import CommandRun

AuthStatus = Literal["ready", "not_ready", "unresolved", "missing", "unknown"]


def build_exec_command(
    *, pi_bin: str, read_only: bool, model: str, thinking: str | None
) -> list[str]:
    """The `pi -p` invocation. No prompt text: the prompt is written to stdin by the runner.
    `--append-system-prompt ""` keeps a discovered APPEND_SYSTEM.md inert."""
    tools = contract.READ_ONLY_TOOLS if read_only else contract.WRITE_TOOLS
    argv = [
        pi_bin,
        *contract.RUN_FLAGS,
        contract.SYSTEM_PROMPT_FLAG,
        contract.PI_SYSTEM_PROMPT,
        contract.APPEND_SYSTEM_PROMPT_FLAG,
        "",
        contract.TOOLS_FLAG,
        ",".join(tools),
        contract.MODEL_FLAG,
        model,
    ]
    if thinking is not None:
        argv += [contract.THINKING_FLAG, thinking]
    return argv


def build_run_env(base: dict[str, str]) -> dict[str, str]:
    """Child environment: telemetry and the version check off, a session-dir override dropped.
    Provider credentials are inherited: they are what authenticate the run."""
    env = {k: v for k, v in base.items() if k not in contract.RUN_ENV_DROP}
    env.update(contract.RUN_ENV_SET)
    return env


# --- free probes ------------------------------------------------------------------------------
# Each takes the directory to spawn pi from: callers pass `config.probe_cwd`, never the
# server's own cwd, because pi migrates the project files of its cwd at startup.


def pi_version(binary: str, timeout_seconds: int = 10, *, cwd: str | None = None) -> str | None:
    run = runtime.run_sync_capture(
        [binary, *contract.VERSION_ARGS], timeout_seconds=timeout_seconds, cwd=cwd
    )
    if run.binary_missing or run.exit_code != 0:
        return None
    return run.stdout.strip() or None


def auth_status(
    binary: str, model: str | None, timeout_seconds: int = 10, *, cwd: str | None = None
) -> AuthStatus:
    """`pi auth check --model <model> --json --no-refresh`: free, never passes `--credentials`.
    No model spawns nothing. pi wraps any exception during the check, including "Unable to
    resolve model", as status `invalid` whose `provider` is the requested model string, so
    that shape is `unresolved`; any other `invalid` is a runtime-state problem, `not_ready`.
    A binary that could not be spawned is `missing`, so validation can step aside and let the
    run report pi_not_found. Unparseable output or a timeout is `unknown`."""
    if not model:
        return "unknown"
    run = runtime.run_sync_capture(
        [binary, *contract.AUTH_CHECK_ARGS, "--model", model],
        timeout_seconds=timeout_seconds,
        cwd=cwd,
    )
    if run.binary_missing:
        return "missing"
    if run.timed_out:
        return "unknown"
    try:
        data = json.loads(run.stdout)
    except (json.JSONDecodeError, TypeError, RecursionError):
        return "unknown"
    if not isinstance(data, dict):
        return "unknown"
    status = data.get("status")
    if status == "ready":
        return "ready"
    if status == "not_ready":
        return "not_ready"
    if status == "invalid":
        return "unresolved" if data.get("provider") == model else "not_ready"
    return "unknown"


NO_DIAGNOSTIC = "pi wrote no error message and nothing to stderr."
_ECHO_MAX_CHARS = 200
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    return _ANSI_ESCAPE.sub("", text)


def version_display(version: str | None) -> str | None:
    """The bounded, sanitized DISPLAY copy of a version string; None when nothing survives."""
    if version is None:
        return None
    sanitized = redaction.sanitize_echo(_strip_ansi(version))
    return sanitized[:_ECHO_MAX_CHARS] or None


# --- classification --------------------------------------------------------------------------


def classify_failure(
    run: CommandRun,
    *,
    error_message: str | None,
    sanitize: Callable[[str], str] | None,
    stop_reason: str | None = None,
) -> ClassifiedFailure:
    """Map a non-success run into the shared taxonomy, in the SDK's order: binary missing,
    timeout, drift, auth, rate limit, invalid model, nonzero_exit. pi can fail with exit 0 and
    an error in its event stream, so `error_message` (already extracted) is read alongside
    stderr. stdout is never read: under `--mode json` it is the event stream, which echoes
    the system prompt, the user's prompt and the answer, so a prompt mentioning "401" would
    be misclassified and any copy of it would put prompt input in the detail (rule 18). pi
    writes its own CLI errors to stderr. The generic detail is `error_message`, else stderr,
    else a fixed literal. `sanitize` runs BEFORE the 300-char cut, so a secret or worktree
    path straddling the cut cannot leak a prefix. A zero-exit failure is worded as its
    `stop_reason` (one of normalize.FAILED_STOP_REASONS), since "pi exited 0" beside a
    failure reads as a contradiction."""
    if run.binary_missing:
        return ClassifiedFailure(
            code="pi_not_found",
            detail="The `pi` CLI was not found; run amicus_backends for the resolution detail.",
        )
    if run.timed_out:
        return ClassifiedFailure(code="timeout", detail="pi exceeded the timeout.")
    texts = (run.stderr, error_message)
    if contract.is_contract_drift(*texts):
        return ClassifiedFailure(
            code="cli_contract_changed",
            detail=(
                "pi rejected a flag or value amicus sent — its CLI contract likely changed "
                "for your installed version."
            ),
        )
    if contract.is_auth_failure(*texts):
        return ClassifiedFailure(
            code="pi_auth_required",
            detail="pi is not authenticated: the provider rejected the credentials.",
        )
    if contract.is_rate_limited(*texts):
        retry_after = contract.parse_retry_after_ms(*texts)
        if retry_after is None:
            retry_after = contract.RATE_LIMIT_DEFAULT_BACKOFF_MS
        return ClassifiedFailure(
            code="pi_rate_limited",
            detail="pi hit a usage/rate limit.",
            retry_after_ms=retry_after,
        )
    if contract.is_invalid_model(*texts):
        return ClassifiedFailure(
            code="invalid_model",
            detail="pi does not know that model id.",
            details={"field": "model"},
            repair=RepairHint(
                next_step="use_allowed_value",
                tool="amicus_models",
                alternative="Pass one of the model ids amicus_models lists for pi.",
            ),
        )
    raw = (error_message or "").strip() or run.stderr.strip()
    if run.exit_code == 0 and stop_reason:
        prefix = f"pi stopped with reason {stop_reason!r}"
        if not raw:
            return ClassifiedFailure(
                code="nonzero_exit",
                detail=f"{prefix} and wrote no error message and nothing to stderr.",
            )
    else:
        prefix = f"pi exited {run.exit_code}"
    stripped_ansi = _strip_ansi(raw or NO_DIAGNOSTIC)
    sanitized = (
        sanitize(stripped_ansi)
        if sanitize is not None
        else redaction.sanitize_echo_prose(stripped_ansi)
    )
    return ClassifiedFailure(code="nonzero_exit", detail=f"{prefix}: {sanitized[:300]}")
