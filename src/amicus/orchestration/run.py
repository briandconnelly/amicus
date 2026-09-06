"""run_request: THE loop. Gather (review) → frame → site → RunRequest → validate → binary →
prepare → run → orphan sweep → inspect (every completed process) → classify or finalize →
delegate diff → the kind's envelope. Both the sync tools (via the worker) and the M2 async
jobs run exactly this."""

from __future__ import annotations

import os
from stat import S_ISREG
from typing import TYPE_CHECKING, Any

from pontonier.backend.protocol import RunOutcome, RunRequest, inspect_outcome
from pontonier.core import runtime

from amicus.errors import error_envelope, render_failure
from amicus.orchestration import finalize, prompts, review
from amicus.orchestration.isolation import SiteError, select_site
from amicus.request import meta_for
from amicus.schemas.envelope import ErrorDetail

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Callable

    from pontonier.backend.protocol import PreparedRun

    from amicus.plugin import BackendPlugin
    from amicus.request import RunSpec

MAX_ARTIFACT_BYTES = 1_000_000


def _read_bounded(path: str) -> str:
    """An artifact, or "" if it is anything but a plain small regular file. A delegate's
    answer file is written by a full-tool agent, so its path is model-controlled at read
    time: O_NOFOLLOW rejects a substituted symlink, O_NONBLOCK keeps a FIFO from blocking
    before fstat can reject it, and the cap bounds memory (ADR 0009)."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return ""
    try:
        st = os.fstat(fd)
        if not S_ISREG(st.st_mode) or st.st_size > MAX_ARTIFACT_BYTES:
            return ""
        raw = os.read(fd, MAX_ARTIFACT_BYTES)
    except OSError:
        return ""
    finally:
        os.close(fd)
    return raw.decode("utf-8", "replace")


def _read_artifacts(prepared: PreparedRun) -> dict[str, str]:
    texts: dict[str, str] = {}
    for name, path in prepared.artifact_paths.items():
        text = _read_bounded(path)
        if text:
            texts[name] = text
    return texts


def _site_error(exc: SiteError, meta: Any, plugin: BackendPlugin) -> dict[str, Any]:
    return error_envelope(
        exc.code,
        exc.detail,
        meta,
        plugin=plugin,
        details=ErrorDetail(field=exc.field) if exc.field else None,
        repair_alternative=exc.repair_alternative,
    )


async def run_request(
    spec: RunSpec,
    plugin: BackendPlugin,
    *,
    on_event: Callable[[str], None] | None = None,
    on_worktree_parent: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    meta = meta_for(spec)
    reasons: list[str] = []
    if spec.kind == "review_changes":
        gathered = review.gather(spec, meta, plugin)
        if isinstance(gathered, dict):
            return gathered
        reasons = review.coverage_reasons(spec.scope or "working_tree", gathered)
        if spec.focus and spec.focus.strip():
            # A focused pass is never a full review (per the `focus` parameter contract):
            # fold it into apply_coverage so a model `pass` is downgraded with a caveat.
            reasons.append("focused")
        prompt = prompts.review_prompt(
            spec.host_name,
            gathered.text,
            prompts.review_label(spec.scope or "working_tree", spec.base, spec.commit),
            prompts.review_caller_text(spec.focus, spec.extra_context),
        )
        schema: dict[str, Any] | None = prompts.REVIEW_OUTPUT_SCHEMA
    elif spec.kind == "consult":
        prompt = prompts.consult_prompt(spec.host_name, spec.question or "", spec.extra_context)
        schema = prompts.CONSULT_OUTPUT_SCHEMA
    else:
        prompt = prompts.delegate_prompt(spec.host_name, spec.task or "")
        schema = None

    try:
        with select_site(spec, plugin, on_worktree_parent) as site:
            if site.security_warnings:
                meta.security_warnings = list(site.security_warnings)
            request = RunRequest(
                kind=spec.kind,
                prompt=prompt,
                cwd=site.cwd,
                timeout_seconds=spec.timeout_seconds,
                schema=schema,
                model=spec.model,
                reasoning_effort=spec.reasoning_effort,
                budget_usd=spec.options.get("max_budget_usd"),
                config_mode=spec.options.get("config_mode"),
                access=spec.options.get("access"),
                isolation=spec.options.get("isolation"),
                sanitize_aliases=site.aliases,
                instructions_append=spec.instructions_append,
            )
            invalid = plugin.backend.validate_request(request)
            if invalid is not None:
                return render_failure(plugin, invalid, meta)
            if plugin.binary.resolve() is None:
                missing = RunOutcome(
                    run=runtime.CommandRun("", runtime.BINARY_NOT_FOUND, 127, 0, False)
                )
                finalize.stamp_run(meta, missing.run, ())
                return render_failure(
                    plugin, plugin.backend.classify_failure(missing, request), meta
                )
            async with plugin.backend.prepare(request) as prepared:
                run = await runtime.run_async(
                    list(prepared.argv),
                    cwd=prepared.cwd,
                    timeout_seconds=spec.timeout_seconds,
                    stdin_text=prepared.stdin_text,
                    env=prepared.env,
                    on_stdout_line=on_event,
                    max_output_bytes=spec.max_output_bytes,
                    orphan_marker=prepared.orphan_marker,
                )
                # Inside the context on purpose: staging is torn down on exit.
                artifact_texts = _read_artifacts(prepared)
            if plugin.contract.needs_orphan_sweep and prepared.orphan_marker:
                runtime.sweep_orphans(prepared.orphan_marker)
            outcome = RunOutcome(run=run, events=run.stdout, artifact_texts=artifact_texts)
            finalize.stamp_run(meta, run, prepared.dropped_flags)
            failure = inspect_outcome(plugin.backend, outcome, request)
            if failure is None and (run.exit_code != 0 or run.binary_missing or run.timed_out):
                failure = plugin.backend.classify_failure(outcome, request)
            if failure is not None:
                return render_failure(plugin, failure, meta)
            result = plugin.backend.finalize(outcome, request)
            diff = site.capture_diff() if spec.kind == "delegate" else None
            aliases = site.aliases
    except SiteError as exc:
        return _site_error(exc, meta, plugin)

    if spec.kind == "review_changes":
        return finalize.review_result(result, meta, reasons, plugin)
    if spec.kind == "consult":
        return finalize.consult_result(result, meta)
    return finalize.delegate_result(
        result, meta, diff=diff or "", aliases=aliases, max_diff_bytes=spec.max_diff_bytes
    )
