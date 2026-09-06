#!/usr/bin/env python
"""Capture moonbridge's hot-path behaviour into a fixture amicus's differential tests
compare against. Run INSIDE the sibling's checkout so its package and venv are used:

    cd /Users/bdc/projects/moonbridge && uv run --no-sync python \
        /Users/bdc/projects/amicus-wt-m3/scripts/capture_kimi_differentials.py \
        > /Users/bdc/projects/amicus-wt-m3/tests/fixtures/kimi_differentials.json

Zero spend: nothing here spawns kimi. The argv cases pin the builder with the handshake
paths fixed at /TMP/; the envelope cases feed raw CommandRun/event fixtures through the
sibling's runspace finisher (failures, with the worktree sanitizer) and finalizers
(successes) and record a projection: codes, temporary, retry_after_ms, usage, session_id,
summary/verdict/findings, and four leak checks (secret, secret prefix, worktree path,
relative path).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

for key in list(os.environ):
    if key.startswith("MOONBRIDGE_"):
        del os.environ[key]

from moonbridge import cli_contract, kimi, orchestration, prompts, runspace  # noqa: E402
from moonbridge.backend import schema_instruction  # noqa: E402
from moonbridge.preflight import FlagSupport  # noqa: E402
from moonbridge.schemas import Coverage, Meta  # noqa: E402
from pontonier.core.runtime import BINARY_NOT_FOUND, TIMED_OUT, CommandRun  # noqa: E402

ALL = FlagSupport(
    supported=frozenset(set(cli_contract.ALWAYS_SEND_FLAGS) | set(cli_contract.HELP_GATED_FLAGS)),
    help_parsed=True,
)
NO_MODEL = FlagSupport(supported=frozenset(cli_contract.ALWAYS_SEND_FLAGS), help_parsed=True)
PATHS_RO = {"prompt": "/TMP/prompt.md", "agent": "/TMP/readonly-agent.md"}
PATHS_RW = {"prompt": "/TMP/prompt.md", "answer": "/TMP/answer.md"}
WT = "/wt/abc"
ALIASES = (WT,)
SECRET = "sk-" + "c" * 32

ARGV_CASES: dict[str, dict] = {
    "consult_default": dict(kind="consult", read_only=True),
    "consult_model": dict(kind="consult", read_only=True, model="k3"),
    "consult_model_gated": dict(kind="consult", read_only=True, model="k3", flags="no_model"),
    "consult_ignore_skills": dict(kind="consult", read_only=True, skills_dir="/TMP/empty-skills"),
    "review_default": dict(kind="review_changes", read_only=True),
    "delegate_default": dict(kind="delegate", read_only=False),
    "delegate_model": dict(kind="delegate", read_only=False, model="k3"),
}


def _argv_case(spec: dict) -> dict:
    paths = PATHS_RO if spec["read_only"] else PATHS_RW
    cmd, dropped = kimi.build_exec_command(
        cwd="/repo",
        sandbox=cli_contract.SANDBOX_READ_ONLY
        if spec["read_only"]
        else cli_contract.SANDBOX_WORKSPACE_WRITE,
        isolation="ignore-skills" if spec.get("skills_dir") else "inherit",
        prompt_pointer=kimi.build_prompt_pointer(paths, read_only=spec["read_only"]),
        model=spec.get("model"),
        agent_file_path=paths.get("agent"),
        skills_dir=spec.get("skills_dir"),
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


VERSION = '{"role":"meta","type":"system.version","version":"0.41.0"}\n'
RESUME = '{"role":"meta","type":"session.resume_hint","session_id":"session_abc"}\n'
USAGE = (
    '{"type":"token_count","usage":'
    '{"input_tokens":100,"output_tokens":20,"cached_input_tokens":80}}\n'
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


def _assistant(text: str) -> str:
    return json.dumps({"role": "assistant", "content": text}) + "\n"


ENVELOPE_CASES: dict[str, dict] = {
    "consult_structured": dict(
        kind="consult", events=VERSION + _assistant(STRUCTURED) + RESUME, stderr="", exit_code=0
    ),
    "consult_prose": dict(
        kind="consult",
        events=VERSION + _assistant("A plain answer.") + RESUME,
        stderr="",
        exit_code=0,
    ),
    "consult_usage": dict(
        kind="consult", events=VERSION + USAGE + _assistant("ok") + RESUME, stderr="", exit_code=0
    ),
    "consult_tool_calls_only": dict(
        kind="consult",
        events=VERSION + '{"role":"assistant","tool_calls":[{"id":"Read:0"}]}\n' + RESUME,
        stderr="",
        exit_code=0,
    ),
    "consult_empty_stream": dict(kind="consult", events=VERSION + RESUME, stderr="", exit_code=0),
    "consult_malformed_events": dict(
        kind="consult", events="{not json\n" + _assistant("ok"), stderr="", exit_code=0
    ),
    "review_structured": dict(
        kind="review_changes",
        events=VERSION + _assistant(STRUCTURED) + RESUME,
        stderr="",
        exit_code=0,
    ),
    "review_invalid_json": dict(
        kind="review_changes", events=VERSION + _assistant("prose") + RESUME, stderr="", exit_code=0
    ),
    "review_non_object": dict(
        kind="review_changes",
        events=VERSION + _assistant("[1, 2]") + RESUME,
        stderr="",
        exit_code=0,
    ),
    "auth": dict(kind="consult", events="", stderr="Error: 401 Unauthorized", exit_code=1),
    "rate_limit": dict(
        kind="consult", events="", stderr="429 Too Many Requests; retry-after: 5", exit_code=1
    ),
    "rate_limit_event": dict(
        kind="consult",
        events='{"type":"turn.failed","message":"rate limit reached; try again in 2 seconds"}\n',
        stderr="",
        exit_code=1,
    ),
    "drift": dict(kind="consult", events="", stderr="error: unknown option '--zap'", exit_code=1),
    "prompt_mode_drift": dict(
        kind="consult", events="", stderr="Cannot combine --prompt with --yolo.", exit_code=1
    ),
    "invalid_model": dict(
        kind="consult",
        events="",
        stderr='error: failed to run prompt: Model "nope" is not configured in config.toml.',
        exit_code=1,
    ),
    "unresolved_default_model": dict(
        kind="consult",
        events="",
        stderr="error: failed to run prompt: model foo does not resolve to a configured provider",
        exit_code=1,
    ),
    "model_prose_is_not_invalid_model": dict(
        kind="consult",
        events=_assistant("the alias does not resolve to a configured provider, per the docs"),
        stderr="",
        exit_code=3,
    ),
    "timeout": dict(kind="consult", events="", stderr=TIMED_OUT, exit_code=-9, timed_out=True),
    "binary_missing": dict(kind="consult", events="", stderr=BINARY_NOT_FOUND, exit_code=127),
    "nonzero_secret": dict(kind="consult", events="", stderr=f"boom token={SECRET}", exit_code=3),
    "nonzero_worktree_path": dict(
        kind="consult", events="", stderr="failed reading {WT}/src/a.py", exit_code=2
    ),
    "nonzero_secret_straddles_cut": dict(
        kind="consult", events="", stderr="x" * 280 + f" token={SECRET}", exit_code=2
    ),
}


def _envelope_case(spec: dict) -> dict:
    events = spec["events"]
    stderr = spec["stderr"].replace("{WT}", WT)
    run = CommandRun(events, stderr, spec["exit_code"], 12, spec.get("timed_out", False))
    result = kimi.KimiRunResult(
        run=run, last_message=kimi._resolve_answer(None, events), events=events
    )
    meta = _meta()
    # The real pipeline (runspace.run_isolated -> _invoke) always stamps process facts
    # (command_exit_code, usage, session_id) onto meta BEFORE `_finish` classifies a
    # failure. Calling `_finish` directly (as this fixture does, to reach it without a
    # real worktree) skips that stamp unless we replay it here — without this call every
    # failure case would fix command_exit_code at None, which the real sibling never does.
    runspace.apply_run_meta(meta, result)
    finished = runspace._finish(result, meta, diff="", aliases=ALIASES)
    if finished.error is not None:
        env = finished.error
    elif spec["kind"] == "consult":
        env = orchestration.finalize_consult(result, meta=meta)
    else:
        env = orchestration.finalize_review(result, meta=meta, coverage=Coverage(status="complete"))
    projection: dict = {"ok": env["ok"]}
    if env["ok"]:
        for key in ("summary", "verdict", "confidence", "review_status"):
            if key in env:
                projection[key] = env[key]
        projection["findings"] = env.get("findings", [])
    else:
        message = env["error"]["message"]
        projection["error"] = {
            k: env["error"].get(k) for k in ("code", "temporary", "retry_after_ms")
        }
        projection["message_has_secret"] = SECRET in message
        projection["message_has_secret_prefix"] = "sk-cccc" in message
        projection["message_has_worktree_path"] = WT in message
        projection["message_has_relative_path"] = "src/a.py" in message
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
    run_env = kimi.build_run_env("high")
    out = {
        "sibling_commit": commit,
        "argv": {name: _argv_case(spec) for name, spec in ARGV_CASES.items()},
        "agent_document": kimi.read_only_agent_document(),
        "schema_instruction": schema_instruction({"type": "object"}),
        "run_env": {k: v for k, v in run_env.items() if k.startswith("KIMI_MODEL_")},
        "prompts": {
            "consult": prompts.build_consult_prompt("Why?", "some context"),
            "review": prompts.build_review_prompt("DIFF TEXT", "working_tree", "author intent"),
            "delegate": prompts.build_delegate_prompt("Do the thing."),
        },
        "envelopes": {name: _envelope_case(spec) for name, spec in ENVELOPE_CASES.items()},
    }
    sys.stdout.write(json.dumps(out, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
