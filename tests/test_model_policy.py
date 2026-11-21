"""AMICUS_DENY_MODELS (#547): parsing, pre-spend enforcement and discovery."""

from __future__ import annotations

from dataclasses import replace

import pytest
from tests.support import fakeplugin

from amicus import config
from amicus.config import model_policy
from amicus.plugin import OptionSpec
from amicus.registry import BackendRegistry
from amicus.request import IDENTITY_EXCLUDE
from amicus.sdk.conventions.preflight import FlagSupport
from amicus.tools import _prepare, discovery


def _settings(raw: str | None, **extra: str):
    env = dict(extra)
    if raw is not None:
        env["AMICUS_DENY_MODELS"] = raw
    return config.settings(env)


@pytest.mark.parametrize(
    ("raw", "backend", "selector", "denied"),
    [
        ("claude:*opus-5-0*", "claude", "claude-OPUS-5-0-20260101", True),
        ("claude:*opus-5-0*", "codex", "claude-opus-5-0", False),
        (" PI : openrouter/deepseek/* ", "pi", "openrouter/deepseek/v4/pro", True),
        ("pi:openrouter/deepseek/*", "pi", "openrouter/qwen/x", False),
        ("*:*mini*", "codex", "gpt-5-mini", True),
        ("codex:gpt-5", "codex", "gpt-5.4", False),
    ],
)
def test_match_semantics(raw, backend, selector, denied):
    policy = model_policy.parse(raw)
    assert isinstance(policy, model_policy.ModelPolicy)
    assert (policy.denied_by(backend, selector) is not None) is denied


@pytest.mark.parametrize(
    ("raw", "fragment"),
    [
        ("claude:x,gpt", "entry 2 has no ':'"),
        ("kimi:x", "entry 1 names no backend"),
        ("codex:  ", "entry 1 has an empty model glob"),
        ("codex:${MODEL}", "entry 1 holds an unexpanded"),
    ],
)
def test_malformed_lists_name_the_entry_and_never_echo_it(raw, fragment):
    out = model_policy.parse(raw)
    assert isinstance(out, str) and fragment in out and "AMICUS_DENY_MODELS" in out
    assert "gpt" not in out.replace(fragment, "") or "gpt" not in raw


def test_blank_and_unset_are_inactive_and_blank_entries_skip():
    assert model_policy.parse(None).rules == () and model_policy.parse("  ").rules == ()
    assert model_policy.parse("codex:a,, ,pi:b").rules == (("codex", "a"), ("pi", "b"))


def test_settings_report_a_malformed_list_as_a_non_fatal_config_error():
    s = _settings("nope")
    assert s.model_policy_error and s.model_policy_error in s.config_errors
    assert not s.fatal_errors


def _registry(model_default=None, flag_support=None):
    overrides = {"options": (OptionSpec("model", "model", frozenset({"consult"}), model_default),)}
    if flag_support is not None:

        class _Probe:
            def flag_support(self):
                return flag_support

        overrides["help_probe"] = _Probe()
    return BackendRegistry({"codex": fakeplugin.make_plugin("codex", **overrides)}, {})


