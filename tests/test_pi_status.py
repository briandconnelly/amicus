"""The pi readiness probe behind amicus_backends, against the fake pi executable: installed,
version and authentication, and the advisory warnings."""

from __future__ import annotations

import pytest

from amicus.backends import pi as pi_pkg
from amicus.backends.pi import contract
from amicus.backends.pi import status as st

MODEL = "openrouter/moonshotai/kimi-k3"


@pytest.fixture
def env(fake_pi, monkeypatch) -> dict[str, str]:
    for key in ("FAKE_PI_AUTH", "FAKE_PI_VERSION", "FAKE_PI_HELP_FILE", "AMICUS_PI_MODEL"):
        monkeypatch.delenv(key, raising=False)
    return {"AMICUS_PI_BIN": str(fake_pi), "AMICUS_PI_MODEL": MODEL}


def test_ready_report(env, fake_pi):
    rep = pi_pkg.plugin(env).status.probe()
    assert rep.installed is True and rep.version == "1.5.0" and rep.authenticated is True
    assert rep.warnings == ()


def test_no_configured_model_leaves_authentication_unknown(env):
    del env["AMICUS_PI_MODEL"]
    rep = pi_pkg.plugin(env).status.probe()
    assert rep.installed is True and rep.authenticated is None
    assert any("AMICUS_PI_MODEL" in w and "`model`" in w for w in rep.warnings)


@pytest.mark.parametrize(
    ("auth", "expected"),
    [
        ('{"status":"not_ready","provider":"openrouter","authType":"api_key"}', False),
        ('{"status":"invalid","provider":"openrouter","reason":"invalid_state"}', False),
        ('{"status":"weird"}', None),
        ("not json", None),
    ],
)
def test_auth_check_maps_onto_authenticated(env, monkeypatch, auth, expected):
    monkeypatch.setenv("FAKE_PI_AUTH", auth)
    assert pi_pkg.plugin(env).status.probe().authenticated is expected


def test_a_binary_gone_between_the_probes_is_unknown_not_unauthenticated(env, monkeypatch):
    """`missing` is a spawn failure, not a statement about credentials."""
    from amicus.backends.pi import cli

    monkeypatch.setattr(cli, "auth_status", lambda binary, model: "missing")
    rep = pi_pkg.plugin(env).status.probe()
    assert rep.installed is True and rep.authenticated is None
    assert st.UNRESOLVED_MODEL_WARNING not in rep.warnings


def test_unresolvable_configured_model_is_unauthenticated_and_says_why(env, monkeypatch):
    monkeypatch.setenv(
        "FAKE_PI_AUTH", f'{{"status":"invalid","provider":"{MODEL}","reason":"invalid_state"}}'
    )
    rep = pi_pkg.plugin(env).status.probe()
    assert rep.authenticated is False
    assert any("AMICUS_PI_MODEL" in w and "resolve" in w for w in rep.warnings)


def test_unsupported_version_warns(env, monkeypatch):
    monkeypatch.setenv("FAKE_PI_VERSION", "1.4.9")
    rep = pi_pkg.plugin(env).status.probe()
    assert rep.installed is True and rep.version == "1.4.9"
    assert st.VERSION_WARNING in rep.warnings


def test_help_probe_carries_the_suppression_flags(env, fake_pi):
    plugin = pi_pkg.plugin(env)
    assert plugin.help_probe.help_argv == (str(fake_pi), "--help", *contract.SUPPRESSION_FLAGS)
    # The fake answers --help only when every suppression flag follows it, so no missing-flag
    # warning means the probe really sent them.
    assert not any("--help" in w for w in plugin.status.probe().warnings)


def test_missing_help_flags_warn(env, monkeypatch, tmp_path):
    thin = tmp_path / "help.txt"
    thin.write_text("  --model <pattern>\n")
    monkeypatch.setenv("FAKE_PI_HELP_FILE", str(thin))
    joined = "\n".join(pi_pkg.plugin(env).status.probe().warnings)
    assert "`pi --help` did not list expected flags" in joined and "--no-session" in joined


def test_not_installed_and_bad_override(env, tmp_path):
    rep = pi_pkg.plugin({**env, "AMICUS_PI_BIN": str(tmp_path / "missing")}).status.probe()
    assert rep.installed is False and rep.authenticated is None and rep.version is None
    assert any("AMICUS_PI_BIN" in w for w in rep.warnings)
    broken = tmp_path / "pi"
    broken.write_text("#!/bin/sh\nexit 3\n")
    broken.chmod(0o755)
    rep = pi_pkg.plugin({**env, "AMICUS_PI_BIN": str(broken)}).status.probe()
    assert rep.installed is False and rep.version is None
