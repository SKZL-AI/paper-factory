"""Interchange exporters (ROADMAP v1.3, WP9/WP10/WP11).

EXPORT ONLY: these modules project Paper Factory's canonical machine evidence
(ReproductionCapsule, ExecutionReceipt, ReproductionComparison) into external
interchange formats — RO-Crate 1.3 / Process Run Crate 0.6 (WP9), W3C-PROV
PROV-JSON (WP10) and a derived Workflow Card (WP11). No RO-Crate, PROV or
card semantics ever enter PF's core model; PF-internal provenance
(firewall, origin receipts, receipts in state/store.py) stays authoritative.
The Workflow Card is derived exclusively from canonical evidence and is
never a source of truth or a gate input.

All exporters share one mapping engine (`_shared.ExportBundle`): the PF-side
evidence is validated once, fail-visible, and both format exporters project
the same validated bundle — no duplicated mapping logic.

Round-trip is NOT a goal: exports may lose information by design. Correctness
is pinned by defined exported invariants tested in tests/test_export_*.py
(e.g. every content hash recorded in the capsule/receipts appears in the
export), not by re-importing into PF.
"""

from . import rocrate
from ._shared import ExportBundle, ExportError
from .rocrate import build_rocrate, write_rocrate

__all__ = [
    "ExportBundle",
    "ExportError",
    "build_rocrate",
    "rocrate",
    "write_rocrate",
]
