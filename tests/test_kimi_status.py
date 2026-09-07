"""The Kimi readiness probe: installed/version/auth plus advisory warnings."""

from __future__ import annotations

from pontonier.core.runtime import BINARY_NOT_FOUND, CommandRun
from tests.support import kimifixtures as kf

from amicus.backends.kimi import status as st

HELP = (
    "  -p, --prompt <prompt>\n  --output-format <format>\n  --agent-file <path>\n"
    "  -m, --model <model>\n  --skills-dir <dir>\n"
)
PROVIDERS = '{"providers": {"p": {"apiKey": "sk-x"}}, "models": {}}'


def _probe_with(
    monkeypatch, *, version="0.41.0\n", providers=PROVIDERS, provider_exit=0, help_text=HELP
):
    def fake(cmd, timeout_seconds, **k):
        if cmd[1:] == ["--version"]:
            return (
                CommandRun(version, "", 0, 1, False)
                if version
                else CommandRun("", BINARY_NOT_FOUND, 127, 1, False)
            )
        if cmd[1:] == ["provider", "list", "--json"]:
            return CommandRun(providers, "", provider_exit, 1, False)
        return CommandRun(help_text, "", 0, 1, False)

    monkeypatch.setattr(st.cli.runtime, "run_sync_capture", fake)
    monkeypatch.setattr(st.preflight.runtime, "run_sync_capture", fake)


def test_ready_report(pinned_kimi_bin, monkeypatch):
    _probe_with(monkeypatch)
    plugin, _ = kf.make_backend()
    del plugin.help_probe.flag_support
    rep = plugin.status.probe()
    assert rep.installed and rep.version == "0.41.0" and rep.authenticated is True
    assert rep.warnings == ()


def test_unsupported_version_missing_flags_and_bad_extra_args_warn(pinned_kimi_bin, monkeypatch):
    _probe_with(monkeypatch, version="0.30.0\n", help_text="  --prompt <p>\n")
    plugin, _ = kf.make_backend({"AMICUS_KIMI_EXTRA_ARGS": "-p x", "MOONBRIDGE_MODEL": "m"})
    del plugin.help_probe.flag_support
    rep = plugin.status.probe()
    joined = "\n".join(rep.warnings)
    assert rep.installed and st.VERSION_WARNING in joined and "--agent-file" in joined
    assert "AMICUS_KIMI_EXTRA_ARGS is invalid" in joined and "read from legacy" in joined


def test_not_installed_bad_override_and_no_provider(pinned_kimi_bin, monkeypatch, tmp_path):
    _probe_with(monkeypatch, version=None)
    rep = kf.make_backend()[0].status.probe()
    assert rep.installed is False and rep.authenticated is None and rep.version is None
    bad = kf.make_backend({"AMICUS_KIMI_BIN": str(tmp_path / "missing")})[0].status.probe()
    assert bad.installed is False and any("AMICUS_KIMI_BIN" in w for w in bad.warnings)
    _probe_with(monkeypatch, providers='{"providers": {}}')
    plugin, _ = kf.make_backend()
    del plugin.help_probe.flag_support
    assert plugin.status.probe().authenticated is False
