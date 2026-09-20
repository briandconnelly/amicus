"""ExecResult → the success envelope per kind (ported from codex-in-claude
`orchestration.py`/`delegate.py`). Prose fields are sanitized (control characters stripped,
then redacted); machine fields (severity, file, verdict) reach the enum/coercion exactly as
the model wrote them so a control-split value degrades rather than being repaired."""

from __future__ import annotations

import dataclasses
import json
import os
import re
from typing import TYPE_CHECKING, Any, cast, get_args

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
    ListDiagnostics,
    ListReason,
    ListsDiagnostics,
    RawResponse,
    ReviewResult,
    Severity,
)
from amicus.schemas.structured import classify_structured
from amicus.sdk.core import pathalias, redaction

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Iterable

    from amicus.plugin import BackendPlugin
    from amicus.schemas.envelope import Meta
    from amicus.schemas.results import Coverage
    from amicus.sdk.backend.protocol import ClassifiedFailure, ExecResult
    from amicus.sdk.core.runtime import CommandRun

_PROSE_KEYS = ("summary", "questions", "assumptions", "next_steps")
_LIST_KEYS = ("questions", "assumptions", "next_steps")
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


def _sanitize_structured(
    parsed: dict, refs: ArtifactRefs | None = None
) -> tuple[dict, frozenset[int]]:
    parsed, scrubbed = scrub_structured(parsed, refs or NO_ARTIFACTS)
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
    return out, scrubbed


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


# What a reference to one of amicus's own staged temp files becomes (#140). Kimi is handed its
# prompt as a file, so its answer can cite `<tmp>/amicus-kimi-handshake-XXXX/prompt.md:28`: a
# path deleted before the caller reads the result, a line number into amicus's framing, and
# the handshake location besides.
ARTIFACT_PLACEHOLDER = "[amicus temporary file]"
# What may follow a staged FILE's path and still be that file: `prompt.md:28` and a sentence's
# closing `prompt.md.` are; `prompt.md.bak` and `prompt.mdx` are other files.
_FILE_END = r"(?![\w\-]|\.\w|\\u[0-9a-fA-F]{4})"
# A staging DIRECTORY takes everything beneath it, whether or not `artifacts` listed it, and
# must not match a longer sibling name (`...-ab` inside `...-abc`). A `:` ends the path, so
# `other.md:3` keeps its line suffix as a listed file's does.
# A path separator as JSON may spell it: `/`, `\/` or `\u002f`. An answer that is prose around
# a JSON fragment is never decoded, so the text pass has to read these itself (#207). `\/` is
# what ordinary encoders emit; a path spelled wholly in `\uXXXX` inside prose is not chased.
_SLASH = r"(?:\\?/|\\u002[fF])"
# What follows a path may itself be escaped: `<dir>\u002ebak` is a longer sibling, and its
# next character is a backslash, which no guard written for decoded text refuses. The text
# pass declines any `\uXXXX` there; a whole-JSON answer is then judged decoded, exactly.
_UNDER_DIR = rf"(?:{_SLASH}[^\s\"'`<>)\]:]*|(?![\w.\-]|\\u[0-9a-fA-F]{{4}}))"


@dataclasses.dataclass(frozen=True)
class ArtifactRefs:
    """The strings that name one run's staged temp files. EXACT run-owned paths only: a
    prefix or temp-root heuristic would also clear a real workspace location that merely
    looks like one, which costs the caller more than a leaked dead path does."""

    pattern: re.Pattern[str] | None = None

    def scrub(self, text: str) -> str:
        return self.pattern.sub(ARTIFACT_PLACEHOLDER, text) if self.pattern else text

    def names(self, text: object) -> bool:
        return bool(self.pattern and isinstance(text, str) and self.pattern.search(text))


NO_ARTIFACTS = ArtifactRefs()


def artifact_refs(artifacts: tuple[str, ...], staging_dir: str | None = None) -> ArtifactRefs:
    """Each path as written and as resolved (macOS hands out /var temp paths that resolve
    under /private/var, and a backend may cite either), longest first so a directory's
    pattern never pre-empts a longer one."""

    def spellings(path: str) -> set[str]:
        return {path, os.path.realpath(path)} if path else set()

    dirs = {d.rstrip("/") for d in spellings(staging_dir or "")} - {""}
    files = {f for a in artifacts for f in spellings(a)}

    def spelled(path: str) -> str:
        return re.escape(path).replace("/", _SLASH)

    parts = [(d, spelled(d) + _UNDER_DIR) for d in dirs]
    parts += [(f, spelled(f) + _FILE_END) for f in files]
    if not parts:
        return NO_ARTIFACTS
    parts.sort(key=lambda part: len(part[0]), reverse=True)
    return ArtifactRefs(re.compile("|".join(pattern for _, pattern in parts)))


