"""ExecResult → the success envelope per kind (ported from codex-in-claude
`orchestration.py`/`delegate.py`). Prose fields are sanitized (control characters stripped,
then redacted); machine fields (severity, file, verdict) reach the enum/coercion exactly as
the model wrote them so a control-split value degrades rather than being repaired."""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any, cast, get_args

from pontonier.core import redaction, worktree
from pydantic import ValidationError

from amicus.errors import error_envelope
from amicus.orchestration import review as review_mod
from amicus.schemas.envelope import ContextSummary, Usage, dump_success
from amicus.schemas.results import (
    AdversarialReviewResult,
    ConsultResult,
    DelegateResult,
    Finding,
    FindingReason,
    FindingsDiagnostics,
    RawResponse,
    ReviewResult,
    Severity,
)
from amicus.schemas.structured import classify_structured

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Iterable

    from pontonier.backend.protocol import ExecResult
    from pontonier.core.runtime import CommandRun

    from amicus.plugin import BackendPlugin
    from amicus.schemas.envelope import Meta

_PROSE_KEYS = ("summary", "questions", "assumptions", "next_steps")
_FINDING_PROSE_KEYS = ("title", "evidence", "suggestion")
_MODEL_FLAG = "--model"
_FINDING_FIELDS = frozenset(Finding.model_fields)


class _Absent:
    """A findings key that was never there, which `dict.get` cannot distinguish from one
    the backend set to null. The schema requires an array, so an explicit null is a
    deviation and says so; an absent key had nothing to deviate from."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "ABSENT"


ABSENT = _Absent()
_SEVERITIES = frozenset(get_args(Severity))


def stamp_run(meta: Meta, run: CommandRun, dropped_flags: Iterable[str]) -> None:
    """Process facts onto meta; a help-gated `--model` drop means the CLI's default ran."""
    meta.elapsed_ms = run.elapsed_ms
    meta.command_exit_code = run.exit_code
    meta.compat_warnings = list(dropped_flags)
    if _MODEL_FLAG in meta.compat_warnings:
        meta.model = None


def apply_exec(meta: Meta, result: ExecResult) -> None:
    meta.usage = Usage(**dataclasses.asdict(result.usage)) if result.usage is not None else None
    meta.session_id = result.session_id
    # A backend's own per-run warnings (Claude: the workspace defines hooks) join the site's;
    # idempotent, since the loop calls this before inspection and the kind's finalizer again.
    for warning in result.warnings:
        if warning not in meta.security_warnings:
            meta.security_warnings.append(warning)


def sanitize_prose_value(value: object) -> object:
    if isinstance(value, str):
        return redaction.sanitize_echo_prose(value)
    if isinstance(value, list):
        return [sanitize_prose_value(v) for v in value]
    return redaction.redact_tree(value)


def sanitize_finding(finding: object) -> object:
    if not isinstance(finding, dict):
        return redaction.redact_tree(finding)
    return {
        k: sanitize_prose_value(v) if k in _FINDING_PROSE_KEYS else redaction.redact_tree(v)
        for k, v in finding.items()
    }


def _sanitize_structured(parsed: dict) -> dict:
    out: dict = dict(parsed)
    for key in _PROSE_KEYS:
        if key in out:
            out[key] = sanitize_prose_value(out[key])
    findings = out.get("findings")
    if isinstance(findings, list):
        out["findings"] = [sanitize_finding(f) for f in findings]
    for key, value in out.items():
        if key in _PROSE_KEYS or (key == "findings" and isinstance(findings, list)):
            continue
        out[key] = redaction.redact_tree(value)
    return out


def _normalize_severity(item: dict) -> tuple[dict, bool]:
    """Case and surrounding space only. A backend that answers `HIGH` means `high`, and
    two of three backends are merely ASKED for the schema rather than held to it. Nothing
    else is touched: a control-split value still degrades rather than being repaired, and
    a synonym amicus would have to GUESS at (`P1`, `warning`) is not a severity."""
    value = item.get("severity")
    if not isinstance(value, str):
        return item, False
    normalized = value.strip().lower()
    if normalized == value or normalized not in _SEVERITIES:
        return item, False
    return {**item, "severity": normalized}, True


