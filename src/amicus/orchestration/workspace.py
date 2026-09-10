"""Workspace resolution (ADR 0003) and the handshake-era client probes.

Precedence: explicit workspace_root → the client's file roots (first root; an explicit root
must lie inside one) → a structured invalid_workspace_root. The server's own cwd is used only
under AMICUS_ALLOW_CWD_WORKSPACE=1 and is then disclosed in meta.workspace_warning. Roots
resolve on handshake-era connections only (the 2026-07-28 `roots/list` round-trip is not
implemented; see codex-in-claude ADR 0004 D5)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote, urlparse

from pontonier.core import workspace as _pw

if TYPE_CHECKING:  # pragma: no cover
    from amicus.schemas.envelope import RootsSource


@dataclass(frozen=True)
class WorkspaceResolution:
    path: str | None
    source: str | None  # "param" | "roots" | "cwd"
    error_code: str | None = None  # invalid_workspace_root | workspace_outside_roots
    error_detail: str | None = None


_NO_WORKSPACE = (
    "no workspace_root was given and the client advertised no file roots; pass "
    "workspace_root (an absolute directory) from a sessionless client on every call whose "
    "schema declares it"
)


def resolve(
    explicit: str | None,
    roots: list[str],
    *,
    allow_cwd: bool,
    server_cwd: str | None = None,
) -> WorkspaceResolution:
    cwd = server_cwd if server_cwd is not None else _pw.server_cwd()
    res = _pw.resolve_workspace(explicit, roots, cwd)
    if res.error_code is not None:
        return WorkspaceResolution(None, None, res.error_code, res.error_detail)
    if res.source == "cwd" and not allow_cwd:
        return WorkspaceResolution(None, None, "invalid_workspace_root", _NO_WORKSPACE)
    return WorkspaceResolution(res.path, res.source)


def workspace_warning_for(source: str | None, cwd: str | None) -> str | None:
    if source == "cwd":
        return (
            f"workspace resolved from the server's own cwd ({cwd}) under "
            "AMICUS_ALLOW_CWD_WORKSPACE; pass workspace_root (or configure an MCP root) to be "
            "sure the call targets the intended repository"
        )
    return None


def _session(ctx: Any) -> Any | None:
    if ctx is None:
        return None
    try:
        return ctx.session
    except RuntimeError:
        return None


async def roots_from_ctx(ctx: Any) -> tuple[list[str], RootsSource]:
    """Absolute local paths from the client's file:// roots, plus which of three states
    produced them: client | not_negotiated | probe_failed."""
    session = _session(ctx)
    if session is None:
        return [], "not_negotiated"
    capabilities = getattr(session, "client_capabilities", None)
    if capabilities is None or getattr(capabilities, "roots", None) is None:
        return [], "not_negotiated"
    try:
        roots = (await session.list_roots()).roots
    except Exception:
        return [], "probe_failed"
    paths: list[str] = []
    for root in roots:
        parsed = urlparse(str(root.uri))
        if parsed.scheme == "file" and parsed.netloc in ("", "localhost"):
            path = unquote(parsed.path)
            if path and path != "/" and Path(path).is_absolute():
                paths.append(path)
    return paths, "client"


def client_name_from_ctx(ctx: Any) -> str | None:
    """The client's declared name (`clientInfo.name`, `client_info` on the v2 SDK), or None."""
    session = _session(ctx)
    if session is None:
        return None
    params = getattr(session, "client_params", None)
    # MCP SDK v2 names it `client_info`; `clientInfo` is the pre-v2 alias, kept as a
    # fallback so a handshake-era session object built by an older client still reads.
    info = getattr(params, "client_info", None) or getattr(params, "clientInfo", None)
    name = getattr(info, "name", None)
    return name if isinstance(name, str) and name.strip() else None