def _scrub_value(value: object, refs: ArtifactRefs) -> object:
    if isinstance(value, str):
        return refs.scrub(value)
    if isinstance(value, list):
        return [_scrub_value(v, refs) for v in value]
    if isinstance(value, dict):
        # Keys are the backend's text as much as values are (#207). Two keys can scrub to
        # one string, and a dict would keep the last and drop the rest, so later ones are
        # numbered instead.
        out: dict = {}
        for key, item in value.items():
            base = refs.scrub(key) if isinstance(key, str) else key
            new, count = base, 1
            while new in out:
                count += 1
                new = f"{base} ({count})"
            out[new] = _scrub_value(item, refs)
        return out
    return value


def scrub_structured(parsed: dict, refs: ArtifactRefs) -> tuple[dict, frozenset[int]]:
    """The parsed object with every artifact reference replaced, and the indexes of the
    findings that changed. It works on DECODED values, so a path the backend spelled
    `\\/tmp\\/x` or `\\u002ftmp` in its JSON is the same string here. The indexes travel
    beside the object rather than in it: the placeholder is ordinary text a backend could
    write itself, so its presence proves nothing. A `file` that named an artifact is cleared
    whole with its `line`, since a line without its file points nowhere."""
    if refs.pattern is None:
        return parsed, frozenset()
    out = cast("dict", _scrub_value(parsed, refs))
    raw_findings = parsed.get("findings")
    if not isinstance(raw_findings, list):
        return out, frozenset()
    touched: set[int] = set()
    for index, (before, after) in enumerate(zip(raw_findings, out["findings"], strict=True)):
        if before == after:
            continue
        touched.add(index)
        if isinstance(after, dict) and refs.names(before.get("file")):
            after["file"] = None
            after["line"] = None
    return out, frozenset(touched)


def scrub_answer(answer: str, refs: ArtifactRefs) -> str:
    """The raw answer, for `raw_response.text` and a prose summary. An answer that is one
    JSON object is judged by what it DECODES to and rebuilt from the scrubbed object, which
    covers every spelling JSON allows and numbers keys that collide; replacing text inside it
    instead can write one key twice, which is no longer the JSON it was (#207). Anything else
    is text, and gets the text pass with its escaped-solidus spellings."""
    if refs.pattern is None:
        return answer
    status, parsed = classify_structured(answer)
    if status != "ok" or not isinstance(parsed, dict):
        return refs.scrub(answer)
    scrubbed, _ = scrub_structured(parsed, refs)
    return answer if scrubbed == parsed else json.dumps(scrubbed, ensure_ascii=False)


def scrub_failure(failure: ClassifiedFailure, refs: ArtifactRefs) -> ClassifiedFailure:
    """A failed run's detail is built from the backend's stderr, stdout or error event,
    which can cite a staged path as readily as an answer can."""
    if refs.pattern is None:
        return failure
    details = failure.details
    return dataclasses.replace(
        failure,
        detail=refs.scrub(failure.detail),
        details=cast("dict", _scrub_value(details, refs)) if details is not None else None,
    )


def coerce_findings(
    raw: object, scrubbed: frozenset[int] = frozenset()
) -> tuple[list[Finding], FindingsDiagnostics | None]:
    """The backend's findings list, plus what could not be carried from it (issue #38).

    Returns diagnostics of None only when nothing deviated, so a caller can distinguish a
    genuinely clean list from one amicus failed to relay. The findings member is required
    by the output schema, so an absent one deviates (`missing_findings`) as surely as a
    present one that is not a list (`invalid_container`, which an explicit null reaches);
    both leave the count unknowable. Pass ABSENT, not None, for a key never there.
    `scrubbed` holds the indexes `scrub_structured` changed (#140)."""
    if raw is ABSENT:
        # The output schema REQUIRES findings, so an omitted member is not the backend
        # saying "none" -- it is the backend leaving amicus unable to know, and a verdict
        # it did supply must not stand over that silence.
        return [], FindingsDiagnostics(dropped=None, reasons=["missing_findings"])
    if not isinstance(raw, list):
        return [], FindingsDiagnostics(dropped=None, reasons=["invalid_container"])
    findings: list[Finding] = []
    seen: set[str] = set()
    dropped = 0
    for index, item in enumerate(raw):
        if index in scrubbed:
            seen.add("backend_artifact_reference_removed")
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


