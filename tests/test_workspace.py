"""ADR 0003: explicit workspace_root → handshake-era roots → invalid_workspace_root; the
server cwd only under the operator opt-in, always disclosed."""

from __future__ import annotations

from types import SimpleNamespace

from amicus.orchestration import workspace as ws


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
            SimpleNamespace(clientInfo=SimpleNamespace(name=name)) if name else None
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
