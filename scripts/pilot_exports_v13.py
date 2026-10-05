"""WP12 pilot exports: RO-Crate / PROV / Workflow Card for the v1.3 pilots.

Reads the Reproduction Capsule and the two P10 ExecutionReceipts that the
Pilot A DAG run persisted (``.paper-factory/reports/reproducibility.json``
in ``pilots/v1-3-repro-synth/project``) and projects them through the v1.3
exporters (``paper_factory/export/`` — EXPORT ONLY, PF provenance stays
authoritative). Output lands in the report directory; a manifest with
SHA-256 hashes is written alongside.

Existing pilot workspaces (Pilot B) declare no reproduction capsule, so the
interchange export applies to Pilot A only — recorded honestly in the
manifest. Real local execution only: no network, no LLM, no HoH.

Usage:
    python -m scripts.pilot_exports_v13 --out-dir docs/reports/v1_3/exports
"""
from __future__ import annotations

import argparse
import json
import platform
import sys
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from paper_factory.export import (
    build_workflow_card,
    write_prov_document,
    write_rocrate,
    write_workflow_card,
)
from paper_factory.reproduction import ExecutionReceipt, ReproductionCapsule

PILOT = REPO / "pilots" / "v1-3-repro-synth" / "project"
REPORT_REL = Path(".paper-factory") / "reports" / "reproducibility.json"


def _utc() -> str:
    return datetime.now(UTC).isoformat()


def _sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out-dir", type=Path,
                        default=REPO / "docs" / "reports" / "v1_3" / "exports")
    args = parser.parse_args()
    out_root = args.out_dir.resolve()

    report_path = PILOT / REPORT_REL
    if not report_path.exists():
        raise SystemExit(
            f"Pilot A reproducibility report not found: {REPORT_REL} — "
            "run the Pilot A DAG first (see docs/reports/V1_3_PILOT_MATRIX.md)")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    capsule = ReproductionCapsule.model_validate_json(
        (PILOT / ".paper-factory" / "reproduction" / "capsule.json")
        .read_text(encoding="utf-8"))
    receipts = [ExecutionReceipt.model_validate(r) for r in report["receipts"]]
    comparison_cls = report["classification"]

    target = out_root / "v1-3-repro-synth"
    written = []
    written.append(write_rocrate(capsule, receipts, target))
    written.append(write_prov_document(capsule, receipts, target))
    json_path, md_path = write_workflow_card(capsule, receipts, target)
    written += [json_path, md_path]

    manifest = {
        "generated_at": _utc(),
        "source": {
            "pilot": "pilots/v1-3-repro-synth/project",
            "report": str(REPORT_REL),
            "capsule_id": capsule.capsule_id,
            "capsule_digest": capsule.capsule_digest,
            "classification": comparison_cls,
            "receipts": [r.execution_id for r in receipts],
        },
        "exporters": {
            "ro_crate": "paper_factory/export/rocrate.py (RO-Crate 1.3 / "
                        "Process Run Crate 0.6 profile)",
            "prov": "paper_factory/export/prov.py (W3C PROV-JSON)",
            "workflow_card": "paper_factory/export/workflow_card.py "
                             "(derived summary, never a gate input)",
        },
        "scope_note": (
            "Interchange export applies to Pilot A only: the existing "
            "Pilot B workspaces (v1.2 pilots) declare no reproduction "
            "capsule, so there is no capsule/receipt bundle to export — "
            "a documented gap, not a PASS."
        ),
        "environment": {
            "python": platform.python_version(),
            "platform": f"{sys.platform}-{platform.machine()}",
        },
        "files": {p.name: _sha256_file(p) for p in sorted(written)},
    }
    manifest_path = target / "export_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    card = build_workflow_card(capsule, receipts)
    print(f"wrote {len(written) + 1} files under {target.relative_to(REPO)}:")
    for p in sorted(written) + [manifest_path]:
        print(f"  {p.relative_to(REPO)}  sha256={_sha256_file(p)[:16]}…")
    print(f"classification: {comparison_cls} | card verdict: "
          f"{card.get('verdict', 'n/a')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
