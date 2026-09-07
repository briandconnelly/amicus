#!/usr/bin/env python3
"""A stand-in `claude` executable for end-to-end tests without spend (stdlib only).

Probes: `--version` prints `2.1.263 (Claude Code)`; `--help` lists every flag the contract
sends (minus FAKE_CLAUDE_HELP_OMIT); `auth status --text` exits FAKE_CLAUDE_AUTH_EXIT (default
0) printing a non-identifying line. A `-p` run reads the whole prompt from stdin, copies it to
FAKE_CLAUDE_PROMPT_FILE, prints FAKE_CLAUDE_STDOUT verbatim if set, else a success envelope
whose `result` is FAKE_CLAUDE_ANSWER (default: a structured review JSON) with a session id,
cost and usage; prints FAKE_CLAUDE_STDERR to stderr, sleeps FAKE_CLAUDE_SLEEP seconds, and
exits FAKE_CLAUDE_EXIT (default 0). FAKE_CLAUDE_ARGV_FILE gets one JSON line per invocation:
the argv (binary omitted), whether ANTHROPIC_API_KEY was in the environment, and the cwd."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

_FLAGS = [
    "-p, --print",
    "--output-format <format>",
    "--no-chrome",
    "--append-system-prompt <prompt>",
    "--max-budget-usd <amount>",
    "--no-session-persistence",
    '--tools <tools...>  Use "" to disable all tools',
    "--disallowedTools, --disallowed-tools <tools...>",
    "--strict-mcp-config",
    "--mcp-config <configs...>",
    "--setting-sources <sources>",
    "--safe-mode",
    "--bare",
    "--effort <level>  (low, medium, high, xhigh, max)",
    "--model <model>",
    "-v, --version",
    "-h, --help",
]
_DEFAULT_ANSWER = json.dumps(
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


def _help() -> str:
    omit = {f for f in os.environ.get("FAKE_CLAUDE_HELP_OMIT", "").split(",") if f}
    lines = [line for line in _FLAGS if not any(o in line for o in omit)]
    body = "\n".join(f"  {flag}" for flag in lines)
    return f"Usage: claude [options] [command] [prompt]\n\nOptions:\n{body}\n"


def _record(argv: list[str]) -> None:
    path = os.environ.get("FAKE_CLAUDE_ARGV_FILE")
    if path:
        record = {
            "argv": argv,
            "has_api_key": "ANTHROPIC_API_KEY" in os.environ,
            "cwd": str(Path.cwd()),
        }
        with Path(path).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")


def main(argv: list[str]) -> int:
    _record(argv)
    if argv == ["--version"]:
        print("2.1.263 (Claude Code)")
        return 0
    if argv == ["--help"]:
        sys.stdout.write(_help())
        return 0
    if argv == ["auth", "status", "--text"]:
        code = int(os.environ.get("FAKE_CLAUDE_AUTH_EXIT", "0"))
        print("Logged in" if code == 0 else "Not logged in")
        return code
    if "-p" not in argv:
        print("error: unknown command", file=sys.stderr)
        return 2
    prompt = sys.stdin.read()
    if os.environ.get("FAKE_CLAUDE_PROMPT_FILE"):
        Path(os.environ["FAKE_CLAUDE_PROMPT_FILE"]).write_text(prompt, encoding="utf-8")
    stdout = os.environ.get("FAKE_CLAUDE_STDOUT")
    if stdout is None:
        stdout = json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "result": os.environ.get("FAKE_CLAUDE_ANSWER", _DEFAULT_ANSWER),
                "session_id": "sess-fake",
                "total_cost_usd": 0.0123,
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "cache_read_input_tokens": 10,
                    "cache_creation_input_tokens": 5,
                },
            }
        )
    time.sleep(float(os.environ.get("FAKE_CLAUDE_SLEEP", "0")))
    sys.stdout.write(stdout)
    sys.stdout.flush()
    stderr = os.environ.get("FAKE_CLAUDE_STDERR")
    if stderr:
        sys.stderr.write(stderr + "\n")
    return int(os.environ.get("FAKE_CLAUDE_EXIT", "0"))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
