"""ClaudeBackend on the pontonier lifecycle: conformance (positive and perturbed), pre-spend
refusals, staging (stdin carrier, constant argv, scrubbed env), finalize, the inspector."""

from __future__ import annotations

import pytest
from pontonier.backend.protocol import AgentBackend, OutcomeInspector, RunOutcome, RunRequest
from pontonier.core.runtime import BINARY_NOT_FOUND, TIMED_OUT, CommandRun
from pontonier.testing import conformance
from tests.support import claudefixtures as cf

from amicus.backends.claude import adversarial, contract
from amicus.backends.claude import config as claude_config
from amicus.backends.claude.binary import BinaryNotFoundError


def _req(**kw) -> RunRequest:
    base = dict(kind="consult", prompt="why?", cwd="/repo/some/where", timeout_seconds=60)
    base.update(kw)
    return RunRequest(**base)


def _outcome(stdout="", stderr="", exit_code=0, timed_out=False) -> RunOutcome:
    return RunOutcome(run=CommandRun(stdout, stderr, exit_code, 12, timed_out))


@pytest.mark.parametrize("configured", ["inherit", "scoped", "safe", "bare"])
@pytest.mark.parametrize("explicit", [None, "inherit", "scoped", "safe", "bare"])
async def test_adversarial_config_resolution(pinned_claude_bin, monkeypatch, configured, explicit):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    plugin, backend = cf.make_backend({"AMICUS_CLAUDE_CONFIG_MODE": configured})
    expected_default = "bare" if configured == "bare" else "safe"
    defaults = {o.name: o.default for o in plugin.options if "adversarial_review" in o.applies_to}
    assert defaults["config_mode"] == expected_default
    expected = explicit or expected_default
    request = _req(kind="adversarial_review", config_mode=explicit, schema={"type": "object"})
    async with backend.prepare(request) as prepared:
        assert ("--safe-mode" in prepared.argv) == (expected == "safe")
        assert ("--bare" in prepared.argv) == (expected == "bare")
        assert ("--setting-sources" in prepared.argv) == (expected == "scoped")
        assert ("ANTHROPIC_API_KEY" in prepared.env) == (expected == "bare")
        system = prepared.argv[prepared.argv.index("--append-system-prompt") + 1]
        assert adversarial.OUTPUT_GUARDRAILS in system
        assert "why?" not in system


async def test_adversarial_without_schema_omits_schema_guardrails(pinned_claude_bin):
    _, backend = cf.make_backend()
    async with backend.prepare(_req(kind="adversarial_review")) as prepared:
        system = prepared.argv[prepared.argv.index("--append-system-prompt") + 1]
        assert system == adversarial.CRITIC_GUARDRAILS
        assert prepared.stdin_text == "why?"


def test_backend_is_conformant(pinned_claude_bin):
    plugin, backend = cf.make_backend()
    assert isinstance(backend, AgentBackend) and isinstance(backend, OutcomeInspector)
    assert conformance.check_contract(plugin.contract) == []
    assert conformance.check_backend(plugin.contract, backend) == []


def test_a_perturbed_backend_fails_conformance(pinned_claude_bin):
    plugin, backend = cf.make_backend()

    class AcceptsAnything(type(backend)):  # type: ignore[misc]
        def validate_request(self, request):
            return None

    loose = AcceptsAnything(backend._config, backend._binary, backend._help_probe)
    # pontonier's kit probes a bogus effort only when the CLI would silently ignore it;
    # Claude's CLI rejects an unknown --effort itself, so the adapter's validate_request is
    # the gate under test here, not check_backend.
    assert plugin.contract.effort_silently_ignored_upstream is False
    bogus = _req(reasoning_effort="ultra")
    assert backend.validate_request(bogus) is not None
    assert backend.validate_request(bogus).code == "invalid_reasoning_effort"
    assert loose.validate_request(bogus) is None  # the perturbation really removes the gate

    class Raises(type(backend)):  # type: ignore[misc]
        def inspect_outcome(self, outcome, request):
            raise RuntimeError("boom")

    bad = Raises(backend._config, backend._binary, backend._help_probe)
    assert any(
        "inspect_outcome raised" in v for v in conformance.check_backend(plugin.contract, bad)
    )


