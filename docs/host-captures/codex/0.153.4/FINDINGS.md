# Codex CLI 0.153.4 — amicus M5 host capture

Captured 2026-09-07 on the maintainer's machine with `codex exec` pointed at the M5 worktree's server (`AMICUS_TASKS=1`, `AMICUS_LOG_LEVEL=DEBUG`, `AMICUS_LOG_FILE`), asking the host to call the free `amicus_backends`.
One Codex turn was spent; no backend quota was spent.

## What the capture shows

- `connection.log`: every `tools/call amicus_backends` line amicus logged; the protocol version is a handshake-era one (`2025-06-18`), `clientInfo` is `codex-mcp-client/0.153.4`, and `tasks_negotiated=False`.
  `tests/test_host_captures.py` asserts exactly that against this file, after first proving the same regex accepts a known-positive line and reads a modern tasked line as modern.
- `host-output.jsonl`: the host's final JSONL events (with `session_id` and `thread_id` lines dropped); the tool ran and the host received an ordinary tool result, not a task.

## What this settles

- ADR 0004's "legacy fallback is claimed only after a host capture": Codex CLI 0.153.4 negotiates the handshake era, where the tasks extension cannot be negotiated, so its calls always take the plain path even with `AMICUS_TASKS=1`.
- The capability summary and `amicus_capabilities.tasks.fallback` claim only this (Task 4 wording), and now names Codex CLI 0.153.4.
