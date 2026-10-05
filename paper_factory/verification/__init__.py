"""Verification plane: versioned contracts and capability declarations."""

from .capabilities import CapabilityDeclaration, CapabilityStatus, declare
from .contract import (
    SCHEMA_VERSION,
    ArtifactRef,
    BackendIdentity,
    EvidenceRef,
    ExecutionReceipt,
    ReceiptExpectation,
    ReceiptFreshnessError,
    VerificationFinding,
    VerificationResult,
    WorkPackage,
    artifact_binding,
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
    "ReceiptExpectation",
    "ReceiptFreshnessError",
    "VerificationBackend",
    "VerificationFinding",
    "VerificationResult",
    "WorkPackage",
    "artifact_binding",
    "available",
    "compare",
    "declare",
    "get",
    "normalize_statement",
    "register",
    "run_shadow",
    "statement_digest",
]
