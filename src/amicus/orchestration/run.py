"""run_request: THE loop. Gather (review; a critique with an attached scope) → frame (through
the plugin's framing hook) → site → RunRequest → validate → binary →
prepare → run → orphan sweep → inspect (every completed process) → classify or finalize →
delegate diff → the kind's envelope. Both the sync tools (via the worker) and the M2 async
jobs run exactly this."""

from __future__ import annotations

import dataclasses
import errno
import os
from stat import S_ISREG
from typing import TYPE_CHECKING, Any, NamedTuple

from amicus.errors import error_envelope, render_failure
from amicus.orchestration import finalize, prompts, review
from amicus.orchestration.isolation import SiteError, select_site
from amicus.request import meta_for
from amicus.schemas.envelope import ErrorDetail
from amicus.sdk.backend.protocol import RunOutcome, RunRequest, inspect_outcome
from amicus.sdk.core import runtime

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Callable

    from amicus.orchestration.gitdiff import DiffResult
    from amicus.plugin import BackendPlugin
    from amicus.request import RunSpec
    from amicus.schemas.envelope import Meta
    from amicus.schemas.results import Coverage
    from amicus.sdk.backend.protocol import PreparedRun

MAX_ARTIFACT_BYTES = 1_000_000


# Why amicus declined an artifact that WAS there (#162). An absent file is not here: the
# backend wrote nothing, which is a different fact from amicus refusing what it wrote.
REFUSED_OVERSIZE = "oversize"
REFUSED_NOT_REGULAR = "not_regular_file"
REFUSED_UNREADABLE = "unreadable"


class Refusal(NamedTuple):
    reason: str
    size: int | None = None  # known only where fstat said so


# What a refusal looks like on the wire: a fixed token and fixed prose, never the path, an
# errno or the exception text. `artifact_not_regular` stays apart from `artifact_unreadable`:
# one is a security invariant holding (ADR 0009), the other an operational read failure.
_REFUSAL_WIRE: dict[str, tuple[str, str, str | None]] = {
    REFUSED_OVERSIZE: (
        "artifact_oversize",
        "the backend answered, but its answer file exceeded amicus's "
        f"{MAX_ARTIFACT_BYTES:,}-byte read limit, so amicus did not read it.",
        None,
    ),
    REFUSED_NOT_REGULAR: (
        "artifact_not_regular",
        "the backend answered, but its answer file was not a regular file (a symlink, FIFO "
        "or device), so amicus refused to read it.",
        "inspect_and_retry",
    ),
    REFUSED_UNREADABLE: (
        "artifact_unreadable",
        "the backend answered, but amicus could not read its answer file.",
        "inspect_and_retry",
    ),
}
ANSWER_REFUSED_WARNING = (
    "amicus refused to read the backend's answer file (see ADR 0009); what is delivered "
    "comes from the backend's other output, not from that file."
)
DELEGATE_SUMMARY_UNAVAILABLE = (
    "The backend's summary could not be read: amicus refused its answer file. The diff below "
    "was captured from the worktree and is complete."
)


