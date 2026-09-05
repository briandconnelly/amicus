"""Build the `codex exec` argv, run the free probes, and classify a failed run into a
pontonier ClassifiedFailure (ported from codex-in-claude `codex.py`)."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from pontonier.backend.protocol import ClassifiedFailure, RepairHint
from pontonier.conventions import preflight
from pontonier.core import redaction, runtime

from amicus.backends.codex import contract, normalize
from amicus.backends.codex.config import ExtraArgs, isolation_flags
from amicus.schemas import instructions

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Callable

    from pontonier.conventions.preflight import FlagSupport
    from pontonier.core.runtime import CommandRun

_CONFIG_OVERRIDE_FLAGS = ("-c", "--config")


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
    codex_bin: str,
    cwd: str,
    sandbox: str,
    isolation: str,
    output_last_message_path: str,
    model: str | None = None,
    reasoning_effort: str | None = None,
    developer_instructions: str | None = None,
    output_schema_path: str | None = None,
    skip_git_repo_check: bool = False,
    extra_args: tuple[str, ...] = (),
    flag_support: FlagSupport,
) -> tuple[list[str], list[str]]:
    """The `codex exec` invocation; the prompt rides stdin (trailing `-`). Returns
    (argv, dropped_help_gated_flags). Plugin-owned tokens precede operator extra args;
    `--strict-config` rides only when a `-c` override does."""
    tokens = [codex_bin, *contract.EXEC_SUBCOMMAND, "--json", "--sandbox", sandbox, "--cd", cwd]
    tokens += ["--output-last-message", output_last_message_path, "--ephemeral"]
    plugin_config_override = False
    for feature in contract.MODEL_RUN_DISABLED_FEATURES:
        tokens += [contract.DISABLE_FEATURE_FLAG, feature]
    if sandbox == contract.SANDBOX_WORKSPACE_WRITE:
        tokens += ["-c", f"{contract.WORKSPACE_WRITE_NETWORK_ACCESS_CONFIG_KEY}=false"]
        tokens += ["-c", f"{contract.WORKSPACE_WRITE_WRITABLE_ROOTS_CONFIG_KEY}=[]"]
        plugin_config_override = True
    tokens += isolation_flags(isolation)
    if skip_git_repo_check:
        tokens += ["--skip-git-repo-check"]
    if output_schema_path:
        tokens += ["--output-schema", output_schema_path]
    if model:
        tokens += [contract.MODEL_FLAG, model]
    # TOML-string-encoded (JSON string syntax is valid TOML); ensure_ascii=False keeps astral
    # characters scalar. An explicit "" is the caller's value and is sent.
    if reasoning_effort is not None:
        tokens += [
            "-c",
            f"{contract.MODEL_REASONING_EFFORT_CONFIG_KEY}="
            f"{json.dumps(reasoning_effort, ensure_ascii=False)}",
        ]
        plugin_config_override = True
    if developer_instructions is not None:
        tokens += [
            "-c",
            f"{contract.DEVELOPER_INSTRUCTIONS_CONFIG_KEY}="
            + json.dumps(instructions.compose(developer_instructions), ensure_ascii=False),
        ]
        plugin_config_override = True
    operator_config_override = any(
        extra_args[i] in _CONFIG_OVERRIDE_FLAGS for i in range(0, len(extra_args), 2)
    )
    if plugin_config_override or operator_config_override:
        tokens += [contract.STRICT_CONFIG_FLAG]
    cmd, dropped = _gate_optional(tokens, flag_support)
    cmd += list(extra_args)
    cmd += [contract.STDIN_PROMPT]
    return cmd, dropped


def plugin_config_keys_for(
    *, sandbox: str, reasoning_effort: str | None, developer_instructions: str | None
) -> frozenset[str]:
    """The `-c` KEYS build_exec_command emits for a run of this shape."""
    keys: set[str] = set()
    if sandbox == contract.SANDBOX_WORKSPACE_WRITE:
        keys.add(contract.WORKSPACE_WRITE_NETWORK_ACCESS_CONFIG_KEY)
        keys.add(contract.WORKSPACE_WRITE_WRITABLE_ROOTS_CONFIG_KEY)
    if reasoning_effort is not None:
        keys.add(contract.MODEL_REASONING_EFFORT_CONFIG_KEY)
    if developer_instructions is not None:
        keys.add(contract.DEVELOPER_INSTRUCTIONS_CONFIG_KEY)
    return frozenset(keys)


# --- free probes -------------------------------------------------------------------------------


def codex_version(binary: str, timeout_seconds: int = 10) -> str | None:
    """Raw `codex --version` output (the IDENTITY version parsing reads), or None."""
    run = runtime.run_sync_capture(
        [binary, *contract.VERSION_ARGS], timeout_seconds=timeout_seconds
    )
    if run.binary_missing or run.exit_code != 0:
        return None
    return run.stdout.strip() or None


def login_status(binary: str, timeout_seconds: int = 10) -> tuple[bool | None, str | None]:
    """(logged_in, non-identifying detail). None when the probe could not run."""
    run = runtime.run_sync_capture(
        [binary, *contract.LOGIN_STATUS_ARGS], timeout_seconds=timeout_seconds
    )
    if run.binary_missing or run.timed_out:
        return None, None
    if run.exit_code != 0:
        return False, "Codex reports no authenticated session; run `codex login`."
    blob = f"{run.stdout}\n{run.stderr}".lower()
    if contract.LOGIN_METHOD_CHATGPT.lower() in blob:
        method = "ChatGPT"
    elif contract.LOGIN_METHOD_API_KEY.lower() in blob:
        method = "API key"
    else:
        method = None
    detail = (
        f"Codex reports an authenticated session ({method})."
        if method
        else "Codex reports an authenticated session."
    )
    return True, detail


_ECHO_MAX_CHARS = 200
_ECHO_TRUNC_MARKER = "…[truncated]"


def _bounded_echo(text: str) -> str:
    if len(text) <= _ECHO_MAX_CHARS:
        return text
    return text[: _ECHO_MAX_CHARS - len(_ECHO_TRUNC_MARKER)] + _ECHO_TRUNC_MARKER


def safe_echo(text: str | None) -> str:
    """Sanitize (strip controls, redact) then bound a single-token echoed span."""
    return _bounded_echo(redaction.sanitize_echo(text))


def version_display(version: str | None) -> str | None:
    """The bounded, sanitized DISPLAY copy of a version string; None when nothing survives."""
    return safe_echo(version) or None


# --- classification ----------------------------------------------------------------------------

_CAPTURE_FAILED_TIMEOUT_MESSAGE = (
    "codex exceeded the timeout, and amicus's output capture failed mid-run (a capture "
    "thread died). Codex may have been blocked on an undrained pipe rather than slow, so this "
    "may be a bridge fault rather than a model timeout."
)
_CAPTURE_FAILED_TIMEOUT_ALTERNATIVE = (
    "Retry the same call once first: if the capture failure caused this timeout, the retry "
    "may finish normally. If it times out again without this notice, treat it as an ordinary "
    "timeout — prefer the matching async tool, or narrow the task or raise timeout_seconds."
)
_CAPTURE_FAILED_EXIT_NOTE = (
    " (amicus's output capture failed mid-run, so part of codex's output may have been lost "
    "and this diagnosis may be incomplete)"
)
_CONFIG_VALUE_REPAIR_TAIL = (
    "Remove or change the setting in your Codex config — checking any operator-selected "
    "profile too — then rerun. As a last resort, backend_options.isolation='ignore-config' "
    "skips your config file for the run — but it drops ALL of it (model provider, MCP "
    "servers, and every other setting), so prefer fixing the setting."
)


def _contract_changed() -> ClassifiedFailure:
    return ClassifiedFailure(
        code="cli_contract_changed",
        detail=(
            "codex rejected a flag or value amicus sent — its CLI contract likely changed "
            "for your installed version."
        ),
    )


def _extra_args_rejected(matched: list[str]) -> ClassifiedFailure:
    named = ", ".join(safe_echo(d) for d in matched) if matched else "AMICUS_CODEX_EXTRA_ARGS"
    return ClassifiedFailure(
        code="extra_args_rejected",
        detail=(
            f"codex rejected an argument from AMICUS_CODEX_EXTRA_ARGS ({named}) — the "
            "passthrough option/config key/profile is not accepted by your installed codex."
        ),
        repair=RepairHint(
            next_step="correct_config",
            alternative=(
                f"Fix or remove the offending entry ({named}) in AMICUS_CODEX_EXTRA_ARGS; "
                "this is operator config, NOT a contract drift. Verify the option against "
                "`codex --help` / `codex exec --help` for your installed version."
            ),
        ),
    )


def _user_config_rejected(detail: str, alternative: str | None = None) -> ClassifiedFailure:
    return ClassifiedFailure(
        code="user_config_rejected",
        detail=detail,
        repair=RepairHint(next_step="correct_config", alternative=alternative)
        if alternative
        else None,
    )


def _strict_config_failure(
    rejection: contract.StrictConfigRejection, extra: ExtraArgs
) -> ClassifiedFailure:
    if rejection.origin == "override":
        if rejection.key in contract.PLUGIN_OWNED_CONFIG_KEYS:
            return _contract_changed()
        if extra.owns_config_key(rejection.key):
            return _extra_args_rejected([rejection.key])
        return _contract_changed()
    if extra.owns_profile_file(rejection.source_path):
        return _extra_args_rejected([rejection.key])
    where = safe_echo(rejection.source_path) or "your Codex config"
    line = f":{rejection.line}" if rejection.line is not None else ""
    return _user_config_rejected(
        f"codex refused to start: your Codex config sets `{safe_echo(rejection.key)}`, which "
        f"this codex version does not recognize ({where}{line}). No model call was made."
    )


def _config_value_failure(
    key: str,
    *,
    what_is_wrong: str,
    alternative: str,
    extra: ExtraArgs,
    plugin_config_keys: frozenset[str],
) -> ClassifiedFailure:
    if key in plugin_config_keys:
        return _contract_changed()
    if extra.owns_config_key(key):
        return _extra_args_rejected([key])
    caveat = ""
    if extra.profile_names:
        selected = ", ".join(safe_echo(n) for n in extra.profile_names)
        caveat = (
            f" The setting may instead come from the operator profile selected by "
            f"AMICUS_CODEX_EXTRA_ARGS ({selected}), which amicus cannot inspect — check there too."
        )
    return _user_config_rejected(
        f"codex refused to start: your Codex config sets `{safe_echo(key)}` {what_is_wrong} "
        f"Remove or change that setting.{caveat} No model call was made.",
        alternative,
    )


def _descriptor_in_blob(descriptor: str, blob: str) -> bool:
    pattern = rf"(?<![\w-]){re.escape(descriptor)}(?![\w-])"
    return re.search(pattern, blob, re.IGNORECASE) is not None


def _extra_args_drift_match(extra: ExtraArgs, *texts: str | None) -> list[str] | None:
    if not extra.configured or not extra.valid or not extra.descriptors:
        return None
    blob = "\n".join(t for t in texts if t)
    matched = [d for d in extra.descriptors if _descriptor_in_blob(d, blob)]
    return matched or None


def classify_failure(
    run: CommandRun,
    *,
    last_message: str | None,
    events: str | None,
    extra_args: ExtraArgs,
    reasoning_effort: str | None,
    sanitize: Callable[[str], str] | None,
    plugin_config_keys: frozenset[str],
) -> ClassifiedFailure:
    """Map a non-success run into the shared taxonomy. Order: binary missing → timeout →
    the three config-parse grammars (stderr only, ahead of the substring matchers they could
    satisfy) → auth → drift (with effort/operator attribution) → rate limit → nonzero_exit.
    `sanitize` replaces the generic branch's sanitizer (delegate passes the worktree-aware
    one) and runs BEFORE the 300-char cut."""
    if run.binary_missing:
        return ClassifiedFailure(
            code="codex_not_found",
            detail="The `codex` CLI was not found; run amicus_backends for the resolution detail.",
        )
    if run.timed_out:
        if run.capture_failed:
            return ClassifiedFailure(
                code="timeout",
                detail=_CAPTURE_FAILED_TIMEOUT_MESSAGE,
                repair=RepairHint(
                    next_step="retry_after_delay", alternative=_CAPTURE_FAILED_TIMEOUT_ALTERNATIVE
                ),
            )
        return ClassifiedFailure(code="timeout", detail="codex exceeded the timeout.")
    event_error = normalize.extract_error_message(events) if events else None
    strict = contract.parse_strict_config_rejection(run.stderr)
    if strict is not None:
        return _strict_config_failure(strict, extra_args)
    retired = contract.parse_unsupported_config_setting(run.stderr)
    if retired is not None:
        return _config_value_failure(
            retired.key,
            what_is_wrong=(
                f"to {safe_echo(retired.value)}, which this codex version no longer supports."
            ),
            alternative=(
                "This codex version no longer supports that config VALUE (the key itself is "
                "still recognized, and codex reports no file or line for it). "
                + _CONFIG_VALUE_REPAIR_TAIL
            ),
            extra=extra_args,
            plugin_config_keys=plugin_config_keys,
        )
    invalid = contract.parse_invalid_config_value(run.stderr)
    if invalid is not None:
        expected = safe_echo(invalid.expected)
        what = (
            f"to a value this codex version does not accept (expected one of {expected})."
            if invalid.kind == "unknown_variant"
            else f"to a value of the wrong type (expected {expected})."
        )
        return _config_value_failure(
            invalid.key,
            what_is_wrong=what,
            alternative=(
                "codex refused that config VALUE: the key itself is recognized, but the value "
                "is not one it accepts, and codex reports no file or line for it. "
                + _CONFIG_VALUE_REPAIR_TAIL
            ),
            extra=extra_args,
            plugin_config_keys=plugin_config_keys,
        )
    if contract.is_auth_failure(run.stderr, run.stdout, last_message, event_error):
        return ClassifiedFailure(code="codex_auth_required", detail="codex is not authenticated.")
    # The reasoning-effort rejection markers are checked on their own, ahead of the generic
    # drift-pattern gate: the sibling's actual message shape does not always also match one
    # of CONTRACT_DRIFT_STDERR_PATTERNS (e.g. it may omit "invalid value"), and the bracketed
    # markers are specific enough on their own to distinguish a caller error from drift.
    if reasoning_effort is not None and contract.is_reasoning_effort_rejection(
        run.stderr, run.stdout, event_error
    ):
        return ClassifiedFailure(
            code="invalid_reasoning_effort",
            detail=(
                "The Codex backend rejected the requested reasoning_effort for this model/account."
            ),
            details={"field": "reasoning_effort"},
        )
    if contract.is_contract_drift(run.stderr, run.stdout, event_error):
        matched = _extra_args_drift_match(extra_args, run.stderr, run.stdout, event_error)
        if matched is not None and contract.is_reasoning_effort_rejection(*matched):
            return _extra_args_rejected(matched)
        plugin_owns_dash_c = reasoning_effort is not None or bool(plugin_config_keys)
        if matched is not None and not (plugin_owns_dash_c and set(matched) <= {"-c"}):
            return _extra_args_rejected(matched)
        return _contract_changed()
    if contract.is_rate_limited(run.stderr, run.stdout, last_message, event_error):
        retry_after = contract.parse_retry_after_ms(
            run.stderr, run.stdout, last_message, event_error
        )
        if retry_after is None:
            retry_after = contract.RATE_LIMIT_DEFAULT_BACKOFF_MS
        return ClassifiedFailure(
            code="codex_rate_limited",
            detail="codex hit a usage/rate limit.",
            retry_after_ms=retry_after,
        )
    raw = (event_error or run.stderr or run.stdout).strip()
    detail = (sanitize(raw) if sanitize is not None else redaction.sanitize_echo_prose(raw))[:300]
    message = f"codex exited {run.exit_code}: {detail}"
    if run.capture_failed:
        message += _CAPTURE_FAILED_EXIT_NOTE
    return ClassifiedFailure(code="nonzero_exit", detail=message)