def coerce_findings(raw: object) -> tuple[list[Finding], FindingsDiagnostics | None]:
    """The backend's findings list, plus what could not be carried from it (issue #38).

    Returns diagnostics of None only when nothing deviated, so a caller can distinguish a
    genuinely clean list from one amicus failed to relay. An absent `findings` key is not
    a deviation; a present one that is not a list is - including an explicit null - and
    its loss is uncountable. Pass ABSENT, not None, for a key that was never there."""
    if raw is ABSENT:
        return [], None
    if not isinstance(raw, list):
        return [], FindingsDiagnostics(dropped=None, reasons=["invalid_container"])
    findings: list[Finding] = []
    seen: set[str] = set()
    dropped = 0
    for item in raw:
        if not isinstance(item, dict):
            dropped += 1
            seen.add("invalid_entry")
            continue
        candidate, normalized = _normalize_severity(item)
        if normalized:
            seen.add("severity_normalized")
        known = {k: v for k, v in candidate.items() if k in _FINDING_FIELDS}
        if len(known) != len(candidate):
            # An unknown key (`category`, `cwe`) is an ordinary backend addition; losing
            # the whole finding over one is the defect. Keep the finding, report the loss.
            seen.add("extra_fields_omitted")
        try:
            findings.append(Finding.model_validate(known))
        except ValidationError:
            dropped += 1
            seen.add("invalid_entry")
    if not seen:
        return findings, None
    return findings, FindingsDiagnostics(
        dropped=dropped, reasons=[r for r in get_args(FindingReason) if r in seen]
    )


def _summary_of(structured: dict) -> str:
    return (
        redaction.sanitize_echo_prose(str(structured.get("summary") or "")).strip()
        or "(no summary)"
    )


def _enum(value: object, allowed: tuple[str, ...], default: str) -> Any:
    return value if isinstance(value, str) and value in allowed else default


def _str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v) for v in value if isinstance(v, (str, int, float))]


def _raw(result: ExecResult, meta: Meta) -> RawResponse:
    return RawResponse(
        text=redaction.redact_text(result.answer) or None,
        session_id=meta.session_id,
        model=meta.model,
    )


def consult_result(result: ExecResult, meta: Meta) -> dict[str, Any]:
    apply_exec(meta, result)
    structured = result.structured
    if structured is not None:
        s = cast("dict[str, Any]", _sanitize_structured(structured))
        findings, diagnostics = coerce_findings(s.get("findings", ABSENT))
        return dump_success(
            ConsultResult(
                summary=_summary_of(s),
                findings=findings,
                findings_diagnostics=diagnostics,
                questions=_str_list(s.get("questions")),
                assumptions=_str_list(s.get("assumptions")),
                next_steps=_str_list(s.get("next_steps")),
                raw_response=_raw(result, meta),
                meta=meta,
            )
        )
    # Consult is Q&A: exit-0 prose is itself a valid answer.
    return dump_success(
        ConsultResult(
            summary=redaction.sanitize_echo_prose(result.answer).strip()
            or "(the backend returned no message)",
            raw_response=_raw(result, meta),
            meta=meta,
        )
    )


