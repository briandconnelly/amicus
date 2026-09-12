"""Review-kind gathering (zero spend), the coverage disclosure, and the fold that reads it
(ported from codex-in-claude `orchestration.py`; issue #65 restored the disclosure)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, get_args

from pontonier.core import gitdiff, redaction

from amicus.errors import error_envelope
from amicus.schemas.envelope import ContextSummary, ErrorDetail, InvalidArgument, dump_success
from amicus.schemas.results import (
    AdversarialReviewResult,
    Coverage,
    CoverageReason,
    FindingsDiagnostics,
    RedactionSummary,
    ReviewResult,
    ReviewScope,
    Untracked,
)

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


def is_focused(spec: RunSpec) -> bool:
    return bool(spec.focus and spec.focus.strip())


def build_coverage(scope: str | None, diff: DiffResult | None, *, focused: bool) -> Coverage:
    """What the model was shown, from the gathered diff and the call's focus (issue #65).

    The one source for both the disclosure and apply_coverage's fold, so the two cannot
    disagree. `diff` is None only for a critique with no attached scope: nothing was
    gathered to omit, so only a focus can make it partial. The untracked counts are null
    outside working_tree, where untracked files are out of scope, and gather_diff reports
    `included <= detected` by construction (one enumeration, or none included)."""
    reasons: list[CoverageReason] = []
    detected: int | None = None
    included: int | None = None
    omitted: int | None = None
    redaction: RedactionSummary | None = None
    if diff is not None:
        if scope == "working_tree":
            detected = diff.untracked_detected or 0
            included = diff.untracked_included
            omitted = detected - included
            if omitted > 0:
                reasons.append("untracked_omitted")
            if diff.tree_changed_during_gather:
                reasons.append("tree_changed_during_gather")
        if diff.truncated:
            reasons.append("truncated")
        # The reason fires on any redaction signal, but the breakdown only from the split
        # fields: redaction that fell wholly past the byte cap leaves them empty while
        # redacted_paths still names the file, and no breakdown is invented for it.
        split = bool(diff.withheld_paths or diff.masked_paths or diff.inline_masks)
        if diff.redacted_paths or split:
            reasons.append("redacted")
        if split:
            redaction = RedactionSummary(
                withheld_paths=list(diff.withheld_paths),
                masked_paths=list(diff.masked_paths),
                inline_masks=diff.inline_masks,
            )
    if focused:
        reasons.append("focused")
    return Coverage(
        status="partial" if reasons else "complete",
        untracked_files_detected=detected,
        untracked_files_included=included,
        untracked_files_omitted=omitted,
        omission_reasons=reasons,
        redaction=redaction,
    )


def apply_coverage(
    verdict: str, confidence: str, summary: str, coverage: Coverage
) -> tuple[str, str, str]:
    """A model `pass` over partly reviewed code is delivered as unknown/low with a caveat;
    a concrete fail/concerns stands."""
    reasons = coverage.omission_reasons
    if reasons and verdict == "pass":
        return (
            "unknown",
            "low",
            f"Overall verdict is unknown because coverage is partial ({', '.join(reasons)}); "
            f"the model reported no blocking concerns in the reviewed portion. {summary}",
        )
    return verdict, confidence, summary


# Reasons that mean content was LOST, as opposed to carried in a reshaped form.
_REPRESENTATION_LOSS = frozenset({"invalid_entry", "invalid_container", "missing_findings"})


def apply_findings_loss(
    verdict: str, confidence: str, summary: str, diagnostics: FindingsDiagnostics | None
) -> tuple[str, str, str]:
    """A finding amicus could not carry may not be delivered as silence (issue #38).

    The opposite axis from `apply_coverage`: there the model did not see everything, here
    it did and amicus could not relay what it said. So this fold runs after that one and
    speaks for itself rather than joining its reasons. A `fail` or `concerns` stands, with
    its confidence intact - missing output does not refute a negative the model did
    reach. Anything else cannot be delivered as clean."""
    if diagnostics is None or not (_REPRESENTATION_LOSS & set(diagnostics.reasons)):
        return verdict, confidence, summary
    if verdict in ("fail", "concerns"):
        return verdict, confidence, summary
    lost = (
        f"{diagnostics.dropped} of the backend's findings could not be fully represented"
        if diagnostics.dropped
        else "the backend's findings could not be fully represented"
    )
    return (
        "unknown",
        "low",
        f"Overall verdict is unknown because {lost} "
        f"({', '.join(sorted(_REPRESENTATION_LOSS & set(diagnostics.reasons)))}); this result "
        f"cannot establish a clean review. {summary}",
    )


def _not_run(spec: RunSpec, meta: Meta, diff: DiffResult) -> dict[str, Any]:
    coverage = build_coverage(spec.scope, diff, focused=is_focused(spec))
    omitted = coverage.untracked_files_omitted or 0
    remedy = (
        'Re-run with untracked="include" to review them.'
        if spec.untracked == "exclude"
        else 'Re-run with untracked="include", or name them in paths, to review them.'
    )
    if omitted > 0:
        summary = (
            f"No reviewable changes were gathered for scope={spec.scope}, but {omitted} "
            f"untracked file(s) were detected and omitted. {remedy}"
        )
    else:
        summary = f"No changes to review for scope={spec.scope}."
    if spec.kind == "adversarial_review":
        # The critique's tail differs, but the untracked remedy does not: an omitted
        # untracked file is a change the caller can surface with one flag, so saying
        # "attach a scope that has changes" here would be actively misleading.
        critique_summary = (
            f"No reviewable changes were gathered for scope={spec.scope}, but {omitted} "
            "untracked file(s) were detected and omitted, so the critique did not run "
            f"(zero spend). {remedy} Or drop scope to critique the target alone."
            if omitted > 0
            else (
                f"No changes were gathered for scope={spec.scope}, so the critique did not run "
                "(zero spend). Drop scope to critique the target alone, or attach a scope that "
                "has changes."
            )
        )
        return dump_success(
            AdversarialReviewResult(
                summary=critique_summary,
                verdict="unknown",
                confidence="low",
                review_status="not_run",
                context_summary=meta.context_summary,
                coverage=coverage,
                meta=meta,
            )
        )
    return dump_success(
        ReviewResult(
            summary=summary,
            verdict="unknown",
            confidence="low",
            review_status="not_run",
            context_summary=meta.context_summary,
            coverage=coverage,
            meta=meta,
        )
    )


def gather(spec: RunSpec, meta: Meta, plugin: BackendPlugin) -> DiffResult | dict[str, Any]:
    """Gather + validate the diff BEFORE any model call. Returns the DiffResult, or a ready
    envelope: a structured error (zero spend) or the `not_run` success for an empty scope.
    The gathered diff has its own max_input_bytes budget (truncated with meta.truncated,
    not rejected), separate from the caller-input sum enforced in tools/_prepare.py; both
    mirror codex-in-claude, which limits each input independently rather than sharing one
    budget."""
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
