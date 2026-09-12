"""List-time compaction of the published input schemas (issue #41).

Pydantic stamps ``"default": null`` on every optional parameter. Absence from ``required``
already says the parameter may be omitted, so the annotation tells a caller nothing and
cost about 2 KB of every ``tools/list``. It is removed by a FastMCP *transform*, not a
response middleware, for two reasons:

* ``surface.surface_records`` lists with ``run_middleware=False`` so that
  ``surface_digest`` covers the records as the server holds them; a transform runs
  inside that listing, so the digest and the wire agree on the schema.
* A transform's ``list_tools`` returns copies; ``get_tool`` is left alone, so
  ``Tool.parameters`` as FastMCP built it is what ``ValidationEnvelopeMiddleware`` and
  anything else that looks a tool up still sees. Argument validation is unaffected
  either way: FastMCP validates a call from the function signature, not from this dict.

Only a ``default`` whose value is ``null`` is removed. A non-null default (``detail:
"summary"``, ``scope: "working_tree"``) is information and stays. The nullable
``anyOf`` shape is untouched: an explicit null is accepted exactly where it was.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastmcp.server.transforms import Transform

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Sequence

    from fastmcp.tools import Tool


def strip_null_defaults(node: Any) -> Any:
    """A deep copy of ``node`` with every ``"default": null`` entry removed."""
    if isinstance(node, dict):
        return {
            k: strip_null_defaults(v) for k, v in node.items() if not (k == "default" and v is None)
        }
    if isinstance(node, list):
        return [strip_null_defaults(v) for v in node]
    return node


class NullDefaultStrip(Transform):
    """Publish each tool's input schema without ``default: null`` annotations."""

    async def list_tools(self, tools: Sequence[Tool]) -> Sequence[Tool]:
        return [
            tool.model_copy(update={"parameters": strip_null_defaults(tool.parameters)})
            if tool.parameters is not None
            else tool
            for tool in tools
        ]
