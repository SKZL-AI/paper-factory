"""Reproduction plane: versioned capsule contract (WP4), native local runner
(WP5) and reproduction differential (WP6). PF owns these types; runners
consume a ReproductionCapsule and produce an ExecutionReceipt; the
differential classifies pairs of receipts. The capsule contract follows the
verification plane's conventions (strict Pydantic, schema_version,
fail-visible on unknown versions, control-char rejection in digest-relevant
paths).
"""

from .capsule import (
    SCHEMA_VERSION,
    EnvironmentIdentity,
    ExecutionReceipt,
    FileRef,
    NondeterminismDecl,
    ParameterDecl,
    ReproductionCapsule,
    SemanticRule,
    sha256_file,
    utcnow,
)
from .differential import (
    ReproClassification,
    ReproductionComparison,
    compare_executions,
)
from .runner import (
    CapsuleIntegrityError,
    LocalReproductionRunner,
    UndeclaredOutputError,
)

__all__ = [
    "SCHEMA_VERSION",
    "CapsuleIntegrityError",
    "EnvironmentIdentity",
    "ExecutionReceipt",
    "FileRef",
    "LocalReproductionRunner",
    "NondeterminismDecl",
    "ParameterDecl",
    "ReproClassification",
    "ReproductionCapsule",
    "ReproductionComparison",
    "SemanticRule",
    "UndeclaredOutputError",
    "compare_executions",
    "sha256_file",
    "utcnow",
]
