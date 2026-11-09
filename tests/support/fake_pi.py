#!/usr/bin/env python3
"""A stand-in `pi` executable for end-to-end tests without spend (stdlib only).

Probes, matched on the exact argv amicus sends:

- `--version` prints FAKE_PI_VERSION (default `1.5.0`).
- `--help <suppression flags>` prints FAKE_PI_HELP_FILE, else the verbatim 1.5.0 capture
  `pi-help.txt` beside this script (the `fake_pi` fixture copies it there).
- `--list-models [term] <suppression flags>` prints FAKE_PI_MODELS (default: the header and
  one `openrouter moonshotai/kimi-k3` row), keeping only rows whose joined `provider/model`
  contains the term, and pi's `No models matching` line when none does.
- `auth check --json --no-refresh --model <m>` prints FAKE_PI_AUTH, the raw JSON line
  (default `{"status":"ready","provider":"openrouter","authType":"api_key"}`), and exits 0
  for ready, 1 for not_ready and 2 otherwise.

A `-p` run reads stdin, copies it to FAKE_PI_STDIN_FILE and appends its argv (binary omitted)
as one JSON line to FAKE_PI_ARGV_FILE when set, writes FAKE_PI_WRITE (a relative path) under
cwd when set, prints FAKE_PI_EVENTS or a pi 1.5.0 shaped JSONL stream answering
FAKE_PI_ANSWER (default: a structured consult/review JSON), writes FAKE_PI_STDERR to stderr,
and exits FAKE_PI_EXIT (default 0).

Every invocation appends `[argv[0], cwd]` as one JSON line to FAKE_PI_CWD_FILE when set. Like
pi 1.5.0 (`runMigrations(cwd)` in main.js), every invocation except `--version` and `auth`
renames `<cwd>/.pi/commands` to `<cwd>/.pi/prompts` when only the former exists."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

SUPPRESSION_FLAGS = [
    "--no-context-files",
    "--no-skills",
    "--no-extensions",
    "--no-mcp",
    "--no-prompt-templates",
    "--no-themes",
    "--no-approve",
    "--offline",
]
_HEADER = "provider    model                     context  max-out  thinking  images"
_ROW = "openrouter  moonshotai/kimi-k3        1.0M     943.7K   yes       yes"
_DEFAULT_MODELS = f"{_HEADER}\n{_ROW}\n"
_DEFAULT_AUTH = '{"status":"ready","provider":"openrouter","authType":"api_key"}'
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


def _strip_suppression(argv: list[str]) -> list[str] | None:
    """argv without its trailing suppression flags, or None when they are not all there."""
    n = len(SUPPRESSION_FLAGS)
    if argv[-n:] != SUPPRESSION_FLAGS:
        return None
    return argv[:-n]


def _list_models(term: str | None) -> int:
    table = os.environ.get("FAKE_PI_MODELS", _DEFAULT_MODELS)
    lines = table.splitlines()
    header, rows = lines[0], lines[1:]
    if term is not None:
        rows = [r for r in rows if len(r.split()) >= 2 and term in "/".join(r.split()[:2])]
        if not rows:
            print(f'No models matching "{term}"')
            return 0
    print("\n".join([header, *rows]))
    return 0


def _auth_check(argv: list[str]) -> int:
    if argv[:4] != ["auth", "check", "--json", "--no-refresh"] or argv[4:5] != ["--model"]:
        print("error: unknown option", file=sys.stderr)
        return 2
    raw = os.environ.get("FAKE_PI_AUTH", _DEFAULT_AUTH)
    print(raw)
    try:
        status = json.loads(raw).get("status")
    except (json.JSONDecodeError, AttributeError):
        status = None
    return {"ready": 0, "not_ready": 1}.get(status, 2)


def _probe(argv: list[str]) -> int | None:
    """Answer a free probe; None for a `-p` run."""
    if argv == ["--version"]:
        print(os.environ.get("FAKE_PI_VERSION", "1.5.0"))
        return 0
    if argv[:1] == ["auth"]:
        return _auth_check(argv)
    stripped = _strip_suppression(argv)
    if stripped == ["--help"]:
        # The verbatim 1.5.0 capture, copied beside this script by the `fake_pi` fixture.
        help_file = os.environ.get("FAKE_PI_HELP_FILE") or Path(__file__).with_name("pi-help.txt")
        sys.stdout.write(Path(help_file).read_text(encoding="utf-8"))
        return 0
    if stripped is not None and stripped[:1] == ["--list-models"] and len(stripped) <= 2:
        return _list_models(stripped[1] if len(stripped) == 2 else None)
    if "-p" not in argv:
        print("error: unknown command", file=sys.stderr)
        return 2
    return None


def _usage(inp: int, out: int) -> dict:
    return {
        "input": inp,
        "output": out,
        "cacheRead": 0,
        "cacheWrite": 0,
        "totalTokens": inp + out,
        "cost": {"total": 0.0012, "totalFromProvider": True},
    }


def _default_events(prompt: str, answer: str, model: str) -> str:
    provider, _, model_id = model.partition("/")
    assistant = {
        "role": "assistant",
        "content": [{"type": "text", "text": answer}],
        "api": "openai-completions",
        "provider": provider,
        "model": model_id,
        "thinkingLevel": "medium",
        "usage": _usage(120, 40),
        "stopReason": "stop",
        "timestamp": 1762560000000,
    }
    user = {"role": "user", "content": [{"type": "text", "text": prompt}], "timestamp": 0}
    events = [
        {"type": "session", "version": 3, "id": "fake-pi-session", "cwd": str(Path.cwd())},
        {"type": "agent_start"},
        {"type": "message_end", "message": {"role": "system", "content": "fixed"}},
        {"type": "message_end", "message": user},
        {"type": "message_end", "message": assistant},
        {"type": "turn_end", "message": assistant, "toolResults": []},
        {"type": "agent_end", "messages": [user, assistant]},
        {"type": "agent_settled"},
    ]
    return "".join(json.dumps(e) + "\n" for e in events)


def _record_cwd(argv: list[str]) -> None:
    cwd_file = os.environ.get("FAKE_PI_CWD_FILE")
    if cwd_file:
        with Path(cwd_file).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps([argv[0] if argv else "", str(Path.cwd())]) + "\n")


def _migrate(argv: list[str]) -> None:
    """pi's project migration, which runs before it handles `--help` or `--list-models`."""
    if argv == ["--version"] or argv[:1] == ["auth"]:
        return
    project = Path.cwd() / ".pi"
    if (project / "commands").exists() and not (project / "prompts").exists():
        (project / "commands").rename(project / "prompts")


def main(argv: list[str]) -> int:
    _record_cwd(argv)
    _migrate(argv)
    probed = _probe(argv)
    if probed is not None:
        return probed
    prompt = sys.stdin.read()
    argv_file = os.environ.get("FAKE_PI_ARGV_FILE")
    if argv_file:
        with Path(argv_file).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(argv) + "\n")
    stdin_file = os.environ.get("FAKE_PI_STDIN_FILE")
    if stdin_file:
        Path(stdin_file).write_text(prompt, encoding="utf-8")
    write = os.environ.get("FAKE_PI_WRITE")
    if write:
        (Path.cwd() / write).write_text("written by fake pi\n", encoding="utf-8")
    events = os.environ.get("FAKE_PI_EVENTS")
    if events is None:
        model = argv[argv.index("--model") + 1] if "--model" in argv else "fake/model"
        events = _default_events(prompt, os.environ.get("FAKE_PI_ANSWER", _DEFAULT_ANSWER), model)
    sys.stdout.write(events)
    sys.stdout.flush()
    stderr = os.environ.get("FAKE_PI_STDERR")
    if stderr:
        sys.stderr.write(stderr + "\n")
    return int(os.environ.get("FAKE_PI_EXIT", "0"))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
