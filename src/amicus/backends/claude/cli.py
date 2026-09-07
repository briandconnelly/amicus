"""Build the `claude -p` invocation, scrub the child environment per config mode, run the
free probes, and classify a failed or failure-shaped run into a pontonier ClassifiedFailure
(ported from claude-in-codex `claude.py`/`config.py`).

Two guarantees live here:

* argv carries no caller text. Its only free-text value is the constant independent-critic
  guardrails on --append-system-prompt; the prompt, and any instructions_append, ride stdin.
* The classifier sanitizes BEFORE it truncates, so a secret or a worktree path that straddles
  the cut cannot leak a prefix; the site's alias sanitizer runs when the loop supplies one.
"""

from __future__ import annotations

import os
import re
import subprocess
from typing import TYPE_CHECKING, Any

from pontonier.backend.protocol import ClassifiedFailure, RepairHint
from pontonier.conventions import preflight
from pontonier.core import redaction, runtime

from amicus.backends.claude import contract, normalize
from amicus.config.envspec import is_env_placeholder

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Callable, Mapping

    from pontonier.conventions.preflight import FlagSupport
    from pontonier.core.runtime import CommandRun

_ECHO_MAX_CHARS = 300
_RESULT_ECHO_MAX_CHARS = 200
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")

NOT_FOUND_DETAIL = "The `claude` CLI was not found; run amicus_backends for the resolution detail."
TIMEOUT_DETAIL = (
    "claude exceeded the timeout. The call MAY already have been charged — a timeout cannot "
    "tell a request that was billed from one that never reached Anthropic — and re-issuing it "
    "risks a second charge for work you cannot recover."
)
TIMEOUT_REPAIR = (
    "Decide whether to spend again: any next attempt is a NEW paid run, not a recovery of this "
    "one. To retry, start the matching _async twin (amicus_consult_async / "
    "amicus_review_changes_async / amicus_adversarial_review_async), which survives the "
    "deadline; its idempotency_key guards that new launch against duplicate retries. Raising "
    "timeout_seconds or narrowing the scope spends again too."
)
BUDGET_REPAIR = (
    "Before making another call, raise backend_options.max_budget_usd (up to 5.00) or narrow "
    "the prompt/context (for reviews, a smaller scope or fewer paths). For small prompts try at "
    "least 0.10-0.20; a lower best-effort budget can spend and still stop before a useful answer."
)
PERMISSION_REPAIR = (
    "Use backend_options.access='toolless' (the default), or 'readonly' when Claude must read "
    "files itself; a denied tool is never granted by amicus."
)
DRIFT_DETAIL = (
    "claude rejected a flag or value amicus sent — its CLI contract likely changed for your "
    "installed version."
)
INVALID_JSON_DETAIL = "claude exited 0 but printed no JSON result envelope on stdout."


# --- argv -----------------------------------------------------------------------------------


def config_mode_flags(mode: str) -> list[str]:
    """Every mode drops the user's MCP fleet and session persistence; inherit/scoped/safe keep
    the user's login, bare needs an API key. Byte-for-byte the sibling's lists."""
    if mode == "inherit":
        return [
            contract.NO_SESSION_PERSISTENCE_FLAG,
            contract.STRICT_MCP_FLAG,
            contract.MCP_CONFIG_FLAG,
            contract.EMPTY_MCP,
        ]
    if mode == "scoped":
        return [
            contract.SETTING_SOURCES_FLAG,
            "project",
            contract.STRICT_MCP_FLAG,
            contract.MCP_CONFIG_FLAG,
            contract.EMPTY_MCP,
            contract.NO_SESSION_PERSISTENCE_FLAG,
        ]
    if mode == "safe":
        return [
            contract.SAFE_MODE_FLAG,
            contract.NO_SESSION_PERSISTENCE_FLAG,
            contract.STRICT_MCP_FLAG,
            contract.MCP_CONFIG_FLAG,
            contract.EMPTY_MCP,
        ]
    if mode == "bare":
        return [
            contract.BARE_FLAG,
            contract.NO_SESSION_PERSISTENCE_FLAG,
            contract.STRICT_MCP_FLAG,
            contract.MCP_CONFIG_FLAG,
            contract.EMPTY_MCP,
        ]
    raise ValueError(f"unsupported config_mode: {mode}")


