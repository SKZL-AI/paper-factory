"""P07 Prior-art / novelty attack (deterministic scaffold).

The purpose is not to maximize novelty claims — it is to narrow each claim
until it survives evidence. Produces reviews/novelty_attack.json.
The deep adversarial analysis is agent work (P25); this node builds the
deterministic attack surface: canonical terms → synonyms → search queries →
discovered prior art hits per claim.
"""
from __future__ import annotations

import json

from ..core.results import Verdict
from ..core.util import utcnow, write_json
from ..dag.executor import NodeContext, NodeOutcome


def run_novelty_attack(ctx: NodeContext) -> NodeOutcome:
    ws = ctx.workspace
    disc_path = ws.reports_dir / "literature_discovery.json"
    discovery = json.loads(disc_path.read_text()) if disc_path.exists() else {"unique_works": {}}

    claims_file = ws.claims_dir / "claims.yaml"
    attack: dict[str, Any] = {"attacked_at": utcnow(), "claims": {}, "prior_art_pool": []}
    if claims_file.exists():
        import yaml

        graph = yaml.safe_load(claims_file.read_text(encoding="utf-8")) or {}
        for c in graph.get("claims", []):
            statement = c.get("statement", "")
            terms = [w.lower() for w in statement.split() if len(w) > 5][:8]
            hits = []
            for key, work in discovery.get("unique_works", {}).items():
                title = (work.get("title") or "").lower()
                overlap = [t for t in terms if t in title]
                if len(overlap) >= 2:
                    hits.append({"work": key, "title": work.get("title"),
                                 "term_overlap": overlap})
            attack["claims"][c.get("claim_id")] = {
                "statement": statement[:200],
                "prior_art_hits": hits,
                "novelty_narrowed": bool(hits),
            }
    attack["prior_art_pool"] = list(discovery.get("unique_works", {}).values())[:50]
    write_json(ws.reviews_dir / "novelty_attack.json", attack)
    if not discovery.get("unique_works"):
        # B-G13: an EMPTY prior-art pool must not PASS the novelty attack —
        # 'attacked against nothing' is degraded, offline or not
        return NodeOutcome(Verdict.DEGRADED,
                           {"reason": "empty prior-art pool — novelty not attacked "
                                      "(offline or no usable query vocabulary)"})
    return NodeOutcome(Verdict.PASS, {"claims_attacked": len(attack["claims"]),
                                      "pool": len(attack["prior_art_pool"])})
