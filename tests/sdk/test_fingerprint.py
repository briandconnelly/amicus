"""Surface-fingerprint helpers: parsing and digest stability."""

from __future__ import annotations

import pytest

from amicus.schemas import fingerprint

FP = "some-bridge/0.1/schema-7"


def test_parse_fingerprint():
    assert fingerprint.parse_fingerprint(FP) == ("some-bridge", "0.1", 7)


@pytest.mark.parametrize(
    ("good", "parts"),
    [
        ("b/0.0/schema-1", ("b", "0.0", 1)),
        ("b/10.20/schema-100", ("b", "10.20", 100)),
        ("amicus/0.1/schema-52", ("amicus", "0.1", 52)),
    ],
)
def test_parse_accepts_canonical_integers(good: str, parts: tuple[str, str, int]):
    assert fingerprint.parse_fingerprint(good) == parts


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "schema-7",
        "Bridge/0.1/schema-7",
        "b/0.1/schema-",
        "b/0.1/rev-7",
        "b/x/schema-7",
        "b/0.1/schema7",
        "b/0.1/schema-07",
        "b/0.1/schema-0",
        "b/00.1/schema-7",
        "b/0.01/schema-7",
        "b/0.1/schema-7\n",
        " b/0.1/schema-7",
        "b/0.1/schema-7/",
    ],
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