def access_flags(access: str) -> list[str]:
    if access == "toolless":
        return [contract.TOOLS_FLAG, ""]
    if access == "readonly":
        return [
            contract.TOOLS_FLAG,
            contract.READONLY_TOOLS,
            contract.DISALLOWED_TOOLS_FLAG,
            contract.READONLY_DISALLOWED_TOOLS,
        ]
    raise ValueError(f"unsupported access: {access}")


def _gate_optional(tokens: list[str], fs: FlagSupport) -> tuple[list[str], list[str]]:
    kept: list[str] = []
    dropped: list[str] = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        takes_value = contract.HELP_GATED_FLAGS.get(token)
        if takes_value is not None:
            if not preflight.is_supported(token, fs):
                dropped.append(token)
                i += 2 if takes_value else 1
                continue
            if takes_value and i + 1 < len(tokens):
                # Consume the value with its flag: a value that happens to look like a flag
                # (a model slug such as "--effort") must never be re-scanned as one.
                kept += [token, tokens[i + 1]]
                i += 2
                continue
        kept.append(token)
        i += 1
    return kept, dropped


def build_command(
    *,
    claude_bin: str,
    config_mode: str,
    access: str,
    system_prompt: str,
    max_budget_usd: float,
    effort: str | None,
    model: str | None,
    flag_support: FlagSupport,
) -> tuple[list[str], list[str]]:
    """The `claude -p --output-format json` invocation. Returns (argv, dropped_help_gated_flags).
    The prompt is NOT here: the runner streams it over stdin."""
    tokens = [claude_bin, *contract.CORE_INVOCATION, contract.NO_CHROME_FLAG]
    tokens += config_mode_flags(config_mode)
    tokens += access_flags(access)
    tokens += [contract.APPEND_SYSTEM_PROMPT_FLAG, system_prompt]
    tokens += [contract.MAX_BUDGET_FLAG, f"{max_budget_usd}"]
    if effort:
        tokens += [contract.EFFORT_FLAG, effort]
    if model:
        tokens += [contract.MODEL_FLAG, model]
    return _gate_optional(tokens, flag_support)


def scrub_env(env: Mapping[str, str], config_mode: str | None) -> dict[str, str]:
    """Login-backed modes must use Claude Code's OAuth/session path, so a stale direct
    credential cannot override it; bare NEEDS the key and keeps the environment whole."""
    if config_mode not in contract.LOGIN_MODES:
        return dict(env)
    return {k: v for k, v in env.items() if k not in contract.LOGIN_CREDENTIAL_ENV_VARS}


# --- free probes ------------------------------------------------------------------------------


def claude_version(binary: str, timeout_seconds: int = 10) -> str | None:
    run = runtime.run_sync_capture(
        [binary, *contract.VERSION_ARGS], timeout_seconds=timeout_seconds
    )
    if run.binary_missing or run.exit_code != 0:
        return None
    return run.stdout.strip() or None


