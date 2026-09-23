"""Structured review framework. Findings are JSON, severity-classified, and
CRITICAL/MAJOR findings cannot silently disappear — closure re-reads them.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ..core.results import CLOSED_DISPOSITIONS, Disposition, Severity
from ..core.util import utcnow, write_json


class Finding(BaseModel):
    finding_id: str
    reviewer: str
    severity: Severity
    category: str  # methods | statistics | novelty | citation | reproducibility | adversarial | language | compliance
    statement: str
    evidence_refs: list[str] = Field(default_factory=list)
    claim_refs: list[str] = Field(default_factory=list)
    affected_section: str | None = None
    kind: str | None = None  # machine-actionable finding type (e.g. number_mismatch)
    details: dict[str, Any] = Field(default_factory=dict)  # value/span/doi/… binding data
    disposition: Disposition | None = None
    disposition_reason: str | None = None
    resolved_by: str | None = None


class ReviewReport(BaseModel):
    review_id: str
    reviewer: str
    reviewer_family: str = "unknown"
    created_at: str = Field(default_factory=utcnow)
    independence: str = "independent"  # independent | DEGRADED_INDEPENDENCE
    findings: list[Finding] = Field(default_factory=list)


def save_review(reviews_dir: Path, report: ReviewReport) -> Path:
    path = reviews_dir / f"{report.review_id}.json"
    write_json(path, report.model_dump(mode="json"))
    return path


def load_reviews(reviews_dir: Path) -> tuple[list[ReviewReport], list[dict[str, str]]]:
    """Returns (valid reviews, invalid artifacts). Fails closed: a review file
    that exists but does not parse or violates the schema is reported as a
    REVIEW_ARTIFACT_INVALID entry — never silently skipped, so a corrupt file
    cannot make CRITICAL/MAJOR findings disappear."""
    out: list[ReviewReport] = []
    invalid: list[dict[str, str]] = []
    for f in sorted(reviews_dir.glob("*.json")):
        try:
            out.append(ReviewReport.model_validate_json(f.read_text(encoding="utf-8")))
        except Exception as exc:
            if f.stem == "novelty_attack":
                # P07 writes its (non-review) artifact under this name — skip
                # it only when it provably IS that artifact: the P07 shape
                # present AND no review-ish fields. Shape keys alone are
                # forgeable; a broken review hiding behind them must surface
                # as REVIEW_ARTIFACT_INVALID instead of disappearing.
                try:
                    import json as _json
                    data = _json.loads(f.read_text(encoding="utf-8"))
                except Exception:
                    data = None
                reviewish = {"findings", "review_id", "reviewer", "severity"}
                if (isinstance(data, dict) and {"attacked_at", "claims"} <= set(data)
                        and not (set(data) & reviewish)):
                    continue  # the genuine P07 artifact
            invalid.append({"kind": "REVIEW_ARTIFACT_INVALID", "path": str(f),
                            "error": f"{type(exc).__name__}: {exc}"})
    return out, invalid


def unresolved_blocking(reviews: list[ReviewReport]) -> list[Finding]:
    """CRITICAL/MAJOR findings without a closing disposition block closure.

    Closed-set semantics (GAP-004): only RESOLVED / NOT_APPLICABLE /
    ACCEPTED_LIMITATION / AUTHOR_DECISION close a finding. DEFERRED,
    UNRESOLVED and INVALID_REMEDIATION_ARTIFACT are honest open states and
    keep blocking. A closing disposition ALSO needs provenance (reviewer
    A-G3): without resolved_by + disposition_reason it is an assertion, not
    a closure, and blocks like an undisposed finding.
    """
    out = []
    for r in reviews:
        for f in r.findings:
            if f.severity not in (Severity.CRITICAL, Severity.MAJOR):
                continue
            if f.disposition in CLOSED_DISPOSITIONS:
                if f.resolved_by and f.disposition_reason:
                    continue  # legitimately closed, with provenance
            out.append(f)
    return out