async def _prep(tmp_path, settings, registry=None, **kw):
    base = dict(
        registry=registry or _registry(),
        settings=settings,
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


async def test_an_explicit_denied_model_is_refused_with_a_models_repair(tmp_path):
    out = await _prep(tmp_path, _settings("codex:gpt-5*"), model="GPT-5.4")
    err = out["error"]
    assert err["code"] == "model_denied" and err["details"]["field"] == "model"
    assert (
        err["repair"]["tool"] == "amicus_consult"
        and "amicus_models" in err["repair"]["alternative"]
    )
    assert err["temporary"] is False


async def test_a_denied_configured_default_is_refused(tmp_path):
    out = await _prep(tmp_path, _settings("codex:gpt-5*"), registry=_registry("gpt-5.4"))
    assert out["error"]["code"] == "model_denied"


async def test_an_explicit_allowed_model_overrides_a_denied_default(tmp_path):
    prep = await _prep(
        tmp_path, _settings("codex:gpt-5*"), registry=_registry("gpt-5.4"), model="o9"
    )
    assert isinstance(prep, _prepare.Prepared)
    assert prep.spec.model == "o9" and prep.spec.require_model_flag is True


async def test_no_selector_is_refused_only_where_rules_apply(tmp_path):
    out = await _prep(tmp_path, _settings("codex:x"))
    assert out["error"]["code"] == "model_denied" and "names no model" in out["error"]["message"]
    prep = await _prep(tmp_path, _settings("pi:x"))
    assert isinstance(prep, _prepare.Prepared) and prep.spec.require_model_flag is False


async def test_a_dropped_model_flag_is_refused_with_its_own_repair(tmp_path):
    reg = _registry(flag_support=FlagSupport(frozenset(), help_parsed=True))
    out = await _prep(tmp_path, _settings("codex:x"), registry=reg, model="ok")
    err = out["error"]
    assert err["code"] == "model_denied" and err["details"]["reason"] == "model_flag_unsupported"
    assert err["repair"]["next_step"] == "install_backend"
    # Without rules the help gate keeps its old silent-drop behavior.
    assert isinstance(
        await _prep(tmp_path, _settings(None), registry=reg, model="ok"), _prepare.Prepared
    )


async def test_a_malformed_list_fails_closed_and_a_placeholder_wins(tmp_path):
    out = await _prep(tmp_path, _settings("codex"), model="ok")
    assert out["error"]["code"] == "model_policy_invalid"
    assert out["error"]["repair"]["tool"] == "amicus_backends"
    out = await _prep(tmp_path, _settings("${AMICUS_DENY_MODELS}"), model="ok")
    assert out["error"]["code"] == "unexpanded_env_placeholder"


def test_the_flag_bit_is_not_part_of_a_keyed_identity():
    assert "require_model_flag" in IDENTITY_EXCLUDE


def test_backends_report_policy_state_and_a_denied_default():
    reg = _registry("gpt-5.4")
    for raw, state in (("codex:gpt-5*", "active"), ("pi:x", "inactive"), ("bad", "invalid")):
        out = discovery.backends_payload(_settings(raw), reg, [], "codex", detail="summary")
        info = out["backends"][0]["model_policy"]
        assert info["state"] == state
        if state == "active":
            assert info == {"state": "active", "deny_patterns": ["gpt-5*"], "default_denied": True}
    out = discovery.backends_payload(
        _settings("${AMICUS_DENY_MODELS}"), reg, [], "codex", detail="summary"
    )
    assert out["backends"][0]["model_policy"]["state"] == "invalid"


def _catalog_registry(truncated: bool):
    from amicus.plugin import ModelEntry, ModelListing

    listing = ModelListing(
        models=(ModelEntry(slug="gpt-5.4"), ModelEntry(slug="o9")),
        source="static",
        truncated=truncated,
    )

    class _Reader:
        def read(self):
            return listing

    return BackendRegistry({"codex": fakeplugin.make_plugin("codex", models=_Reader())}, {})


@pytest.mark.parametrize("truncated", [False, True])
def test_models_omit_denied_rows_and_the_resource_matches_the_tool(truncated):
    reg = _catalog_registry(truncated)
    out = discovery.models_payload(reg, "codex", _settings("codex:gpt-*"))
    assert [m["slug"] for m in out["models"]] == ["o9"]
    assert out["hidden_by_policy"] == 1 and out["model_policy"] == "active"
    assert out["truncated"] is truncated
    if truncated:
        assert "these 1 are not denied" in out["truncation_hint"]
    plain = discovery.models_payload(reg, "codex", _settings(None))
    assert plain["hidden_by_policy"] == 0 and len(plain["models"]) == 2


def test_dataclass_replace_keeps_policy():
    s = replace(_settings("codex:x"), host_name="h")
    assert s.model_policy.patterns_for("codex") == ("x",)
