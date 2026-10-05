"""Reproduction plane: versioned capsule contract (WP4), native local runner
(WP5), reproduction differential (WP6) and the Snakemake backend adapter
(WP7 — first workflow consumer of the capsule; thin mapping only, Snakemake
never becomes PF's orchestrator). PF owns these types; runners consume a
ReproductionCapsule and produce an ExecutionReceipt; the differential
classifies pairs of receipts. The capsule contract follows the verification
plane's conventions (strict Pydantic, schema_version, fail-visible on
unknown versions, control-char rejection in digest-relevant paths).
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
from .snakemake_backend import (
    SnakemakeBackend,
    SnakemakeUnavailableError,
    render_snakefile,
    snakemake_binary,
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
    "SnakemakeBackend",
    "SnakemakeUnavailableError",
    "UndeclaredOutputError",
    "compare_executions",
    "render_snakefile",
    "sha256_file",
    "snakemake_binary",
    "utcnow",
]
