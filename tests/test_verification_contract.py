"""Contract tests for the verification plane (plan §4): round-trips, strictness,
schema-version fail-visible, sha256 validation, statement-hash stability."""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from paper_factory.core.results import EvidenceTier, Severity, Verdict
from paper_factory.verification import (
    ArtifactRef,
    BackendIdentity,
    CapabilityDeclaration,
    CapabilityStatus,
    EvidenceRef,
    ExecutionReceipt,
    VerificationFinding,
    VerificationResult,
    WorkPackage,
    declare,
)

SHA = "a" * 64
SHA_B = "b" * 64
NOW = datetime(2026, 10, 4, 12, 0, 0, tzinfo=UTC)
LATER = datetime(2026, 10, 4, 12, 5, 0, tzinfo=UTC)


def artifact() -> ArtifactRef:
    return ArtifactRef(rel_path="results/table1.csv", sha256=SHA, kind="data")


def backend() -> BackendIdentity:
    return BackendIdentity(kind="veriharness", name="hoh", version="0.1.0")


def finding() -> VerificationFinding:
    return VerificationFinding(kind="number_mismatch", severity=Severity.MAJOR,
                               statement="Table 1 reports 42, source reports 43.")


def result() -> VerificationResult:
    return VerificationResult(package_id="wp-p05-1", backend=backend(),
                              verdict=Verdict.PASS, findings=[finding()],
                              artifact_sha256=SHA, started_at=NOW, finished_at=LATER)


def roundtrip(model):
    return type(model).model_validate_json(model.model_dump_json())


# ---------------------------------------------------------------- round-trips


def test_artifact_ref_roundtrip():
    assert roundtrip(artifact()) == artifact()


def test_evidence_ref_roundtrip():
    assert roundtrip(EvidenceRef(evidence_id="E1", tier=EvidenceTier.T0,
                                 artifact=artifact())) == EvidenceRef(
        evidence_id="E1", tier=EvidenceTier.T0, artifact=artifact())


def test_work_package_roundtrip():
    wp = WorkPackage(schema_version=1, package_id="wp-p05-1", node_id="P05",
                     spec_markdown="# Result Integrity\nCheck numbers.",
                     artifacts=[artifact()],
                     acceptance_criteria=["every number traces to source"],
                     provenance={"pilot": "synthetic"})
    assert roundtrip(wp) == wp


def test_backend_identity_roundtrip():
    b = BackendIdentity(kind="external", name="paperqa", version="5.1.0",
                        detail={"env": "local"})
    assert roundtrip(b) == b


def test_verification_finding_roundtrip():
    assert roundtrip(finding()) == finding()


def test_verification_result_roundtrip():
    assert roundtrip(result()) == result()


def test_execution_receipt_roundtrip():
    r = ExecutionReceipt(receipt_id="r-1", backend=backend(),
                         artifact_sha256=SHA, sha256=SHA_B, created_at=NOW)
    assert roundtrip(r) == r


# ---------------------------------------------------------------- strictness


@pytest.mark.parametrize("model", [
    artifact(),
    EvidenceRef(evidence_id="E1", tier=EvidenceTier.T1),
    WorkPackage(schema_version=1, package_id="wp", node_id="P05", spec_markdown="s"),
    backend(),
    finding(),
    result(),
])
def test_extra_fields_forbidden(model):
    payload = model.model_dump(mode="json")
    payload["provider_pane_id"] = "leak"
    with pytest.raises(ValidationError):
        type(model).model_validate(payload)


def test_wrong_schema_version_work_package():
    with pytest.raises(ValidationError):
        WorkPackage(schema_version=2, package_id="wp", node_id="P05", spec_markdown="s")


def test_wrong_schema_version_result():
    payload = result().model_dump(mode="json")
    payload["schema_version"] = 2
    with pytest.raises(ValidationError):
        VerificationResult.model_validate(payload)


def test_invalid_sha256_artifact_ref():
    with pytest.raises(ValidationError):
        ArtifactRef(rel_path="x", sha256="not-hex", kind="data")


def test_invalid_sha256_too_short():
    with pytest.raises(ValidationError):
        ArtifactRef(rel_path="x", sha256="abc123", kind="data")


def test_invalid_sha256_result_binding():
    with pytest.raises(ValidationError):
        VerificationResult(package_id="wp", backend=backend(), verdict=Verdict.PASS,
                           artifact_sha256="ZZ" * 32, started_at=NOW, finished_at=LATER)


def test_invalid_backend_kind():
    with pytest.raises(ValidationError):
        BackendIdentity(kind="herdr", name="x", version="0")


# ---------------------------------------------------------------- statement hash


def test_statement_hash_whitespace_invariant():
    f1 = VerificationFinding(kind="k", severity=Severity.NIT,
                             statement="alpha  beta\ngamma")
    f2 = VerificationFinding(kind="k", severity=Severity.NIT,
                             statement=" alpha beta gamma ")
    assert f1.statement_hash == f2.statement_hash


def test_statement_hash_differs_for_different_statements():
    f1 = VerificationFinding(kind="k", severity=Severity.NIT, statement="alpha")
    f2 = VerificationFinding(kind="k", severity=Severity.NIT, statement="beta")
    assert f1.statement_hash != f2.statement_hash


def test_statement_hash_matches_sha256_of_normalized():
    f = VerificationFinding(kind="k", severity=Severity.NIT, statement="  a  b ")
    expected = hashlib.sha256(b"a b").hexdigest()
    assert f.statement_hash == expected


# ---------------------------------------------------------------- capabilities


def test_capability_status_all_six_serializable():
    expected = {"SUPPORTED", "SUPPORTED_DEGRADED", "UNAVAILABLE", "UNSUPPORTED",
                "REQUIRES_NETWORK", "REQUIRES_HUMAN"}
    assert {s.value for s in CapabilityStatus} == expected
    for status in CapabilityStatus:
        decl = CapabilityDeclaration(backend=backend(), capability="verify",
                                     status=status)
        assert CapabilityDeclaration.model_validate_json(
            decl.model_dump_json()).status is status


def test_declare_helper():
    decl = declare(backend(), "verify", CapabilityStatus.REQUIRES_NETWORK,
                   detail="no OpenAlex reachability")
    assert decl.status is CapabilityStatus.REQUIRES_NETWORK
    assert decl.backend.name == "hoh"
    assert decl.detail == "no OpenAlex reachability"
