# ADR 0023: amicus owns the dependency loggers' stderr, never below WARNING

**Status:** Accepted (2026-09-13)

**Note (M8, ADR 0029):** the separate `pontonier` logger this ADR names is gone.
The SDK now logs under `amicus.sdk.*`, which `obs.configure` covers through the `amicus` logger.
The Decision's log-file sentence and the Consequences' fall-through sentence no longer name it (#148); the Context keeps it, because it describes the tree this ADR was written against.

## Context

Issue #79 found that FastMCP logs a rejected `tools/call` on `fastmcp.server.server` with pydantic's error list, and that each error's `input` is the rejected value itself.
For a missing required argument that `input` is the whole argument dict, so a valid prompt field sent beside the omission reached the server's stderr verbatim, against AGENTS.md rule 18.
A probe of the real stdio server found a second route the issue did not name: for an unknown key, pydantic's `loc` is the key the client sent.
The record never met the value policy `obs` applies (issue #39), because `obs.configure` attached handlers only to `amicus` and `pontonier`.
`import fastmcp` installs FastMCP's own rich handlers on `fastmcp`, and `mcp` has none, so its WARNING records fall through to `logging.lastResort`.
Both render an exception's own text, which is the family issue #39 closed for amicus's own loggers.
FastMCP 4.0.3 is the latest release, and no upstream report of the leak existed on 2026-09-13.
A Codex consult on this issue (2026-09-13) corrected the first design in three ways, and each correction is recorded below.

## Decision

**The validation record is rewritten where it starts.**
`obs.FastMCPServerRecordFilter` is a logger filter on `fastmcp.server.server`, so it runs once, before every handler the record reaches, and survives a handler being replaced.
The rewritten record names the tool and, for each error, its `type` and the top-level component of its `loc`: `Invalid arguments for tool amicus_consult: 1 error(s): missing_argument at question`.
`input`, `ctx` and `msg` are never read, because `msg` echoes the input through a `value_error`.
FastMCP 4.0.4 closed the same leak upstream (PrefectHQ/fastmcp#5106) by logging a `{"error_count", "error_types"}` summary in place of pydantic's error list.
That summary carries no `loc`, so against it the rewritten record names no field: `Invalid arguments for tool amicus_consult: 1 error(s): missing_argument`.
Both shapes are read, because the `fastmcp>=4.0,<4.1` floor still admits 4.0.3, and upstream's count and types are re-checked here rather than trusted, on the same grounds as the list branch.
The `loc` is withheld for an extra-key error, and every component below the top level is dropped, because inside an open-keyed mapping a component can be a client's key under any error type.
An error type must be a lowercase slug and a field or tool name an identifier, because a `PydanticCustomError` may carry any string as its type.

**It is recognised by shape as well as by text, and anything unaudited is withheld.**
The first design matched the message template alone.
Codex held that a reworded template in a later 4.0.x release would pass the record through unchanged, which fails open.
A two-argument record whose second argument is a list of error mappings, or FastMCP's own summary mapping, is therefore rewritten whatever its message says.
A tool or prompt failure record is kept only when the name has an identifier's shape, since FastMCP writes it after the name was looked up.
A resource URI is the client's own text, so it is never kept.
Every other record from that logger keeps its level, logger name and exception, which the formatter renders as type and frames, and loses its message.
The filter never drops a record and never raises.

**amicus takes over `fastmcp` and `mcp` for stderr.**
Each gets one `PolicyStreamHandler` and stops propagating, which replaces FastMCP's rich handlers and `mcp`'s fall-through to `logging.lastResort`.
The first design left `mcp` alone; Codex pointed at `mcp`'s `logger.exception` sites, and a probe confirmed that `logging.lastResort` prints the exception's own text.
`fastmcp.settings.log_enabled` is switched off afterwards, because it is the only switch FastMCP's `configure_logging` honours, and `run(log_level=...)` would otherwise reinstall the rich handlers.

**The floor is WARNING, on each logger and each handler, whatever `AMICUS_LOG_LEVEL` says.**
The `mcp` stdio runner logs a whole inbound frame at DEBUG, and until now only `logging.lastResort`'s WARNING floor kept it off stderr.
The handler carries the floor as well, because FastMCP clamps `fastmcp.server.context.to_client`, which carries every message a tool sends its client, to DEBUG after the logger has admitted the record.

**Neither logger is written to `AMICUS_LOG_FILE`.**
The value policy passes a message string through unchanged, and both libraries build some messages with f-strings.
Routing them to disk would copy records that today reach only stderr, so the file keeps carrying amicus's records alone.

## Consequences

FastMCP's INFO log lines no longer reach stderr.
Its startup banner is printed to stderr rather than logged, so it still appears, once, before any request arrives.
The takeover does not make every dependency record safe: a message either library preformats with an f-string is still written as it stands, because the value policy cannot tell where a string came from.
The one such record known to carry prompt text is the one rewritten above.
Loggers outside `amicus`, `fastmcp` and `mcp` still fall through to `logging.lastResort`.
`tests/test_fastmcp_argument_log.py` reads a real stdio server's stderr and log file at WARNING and DEBUG, with a positive control for each.

## Audited versions

Every claim above about what a dependency logs was read from a specific release, and a bump of either dependency is a reason to read it again, because the filter's shape test and the WARNING floor are sized to those releases.
The audit on 2026-09-13 read fastmcp 4.0.3 and mcp 2.1.1.
mcp moved to 2.2.0 on 2026-09-14 (PR #81), after the audit, and a re-read that day found the two facts unchanged: FastMCP's argument-validation record is still written on `fastmcp.server.server` with pydantic's error list as its second argument, and the `mcp` stdio runner still logs a dropped pre-initialization frame at DEBUG.
Record the next bump's re-read here.
