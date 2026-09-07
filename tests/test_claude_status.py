"""The readiness probe: config problems, the override, version, auth, help drift, the
API-key-ignored warning."""

from __future__ import annotations

from pontonier.conventions.preflight import FlagSupport
from tests.support import claudefixtures as cf

from amicus.backends.claude import cli, status


def _pin(monkeypatch, version="2.1.263 (Claude Code)", auth=True):
    monkeypatch.setattr(cli, "claude_version", lambda binary, **kw: version)
    monkeypatch.setattr(cli, "auth_status", lambda binary, mode, **kw: auth)


def test_installed_and_authenticated(pinned_claude_bin, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    plugin, _ = cf.make_backend()
    _pin(monkeypatch)
    report = plugin.status.probe()
    assert report.installed is True and report.authenticated is True
    assert report.version == "2.1.263 (Claude Code)" and report.warnings == ()


def test_not_installed_when_the_version_probe_fails(pinned_claude_bin, monkeypatch):
    plugin, _ = cf.make_backend()
    _pin(monkeypatch, version=None)
    report = plugin.status.probe()
    assert report.installed is False and report.version is None and report.authenticated is None


def test_unusable_override_is_reported_without_spawning(monkeypatch):
    plugin, _ = cf.make_backend({"AMICUS_CLAUDE_BIN": "/nonexistent/claude"})

    def boom(*a, **k):
        raise AssertionError("must not spawn")

    monkeypatch.setattr(cli, "claude_version", boom)
    report = plugin.status.probe()
    assert report.installed is False and any("AMICUS_CLAUDE_BIN" in w for w in report.warnings)


def test_warnings_for_version_help_drift_config_and_ignored_key(pinned_claude_bin, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    plugin, _ = cf.make_backend(
        {"AMICUS_CLAUDE_ACCESS": "bogus"},
        flags=FlagSupport(supported=frozenset({"--output-format"}), help_parsed=True),
    )
    _pin(monkeypatch, version="3.0.0 (Claude Code)", auth=False)
    report = plugin.status.probe()
    assert report.installed is True and report.authenticated is False
    assert status.VERSION_WARNING in report.warnings
    assert status.API_KEY_IGNORED_WARNING in report.warnings
    assert any(
        "did not list expected flags" in w and "--append-system-prompt" in w
        for w in report.warnings
    )
    assert any("AMICUS_CLAUDE_ACCESS" in w for w in report.warnings)


def test_bare_mode_reports_the_key_requirement(pinned_claude_bin, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    plugin, _ = cf.make_backend({"AMICUS_CLAUDE_CONFIG_MODE": "bare"})
    _pin(monkeypatch, auth=False)
    report = plugin.status.probe()
    assert status.BARE_NEEDS_KEY_WARNING in report.warnings
