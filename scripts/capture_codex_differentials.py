#!/usr/bin/env python
"""Capture codex-in-claude's hot-path behaviour into a fixture amicus's differential tests
compare against. Run INSIDE the sibling's checkout so its package and venv are used:

    cd /Users/bdc/projects/codex-in-claude && uv run --no-sync python \
        /Users/bdc/projects/amicus-wt-m1/scripts/capture_codex_differentials.py \
        > /Users/bdc/projects/amicus-wt-m1/tests/fixtures/codex_differentials.json

Zero spend: nothing here spawns codex. The argv cases pin the builder; the envelope cases
feed raw CommandRun/event fixtures through the sibling's finalizers and record a projection
of the envelope (codes, temporary, retry_after_ms, usage, session_id, summary, verdict).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

os.environ.pop("CODEX_IN_CLAUDE_EXTRA_ARGS", None)
for key in list(os.environ):
    if key.startswith("CODEX_IN_CLAUDE_"):
        del os.environ[key]

from codex_in_claude import binpath, cli_contract, codex, orchestration, prompts  # noqa: E402
from codex_in_claude.preflight import FlagSupport  # noqa: E402
from codex_in_claude.schemas import Coverage, Meta  # noqa: E402
from pontonier.core.runtime import BINARY_NOT_FOUND, TIMED_OUT, CommandRun  # noqa: E402

binpath._cache = "/CODEX"
ALL = FlagSupport(
    supported=frozenset(cli_contract.ALWAYS_SEND_FLAGS | set(cli_contract.HELP_GATED_FLAGS)),
    help_parsed=True,
)
NO_MODEL = FlagSupport(supported=frozenset(cli_contract.ALWAYS_SEND_FLAGS), help_parsed=True)

ARGV_CASES: dict[str, dict] = {
    "consult_default": dict(kind="consult", sandbox="read-only", schema=True),
    "consult_model_effort": dict(
        kind="consult",
        sandbox="read-only",
        schema=True,
        model="gpt-5.6-sol",
        reasoning_effort="high",
    ),
    "consult_empty_effort": dict(
        kind="consult", sandbox="read-only", schema=True, reasoning_effort=""
    ),
    "consult_instructions": dict(
        kind="consult", sandbox="read-only", schema=True, developer_instructions="Focus on locking."
    ),
    "review_default": dict(kind="review_changes", sandbox="read-only", schema=True),
    "review_ignore_rules": dict(
        kind="review_changes", sandbox="read-only", schema=True, isolation="ignore-rules"
    ),
    "delegate_default": dict(kind="delegate", sandbox="workspace-write", schema=False),
    "delegate_model": dict(
        kind="delegate", sandbox="workspace-write", schema=False, model="gpt-5.5"
    ),
    "consult_model_gated": dict(
        kind="consult", sandbox="read-only", schema=True, model="gpt-5.4", flags="no_model"
    ),
    "consult_extra_args": dict(
        kind="consult", sandbox="read-only", schema=True, extra_args=("-c", "model_provider=x")
    ),
}


def _argv_case(spec: dict) -> dict:
    cmd, dropped = codex.build_exec_command(
        cwd="/repo",
        sandbox=spec["sandbox"],
        isolation=spec.get("isolation", "inherit"),
        output_last_message_path="/TMP/last-message.txt",
        model=spec.get("model"),
        reasoning_effort=spec.get("reasoning_effort"),
        developer_instructions=spec.get("developer_instructions"),
        output_schema_path="/TMP/schema.json" if spec["schema"] else None,
        skip_git_repo_check=spec["kind"] == "consult",
        extra_args=tuple(spec.get("extra_args", ())),
        flag_support=NO_MODEL if spec.get("flags") == "no_model" else ALL,
    )
    return {
        "argv": cmd,
        "dropped": dropped,
        "request": {k: v for k, v in spec.items() if k != "flags"},
    }


def _meta(effort: str | None = None) -> Meta:
    return Meta(
        cwd="/repo",
        tier="consult",
        sandbox="read-only",
        isolation="inherit",
        model=None,
        reasoning_effort=effort,
        timeout_seconds=60,
        elapsed_ms=0,
    )


USAGE_EVENTS = (
    '{"type":"session.created","session_id":"sess-1"}\n'
    '{"type":"token_count","usage":{"input_tokens":100,"output_tokens":20,"cached_input_tokens":80}}\n'
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
ENVELOPE_CASES: dict[str, dict] = {
    "consult_structured": dict(
        kind="consult", stdout=USAGE_EVENTS, stderr="", exit_code=0, last_message=STRUCTURED
    ),
    "consult_prose": dict(
        kind="consult", stdout="", stderr="", exit_code=0, last_message="A plain answer."
    ),
    "consult_malformed_events": dict(
        kind="consult",
        stdout='{not json\n{"type":"x"}\n',
        stderr="",
        exit_code=0,
        last_message="ok",
    ),
    "review_structured": dict(
        kind="review_changes", stdout=USAGE_EVENTS, stderr="", exit_code=0, last_message=STRUCTURED
    ),
    "review_invalid_json": dict(
        kind="review_changes", stdout="", stderr="", exit_code=0, last_message="prose"
    ),
    "review_non_object": dict(
        kind="review_changes", stdout="", stderr="", exit_code=0, last_message="[1, 2]"
    ),
    "auth": dict(
        kind="consult",
        stdout="",
        stderr="Error: not logged in; please run `codex login`",
        exit_code=1,
        last_message=None,
    ),
    "rate_limit": dict(
        kind="consult",
        stdout="",
        stderr="429 Too Many Requests; Retry-After: 5",
        exit_code=1,
        last_message=None,
    ),
    "drift": dict(
        kind="consult",
        stdout="",
        stderr="error: unexpected argument '--zap' found",
        exit_code=2,
        last_message=None,
    ),
    "timeout": dict(
        kind="consult", stdout="", stderr=TIMED_OUT, exit_code=-9, last_message=None, timed_out=True
    ),
    "binary_missing": dict(
        kind="consult", stdout="", stderr=BINARY_NOT_FOUND, exit_code=127, last_message=None
    ),
    "effort_rejected": dict(
        kind="consult",
        stdout=(
            '{"type":"error","message":"[ReasoningEffortParam] [reasoning.effort] '
            "[invalid_enum_value] Invalid value: 'zz'\"}\n"
        ),
        stderr="",
        exit_code=1,
        last_message=None,
        effort="zz",
    ),
    "user_config_file": dict(
        kind="consult",
        stdout="",
        stderr=(
            "Error loading config.toml:\n"
            "/h/.codex/config.toml:3:1: unknown configuration field `zzz`\n"
        ),
        exit_code=1,
        last_message=None,
    ),
    "nonzero_generic": dict(
        kind="consult",
        stdout="",
        stderr="boom token=sk-" + "c" * 32,
        exit_code=3,
        last_message=None,
    ),
}


def _envelope_case(spec: dict) -> dict:
    run = CommandRun(
        spec["stdout"], spec["stderr"], spec["exit_code"], 12, spec.get("timed_out", False)
    )
    result = codex.CodexExecResult(
        run=run, last_message=spec["last_message"], events=spec["stdout"]
    )
    meta = _meta(spec.get("effort"))
    if spec["kind"] == "consult":
        env = orchestration.finalize_consult(result, meta=meta)
    else:
        cov = Coverage(
            status="complete",
            untracked_files_detected=0,
            untracked_files_included=0,
            untracked_files_omitted=0,
        )
        env = orchestration.finalize_review(result, meta=meta, coverage=cov)
    projection: dict = {"ok": env["ok"]}
    if env["ok"]:
        for key in ("summary", "verdict", "confidence", "review_status"):
            if key in env:
                projection[key] = env[key]
        projection["findings"] = env.get("findings", [])
    else:
        projection["error"] = {
            k: env["error"].get(k) for k in ("code", "temporary", "retry_after_ms")
        }
        projection["message_has_secret"] = "sk-" + "c" * 32 in env["error"]["message"]
    m = env["meta"]
    projection["meta"] = {
        "usage": m.get("usage"),
        "session_id": m.get("session_id"),
        "command_exit_code": m.get("command_exit_code"),
    }
    return {"input": spec, "sibling": projection}


def main() -> int:
    commit = subprocess.run(
        ["git", "log", "-1", "--format=%h"], capture_output=True, text=True, check=True
    ).stdout.strip()
    out = {
        "sibling_commit": commit,
        "argv": {name: _argv_case(spec) for name, spec in ARGV_CASES.items()},
        "prompts": {
            "consult": prompts.build_consult_prompt("Why?", "some context"),
            "review": prompts.build_review_prompt("DIFF TEXT", "working_tree", "author intent"),
            "delegate": prompts.build_delegate_prompt("Do the thing."),
            "developer_instructions": prompts.compose_developer_instructions("Focus on locking."),
        },
        "envelopes": {name: _envelope_case(spec) for name, spec in ENVELOPE_CASES.items()},
    }
    sys.stdout.write(json.dumps(out, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
