"""The Codex readiness probe behind amicus_backends (ported from codex_status)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pontonier.conventions import preflight

from amicus.backends.codex import cli
from amicus.backends.codex.config import version_supported
from amicus.plugin import StatusReport

if TYPE_CHECKING:  # pragma: no cover
    from pontonier.conventions.preflight import HelpProbe

    from amicus.backends.codex.binary import CodexBinary
    from amicus.backends.codex.config import CodexConfig

VERSION_WARNING = (
    "The installed codex version is outside the versions amicus was built against; "
    "paid calls still run, but the CLI contract may have drifted."
)


class CodexStatus:
    def __init__(self, config: CodexConfig, binary: CodexBinary, help_probe: HelpProbe) -> None:
        self._config = config
        self._binary = binary
        self._help_probe = help_probe

    def probe(self) -> StatusReport:
        warnings: list[str] = [*self._config.errors, *self._config.warnings]
        if not self._config.extra_args.valid:
            warnings.append(f"AMICUS_CODEX_EXTRA_ARGS is invalid: {self._config.extra_args.error}.")
        override_error = self._binary.override_error()
        if override_error is not None:
            return StatusReport(installed=False, warnings=(override_error, *warnings))
        binary = self._binary.resolve() or "codex"
        version = cli.codex_version(binary)
        if version is None:
            return StatusReport(installed=False, warnings=tuple(warnings))
        authenticated, _detail = cli.login_status(binary)
        if version_supported(version, self._config) is False:
            warnings.append(VERSION_WARNING)
        fs = self._help_probe.flag_support(force=True)
        missing = self._help_probe.missing_expected_flags(fs)
        if missing:
            warnings.append(
                f"`codex exec --help` did not list expected flags: {', '.join(missing)}. "
                "The CLI contract may have drifted."
            )
        return StatusReport(
            installed=True,
            version=cli.version_display(version),
            authenticated=authenticated,
            warnings=tuple(warnings),
        )


__all__ = ["VERSION_WARNING", "CodexStatus", "preflight"]
