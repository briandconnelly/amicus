"""Unit coverage for amicus.tools._meta: stability tiers, lifecycle _meta, annotations,
and the base Meta builder (exercised end-to-end once real tools land in Task 12)."""

from __future__ import annotations

from amicus import __version__, config
from amicus.schemas.fingerprint import LIFECYCLE_META_KEY
from amicus.schemas.results import ToolDeprecation
from amicus.tools import _meta


def test_the_override_table_is_empty_and_every_tool_inherits_the_server_tier():
    assert _meta.TOOL_STABILITY == {}
    assert _meta.SERVER_STABILITY == "experimental"
    for name in ("amicus_consult", "amicus_job_status", "amicus_delegate_async"):
        assert _meta.tool_stability(name) == "experimental"


def test_an_override_still_wins_over_the_server_tier(monkeypatch):
    """The seam the empty table leaves behind: it fills again when the server reaches a
    more mature tier than an individual tool."""
    monkeypatch.setattr(_meta, "SERVER_STABILITY", "stable")
    monkeypatch.setitem(_meta.TOOL_STABILITY, "amicus_job_status", "experimental")
    assert _meta.tool_stability("amicus_job_status") == "experimental"
    assert _meta.tool_stability("amicus_consult") == "stable"


def test_lifecycle_meta_carries_the_stability_tier():
    assert _meta.lifecycle_meta("amicus_consult") == {
        LIFECYCLE_META_KEY: {"stability": "experimental"}
    }


def test_server_lifecycle_meta_carries_the_server_wide_tier():
    assert _meta.server_lifecycle_meta() == {LIFECYCLE_META_KEY: {"stability": "experimental"}}


_SYNTHETIC = ToolDeprecation(
    since="0.5.0", removal_at_or_after="0.7.0", replaced_by="amicus_backends", migration="m"
)


def test_a_deprecated_tool_carries_the_marker_beside_its_tier(monkeypatch):
    """[9.stability-tiers]: deprecation is its own axis, so a deprecated tool keeps the tier
    it had and gains the marker; its replacement carries no marker at all. Nothing ships
    deprecated since `amicus_dry_run` was removed (#204), so the entry is synthetic."""
    assert _meta.lifecycle_meta("amicus_models")[LIFECYCLE_META_KEY] == {
        "stability": "experimental"
    }, "control: no marker before the entry exists"
    monkeypatch.setitem(_meta.DEPRECATED_TOOLS, "amicus_models", _SYNTHETIC)
    block = _meta.lifecycle_meta("amicus_models")[LIFECYCLE_META_KEY]
    assert block == {
        "stability": "experimental",
        "deprecation": {
            "since": "0.5.0",
            "removal_at_or_after": "0.7.0",
            "replaced_by": "amicus_backends",
            "migration": "m",
        },
    }
    replacement = _meta.lifecycle_meta("amicus_backends")[LIFECYCLE_META_KEY]
    assert replacement == {"stability": "experimental"}


def test_a_null_replaced_by_is_published_rather_than_dropped(monkeypatch):
    """[9.deprecation-marker] fixes the field set: a tool with no successor says so with a
    null, which an exclude_none dump would silently remove."""
    monkeypatch.setitem(
        _meta.DEPRECATED_TOOLS,
        "amicus_consult",
        ToolDeprecation(
            since="0.3.0", removal_at_or_after="0.5.0", replaced_by=None, migration="m"
        ),
    )
    marker = _meta.lifecycle_meta("amicus_consult")[LIFECYCLE_META_KEY]["deprecation"]
    assert marker == {
        "since": "0.3.0",
        "removal_at_or_after": "0.5.0",
        "replaced_by": None,
        "migration": "m",
    }
    assert _meta.deprecation_marker("amicus_consult") == marker


def _minor(version: str) -> tuple[int, int, int]:
    major, minor, micro = (int(part) for part in version.split("."))
    return major, minor, micro


