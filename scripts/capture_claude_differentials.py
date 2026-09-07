#!/usr/bin/env python
"""Capture claude-in-codex's hot-path behaviour into a fixture amicus's differential tests
compare against. Run INSIDE the sibling's checkout so its package and venv are used:

    cd /Users/bdc/projects/claude-in-codex && uv run --no-sync python \
        /Users/bdc/projects/amicus-wt-m4/scripts/capture_claude_differentials.py \
        > /Users/bdc/projects/amicus-wt-m4/tests/fixtures/claude_differentials.json

Zero spend: nothing here spawns claude. The argv cases pin the sibling's command builder with
its --append-system-prompt VALUE masked (amicus carries host-neutral guardrails; the guardrail
text itself is captured separately); the envelope cases feed raw stdout/stderr through the
sibling's normalize_envelope (zero-exit envelopes, any exit) or classify_failure (process
failures) and record a projection: ok, code, retryable, retry_after_ms, summary/verdict/
confidence, usage (mapped onto amicus's field names), session_id, and two leak checks.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

for key in list(os.environ):
    if key.startswith("CLAUDE_IN_CODEX_") or key in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        del os.environ[key]

from claude_in_codex import claude, cli_contract, config, normalize  # noqa: E402
from claude_in_codex.claude import ClaudeRun  # noqa: E402
from claude_in_codex.preflight import FlagSupport  # noqa: E402
from claude_in_codex.schemas import Meta  # noqa: E402

ALL = FlagSupport(
    supported=frozenset(set(cli_contract.ALWAYS_SEND_FLAGS) | set(cli_contract.HELP_GATED_FLAGS)),
    help_parsed=True,
)
NO_MODEL = FlagSupport(
    supported=frozenset(set(cli_contract.ALWAYS_SEND_FLAGS) | {"--effort", "--disallowed-tools"}),
    help_parsed=True,
)
SYSTEM_PROMPT_MASK = "<SYSTEM_PROMPT>"
SECRET = "sk-" + "c" * 32

ARGV_CASES: dict[str, dict] = {
    "consult_default": dict(
        config_mode="inherit", access="toolless", model=None, budget=1.0, effort="xhigh"
    ),
    "consult_model": dict(
        config_mode="inherit", access="toolless", model="sonnet", budget=1.0, effort="xhigh"
    ),
    "consult_model_gated": dict(
        config_mode="inherit",
        access="toolless",
        model="sonnet",
        budget=1.0,
        effort="xhigh",
        flags="no_model",
    ),
    "review_readonly": dict(
        config_mode="inherit", access="readonly", model=None, budget=1.0, effort="xhigh"
    ),
    "scoped": dict(config_mode="scoped", access="toolless", model=None, budget=1.0, effort="xhigh"),
    "safe": dict(config_mode="safe", access="toolless", model=None, budget=1.0, effort="xhigh"),
    "bare": dict(config_mode="bare", access="toolless", model=None, budget=1.0, effort="xhigh"),
    "budget_and_effort": dict(
        config_mode="inherit", access="toolless", model="opus", budget=0.5, effort="low"
    ),
}


def _mask(cmd: list[str]) -> list[str]:
    out: list[str] = []
    mask_next = False
    for tok in cmd:
        out.append(SYSTEM_PROMPT_MASK if mask_next else tok)
        mask_next = tok == "--append-system-prompt"
    return out


def _argv_case(spec: dict) -> dict:
    cmd, dropped = claude.build_command(
        "PROMPT (never on argv)",
        spec["config_mode"],
        spec["access"],
        spec["model"],
        spec["budget"],
        effort=spec["effort"],
        system_prompt_append=None,
        flag_support=NO_MODEL if spec.get("flags") == "no_model" else ALL,
    )
    return {
        "argv": _mask(cmd),
        "dropped": dropped,
        "request": {k: v for k, v in spec.items() if k != "flags"},
    }


def _meta() -> Meta:
    return Meta(
        cwd="/repo",
        config_mode="inherit",
        access="toolless",
        timeout_seconds=180,
        elapsed_ms=12,
        configured_max_budget_usd=1.0,
        effective_max_budget_usd=1.0,
    )


STRUCTURED = json.dumps(
    {
        "summary": "Looks fine",
        "verdict": "pass",
        "confidence": "high",
        "findings": [],
        "questions": [],
        "assumptions": [],
        "next_steps": [],
    }
)
USAGE = {
    "input_tokens": 100,
    "output_tokens": 50,
    "cache_read_input_tokens": 10,
    "cache_creation_input_tokens": 5,
}


def _env(result, *, subtype="success", is_error=False, **extra) -> str:
    body: dict = {"type": "result", "is_error": is_error, "result": result, "session_id": "sess-1"}
    if subtype is not None:
        body["subtype"] = subtype
    body.update(extra)
    return json.dumps(body)


# kind: which sibling tool renders the envelope; stdout/stderr/exit_code/timed_out: the run.
ENVELOPE_CASES: dict[str, dict] = {
    "consult_structured": dict(
        kind="consult",
        stdout=_env(STRUCTURED, total_cost_usd=0.0123, usage=USAGE),
        stderr="",
        exit_code=0,
    ),
    "consult_prose": dict(kind="consult", stdout=_env("A plain answer."), stderr="", exit_code=0),
    "consult_legacy_no_subtype": dict(
        kind="consult", stdout=_env("ok", subtype=None), stderr="", exit_code=0
    ),
    "review_structured": dict(
        kind="review_changes",
        stdout=_env(STRUCTURED, total_cost_usd=0.0123, usage=USAGE),
        stderr="",
        exit_code=0,
    ),
    "review_prose": dict(kind="review_changes", stdout=_env("prose"), stderr="", exit_code=0),
    "zero_exit_budget": dict(
        kind="consult",
        stdout=_env(
            "Budget stop threshold reached.",
            subtype="error_max_budget_usd",
            is_error=True,
            total_cost_usd=0.004,
            usage={"input_tokens": 20, "output_tokens": 0},
        ),
        stderr="",
        exit_code=0,
    ),
    "zero_exit_not_logged_in": dict(
        kind="consult",
        stdout=_env("Not logged in · Please run /login", subtype="error", is_error=True),
        stderr="",
        exit_code=0,
    ),
    "zero_exit_auth_required": dict(
        kind="consult",
        stdout=_env("Authentication required; run claude /login.", subtype="error", is_error=True),
        stderr="",
        exit_code=0,
    ),
    "zero_exit_api_key_invalid": dict(
        kind="consult",
        stdout=_env("Invalid API key.", subtype="error", is_error=True),
        stderr="",
        exit_code=0,
    ),
    "zero_exit_permission": dict(
        kind="consult",
        stdout=_env("Permission denied for tool Read.", subtype="error", is_error=True),
        stderr="",
        exit_code=0,
    ),
    "zero_exit_rate_limited": dict(
        kind="consult",
        stdout=_env("Rate limited; try later.", subtype="error", is_error=True),
        stderr="",
        exit_code=0,
    ),
    "zero_exit_is_error_subtype_success": dict(
        kind="consult",
        stdout=_env("Rate limited; try later.", subtype="success", is_error=True),
        stderr="",
        exit_code=0,
    ),
    "zero_exit_drift": dict(
        kind="consult",
        stdout=_env("error: unknown option '--effort'", subtype="error", is_error=True),
        stderr="",
        exit_code=0,
    ),
    "zero_exit_generic": dict(
        kind="consult",
        stdout=_env("the model declined to answer", subtype="error", is_error=False),
        stderr="",
        exit_code=0,
    ),
    "zero_exit_denials_no_answer": dict(
        kind="consult",
        stdout=_env("", permission_denials=[{"tool": "Bash"}]),
        stderr="",
        exit_code=0,
    ),
    "zero_exit_not_json": dict(kind="consult", stdout="not json at all", stderr="", exit_code=0),
    "zero_exit_non_object": dict(kind="consult", stdout="[1, 2]", stderr="", exit_code=0),
    "timeout": dict(kind="consult", stdout="", stderr="timeout", exit_code=-9, timed_out=True),
    "binary_missing": dict(kind="consult", stdout="", stderr="claude_not_found", exit_code=127),
    "nonzero_not_logged_in": dict(
        kind="consult", stdout="", stderr="Not logged in. Please run /login", exit_code=1
    ),
    "nonzero_invalid_key": dict(
        kind="consult", stdout="", stderr="Error: invalid API key", exit_code=1
    ),
    "nonzero_budget": dict(
        kind="consult", stdout="", stderr="stopped: budget exhausted", exit_code=1
    ),
    "nonzero_drift": dict(
        kind="consult", stdout="", stderr="error: unknown option '--zap'", exit_code=2
    ),
    "nonzero_secret": dict(kind="consult", stdout="", stderr=f"boom token={SECRET}", exit_code=3),
    "nonzero_secret_straddles_cut": dict(
        kind="consult", stdout="", stderr="x" * 280 + f" token={SECRET}", exit_code=2
    ),
}

_TOOL = {"consult": "claude_consult", "review_changes": "claude_review_changes"}


def _usage_projection(meta: dict) -> dict | None:
    """The sibling's meta.usage/meta.cost_usd mapped onto amicus's Usage field names."""
    usage = meta.get("usage")
    cost = meta.get("cost_usd")
    if usage is None and cost is None:
        return None
    usage = usage or {}
    return {
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "cost_usd": cost,
        "cached_input_tokens": usage.get("cache_read_input_tokens"),
        "cache_creation_input_tokens": usage.get("cache_creation_input_tokens"),
    }


def _envelope_case(spec: dict) -> dict:
    run = ClaudeRun(
        spec["stdout"], spec["stderr"], spec["exit_code"], 12, spec.get("timed_out", False)
    )
    meta = _meta()
    if run.exit_code == 0 and not run.timed_out:
        env = normalize.normalize_envelope(_TOOL[spec["kind"]], run.stdout, meta, detail="summary")
    else:
        info = claude.classify_failure(run, config_mode="inherit")
        env = {
            "ok": False,
            "error": {
                "code": info.code,
                "retryable": info.retryable,
                "retry_after_ms": info.retry_after_ms,
                "message": info.message,
            },
            "meta": {},
        }
    projection: dict = {"ok": env["ok"]}
    if env["ok"]:
        # The sibling's consult also carries verdict/confidence; amicus's consult is Q&A and
        # has neither, so only a review's are projected.
        review = spec["kind"] == "review_changes"
        keys = ("summary", "verdict", "confidence") if review else ("summary",)
        for key in keys:
            if key in env:
                projection[key] = env[key]
        projection["findings_count"] = len(env.get("findings", []))
        projection["session_id"] = (env.get("raw_response") or {}).get("session_id")
    else:
        error = env["error"]
        projection["error"] = {
            "code": error["code"],
            "temporary": bool(error.get("retryable", False)),
            "retry_after_ms": error.get("retry_after_ms"),
        }
        message = error["message"]
        projection["message_has_secret"] = SECRET in message
        projection["message_has_secret_prefix"] = "sk-cccc" in message
    projection["usage"] = _usage_projection(env.get("meta") or {})
    return {"input": spec, "sibling": projection}


def main() -> int:
    commit = subprocess.run(
        ["git", "log", "-1", "--format=%h"], capture_output=True, text=True, check=True
    ).stdout.strip()
    out = {
        "sibling_commit": commit,
        "argv": {name: _argv_case(spec) for name, spec in ARGV_CASES.items()},
        "guardrails": config.INDEPENDENT_CRITIC_PROMPT,
        "envelopes": {name: _envelope_case(spec) for name, spec in ENVELOPE_CASES.items()},
    }
    sys.stdout.write(json.dumps(out, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
