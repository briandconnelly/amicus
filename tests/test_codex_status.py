"""The Codex readiness probe: installed/version/auth plus advisory warnings."""

from __future__ import annotations

from pontonier.core.runtime import BINARY_NOT_FOUND, CommandRun
from tests.support import codexfixtures as cf

from amicus.backends.codex import status as st


def _probe_with(
    monkeypatch,
    *,
    version="codex-cli 0.153.4\n",
    login_exit=0,
    help_text=(
        "--sandbox --cd --json --output-last-message --skip-git-repo-check --ephemeral "
        "--ignore-user-config --ignore-rules --add-dir --output-schema --disable "
        "--strict-config --model"
    ),
):
    def fake(cmd, timeout_seconds, **k):
        if cmd[1:] == ["--version"]:
            return (
                CommandRun(version, "", 0, 1, False)
                if version
                else CommandRun("", BINARY_NOT_FOUND, 127, 1, False)
            )
        if cmd[1:] == ["login", "status"]:
            return CommandRun("Logged in using ChatGPT", "", login_exit, 1, False)
        return CommandRun(help_text, "", 0, 1, False)

    monkeypatch.setattr(st.cli.runtime, "run_sync_capture", fake)
    monkeypatch.setattr(st.preflight.runtime, "run_sync_capture", fake)


def test_ready_report(pinned_codex_bin, monkeypatch):
    _probe_with(monkeypatch)
    plugin, _ = cf.make_backend()
    rep = plugin.status.probe()
    assert rep.installed and rep.version == "codex-cli 0.153.4" and rep.authenticated is True
    assert rep.warnings == ()


def test_unsupported_version_missing_flags_and_bad_extra_args_warn(pinned_codex_bin, monkeypatch):
    _probe_with(monkeypatch, version="codex-cli 0.100.0\n", help_text="--json")
    plugin, _ = cf.make_backend(
        {"AMICUS_CODEX_EXTRA_ARGS": "--bogus 1", "CODEX_IN_CLAUDE_MODEL": "m"}
    )
    # cf.make_backend pins help_probe.flag_support to a fixed FlagSupport for the argv tests;
    # undo that here so this test's stubbed `codex exec --help` output drives the real
    # missing-flags computation it asserts on.
    del plugin.help_probe.flag_support
    rep = plugin.status.probe()
    assert rep.installed and rep.authenticated is True
    joined = "\n".join(rep.warnings)
    assert st.VERSION_WARNING in joined and "--sandbox" in joined
    assert "AMICUS_CODEX_EXTRA_ARGS is invalid" in joined and "read from legacy" in joined


def test_not_installed_and_bad_override(pinned_codex_bin, monkeypatch, tmp_path):
    _probe_with(monkeypatch, version=None)
    plugin, _ = cf.make_backend()
    rep = plugin.status.probe()
    assert rep.installed is False and rep.authenticated is None and rep.version is None
    bad = cf.make_backend({"AMICUS_CODEX_BIN": str(tmp_path / "missing")})[0].status.probe()
    assert bad.installed is False and any("AMICUS_CODEX_BIN" in w for w in bad.warnings)


def test_logged_out(pinned_codex_bin, monkeypatch):
    _probe_with(monkeypatch, login_exit=1)
    rep = cf.make_backend()[0].status.probe()
    assert rep.installed and rep.authenticated is False
