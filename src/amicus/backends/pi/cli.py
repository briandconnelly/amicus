"""Build the `pi -p --mode json` invocation and child environment, run the free probes, and
classify a failed run into an SDK ClassifiedFailure.

The prompt never rides argv: it travels on the worker's stdin. argv carries only the fixed
`PI_SYSTEM_PROMPT` literal, the tool allowlist, the model and an optional effort.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Literal

from amicus.backends.pi import budget, contract
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


BUDGET_REPAIR = (
    "Before making another call, raise backend_options.max_budget_usd (up to 5.00), narrow the "
    "request, or, when the stop says the cost was unverifiable, choose a model whose provider "
    "reports its cost (OpenRouter does) or run uncapped: omit max_budget_usd when "
    "AMICUS_PI_MAX_BUDGET_USD is unset, since that default applies otherwise. amicus checks "
    "the cap only between pi's model calls, so a run can exceed it by one call or one "
    "compaction, and any retry spends again."
)
BUDGET_DETAIL = (
    "amicus stopped pi at the max-budget threshold before another model call. It checks the "
    "threshold only between model calls, so the cost can exceed it by one call or one "
    "compaction: a stop threshold, not a ceiling."
)
UNVERIFIABLE_DETAIL = (
    "amicus stopped pi before another model call because a call's cost was not reported by "
    "the provider (or its event was lost), so spend could not be checked against "
    "max_budget_usd. A cap fails closed: it never lets a run continue on spend it cannot measure."
)


def budget_failure(reason: str | None, cap_usd: float | None) -> ClassifiedFailure:
    """The `budget_exceeded` failure for a run the spend probe stopped (#454). The spend so
    far rides the envelope's `meta.usage`, from the stream, when the provider reported it."""
    detail = UNVERIFIABLE_DETAIL if reason == budget.UNVERIFIABLE else BUDGET_DETAIL
    if cap_usd is not None:
        detail += f" The cap was {cap_usd:.2f} USD."
    return ClassifiedFailure(
        code="budget_exceeded", detail=detail, details={"field": "backend_options.max_budget_usd"}
    )


def classify_failure(
    run: CommandRun,
    *,
    error_message: str | None,
    sanitize: Callable[[str], str] | None,
    stop_reason: str | None = None,
) -> ClassifiedFailure:
    """Map a non-success run into the shared taxonomy, in the SDK's order: binary missing,
    timeout, OpenRouter's output-reservation 402 (#542), drift, auth, rate limit, invalid model,
    the provider-config failures (a bodiless 404 and a missing region, #520), nonzero_exit.
    pi can fail with exit 0 and an error in its event stream, so `error_message` (already
    extracted) is read alongside stderr. stdout is never read: under `--mode json` it is the
    event stream, which echoes the system prompt, the user's prompt and the answer, so a
    prompt mentioning "401" would be misclassified and any copy of it would put prompt input
    in the detail (rule 18). pi writes its own CLI errors to stderr. The generic detail is
    `error_message`, else stderr, else a fixed literal. `sanitize` runs BEFORE the 300-char
    cut, so a secret or worktree path straddling the cut cannot leak a prefix. A zero-exit
    failure is worded as its `stop_reason` (one of normalize.FAILED_STOP_REASONS), since
    "pi exited 0" beside a failure reads as a contradiction."""
    if run.binary_missing:
        return ClassifiedFailure(
            code="pi_not_found",
            detail="The `pi` CLI was not found; run amicus_backends for the resolution detail.",
        )
    if run.timed_out:
        return ClassifiedFailure(code="timeout", detail="pi exceeded the timeout.")
    texts = (run.stderr, error_message)
    # Before the generic signatures: the 402's token figures can hold "401" or "429".
    if contract.is_output_reservation_refused(*texts):
        return _output_reservation_failure(
            _generic_detail(run, error_message, sanitize, stop_reason),
            contract.output_reservation_figures(*texts),
        )
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
    if contract.is_bodiless_404(*texts):
        return _provider_config_failure(
            _generic_detail(run, error_message, sanitize, stop_reason),
            details={"reason": "the provider answered 404 with no body"},
            repair=BODILESS_404_REPAIR,
        )
    if contract.is_region_missing(*texts):
        return _provider_config_failure(
            _generic_detail(run, error_message, sanitize, stop_reason),
            details={"reason": "the provider client has no region configured"},
            repair=REGION_MISSING_REPAIR,
        )
    return ClassifiedFailure(
        code="nonzero_exit", detail=_generic_detail(run, error_message, sanitize, stop_reason)
    )


def _generic_detail(
    run: CommandRun,
    error_message: str | None,
    sanitize: Callable[[str], str] | None,
    stop_reason: str | None,
) -> str:
    raw = (error_message or "").strip() or run.stderr.strip()
    if run.exit_code == 0 and stop_reason:
        prefix = f"pi stopped with reason {stop_reason!r}"
        if not raw:
            return f"{prefix} and wrote no error message and nothing to stderr."
    else:
        prefix = f"pi exited {run.exit_code}"
    stripped_ansi = _strip_ansi(raw or NO_DIAGNOSTIC)
    sanitized = (
        sanitize(stripped_ansi)
        if sanitize is not None
        else redaction.sanitize_echo_prose(stripped_ansi)
    )
    return f"{prefix}: {sanitized[:300]}"


OUTPUT_RESERVATION_REPAIR = (
    "The provider refused the request before running it: pi asks for the model's whole "
    "output limit, and the account balance does not cover that worst case. Retrying the "
    "same call cannot succeed. Either add credit, or cap the model's output in pi's "
    "models.json, in $PI_CODING_AGENT_DIR when that is set and ~/.pi/agent otherwise, e.g. "
    '{"providers":{"openrouter":{"modelOverrides":{"<model id>":{"maxTokens":32000}}}}}, '
    "or pick a model with a smaller max-out from amicus_models."
)


def _output_reservation_failure(detail: str, figures: tuple[int, int] | None) -> ClassifiedFailure:
    """#542: nonzero_exit, but never temporary, with the remedy named. Not a new code, so
    the published error catalog is unchanged."""
    details: dict[str, str] = {"field": "model"}
    if figures is not None:
        requested, affordable = figures
        details["reason"] = (
            f"requested up to {requested} output tokens; the balance covers {affordable}"
        )
    return ClassifiedFailure(
        code="nonzero_exit",
        detail=detail,
        retryable=False,
        details=details,
        repair=RepairHint(next_step="correct_config", alternative=OUTPUT_RESERVATION_REPAIR),
    )


BODILESS_404_REPAIR = (
    "The provider answered 404 with no body. That usually means the request went to a "
    "model id or an endpoint the provider does not serve, so retrying the same paid call "
    "unchanged is unlikely to help. Check that the model id is one the provider in its "
    "prefix serves (amicus_models lists pi's), and that pi calls the right endpoint for it: "
    "a baseUrl in pi's models.json, in $PI_CODING_AGENT_DIR when that is set and ~/.pi/agent "
    "otherwise, replaces the default."
)
REGION_MISSING_REPAIR = (
    "pi's provider client reported that no region is configured, so retrying the same call "
    "unchanged is unlikely to help. For Amazon Bedrock, set AWS_REGION in the environment "
    "the amicus server starts with and restart the server; for another provider, set the "
    "region its configuration asks for, or pass a model from a provider that needs none."
)


def _provider_config_failure(
    detail: str, *, details: dict[str, str], repair: str
) -> ClassifiedFailure:
    """#520: a provider-configuration failure that retrying unchanged is unlikely to fix.
    nonzero_exit, not temporary, with what to check named; no new code, so the error catalog
    is unchanged."""
    return ClassifiedFailure(
        code="nonzero_exit",
        detail=detail,
        retryable=False,
        details=details,
        repair=RepairHint(next_step="correct_config", alternative=repair),
    )
