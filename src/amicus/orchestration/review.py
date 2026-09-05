"""Review-kind gathering (zero spend) and the coverage fold (ported from codex-in-claude
`orchestration.py`; the Coverage object itself is not part of the amicus surface)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, get_args

from pontonier.core import gitdiff, redaction

from amicus.errors import error_envelope
from amicus.schemas.envelope import ContextSummary, ErrorDetail, InvalidArgument, dump_success
from amicus.schemas.results import ReviewResult, ReviewScope, Untracked

if TYPE_CHECKING:  # pragma: no cover
    from pontonier.core.gitdiff import DiffResult

    from amicus.plugin import BackendPlugin
    from amicus.request import RunSpec
    from amicus.schemas.envelope import Meta

_GITDIFF_ERRORS: dict[type, tuple[str, str | None]] = {
    gitdiff.InvalidScopeError: ("invalid_scope", "scope"),
    gitdiff.InvalidBaseError: ("invalid_base", "base"),
    gitdiff.InvalidCommitError: ("invalid_commit", "commit"),
    gitdiff.InvalidPathsError: ("invalid_paths", "paths"),
    gitdiff.InvalidUntrackedError: ("invalid_arguments", "untracked"),
    gitdiff.NotAGitRepoError: ("not_a_git_repo", "workspace_root"),
    gitdiff.GitUnavailableError: ("git_unavailable", None),
}
GITDIFF_EXCEPTIONS = (*_GITDIFF_ERRORS.keys(), RuntimeError)


def gitdiff_error(exc: Exception, meta: Meta, plugin: BackendPlugin) -> dict[str, Any]:
    code, offending = _GITDIFF_ERRORS.get(type(exc), ("git_unavailable", None))
    allowed = list(get_args(ReviewScope)) if code == "invalid_scope" else None
    if code == "invalid_arguments" and offending:
        # The exception text embeds the rejected value; InvalidArgument never echoes one.
        values = list(get_args(Untracked))
        reason = f"{offending} must be one of " + ", ".join(repr(v) for v in sorted(values)) + "."
        return error_envelope(
            code,
            reason[:300],
            meta,
            plugin=plugin,
            invalid_arguments=[
                InvalidArgument(field=offending, reason=reason, allowed_values=values)
            ],
        )
    details = (
        ErrorDetail(field=offending, allowed_values=allowed) if (offending or allowed) else None
    )
    return error_envelope(
        code, redaction.sanitize_echo_prose(str(exc))[:300], meta, plugin=plugin, details=details
    )


def coverage_reasons(scope: str, diff: DiffResult) -> list[str]:
    """Why the model did not see everything in scope, in a fixed order."""
    reasons: list[str] = []
    if scope == "working_tree":
        omitted = max(0, (diff.untracked_detected or 0) - diff.untracked_included)
        if omitted > 0:
            reasons.append("untracked_omitted")
        if diff.tree_changed_during_gather:
            reasons.append("tree_changed_during_gather")
    if diff.truncated:
        reasons.append("truncated")
    if diff.redacted_paths or diff.withheld_paths or diff.masked_paths or diff.inline_masks:
        reasons.append("redacted")
    return reasons


def apply_coverage(
    verdict: str, confidence: str, summary: str, reasons: list[str]
) -> tuple[str, str, str]:
    """A model `pass` over partly reviewed code is delivered as unknown/low with a caveat;
    a concrete fail/concerns stands."""
    if reasons and verdict == "pass":
        return (
            "unknown",
            "low",
            f"Overall verdict is unknown because coverage is partial ({', '.join(reasons)}); "
            f"the model reported no blocking concerns in the reviewed portion. {summary}",
        )
    return verdict, confidence, summary


def _not_run(spec: RunSpec, meta: Meta, diff: DiffResult) -> dict[str, Any]:
    omitted = max(0, (diff.untracked_detected or 0) - diff.untracked_included)
    if omitted > 0:
        remedy = (
            'Re-run with untracked="include" to review them.'
            if spec.untracked == "exclude"
            else 'Re-run with untracked="include", or name them in paths, to review them.'
        )
        summary = (
            f"No reviewable changes were gathered for scope={spec.scope}, but {omitted} "
            f"untracked file(s) were detected and omitted. {remedy}"
        )
    else:
        summary = f"No changes to review for scope={spec.scope}."
    return dump_success(
        ReviewResult(
            summary=summary,
            verdict="unknown",
            confidence="low",
            review_status="not_run",
            context_summary=meta.context_summary,
            meta=meta,
        )
    )


def gather(spec: RunSpec, meta: Meta, plugin: BackendPlugin) -> DiffResult | dict[str, Any]:
    """Gather + validate the diff BEFORE any model call. Returns the DiffResult, or a ready
    envelope: a structured error (zero spend) or the `not_run` success for an empty scope."""
    extra_bytes = len((spec.extra_context or "").encode("utf-8"))
    if extra_bytes > spec.max_input_bytes:
        return error_envelope(
            "input_too_large",
            f"extra_context exceeds {spec.max_input_bytes} bytes.",
            meta,
            plugin=plugin,
            details=ErrorDetail(field="extra_context"),
            limit_bytes=spec.max_input_bytes,
            actual_bytes=extra_bytes,
            repair_alternative="Trim extra_context or raise AMICUS_MAX_INPUT_BYTES.",
        )
    try:
        diff = gitdiff.gather_diff(
            spec.cwd,
            spec.scope or "working_tree",
            base=spec.base,
            commit=spec.commit,
            paths=spec.paths,
            untracked=spec.untracked,
            timeout=spec.git_timeout,
            max_bytes=spec.max_input_bytes,
        )
    except GITDIFF_EXCEPTIONS as exc:  # ty: ignore[invalid-exception-caught]
        return gitdiff_error(exc, meta, plugin)
    meta.context_summary = ContextSummary(
        files_changed=diff.summary.files_changed,
        lines_added=diff.summary.lines_added,
        lines_removed=diff.summary.lines_removed,
    )
    meta.redacted_paths = list(diff.redacted_paths)
    meta.truncated = diff.truncated
    meta.truncation_hint = diff.truncation_hint
    if diff.summary.files_changed == 0 and not diff.text.strip():
        return _not_run(spec, meta, diff)
    return diff
