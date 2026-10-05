"""Reproduction plane: versioned capsule contract (WP4), native local runner
(WP5), reproduction differential (WP6), the Snakemake backend adapter
(WP7) and the Nextflow backend adapter (v1.4 WP-B) — thin workflow
consumers of the capsule; the workflow engines map the contract, they
never become PF's orchestrator. PF owns these types; runners consume a
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
from .nextflow_backend import (
    NextflowBackend,
    NextflowUnavailableError,
    nextflow_binary,
    render_nextflow_script,
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
    "NextflowBackend",
    "NextflowUnavailableError",
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
    "nextflow_binary",
    "render_nextflow_script",
    "render_snakefile",
    "sha256_file",
    "snakemake_binary",
    "utcnow",
]