def _window_problems(table: dict[str, ToolDeprecation]) -> list[str]:
    problems = []
    for name, deprecation in table.items():
        major, minor, micro = _minor(deprecation.since)
        if micro != 0 or _minor(deprecation.removal_at_or_after) != (major, minor + 2, 0):
            problems.append(f"{name}: window is not two minor releases")
        if deprecation.replaced_by == name or deprecation.replaced_by in table:
            problems.append(f"{name}: replaced by a deprecated tool")
    return problems


def test_every_window_spans_the_two_minor_releases_the_policy_promises():
    """amicus_capabilities.deprecation_policy: discoverable for two minor releases, so a
    deprecation in x.y.0 may be removed no earlier than x.(y+2).0. The shipped table is
    empty since #204, so the rule is shown to pass a good entry and fail two bad ones before
    it is trusted on the real table."""
    assert _window_problems({"amicus_models": _SYNTHETIC}) == []
    short = _SYNTHETIC.model_copy(update={"removal_at_or_after": "0.6.0"})
    assert _window_problems({"amicus_models": short}) != []
    chained = _SYNTHETIC.model_copy(update={"replaced_by": "amicus_models"})
    assert _window_problems({"amicus_models": chained}) != []
    assert _window_problems(_meta.DEPRECATED_TOOLS) == []


def _outlived(table, version):
    """Names whose removal_at_or_after the given version has reached."""
    return [
        name
        for name, deprecation in table.items()
        if _minor(version) >= _minor(deprecation.removal_at_or_after)
    ]


def test_no_deprecated_tool_outlives_its_window():
    """The removal ratchet: once the tree declares a version at or past a tool's
    removal_at_or_after, the tool must already be gone. It first fires on the release PR that
    moves the version, and that release waits for an ordinary removal PR (rule 19 keeps a
    release PR to its version literals); scripts/check_release_state.py holds the same line
    at tag time."""
    assert _outlived(_meta.DEPRECATED_TOOLS, __version__) == [], (
        "remove each tool, its alias registration and its DEPRECATED_TOOLS entry"
    )


def test_the_ratchet_fires_at_the_removal_version_and_not_before():
    """The shipped table is empty since #204, so the ratchet is shown on a synthetic entry:
    quiet inside the window, and firing from the removal version on."""
    table = {"amicus_models": _SYNTHETIC}
    assert _outlived(table, "0.5.0") == []
    assert _outlived(table, "0.6.3") == []
    assert _outlived(table, "0.7.0") == ["amicus_models"]
    assert _outlived(table, "0.8.1") == ["amicus_models"]


def test_effects_for_is_destructive_when_any_enabled_backend_is():
    destructive = config.settings({"AMICUS_BACKENDS": "claude"})
    benign = config.settings({"AMICUS_BACKENDS": "codex,kimi"})
    assert _meta.effects_for(destructive).paid_calls_destructive is True
    assert _meta.effects_for(benign).paid_calls_destructive is False
    assert _meta.effects_for(benign).job_reads_read_only is True


def test_effects_for_treats_an_unknown_backend_as_worst_case():
    settings = config.settings({"AMICUS_BACKENDS": "codex"})
    object.__setattr__(settings, "enabled_backends", ("codex", "third_party"))
    assert _meta.effects_for(settings).paid_calls_destructive is True


def test_annotations_for_each_kind():
    settings = config.settings({"AMICUS_BACKENDS": "codex"})
    active = _meta.annotations_for("active", settings)
    free = _meta.annotations_for("free", settings)
    job_read = _meta.annotations_for("job_read", settings)
    job_consume = _meta.annotations_for("job_consume", settings)
    job_cancel = _meta.annotations_for("job_cancel", settings)
    assert active["destructiveHint"] is False
    assert free["readOnlyHint"] is True
    assert job_read["readOnlyHint"] is True
    assert job_consume["idempotentHint"] is False
    assert job_cancel["idempotentHint"] is True


def test_base_meta_carries_backend_and_timeout():
    settings = config.settings({"AMICUS_TIMEOUT_SECONDS": "42"})
    meta = _meta.base_meta(settings, backend="codex", model="gpt")
    assert meta.backend == "codex"
    assert meta.timeout_seconds == 42
    assert meta.model == "gpt"
