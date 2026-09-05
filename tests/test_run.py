"""run_request: the one loop, driven with the FakePlugin and a scripted runtime."""

from __future__ import annotations

import dataclasses
import subprocess

import pytest
from pontonier.backend.protocol import ClassifiedFailure
from tests.support import codexfixtures as cf
from tests.support import fakeplugin

from amicus.orchestration import run as run_mod
from amicus.request import RunSpec


def _spec(kind="consult", cwd="/repo", **kw):
    base = dict(
        backend="fake",
        kind=kind,
        tool=f"amicus_{kind}",
        cwd=cwd,
        workspace_source="param",
        roots_source="client",
        host_name="Claude Code",
        timeout_seconds=10,
        question="why?",
        task="do",
        options={"isolation": "inherit"},
    )
    base.update(kw)
    return RunSpec(**base)


async def test_consult_happy_path_builds_prompt_and_stamps_meta(monkeypatch):
    calls: list = []
    monkeypatch.setattr(
        run_mod.runtime, "run_async", cf.scripted_run_async(stdout="hello world", calls=calls)
    )
    out = await run_mod.run_request(_spec(), fakeplugin.make_plugin())
    assert out["ok"] is True and out["summary"] == "hello world"
    assert (
        out["meta"]["backend"] == "fake"
        and out["meta"]["command_exit_code"] == 0
        and out["meta"]["elapsed_ms"] == 12
    )
    assert out["meta"]["backend_details"] == {"isolation": "inherit"}
    call = calls[0]
    assert call["cmd"] == ["fake"] and call["cwd"] == "/repo" and call["timeout"] == 10
    assert call["stdin_text"].startswith("You are giving Claude Code an independent second opinion")
    assert "## Question\nwhy?" in call["stdin_text"]


async def test_events_are_forwarded_and_validate_request_short_circuits(monkeypatch):
    seen: list[str] = []
    monkeypatch.setattr(run_mod.runtime, "run_async", cf.scripted_run_async(stdout="a\nb"))
    await run_mod.run_request(_spec(), fakeplugin.make_plugin(), on_event=seen.append)
    assert seen == ["a", "b"]

    class Refusing(fakeplugin.FakeBackend):
        def validate_request(self, request):
            return ClassifiedFailure(
                code="invalid_reasoning_effort",
                detail="nope",
                details={"field": "reasoning_effort"},
            )

    monkeypatch.setattr(run_mod.runtime, "run_async", cf.scripted_run_async(stdout="must not run"))
    out = await run_mod.run_request(
        _spec(reasoning_effort="x"), fakeplugin.make_plugin(backend=Refusing())
    )
    assert (
        out["ok"] is False
        and out["error"]["code"] == "invalid_reasoning_effort"
        and out["error"]["details"]["field"] == "reasoning_effort"
    )
    assert out["meta"]["backend"] == "fake"


async def test_unresolvable_binary_classifies_as_not_found(monkeypatch):
    class NoBinary:
        def resolve(self):
            return None

    class Classifying(fakeplugin.FakeBackend):
        def classify_failure(self, outcome, request):
            code = "fake_not_found" if outcome.run.binary_missing else "nonzero_exit"
            return ClassifiedFailure(code=code, detail="missing")

    monkeypatch.setattr(run_mod.runtime, "run_async", cf.scripted_run_async(stdout="must not run"))
    out = await run_mod.run_request(
        _spec(), fakeplugin.make_plugin(binary=NoBinary(), backend=Classifying())
    )
    assert out["error"]["code"] == "backend_not_found" and out["error"]["backend"] == "fake"


async def test_failed_run_is_classified_and_rendered(monkeypatch):
    monkeypatch.setattr(
        run_mod.runtime, "run_async", cf.scripted_run_async(stderr="kaboom", exit_code=1)
    )
    out = await run_mod.run_request(_spec(), fakeplugin.make_plugin())
    assert (
        out["ok"] is False
        and out["error"]["code"] == "nonzero_exit"
        and out["error"]["message"] == "kaboom"
    )
    assert out["meta"]["command_exit_code"] == 1


