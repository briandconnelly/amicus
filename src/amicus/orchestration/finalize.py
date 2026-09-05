"""ExecResult → the success envelope per kind (ported from codex-in-claude
`orchestration.py`/`delegate.py`). Prose fields are sanitized (control characters stripped,
then redacted); machine fields (severity, file, verdict) reach the enum/coercion exactly as
the model wrote them so a control-split value degrades rather than being repaired."""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any, cast

from pontonier.core import redaction, worktree

from amicus.errors import error_envelope
from amicus.orchestration import review as review_mod
from amicus.schemas.envelope import ContextSummary, Usage, dump_success
from amicus.schemas.results import (
    ConsultResult,
    DelegateResult,
    Finding,
    RawResponse,
    ReviewResult,
)

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Iterable

    from pontonier.backend.protocol import ExecResult
    from pontonier.core.runtime import CommandRun

    from amicus.plugin import BackendPlugin
    from amicus.schemas.envelope import Meta

_PROSE_KEYS = ("summary", "questions", "assumptions", "next_steps")
_FINDING_PROSE_KEYS = ("title", "evidence", "suggestion")
_MODEL_FLAG = "--model"


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


def coerce_findings(raw: object) -> list[Finding]:
    if not isinstance(raw, list):
        return []
    findings: list[Finding] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            findings.append(Finding.model_validate(item))
        except Exception:
            continue
    return findings


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
        return dump_success(
            ConsultResult(
                summary=_summary_of(s),
                findings=coerce_findings(s.get("findings")),
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


def review_result(
    result: ExecResult, meta: Meta, reasons: list[str], plugin: BackendPlugin
) -> dict[str, Any]:
    """Strict: the verdict/findings ARE the product, so exit-0 output that ignored the
    schema is invalid_json / schema_violation, never a prose downgrade."""
    from amicus.backends.codex import normalize  # noqa: PLC0415  # generic JSON classification

    apply_exec(meta, result)
    status, parsed = normalize.classify_structured(result.answer)
    if status != "ok":
        preview = redaction.sanitize_echo_prose(result.answer).strip()[:300]
        tail = f" Raw output preview: {preview}" if preview else ""
        return error_envelope(
            status,
            "the backend exited 0 but did not return a schema-valid JSON object for the "
            f"review (the output schema appears to have been ignored).{tail}",
            meta,
            plugin=plugin,
        )
    s = cast("dict[str, Any]", _sanitize_structured(cast("dict", parsed)))
    verdict, confidence, summary = review_mod.apply_coverage(
        _enum(s.get("verdict"), ("pass", "concerns", "fail", "unknown"), "unknown"),
        _enum(s.get("confidence"), ("low", "medium", "high"), "medium"),
        _summary_of(s),
        reasons,
    )
    return dump_success(
        ReviewResult(
            summary=summary,
            verdict=cast("Any", verdict),
            confidence=cast("Any", confidence),
            review_status="completed",
            context_summary=meta.context_summary,
            findings=coerce_findings(s.get("findings")),
            questions=_str_list(s.get("questions")),
            assumptions=_str_list(s.get("assumptions")),
            next_steps=_str_list(s.get("next_steps")),
            raw_response=_raw(result, meta),
            meta=meta,
        )
    )


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
        # Bound first, then redact: a byte-cap cut can land mid-hunk, but a still-visible
        # `diff --git a/PATH b/PATH` header is enough for DiffRedactor to drop that file's
        # remainder, so a secret-looking file is scrubbed even out of a truncated diff.
        capped = _bound_diff(diff, meta, max_diff_bytes)
        bounded, meta.redacted_paths = redaction.redact(capped)
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
