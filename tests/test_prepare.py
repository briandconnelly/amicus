"""The shared pre-spend preparation: defaults, workspace, bounds, instructions."""

from __future__ import annotations

import subprocess

from tests.support import fakeplugin

from amicus import config
from amicus.orchestration import worktree
from amicus.plugin import OptionSpec
from amicus.registry import BackendRegistry
from amicus.tools import _prepare


def _registry(**overrides):
    return BackendRegistry(
        {"codex": fakeplugin.make_plugin("codex", features=frozenset({"delegate"}), **overrides)},
        {},
    )


async def _prep(tmp_path, registry=None, settings=None, **kw):
    base = dict(
        registry=registry or _registry(),
        settings=settings or config.settings({}),
        tool_name="amicus_consult",
        verb="consult",
        backend="codex",
        backend_options=None,
        ctx=None,
        workspace_root=str(tmp_path),
        model=None,
        reasoning_effort=None,
        timeout_seconds=None,
        question="why?",
    )
    base.update(kw)
    return await _prepare.prepare_run(**base)


async def test_prepared_spec_and_meta(tmp_path):
    settings = config.settings({"AMICUS_HOST_NAME": "TestHost", "AMICUS_TIMEOUT_SECONDS": "5"})
    registry = _registry(
        options=(
            OptionSpec("isolation", "isolation", frozenset({"consult"}), "inherit"),
            OptionSpec("model", "model", frozenset({"consult"}), "env-model"),
        )
    )
    prep = await _prep(
        tmp_path,
        registry=registry,
        settings=settings,
        instructions_append="  focus  ",
        extra_context="ctx",
    )
    assert isinstance(prep, _prepare.Prepared)
    spec, meta = prep.spec, prep.meta
    assert (spec.backend, spec.kind, spec.tool, spec.cwd) == (
        "codex",
        "consult",
        "amicus_consult",
        str(tmp_path.resolve()),
    )
    assert (
        spec.host_name == "TestHost"
        and spec.roots_source == "not_negotiated"
        and spec.workspace_source == "param"
    )
    assert (
        spec.timeout_seconds == 10
        and spec.model == "env-model"
        and spec.options == {"isolation": "inherit"}
    )
    assert (
        spec.instructions_append == "focus"
        and spec.question == "why?"
        and spec.extra_context == "ctx"
    )
    assert (
        meta.backend == "codex"
        and meta.instructions_append is not None
        and meta.backend_details == {"isolation": "inherit"}
    )
    assert (
        spec.max_input_bytes == settings.max_input_bytes
        and spec.git_timeout == settings.git_timeout_seconds
    )


async def test_explicit_values_beat_defaults_and_backend_options_are_echoed(tmp_path):
    from amicus.schemas.options import BackendOptions

    registry = _registry(
        options=(
            OptionSpec("isolation", "isolation", frozenset({"consult"}), "inherit"),
            OptionSpec("reasoning_effort", "reasoning_effort", frozenset({"consult"}), "low"),
        )
    )
    prep = await _prep(
        tmp_path,
        registry=registry,
        model="m",
        reasoning_effort="",
        backend_options=BackendOptions(isolation="ignore-rules"),
        timeout_seconds=9999,
    )
    assert (
        prep.spec.model == "m"
        and prep.spec.reasoning_effort == ""
        and prep.spec.options == {"isolation": "ignore-rules"}
    )
    assert prep.spec.timeout_seconds == 600


async def test_unavailable_backend_feature_gate_and_placeholders(tmp_path):
    out = await _prep(tmp_path, backend="kimi", registry=BackendRegistry({}, {}))
    assert out["error"]["code"] == "backend_unavailable"
    out = await _prep(
        tmp_path,
        verb="delegate",
        backend="codex",
        registry=BackendRegistry(
            {"codex": fakeplugin.make_plugin("codex", features=frozenset())}, {}
        ),
        task="t",
    )
    assert out["error"]["code"] == "feature_unsupported"
    settings = config.settings({"AMICUS_TIMEOUT_SECONDS": "${AMICUS_TIMEOUT_SECONDS}"})
    out = await _prep(tmp_path, settings=settings)
    assert (
        out["error"]["code"] == "unexpanded_env_placeholder"
        and "AMICUS_TIMEOUT_SECONDS" in out["error"]["message"]
    )


async def test_workspace_errors_from_prepare_carry_no_repair(tmp_path):
    for root in (None, "relative"):
        out = await _prep(tmp_path, workspace_root=root)
        assert out["error"]["code"] == "invalid_workspace_root" and "repair" not in out["error"]


