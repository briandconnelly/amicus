"""The Claude readiness probe behind amicus_backends (ported from claude-in-codex
`claude_status`): version, login, help drift, the API-key posture."""

from __future__ import annotations

from typing import TYPE_CHECKING

from amicus.backends.claude import cli
from amicus.backends.claude.config import api_key_present, version_supported
from amicus.plugin import StatusReport

if TYPE_CHECKING:  # pragma: no cover
    from pontonier.conventions.preflight import HelpProbe

    from amicus.backends.claude.binary import ClaudeBinary
    from amicus.backends.claude.config import ClaudeConfig

VERSION_WARNING = (
    "The installed claude major version is outside the versions amicus was built against; "
    "paid calls still run, but the CLI contract may have drifted."
)
API_KEY_IGNORED_WARNING = (
    "ANTHROPIC_API_KEY is set but the default config_mode is a login mode "
    "(inherit/scoped/safe), which strips it; runs use the Claude login. Use "
    "backend_options.config_mode='bare' to run on the key."
)
BARE_NEEDS_KEY_WARNING = (
    "The default config_mode is bare, which runs only on ANTHROPIC_API_KEY, and the key is "
    "unset; every paid call will fail api_key_missing until it is set or the mode changes."
)


class ClaudeStatus:
    def __init__(self, config: ClaudeConfig, binary: ClaudeBinary, help_probe: HelpProbe) -> None:
        self._config = config
        self._binary = binary
        self._help_probe = help_probe

    def probe(self) -> StatusReport:
        warnings: list[str] = [*self._config.errors, *self._config.warnings]
        override_error = self._binary.override_error()
        if override_error is not None:
            return StatusReport(installed=False, warnings=(override_error, *warnings))
        binary = self._binary.resolve() or "claude"
        version = cli.claude_version(binary)
        if version is None:
            return StatusReport(installed=False, warnings=tuple(warnings))
        authenticated = cli.auth_status(binary, self._config.config_mode)
        if version_supported(version, self._config) is False:
            warnings.append(VERSION_WARNING)
        key = api_key_present()
        if key and self._config.config_mode != "bare":
            warnings.append(API_KEY_IGNORED_WARNING)
        if not key and self._config.config_mode == "bare":
            warnings.append(BARE_NEEDS_KEY_WARNING)
        fs = self._help_probe.flag_support(force=True)
        missing = self._help_probe.missing_expected_flags(fs)
        if missing:
            warnings.append(
                f"`claude --help` did not list expected flags: {', '.join(missing)}. "
                "The CLI contract may have drifted."
            )
        return StatusReport(
            installed=True,
            version=cli.version_display(version),
            authenticated=authenticated,
            warnings=tuple(warnings),
        )
