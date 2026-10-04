"""Mapping tests for the verification plane (plan §3, Phase 6): external
VerificationFindings become PF-owned review Findings — severity 1:1, external
identity only in details, duplicates fold, conflicts stay visible, round-trip
through save_review/load_reviews stays fail-closed-valid. All offline."""
from __future__ import annotations

import pytest

from paper_factory.core.results import Severity
from paper_factory.reviews.framework import Finding, ReviewReport, load_reviews, save_review
from paper_factory.verification.contract import BackendIdentity, VerificationFinding
from paper_factory.verification.findings_map import map_external_findings

BACKEND = BackendIdentity(kind="veriharness", name="hoh", version="0.1.0")
OTHER_BACKEND = BackendIdentity(kind="external", name="ext-tool", version="2.0")


def vfinding(statement: str = "Table 1 reports 42, source reports 43.",
             severity: Severity = Severity.MAJOR,
             kind: str = "statistics",
             claim_refs: list[str] | None = None,
             evidence_ids: list[str] | None = None) -> VerificationFinding:
    return VerificationFinding(
        kind=kind,
        severity=severity,
        statement=statement,
        claim_refs=claim_refs or [],
        evidence_refs=[
            {"evidence_id": e, "tier": "T1"} for e in (evidence_ids or [])
        ],
    )


def test_required_pf_fields_set():
    out = map_external_findings([vfinding()], BACKEND)
    assert len(out) == 1
    f = out[0]
    assert isinstance(f, Finding)
    assert f.finding_id.startswith("VF-hoh-")
    assert f.reviewer == "verification:hoh"
    assert f.statement == "Table 1 reports 42, source reports 43."
    assert f.kind == "statistics"
    assert f.disposition is None  # honest open state, PF owns closure


def test_severity_preserved_one_to_one():
    for sev in (Severity.CRITICAL, Severity.MAJOR, Severity.MINOR, Severity.NIT):
        out = map_external_findings([vfinding(severity=sev)], BACKEND)
        assert out[0].severity is sev


def test_external_identity_lives_in_details_only():
    out = map_external_findings([vfinding()], BACKEND)
    ext = out[0].details["external"]
    assert ext["backend"] == "hoh"
    assert ext["backend_version"] == "0.1.0"
    assert ext["backend_kind"] == "veriharness"
    assert len(ext["statement_hash"]) == 64
    # PF required fields never carry external identity fields
    assert "statement_hash" not in Finding.model_fields
    for field in ("finding_id", "reviewer", "severity", "category", "statement"):
        assert "statement_hash" not in str(getattr(out[0], field))


def test_claim_refs_use_native_field():
    out = map_external_findings(
        [vfinding(claim_refs=["C-01", "C-02"])], BACKEND)
    assert out[0].claim_refs == ["C-01", "C-02"]


def test_evidence_refs_mapped_to_native_strings():
    out = map_external_findings([vfinding(evidence_ids=["E-1", "E-2"])], BACKEND)
    assert out[0].evidence_refs == ["E-1", "E-2"]


def test_kind_in_allowed_categories_maps_directly():
    for kind in ("methods", "statistics", "novelty", "citation", "reproducibility",
                 "adversarial", "language", "compliance"):
        out = map_external_findings([vfinding(kind=kind)], BACKEND)
        assert out[0].category == kind
        assert "category_fallback" not in out[0].details


def test_unknown_kind_uses_documented_fallback():
    out = map_external_findings([vfinding(kind="weird_backend_flag")], BACKEND)
    f = out[0]
    assert f.category == "compliance"  # documented fallback, not invented
    assert f.kind == "weird_backend_flag"  # raw external kind preserved
    assert f.details["category_fallback"] == "weird_backend_flag"


def test_duplicates_fold_with_count_and_ref_union():
    a = vfinding(claim_refs=["C-01"], evidence_ids=["E-1"])
    b = vfinding(claim_refs=["C-02"], evidence_ids=["E-2"])  # same statement
    out = map_external_findings([a, b], BACKEND)
    assert len(out) == 1
    f = out[0]
    assert f.details["duplicate_count"] == 2
    assert f.claim_refs == ["C-01", "C-02"]
    assert f.evidence_refs == ["E-1", "E-2"]
    assert "conflict" not in f.details