def _read_bounded(path: str) -> tuple[str, Refusal | None]:
    """(text, refusal): an artifact's text, or "" with why amicus would not read it. A
    delegate's answer file is written by a full-tool agent, so its path is model-controlled
    at read time: O_NOFOLLOW rejects a substituted symlink, O_NONBLOCK keeps a FIFO from
    blocking before fstat can reject it, and the cap bounds memory (ADR 0009)."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return "", None
    except OSError as exc:
        # ELOOP is what O_NOFOLLOW raises for a symlink at the final component.
        return "", Refusal(REFUSED_NOT_REGULAR if exc.errno == errno.ELOOP else REFUSED_UNREADABLE)
    try:
        st = os.fstat(fd)
        if not S_ISREG(st.st_mode):
            return "", Refusal(REFUSED_NOT_REGULAR)
        if st.st_size > MAX_ARTIFACT_BYTES:
            return "", Refusal(REFUSED_OVERSIZE, st.st_size)
        # `os.read` may return short, and the file can grow after fstat, so the size check
        # above is an early exit and this loop is the bound: one byte past the cap is
        # enough to know, and never more than that is held.
        chunks: list[bytes] = []
        remaining = MAX_ARTIFACT_BYTES + 1
        while remaining > 0 and (chunk := os.read(fd, remaining)):
            chunks.append(chunk)
            remaining -= len(chunk)
    except OSError:
        return "", Refusal(REFUSED_UNREADABLE)
    finally:
        os.close(fd)
    if remaining <= 0:
        return "", Refusal(REFUSED_OVERSIZE)  # it grew after fstat; its size is not known
    return b"".join(chunks).decode("utf-8", "replace"), None


def _read_artifacts(prepared: PreparedRun) -> tuple[dict[str, str], dict[str, Refusal]]:
    """(texts, refused): the artifacts that had text, and the ones amicus declined, by name."""
    texts: dict[str, str] = {}
    refused: dict[str, Refusal] = {}
    for name, path in prepared.artifact_paths.items():
        text, refusal = _read_bounded(path)
        if refusal is not None:
            refused[name] = refusal
        elif text:
            texts[name] = text
    return texts, refused


def _answer_refusal(prepared: PreparedRun, refused: dict[str, Refusal]) -> Refusal | None:
    """The refusal that matters: of an artifact the backend declared as carrying its ANSWER.
    Codex stages its input schema beside the answer, and refusing that says nothing about
    whether the backend answered."""
    return next((refused[name] for name in prepared.answer_artifacts if name in refused), None)


def _answer_unavailable(refusal: Refusal, meta: Any, plugin: BackendPlugin) -> dict[str, Any]:
    reason, message, next_step = _REFUSAL_WIRE[refusal.reason]
    oversize = refusal.reason == REFUSED_OVERSIZE
    return error_envelope(
        "answer_unavailable",
        message,
        meta,
        plugin=plugin,
        details=ErrorDetail(reason=reason),
        repair_next_step=next_step,
        repair_alternative=None
        if oversize
        else "amicus refused the backend's answer file; check the run before repeating it.",
        limit_bytes=MAX_ARTIFACT_BYTES if oversize else None,
        actual_bytes=refusal.size if oversize else None,
    )


def _site_error(exc: SiteError, meta: Any, plugin: BackendPlugin) -> dict[str, Any]:
    return error_envelope(
        exc.code,
        exc.detail,
        meta,
        plugin=plugin,
        details=ErrorDetail(field=exc.field) if exc.field else None,
        repair_alternative=exc.repair_alternative,
    )


def _compose(
    spec: RunSpec, meta: Meta, plugin: BackendPlugin
) -> tuple[str, dict[str, Any] | None, Coverage] | dict[str, Any]:
    """Gather (when the kind attaches a diff) and frame. Returns (prompt, schema, coverage),
    or a ready envelope when gathering ended the run before any spend. Only the review
    kinds read the coverage; consult and delegate get an unused `complete` one."""
    diff: DiffResult | None = None
    attaches_diff = spec.kind == "review_changes" or (
        spec.kind == "adversarial_review" and spec.scope is not None
    )
    if attaches_diff:
        gathered = review.gather(spec, meta, plugin)
        if isinstance(gathered, dict):
            return gathered
        diff = gathered
    gathered_text = diff.text if diff is not None else None
    # A focused pass is never a full review (per the `focus` parameter contract), so the
    # coverage records it and apply_coverage downgrades a model `pass` over it.
    coverage = review.build_coverage(
        spec.scope or "working_tree",
        diff,
        focused=spec.kind in ("review_changes", "adversarial_review") and review.is_focused(spec),
    )
    scope_label = prompts.review_label(spec.scope or "working_tree", spec.base, spec.commit)
    schema: dict[str, Any] | None
    if spec.kind == "review_changes":
        prompt = prompts.review_prompt(
            spec.host_name,
            gathered_text or "",
            scope_label,
            prompts.review_caller_text(spec.focus, spec.extra_context),
            plugin=plugin,
        )
        schema = prompts.REVIEW_OUTPUT_SCHEMA
    elif spec.kind == "adversarial_review":
        prompt = prompts.adversarial_prompt(
            spec.host_name,
            spec.target or "",
            spec.evidence,
            gathered_text,
            scope_label if gathered_text is not None else "",
            prompts.review_caller_text(spec.focus, spec.extra_context, noun="critique"),
            plugin=plugin,
        )
        schema = prompts.REVIEW_OUTPUT_SCHEMA
    elif spec.kind == "consult":
        prompt = prompts.consult_prompt(
            spec.host_name, spec.question or "", spec.extra_context, plugin=plugin
        )
        schema = prompts.CONSULT_OUTPUT_SCHEMA
    else:
        prompt = prompts.delegate_prompt(spec.host_name, spec.task or "", plugin=plugin)
        schema = None
    return prompt, schema, coverage


async def run_request(
    spec: RunSpec,
    plugin: BackendPlugin,
    *,
    on_event: Callable[[str], None] | None = None,
    on_worktree_parent: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    meta = meta_for(spec)
    composed = _compose(spec, meta, plugin)
    if isinstance(composed, dict):
        return composed
    prompt, schema, coverage = composed

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
                artifact_texts, refused = _read_artifacts(prepared)
            if plugin.contract.needs_orphan_sweep and prepared.orphan_marker:
                runtime.sweep_orphans(prepared.orphan_marker)
            outcome = RunOutcome(run=run, events=run.stdout, artifact_texts=artifact_texts)
            finalize.stamp_run(meta, run, prepared.dropped_flags)
            # Parse usage/session_id from the process output BEFORE classifying: a run
            # can fail (or, like kimi's empty_response, be reclassified from an exit-0
            # outcome) after the model already reported a session id or token count, and
            # that accounting belongs on the error envelope's meta too (ported from
            # moonbridge's runspace.apply_run_meta / orchestration._stamp_meta, both of
            # which stamp meta before checking whether the run succeeded). Both backends'
            # `finalize` tolerate an empty or malformed answer, so calling it unconditionally
            # is safe.
            result = plugin.backend.finalize(outcome, request)
            # The staged files are gone, but their paths are still here, and neither an
            # answer nor a failure that cites one may reach the result or the job record (#140).
            refs = finalize.artifact_refs(prepared.artifacts, prepared.staging_dir)
            finalize.apply_exec(meta, result)
            failure = inspect_outcome(plugin.backend, outcome, request)
            if failure is None and (run.exit_code != 0 or run.binary_missing or run.timed_out):
                failure = plugin.backend.classify_failure(outcome, request)
            # An answer file amicus refused is not the backend saying nothing (#162). A real
            # process failure is the more accurate account and wins; a clean exit that an
            # inspector called empty does not, since the refusal is WHY it looked empty.
            refusal = _answer_refusal(prepared, refused)
            clean_exit = run.exit_code == 0 and not run.binary_missing and not run.timed_out
            if failure is not None and not (refusal is not None and clean_exit):
                return render_failure(plugin, finalize.scrub_failure(failure, refs), meta)
            diff = site.capture_diff() if spec.kind == "delegate" else None
            aliases = site.aliases
            if refusal is not None:
                if (result.answer or "").strip():
                    # The backend's other channel carried a whole answer (kimi's stream).
                    meta.security_warnings.append(ANSWER_REFUSED_WARNING)
                elif spec.kind == "delegate" and (diff or "").strip():
                    # The diff comes from the worktree, not from the file, so it is still
                    # the honest primary result; say what is missing rather than hide it.
                    meta.security_warnings.append(ANSWER_REFUSED_WARNING)
                    result = dataclasses.replace(result, answer=DELEGATE_SUMMARY_UNAVAILABLE)
                else:
                    return _answer_unavailable(refusal, meta, plugin)
    except SiteError as exc:
        return _site_error(exc, meta, plugin)

    if spec.kind == "review_changes":
        return finalize.review_result(result, meta, coverage, plugin, refs)
    if spec.kind == "adversarial_review":
        return finalize.adversarial_result(result, meta, coverage, plugin, refs)
    if spec.kind == "consult":
        return finalize.consult_result(result, meta, refs)
    return finalize.delegate_result(
        result,
        meta,
        diff=diff or "",
        aliases=aliases,
        max_diff_bytes=spec.max_diff_bytes,
        refs=refs,
    )
