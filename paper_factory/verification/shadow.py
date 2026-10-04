"""Shadow/differential mode (plan §3, Phase 5).

Runs a verification backend against the same WorkPackage the PF-native path
already processed and compares both results. The native verdict is NEVER
changed by shadow: a MISMATCH is recorded (DifferentialReceipt + JSON in the
receipts tree) and left visible for humans/review, never auto-resolved.

Outcome semantics (precise boundaries):
- PROVIDER_UNAVAILABLE: the shadow side never produced a usable result
  (backend.verify raised, or its verdict is UNAVAILABLE). Native result is
  returned unchanged and is never downgraded because the provider failed.
- MISMATCH: both sides produced a verdict and they differ. Never resolved
  silently; the rationale names both verdicts.
- MATCH: same verdict on both sides AND identical artifact binding
  (artifact_sha256 equal and not None on both sides).
- SEMANTIC_MATCH: same verdict, and the artifact binding is equal in the
  weak sense: both sides bind NO artifact (both None). The verdicts agree,
  but the agreement is not artifact-provable.
- INCOMPARABLE: same verdict, but the artifact bindings conflict — either
  both are set and differ, or exactly one side is bound. Verdict equality
  is therefore not provably equivalent, so neither MATCH nor SEMANTIC_MATCH
  is honest.
"""

from __future__ import annotations

import enum
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal

from pydantic import Field

from ..core.results import Verdict
from .contract import SCHEMA_VERSION, BackendIdentity, Strict, VerificationResult, WorkPackage
from .registry import VerificationBackend


class DifferentialOutcome(str, enum.Enum):
    MATCH = "MATCH"
    SEMANTIC_MATCH = "SEMANTIC_MATCH"
    MISMATCH = "MISMATCH"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    INCOMPARABLE = "INCOMPARABLE"


class DifferentialReceipt(Strict):
    schema_version: Literal[1] = SCHEMA_VERSION
    node_id: str
    package_id: str
    native_verdict: Verdict
    native_artifact_sha256: str | None = None
    native_backend: BackendIdentity
    shadow_verdict: Verdict | None = None
    shadow_artifact_sha256: str | None = None
    shadow_backend: BackendIdentity | None = None
    provider_status: str | None = None  # set only when the shadow side produced no result
    outcome: DifferentialOutcome
    rationale: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def compare(
    native: VerificationResult, shadow: VerificationResult, *, node_id: str = ""
) -> DifferentialReceipt:
    """Compare a native and a shadow VerificationResult for one package.

    Pure: never raises on verdict content, never mutates inputs.
    """
    base = {
        "node_id": node_id,
        "package_id": native.package_id,
        "native_verdict": native.verdict,
        "native_artifact_sha256": native.artifact_sha256,
        "native_backend": native.backend,
    }

    def unavailable(reason: str) -> DifferentialReceipt:
        return DifferentialReceipt(
            outcome=DifferentialOutcome.PROVIDER_UNAVAILABLE,
            rationale=reason,
            provider_status=reason,
            shadow_verdict=shadow.verdict,
            shadow_backend=shadow.backend,
            shadow_artifact_sha256=shadow.artifact_sha256,
            **base,
        )

    if shadow.verdict == Verdict.UNAVAILABLE:
        return unavailable(shadow.failure_reason or "shadow backend reported UNAVAILABLE")

    if native.verdict != shadow.verdict:
        return DifferentialReceipt(
            outcome=DifferentialOutcome.MISMATCH,
            rationale=(
                f"native verdict {native.verdict.value} vs shadow verdict "
                f"{shadow.verdict.value}; not resolved automatically"
            ),
            shadow_verdict=shadow.verdict,
            shadow_backend=shadow.backend,
            shadow_artifact_sha256=shadow.artifact_sha256,
            **base,
        )

    same_artifact = (
        native.artifact_sha256 is not None and native.artifact_sha256 == shadow.artifact_sha256
    )
    if same_artifact:
        return DifferentialReceipt(
            outcome=DifferentialOutcome.MATCH,
            rationale=(
                f"identical verdicts and identical artifact binding ({native.artifact_sha256})"
            ),
            shadow_verdict=shadow.verdict,
            shadow_backend=shadow.backend,
            shadow_artifact_sha256=shadow.artifact_sha256,
            **base,
        )
    if native.artifact_sha256 is None and shadow.artifact_sha256 is None:
        return DifferentialReceipt(
            outcome=DifferentialOutcome.SEMANTIC_MATCH,
            rationale=(
                "identical verdicts; neither side binds an artifact, "
                "so the agreement is not artifact-provable"
            ),
            shadow_verdict=shadow.verdict,
            shadow_backend=shadow.backend,
            **base,
        )
    return DifferentialReceipt(
        outcome=DifferentialOutcome.INCOMPARABLE,
        rationale=(
            f"identical verdicts but conflicting artifact bindings "
            f"(native={native.artifact_sha256}, shadow={shadow.artifact_sha256}); "
            "verdict equality is not provably equivalent"
        ),
        shadow_verdict=shadow.verdict,
        shadow_backend=shadow.backend,
        shadow_artifact_sha256=shadow.artifact_sha256,
        **base,
    )


def run_shadow(
    native_fn: Callable[[WorkPackage], VerificationResult],
    backend: VerificationBackend,
    package: WorkPackage,
) -> tuple[VerificationResult, DifferentialReceipt]:
    """Run the native path, then the backend, and compare.

    Backend exceptions never propagate: they become a PROVIDER_UNAVAILABLE
    receipt. The native result is returned exactly as produced, never
    modified, never downgraded.
    """
    native = native_fn(package)
    try:
        shadow = backend.verify(package)
    except Exception as exc:  # noqa: BLE001 — provider failure must not break the run
        try:
            backend_id = backend.identity()
        except Exception:  # noqa: BLE001
            backend_id = BackendIdentity(kind="external", name="unknown", version="unknown")
        now = datetime.now(UTC)
        shadow = VerificationResult(
            package_id=package.package_id,
            backend=backend_id,
            verdict=Verdict.UNAVAILABLE,
            started_at=now,
            finished_at=now,
            failure_reason=f"shadow backend raised: {exc!r}",
        )
    return native, compare(native, shadow, node_id=package.node_id)
