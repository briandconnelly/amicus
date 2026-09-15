"""The backend adapter layer: what a bridge must say and do about its CLI.

**FROZEN** (``CONTRACT_API_VERSION = 1``). The freeze criterion was met and
then exceeded: all three real adapters (Codex, Kimi, Claude) pass conformance
and argv-differential fixtures, AND each bridge's production orchestration now
stages every model-bearing run through its adapter's ``prepare()`` — the
adapters cannot drift from production behavior because they are production
behavior. Under the freeze, required Protocol members and required
BackendContract fields are frozen within a minor line — "additive" changes to
a Protocol or a frozen dataclass are breaking, so new behavior lands as
optional capability protocols or defaulted fields (as
``effort_validation``/``dropped_flags``/``artifact_paths`` already did).
"""

from __future__ import annotations

# 1 = frozen: all three real adapters pass conformance/differential fixtures
# and carry their bridge's production hot path (plan milestone M4 complete).
CONTRACT_API_VERSION = 1