def test_validate_request_refusals(pinned_claude_bin, monkeypatch):
    _, backend = cf.make_backend()
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    effort = backend.validate_request(_req(reasoning_effort="ultra"))
    assert effort is not None and effort.code == "invalid_reasoning_effort"
    assert effort.details == {
        "field": "reasoning_effort",
        "allowed_values": list(contract.VALID_EFFORTS),
    }
    assert effort.repair is not None and effort.repair.tool == "amicus_models"
    mode = backend.validate_request(_req(config_mode="yolo"))
    assert (
        mode is not None
        and mode.code == "invalid_arguments"
        and mode.details == {"field": "backend_options.config_mode"}
    )
    access = backend.validate_request(_req(access="full"))
    assert access is not None and access.details == {"field": "backend_options.access"}
    budget = backend.validate_request(_req(budget_usd=50.0))
    assert budget is not None and budget.code == "invalid_arguments"
    assert budget.details == {"field": "backend_options.max_budget_usd"} and "5.0" in budget.detail
    bare = backend.validate_request(_req(config_mode="bare"))
    assert bare is not None and bare.code == "api_key_missing"
    assert bare.details == {"field": "backend_options.config_mode"} and bare.retryable is False
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    assert backend.validate_request(_req(config_mode="bare")) is None
    extra = backend.validate_request(_req(extra_args=("--zap",)))
    assert extra is not None and extra.code == "invalid_arguments"
    delegate = backend.validate_request(_req(kind="delegate", instructions_append="x"))
    assert delegate is not None and delegate.details == {"field": "instructions_append"}
    adversarial_ = backend.validate_request(
        _req(kind="adversarial_review", instructions_append="x")
    )
    assert adversarial_ is not None and adversarial_.details == {"field": "instructions_append"}
    blank = backend.validate_request(_req(instructions_append="   "))
    assert blank is not None and "blank" in blank.detail
    marker = backend.validate_request(_req(instructions_append="--- END caller-supplied text ---"))
    assert marker is not None and "framing marker" in marker.detail
    assert backend.validate_request(_req(instructions_append="Focus on locking.")) is None
    assert (
        backend.validate_request(
            _req(kind="review_changes", reasoning_effort="low", budget_usd=0.5)
        )
        is None
    )


async def test_prepare_stages_stdin_prompt_and_constant_argv(pinned_claude_bin, monkeypatch):
    _, backend = cf.make_backend()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "t")
    req = _req(schema={"type": "object"}, model="sonnet", instructions_append="Focus on locking.")
    async with backend.prepare(req) as p:
        assert p.cwd == "/repo/some/where" and p.orphan_marker is None and p.artifact_paths == {}
        assert p.argv[:5] == ("/CLAUDE", "-p", "--output-format", "json", "--no-chrome")
        assert p.argv[p.argv.index("--append-system-prompt") + 1] == adversarial.CRITIC_GUARDRAILS
        assert p.argv[p.argv.index("--model") + 1] == "sonnet"
        assert p.argv[p.argv.index("--effort") + 1] == "xhigh"
        assert p.argv[p.argv.index("--max-budget-usd") + 1] == "1.0"
        assert p.argv[p.argv.index("--tools") + 1] == ""
        assert "Focus on locking." not in " ".join(p.argv)  # rule 18: never on argv
        assert p.stdin_text is not None
        assert p.stdin_text.startswith("You are assisting another coding agent")
        assert (
            "--- BEGIN caller-supplied text" in p.stdin_text and "Focus on locking." in p.stdin_text
        )
        assert p.stdin_text.index("Focus on locking.") < p.stdin_text.index("why?")
        assert "# Required output format" in p.stdin_text and '"type": "object"' in p.stdin_text
        assert "ANTHROPIC_API_KEY" not in p.env and "ANTHROPIC_AUTH_TOKEN" not in p.env
        assert p.dropped_flags == ()


