# Codex CLI 0.153.4 — amicus M6 install smoke

Captured 2026-09-07 on the maintainer's machine.
The install came from `.codex-plugin/`, whose `plugin.json` names `./.mcp.json` as its `mcpServers` source, the same file the Claude manifest points at.

## The `--from` override

Identical substitution to the Claude Code capture, and for the same reason.

```
uv build --wheel --out-dir <scratch>/wheel .
# committed: uvx --from git+https://github.com/briandconnelly/amicus.git@v0.1.0 amicus-mcp
# used:      uvx --from <scratch>/wheel/amicus-0.1.0-py3-none-any.whl amicus-mcp
```

The command stayed `uvx`, the argument order stayed the committed order, and the console script stayed `amicus-mcp`.
`git diff .mcp.json` was empty at commit time.

## How the host was driven

`codex exec --json`, the M5 host-capture pattern.

The first attempt used `-c mcp_servers.amicus.*` overrides on top of the maintainer's own config.
Those overrides ADD amicus alongside every server already configured, and they do not merge into an existing entry, so neither `enabled=false` nor a bogus `command` could remove a rival.
That contaminated the cold-start probe: the host reached for a different second-opinion MCP server before it ever looked at amicus.
The fix was a scoped `CODEX_HOME` holding a `config.toml` that declares amicus and nothing else, with `auth.json` symlinked to the real one so the login still resolves.
Every probe below ran under that scoped home.

## Negotiated handshake

```
tools/call amicus_backends: protocol=2025-06-18 client=codex-mcp-client/0.153.4 tasks_negotiated=False
```

Observed, not expected: an older handshake-era protocol than the Claude host negotiates, the client identifying itself as `codex-mcp-client/0.153.4`, and no tasks extension.
This matches the M5 capture under `docs/host-captures/codex/0.153.4/`.

## Findings

- **This host gates MCP tools on their annotations, and it is visible in a single run.**
  Under `approval_policy = "never"` the host auto-approved `amicus_backends` and `amicus_capabilities`, both of which declare `read_only_hint: true`, and refused `amicus_consult` and `amicus_delegate_async`, which do not, with `MCP tool call requires approval, but approval policy is never`.
  This is the annotation-driven friction ADR 0001 discloses, met as a user meets it.
  The paid S1 runs therefore had to use `--approve-for-me`, which routes approvals through automatic review; `--approve-for-me` and `--sandbox` cannot be combined.
- **This host advertises no file roots.**
  Every amicus result reported `roots_source: not_negotiated`, and a call made without `workspace_root` came back with `error.code = invalid_workspace_root` naming the fix.
  The Claude host reported `roots_source: client` on the same calls.
- **The rival-server contamination above is worth keeping.**
  On a real Codex install that already carries a per-model second-opinion server, the agent picked the sibling over amicus at cold start.
  That is not an amicus defect, but it is what a cold start looks like on a host that has not migrated.

## Spend

Three paid calls were spent here, one per backend, all on S1.
The install, the handshake, the isolation work, S7, and every discovery probe were free.
Two earlier S1 attempts made no paid amicus call at all: the first was contaminated by the rival server, and the second was refused by the approval policy before dispatch.
Neither consumed budget.

## Command discovery is inapplicable here

Codex CLI has no slash-command surface, so there is nothing for a command-discovery probe to enumerate.
`.codex-plugin/plugin.json` reflects that: it declares `skills` and `mcpServers` but no `commands` key, where `.claude-plugin/plugin.json` declares all three.
The probe is recorded as inapplicable for that reason rather than skipped in silence.
