"""Workspace resolution (ADR 0003) and the handshake-era client probes.

Precedence: explicit workspace_root → the client's file roots (first root; an explicit root
must lie inside one) → a structured invalid_workspace_root. The server's own cwd is used only
under AMICUS_ALLOW_CWD_WORKSPACE=1 and is then disclosed in meta.workspace_warning. It is
read only on that last branch, so a cwd that has been deleted under the running server
(issue #170) cannot fail a call that named its workspace, and when that branch is reached
and the cwd is gone the call fails as invalid_workspace_root, not a retryable
internal_error. Roots resolve on handshake-era connections only (the 2026-07-28
`roots/list` round-trip is not implemented; see codex-in-claude ADR 0004 D5)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote, urlparse

from amicus.schemas.params import WORKSPACE_SCOPE

if TYPE_CHECKING:  # pragma: no cover
    from amicus.schemas.envelope import RootsSource


@dataclass(frozen=True)
class WorkspaceResolution:
    path: str | None
    source: str | None  # "param" | "roots" | "cwd"
    error_code: str | None = None  # invalid_workspace_root | workspace_outside_roots
    error_detail: str | None = None
    reason: str | None = None  # a WORKSPACE_REASONS token, set with error_code (#214)


# The scope clause is the shared one (schemas.params), so this repair cannot widen the
# rule back to "every call" on its own (issue #40).
_NO_WORKSPACE = (
    "no workspace_root was given and the client advertised no file roots; pass "
    f"workspace_root (an absolute directory) {WORKSPACE_SCOPE}"
)
# The cwd branch was reached and the process cwd is gone (deleted under the running
# server). No call can mint the directory, so like _NO_WORKSPACE this carries no repair;
# the message names the ways out.
_CWD_GONE = (
    "the server's working directory no longer exists, so AMICUS_ALLOW_CWD_WORKSPACE has "
    f"nothing to fall back to; pass workspace_root (an absolute directory) {WORKSPACE_SCOPE}, "
    "configure an MCP root, or restart the server from an existing directory"
)


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
    except ValueError:
        return False
    return True


def resolve_workspace(
    explicit: str | None,
    roots: list[str],
    server_cwd: str | None,
) -> WorkspaceResolution:
    """The precedence alone: the explicit path, then the first root, then `server_cwd`,
    which `resolve` supplies only when its cwd policy allows it and is None otherwise, so
    reaching it with None is the refusal. `roots` are absolute filesystem paths already
    extracted from the client's MCP roots (file:// URIs decoded by the caller)."""
    norm_roots = [str(Path(r).resolve()) for r in roots]
    if explicit is not None:
        candidate = Path(explicit)
        if not candidate.is_absolute():
            return WorkspaceResolution(
                None,
                None,
                "invalid_workspace_root",
                "workspace_root must be an absolute path",
                "not_absolute",
            )
        resolved = candidate.resolve()
        if not resolved.is_dir():
            return WorkspaceResolution(
                None,
                None,
                "invalid_workspace_root",
                f"not a directory: {resolved}",
                "not_a_directory",
            )
        if norm_roots and not any(_is_within(resolved, Path(r)) for r in norm_roots):
            return WorkspaceResolution(
                None,
                None,
                "workspace_outside_roots",
                f"{resolved} is outside the client's MCP roots",
                "outside_roots",
            )
        return WorkspaceResolution(str(resolved), "param")
    if norm_roots:
        root = norm_roots[0]
        if not Path(root).is_dir():
            # Checked like an explicit path (#248): a stale root would otherwise become the
            # cwd of every git subprocess, which then fails as a missing executable. First-root
            # selection stands; a later root is never tried silently.
            return WorkspaceResolution(
                None,
                None,
                "invalid_workspace_root",
                f"the client's first file root is not an existing directory: {root}",
                "root_not_a_directory",
            )
        return WorkspaceResolution(root, "roots")
    if server_cwd is None:
        return WorkspaceResolution(
            None, None, "invalid_workspace_root", _NO_WORKSPACE, "no_workspace"
        )
    return WorkspaceResolution(str(Path(server_cwd).resolve()), "cwd")


