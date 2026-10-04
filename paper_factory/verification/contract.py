"""Versioned contracts for the verification plane (plan §4, Phase 2).

PF owns these types; backends (pf_native, veriharness, external) consume
WorkPackage and produce VerificationResult. Strict everywhere: unknown
fields are rejected so provider-specific leakage cannot slip in silently.
Provider internals (blocked_kind, Herdr pane IDs, ...) belong in
raw_receipt_refs, never in these models.
"""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..core.results import EvidenceTier, Severity, Verdict

SCHEMA_VERSION = 1

_SHA256_PATTERN = r"[0-9a-f]{64}"


def utcnow() -> datetime:
    return datetime.now(UTC)


def normalize_statement(statement: str) -> str:
    """Whitespace-normalized form: single spaces, no leading/trailing whitespace."""
    return " ".join(statement.split())


def statement_digest(statement: str) -> str:
    return hashlib.sha256(normalize_statement(statement).encode("utf-8")).hexdigest()


class Strict(BaseModel):
    """Base: no unknown fields, no silent type reinterpretations."""

    model_config = ConfigDict(extra="forbid", frozen=False, str_strip_whitespace=True)


# --------------------------------------------------------------------------- #
# References
# --------------------------------------------------------------------------- #


class ArtifactRef(Strict):
    rel_path: str
    sha256: str = Field(pattern=_SHA256_PATTERN)
    kind: str


class EvidenceRef(Strict):
    evidence_id: str
    tier: EvidenceTier
    artifact: ArtifactRef | None = None


class BackendIdentity(Strict):
    kind: Literal["pf_native", "veriharness", "external"]
    name: str
    version: str
    detail: dict = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Work package & findings
# --------------------------------------------------------------------------- #


class WorkPackage(Strict):
    schema_version: Literal[1] = SCHEMA_VERSION
    package_id: str
    node_id: str
    spec_markdown: str
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    provenance: dict = Field(default_factory=dict)


class VerificationFinding(Strict):
    kind: str
    severity: Severity
    statement: str
    claim_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    statement_hash: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="before")
    @classmethod
    def _fill_statement_hash(cls, data: object) -> object:
        if isinstance(data, dict) and isinstance(data.get("statement"), str):
            data["statement_hash"] = statement_digest(data["statement"])
        return data


# --------------------------------------------------------------------------- #
# Results & receipts
# --------------------------------------------------------------------------- #


class VerificationResult(Strict):
    schema_version: Literal[1] = SCHEMA_VERSION
    package_id: str
    backend: BackendIdentity
    verdict: Verdict
    findings: list[VerificationFinding] = Field(default_factory=list)
    receipts: list[ExecutionReceipt] = Field(default_factory=list)
    artifact_sha256: str | None = Field(default=None, pattern=_SHA256_PATTERN)
    started_at: datetime
    finished_at: datetime
    failure_reason: str | None = None
    raw_receipt_refs: list[str] = Field(default_factory=list)


class ExecutionReceipt(Strict):
    receipt_id: str
    backend: BackendIdentity
    artifact_sha256: str = Field(pattern=_SHA256_PATTERN)
    sha256: str = Field(pattern=_SHA256_PATTERN)
    created_at: datetime = Field(default_factory=utcnow)
