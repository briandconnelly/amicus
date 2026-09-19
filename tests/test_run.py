"""run_request: the one loop, driven with the FakePlugin and a scripted runtime."""

from __future__ import annotations

import dataclasses
import subprocess
from pathlib import Path

import pytest
from tests.support import codexfixtures as cf
from tests.support import fakeplugin

from amicus.orchestration import run as run_mod
from amicus.request import RunSpec
from amicus.sdk.backend.protocol import ClassifiedFailure


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


async def test_review_focus_reaches_the_prompt_and_folds_a_pass_to_unknown(monkeypatch, repo):
    (repo / "a.py").write_text("x = 2\n")
    payload = (
        '{"summary":"ok","verdict":"pass","confidence":"high","findings":[],'
        '"questions":[],"assumptions":[],"next_steps":[]}'
    )
    calls: list = []
    monkeypatch.setattr(
        run_mod.runtime, "run_async", cf.scripted_run_async(stdout=payload, calls=calls)
    )
    out = await run_mod.run_request(
        _spec("review_changes", str(repo), scope="working_tree", focus="locking"),
        fakeplugin.make_plugin(),
    )
    prompt = calls[0]["stdin_text"]
    marker = "## Author-provided context (untrusted data)"
    assert marker in prompt
    after_marker = prompt.split(marker, 1)[1]
    assert "Focus this review on: locking" in after_marker
    assert out["ok"] is True
    assert out["verdict"] == "unknown" and out["confidence"] == "low"
    assert "focused" in out["summary"]

    calls_unfocused: list = []
    monkeypatch.setattr(
        run_mod.runtime, "run_async", cf.scripted_run_async(stdout=payload, calls=calls_unfocused)
    )
    out_unfocused = await run_mod.run_request(
        _spec("review_changes", str(repo), scope="working_tree"), fakeplugin.make_plugin()
    )
    assert "Focus this review on:" not in calls_unfocused[0]["stdin_text"]
    assert out_unfocused["verdict"] == "pass" and out_unfocused["confidence"] == "high"


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

            from amicus.sdk.backend.protocol import PreparedRun

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


async def test_non_repo_consult_under_all_tiers_runs_in_an_empty_dir_with_a_warning(
    monkeypatch, tmp_path
):
    import dataclasses

    from amicus.orchestration import isolation
    from amicus.sdk.backend.contract import IsolationPolicy

    calls: list = []
    monkeypatch.setattr(
        run_mod.runtime, "run_async", cf.scripted_run_async(stdout="answer", calls=calls)
    )
    plugin = fakeplugin.make_plugin(
        contract=dataclasses.replace(
            fakeplugin.make_contract(), isolation_policy=IsolationPolicy.WORKTREE_ALL_TIERS
        )
    )
    out = await run_mod.run_request(_spec(cwd=str(tmp_path)), plugin)
    assert out["ok"] is True and out["meta"]["security_warnings"] == [isolation.NO_REPO_WARNING]
    assert calls[0]["cwd"] != str(tmp_path) and not Path(calls[0]["cwd"]).exists()
    review = await run_mod.run_request(_spec(kind="review_changes", cwd=str(tmp_path)), plugin)
    assert review["ok"] is False and review["error"]["code"] == "not_a_git_repo"


def test_artifact_reads_are_hardened(tmp_path):
    import os

    from amicus.sdk.backend.protocol import PreparedRun

    normal = tmp_path / "a.txt"
    normal.write_text("hello")
    link = tmp_path / "link.txt"
    link.symlink_to(normal)
    big = tmp_path / "big.txt"
    big.write_bytes(b"x" * (run_mod.MAX_ARTIFACT_BYTES + 1))
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    empty = tmp_path / "empty.txt"
    empty.write_text("")
    prepared = PreparedRun(
        argv=("x",),
        env={},
        cwd=str(tmp_path),
        artifact_paths={
            "normal": str(normal),
            "link": str(link),
            "big": str(big),
            "fifo": str(fifo),
            "empty": str(empty),
            "missing": str(tmp_path / "missing"),
        },
    )
    texts, refused = run_mod._read_artifacts(prepared)
    assert texts == {"normal": "hello"}
    # A refusal is amicus declining a file that IS there (#162). An absent file and an empty
    # one are the backend writing nothing, which is a different fact and not a refusal.
    assert {name: r.reason for name, r in refused.items()} == {
        "link": "not_regular_file",
        "big": "oversize",
        "fifo": "not_regular_file",
    }
    assert refused["big"].size == run_mod.MAX_ARTIFACT_BYTES + 1 and refused["link"].size is None