def auth_status(binary: str, config_mode: str, timeout_seconds: int = 10) -> bool | None:
    """`claude auth status --text`, exit code ONLY: the text names the account and organization
    and is never read. None when the probe could not run. The env is scrubbed per mode so the
    probe answers for the credential path the run would use."""
    try:
        proc = subprocess.run(
            [binary, *contract.AUTH_STATUS_ARGS],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
            env=scrub_env(os.environ, config_mode),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.returncode == 0


def _strip_ansi(text: str) -> str:
    return _ANSI_ESCAPE.sub("", text)


def version_display(version: str | None) -> str | None:
    if version is None:
        return None
    sanitized = redaction.sanitize_echo(_strip_ansi(version))
    return sanitized[:_ECHO_MAX_CHARS] or None


# --- classification --------------------------------------------------------------------------


def _clean(text: str | None, sanitize: Callable[[str], str] | None) -> str:
    """ANSI-stripped, sanitized prose, UNTRUNCATED: callers cut after this so a secret or a
    worktree path straddling the cut cannot leak a prefix."""
    stripped = _strip_ansi(text or "")
    if sanitize is not None:
        return sanitize(stripped) or ""
    return redaction.sanitize_echo_prose(stripped) or ""


def auth_repair_for(config_mode: str | None) -> str:
    if config_mode in contract.LOGIN_MODES:
        return "Run `claude /login`; the requested config_mode uses the Claude login path."
    if config_mode == "bare":
        return (
            "Set a valid ANTHROPIC_API_KEY, or use backend_options.config_mode "
            "inherit/scoped/safe after `claude /login`."
        )
    return "Run `claude /login`, or set a valid ANTHROPIC_API_KEY for config_mode=bare."


def api_key_repair_for(config_mode: str | None, environ: Mapping[str, str] | None = None) -> str:
    env = os.environ if environ is None else environ
    # A literal `${ANTHROPIC_API_KEY}` is the host failing to expand env vars, not a bad key.
    if is_env_placeholder(env.get(contract.API_KEY_ENV)):
        return (
            "ANTHROPIC_API_KEY is a literal ${...} placeholder; your MCP host is not expanding "
            "env substitutions. Use an env_vars passthrough list, or set a literal key."
        )
    if config_mode in contract.LOGIN_MODES:
        return (
            "The requested config_mode does not rely on ANTHROPIC_API_KEY; unset or fix "
            "ANTHROPIC_API_KEY, then rerun amicus_backends before retrying."
        )
    return (
        "Set a valid ANTHROPIC_API_KEY, or use backend_options.config_mode inherit/scoped/safe "
        "after `claude /login`."
    )


def _hint(next_step: str, alternative: str, tool: str | None = None) -> RepairHint:
    return RepairHint(next_step=next_step, tool=tool, alternative=alternative)


def classify_envelope(
    env: dict[str, Any],
    *,
    stderr: str,
    config_mode: str | None,
    sanitize: Callable[[str], str] | None,
) -> ClassifiedFailure:
    """A zero-exit (or any-exit) FAILURE envelope into the shared taxonomy, in the sibling's
    order: logged out → invalid key → auth-ish → budget → permission → rate limit → drift →
    generic. The result text is model-derived and may carry secrets, so it is sanitized before
    any of it is echoed or matched. Usage the envelope still reports rides along."""
    subtype = str(env.get("subtype") or "").lower()
    result = _clean(normalize.extract_answer(env), sanitize)
    structured = f"{subtype}\n{result}"
    combined = f"{structured}\n{_clean(stderr, sanitize)}"
    usage = normalize.extract_usage(env)
    if contract.is_logged_out(combined):
        return ClassifiedFailure(
            code="claude_auth_required",
            detail="claude is not authenticated.",
            repair=_hint("authenticate", auth_repair_for(config_mode)),
            usage=usage,
        )
    if contract.is_invalid_api_key(structured):
        return ClassifiedFailure(
            code="api_key_invalid",
            detail="ANTHROPIC_API_KEY is invalid.",
            repair=_hint("authenticate", api_key_repair_for(config_mode), "amicus_backends"),
            usage=usage,
        )
    if contract.mentions_auth(structured):
        return ClassifiedFailure(
            code="claude_auth_required",
            detail="claude is not authenticated.",
            repair=_hint("authenticate", auth_repair_for(config_mode)),
            usage=usage,
        )
    if contract.is_budget_stop(structured):
        return ClassifiedFailure(
            code="budget_exceeded",
            detail=(
                "claude reached the max-budget stop threshold "
                "(a best-effort limit, not a hard cap)."
            ),
            retryable=False,
            details={"field": "backend_options.max_budget_usd"},
            repair=_hint("reduce_input", BUDGET_REPAIR),
            usage=usage,
        )
    if contract.is_permission_denied(structured):
        return ClassifiedFailure(
            code="claude_permission_error",
            detail="claude was denied a requested permission.",
            retryable=False,
            details={"field": "backend_options.access"},
            repair=_hint("correct_arguments", PERMISSION_REPAIR),
            usage=usage,
        )
    if contract.is_rate_limited(structured):
        return ClassifiedFailure(
            code="claude_rate_limited",
            detail=f"claude reported a rate limit: {result[:_RESULT_ECHO_MAX_CHARS]}",
            usage=usage,
        )
    if contract.is_contract_drift(structured):
        return ClassifiedFailure(code="cli_contract_changed", detail=DRIFT_DETAIL, usage=usage)
    detail = result.strip()[:_RESULT_ECHO_MAX_CHARS] or subtype or "unknown error"
    # The model ran and reported an error about THIS request: replaying it unchanged gives the
    # same answer, so this is not temporary (the sibling agrees: retryable=False).
    return ClassifiedFailure(
        code="nonzero_exit",
        detail=f"claude reported an error: {detail}",
        retryable=False,
        usage=usage,
    )


def classify_failure(
    run: CommandRun, *, config_mode: str | None, sanitize: Callable[[str], str] | None
) -> ClassifiedFailure:
    """Map a non-success process into the shared taxonomy: binary missing → timeout → a
    failure envelope on stdout (whatever the exit code) → the stderr/stdout blob: logged out →
    invalid key → budget → rate limit → drift (last, so an auth message is never misread as
    drift) → nonzero_exit."""
    if run.binary_missing:
        return ClassifiedFailure(code="claude_not_found", detail=NOT_FOUND_DETAIL)
    if run.timed_out:
        return ClassifiedFailure(
            code="timeout",
            detail=TIMEOUT_DETAIL,
            retryable=False,
            repair=_hint("start_new_job", TIMEOUT_REPAIR),
        )
    env = normalize.parse_envelope(run.stdout)
    if env is not None and normalize.is_failure_envelope(env):
        return classify_envelope(env, stderr=run.stderr, config_mode=config_mode, sanitize=sanitize)
    safe_stderr = _clean(run.stderr, sanitize)
    extra = _clean(normalize.extract_answer(env), sanitize) if env is not None else ""
    blob = f"{extra}\n{run.stdout if env is None else ''}\n{safe_stderr}"
    if contract.is_logged_out(blob):
        return ClassifiedFailure(
            code="claude_auth_required",
            detail="claude is not authenticated.",
            repair=_hint("authenticate", auth_repair_for(config_mode)),
        )
    if contract.is_invalid_api_key(blob):
        return ClassifiedFailure(
            code="api_key_invalid",
            detail="ANTHROPIC_API_KEY is invalid.",
            repair=_hint("authenticate", api_key_repair_for(config_mode), "amicus_backends"),
        )
    if contract.is_budget_stop(blob):
        return ClassifiedFailure(
            code="budget_exceeded",
            detail=(
                "claude reached the max-budget stop threshold "
                "(a best-effort limit, not a hard cap)."
            ),
            retryable=False,
            details={"field": "backend_options.max_budget_usd"},
            repair=_hint("reduce_input", BUDGET_REPAIR),
        )
    if contract.is_rate_limited(blob):
        return ClassifiedFailure(code="claude_rate_limited", detail="claude hit a rate limit.")
    if contract.is_contract_drift(blob):
        return ClassifiedFailure(code="cli_contract_changed", detail=DRIFT_DETAIL)
    return ClassifiedFailure(
        code="nonzero_exit",
        detail=f"claude exited {run.exit_code}: {safe_stderr.strip()[:_ECHO_MAX_CHARS]}",
    )
