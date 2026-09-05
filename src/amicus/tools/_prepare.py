"""The pre-spend preparation every paid sync tool and dry run shares, in the cheapest-first
order: options/availability/feature → placeholders → defaults → roots and host → workspace
(ADR 0003) → effort shape → instructions_append rules → input budget → delegate repo
preflight. Returns a `Prepared` (spec + meta + plugin) or a ready error envelope."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pontonier.core import redaction, worktree

from amicus.errors import error_envelope
from amicus.orchestration import prompts
from amicus.orchestration import workspace as ws
from amicus.request import RunSpec, meta_for
from amicus.schemas import instructions
from amicus.schemas.envelope import ErrorDetail, InvalidArgument, Meta
from amicus.schemas.options import OPTION_ALLOWED_VALUES
from amicus.schemas.params import (
    MAX_TIMEOUT_SECONDS,
    MIN_TIMEOUT_SECONDS,
    reasoning_effort_shape_error,
)
from amicus.tools import _resolve

if TYPE_CHECKING:  # pragma: no cover
    from amicus.config import Settings
    from amicus.plugin import BackendPlugin
    from amicus.registry import BackendRegistry
    from amicus.schemas.options import BackendOptions

DEADLINE_ADVISORY_PROMPT_BYTES = 100_000
_HIGH_EFFORTS = frozenset({"high", "xhigh"})


@dataclass
class Prepared:
    spec: RunSpec
    meta: Meta
    plugin: BackendPlugin


def clamp_timeout(value: int) -> int:
    return max(MIN_TIMEOUT_SECONDS, min(MAX_TIMEOUT_SECONDS, value))


def deadline_advisory(
    would_call_model: bool,
    prompt_bytes: int,
    effort: str | None,
    timeout_seconds: int,
    async_tool: str,
) -> str | None:
    if not would_call_model:
        return None
    if prompt_bytes <= DEADLINE_ADVISORY_PROMPT_BYTES and effort not in _HIGH_EFFORTS:
        return None
    return (
        f"This previewed call's prompt size or reasoning effort may exceed the "
        f"{timeout_seconds}s synchronous deadline; prefer {async_tool} (the async counterpart "
        "of the previewed call), which is polled instead of terminated if the run outlasts "
        "the deadline."
    )


def _placeholder_error(
    settings: Settings, plugin: BackendPlugin, meta: Meta
) -> dict[str, Any] | None:
    names = [*settings.placeholders, *plugin.env.report().placeholders]
    if not names:
        return None
    return error_envelope(
        "unexpanded_env_placeholder",
        redaction.sanitize_echo_prose(f"Unexpanded ${{...}} env placeholders: {', '.join(names)}."),
        meta,
        plugin=plugin,
        repair_alternative=(
            "These env vars are literal ${...}; your MCP host is not expanding env "
            "substitutions. Use an env_vars passthrough list, or set literal values."
        ),
    )


async def prepare_run(
    *,
    registry: BackendRegistry,
    settings: Settings,
    tool_name: str,
    verb: str,
    backend: str,
    backend_options: BackendOptions | None,
    ctx: Any,
    workspace_root: str | None,
    model: str | None,
    reasoning_effort: str | None,
    timeout_seconds: int | None,
    instructions_append: str | None = None,
    extra_context: str | None = None,
    question: str | None = None,
    task: str | None = None,
    focus: str | None = None,
    scope: str | None = None,
    base: str | None = None,
    commit: str | None = None,
    paths: list[str] | None = None,
    untracked: str = "explicit_only",
) -> Prepared | dict[str, Any]:
    resolved = _resolve.resolve_paid_call(
        registry=registry,
        settings=settings,
        tool_name=tool_name,
        verb=verb,
        backend=backend,
        backend_options=backend_options,
    )
    if isinstance(resolved, dict):
        return resolved
    plugin, options = resolved
    defaults = {o.name: o.default for o in plugin.options if verb in o.applies_to}
    for name, default in defaults.items():
        if name in OPTION_ALLOWED_VALUES and name not in options and default is not None:
            options[name] = default
    model_v = model or defaults.get("model")
    effort_from_config = reasoning_effort is None
    effort = reasoning_effort if reasoning_effort is not None else defaults.get("reasoning_effort")
    timeout = clamp_timeout(
        timeout_seconds if timeout_seconds is not None else settings.timeout_seconds
    )

    roots, roots_source = await ws.roots_from_ctx(ctx)
    host_name = prompts.host_display_name(ws.client_name_from_ctx(ctx), settings.host_name)
    resolution = ws.resolve(workspace_root, roots, allow_cwd=settings.allow_cwd_workspace)
    meta = Meta(
        backend=backend,
        cwd=resolution.path,
        workspace_source=resolution.source,  # ty: ignore[invalid-argument-type]
        workspace_warning=ws.workspace_warning_for(resolution.source, resolution.path),
        roots_source=roots_source,  # ty: ignore[invalid-argument-type]
        model=model_v,
        reasoning_effort=effort,
        timeout_seconds=timeout,
        backend_details=dict(options) or None,
    )
    placeholder = _placeholder_error(settings, plugin, meta)
    if placeholder is not None:
        return placeholder
    if resolution.error_code is not None:
        return error_envelope(
            resolution.error_code,
            redaction.sanitize_echo_prose(resolution.error_detail) or "invalid workspace",
            meta,
            plugin=plugin,
            details=ErrorDetail(field="workspace_root"),
            candidate_roots=list(roots)
            if resolution.error_code == "workspace_outside_roots" and roots
            else None,
        )
    assert resolution.path is not None
    if effort is not None and (reason := reasoning_effort_shape_error(effort)) is not None:
        meta.reasoning_effort = None
        return error_envelope(
            "invalid_reasoning_effort",
            f"the requested reasoning_effort {reason}.",
            meta,
            plugin=plugin,
            details=ErrorDetail(field="reasoning_effort"),
            repair_next_step="correct_config" if effort_from_config else "correct_arguments",
            repair_tool=None,
            repair_alternative=(
                "Fix the per-call reasoning_effort or the backend's REASONING_EFFORT default "
                "(no control or surrogate characters, bounded length), or omit the override. "
                "The value never reached the backend (zero spend)."
            ),
        )
    text = instructions.normalize(instructions_append)
    if text is not None and (boundary := instructions.boundary_error(text)) is not None:
        reason, repair = boundary
        return error_envelope(
            "invalid_arguments",
            f"{tool_name}: 1 invalid argument(s): instructions_append — {reason}",
            meta,
            plugin=plugin,
            repair_tool=tool_name,
            repair_alternative=repair,
            invalid_arguments=[InvalidArgument(field="instructions_append", reason=reason)],
        )
    sized = [
        (n, v)
        for n, v in (
            ("question", question),
            ("task", task),
            ("extra_context", extra_context),
            ("instructions_append", text),
            ("focus", focus),
        )
        if v
    ]
    total = sum(len(v.encode("utf-8")) for _, v in sized)
    if total > settings.max_input_bytes:
        fields = [n for n, _ in sized]
        return error_envelope(
            "input_too_large",
            f"{' + '.join(fields)} exceeds {settings.max_input_bytes} bytes.",
            meta,
            plugin=plugin,
            details=ErrorDetail(fields=fields) if len(fields) > 1 else ErrorDetail(field=fields[0]),
            limit_bytes=settings.max_input_bytes,
            actual_bytes=total,
        )
    if verb == "delegate":
        try:
            worktree.ensure_repo_with_head(resolution.path, timeout=settings.git_timeout_seconds)
        except worktree.NotAGitRepoError as exc:
            return error_envelope(
                "not_a_git_repo",
                redaction.sanitize_echo_prose(str(exc)),
                meta,
                plugin=plugin,
                details=ErrorDetail(field="workspace_root"),
            )
        except (worktree.NoCommitsError, worktree.WorktreeError) as exc:
            return error_envelope(
                "worktree_error", redaction.sanitize_echo_prose(str(exc))[:300], meta, plugin=plugin
            )
        except FileNotFoundError as exc:
            return error_envelope(
                "git_unavailable",
                redaction.sanitize_echo_prose(str(exc))[:300],
                meta,
                plugin=plugin,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return error_envelope(
                "worktree_error", redaction.sanitize_echo_prose(str(exc))[:300], meta, plugin=plugin
            )
    spec = RunSpec(
        backend=backend,
        kind=verb,
        tool=tool_name,
        cwd=resolution.path,
        workspace_source=resolution.source,
        roots_source=roots_source,
        host_name=host_name,
        timeout_seconds=timeout,
        model=model_v,
        reasoning_effort=effort,
        options=options,
        scope=scope,
        base=base,
        commit=commit,
        paths=paths,
        untracked=untracked,
        git_timeout=settings.git_timeout_seconds,
        max_input_bytes=settings.max_input_bytes,
        max_diff_bytes=settings.max_delegate_diff_bytes,
        max_output_bytes=settings.max_output_bytes,
        question=question,
        task=task,
        extra_context=extra_context,
        instructions_append=text,
        focus=focus,
    )
    return Prepared(spec=spec, meta=meta_for(spec), plugin=plugin)
