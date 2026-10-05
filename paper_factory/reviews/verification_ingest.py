"""Ingest external verification findings into the PF-owned review plane
(v1.3 WP8 — findings_map production wiring).

Where the shadow/dual verification path receives a ``VerificationResult``
whose backend reported findings, those findings enter the SAME
review/remediation/decision structure as native reviewer findings:

- normalized by ``verification.findings_map`` (severity 1:1, external
  identity only in ``details`` — provider semantics never leak into a PF
  required field);
- identified by the SAME ``dedupe_key`` logic as every other finding
  (kind + claim_refs + value/doi/span binding + normalized statement
  hash): one durable AUTHOR_DECISION binds the underlying issue across
  providers and across runs, and two DIFFERENT findings on the same claim
  can never false-close each other (the v1.2 weak-identity lesson, already
  solved for durable decisions — mapped findings reuse that logic exactly);
- closure stays with PF: mapped findings block U5 exactly like native
  CRITICAL/MAJOR findings and close only through a PF disposition recorded
  via ``reviews.decisions.record_decision``. A provider finding never sets
  a gate verdict directly and never writes or replaces a decision
  (decisions.jsonl stays append-only and PF-written).

One review artifact per node (``VF-<node_id>.json``) is (re)written
whenever the node's verification plane ran — the same regeneration contract
as P23–P26; durable decisions survive regeneration by design (real-pilot-3).

The artifact binding the finding was verified against is recorded in
``details["external"]["artifact_sha256"]``. It is PROVENANCE, never
identity: identity binds the underlying issue (GAP-010), so a legitimately
decided issue stays decided across artifact rebinds, while a finding whose
statement/claims genuinely change after an artifact change is a new issue
with a new identity — and reopens honestly.
"""
from __future__ import annotations

from pathlib import Path

from ..verification.contract import BackendIdentity, VerificationFinding
from ..verification.findings_map import map_external_findings
from .framework import ReviewReport, save_review

REVIEW_ID_PREFIX = "VF-node-"


def verification_review_id(node_id: str) -> str:
    return f"{REVIEW_ID_PREFIX}{node_id}"


def _safe_part(s: str) -> str:
    return "".join(c if (c.isalnum() or c in "._-") else "_" for c in s)


def ingest_verification_findings(
    reviews_dir: Path,
    node_id: str,
    backend: BackendIdentity,
    vfindings: list[VerificationFinding],
    *,
    run_id: str = "",
    artifact_sha256: str | None = None,
    known_claim_ids: set[str] | None = None,
) -> ReviewReport | None:
    """Map external findings and persist them as this node's review report.

    Returns the report, or None when there was nothing to ingest (no review
    artifact is written for an empty finding list — an empty file would
    shadow a previous run's findings without replacing their decisions).

    ``artifact_sha256``: the binding the backend verified against, kept as
    stale-binding provenance in ``details`` (never part of the identity —
    see module docstring).

    ``known_claim_ids``: the current claim graph's ids. A finding whose
    ``claim_refs`` name a claim PF does not know is a provider/PF claim-space
    mismatch: it is flagged ``details["external"]["unknown_claim_refs"]``
    (visible, never silently dropped or removed from ``claim_refs``). None
    disables the check (no graph to check against — not applicable, not
    silently passed).
    """
    if not vfindings:
        return None
    mapped = map_external_findings(vfindings, backend)
    for f in mapped:
        ext = f.details.setdefault("external", {})
        ext["node_id"] = node_id
        if run_id:
            ext["run_id"] = run_id
        if artifact_sha256:
            ext["artifact_sha256"] = artifact_sha256
        if known_claim_ids is not None:
            unknown = sorted(ref for ref in f.claim_refs if ref not in known_claim_ids)
            if unknown:
                ext["unknown_claim_refs"] = unknown
    report = ReviewReport(
        review_id=verification_review_id(node_id),
        reviewer=f"verification:{_safe_part(backend.name)}",
        reviewer_family="verification",
        findings=mapped,
    )
    save_review(reviews_dir, report)
    return report
