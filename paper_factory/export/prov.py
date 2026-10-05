"""W3C-PROV export (WP10): ReproductionCapsule + ExecutionReceipts → PROV-JSON
(PROV-DM core, W3C Recommendation 2013-04-30, JSON serialization).

EXPORT ONLY — PF-internal provenance stays canonical/authoritative; this is a
pure projection for interchange (see the package docstring). The mapping does
NOT re-derive anything: it reuses the validated `ExportBundle` from
`_shared.py` (the same mapping engine the RO-Crate exporter builds on).

Mapping (PF → PROV-DM), core relations only, everything evidence-backed:

| PF evidence | PROV |
|---|---|
| capsule (declared computation) | Entity `pf:capsule-<digest>` (content-addressed id) |
| input/config/code file (FileRef) | Entity `pf:file-<sha256>` — content-addressed, so two runs with differing content yield two distinct entities for free |
| execution receipt | Activity `pf:run-<execution_id>` with startTime/endTime |
| backend identity | Agent `pf:tool-<kind>-<name>` (prov:SoftwareAgent) |
| inputs/configs/code consumed by a run | `used` |
| outputs produced by a run | `wasGeneratedBy` |
| outputs vs everything the run used | `wasDerivedFrom` (generatedEntity=output, usedEntity=input/config/code) |
| run ↔ tool | `wasAssociatedWith` (with `prov:plan` = the capsule entity: the run followed this declared computation) |

PF-specific attributes live in the default namespace bound to `pf:` and are
prefixed (`pf:rel_path`, `pf:status`, ...). All attribute values use the
PROV-JSON typed-value form (`{"$": ..., "type": "xsd:..."}`); times are ISO
8601 strings per the PROV-JSON convention.

Conscious simplifications (documented, not hidden):

- The reproduction differential (WP6) is not exported as PROV activity: its
  inputs are receipts (activities), and PROV-DM `used` requires entities.
  The comparison appears in the Workflow Card instead.
- Round-trip is not a goal; exported invariants are tested instead
  (tests/test_export_prov.py).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..reproduction.capsule import ExecutionReceipt, ReproductionCapsule
from ._shared import ExportBundle

PF_PREFIX = "pf"
PF_NAMESPACE = "urn:paper-factory:"
XSD_NAMESPACE = "http://www.w3.org/2001/XMLSchema#"
PROV_FILENAME = "prov.json"


def _str(value: str) -> dict[str, str]:
    return {"$": value, "type": "xsd:string"}


def _int(value: int) -> dict[str, str]:
    return {"$": str(value), "type": "xsd:int"}


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", text).strip("-") or "x"


def _capsule_id(capsule: ReproductionCapsule) -> str:
    return f"{PF_PREFIX}:capsule-{capsule.capsule_digest}"


def _file_id(sha256: str) -> str:
    return f"{PF_PREFIX}:file-{sha256}"


def _agent_id(backend) -> str:
    return f"{PF_PREFIX}:tool-{_slug(backend.kind)}-{_slug(backend.name)}"


def build_prov_document(
    capsule: ReproductionCapsule,
    receipts: list[ExecutionReceipt] | tuple[ExecutionReceipt, ...] = (),
) -> dict[str, Any]:
    """Project a validated bundle into a PROV-JSON document. Raises
    ExportError on missing/mandatory-data violations (see _shared)."""
    bundle = ExportBundle.build(capsule, receipts)

    entity: dict[str, Any] = {
        _capsule_id(capsule): {
            "prov:label": f"reproduction capsule {capsule.capsule_id}",
            "pf:capsule_id": _str(capsule.capsule_id),
            "pf:capsule_digest": _str(capsule.capsule_digest),
            "pf:command": _str(" ".join(capsule.command)),
            "pf:cwd": _str(capsule.cwd),
        }
    }
    for ref in bundle.declared_refs():
        entity[_file_id(ref.sha256)] = {
            "prov:label": ref.rel_path,
            "pf:rel_path": _str(ref.rel_path),
            "pf:sha256": _str(ref.sha256),
        }

    activity: dict[str, Any] = {}
    agent: dict[str, Any] = {}
    used: dict[str, Any] = {}
    was_generated_by: dict[str, Any] = {}
    was_derived_from: dict[str, Any] = {}
    was_associated_with: dict[str, Any] = {}
    n = 0

    consumed_ids = [_file_id(r.sha256) for r in bundle.declared_refs()]

    for receipt in bundle.receipts:
        backend = receipt.backend
        agent[_agent_id(backend)] = {
            "prov:label": f"{backend.kind}/{backend.name}",
            "prov:type": {"$": "prov:SoftwareAgent", "type": "xsd:QName"},
            "pf:backend_version": _str(backend.version),
        }

        run_id = f"{PF_PREFIX}:run-{_slug(receipt.execution_id)}"
        act: dict[str, Any] = {
            "prov:label": f"execution {receipt.execution_id}",
            "prov:startTime": receipt.started_at.isoformat(),
            "prov:endTime": receipt.finished_at.isoformat(),
            "pf:receipt_id": _str(receipt.receipt_id),
            "pf:status": _str(receipt.status),
            "pf:capsule_digest": _str(receipt.capsule_digest),
        }
        if receipt.exit_code is not None:
            act["pf:exit_code"] = _int(receipt.exit_code)
        if receipt.failure_reason:
            act["pf:failure_reason"] = _str(receipt.failure_reason)
        activity[run_id] = act

        for entity_id in consumed_ids:
            n += 1
            used[f"_:u{n}"] = {"prov:activity": run_id,
                               "prov:entity": entity_id}
        for ref in receipt.outputs:
            out_id = _file_id(ref.sha256)
            if out_id not in entity:
                entity[out_id] = {
                    "prov:label": ref.rel_path,
                    "pf:rel_path": _str(ref.rel_path),
                    "pf:sha256": _str(ref.sha256),
                }
            n += 1
            was_generated_by[f"_:g{n}"] = {"prov:entity": out_id,
                                           "prov:activity": run_id}
            for source_id in consumed_ids:
                n += 1
                was_derived_from[f"_:d{n}"] = {
                    "prov:generatedEntity": out_id,
                    "prov:usedEntity": source_id,
                }
        n += 1
        was_associated_with[f"_:w{n}"] = {
            "prov:activity": run_id,
            "prov:agent": _agent_id(backend),
            "prov:plan": _capsule_id(capsule),
        }

    document: dict[str, Any] = {
        "prefix": {PF_PREFIX: PF_NAMESPACE, "xsd": XSD_NAMESPACE},
        "entity": entity,
    }
    if activity:
        document["activity"] = activity
        document["agent"] = agent
        document["used"] = used
        document["wasGeneratedBy"] = was_generated_by
        document["wasDerivedFrom"] = was_derived_from
        document["wasAssociatedWith"] = was_associated_with
    return document


def write_prov_document(
    capsule: ReproductionCapsule,
    receipts: list[ExecutionReceipt] | tuple[ExecutionReceipt, ...],
    target_dir: str | Path,
    filename: str = PROV_FILENAME,
) -> Path:
    """Write the PROV-JSON document into `target_dir` (created if needed)."""
    document = build_prov_document(capsule, receipts)
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)
    path = target / filename
    path.write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    return path
