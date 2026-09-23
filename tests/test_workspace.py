"""ADR 0003: explicit workspace_root → handshake-era roots → invalid_workspace_root; the
server cwd only under the operator opt-in, always disclosed."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from mcp.types import ClientCapabilities, Implementation, InitializeRequestParams

from amicus.orchestration import workspace as ws
from amicus.schemas.params import WORKSPACE_REASONS, WORKSPACE_SCOPE


def test_explicit_root_wins_and_is_checked_against_roots(tmp_path):
    inside = tmp_path / "repo"
    inside.mkdir()
    res = ws.resolve(str(inside), [str(tmp_path)], allow_cwd=False)
    assert (res.path, res.source, res.error_code) == (
        str(inside.resolve()),
        "param",
        None,
    )
    outside = ws.resolve(str(inside), ["/somewhere/else"], allow_cwd=False)
    assert outside.error_code == "workspace_outside_roots" and outside.path is None
    assert ws.resolve("relative/path", [], allow_cwd=False).error_code == "invalid_workspace_root"
    assert (
        ws.resolve(str(tmp_path / "missing"), [], allow_cwd=False).error_code
        == "invalid_workspace_root"
    )


def test_roots_then_refusal_then_opt_in_cwd(tmp_path):
    res = ws.resolve(None, [str(tmp_path)], allow_cwd=False)
    assert (res.path, res.source) == (str(tmp_path.resolve()), "roots")
    refused = ws.resolve(None, [], allow_cwd=False)
    assert refused.error_code == "invalid_workspace_root" and (
        "workspace_root" in (refused.error_detail or "")
    )
    # The repair carries the SHARED scope clause, so it cannot widen the rule back to
    # "every call" on its own and send the caller into a tool that rejects the parameter
    # (issue #40). What is pinned is that it renders from the one source, not its prose.
    assert WORKSPACE_SCOPE in (refused.error_detail or "")
    allowed = ws.resolve(None, [], allow_cwd=True, server_cwd=str(tmp_path))
    assert (allowed.path, allowed.source) == (str(tmp_path.resolve()), "cwd")
    assert ws.workspace_warning_for("cwd", "/x") and (
        ws.workspace_warning_for("param", "/x") is None
    )


class _Session:
    def __init__(self, caps, roots=None, raise_on_list=False, name=None):
        self.client_capabilities = caps
        self._roots = roots or []
        self._raise = raise_on_list
        self.client_params = (
            InitializeRequestParams(
                protocol_version="2025-11-25",
                capabilities=ClientCapabilities(),
                client_info=Implementation(name=name, version="1.0"),
            )
            if name
            else None
        )

    async def list_roots(self):
        if self._raise:
            raise RuntimeError("no back-channel")
        return SimpleNamespace(roots=[SimpleNamespace(uri=u) for u in self._roots])


class _Ctx:
    def __init__(self, session):
        self._session = session

    @property
    def session(self):
        if self._session is None:
            raise RuntimeError("no session")
        return self._session


async def test_roots_from_ctx_states():
    assert await ws.roots_from_ctx(None) == ([], "not_negotiated")
    assert await ws.roots_from_ctx(_Ctx(None)) == ([], "not_negotiated")
    assert await ws.roots_from_ctx(_Ctx(_Session(SimpleNamespace(roots=None)))) == (
        [],
        "not_negotiated",
    )
    assert await ws.roots_from_ctx(
        _Ctx(_Session(SimpleNamespace(roots=True), raise_on_list=True))
    ) == ([], "probe_failed")
    roots, source = await ws.roots_from_ctx(
        _Ctx(
            _Session(
                SimpleNamespace(roots=True),
                roots=[
                    "file:///repo%20a",
                    "file://host/x",
                    "file:///",
                    "https://x",
                    "file:///ok",
                ],
            )
        )
    )
    assert (roots, source) == (["/repo a", "/ok"], "client")


def test_client_name_from_ctx():
    assert ws.client_name_from_ctx(None) is None
    assert ws.client_name_from_ctx(_Ctx(None)) is None
    assert ws.client_name_from_ctx(_Ctx(_Session(None))) is None
    assert ws.client_name_from_ctx(_Ctx(_Session(None, name="claude-code"))) == "claude-code"


async def test_client_name_reaches_the_host_framing_from_a_real_client():
    """Regression: the SDK v2 field is `client_info` (snake_case). Reading `clientInfo`
    silently yielded None on every real connection, so host framing was always neutral."""
    from fastmcp import Client, FastMCP
    from fastmcp.server.middleware import Middleware

    from amicus.orchestration import prompts

    seen: list[str | None] = []

    class _Probe(Middleware):
        async def on_call_tool(self, context, call_next):
            seen.append(ws.client_name_from_ctx(context.fastmcp_context))
            return await call_next(context)

    app = FastMCP(name="scratch")
    app.add_middleware(_Probe())

    @app.tool(name="t", output_schema={"type": "object", "additionalProperties": True})
    async def t() -> dict:
        return {"ok": True}

    async with Client(
        app, mode="legacy", client_info={"name": "claude-code", "version": "2.1.263"}
    ) as c:
        await c.call_tool("t", {})
    assert seen == ["claude-code"]
    assert prompts.host_display_name(seen[0], None) == prompts.HOST_DISPLAY_NAMES["claude-code"]


def _patched_path(cwd):
    """A Path whose cwd() is `cwd`, bound to the resolver module only: patching
    pathlib.Path itself would also break pytest's own traceback rendering. The base is
    the concrete class (PosixPath here): subclassing `Path` itself is a 3.12+ feature."""
    return type("_Path", (type(Path()),), {"cwd": classmethod(lambda _cls: cwd())})


def _never():
    raise AssertionError("Path.cwd() was consulted on a branch it cannot decide")


def test_the_cwd_is_read_only_when_it_decides_the_outcome(tmp_path, monkeypatch):
    """Issue #170: an explicit root, a client root and the refusal never consult the
    process cwd, so a deleted cwd cannot fail a call that named its workspace."""
    monkeypatch.setattr(ws, "Path", _patched_path(_never))
    inside = tmp_path / "repo"
    inside.mkdir()
    assert ws.resolve(str(inside), [], allow_cwd=True).source == "param"
    assert ws.resolve(str(inside), [str(tmp_path)], allow_cwd=True).source == "param"
    assert (
        ws.resolve(str(inside), ["/somewhere/else"], allow_cwd=True).error_code
        == "workspace_outside_roots"
    )
    assert ws.resolve("relative/path", [], allow_cwd=True).error_code == "invalid_workspace_root"
    assert (
        ws.resolve(str(tmp_path / "missing"), [], allow_cwd=True).error_code
        == "invalid_workspace_root"
    )
    assert ws.resolve(None, [str(tmp_path)], allow_cwd=True).source == "roots"
    refused = ws.resolve(None, [], allow_cwd=False)
    assert refused.error_code == "invalid_workspace_root" and WORKSPACE_SCOPE in (
        refused.error_detail or ""
    )
    injected = ws.resolve(None, [], allow_cwd=True, server_cwd=str(tmp_path))
    assert (injected.path, injected.source) == (str(tmp_path.resolve()), "cwd")


def _gone():
    raise FileNotFoundError(2, "No such file or directory")


def test_a_deleted_cwd_is_reported_not_raised_when_the_cwd_is_needed(tmp_path, monkeypatch):
    """Issue #170: the one branch that needs the cwd reports its absence as a
    non-temporary invalid_workspace_root that names the ways out, instead of raising
    into the guard's retryable internal_error."""
    monkeypatch.setattr(ws, "Path", _patched_path(_gone))
    res = ws.resolve(None, [], allow_cwd=True)
    assert (res.path, res.source, res.error_code) == (None, None, "invalid_workspace_root")
    detail = res.error_detail or ""
    assert "no longer exists" in detail and "workspace_root" in detail and "restart" in detail
    assert WORKSPACE_SCOPE in detail
    # Positive control on the instrument: the same call with a live cwd resolves from it.
    monkeypatch.setattr(ws, "Path", _patched_path(lambda: tmp_path))
    live = ws.resolve(None, [], allow_cwd=True)
    assert (live.path, live.source) == (str(tmp_path.resolve()), "cwd")


def test_every_refusal_carries_a_published_reason_token(tmp_path, monkeypatch):
    """Issue #214: the refusals share a code or two, so each names its cause as a
    WORKSPACE_REASONS token, and every published token is one some refusal emits, so the
    vocabulary cannot drift. The prose stays in error_detail, which names no token."""
    root = tmp_path / "root"
    root.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    cases = {
        "no_workspace": ws.resolve_workspace(None, [], None),
        "not_absolute": ws.resolve_workspace("relative/path", [], None),
        "not_a_directory": ws.resolve_workspace(str(tmp_path / "nope"), [], None),
        "outside_roots": ws.resolve_workspace(str(other), [str(root)], None),
    }
    monkeypatch.setattr(ws, "Path", _patched_path(_gone))
    cases["cwd_gone"] = ws.resolve(None, [], allow_cwd=True)
    for reason, res in cases.items():
        assert (res.path, res.reason) == (None, reason), reason
        assert res.error_detail and reason not in res.error_detail, reason
    assert set(cases) == set(WORKSPACE_REASONS)
    # Control: a resolution that succeeds carries no reason at all.
    assert ws.resolve_workspace(str(root), [str(root)], None).reason is None