def test_a_file_at_the_cap_is_read_and_one_byte_over_is_refused(tmp_path):
    from amicus.sdk.backend.protocol import PreparedRun

    at_cap, over = tmp_path / "at", tmp_path / "over"
    at_cap.write_bytes(b"x" * run_mod.MAX_ARTIFACT_BYTES)
    over.write_bytes(b"x" * (run_mod.MAX_ARTIFACT_BYTES + 1))
    prepared = PreparedRun(
        argv=("x",),
        env={},
        cwd=str(tmp_path),
        artifact_paths={"at": str(at_cap), "over": str(over)},
    )
    texts, refused = run_mod._read_artifacts(prepared)
    assert len(texts["at"]) == run_mod.MAX_ARTIFACT_BYTES
    assert refused == {"over": run_mod.Refusal("oversize", run_mod.MAX_ARTIFACT_BYTES + 1)}


def test_a_short_read_does_not_deliver_a_partial_artifact(tmp_path, monkeypatch):
    """`os.read` may return fewer bytes than asked for. One call could hand back a prefix
    of the answer as if it were the whole of it, with nothing to say so (#162)."""
    import os

    from amicus.sdk.backend.protocol import PreparedRun

    body = "0123456789" * 50
    path = tmp_path / "answer.md"
    path.write_text(body)
    real_read = os.read
    monkeypatch.setattr(run_mod.os, "read", lambda fd, n: real_read(fd, min(n, 7)))
    prepared = PreparedRun(
        argv=("x",), env={}, cwd=str(tmp_path), artifact_paths={"answer": str(path)}
    )
    texts, refused = run_mod._read_artifacts(prepared)
    assert texts == {"answer": body} and refused == {}


def test_a_file_that_grows_past_the_cap_after_fstat_is_refused(tmp_path, monkeypatch):
    """The size check is an early exit, not the bound: a file can grow between fstat and
    read, and the read itself has to notice."""
    import os

    from amicus.sdk.backend.protocol import PreparedRun

    monkeypatch.setattr(run_mod, "MAX_ARTIFACT_BYTES", 10)
    path = tmp_path / "answer.md"
    path.write_text("x" * 11)
    real_fstat = os.fstat

    class Small:
        def __init__(self, st):
            self.st_mode, self.st_size = st.st_mode, 5

    monkeypatch.setattr(run_mod.os, "fstat", lambda fd: Small(real_fstat(fd)))
    prepared = PreparedRun(
        argv=("x",), env={}, cwd=str(tmp_path), artifact_paths={"answer": str(path)}
    )
    # Its size was never learned: fstat lied, and the read stopped one byte past the cap.
    assert run_mod._read_artifacts(prepared) == ({}, {"answer": run_mod.Refusal("oversize")})


def test_only_a_refused_answer_artifact_is_a_refused_answer(tmp_path):
    """Codex lists its input schema in `artifact_paths` beside the answer. A refused schema
    with an absent answer is the backend writing nothing, not amicus refusing an answer."""
    from amicus.sdk.backend.protocol import PreparedRun

    big = tmp_path / "schema.json"
    big.write_bytes(b"x" * (run_mod.MAX_ARTIFACT_BYTES + 1))
    prepared = PreparedRun(
        argv=("x",),
        env={},
        cwd=str(tmp_path),
        artifact_paths={"last-message": str(tmp_path / "absent"), "schema": str(big)},
        answer_artifacts=("last-message",),
    )
    _, refused = run_mod._read_artifacts(prepared)
    assert set(refused) == {"schema"}, "control: something WAS refused"
    assert run_mod._answer_refusal(prepared, refused) is None
    swapped = PreparedRun(
        argv=("x",),
        env={},
        cwd=str(tmp_path),
        artifact_paths=prepared.artifact_paths,
        answer_artifacts=("schema",),
    )
    assert run_mod._answer_refusal(swapped, refused) == refused["schema"]


# --- #162: what a refused answer artifact may and may not override -------------------------


def _refusing(base, tmp_path):
    """`base` with an answer artifact amicus will refuse (a symlink), answering on stdout."""
    import contextlib

    from amicus.sdk.backend.protocol import PreparedRun

    real = tmp_path / "answer.real"
    real.write_text("from the file")
    link = tmp_path / "answer.md"
    link.symlink_to(real)

    class Refusing(base):
        def prepare(self, request):
            @contextlib.asynccontextmanager
            async def _cm():
                yield PreparedRun(
                    argv=("fake",),
                    env={},
                    cwd=request.cwd,
                    stdin_text=request.prompt,
                    artifact_paths={"answer": str(link)},
                    answer_artifacts=("answer",),
                )

            return _cm()

    return fakeplugin.make_plugin(backend=Refusing())


