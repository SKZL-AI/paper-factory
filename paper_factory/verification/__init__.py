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
from .registry import BACKENDS, VerificationBackend, available, get, register

__all__ = [
    "BACKENDS",
    "SCHEMA_VERSION",
    "ArtifactRef",
    "BackendIdentity",
    "CapabilityDeclaration",
    "CapabilityStatus",
    "EvidenceRef",
    "ExecutionReceipt",
    "VerificationBackend",
    "VerificationFinding",
    "VerificationResult",
    "WorkPackage",
    "available",
    "declare",
    "get",
    "normalize_statement",
    "register",
    "statement_digest",
]
