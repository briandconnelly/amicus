"""schemas.structured: the schema instruction appended to a structured-output prompt."""

from __future__ import annotations

from amicus.schemas.structured import schema_instruction


def test_schema_instruction_names_the_schema():
    text = schema_instruction({"type": "object"})
    assert text.startswith("\n\n# Required output format") and '"type": "object"' in text
