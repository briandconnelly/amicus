#!/usr/bin/env python3
"""A stand-in `kimi` executable for end-to-end tests without spend (stdlib only).

Probes: `--version` prints `0.41.0`; `--help` lists every flag the contract sends or
refuses; `provider list --json` prints FAKE_KIMI_PROVIDERS (default: one provider and one
alias `k3` declaring low/medium/high). A `--prompt` run parses the pointer: it copies the
handshake prompt file to FAKE_KIMI_PROMPT_FILE, writes FAKE_KIMI_ANSWER (default: a
structured review/consult JSON) to the answer file the pointer names (write tier only),
optionally writes FAKE_KIMI_WRITE (a relative path) under cwd, prints FAKE_KIMI_EVENTS
(default: a version line, an assistant line carrying the answer, a resume hint) to stdout
and FAKE_KIMI_STDERR to stderr, sleeps FAKE_KIMI_SLEEP seconds, and exits FAKE_KIMI_EXIT
(default 0). FAKE_KIMI_ARGV_FILE gets one JSON line per invocation: the argv (binary
omitted) and the KIMI_MODEL_* environment."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

_HELP = """Usage: kimi [options]
  -V, --version                 output the version number
  -S, --session [id]            Resume a session.
  -c, --continue                Continue the previous session.
  -y, --yolo                    Start in Ask When Needed mode.
  --auto                        Start in Never Ask mode.
  -m, --model <model>           LLM model alias to use for this invocation.
  -p, --prompt <prompt>         Run one prompt non-interactively and print the response.
  --output-format <format>      Output format for prompt mode. (choices: "text", "stream-json")
  --skills-dir <dir>            Load skills from this directory instead of auto-discovered.
  --agent-file <path>           Load an agent definition from a Markdown file.
  --add-dir <dir>               Add an additional workspace directory for this session.
  --plan                        Start in plan mode.
  -h, --help                    Show help.
"""
_DEFAULT_PROVIDERS = json.dumps(
    {
        "providers": {
            "fake": {"apiKey": "sk-fake-not-a-secret", "baseUrl": "https://fake.invalid"}
        },
        "models": {
            "k3": {
                "displayName": "Kimi K3",
                "defaultEffort": "medium",
                "supportEfforts": ["low", "medium", "high"],
                "provider": "fake",
            }
        },
    }
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
_PROMPT_POINTER = re.compile(r"Read the file (\S+) and follow it exactly")
_ANSWER_POINTER = re.compile(r"write your final answer to (\S+?)\.?$")


def _record(argv: list[str]) -> None:
    path = os.environ.get("FAKE_KIMI_ARGV_FILE")
    if path:
        env = {k: v for k, v in os.environ.items() if k.startswith("KIMI_MODEL_")}
        with Path(path).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"argv": argv, "env": env}) + "\n")


def main(argv: list[str]) -> int:
    _record(argv)
    if argv == ["--version"]:
        print("0.41.0")
        return 0
    if argv == ["--help"]:
        print(_HELP)
        return 0
    if argv == ["provider", "list", "--json"]:
        print(os.environ.get("FAKE_KIMI_PROVIDERS", _DEFAULT_PROVIDERS))
        return 0
    if "--prompt" not in argv:
        print("error: unknown command", file=sys.stderr)
        return 2
    pointer = argv[argv.index("--prompt") + 1]
    prompt_match = _PROMPT_POINTER.search(pointer)
    if prompt_match and os.environ.get("FAKE_KIMI_PROMPT_FILE"):
        Path(os.environ["FAKE_KIMI_PROMPT_FILE"]).write_text(
            Path(prompt_match.group(1)).read_text(encoding="utf-8"), encoding="utf-8"
        )
    answer = os.environ.get("FAKE_KIMI_ANSWER", _DEFAULT_ANSWER)
    answer_match = _ANSWER_POINTER.search(pointer)
    if answer_match and answer:
        Path(answer_match.group(1)).write_text(answer, encoding="utf-8")
    write = os.environ.get("FAKE_KIMI_WRITE")
    if write:
        (Path.cwd() / write).write_text("written by fake kimi\n", encoding="utf-8")
    events = os.environ.get("FAKE_KIMI_EVENTS")
    if events is None:
        lines = ['{"role":"meta","type":"system.version","version":"0.41.0"}']
        if answer:
            lines.append(json.dumps({"role": "assistant", "content": answer}))
        lines.append('{"role":"meta","type":"session.resume_hint","session_id":"session-fake"}')
        events = "\n".join(lines) + "\n"
    time.sleep(float(os.environ.get("FAKE_KIMI_SLEEP", "0")))
    sys.stdout.write(events)
    sys.stdout.flush()
    stderr = os.environ.get("FAKE_KIMI_STDERR")
    if stderr:
        sys.stderr.write(stderr + "\n")
    return int(os.environ.get("FAKE_KIMI_EXIT", "0"))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
