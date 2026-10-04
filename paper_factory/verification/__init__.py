"""Verification plane: versioned contracts and capability declarations."""
from .capabilities import CapabilityDeclaration, CapabilityStatus, declare
from .contract import (
    SCHEMA_VERSION,
    ArtifactRef,
    BackendIdentity,
    EvidenceRef,
    ExecutionReceipt,
    VerificationFinding,
    VerificationResult,
    WorkPackage,
    normalize_statement,
    statement_digest,
)

__all__ = [
    "SCHEMA_VERSION",
    "ArtifactRef",
    "BackendIdentity",
    "CapabilityDeclaration",
    "CapabilityStatus",
    "EvidenceRef",
    "ExecutionReceipt",
    "VerificationFinding",
    "VerificationResult",
    "WorkPackage",
    "declare",
    "normalize_statement",
    "statement_digest",
]
