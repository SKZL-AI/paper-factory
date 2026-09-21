"""P04 Evidence Inventory: hash every input artifact and classify it into the
T0–T4 authority tiers. Writes evidence/evidence_ledger.jsonl (immutable
append-only) and evidence/evidence_index.json.
"""
from __future__ import annotations

import json
from pathlib import Path

from ...core.results import Verdict
from ...core.util import append_jsonl, sha256_file, utcnow, write_json
from ...dag.executor import NodeContext, NodeOutcome

# path-hint → tier. T0 = empirical source, T1 = derived, T2 = external lit,
# T3 = rationale/chat, T4 = draft prose.
TIER_RULES = [
    ("T0", ("results/", "data/", "code/", "experiments/", "benchmarks/", "runs/")),
    ("T1", ("analysis/", "derived/", "metrics/")),
    ("T2", ("literature/", "references")),
    ("T3", ("history/", "chat", "handoff", "notes")),
    ("T4", ("draft/", "drafts/", "preprint")),
]


def _tier_for(rel: str) -> str:
    lower = rel.lower()
    for tier, hints in TIER_RULES:
        if any(h in lower for h in hints):
            return tier
    return "T0"  # unknown artifacts are source-side evidence, still above prose


def run_evidence_inventory(ctx: NodeContext) -> NodeOutcome:
    root = ctx.workspace.target_root
    intake_path = ctx.workspace.reports_dir / "intake_report.json"
    if not intake_path.exists():
        return NodeOutcome(Verdict.FAIL, {"reason": "intake report missing (P01 must run first)"})
    intake = json.loads(intake_path.read_text(encoding="utf-8"))

    ledger = ctx.workspace.evidence_dir / "evidence_ledger.jsonl"
    if ledger.exists():
        ledger.rename(ledger.with_suffix(f".jsonl.v1.{utcnow().replace(':', '')}"))
    count = 0
    for kind, entries in intake.get("inputs", {}).items():
        for e in entries:
            rel = e["path"]
            path = root / rel
            if not path.exists():
                continue
            record = {
                "evidence_id": f"E{count + 1:03d}",
                "recorded_at": utcnow(),
                "tier": _tier_for(rel),
                "kind": kind,
                "path": rel,
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
            append_jsonl(ledger, record)
            count += 1
    index = {"built_at": utcnow(), "count": count,
             "tiers": {t: 0 for t in ("T0", "T1", "T2", "T3", "T4")}}
    for line in ledger.read_text(encoding="utf-8").splitlines():
        if line.strip():
            index["tiers"][json.loads(line)["tier"]] += 1
    write_json(ctx.workspace.evidence_dir / "evidence_index.json", index)
    if count == 0:
        return NodeOutcome(Verdict.FAIL, {"reason": "no evidence artifacts"})
    return NodeOutcome(Verdict.PASS, {"evidence_count": count, "tiers": index["tiers"]})
