# ADR 0003: Workspace resolution never silently falls back to the server cwd

**Status:** Accepted (2026-09-05, implemented in M1)

## Context

The MCP server launches from its install directory, so a cwd fallback silently targets the wrong repository.
codex-in-claude resolves explicit `workspace_root` → first file root → server cwd with a warning.

## Decision

Explicit `workspace_root` → handshake-era file roots (see codex-in-claude ADR 0004 D5) → structured `invalid_workspace_root`.
The server cwd is used only under `AMICUS_ALLOW_CWD_WORKSPACE=1`, and then the resolved path is disclosed in `meta.workspace_warning`.

## Consequences

- Sessionless (2026-07-28) clients must pass `workspace_root`; the parameter description says so.
- M1 implements the resolver (orchestration/workspace.py) and the handshake-era roots probe; a sessionless client without workspace_root receives invalid_workspace_root with zero spend.
- The server cwd is read only on the branch that would use it (issue #170): an explicit or client root never consults it, so a cwd deleted under the running server cannot fail a call that named its workspace, and when that branch is reached and the cwd is gone the call fails as invalid_workspace_root rather than a retryable internal_error.
- A client root is checked with `is_dir()` like an explicit path (issue #248): a root the client still advertises after the directory is gone is refused as invalid_workspace_root with reason `root_not_a_directory`, first-root selection stands, and a workspace that vanishes after resolution is reported with the token of its source (`root_not_a_directory`, `not_a_directory` or `cwd_gone`) rather than as a missing git executable, from the git wrappers, the delegate preflight and dry run, and a delegate job's worktree setup.