def test_single_finding_has_no_duplicate_count():
    out = map_external_findings([vfinding()], BACKEND)
    assert "duplicate_count" not in out[0].details


def test_distinct_statement_hashes_stay_distinct():
    out = map_external_findings(
        [vfinding("Statement one."), vfinding("Statement two.")], BACKEND)
    assert len(out) == 2
    assert {f.statement for f in out} == {"Statement one.", "Statement two."}


def test_same_hash_other_backend_stays_distinct():
    stmt = "Same statement."
    out = map_external_findings([vfinding(stmt), vfinding(stmt)], OTHER_BACKEND)
    # called per backend in practice; here both map under OTHER_BACKEND only if
    # passed together — same backend + same hash folds, so pass separately:
    out_a = map_external_findings([vfinding(stmt)], BACKEND)
    out_b = map_external_findings([vfinding(stmt)], OTHER_BACKEND)
    assert len(out) == 1  # same backend folds
    assert out_a[0].finding_id != out_b[0].finding_id  # different backends differ
    assert out_a[0].details["external"]["backend"] == "hoh"
    assert out_b[0].details["external"]["backend"] == "ext-tool"


def test_conflict_different_severity_keeps_both_visible():
    a = vfinding(severity=Severity.CRITICAL)
    b = vfinding(severity=Severity.MINOR)  # same statement → same hash
    out = map_external_findings([a, b], BACKEND)
    assert len(out) == 2
    assert {f.severity for f in out} == {Severity.CRITICAL, Severity.MINOR}
    assert all(f.details["conflict"] is True for f in out)
    assert all("duplicate_count" not in f.details for f in out)
    assert len({f.finding_id for f in out}) == 2


def test_conflict_different_kind_keeps_both_visible():
    a = vfinding(kind="statistics")
    b = vfinding(kind="number_mismatch")
    out = map_external_findings([a, b], BACKEND)
    assert len(out) == 2
    assert all(f.details["conflict"] is True for f in out)
    assert {f.kind for f in out} == {"statistics", "number_mismatch"}


def test_roundtrip_save_load_reviews(tmp_path):
    mapped = map_external_findings(
        [vfinding(), vfinding("Second issue.", severity=Severity.CRITICAL,
                              kind="citation")],
        BACKEND,
    )
    report = ReviewReport(review_id="r-verification-1",
                          reviewer="verification:hoh", findings=mapped)
    path = save_review(tmp_path, report)
    assert path.exists()
    reviews, invalid = load_reviews(tmp_path)
    assert invalid == []
    assert len(reviews) == 1
    loaded = reviews[0].findings
    assert [f.finding_id for f in loaded] == [f.finding_id for f in mapped]
    assert loaded[0].details["external"]["statement_hash"] == \
        mapped[0].details["external"]["statement_hash"]
    assert loaded[1].severity is Severity.CRITICAL


def test_load_reviews_stays_fail_closed_with_mapped_findings(tmp_path):
    mapped = map_external_findings([vfinding()], BACKEND)
    save_review(tmp_path, ReviewReport(review_id="r-ok", reviewer="verification:hoh",
                                       findings=mapped))
    (tmp_path / "r-broken.json").write_text('{"review_id": "nope"', encoding="utf-8")
    reviews, invalid = load_reviews(tmp_path)
    assert len(reviews) == 1
    assert len(invalid) == 1
    assert invalid[0]["kind"] == "REVIEW_ARTIFACT_INVALID"


def test_empty_input():
    assert map_external_findings([], BACKEND) == []


@pytest.mark.parametrize("kind", ["methods", "adversarial"])
def test_kind_preserved_regardless_of_category_mapping(kind):
    out = map_external_findings([vfinding(kind=kind)], BACKEND)
    assert out[0].kind == kind
