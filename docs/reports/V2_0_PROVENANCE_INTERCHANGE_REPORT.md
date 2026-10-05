# V2 Provenance Interchange Report

Date: 2026-10-05

PF-internal provenance (receipts, claim–evidence graph, provenance firewall)
is the canonical truth. All standards are **pure exporters**:

| Format | Spec status (verified 2026-10-05) | Module | Tests |
|---|---|---|---|
| RO-Crate 1.3 / Process Run Crate 0.6 | Recommendation / profiles 0.6.0 | `paper_factory/export/rocrate.py` | tests/test_export_rocrate.py (16) |
| W3C PROV-JSON | REC 2013-04-30 (structure per spec; w3.org fetch 403, structure cross-checked against known schema + community sources) | `paper_factory/export/prov.py` | tests/test_export_prov.py (14) |
| CWL v1.2 CommandLineTool | Stable standard | `paper_factory/export/cwl.py` | tests/test_export_cwl.py (16+) |
| Workflow Card | derived summary, never gate input | `paper_factory/export/workflow_card.py` | tests/test_workflow_card.py (12) |

Invariant enforcement: ExportBundle validates evidence once, fail-visible;
completed receipts must cover every declared expected output; receipts bound
to the wrong capsule are rejected. No exported format feeds back into gates.
