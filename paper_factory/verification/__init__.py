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
from .shadow import DifferentialOutcome, DifferentialReceipt, compare, run_shadow

__all__ = [
    "BACKENDS",
    "SCHEMA_VERSION",
    "ArtifactRef",
    "BackendIdentity",
    "CapabilityDeclaration",
    "CapabilityStatus",
    "DifferentialOutcome",
    "DifferentialReceipt",
    "EvidenceRef",
    "ExecutionReceipt",
    "VerificationBackend",
    "VerificationFinding",
    "VerificationResult",
    "WorkPackage",
    "available",
    "compare",
    "declare",
    "get",
    "normalize_statement",
    "register",
    "run_shadow",
    "statement_digest",
]
