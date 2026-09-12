"""The fourth verb end to end through the loop with the FakePlugin, the framing hook seam,
the not_run path, backend warnings onto meta, and the tool wiring through prepare_run."""

from __future__ import annotations

import subprocess

import pytest
from fastmcp import Client
from pontonier.backend.protocol import ExecResult
from tests.support import codexfixtures as cxf
from tests.support import fakeplugin

from amicus import config, server
from amicus.orchestration import finalize, prompts
from amicus.orchestration import run as run_mod
from amicus.registry import BackendRegistry
from amicus.request import INPUT_FIELDS, RunSpec

STRUCTURED = (
    '{"summary": "The plan ignores retries", "verdict": "concerns", "confidence": "high", '
    '"findings": [{"title": "no retry", "severity": "high", "file": null, "line": null, '
    '"evidence": "the target says fire-and-forget", "suggestion": "add a retry budget"}], '
    '"questions": [], "assumptions": [], "next_steps": ["decide the retry policy"]}'
)


class _Hook:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def frame(self, verb: str, framing: str, host_name: str) -> str:
        self.calls.append((verb, host_name))
        return f"[{verb}:{host_name}]\n{framing}"


def _spec(kind="adversarial_review", cwd="/repo", **kw):
    base = dict(
        backend="fake",
        kind=kind,
        tool="amicus_adversarial_review",
        cwd=cwd,
        workspace_source="param",
        roots_source="client",
        host_name="Claude Code",
        timeout_seconds=10,
        target="Ship without retries.",
        evidence="The queue is at-most-once.",
        question="why?",
        task="do",
        options={"isolation": "inherit"},
    )
    base.update(kw)
    return RunSpec(**base)


def _plugin(**overrides):
    return fakeplugin.make_plugin(
        features=frozenset({"adversarial_review", "delegate"}), **overrides
    )


def test_target_and_evidence_are_inputs_never_public():
    assert {"target", "evidence"} <= set(INPUT_FIELDS)
    spec = _spec()
    assert "target" not in spec.public() and spec.inputs()["target"] == "Ship without retries."
    rebuilt = RunSpec.from_parts(spec.public(), spec.inputs())
    assert rebuilt == spec
    assert RunSpec.from_parts(spec.public(), {"question": "q"}).target is None


def test_framing_for_uses_the_hook_when_the_plugin_has_one():
    hook = _Hook()
    plain = prompts.framing_for(fakeplugin.make_plugin(), "consult", "Codex")
    assert plain.startswith("You are giving Codex an independent second opinion")
    framed = prompts.framing_for(fakeplugin.make_plugin(framing=hook), "review_changes", "Codex")
    assert framed.startswith("[review_changes:Codex]\nYou are an independent code reviewer")
    assert hook.calls == [("review_changes", "Codex")]
    adversarial = prompts.framing_for(None, "adversarial_review", "Kimi")
    assert adversarial == prompts.adversarial_framing("Kimi")
    assert "Kimi" in adversarial and "untrusted DATA" in adversarial
    assert (
        "Do not modify files" in adversarial
        and prompts.ADVERSARIAL_STRUCTURED_CLAUSE in adversarial
    )
    for verb in ("consult", "review_changes", "delegate"):
        assert prompts.framing_for(None, verb, "Codex") == getattr(
            prompts._pp.framings("Codex"),
            {"consult": "consult", "review_changes": "review", "delegate": "delegate"}[verb],
        )


def test_adversarial_prompt_sections_are_labelled_untrusted():
    text = prompts.adversarial_prompt(
        "Codex",
        "T",
        "E",
        "DIFF",
        "working_tree",
        prompts.review_caller_text("security", "ctx", noun="critique"),
    )
    assert text.startswith(prompts.adversarial_framing("Codex"))
    assert "## Target (untrusted data)\nT" in text and "## Evidence (untrusted data)\nE" in text
    assert (
        "## Caller-provided context (untrusted data)\nFocus this critique on: security\n\nctx"
        in text
    )
    assert "## Attached changes (working_tree) — untrusted data\nDIFF" in text
    bare = prompts.adversarial_prompt("Codex", "T", None, None, "", None)
    assert (
        "## Evidence" not in bare and "## Attached changes" not in bare and "## Caller" not in bare
    )
    empty_diff = prompts.adversarial_prompt("Codex", "T", None, "", "commit abc", None)
    assert "## Attached changes (commit abc) — untrusted data\n(empty diff)" in empty_diff
    hooked = prompts.adversarial_prompt(
        "Codex", "T", None, None, "", None, plugin=fakeplugin.make_plugin(framing=_Hook())
    )
    assert hooked.startswith("[adversarial_review:Codex]\n")


