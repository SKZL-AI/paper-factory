"""Reproduction plane: versioned capsule contract (WP4; runner and
differential land in WP5/WP6). PF owns these types; runners consume a
ReproductionCapsule and produce an ExecutionReceipt. The capsule contract
follows the verification plane's conventions (strict Pydantic,
schema_version, fail-visible on unknown versions, control-char rejection in
digest-relevant paths).
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

__all__ = [
    "SCHEMA_VERSION",
    "EnvironmentIdentity",
    "ExecutionReceipt",
    "FileRef",
    "NondeterminismDecl",
    "ParameterDecl",
    "ReproductionCapsule",
    "SemanticRule",
    "sha256_file",
    "utcnow",
]