def _parse_reviewed(
    result: ExecResult, meta: Meta, reasons: list[str], plugin: BackendPlugin, noun: str
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Strict about SHAPE, lenient about FIELDS: exit-0 output that is not JSON, or not a
    JSON object, is a hard invalid_json/schema_violation error, never a prose downgrade.
    A JSON object that clears that bar but deviates field-by-field is coerced instead —
    verdict defaults to unknown and confidence to medium — so a malformed object can
    never be delivered as a `pass`. This deliberately mirrors codex-in-claude, whose
    normalize.py says a missing verdict "defaults to unknown, which is honest, so it is
    intentionally accepted". Returns (error_envelope, None) or (None, model fields)."""
    apply_exec(meta, result)
    status, parsed = classify_structured(result.answer)
    if status != "ok":
        preview = redaction.sanitize_echo_prose(result.answer).strip()[:300]
        tail = f" Raw output preview: {preview}" if preview else ""
        return (
            error_envelope(
                status,
                "the backend exited 0 but did not return a schema-valid JSON object for the "
                f"{noun} (the output schema appears to have been ignored).{tail}",
                meta,
                plugin=plugin,
            ),
            None,
        )
    s = cast("dict[str, Any]", _sanitize_structured(cast("dict", parsed)))
    findings, diagnostics = coerce_findings(s.get("findings", ABSENT))
    verdict, confidence, summary = review_mod.apply_coverage(
        _enum(s.get("verdict"), ("pass", "concerns", "fail", "unknown"), "unknown"),
        _enum(s.get("confidence"), ("low", "medium", "high"), "medium"),
        _summary_of(s),
        reasons,
    )
    verdict, confidence, summary = review_mod.apply_findings_loss(
        verdict, confidence, summary, diagnostics
    )
    return None, {
        "summary": summary,
        "verdict": verdict,
        "confidence": confidence,
        "review_status": "completed",
        "context_summary": meta.context_summary,
        "findings": findings,
        "findings_diagnostics": diagnostics,
        "questions": _str_list(s.get("questions")),
        "assumptions": _str_list(s.get("assumptions")),
        "next_steps": _str_list(s.get("next_steps")),
        "raw_response": _raw(result, meta),
        "meta": meta,
    }


def review_result(
    result: ExecResult, meta: Meta, reasons: list[str], plugin: BackendPlugin
) -> dict[str, Any]:
    error, fields = _parse_reviewed(result, meta, reasons, plugin, "review")
    if error is not None:
        return error
    return dump_success(ReviewResult(**cast("dict[str, Any]", fields)))


def adversarial_result(
    result: ExecResult, meta: Meta, reasons: list[str], plugin: BackendPlugin
) -> dict[str, Any]:
    """The critique's envelope: the review shape (verdict, confidence, findings), the same
    strict/lenient rule, and the same coverage fold for an attached diff or a focus."""
    error, fields = _parse_reviewed(result, meta, reasons, plugin, "critique")
    if error is not None:
        return error
    return dump_success(AdversarialReviewResult(**cast("dict[str, Any]", fields)))


def _diffstat(diff: str) -> ContextSummary:
    files = added = removed = 0
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            files += 1
        elif line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return ContextSummary(files_changed=files, lines_added=added, lines_removed=removed)


def _bound_diff(diff: str, meta: Meta, max_bytes: int) -> str:
    encoded = diff.encode("utf-8", "replace")
    if len(encoded) <= max_bytes:
        return diff
    meta.truncated = True
    meta.truncation_hint = (
        f"diff exceeded {max_bytes} bytes and was truncated; narrow the task to a smaller "
        "change, or raise AMICUS_MAX_DELEGATE_DIFF_BYTES to receive it whole"
    )
    return encoded[:max_bytes].decode("utf-8", "ignore")


def delegate_result(
    result: ExecResult,
    meta: Meta,
    *,
    diff: str,
    aliases: tuple[str, ...],
    max_diff_bytes: int,
) -> dict[str, Any]:
    apply_exec(meta, result)
    stat = _diffstat(diff)
    meta.context_summary = stat
    last_message = worktree.sanitize_prose(result.answer or None, aliases)
    summary_text = worktree.sanitize_echo_prose(result.answer or None, aliases)
    summary = (summary_text or "").strip() or "(the backend returned no summary)"
    if not diff.strip():
        summary = f"The backend made no changes. {summary}"
        bounded = ""
    else:
        redacted, meta.redacted_paths = redaction.redact(diff)
        bounded = _bound_diff(redacted, meta, max_diff_bytes)
    plural = lambda n, word: f"{n} {word}{'' if n == 1 else 's'}"  # noqa: E731
    diffstat = (
        f"{plural(stat.files_changed, 'file')} changed, "
        f"{plural(stat.lines_added, 'insertion')}(+), "
        f"{plural(stat.lines_removed, 'deletion')}(-)"
        if diff.strip()
        else None
    )
    return dump_success(
        DelegateResult(
            summary=summary,
            diff=bounded or None,
            diffstat=diffstat,
            raw_response=RawResponse(
                text=last_message, session_id=meta.session_id, model=meta.model
            ),
            next_steps=["Review the returned diff; apply it to your tree only if correct."],
            meta=meta,
        )
    )