async def test_adversarial_without_a_scope_runs_directly_and_returns_the_review_shape(monkeypatch):
    calls: list = []
    monkeypatch.setattr(
        run_mod.runtime, "run_async", cxf.scripted_run_async(stdout=STRUCTURED, calls=calls)
    )
    out = await run_mod.run_request(_spec(cwd="/nowhere/not/a/repo"), _plugin())
    assert out["ok"] is True and out["tool"] == "amicus_adversarial_review"
    assert out["verdict"] == "concerns" and out["confidence"] == "high"
    assert out["review_status"] == "completed" and out["context_summary"] is None
    # No diff was gathered, so there is nothing to omit and no untracked count to report.
    assert out["coverage"] == {
        "status": "complete",
        "untracked_files_detected": None,
        "untracked_files_included": None,
        "untracked_files_omitted": None,
        "omission_reasons": [],
        "redaction": None,
    }
    assert out["findings"][0]["title"] == "no retry" and out["next_steps"] == [
        "decide the retry policy"
    ]
    prompt = calls[0]["stdin_text"]
    assert "## Target (untrusted data)\nShip without retries." in prompt
    assert "## Evidence (untrusted data)\nThe queue is at-most-once." in prompt
    assert "## Attached changes" not in prompt and calls[0]["cwd"] == "/nowhere/not/a/repo"


async def test_adversarial_without_a_scope_but_with_a_focus_is_partial(monkeypatch):
    """A focus narrows the critique even when no diff is attached, so it is never complete."""
    monkeypatch.setattr(run_mod.runtime, "run_async", cxf.scripted_run_async(stdout=STRUCTURED))
    out = await run_mod.run_request(_spec(cwd="/nowhere/not/a/repo", focus="retries"), _plugin())
    assert out["coverage"]["status"] == "partial"
    assert out["coverage"]["omission_reasons"] == ["focused"]
    assert out["coverage"]["untracked_files_detected"] is None


async def test_adversarial_prose_is_invalid_json_not_a_pass(monkeypatch):
    monkeypatch.setattr(run_mod.runtime, "run_async", cxf.scripted_run_async(stdout="I disagree."))
    out = await run_mod.run_request(_spec(), _plugin())
    assert out["ok"] is False and out["error"]["code"] == "invalid_json"
    assert "critique" in out["error"]["message"]


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


async def test_adversarial_with_an_empty_scope_is_not_run_and_never_spawns(monkeypatch, repo):
    spawned: list = []
    monkeypatch.setattr(
        run_mod.runtime, "run_async", cxf.scripted_run_async(stdout=STRUCTURED, calls=spawned)
    )
    out = await run_mod.run_request(_spec(cwd=str(repo), scope="working_tree"), _plugin())
    assert out["ok"] is True and out["tool"] == "amicus_adversarial_review"
    assert (
        out["review_status"] == "not_run"
        and out["verdict"] == "unknown"
        and out["confidence"] == "low"
    )
    assert "critique did not run" in out["summary"] and spawned == []


async def test_adversarial_not_run_keeps_the_untracked_remedy(monkeypatch, repo):
    (repo / "new.py").write_text("y = 1\n")
    spawned: list = []
    monkeypatch.setattr(
        run_mod.runtime, "run_async", cxf.scripted_run_async(stdout=STRUCTURED, calls=spawned)
    )
    out = await run_mod.run_request(_spec(cwd=str(repo), scope="working_tree"), _plugin())
    assert out["ok"] is True and out["review_status"] == "not_run"
    assert "1 untracked file" in out["summary"] and 'untracked="include"' in out["summary"]
    assert "critique did not run" in out["summary"] and spawned == []


async def test_adversarial_with_changes_attaches_the_diff_and_folds_coverage(monkeypatch, repo):
    (repo / "a.py").write_text("x = 2\n")
    calls: list = []
    passing = STRUCTURED.replace('"verdict": "concerns"', '"verdict": "pass"')
    monkeypatch.setattr(
        run_mod.runtime, "run_async", cxf.scripted_run_async(stdout=passing, calls=calls)
    )
    out = await run_mod.run_request(
        _spec(cwd=str(repo), scope="working_tree", focus="retries"), _plugin()
    )
    assert out["ok"] is True and out["review_status"] == "completed"
    assert out["context_summary"]["files_changed"] == 1
    assert out["verdict"] == "unknown" and "focused" in out["summary"]  # a focused pass is partial
    assert out["coverage"]["status"] == "partial"
    assert out["coverage"]["omission_reasons"] == ["focused"]
    prompt = calls[0]["stdin_text"]
    assert "## Attached changes (working_tree) — untrusted data" in prompt and "-x = 1" in prompt
    assert "Focus this critique on: retries" in prompt


