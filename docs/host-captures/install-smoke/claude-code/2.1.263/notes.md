# Claude Code 2.1.263 — amicus M6 install smoke

Captured 2026-09-07 on the maintainer's machine.
The install came from `.claude-plugin/`, whose `plugin.json` names `./.mcp.json` as its `mcpServers` source.

## The `--from` override

The committed `.mcp.json` names `git+https://github.com/briandconnelly/amicus.git@v0.1.0`, a tag that does not exist until release.
For this capture that ONE argument was replaced with a locally built wheel, exactly as `tests/test_packaging.py::test_the_committed_manifest_command_starts_a_real_server` does it.

```
uv build --wheel --out-dir <scratch>/wheel .
# committed: uvx --from git+https://github.com/briandconnelly/amicus.git@v0.1.0 amicus-mcp
# used:      uvx --from <scratch>/wheel/amicus-0.1.0-py3-none-any.whl amicus-mcp
```

Every other field survived unchanged: the command is `uvx`, the argument order is the committed order, and the console script is still `amicus-mcp`.
`git diff .mcp.json` was empty at commit time; the substitution lived only in the scratch copies of the manifest.

## Two install paths were exercised

1. **Real plugin install into a scoped `CLAUDE_CONFIG_DIR`.**
   `claude plugin marketplace add <scratch plugin root>` then `claude plugin install amicus@amicus` both succeeded, and `claude plugin list` reported `amicus@amicus 0.1.0, scope: user, enabled`.
   `claude plugin validate .` passes with two warnings, recorded under "Findings" below.
   `claude plugin details amicus@amicus` reports 1 skill, 0 agents, 0 hooks, 1 MCP server, and an always-on cost of about 105 tokens.
   That config directory carries no login (Claude Code's credentials live in the macOS keychain), so it could smoke the install but not run a session.
2. **`claude -p --strict-mcp-config --mcp-config` against the substituted manifest**, the M5 host-capture pattern, for every live probe below.
   The plugin's skill and commands were supplied project-scoped (`--setting-sources project`) so the runs see the same components the installed plugin ships.

## Negotiated handshake

```
tools/call amicus_backends: protocol=2025-11-25 client=claude-code/2.1.263 tasks_negotiated=False
```

Observed, not expected: the protocol version is a handshake-era one, the client identifies itself as `claude-code/2.1.263`, and the tasks extension was not declared.
This matches the M5 capture under `docs/host-captures/claude-code/2.1.263/`.

## Findings

- `claude plugin validate` warns that the marketplace manifest has no `description`, and that `plugin.json`'s `interface` block is an unknown field Claude Code ignores at load time.
  Neither blocks the install; the `interface` block is there for other surfaces.
- This host does not preload MCP tool definitions.
  Every run reached the amicus tools through a `ToolSearch` deferred-tool lookup first, so the `tools/list` wire size is not a per-session token tax on this client the way the M0 ratchet's "least-capable realistic client" assumes.
  The ratchet is still the right ceiling for clients that do preload.
- In `-p` mode the host's approval gate appears as a refusal rather than an interactive prompt, and it is not annotation-specific: Claude Code withholds every ungranted MCP tool regardless of its hints.
  The annotation-driven half of that gate is visible on the Codex host instead; see that capture.

## Spend

Three paid calls were spent here, one per backend, all on S1.
Every other probe on this host was free: the install, the handshake, discovery, S2 (rejected before dispatch, then repaired against a stub backend) and S7 (refused at the host's permission gate before dispatch).
