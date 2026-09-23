"""Claim–evidence graph: claims.yaml + novelty.yaml + limitations.yaml.

Rule (code-enforced): no empirical claim in the final paper without evidence
linkage. Claim states follow the blueprint: PROPOSED, EVIDENCE_FOUND,
VERIFIED, PARTIAL, CONTRADICTED, UNSUPPORTED, RETIRED.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator

from ..core.results import ClaimStatus


class Claim(BaseModel):
    claim_id: str
    type: str = "empirical"  # empirical | methodological | conceptual
    statement: str
    status: ClaimStatus = ClaimStatus.PROPOSED
    evidence: list[str] = Field(default_factory=list)
    external_support: list[dict[str, str]] = Field(default_factory=list)
    contradictions: list[dict[str, str]] = Field(default_factory=list)
    risk: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_linkage(self) -> "Claim":
        if self.status == ClaimStatus.VERIFIED and not self.evidence and self.type == "empirical":
            raise ValueError(f"{self.claim_id}: VERIFIED empirical claim without evidence linkage")
        return self


class ClaimGraph(BaseModel):
    version: int = 1
    claims: list[Claim] = Field(default_factory=list)

    def by_id(self) -> dict[str, Claim]:
        return {c.claim_id: c for c in self.claims}

    def unsupported_final_claims(self) -> list[Claim]:
        bad = (ClaimStatus.PROPOSED, ClaimStatus.UNSUPPORTED, ClaimStatus.CONTRADICTED)
        return [c for c in self.claims if c.type == "empirical" and c.status in bad]


def load_claims(path: Path) -> ClaimGraph:
    if not path.exists():
        return ClaimGraph()
    graph = ClaimGraph(**(yaml.safe_load(path.read_text(encoding="utf-8")) or {}))
    ids = [c.claim_id for c in graph.claims]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        # fail closed (reviewer A-G1): a duplicate id makes by_id() last-wins and
        # can shadow a VERIFIED claim behind an UNSUPPORTED twin
        raise ValueError(f"claims.yaml contains duplicate claim_ids: {dupes}")
    return graph


def save_claims(path: Path, graph: ClaimGraph) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(graph.model_dump(mode="json"), sort_keys=False,
                                   allow_unicode=True), encoding="utf-8")


def upsert_claim(graph: ClaimGraph, claim: Claim) -> ClaimGraph:
    claims = {c.claim_id: c for c in graph.claims}
    claims[claim.claim_id] = claim
    return ClaimGraph(version=graph.version, claims=list(claims.values()))


class LedgerEntry(BaseModel):
    id: str
    text: str
    source: str | None = None
    recorded_at: str | None = None
    related_claims: list[str] = Field(default_factory=list)


class SimpleLedger(BaseModel):
    version: int = 1
    entries: list[LedgerEntry] = Field(default_factory=list)


def load_ledger(path: Path) -> SimpleLedger:
    if not path.exists():
        return SimpleLedger()
    return SimpleLedger(**(yaml.safe_load(path.read_text(encoding="utf-8")) or {}))


def save_ledger(path: Path, ledger: SimpleLedger) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(ledger.model_dump(mode="json"), sort_keys=False,
                                   allow_unicode=True), encoding="utf-8")