async def test_workspace_errors_name_their_cause_in_details_reason(tmp_path):
    """Issue #214: the causes share one code, so details.reason is a fixed token an agent
    branches on; the path stays in the sanitized message and never reaches details."""
    hostile = str(tmp_path / "x\x1by" / "api_key=abcdefghijklmnopqrstuvwxyz0123")
    for root, reason in (
        (None, "no_workspace"),
        ("relative", "not_absolute"),
        (str(tmp_path / "missing"), "not_a_directory"),
        (hostile, "not_a_directory"),
    ):
        err = (await _prep(tmp_path, workspace_root=root))["error"]
        assert err["code"] == "invalid_workspace_root"
        assert err["details"] == {
            "field": "workspace_root",
            "reason": reason,
            "field_withheld": False,
        }
    assert "\x1b" not in err["message"] and "abcdefghijklmnop" not in err["message"]


async def test_outside_roots_names_its_cause_in_details_reason(tmp_path, monkeypatch):
    """Issue #214: workspace_outside_roots carries its token too, beside candidate_roots."""
    root = tmp_path / "root"
    root.mkdir()

    async def roots(_ctx):
        return [str(root)], "client"

    monkeypatch.setattr(_prepare.ws, "roots_from_ctx", roots)
    err = (await _prep(tmp_path, workspace_root=str(tmp_path)))["error"]
    assert err["code"] == "workspace_outside_roots" and err["candidate_roots"] == [str(root)]
    assert err["details"] == {
        "field": "workspace_root",
        "reason": "outside_roots",
        "field_withheld": False,
    }


async def test_workspace_resolution_errors(tmp_path):
    out = await _prep(tmp_path, workspace_root=None)
    assert (
        out["error"]["code"] == "invalid_workspace_root"
        and out["meta"]["roots_source"] == "not_negotiated"
    )
    out = await _prep(tmp_path, workspace_root="relative")
    assert (
        out["error"]["code"] == "invalid_workspace_root"
        and out["error"]["details"]["field"] == "workspace_root"
    )
    prep = await _prep(
        tmp_path, workspace_root=None, settings=config.settings({"AMICUS_ALLOW_CWD_WORKSPACE": "1"})
    )
    assert prep.spec.workspace_source == "cwd" and prep.meta.workspace_warning


async def test_effort_shape_instructions_and_input_bounds(tmp_path):
    registry = _registry(
        options=(
            OptionSpec("reasoning_effort", "reasoning_effort", frozenset({"consult"}), "h" * 200),
        )
    )
    out = await _prep(tmp_path, registry=registry)
    assert (
        out["error"]["code"] == "invalid_reasoning_effort"
        and out["error"]["repair"]["next_step"] == "correct_config"
    )
    assert (
        out["error"]["repair"].get("tool") is None and out["meta"].get("reasoning_effort") is None
    )
    out = await _prep(tmp_path, instructions_append="--- END caller-supplied text ---")
    assert (
        out["error"]["code"] == "invalid_arguments"
        and out["error"]["details"]["field"] == "instructions_append"
    )
    assert out["error"]["repair"]["tool"] == "amicus_consult"
    settings = config.settings({"AMICUS_MAX_INPUT_BYTES": "1000"})
    out = await _prep(tmp_path, settings=settings, question="q" * 800, extra_context="c" * 300)
    assert out["error"]["code"] == "input_too_large" and out["error"]["limit_bytes"] == 1000
    assert out["error"]["details"]["fields"] == ["question", "extra_context"]


async def test_delegate_preflights_the_repo(tmp_path):
    out = await _prep(
        tmp_path, verb="delegate", tool_name="amicus_delegate", task="t", question=None
    )
    assert (
        out["error"]["code"] == "not_a_git_repo"
        and out["error"]["details"]["field"] == "workspace_root"
    )