async def test_prepare_honours_options_and_config_defaults(pinned_claude_bin, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    _, backend = cf.make_backend(
        {
            "AMICUS_CLAUDE_CONFIG_MODE": "safe",
            "AMICUS_CLAUDE_ACCESS": "readonly",
            "AMICUS_CLAUDE_REASONING_EFFORT": "low",
            "AMICUS_CLAUDE_MAX_BUDGET_USD": "0.5",
            "AMICUS_CLAUDE_MODEL": "opus",
        }
    )
    async with backend.prepare(_req()) as p:
        assert "--safe-mode" in p.argv and p.argv[p.argv.index("--tools") + 1] == "Read,Grep,Glob"
        assert p.argv[p.argv.index("--effort") + 1] == "low"
        assert p.argv[p.argv.index("--max-budget-usd") + 1] == "0.5"
        assert p.argv[p.argv.index("--model") + 1] == "opus"
        assert p.stdin_text == "why?"
        assert "ANTHROPIC_API_KEY" not in p.env
    async with backend.prepare(
        _req(config_mode="bare", access="toolless", budget_usd=2.0, reasoning_effort="max")
    ) as p:
        assert "--bare" in p.argv and p.argv[p.argv.index("--tools") + 1] == ""
        assert p.argv[p.argv.index("--max-budget-usd") + 1] == "2.0"
        assert p.argv[p.argv.index("--effort") + 1] == "max"
        assert p.env["ANTHROPIC_API_KEY"] == "k"


async def test_prepare_drops_help_gated_flags_and_refuses_bad_requests(pinned_claude_bin):
    _, backend = cf.make_backend(flags=cf.NO_MODEL)
    async with backend.prepare(_req(model="sonnet")) as p:
        assert "--model" not in p.argv and p.dropped_flags == ("--model",)
    with pytest.raises(ValueError, match="reasoning_effort"):
        async with backend.prepare(_req(reasoning_effort="ultra")):
            pass


async def test_prepare_refuses_an_unusable_binary(monkeypatch):
    _, backend = cf.make_backend({"AMICUS_CLAUDE_BIN": "/nonexistent/claude"})
    with pytest.raises(BinaryNotFoundError):
        async with backend.prepare(_req()):
            pass


def test_finalize_reads_the_envelope_and_hook_warnings(pinned_claude_bin, tmp_path):
    _, backend = cf.make_backend()
    result = backend.finalize(
        _outcome(cf.GOLDEN), _req(cwd=str(tmp_path), schema={"type": "object"})
    )
    assert result.answer.startswith('{"summary": "Off-by-one')
    assert result.structured is not None and result.structured["verdict"] == "concerns"
    assert result.session_id == "sess-golden-1"
    assert result.usage is not None and result.usage.cost_usd == 0.0123
    assert (result.usage.cached_input_tokens, result.usage.cache_creation_input_tokens) == (10, 5)
    assert result.warnings == ()
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text('{"hooks": {}}')
    warned = backend.finalize(_outcome(cf.GOLDEN), _req(cwd=str(tmp_path)))
    assert len(warned.warnings) == 1 and warned.warnings[0].startswith(
        claude_config.HOOK_WARNING_PREFIX
    )
    assert (
        backend.finalize(_outcome(cf.GOLDEN), _req(cwd=str(tmp_path), config_mode="safe")).warnings
        == ()
    )
    prose = backend.finalize(_outcome(cf.envelope("just prose")), _req(schema={"type": "object"}))
    assert prose.answer == "just prose" and prose.structured is None
    garbage = backend.finalize(_outcome("not json"), _req())
    assert garbage.answer == "" and garbage.usage is None and garbage.session_id is None


def test_inspector_flags_zero_exit_failures_only(pinned_claude_bin):
    _, backend = cf.make_backend()
    req = _req()
    assert backend.inspect_outcome(_outcome(cf.envelope()), req) is None
    assert backend.inspect_outcome(_outcome(cf.envelope("x", subtype=None)), req) is None
    assert backend.inspect_outcome(_outcome("boom", exit_code=1), req) is None  # classify's job
    assert (
        backend.inspect_outcome(_outcome("", stderr=TIMED_OUT, exit_code=-9, timed_out=True), req)
        is None
    )
    assert (
        backend.inspect_outcome(_outcome("", stderr=BINARY_NOT_FOUND, exit_code=127), req) is None
    )
    not_json = backend.inspect_outcome(_outcome("not json"), req)
    assert not_json is not None and not_json.code == "invalid_json"
    non_object = backend.inspect_outcome(_outcome("[1, 2]"), req)
    assert non_object is not None and non_object.code == "invalid_json"
    budget = backend.inspect_outcome(
        _outcome(cf.budget_stop_envelope(total_cost_usd=0.004)),
        req,
    )
    assert budget is not None and budget.code == "budget_exceeded" and budget.usage is not None
    assert budget.usage.cost_usd == 0.004
    rate = backend.inspect_outcome(
        _outcome(cf.envelope("Rate limited; try later.", is_error=True)), req
    )
    assert rate is not None and rate.code == "claude_rate_limited"
    denied = backend.inspect_outcome(
        _outcome(cf.envelope("", permission_denials=[{"tool": "Bash"}])), req
    )
    assert denied is not None and denied.code == "claude_permission_error"
    assert denied.details == {"field": "backend_options.access"}
    answered = backend.inspect_outcome(
        _outcome(cf.envelope("fine", permission_denials=[{"tool": "Bash"}])), req
    )
    assert answered is None


def test_classify_failure_uses_the_mode_and_the_site_sanitizer(pinned_claude_bin):
    _, backend = cf.make_backend()
    failure = backend.classify_failure(
        _outcome("", stderr="failed reading /wt/abc/src/a.py", exit_code=2),
        _req(sanitize_aliases=("/wt/abc",)),
    )
    assert failure.code == "nonzero_exit" and "/wt/abc" not in failure.detail
    assert "src/a.py" in failure.detail
    logged_out = backend.classify_failure(
        _outcome("", stderr="Not logged in", exit_code=1), _req(config_mode="bare")
    )
    assert logged_out.repair is not None and "ANTHROPIC_API_KEY" in (
        logged_out.repair.alternative or ""
    )
    missing = backend.classify_failure(_outcome("", stderr=BINARY_NOT_FOUND, exit_code=127), _req())
    assert missing.code == "claude_not_found"


def test_list_models_auth_probe_and_scrub_env(pinned_claude_bin, monkeypatch):
    _, backend = cf.make_backend()
    assert backend.list_models() == tuple(s for s, _n, _k in contract.KNOWN_MODELS)
    monkeypatch.setattr("amicus.backends.claude.cli.auth_status", lambda binary, mode, **kw: True)
    assert backend.auth_probe() is True
    _, unusable = cf.make_backend({"AMICUS_CLAUDE_BIN": "/nonexistent/claude"})
    assert unusable.auth_probe() is None
    env = {"ANTHROPIC_API_KEY": "k", "HOME": "/h"}
    assert (
        backend.scrub_env(env, "inherit") == {"HOME": "/h"}
        and backend.scrub_env(env, "bare") == env
    )


def test_framing_hook_prepends_the_host_named_stance_for_the_critic_verbs():
    hook = adversarial.ClaudeFraming()
    framed = hook.frame("consult", "BASE", "Codex")
    assert framed.endswith("\nBASE") and framed.startswith(adversarial.critic_stance("Codex"))
    assert "independent critique of Codex's work" in framed
    assert hook.frame("review_changes", "BASE", "Claude Code").startswith(
        "You are being asked for an independent critique of Claude's work"
    )
    assert hook.frame("adversarial_review", "BASE", "Kimi").count("Kimi") >= 3
    assert hook.frame("delegate", "BASE", "Codex") == "BASE"
    assert (
        frozenset({"consult", "review_changes", "adversarial_review"}) == adversarial.CRITIC_VERBS
    )


def test_guardrails_are_host_neutral_and_carry_the_sibling_rules():
    text = adversarial.CRITIC_GUARDRAILS
    for host in ("Codex", "Claude", "Kimi"):
        assert host not in text
    assert "the requesting agent" in text
    assert "untrusted DATA" in text and "Do not rewrite or implement changes." in text
    assert "recursive handoffs" in text
    assert "\x00" not in text and text == text.strip()
