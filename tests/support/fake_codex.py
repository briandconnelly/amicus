#!/usr/bin/env python3
"""A stand-in `codex` executable for end-to-end tests without spend (stdlib only).

Probes: `--version` prints `codex-cli 0.153.4`; `login status` prints `Logged in using
ChatGPT`; `exec --help` lists every ALWAYS_SEND flag plus `--model`. An `exec` run reads the
prompt from stdin when the last token is `-`, writes FAKE_CODEX_ANSWER (default: a
structured review/consult JSON) to the `--output-last-message` path, optionally writes a
file under `--cd` (FAKE_CODEX_WRITE=relative/path), prints FAKE_CODEX_EVENTS (default: a
session + token_count JSONL) to stdout and FAKE_CODEX_STDERR to stderr, sleeps
FAKE_CODEX_SLEEP seconds, and exits FAKE_CODEX_EXIT (default 0). FAKE_CODEX_ARGV_FILE gets
one JSON line per invocation; FAKE_CODEX_STDIN_FILE receives the prompt."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

_ALWAYS = (
    "--sandbox --cd --json --output-last-message --skip-git-repo-check --ephemeral "
    "--ignore-user-config --ignore-rules --add-dir --output-schema --disable --strict-config"
)
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
_DEFAULT_EVENTS = (
    '{"type":"session.created","session_id":"sess-fake"}\n'
    '{"type":"token_count","usage":{"input_tokens":100,"output_tokens":20,"cached_input_tokens":80}}\n'
)


def main() -> int:
    argv = sys.argv[1:]
    if argv[:1] == ["--version"]:
        print("codex-cli 0.153.4")
        return 0
    if argv[:2] == ["login", "status"]:
        print("Logged in using ChatGPT")
        return 0
    if argv[:2] == ["exec", "--help"]:
        print(f"{_ALWAYS} --model")
        return 0
    argv_file = os.environ.get("FAKE_CODEX_ARGV_FILE")
    if argv_file:
        with Path(argv_file).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(argv) + "\n")
    prompt = sys.stdin.read() if argv and argv[-1] == "-" else ""
    stdin_file = os.environ.get("FAKE_CODEX_STDIN_FILE")
    if stdin_file:
        with Path(stdin_file).open("w", encoding="utf-8") as fh:
            fh.write(prompt)
    time.sleep(float(os.environ.get("FAKE_CODEX_SLEEP", "0")))
    cwd = argv[argv.index("--cd") + 1] if "--cd" in argv else Path.cwd()
    target = os.environ.get("FAKE_CODEX_WRITE")
    if target:
        with (Path(cwd) / target).open("w", encoding="utf-8") as fh:
            fh.write("changed\n")
    if "--output-last-message" in argv:
        with Path(argv[argv.index("--output-last-message") + 1]).open("w", encoding="utf-8") as fh:
            fh.write(os.environ.get("FAKE_CODEX_ANSWER", _DEFAULT_ANSWER))
    sys.stdout.write(os.environ.get("FAKE_CODEX_EVENTS", _DEFAULT_EVENTS))
    sys.stderr.write(os.environ.get("FAKE_CODEX_STDERR", ""))
    return int(os.environ.get("FAKE_CODEX_EXIT", "0"))


if __name__ == "__main__":
    raise SystemExit(main())
