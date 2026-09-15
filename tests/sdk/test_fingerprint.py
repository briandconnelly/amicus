"""Surface-fingerprint helpers: parsing, digest stability, and the invariant."""

from __future__ import annotations

import pytest

from amicus.sdk.conventions import fingerprint

FP = "some-bridge/0.1/schema-7"
SURFACE = {"tools": ["a", "b"], "codes": ["x"]}


def test_parse_fingerprint():
    assert fingerprint.parse_fingerprint(FP) == ("some-bridge", "0.1", 7)


@pytest.mark.parametrize(
    "bad",
    ["", "schema-7", "Bridge/0.1/schema-7", "b/0.1/schema-", "b/0.1/rev-7", "b/x/schema-7"],
)
def test_parse_rejects_malformed(bad: str):
    with pytest.raises(ValueError, match="must look like"):
        fingerprint.parse_fingerprint(bad)


def test_digest_is_key_order_independent():
    a = fingerprint.canonical_digest({"x": 1, "y": [1, 2]})
    b = fingerprint.canonical_digest({"y": [1, 2], "x": 1})
    assert a == b


def test_digest_changes_with_content():
    assert fingerprint.canonical_digest({"x": 1}) != fingerprint.canonical_digest({"x": 2})


def _digest() -> str:
    return fingerprint.canonical_digest(SURFACE)


def test_ok_when_nothing_changed():
    check = fingerprint.check_surface(
        SURFACE, fingerprint=FP, snapshot_digest=_digest(), snapshot_fingerprint=FP
    )
    assert check.ok
    assert check.reason is None


def test_missing_snapshot_fails_with_instructions():
    check = fingerprint.check_surface(
        SURFACE, fingerprint=FP, snapshot_digest=None, snapshot_fingerprint=None
    )
    assert not check.ok
    assert "no committed snapshot" in check.reason


def test_silent_surface_change_fails():
    check = fingerprint.check_surface(
        {"tools": ["a", "b", "NEW"]},
        fingerprint=FP,
        snapshot_digest=_digest(),
        snapshot_fingerprint=FP,
    )
    assert not check.ok
    assert "fingerprint did not" in check.reason


def test_stale_bump_fails():
    check = fingerprint.check_surface(
        SURFACE,
        fingerprint="some-bridge/0.1/schema-8",
        snapshot_digest=_digest(),
        snapshot_fingerprint=FP,
    )
    assert not check.ok
    assert "digest did not" in check.reason


def test_acknowledged_change_requires_snapshot_regen():
    check = fingerprint.check_surface(
        {"tools": ["a", "b", "NEW"]},
        fingerprint="some-bridge/0.1/schema-8",
        snapshot_digest=_digest(),
        snapshot_fingerprint=FP,
    )
    assert not check.ok
    assert "regenerate" in check.reason


def test_malformed_fingerprint_raises_before_comparison():
    with pytest.raises(ValueError, match="must look like"):
        fingerprint.check_surface(
            SURFACE, fingerprint="bad", snapshot_digest=_digest(), snapshot_fingerprint=FP
        )