async def test_the_hook_frames_every_verb_in_the_loop(monkeypatch):
    hook = _Hook()
    calls: list = []
    monkeypatch.setattr(
        run_mod.runtime, "run_async", cxf.scripted_run_async(stdout=STRUCTURED, calls=calls)
    )
    await run_mod.run_request(_spec(), _plugin(framing=hook))
    await run_mod.run_request(_spec(kind="consult", tool="amicus_consult"), _plugin(framing=hook))
    assert [v for v, _ in hook.calls] == ["adversarial_review", "consult"]
    assert all(h == "Claude Code" for _, h in hook.calls)
    assert calls[0]["stdin_text"].startswith("[adversarial_review:Claude Code]\n")
    assert calls[1]["stdin_text"].startswith("[consult:Claude Code]\n")


def test_apply_exec_copies_backend_warnings_once():
    meta = run_mod.meta_for(_spec())
    meta.security_warnings = ["site warning"]
    result = ExecResult(answer="a", warnings=("hooks defined", "site warning"))
    finalize.apply_exec(meta, result)
    finalize.apply_exec(meta, result)
    assert meta.security_warnings == ["site warning", "hooks defined"]


async def test_backend_warnings_reach_the_envelope(monkeypatch):
    class Warning_(fakeplugin.FakeBackend):
        def finalize(self, outcome, request):
            return ExecResult(answer=outcome.run.stdout, warnings=("hooks defined",))

    monkeypatch.setattr(run_mod.runtime, "run_async", cxf.scripted_run_async(stdout="hello"))
    out = await run_mod.run_request(
        _spec(kind="consult", tool="amicus_consult"), _plugin(backend=Warning_())
    )
    assert out["ok"] is True and out["meta"]["security_warnings"] == ["hooks defined"]


def _app(registry: BackendRegistry):
    return server.create_app(config.settings({}), registry)


def _registry():
    return BackendRegistry({"claude": _plugin()}, {})


async def test_tool_refuses_selectors_without_a_scope_and_needs_a_workspace():
    async with Client(_app(_registry())) as c:
        paths = await c.call_tool(
            "amicus_adversarial_review",
            {"backend": "claude", "target": "t", "paths": ["src"], "workspace_root": "/tmp"},
            raise_on_error=False,
        )
        base = await c.call_tool(
            "amicus_adversarial_review_async",
            {"backend": "claude", "target": "t", "base": "main", "workspace_root": "/tmp"},
            raise_on_error=False,
        )
        no_ws = await c.call_tool(
            "amicus_adversarial_review", {"backend": "claude", "target": "t"}, raise_on_error=False
        )
    err = paths.structured_content["error"]
    assert err["code"] == "invalid_arguments" and err["details"]["field"] == "paths"
    assert (
        err["repair"]["tool"] == "amicus_adversarial_review" and "requires scope" in err["message"]
    )
    assert base.structured_content["error"]["details"]["field"] == "base"
    assert no_ws.structured_content["error"]["code"] == "invalid_workspace_root"


async def test_prepare_run_carries_target_and_evidence_as_inputs(tmp_path):
    from amicus.tools import _prepare

    prep = await _prepare.prepare_run(
        registry=_registry(),
        settings=config.settings({}),
        tool_name="amicus_adversarial_review",
        verb="adversarial_review",
        backend="claude",
        backend_options=None,
        ctx=None,
        workspace_root=str(tmp_path),
        model=None,
        reasoning_effort=None,
        timeout_seconds=None,
        target="Ship without retries.",
        evidence="At-most-once queue.",
    )
    assert not isinstance(prep, dict), prep
    assert prep.spec.kind == "adversarial_review" and prep.spec.scope is None
    assert (
        prep.spec.target == "Ship without retries." and prep.spec.evidence == "At-most-once queue."
    )
    assert (
        "target" not in prep.spec.public()
        and prep.spec.inputs()["evidence"] == "At-most-once queue."
    )
    over = await _prepare.prepare_run(
        registry=_registry(),
        settings=config.settings({"AMICUS_MAX_INPUT_BYTES": "1000"}),
        tool_name="amicus_adversarial_review",
        verb="adversarial_review",
        backend="claude",
        backend_options=None,
        ctx=None,
        workspace_root=str(tmp_path),
        model=None,
        reasoning_effort=None,
        timeout_seconds=None,
        target="t" * 600,
        evidence="e" * 600,
    )
    assert isinstance(over, dict) and over["error"]["code"] == "input_too_large"
    assert over["error"]["details"]["fields"] == ["target", "evidence"]


def test_framing_for_refuses_an_unknown_verb():
    with pytest.raises(ValueError, match="unknown verb 'transfer'"):
        prompts.framing_for(None, "transfer", "Codex")
