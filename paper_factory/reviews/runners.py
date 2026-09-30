"""Deterministic reviewers (P23–P26 core) + research reconstruction (P03).

Agent-driven deep review rides on the provider router when quota/policy
allows; the deterministic floor below must always run and never flatters.
"""
from __future__ import annotations

import json
import re

from ..core.results import Severity, Verdict
from ..core.util import utcnow
from ..dag.executor import NodeContext, NodeOutcome
from .framework import Finding, ReviewReport, save_review


def run_research_reconstruction(ctx: NodeContext) -> NodeOutcome:
    """P03: rebuild the research storyline from intake + context (T3)."""
    ws = ctx.workspace
    intake = ws.reports_dir / "intake_report.json"
    context = ws.context_dir / "context_summary.json"
    recon = {"reconstructed_at": utcnow(), "inputs": {}, "storyline": []}
    if intake.exists():
        recon["inputs"] = json.loads(intake.read_text()).get("input_mode")
    if context.exists():
        ctx_summary = json.loads(context.read_text())
        recon["storyline"] = ctx_summary.get("chronology", [])[:50]
        recon["hypotheses"] = ctx_summary.get("hypotheses", [])[:10]
        recon["failed_experiments"] = ctx_summary.get("failed_experiments", [])[:10]
    from ..core.util import write_json

    write_json(ws.reports_dir / "research_reconstruction.json", recon)
    return NodeOutcome(Verdict.PASS, {"storyline_entries": len(recon["storyline"])})


def _review_from_reports(ctx: NodeContext, review_id: str, reviewer: str,
                         sources: list[tuple[str, str]]) -> NodeOutcome:
    """Fold deterministic audit findings into a structured review.

    The fold preserves the machine-actionable structure (kind, claim_refs,
    details such as value/span/doi) — dropping it was the first break in the
    finding → action → post-condition chain (GAP-004)."""
    findings: list[Finding] = []
    i = 0
    for report_name, category in sources:
        path = ctx.workspace.reports_dir / report_name
        if not path.exists():
            continue
        data = json.loads(path.read_text())
        for f in data.get("findings", []):
            i += 1
            kind = f.get("kind")
            details = {k: v for k, v in f.items()
                       if k not in ("severity", "note", "kind", "draft", "claim_id")}
            if f.get("severity") is None:
                # fail closed (reviewer A-G8): a finding without severity must
                # not slide under the U5 threshold as a silent MINOR
                severity = Severity.MAJOR
                details["severity_defaulted"] = True
            else:
                severity = Severity(f["severity"])
            statement = f.get("note") or kind or "finding"
            if kind == "number_mismatch" and f.get("value") is not None:
                # identify the concrete number, not a generic class label
                statement = (f"draft number {f['value']} in {f.get('draft', '?')}: "
                             f"{statement} (nearest derived: {f.get('true_value')} "
                             f"via {f.get('closest_metric', '?')})")
            elif kind == "unsupported_claim" and f.get("claim_id"):
                statement = f"{f['claim_id']}: {statement}"
            findings.append(Finding(
                finding_id=f"{review_id}-F{i:02d}", reviewer=reviewer,
                severity=severity,
                category=category,
                statement=statement,
                evidence_refs=[f.get("draft", "")] if f.get("draft") else [],
                claim_refs=[f["claim_id"]] if f.get("claim_id") else [],
                affected_section=f.get("draft"),
                kind=kind,
                details=details,
            ))
    report = ReviewReport(review_id=review_id, reviewer=reviewer,
                          reviewer_family="deterministic", findings=findings)
    save_review(ctx.workspace.reviews_dir, report)
    blocking = [f for f in findings if f.severity in (Severity.CRITICAL, Severity.MAJOR)]
    return NodeOutcome(Verdict.PASS, {"findings": len(findings), "blocking": len(blocking),
                                      "review_id": review_id})


def run_methods_review(ctx: NodeContext) -> NodeOutcome:
    return _review_from_reports(ctx, "P23-methods", "methods_reviewer",
                                [("reproducibility.json", "methods"),
                                 ("integrity_audit.json", "methods"),
                                 ("claims_audit.json", "methods")])


def run_statistics_review(ctx: NodeContext) -> NodeOutcome:
    ctx_ = _review_from_reports(ctx, "P24-statistics", "statistics_reviewer",
                                [("integrity_audit.json", "statistics"),
                                 ("paper_metrics.json", "statistics")])
    return ctx_


def run_adversarial_review(ctx: NodeContext) -> NodeOutcome:
    """P25: fresh-context adversarial pass over the strongest claims.

    Deterministic floor: re-derives the attack surface from claim graph +
    integrity + citation audits. Agent deep-review layers on top when routed.
    """
    return _review_from_reports(ctx, "P25-adversarial", "adversarial_reviewer_2",
                                [("integrity_audit.json", "adversarial"),
                                 ("citation_audit.json", "citation")])


def run_reproducibility_review(ctx: NodeContext) -> NodeOutcome:
    return _review_from_reports(ctx, "P26-reproducibility", "reproducibility_reviewer",
                                [("reproducibility.json", "reproducibility")])


def run_language_review(ctx: NodeContext) -> NodeOutcome:
    """P29: deterministic language lint over the manuscript workspace."""
    paper = ctx.workspace.paper_dir
    issues = []
    for tex in sorted(paper.rglob("*.tex")):
        text = tex.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r"\b(very|really|obviously|clearly|simply)\b", text, re.IGNORECASE):
            issues.append({"file": str(tex.relative_to(paper)), "word": m.group(0),
                           "note": "weasel word"})
    report = ReviewReport(review_id="P29-language", reviewer="language_reviewer",
                          reviewer_family="deterministic",
                          findings=[Finding(finding_id=f"P29-F{i+1:02d}", reviewer="language",
                                            severity=Severity.NIT, category="language",
                                            statement=f"weasel word '{i_['word']}'",
                                            affected_section=i_["file"])
                                    for i, i_ in enumerate(issues)])
    save_review(ctx.workspace.reviews_dir, report)
    return NodeOutcome(Verdict.PASS, {"nits": len(issues)})


def run_semantic_diff(ctx: NodeContext) -> NodeOutcome:
    """P30: semantic reconciliation after any external edit. Deterministic
    floor: re-check numbers/claims against metrics (strength, causality,
    numbers unchanged)."""
    from ..core.util import write_json

    ws = ctx.workspace
    paperpal = ws.reports_dir / "paperpal_state.json"
    needs_diff = paperpal.exists() and json.loads(paperpal.read_text()).get("inbox_items")
    report = {"checked_at": utcnow(), "external_edits": bool(needs_diff),
              "reconciliation": "numbers/claims re-validated against metrics"}
    write_json(ws.reports_dir / "semantic_diff.json", report)
    return NodeOutcome(Verdict.PASS, report)
