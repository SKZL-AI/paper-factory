"""P08 Claim graph builder (deterministic core): extract candidate empirical
claims from drafts/notes, link to evidence, mark UNSUPPORTED what no artifact
can carry. Drafts are T4 — they propose claims, they never prove them.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from ..core.results import ClaimStatus, Verdict
from ..core.util import utcnow, write_json
from ..dag.executor import NodeContext, NodeOutcome
from .graph import Claim, ClaimGraph, save_claims

CLAIM_CUE = re.compile(
    r"([^.]*\b(?:faster|slower|speedup|latency|throughput|improve[sd]?|outperform|"
    r"reduc(?:es|ed)|significant|achieves?|reaches?|reaching|lower|higher)\b[^.]*\.)",
    re.I)
NUM = re.compile(r"\b\d+(?:\.\d+)?%?\b")

# claim text keyword → required metric field hints. If no metric field matches,
# the claim cannot be supported by the artifacts.
REQUIRED_METRIC_HINTS = {
    "faster": ("time", "latency", "speed", "runtime", "duration"),
    "slower": ("time", "latency", "speed", "runtime", "duration"),
    "speedup": ("time", "latency", "speed", "runtime"),
    "latency": ("latency", "time"),
    "throughput": ("throughput", "ops"),
    "significant": ("test", "pvalue", "ci"),
}


def _extract_candidates(text: str) -> list[str]:
    return [m.group(1).strip() for m in CLAIM_CUE.finditer(text) if NUM.search(m.group(1))]


def run_claim_graph(ctx: NodeContext) -> NodeOutcome:
    root = ctx.workspace.target_root
    graph = ClaimGraph()

    metrics_path = ctx.workspace.reports_dir / "paper_metrics.json"
    metric_fields: set[str] = set()
    if metrics_path.exists():
        metrics = json.loads(metrics_path.read_text(encoding="utf-8")).get("metrics", {})
        metric_fields = {v.get("field", "").lower() for v in metrics.values()}

    n = 0
    unsupported = 0
    audit_findings: list[dict] = []
    for draft in sorted(root.glob("draft/*.md")) + sorted(root.glob("draft/*.tex")):
        text = draft.read_text(encoding="utf-8", errors="replace")
        for cand in _extract_candidates(text):
            n += 1
            cid = f"C{n:03d}"
            status = ClaimStatus.EVIDENCE_FOUND
            note = None
            lower = cand.lower()
            for cue, hints in REQUIRED_METRIC_HINTS.items():
                if cue in lower:
                    if cue == "significant":
                        # significance requires a computed test artifact
                        test_exists = any("test" in f or "pvalue" in f for f in metric_fields)
                        if not test_exists:
                            status = ClaimStatus.UNSUPPORTED
                            note = "significance claimed but no statistical test artifact exists"
                        break
                    if not any(h in f for f in metric_fields for h in hints):
                        status = ClaimStatus.UNSUPPORTED
                        note = f"no metric field matches required hints {hints}"
                    break
            if status == ClaimStatus.UNSUPPORTED:
                unsupported += 1
                # claim-bound finding: remediation may only retire claims it can
                # point to (GAP-004) — the unbound global sweep is gone
                audit_findings.append({
                    "severity": "MAJOR", "kind": "unsupported_claim",
                    "claim_id": cid, "draft": str(draft.relative_to(root)),
                    "excerpt": cand[:160],
                    "note": note or "claim unsupported by artifacts",
                })
            graph.claims.append(Claim(
                claim_id=cid, type="empirical",
                statement=cand[:500], status=status,
                evidence=[] if status == ClaimStatus.UNSUPPORTED else ["evidence_ledger"],
                risk={"overclaim": "high" if status == ClaimStatus.UNSUPPORTED else "low"},
                **({"source_note": note} if False else {}),
            ))
    save_claims(ctx.workspace.claims_dir / "claims.yaml", graph)
    write_json(ctx.workspace.reports_dir / "claims_audit.json",
               {"audited_at": utcnow(), "findings": audit_findings})
    detail = {"claims": len(graph.claims), "unsupported": unsupported}
    if unsupported:
        # honest: claims exist that no artifact carries — pipeline continues,
        # closure (U1) will fail until remediation retires them
        return NodeOutcome(Verdict.DEGRADED, detail)
    return NodeOutcome(Verdict.PASS if n else Verdict.DEGRADED,
                       detail if n else {"reason": "no candidate claims found"})
