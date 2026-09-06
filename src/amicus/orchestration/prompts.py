"""Host identity, the framings (pontonier's, byte-for-byte for a named host), the prompt
builders, and the strict structured-output schemas the model must satisfy."""

from __future__ import annotations

from typing import Any

from pontonier.conventions import prompts as _pp
from pontonier.core import redaction

NEUTRAL_HOST_NAME = "Caller"
HOST_DISPLAY_NAMES: dict[str, str] = {
    "claude-code": "Claude Code",
    "claude code": "Claude Code",
    "claude": "Claude Code",
    "codex": "Codex",
    "codex-cli": "Codex",
    "codex cli": "Codex",
    "kimi": "Kimi",
    "kimi-code": "Kimi",
    "kimi code": "Kimi",
}
_HOST_NAME_MAX_CHARS = 64


def host_display_name(client_name: str | None, override: str | None) -> str:
    """AMICUS_HOST_NAME override → normalized handshake-era clientInfo.name → neutral."""
    if override and override.strip():
        return override.strip()[:_HOST_NAME_MAX_CHARS]
    if not client_name or not client_name.strip():
        return NEUTRAL_HOST_NAME
    key = client_name.strip().lower()
    if key in HOST_DISPLAY_NAMES:
        return HOST_DISPLAY_NAMES[key]
    shown = redaction.sanitize_echo(client_name.strip())[:_HOST_NAME_MAX_CHARS]
    return shown or NEUTRAL_HOST_NAME


def consult_prompt(host_name: str, question: str, extra_context: str | None) -> str:
    return _pp.build_consult_prompt(_pp.framings(host_name).consult, question, extra_context or "")


def review_prompt(
    host_name: str, diff_text: str, scope_label: str, extra_context: str | None
) -> str:
    return _pp.build_review_prompt(
        _pp.framings(host_name).review, diff_text, scope_label, extra_context or ""
    )


def review_caller_text(focus: str | None, extra_context: str | None) -> str | None:
    """Fold `focus` into the text that goes in review_prompt's `extra_context` slot, so
    focus rides inside the same UNTRUSTED caller-supplied framing ("narrows focus only")
    as extra_context, without changing review_prompt's signature."""
    focus_line = f"Focus this review on: {focus.strip()}" if focus and focus.strip() else None
    context = extra_context.strip() if extra_context and extra_context.strip() else None
    if focus_line is None and context is None:
        return None
    if focus_line is None:
        return context
    if context is None:
        return focus_line
    return f"{focus_line}\n\n{context}"


def delegate_prompt(host_name: str, task: str) -> str:
    return _pp.build_delegate_prompt(_pp.framings(host_name).delegate, task)


def review_label(scope: str, base: str | None, commit: str | None) -> str:
    if scope == "commit":
        return f"commit {commit}"
    if scope == "branch":
        return f"branch {base}...HEAD"
    return scope


# OpenAI strict structured outputs: every property required, additionalProperties false;
# optional members are nullable. The finding shape is amicus's `Finding` (schemas/results.py).
_FINDINGS_ARRAY_SCHEMA: dict[str, Any] = {
    "type": "array",
    "items": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "title": {"type": "string"},
            "severity": {"type": "string", "enum": ["critical", "high", "medium", "low", "nit"]},
            "file": {"type": ["string", "null"]},
            "line": {"type": ["integer", "null"]},
            "evidence": {"type": ["string", "null"]},
            "suggestion": {"type": ["string", "null"]},
        },
        "required": ["title", "severity", "file", "line", "evidence", "suggestion"],
    },
}
_STR_ARRAY_SCHEMA: dict[str, Any] = {"type": "array", "items": {"type": "string"}}

REVIEW_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary": {"type": "string"},
        "verdict": {"type": "string", "enum": ["pass", "concerns", "fail", "unknown"]},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "findings": _FINDINGS_ARRAY_SCHEMA,
        "questions": _STR_ARRAY_SCHEMA,
        "assumptions": _STR_ARRAY_SCHEMA,
        "next_steps": _STR_ARRAY_SCHEMA,
    },
    "required": [
        "summary",
        "verdict",
        "confidence",
        "findings",
        "questions",
        "assumptions",
        "next_steps",
    ],
}
CONSULT_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary": {"type": "string"},
        "findings": _FINDINGS_ARRAY_SCHEMA,
        "questions": _STR_ARRAY_SCHEMA,
        "assumptions": _STR_ARRAY_SCHEMA,
        "next_steps": _STR_ARRAY_SCHEMA,
    },
    "required": ["summary", "findings", "questions", "assumptions", "next_steps"],
}