def coerce_str_list(raw: object) -> tuple[list[str], ListDiagnostics | None]:
    """One prose list (questions, assumptions, next_steps), plus what could not be carried
    from it (issue #52). The output schema requires each as an array of strings, so an
    absent member (`missing_member`, pass ABSENT) and a present non-list one
    (`invalid_container`, which an explicit null reaches) both deviate and leave the count
    unknowable. A number is kept as its string and said so (`number_stringified`); a bool,
    null, object or array entry is dropped and counted (`invalid_entry`), never guessed at
    - amicus does not decide what `{"step": ..., "why": ...}` reads as. Diagnostics are
    None only when nothing deviated, so `[]` still means the backend said none."""
    if raw is ABSENT:
        return [], ListDiagnostics(dropped=None, reasons=["missing_member"])
    if not isinstance(raw, list):
        return [], ListDiagnostics(dropped=None, reasons=["invalid_container"])
    items: list[str] = []
    seen: set[str] = set()
    dropped = 0
    for entry in raw:
        if isinstance(entry, str):
            items.append(entry)
        elif isinstance(entry, (int, float)) and not isinstance(entry, bool):
            items.append(str(entry))
            seen.add("number_stringified")
        else:
            dropped += 1
            seen.add("invalid_entry")
    if not seen:
        return items, None
    return items, ListDiagnostics(
        dropped=dropped, reasons=[r for r in get_args(ListReason) if r in seen]
    )


def coerce_prose_lists(
    structured: dict[str, Any],
) -> tuple[dict[str, list[str]], ListsDiagnostics | None]:
    """The three prose lists of a structured result and, when any deviated, one
    diagnostic per list; None when all three were clean, so the outer null means it."""
    lists: dict[str, list[str]] = {}
    diagnostics: dict[str, ListDiagnostics] = {}
    for key in _LIST_KEYS:
        lists[key], diagnostic = coerce_str_list(structured.get(key, ABSENT))
        if diagnostic is not None:
            diagnostics[key] = diagnostic
    return lists, ListsDiagnostics(**diagnostics) if diagnostics else None


def _raw(result: ExecResult, meta: Meta, refs: ArtifactRefs = NO_ARTIFACTS) -> RawResponse:
    return RawResponse(
        text=redaction.redact_text(scrub_answer(result.answer, refs)) or None,
        session_id=meta.session_id,
        model=meta.model,
    )


def consult_result(
    result: ExecResult, meta: Meta, refs: ArtifactRefs = NO_ARTIFACTS
) -> dict[str, Any]:
    apply_exec(meta, result)
    structured = result.structured
    if structured is not None:
        sanitized, scrubbed = _sanitize_structured(structured, refs)
        s = cast("dict[str, Any]", sanitized)
        findings, diagnostics = coerce_findings(s.get("findings", ABSENT), scrubbed)
        lists, lists_diagnostics = coerce_prose_lists(s)
        return dump_success(
            ConsultResult(
                summary=_summary_of(s),
                findings=findings,
                findings_diagnostics=diagnostics,
                lists_diagnostics=lists_diagnostics,
                questions=lists["questions"],
                assumptions=lists["assumptions"],
                next_steps=lists["next_steps"],
                raw_response=_raw(result, meta, refs),
                meta=meta,
            )
        )
    # Consult is Q&A: exit-0 prose is itself a valid answer, carried whole in summary.
    # But nothing was parsed from it, so the findings and the prose lists are not "clean"
    # - every required member was absent, and both diagnostics say so rather than letting
    # a null claim that the backend reported none (a Codex review finding on #52).
    findings, diagnostics = coerce_findings(ABSENT)
    lists, lists_diagnostics = coerce_prose_lists({})
    return dump_success(
        ConsultResult(
            summary=redaction.sanitize_echo_prose(scrub_answer(result.answer, refs)).strip()
            or "(the backend returned no message)",
            findings=findings,
            findings_diagnostics=diagnostics,
            lists_diagnostics=lists_diagnostics,
            questions=lists["questions"],
            assumptions=lists["assumptions"],
            next_steps=lists["next_steps"],
            raw_response=_raw(result, meta, refs),
            meta=meta,
        )
    )


# The fixed summary of a review whose answer amicus could not read as the requested object.
# Fixed text, never a digest of the answer: the answer itself is raw_response.text.
UNSTRUCTURED_SUMMARY = (
    "The backend answered, but not with one JSON object amicus could read, so nothing was "
    "parsed from it: verdict and confidence are unknown and findings is empty. Its whole "
    "answer is raw_response.text, returned at detail=full (on this call, or free from "
    "amicus_job_result for meta.job_id); read it as unverified prose."
)


