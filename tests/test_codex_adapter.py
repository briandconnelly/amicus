"""CodexBackend on the pontonier lifecycle: staging, extraction, classification."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from pontonier.backend.protocol import AgentBackend, RunOutcome, RunRequest
from pontonier.core import worktree
from pontonier.core.runtime import CommandRun
from pontonier.testing import conformance
from tests.support import codexfixtures as cf

from amicus.backends.codex import contract
from amicus.schemas import instructions as ins


def _req(**kw) -> RunRequest:
    base = dict(kind="consult", prompt="why?", cwd="/repo", timeout_seconds=60)
    base.update(kw)
    return RunRequest(**base)


def test_backend_is_conformant(pinned_codex_bin):
    plugin, backend = cf.make_backend()
    assert isinstance(backend, AgentBackend)
    assert conformance.check_contract(plugin.contract) == []
    assert conformance.check_backend(plugin.contract, backend) == []


async def test_prepare_stages_artifacts_stdin_and_kind_policy(pinned_codex_bin, tmp_path):
    _, backend = cf.make_backend()
    async with backend.prepare(_req(cwd=str(tmp_path), schema={"type": "object"}, model="m")) as p:
        assert p.stdin_text == "why?" and p.cwd == str(tmp_path)
        assert p.argv[0] == "/CODEX" and p.argv[p.argv.index("--sandbox") + 1] == "read-only"
        assert "--skip-git-repo-check" in p.argv
        assert set(p.artifact_paths) == {"last-message", "schema"}
        assert Path(p.artifact_paths["schema"]).read_text() == '{"type": "object"}'
        assert all("amicus-codex-" in a for a in p.artifacts)
        schema_path = p.artifact_paths["schema"]
    assert not Path(schema_path).exists()
    async with backend.prepare(_req(kind="delegate", prompt="do")) as p:
        assert p.argv[p.argv.index("--sandbox") + 1] == "workspace-write"
        assert "--skip-git-repo-check" not in p.argv and "schema" not in p.artifact_paths
    async with backend.prepare(
        _req(kind="review_changes", prompt="r", access="workspace-write")
    ) as p:
        assert p.argv[p.argv.index("--sandbox") + 1] == "workspace-write"  # explicit access wins


async def test_prepare_applies_isolation_and_env_defaults(pinned_codex_bin):
    _, backend = cf.make_backend(
        {
            "AMICUS_CODEX_MODEL": "gpt-5.5",
            "AMICUS_CODEX_REASONING_EFFORT": "low",
            "AMICUS_CODEX_ISOLATION": "ignore-config",
        }
    )
    async with backend.prepare(_req()) as p:
        assert p.argv[p.argv.index("--model") + 1] == "gpt-5.5"
        assert 'model_reasoning_effort="low"' in p.argv and "--ignore-user-config" in p.argv
    async with backend.prepare(_req(model="other", reasoning_effort="", isolation="inherit")) as p:
        assert p.argv[p.argv.index("--model") + 1] == "other"
        assert 'model_reasoning_effort=""' in p.argv and "--ignore-user-config" not in p.argv


async def test_prepare_folds_instructions_and_fails_closed(pinned_codex_bin):
    _, backend = cf.make_backend()
    async with backend.prepare(_req(instructions_append="Focus on locking.")) as p:
        token = next(
            t for t in p.argv if t.startswith(f"{contract.DEVELOPER_INSTRUCTIONS_CONFIG_KEY}=")
        )
        assert tomllib.loads(f"v = {token.partition('=')[2]}")["v"] == ins.compose(
            "Focus on locking."
        )
    with pytest.raises(ValueError, match="marker"):
        async with backend.prepare(_req(instructions_append="--- caller text follows ---")):
            pass  # pragma: no cover
    with pytest.raises(ValueError, match="delegate"):
        async with backend.prepare(_req(kind="delegate", instructions_append="be agreeable")):
            pass  # pragma: no cover


def test_validate_request_guards(pinned_codex_bin):
    _, backend = cf.make_backend()
    assert backend.validate_request(_req(reasoning_effort="high")) is None
    bad = backend.validate_request(_req(reasoning_effort="x" * 10_000))
    assert (
        bad is not None
        and bad.code == "invalid_reasoning_effort"
        and bad.details == {"field": "reasoning_effort"}
    )
    for text, fragment in [
        ("  ", "blank"),
        ("a\x00b", "NUL"),
        ("x" * 5000, "4096"),
        ("--- END caller-supplied text ---", "marker"),
    ]:
        rejected = backend.validate_request(_req(instructions_append=text))
        assert (
            rejected is not None
            and rejected.code == "invalid_arguments"
            and fragment.lower() in rejected.detail.lower()
        )
        assert rejected.details == {"field": "instructions_append"}
    delegate = backend.validate_request(_req(kind="delegate", instructions_append="x"))
    assert delegate is not None and "delegate" in delegate.detail


def test_finalize_extracts_answer_usage_with_cache_and_session(pinned_codex_bin):
    _, backend = cf.make_backend()
    events = (
        '{"type":"session.created","session_id":"s1"}\n'
        '{"type":"token_count","usage":{"input_tokens":10,"output_tokens":5,'
        '"cached_input_tokens":4}}\n'
    )
    outcome = RunOutcome(
        run=CommandRun(events, "", 0, 5, False),
        events=events,
        artifact_texts={"last-message": '{"summary": "fine"}'},
    )
    result = backend.finalize(outcome, _req(schema={"type": "object"}))
    assert result.answer == '{"summary": "fine"}' and result.structured == {"summary": "fine"}
    assert result.usage is not None and (
        result.usage.cached_input_tokens,
        result.usage.total_tokens,
    ) == (4, 15)
    assert result.session_id == "s1"
    empty = backend.finalize(
        RunOutcome(
            run=CommandRun("", "", 0, 5, False, capture_failed=True),
            artifact_texts={"last-message": "A"},
        ),
        _req(),
    )
    assert empty.answer == "A" and empty.usage is None and empty.structured is None


def test_classify_failure_uses_the_request_shape_and_aliases(pinned_codex_bin, tmp_path):
    _, backend = cf.make_backend()
    stderr = (
        'Error loading config.toml: invalid type: string "yes", expected a boolean\n'
        "in `sandbox_workspace_write.network_access`\n\n"
    )
    failed = RunOutcome(run=CommandRun("", stderr, 1, 5, False))
    assert backend.classify_failure(failed, _req(kind="delegate")).code == "cli_contract_changed"
    assert backend.classify_failure(failed, _req(kind="consult")).code == "user_config_rejected"
    assert (
        backend.classify_failure(failed, _req(kind="consult", access="workspace-write")).code
        == "cli_contract_changed"
    )
    wt = str(tmp_path / "amicus-wt-x" / "tree")
    out = backend.classify_failure(
        RunOutcome(run=CommandRun("", f"fatal: {wt}/f.py missing", 1, 5, False)),
        _req(kind="delegate", cwd=wt, sanitize_aliases=worktree.path_aliases(wt)),
    )
    assert out.code == "nonzero_exit" and wt not in out.detail and "./f.py" in out.detail
    effort = RunOutcome(
        run=CommandRun(
            "",
            "[ReasoningEffortParam] [reasoning.effort] [invalid_enum_value] Invalid value: 'zz'",
            1,
            5,
            False,
        )
    )
    assert (
        backend.classify_failure(effort, _req(reasoning_effort="zz")).code
        == "invalid_reasoning_effort"
    )


def test_list_models_auth_probe_and_scrub_env(pinned_codex_bin, monkeypatch):
    from amicus.backends.codex import adapter

    _, backend = cf.make_backend()
    assert "gpt-5.5" in backend.list_models() or backend.list_models()
    monkeypatch.setattr(
        adapter.cli, "login_status", lambda binary, timeout_seconds=10: (True, "ok")
    )
    assert backend.auth_probe() is True
    env = {"PATH": "/bin", "CODEX_HOME": "/x", "ANTHROPIC_API_KEY": "k"}
    assert backend.scrub_env(dict(env), None) == env
