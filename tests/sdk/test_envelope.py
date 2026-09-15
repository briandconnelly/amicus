"""Error taxonomy: code minting, rule coverage, and vocabulary parameterization."""

from __future__ import annotations

import pytest

from amicus.sdk.conventions import envelope

VOCAB = envelope.BackendErrorVocabulary(
    backend_id="kimi",
    display_name="Kimi",
    install_hint="Install the kimi CLI, then rerun kimi_status.",
    login_hint="Run `kimi login`, then rerun kimi_status.",
    status_tool="kimi_status",
)


def test_backend_codes_minted_per_id():
    assert envelope.backend_codes("codex") == {
        "codex_not_found",
        "codex_auth_required",
        "codex_auth_indeterminate",
        "codex_rate_limited",
    }


def test_feature_codes_transfer():
    assert envelope.feature_codes(frozenset({"transfer"})) == {
        "transfer_unsupported",
        "transfer_failed",
        "transfer_incomplete",
    }


def test_feature_codes_moonbridge_set():
    codes = envelope.feature_codes(frozenset({"model_validation", "empty_response_detection"}))
    assert codes == {"invalid_model", "empty_response"}


def test_unknown_features_mint_nothing():
    assert envelope.feature_codes(frozenset({"delegate", "made_up_thing"})) == frozenset()


def test_every_code_has_a_rule():
    features = frozenset({"transfer", "model_validation", "empty_response_detection"})
    rules = envelope.repair_rules(VOCAB, features)
    assert set(rules) == set(envelope.all_codes(VOCAB, features))


def test_rules_without_features_exclude_feature_codes():
    rules = envelope.repair_rules(VOCAB)
    assert "transfer_failed" not in rules
    assert "invalid_model" not in rules


def test_every_rule_uses_a_known_step():
    rules = envelope.repair_rules(
        VOCAB, frozenset({"transfer", "model_validation", "empty_response_detection"})
    )
    for code, rule in rules.items():
        assert rule.next_step in envelope.REPAIR_STEPS, code


def test_unknown_step_raises():
    with pytest.raises(ValueError, match="unknown repair step"):
        envelope.RepairRule("not_a_step", None, False, "nope")


def test_vocabulary_reaches_prose():
    rules = envelope.repair_rules(VOCAB)
    assert rules["kimi_not_found"].alternative == VOCAB.install_hint
    assert rules["kimi_auth_required"].alternative == VOCAB.login_hint
    assert "kimi_status" in rules["kimi_auth_indeterminate"].alternative
    assert "kimi_status" in rules["cli_contract_changed"].alternative
    assert "Kimi" in rules["kimi_rate_limited"].alternative


def test_auth_indeterminate_is_temporary_not_found_is_not():
    rules = envelope.repair_rules(VOCAB)
    # Load-bearing pair: the probe failing to answer clears itself; a missing
    # binary does not. Steering an indeterminate probe to `authenticate` would
    # be a false repair.
    assert rules["kimi_auth_indeterminate"].temporary
    assert rules["kimi_auth_indeterminate"].next_step == "inspect_and_retry"
    assert not rules["kimi_not_found"].temporary
    assert rules["kimi_not_found"].next_step == "install_backend"


def test_universal_codes_are_backend_free():
    for code in envelope.UNIVERSAL_CODES:
        assert not code.startswith(("codex_", "kimi_", "claude_")), code
        assert code not in envelope.FEATURE_CODES.get("transfer", ()), code