def _parse_reviewed(
    result: ExecResult,
    meta: Meta,
    coverage: Coverage,
    plugin: BackendPlugin,
    noun: str,
    refs: ArtifactRefs = NO_ARTIFACTS,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Strict about SHAPE, lenient about FIELDS, and never discarding an answer. An empty
    answer is a hard invalid_json error: there is nothing to deliver. A non-empty answer
    that is not one readable JSON object is delivered, not discarded (#139): as
    `review_status: unstructured`, with the verdict and confidence unknown, nothing parsed,
    and the whole answer in raw_response.text. A JSON object that clears the shape bar but
    deviates field-by-field is coerced instead: each machine enum falls to its own honest
    floor, so a malformed object can never be delivered as a `pass`. This deliberately
    mirrors codex-in-claude, whose normalize.py says a missing verdict "defaults to unknown,
    which is honest, so it is intentionally accepted". Confidence answers to the same
    principle (issue #53): `low` is the lowest rating a backend can REPORT, so defaulting to
    it would manufacture a claim; `unknown` declines to make one. The folds downstream may
    still state `low` on their own basis. Returns (error_envelope, None) or (None, model
    fields)."""
    apply_exec(meta, result)
    if not (result.answer or "").strip():
        return (
            error_envelope(
                "invalid_json",
                f"the backend exited 0 but amicus read no answer for the {noun}: it returned "
                "none. (An answer file amicus refuses to read is answer_unavailable instead.)",
                meta,
                plugin=plugin,
            ),
            None,
        )
    status, parsed = classify_structured(result.answer, enclosed=True)
    if status != "ok":
        # Nothing was parsed, so no finding or prose list was carried, and both diagnostics
        # say so rather than a null claiming the backend reported none (#38, #52).
        findings, diagnostics = coerce_findings(ABSENT)
        lists, lists_diagnostics = coerce_prose_lists({})
        return None, {
            "summary": UNSTRUCTURED_SUMMARY,
            "verdict": "unknown",
            "confidence": "unknown",
            "review_status": "unstructured",
            "context_summary": meta.context_summary,
            "coverage": coverage,
            "findings": findings,
            "findings_diagnostics": diagnostics,
            "lists_diagnostics": lists_diagnostics,
            **lists,
            "raw_response": _raw(result, meta, refs),
            "meta": meta,
        }
    sanitized, scrubbed = _sanitize_structured(cast("dict", parsed), refs)
    s = cast("dict[str, Any]", sanitized)
    findings, diagnostics = coerce_findings(s.get("findings", ABSENT), scrubbed)
    verdict, confidence, summary = review_mod.apply_coverage(
        _enum(s.get("verdict"), ("pass", "concerns", "fail", "unknown"), "unknown"),
        _enum(s.get("confidence"), ("low", "medium", "high"), "unknown"),
        _summary_of(s),
        coverage,
    )
    verdict, confidence, summary = review_mod.apply_findings_loss(
        verdict, confidence, summary, diagnostics
    )
    # A lost prose entry is advice, not the review's correctness signal: no verdict is
    # computed from these lists, so their loss is disclosed and nothing is folded.
    lists, lists_diagnostics = coerce_prose_lists(s)
    return None, {
        "summary": summary,
        "verdict": verdict,
        "confidence": confidence,
        "review_status": "completed",
        "context_summary": meta.context_summary,
        "coverage": coverage,
        "findings": findings,
        "findings_diagnostics": diagnostics,
        "lists_diagnostics": lists_diagnostics,
        **lists,
        "raw_response": _raw(result, meta, refs),
        "meta": meta,
    }


def review_result(
    result: ExecResult,
    meta: Meta,
    coverage: Coverage,
    plugin: BackendPlugin,
    refs: ArtifactRefs = NO_ARTIFACTS,
) -> dict[str, Any]:
    error, fields = _parse_reviewed(result, meta, coverage, plugin, "review", refs)
    if error is not None:
        return error
    return dump_success(ReviewResult(**cast("dict[str, Any]", fields)))


def adversarial_result(
    result: ExecResult,
    meta: Meta,
    coverage: Coverage,
    plugin: BackendPlugin,
    refs: ArtifactRefs = NO_ARTIFACTS,
) -> dict[str, Any]:
    """The critique's envelope: the review shape (verdict, confidence, findings), the same
    strict/lenient rule, and the same coverage fold for an attached diff or a focus."""
    error, fields = _parse_reviewed(result, meta, coverage, plugin, "critique", refs)
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
    refs: ArtifactRefs = NO_ARTIFACTS,
    summary_override: str | None = None,
) -> dict[str, Any]:
    """`summary_override` is amicus's own account, given when the backend's answer could
    not be read (#162). It becomes the summary and nothing else: `raw_response.text` is the
    backend's words, so it stays null rather than carry amicus's."""
    apply_exec(meta, result)
    stat = _diffstat(diff)
    meta.context_summary = stat
    answer = scrub_answer(result.answer, refs) if result.answer else None
    last_message = pathalias.sanitize_prose(answer, aliases)
    summary_text = pathalias.sanitize_echo_prose(answer, aliases)
    summary = (
        summary_override or (summary_text or "").strip() or "(the backend returned no summary)"
    )
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