def resolve(
    explicit: str | None,
    roots: list[str],
    *,
    allow_cwd: bool,
    server_cwd: str | None = None,
) -> WorkspaceResolution:
    """`resolve_workspace` under the cwd policy. The process cwd is read only when it
    would decide the outcome — no explicit root, no client root, and the opt-in — so an
    explicit or client root never consults it and the refusal never does either (#170).
    `server_cwd` is the test injection point and is used verbatim."""
    if explicit is None and not roots and allow_cwd and server_cwd is None:
        try:
            server_cwd = str(Path.cwd())
        except FileNotFoundError:
            return WorkspaceResolution(None, None, "invalid_workspace_root", _CWD_GONE, "cwd_gone")
    return resolve_workspace(explicit, roots, server_cwd if allow_cwd else None)


# Git's worktree link files each hold one path; anything larger is not one.
_GIT_LINK_MAX_BYTES = 4096


def _read_git_link(path: Path) -> str | None:
    """The stripped text of a small file, or None."""
    try:
        if not path.is_file():
            return None
        with path.open("rb") as f:
            raw = f.read(_GIT_LINK_MAX_BYTES + 1)
        text = raw.decode("utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None
    return text if text and len(raw) <= _GIT_LINK_MAX_BYTES else None


def linked_worktree_checkout(path: str, roots: list[str]) -> str | None:
    """The checkout inside `roots` that `path` lies in a linked git worktree of, or None
    (#267). Advisory, and it fails closed: None on anything it cannot confirm.

    It reads git's worktree link files and runs no git, because `path` lies outside the
    client's roots and git there could run repo-configured code. The link must hold both
    ways, so a stray `.git` file cannot claim a rooted repository: the nearest `.git` is a
    file naming a gitdir, that gitdir's `gitdir` file names this very `.git` back (not its
    symlink target), its `commondir` names an existing `.git` directory whose `worktrees/`
    holds that gitdir, as git lays it out, and the checkout holding that directory lies
    inside a root. A submodule's gitdir has no `commondir`, and a bare repository's common
    dir is not named `.git`, so neither qualifies. A path that cannot be resolved is no
    hint: Python 3.11 and 3.12 raise RuntimeError on a symlink loop, later ones OSError."""
    try:
        return _linked_worktree_checkout(path, roots)
    except (OSError, RuntimeError, ValueError):
        return None


def _linked_worktree_checkout(path: str, roots: list[str]) -> str | None:
    start = Path(path).resolve()
    for directory in (start, *start.parents):
        dot_git = directory / ".git"
        if not dot_git.exists() and not dot_git.is_symlink():
            continue
        # The nearest .git decides: a main checkout's directory, or anything unreadable,
        # means `path` is not in a linked worktree.
        link = _read_git_link(dot_git)
        if link is None or not link.startswith("gitdir:"):
            return None
        gitdir = (directory / link.removeprefix("gitdir:").strip()).resolve()
        back = _read_git_link(gitdir / "gitdir")
        common = _read_git_link(gitdir / "commondir")
        if back is None or common is None or (gitdir / back).resolve() != dot_git:
            return None
        common_dir = (gitdir / common).resolve()
        checkout = common_dir.parent
        if common_dir.name != ".git" or not common_dir.is_dir():
            return None
        if gitdir.parent != common_dir / "worktrees":
            return None
        if not any(_is_within(checkout, Path(r).resolve()) for r in roots):
            return None
        return str(checkout)
    return None


def vanished_reason(source: str | None) -> str:
    """The details.reason for a workspace that resolved and then disappeared before git
    could run in it (#248): the token names the source that supplied the directory, so
    the correction (fix the client's roots, pass another workspace_root, or restore the
    server's working directory) is the right one."""
    if source == "roots":
        return "root_not_a_directory"
    if source == "cwd":
        return "cwd_gone"
    return "not_a_directory"


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