async def test_inspector_runs_on_every_completed_process(monkeypatch):
    monkeypatch.setattr(run_mod.runtime, "run_async", cf.scripted_run_async(stdout="INSPECT_FAIL"))
    out = await run_mod.run_request(
        _spec(), fakeplugin.make_plugin(backend=fakeplugin.InspectingBackend())
    )
    assert (
        out["ok"] is False
        and out["error"]["code"] == "nonzero_exit"
        and out["error"]["temporary"] is False
    )
    monkeypatch.setattr(run_mod.runtime, "run_async", cf.scripted_run_async(stdout="fine"))
    ok = await run_mod.run_request(
        _spec(), fakeplugin.make_plugin(backend=fakeplugin.InspectingBackend())
    )
    assert ok["ok"] is True


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@t.co")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "a.py").write_text("x = 1\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "init")
    return tmp_path


async def test_review_gathers_first_and_never_runs_on_an_empty_scope(monkeypatch, repo):
    monkeypatch.setattr(run_mod.runtime, "run_async", cf.scripted_run_async(stdout="must not run"))
    out = await run_mod.run_request(
        _spec("review_changes", str(repo), scope="working_tree"), fakeplugin.make_plugin()
    )
    assert out["ok"] is True and out["review_status"] == "not_run"
    (repo / "a.py").write_text("x = 2\n")
    calls: list = []
    payload = (
        '{"summary":"ok","verdict":"pass","confidence":"high","findings":[],'
        '"questions":[],"assumptions":[],"next_steps":[]}'
    )
    monkeypatch.setattr(
        run_mod.runtime, "run_async", cf.scripted_run_async(stdout=payload, calls=calls)
    )
    out = await run_mod.run_request(
        _spec("review_changes", str(repo), scope="working_tree"), fakeplugin.make_plugin()
    )
    assert out["ok"] is True and out["verdict"] == "pass" and out["review_status"] == "completed"
    assert (
        "+x = 2" in calls[0]["stdin_text"] and out["meta"]["context_summary"]["files_changed"] == 1
    )


async def test_delegate_runs_in_a_worktree_and_returns_the_diff(monkeypatch, repo):
    calls: list = []
    parents: list[str] = []
    monkeypatch.setattr(
        run_mod.runtime,
        "run_async",
        cf.scripted_run_async(
            stdout="I changed a.py", calls=calls, write_in_cwd={"a.py": "x = 3\n"}
        ),
    )
    out = await run_mod.run_request(
        _spec("delegate", str(repo)), fakeplugin.make_plugin(), on_worktree_parent=parents.append
    )
    assert out["ok"] is True and "+x = 3" in out["diff"] and out["summary"] == "I changed a.py"
    assert calls[0]["cwd"] != str(repo) and parents and (repo / "a.py").read_text() == "x = 1\n"
    assert not __import__("pathlib").Path(parents[0]).exists()
    assert calls[0]["stdin_text"].startswith("Claude Code is delegating a coding task")


async def test_delegate_site_errors_become_envelopes(monkeypatch, tmp_path):
    monkeypatch.setattr(run_mod.runtime, "run_async", cf.scripted_run_async(stdout="must not run"))
    out = await run_mod.run_request(_spec("delegate", str(tmp_path)), fakeplugin.make_plugin())
    assert (
        out["ok"] is False
        and out["error"]["code"] == "not_a_git_repo"
        and out["error"]["details"]["field"] == "workspace_root"
    )


async def test_orphan_sweep_runs_when_the_contract_asks(monkeypatch):
    swept: list[str] = []
    monkeypatch.setattr(run_mod.runtime, "sweep_orphans", lambda marker: swept.append(marker) or [])

    class Marked(fakeplugin.FakeBackend):
        def prepare(self, request):
            import contextlib

            from pontonier.backend.protocol import PreparedRun

            @contextlib.asynccontextmanager
            async def _cm():
                yield PreparedRun(
                    argv=("fake",), env={}, cwd=request.cwd, orphan_marker="amicus-marker-123"
                )

            return _cm()

    contract = dataclasses.replace(fakeplugin.make_contract(), needs_orphan_sweep=True)
    monkeypatch.setattr(run_mod.runtime, "run_async", cf.scripted_run_async(stdout="ok"))
    await run_mod.run_request(_spec(), fakeplugin.make_plugin(contract=contract, backend=Marked()))
    assert swept == ["amicus-marker-123"]
