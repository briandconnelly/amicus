"""Machine identifiers are rejected, never sanitized; carriers are byte-exact."""

from __future__ import annotations

from amicus.schemas import field_policy as fp
from amicus.schemas import params


def test_pattern_has_one_home():
    assert fp.CONTROL_CHAR_FREE_PATTERN is params.CONTROL_CHAR_FREE_PATTERN


def test_reject_and_preserve_sets_are_disjoint_by_carrier_name():
    assert fp.REJECT_PARAMS == ("job_id", "base", "commit", "model", "task_id")
    leaf = {c.rsplit(".", 1)[-1].rstrip("[]") for c in fp.PRESERVE_CARRIERS}
    # `model`/`base`/`commit` appear on both sides on purpose: rejected as INPUTS,
    # replayed byte-exact as stored CARRIERS. Everything else is one or the other.
    assert leaf & set(fp.REJECT_PARAMS) == {"model", "base", "commit"}