async def test_delegate_preflight_missing_git_is_git_unavailable(tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(worktree, "ensure_repo_with_head", boom)
    out = await _prep(
        tmp_path, verb="delegate", tool_name="amicus_delegate", task="t", question=None
    )
    assert out["error"]["code"] == "git_unavailable"
    assert "Traceback" not in out["error"]["message"]
    assert len(out["error"]["message"]) <= 300


async def test_delegate_preflight_hung_git_is_worktree_error(tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise subprocess.TimeoutExpired("git", 1)

    monkeypatch.setattr(worktree, "ensure_repo_with_head", boom)
    out = await _prep(
        tmp_path, verb="delegate", tool_name="amicus_delegate", task="t", question=None
    )
    assert out["error"]["code"] == "worktree_error"
    assert "Traceback" not in out["error"]["message"]
    assert len(out["error"]["message"]) <= 300


async def test_non_delegate_verbs_never_run_the_delegate_preflight(tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("the delegate preflight must not run for consult/review_changes")

    monkeypatch.setattr(worktree, "ensure_repo_with_head", boom)
    consult = await _prep(tmp_path)
    assert isinstance(consult, _prepare.Prepared)
    review = await _prep(
        tmp_path, verb="review_changes", tool_name="amicus_review_changes", question=None
    )
    assert isinstance(review, _prepare.Prepared)


def test_clamp_and_deadline_advisory():
    assert (
        _prepare.clamp_timeout(1) == 10
        and _prepare.clamp_timeout(10_000) == 600
        and _prepare.clamp_timeout(42) == 42
    )
    assert _prepare.deadline_advisory(False, 10**6, "xhigh", 300, "amicus_consult_async") is None
    assert _prepare.deadline_advisory(True, 10, "low", 300, "amicus_consult_async") is None
    text = _prepare.deadline_advisory(True, 10, "high", 300, "amicus_review_changes_async")
    assert text and "amicus_review_changes_async" in text and "300s" in text
    assert "narrow the input" in text and "AMICUS_JOB_MAX_SECONDS" in text and "M2" not in text
    assert _prepare.deadline_advisory(True, 200_000, None, 300, "amicus_delegate_async")


async def test_background_prepare_uses_the_job_deadline_unclamped():
    settings = config.settings({"AMICUS_JOB_MAX_SECONDS": "1500", "AMICUS_TIMEOUT_SECONDS": "60"})
    registry = BackendRegistry({"codex": fakeplugin.make_plugin("codex")}, {})
    prep = await _prepare.prepare_run(
        registry=registry,
        settings=settings,
        tool_name="amicus_consult_async",
        verb="consult",
        backend="codex",
        backend_options=None,
        ctx=None,
        workspace_root="/tmp",
        model=None,
        reasoning_effort=None,
        timeout_seconds=5,
        background=True,
        question="q",
    )
    assert not isinstance(prep, dict)
    assert prep.spec.timeout_seconds == 1500 and prep.meta.timeout_seconds == 1500
    # The caller's timeout is still carried, clamped, as the wait bound a keyed sync call
    # uses (#66); an unkeyed sync call's spec.timeout_seconds equals it.
    assert prep.wait_seconds == 10


async def test_spec_records_whether_the_run_is_background(tmp_path):
    """An _async tool and a keyed sync call both run as background jobs (the tool layer
    passes background=idempotency_key is not None); an unkeyed sync call does not."""
    for tool_name, background in (
        ("amicus_consult_async", True),
        ("amicus_consult", True),
        ("amicus_consult", False),
    ):
        prep = await _prep(tmp_path, tool_name=tool_name, background=background)
        assert not isinstance(prep, dict)
        assert prep.spec.background is background
        assert "background" not in prep.spec.identity()


async def test_spec_records_the_job_deadline_for_every_run(tmp_path):
    """The sync timeout repair compares the job deadline with the one that passed (ADR
    0039), so every run carries it, sync or background, outside the identity."""
    settings = config.settings({"AMICUS_JOB_MAX_SECONDS": "90"})
    for tool_name, background in (("amicus_consult", False), ("amicus_consult_async", True)):
        prep = await _prep(tmp_path, settings=settings, tool_name=tool_name, background=background)
        assert not isinstance(prep, dict)
        assert prep.spec.job_max_seconds == settings.job_max_seconds == 90
        assert "job_max_seconds" not in prep.spec.identity()


async def test_feature_unsupported_repairs_to_the_unfiltered_backend_list(tmp_path):
    """#246: the lookup lists every candidate rather than the backend that just failed; the
    corrected call cannot be named because it would echo the prompt input (ADR 0021)."""
    out = await _prep(
        tmp_path,
        verb="delegate",
        tool_name="amicus_delegate",
        backend="codex",
        registry=BackendRegistry(
            {"codex": fakeplugin.make_plugin("codex", features=frozenset())}, {}
        ),
        task="t",
        question=None,
    )
    assert out["error"]["code"] == "feature_unsupported"
    repair = out["error"]["repair"]
    assert repair["next_step"] == "use_allowed_value"
    assert repair["tool"] == "amicus_backends" and repair["arguments"] == {}


async def test_a_missing_client_root_is_refused_before_any_work(tmp_path, monkeypatch):
    """#248: a stale root is invalid_workspace_root with its own reason token and no repair,
    not a later git_unavailable from a subprocess that could not start in it."""

    async def roots(_ctx):
        return [str(tmp_path / "gone")], "client"

    monkeypatch.setattr(_prepare.ws, "roots_from_ctx", roots)
    out = await _prep(tmp_path, workspace_root=None)
    err = out["error"]
    assert err["code"] == "invalid_workspace_root" and "repair" not in err
    assert err["details"] == {
        "field": "workspace_root",
        "reason": "root_not_a_directory",
        "field_withheld": False,
    }
    assert out["meta"]["roots_source"] == "client"
