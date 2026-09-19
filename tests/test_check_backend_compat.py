"""`scripts/check_backend_compat.py`, driven by the fake CLIs and never the network (#188)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).parent.parent / "scripts" / "check_backend_compat.py"
_spec = importlib.util.spec_from_file_location("check_backend_compat", _SCRIPT)
assert _spec is not None and _spec.loader is not None
compat = importlib.util.module_from_spec(_spec)
sys.modules["check_backend_compat"] = compat
_spec.loader.exec_module(compat)


@pytest.fixture
def fakes(clean_env, fake_codex, fake_kimi, fake_claude):
    clean_env.setenv("AMICUS_CODEX_BIN", str(fake_codex))
    clean_env.setenv("AMICUS_KIMI_BIN", str(fake_kimi))
    clean_env.setenv("AMICUS_CLAUDE_BIN", str(fake_claude))
    return clean_env


def _no_network(backend: str) -> str | None:
    """What a lookup returns when it cannot read a latest release."""
    return None


def _current(report_version: dict[str, str]):
    """A lookup that says whatever is installed IS the latest, so nothing else fails."""
    return report_version.get


def _capture(root: Path, backend: str, version: str, help_text: str) -> None:
    folder = root / f"{backend}-help" / version
    folder.mkdir(parents=True)
    (folder / f"{backend}-help.txt").write_text(help_text)
    (folder / f"{backend}-version.txt").write_text(version + "\n")


def test_every_in_tree_backend_is_checked_and_a_clean_one_passes(fakes, tmp_path):
    reports = compat.check_all(tmp_path, latest=_no_network, offline=True)
    assert [r.backend for r in reports] == ["codex", "kimi", "claude"]
    for report in reports:
        assert report.installed and report.help_ok and report.declared, report.backend
        assert report.missing_flags == [], report
        # No capture exists under this empty docs root, and that is said, not passed over.
        assert report.capture is None and report.capture_state == "none"
        assert report.latest is None, "unknown stays unknown; it is never guessed"
        assert compat.problems(report) == [], report.backend


def test_a_capture_is_compared_to_the_live_help_and_the_newest_one_is_chosen(fakes, tmp_path):
    live = compat.check_backend("kimi", tmp_path, latest=_no_network)
    _capture(tmp_path, "kimi", "0.9.0", "an older capture\n")
    _capture(tmp_path, "kimi", "0.10.0", live.help_text)
    same = compat.check_backend("kimi", tmp_path, latest=_no_network)
    # 0.10.0 sorts after 0.9.0 as a version and before it as a string.
    assert same.capture is not None and same.capture.name == "0.10.0"
    assert same.capture_state == "identical" and same.help_diff == []
    # Re-wrapping and a trimmed trailing line are not a change: claude wraps its help to the
    # terminal width, and the committed kimi capture was trimmed.
    rewrapped = live.help_text.replace("  ", "\n      ", 3).rstrip("\n")
    _capture(tmp_path, "kimi", "0.10.1", rewrapped)
    assert compat.check_backend("kimi", tmp_path, latest=_no_network).capture_state == "identical"
    _capture(tmp_path, "kimi", "0.10.2", live.help_text.replace("Show help", "Display help"))
    assert compat.check_backend("kimi", tmp_path, latest=_no_network).capture_state == "reworded"
    # The capture is what was committed; the live help is what is installed. A flag only the
    # capture has was REMOVED upstream, and one only the live help has was ADDED.
    _capture(tmp_path, "kimi", "0.11.0", live.help_text + "  --gone-upstream    dropped since\n")
    drift = compat.check_backend("kimi", tmp_path, latest=_no_network)
    assert drift.capture_state == "flags_differ"
    assert drift.flags_removed == ["--gone-upstream"] and drift.flags_added == []
    assert any("--gone-upstream" in line for line in drift.help_diff)


def test_a_flag_amicus_always_sends_that_help_no_longer_lists_is_a_failure(fakes, tmp_path):
    ok = compat.check_backend("kimi", tmp_path, latest=_no_network)
    assert compat.problems(ok) == []
    assert "--agent-file" in ok.declared, "control: the flag is declared before it is dropped"
    dropped = compat.check_backend(
        "kimi",
        tmp_path,
        latest=_no_network,
        help_text=ok.help_text.replace("--agent-file", "--agent-phile"),
    )
    assert dropped.missing_flags == ["--agent-file"]
    assert any("--agent-file" in p for p in compat.problems(dropped))


def test_an_installed_version_behind_upstream_or_unsupported_is_a_failure(fakes, tmp_path):
    report = compat.check_backend("codex", tmp_path, latest=lambda _b: "9.9.9")
    assert [p for p in compat.problems(report) if "9.9.9" not in p] == []
    assert report.latest == "9.9.9" and report.version != "9.9.9"
    assert any("9.9.9" in p and "latest" in p for p in compat.problems(report))
    # The fake codex reports 0.153.4, which the contract supports, so no warning arrives.
    assert report.warnings == ()
    fakes.setenv("AMICUS_CODEX_SUPPORTED_VERSIONS", "0.1")
    unsupported = compat.check_backend("codex", tmp_path, latest=_no_network, offline=True)
    assert unsupported.warnings and any("warning" in p for p in compat.problems(unsupported))


def test_a_missing_cli_is_reported_not_crashed_on(clean_env, tmp_path):
    clean_env.setenv("AMICUS_KIMI_BIN", "/nonexistent/amicus-test-kimi")
    report = compat.check_backend("kimi", tmp_path, latest=_no_network)
    assert report.installed is False and report.help_text == ""
    assert any("not installed" in p for p in compat.problems(report))


def test_write_saves_a_capture_under_the_installed_version(fakes, tmp_path):
    report = compat.check_backend("kimi", tmp_path, latest=_no_network)
    folder = compat.write_capture(report, tmp_path)
    assert folder == tmp_path / "kimi-help" / report.version
    assert (folder / "kimi-help.txt").read_text() == report.help_text
    assert (folder / "kimi-version.txt").read_text().strip() == report.version
    again = compat.check_backend("kimi", tmp_path, latest=_no_network)
    assert again.capture_state == "identical"


def test_main_exits_nonzero_on_a_problem_and_zero_when_clean(fakes, tmp_path, capsys, monkeypatch):
    installed = {r.backend: r.version for r in compat.check_all(tmp_path, offline=True)}
    monkeypatch.setattr(compat, "latest_upstream", _current(installed))
    assert compat.main(["--docs-root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    for backend in ("codex", "kimi", "claude"):
        assert backend in out
    assert "carrier" in out.lower(), "the rule-18 re-check is prompted, since no script can do it"
    monkeypatch.setattr(compat, "latest_upstream", lambda _b: "9.9.9")
    assert compat.main(["--docs-root", str(tmp_path)]) == 1


def test_a_flag_that_survives_only_in_another_options_prose_is_missing(fakes, tmp_path):
    """The SDK's help parser takes every `--flag` token, which suits help-GATED flags, where
    a stray match sends a harmless flag. For a compatibility gate it is wrong: claude's help
    names `--mcp-config` inside two other options' descriptions, so dropping the option
    itself would go unnoticed. Only a declared option row counts."""
    live = compat.check_backend("kimi", tmp_path, latest=_no_network)
    row = next(line for line in live.help_text.splitlines() if "--agent-file" in line)
    prose = " " * 40 + "--agent-file is still named here, in a description."
    dropped = compat.check_backend(
        "kimi", tmp_path, latest=_no_network, help_text=live.help_text.replace(row, prose)
    )
    assert "--agent-file" in dropped.help_text, "control: the token is still in the text"
    assert "--agent-file" not in dropped.declared
    assert dropped.missing_flags == ["--agent-file"]


def test_declared_rows_are_read_in_each_clis_own_layout():
    text = (
        "Options:\n"
        "  -s, --sandbox <MODE>\n"
        "          Select the sandbox; see --not-an-option for details\n"
        "      --ephemeral\n"
        "  --allowedTools, --allowed-tools <tools...>\n"
        "  -c, --continue                        Continue the most recent\n"
        "                                        --resume <id>, continues that\n"
    )
    assert compat.declared_flags(text) == {
        "--sandbox",
        "--ephemeral",
        "--allowedTools",
        "--allowed-tools",
        "--continue",
    }


def test_help_that_could_not_be_read_is_a_failure_not_a_clean_run(fakes, tmp_path):
    """An empty probe used to mean "no flag is missing", because nothing was parsed."""
    blank = compat.check_backend("kimi", tmp_path, latest=_no_network, help_text="")
    assert blank.help_ok is False and blank.missing_flags == []
    assert any("--help" in p and "could not be read" in p for p in compat.problems(blank))
    # A help command that exits nonzero is not trusted even though it printed its usual
    # text: a CLI that prints usage on an argument error does exactly that.
    fakes.setenv("FAKE_KIMI_HELP_EXIT", "3")
    failing = compat.check_backend("kimi", tmp_path, latest=_no_network)
    assert failing.help_ok is False and failing.declared == frozenset()
    assert any("could not be read" in p for p in compat.problems(failing))


@pytest.mark.parametrize("state", [False, None])
def test_a_backend_that_is_not_authenticated_is_a_failure(fakes, tmp_path, state):
    """The evidence run needs all three logged in, and RELEASING.md says yes means so."""
    report = compat.check_backend("kimi", tmp_path, latest=_no_network)
    assert report.authenticated is True and compat.problems(report) == []
    report.authenticated = state
    assert any("authenticated" in p for p in compat.problems(report))


def test_an_unreadable_latest_is_expected_for_kimi_and_a_failure_for_an_npm_backend(
    fakes, tmp_path
):
    kimi = compat.check_backend("kimi", tmp_path, latest=_no_network)
    assert kimi.latest is None and compat.problems(kimi) == []
    codex = compat.check_backend("codex", tmp_path, latest=_no_network)
    assert codex.latest is None
    assert any("latest" in p and "npm" in p for p in compat.problems(codex))
    # --offline asked for no lookup, so its absence is advisory and said so, not a failure.
    offline = compat.check_backend("codex", tmp_path, latest=_no_network, offline=True)
    assert compat.problems(offline) == []


def test_an_ambient_support_override_cannot_vouch_for_an_unchecked_version(fakes, tmp_path):
    """The same hole #113 closed in the live gate: `status.warnings` reads the EFFECTIVE
    configuration, so an operator override naming the installed version silences the
    warning. The shipped contract is what a release vouches for, so it is checked directly."""
    ok = compat.check_backend("codex", tmp_path, latest=_no_network, offline=True)
    assert ok.version == "0.153.4" and ok.builtin_supported is True
    assert compat.problems(ok) == []
    # The fake is 0.153.4. Pretend the shipped contract stops short of it, and let the
    # environment claim support for it anyway.
    fakes.setenv("AMICUS_CODEX_SUPPORTED_VERSIONS", "0.153")
    fakes.setattr("amicus.backends.codex.contract.SUPPORTED_VERSIONS", frozenset({(0, 152)}))
    hidden = compat.check_backend("codex", tmp_path, latest=_no_network, offline=True)
    assert hidden.warnings == (), "control: the override did silence the status warning"
    assert hidden.builtin_supported is False
    assert any("built-in contract" in p for p in compat.problems(hidden))


@pytest.mark.parametrize(
    ("backend", "version", "want"),
    [
        ("codex", "0.155.1", True),
        ("codex", "0.999.0", False),
        ("kimi", "0.43.9", True),
        ("kimi", "0.999.0", False),
        ("claude", "2.9.9", True),
        ("claude", "3.0.0", False),
        ("codex", "nightly", False),
    ],
)
def test_builtin_support_is_read_from_each_contract(backend, version, want):
    assert compat.builtin_supported(backend, version) is want