async def test_a_refusal_never_hides_an_inspectors_own_failure(monkeypatch, tmp_path):
    """Only the empty-answer diagnosis is explained by a refusal. Any other failure an
    inspector reports on a clean exit (auth, a rate limit, a budget stop) is its own fact."""
    monkeypatch.setattr(run_mod.runtime, "run_async", cf.scripted_run_async(stdout="INSPECT_FAIL"))
    out = await run_mod.run_request(_spec(), _refusing(fakeplugin.InspectingBackend, tmp_path))
    assert out["ok"] is False and out["error"]["code"] == "nonzero_exit"
    assert "inspector said no" in out["error"]["message"]


@pytest.mark.parametrize("flag", ["output_truncated", "capture_failed"])
async def test_a_stream_that_was_not_captured_whole_is_no_substitute(monkeypatch, tmp_path, flag):
    """With the answer file refused, the stream is the only answer left, and a truncated or
    failed capture may have lost the true final message while an earlier one still parses."""
    import dataclasses

    scripted = cf.scripted_run_async(stdout="an earlier message")

    async def damaged(*args, **kwargs):
        return dataclasses.replace(await scripted(*args, **kwargs), **{flag: True})

    plugin = _refusing(fakeplugin.FakeBackend, tmp_path)
    monkeypatch.setattr(run_mod.runtime, "run_async", damaged)
    out = await run_mod.run_request(_spec(), plugin)
    assert out["ok"] is False and out["error"]["code"] == "answer_unavailable"
    # Control: the same run captured whole IS delivered, with the warning.
    monkeypatch.setattr(run_mod.runtime, "run_async", scripted)
    ok = await run_mod.run_request(_spec(), plugin)
    assert ok["ok"] is True and ok["summary"] == "an earlier message"
    assert run_mod.ANSWER_REFUSED_WARNING in ok["meta"]["security_warnings"]


def test_answer_unavailable_is_amicus_own_code_not_an_sdk_universal_one():
    """The SDK's universal set is the intersection every bridge emits. This code comes from
    amicus's own orchestration, for answer-file backends only (ADR 0030)."""
    from amicus.errors import repair_table
    from amicus.schemas import codes
    from amicus.sdk.conventions import envelope

    assert "answer_unavailable" in codes.LOCAL_CODES
    assert "answer_unavailable" not in envelope.UNIVERSAL_CODES
    rule = repair_table(None)["answer_unavailable"]
    assert rule.next_step == "reduce_input" and rule.temporary is False


@pytest.mark.parametrize("where", ["open", "fstat", "read"])
def test_a_file_that_cannot_be_read_is_unreadable_never_absent(tmp_path, monkeypatch, where):
    """An OSError that is not ELOOP or ENOENT, at any of the three calls. Mapping it back to
    an absent file would turn a refusal into "the backend wrote nothing" again (#162)."""
    import errno
    import os

    from amicus.sdk.backend.protocol import PreparedRun

    path = tmp_path / "answer.md"
    path.write_text("an answer")
    real = getattr(os, where)

    def failing(*args, **kwargs):
        if where == "open" and args[0] != str(path):
            return real(*args, **kwargs)
        raise OSError(errno.EIO, "injected")

    monkeypatch.setattr(run_mod.os, where, failing)
    prepared = PreparedRun(
        argv=("x",), env={}, cwd=str(tmp_path), artifact_paths={"answer": str(path)}
    )
    texts, refused = run_mod._read_artifacts(prepared)
    assert texts == {} and refused == {"answer": run_mod.Refusal("unreadable")}


def test_each_refusal_has_its_own_wire_reason_and_repair():
    from amicus.request import meta_for

    want = {
        "oversize": ("artifact_oversize", "reduce_input"),
        "not_regular_file": ("artifact_not_regular", "inspect_and_retry"),
        "unreadable": ("artifact_unreadable", "inspect_and_retry"),
    }
    assert set(want) == set(run_mod._REFUSAL_WIRE), "a new refusal needs a wire shape"
    for reason, (token, step) in want.items():
        out = run_mod._answer_unavailable(
            run_mod.Refusal(reason, 7), meta_for(_spec()), fakeplugin.make_plugin()
        )
        err = out["error"]
        assert err["code"] == "answer_unavailable" and err["temporary"] is False
        assert err["details"]["reason"] == token and err["repair"]["next_step"] == step
        sized = reason == "oversize"
        assert (err.get("actual_bytes") == 7) is sized and ("limit_bytes" in err) is sized
