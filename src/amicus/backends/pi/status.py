"""The pi readiness probe behind amicus_backends: `pi --version` for installed, `pi auth check`
on AMICUS_PI_MODEL for authenticated, and advisory warnings for the version and help probe.

Authentication is a property of a model's provider, not of pi, so with no AMICUS_PI_MODEL it
is unknown and the report says that calls must pass `model`."""

from __future__ import annotations

from typing import TYPE_CHECKING

from amicus.backends.pi import cli
from amicus.backends.pi.config import probe_cwd, version_supported
from amicus.plugin import StatusReport
from amicus.sdk.conventions import preflight

if TYPE_CHECKING:  # pragma: no cover
    from amicus.backends.pi.binary import PiBinary
    from amicus.backends.pi.config import PiConfig
    from amicus.sdk.conventions.preflight import HelpProbe

VERSION_WARNING = (
    "The installed pi version is outside the versions amicus was built against; paid calls "
    "still run, but the CLI contract may have drifted."
)
NO_MODEL_WARNING = (
    "AMICUS_PI_MODEL is not set, so authentication is unknown: pi authenticates per provider, "
    "and every call must pass `model` as an exact provider/id (see amicus_models)."
)
UNRESOLVED_MODEL_WARNING = (
    "pi cannot resolve the provider of AMICUS_PI_MODEL; a call that uses it will be refused "
    "before any spend (see amicus_models)."
)


class PiStatus:
    def __init__(self, config: PiConfig, binary: PiBinary, help_probe: HelpProbe) -> None:
        self._config = config
        self._binary = binary
        self._help_probe = help_probe

    def probe(self) -> StatusReport:
        warnings: list[str] = [*self._config.errors, *self._config.warnings]
        override_error = self._binary.override_error()
        if override_error is not None:
            return StatusReport(installed=False, warnings=(override_error, *warnings))
        if self._config.agent_dir_error is not None:
            # Every probe would read a pi configuration resolved against the probe directory,
            # not the one a paid run would use, so none runs: installed is the binary resolving.
            return StatusReport(
                installed=self._binary.resolve() is not None,
                warnings=(self._config.agent_dir_error, *warnings),
            )
        binary = self._binary.resolve() or "pi"
        cwd = probe_cwd(self._config)
        version = cli.pi_version(binary, cwd=cwd) if cwd is not None else None
        if version is None:
            return StatusReport(installed=False, warnings=tuple(warnings))
        authenticated: bool | None = None
        if self._config.model is None:
            warnings.append(NO_MODEL_WARNING)
        else:
            auth = cli.auth_status(binary, self._config.model, cwd=cwd)
            if auth == "ready":
                authenticated = True
            elif auth in ("not_ready", "unresolved"):
                authenticated = False
            if auth == "unresolved":
                warnings.append(UNRESOLVED_MODEL_WARNING)
        if version_supported(version, self._config) is False:
            warnings.append(VERSION_WARNING)
        fs = self._help_probe.flag_support(force=True)
        missing = self._help_probe.missing_expected_flags(fs)
        if missing:
            warnings.append(
                f"`pi --help` did not list expected flags: {', '.join(missing)}. "
                "The CLI contract may have drifted."
            )
        return StatusReport(
            installed=True,
            version=cli.version_display(version),
            authenticated=authenticated,
            warnings=tuple(warnings),
        )


__all__ = ["NO_MODEL_WARNING", "VERSION_WARNING", "PiStatus", "preflight"]
