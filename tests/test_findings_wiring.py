"""WP8 (v1.3): findings_map production wiring — adversarial tests.

PF stays finding/closure owner: external VerificationFindings enter the
review plane via reviews.verification_ingest, are identified by the SAME
dedupe_key logic as native findings, block U5 like any CRITICAL/MAJOR
finding, and close only through a PF disposition (durable decision) —
never through the provider.

Adversarial cases covered here:
- duplicate (same backend, same statement) folds with duplicate_count;
- the SAME semantic finding from TWO providers shares one dedupe_key, so
  ONE durable AUTHOR_DECISION binds both;
- conflicting findings (same statement, different severity/kind) stay
  visible, never silently merged;
- identity collision: two DIFFERENT findings on the same claim can never
  false-close each other (the v1.2 weak-identity lesson);
- finding for a claim PF does not know is flagged, never silently dropped;
- stale finding: the verified artifact binding is recorded as provenance,
  not identity — a decided issue stays decided across rebinds, while a
  finding that genuinely changes after an artifact change reopens;
- closed finding reappears after artifact change (both directions);
- end-to-end through U5: provider finding blocks closure, PF decision
  unblocks it, regeneration does not wipe it.

All offline; no HoH runs, no LLM invocations, no network.
"""
from __future__ import annotations

from pathlib import Path

from paper_factory.claims.graph import Claim, ClaimGraph, save_claims
from paper_factory.core.config import (
    MarkingRegistry,
    PaperFactoryConfig,
    ProviderPolicyConfig,
    ProvidersConfig,
)
from paper_factory.core.results import Disposition, Severity
from paper_factory.dag.executor import NodeContext
from paper_factory.release import closure as closure_mod
from paper_factory.reviews.decisions import record_decision
from paper_factory.reviews.framework import (
    dedupe_key,
    load_reviews,
    unresolved_blocking,
)
from paper_factory.reviews.verification_ingest import (
    ingest_verification_findings,
    verification_review_id,
)
from paper_factory.state.store import Workspace
from paper_factory.verification.contract import (
    BackendIdentity,
    VerificationFinding,
)

BACKEND_HOH = BackendIdentity(kind="veriharness", name="hoh", version="0.1.0")
BACKEND_EXT = BackendIdentity(kind="external", name="ext-tool", version="2.0")
SHA_A = "a" * 64
SHA_B = "b" * 64


def vfinding(
    statement: str = "Table 1 reports 42, source reports 43.",
    severity: Severity = Severity.MAJOR,
    kind: str = "statistics",
    claim_refs: list[str] | None = None,
    evidence_ids: list[str] | None = None,
) -> VerificationFinding:
    return VerificationFinding(
        kind=kind,
        severity=severity,
        statement=statement,
        claim_refs=claim_refs or [],
        evidence_refs=[{"evidence_id": e, "tier": "T1"} for e in (evidence_ids or [])],
    )


def _load_vf_findings(reviews_dir: Path, node_id: str = "P05"):
    reviews, invalid = load_reviews(reviews_dir)
    assert invalid == []
    by_id = {r.review_id: r for r in reviews}
    return by_id[verification_review_id(node_id)].findings


# --------------------------------------------------------------------------- #
# ingest: review-plane entry, provenance stamping, empty input
# --------------------------------------------------------------------------- #


def test_ingest_writes_review_report_roundtripping_fail_closed(tmp_path):
    report = ingest_verification_findings(
        tmp_path, "P05", BACKEND_HOH, [vfinding()], run_id="run-1", artifact_sha256=SHA_A
    )
    assert report is not None
    assert report.review_id == verification_review_id("P05")
    assert report.reviewer_family == "verification"
    assert (tmp_path / f"{verification_review_id('P05')}.json").exists()
    (loaded,) = _load_vf_findings(tmp_path)
    assert loaded.finding_id.startswith("VF-hoh-")
    assert loaded.reviewer == "verification:hoh"
    ext = loaded.details["external"]
    assert ext["node_id"] == "P05"
    assert ext["run_id"] == "run-1"
    assert ext["artifact_sha256"] == SHA_A  # stale-binding provenance
    assert loaded.disposition is None  # PF owns closure: honest open state


def test_ingest_empty_input_writes_nothing(tmp_path):
    assert ingest_verification_findings(tmp_path, "P05", BACKEND_HOH, []) is None
    assert list(tmp_path.glob("*.json")) == []


def test_ingest_duplicate_folds_with_count(tmp_path):
    ingest_verification_findings(
        tmp_path, "P05", BACKEND_HOH, [vfinding(), vfinding()], run_id="r"
    )
    (loaded,) = _load_vf_findings(tmp_path)
    assert loaded.details["duplicate_count"] == 2


def test_ingest_conflict_keeps_all_findings_visible(tmp_path):
    report = ingest_verification_findings(
        tmp_path,
        "P05",
        BACKEND_HOH,
        [vfinding(severity=Severity.CRITICAL), vfinding(severity=Severity.MINOR)],
        run_id="r",
    )
    assert len(report.findings) == 2
    assert all(f.details["conflict"] for f in report.findings)
    blocking = unresolved_blocking([report])
    assert len(blocking) == 1 and blocking[0].severity is Severity.CRITICAL


# --------------------------------------------------------------------------- #
# Finding identity: same logic as durable decisions (kind + claim_refs +
# binding + normalized statement hash)
# --------------------------------------------------------------------------- #


def test_same_semantic_finding_two_providers_shares_dedupe_key(tmp_path):
    stmt = "Confidence interval reported without a coverage statement."
    dir_a, dir_b = tmp_path / "a", tmp_path / "b"
    a = ingest_verification_findings(dir_a, "P05", BACKEND_HOH, [vfinding(stmt)], run_id="r")
    b = ingest_verification_findings(dir_b, "P05", BACKEND_EXT, [vfinding(stmt)], run_id="r")
    ka = dedupe_key(a.findings[0])
    kb = dedupe_key(b.findings[0])
    assert ka == kb, "same issue, different provider: ONE underlying identity"
    assert a.findings[0].finding_id != b.findings[0].finding_id


def test_different_findings_same_claim_do_not_collide(tmp_path):
    """Identity collision (v1.2 false-close lesson): two DIFFERENT findings
    about the same claim must have different dedupe_keys, so a durable
    decision for one can never close the other."""
    fa, _ = ingest_verification_findings(
        tmp_path, "P05", BACKEND_HOH,
        [vfinding("Unsupported effect size claimed.", kind="statistics", claim_refs=["C-01"])],
        run_id="r",
    ), None
    fb = ingest_verification_findings(
        tmp_path / "b", "P05", BACKEND_HOH,
        [vfinding("Wrong standard error reported.", kind="statistics", claim_refs=["C-01"])],
        run_id="r",
    )
    assert dedupe_key(fa.findings[0]) != dedupe_key(fb.findings[0])


def test_author_decision_on_one_issue_never_closes_the_other(tmp_path):
    """Full decision flow: decide finding A durably; the regenerated review
    carries A (closed) and B (still blocking)."""
    issue_a = vfinding("Unsupported effect size claimed.", kind="statistics",
                       claim_refs=["C-01"])
    issue_b = vfinding("Wrong standard error reported.", kind="statistics",
                       claim_refs=["C-01"])
    first = ingest_verification_findings(tmp_path, "P05", BACKEND_HOH,
                                         [issue_a, issue_b], run_id="r1")
    fa = next(f for f in first.findings if "effect size" in f.statement)
    record_decision(tmp_path, fa, disposition=Disposition.AUTHOR_DECISION,
                    reason="effect size is contextual, not empirical",
                    decided_by="operator")
    # next run regenerates the review from the provider output; durable
    # decisions are applied at LOAD time (load_reviews), like every review
    second = ingest_verification_findings(tmp_path, "P05", BACKEND_HOH,
                                          [issue_a, issue_b], run_id="r2")
    assert second is not None
    reviews, invalid = load_reviews(tmp_path)
    assert invalid == []
    (vf_report,) = [r for r in reviews
                    if r.review_id == verification_review_id("P05")]
    by_stmt = {f.statement: f for f in vf_report.findings}
    a2 = by_stmt["Unsupported effect size claimed."]
    b2 = by_stmt["Wrong standard error reported."]
    assert a2.disposition == "AUTHOR_DECISION"  # durable decision survived regeneration
    assert a2.resolved_by == "operator"
    assert b2.disposition is None  # never false-closed by A's decision
    blocking = unresolved_blocking(reviews)
    assert [f.statement for f in blocking] == ["Wrong standard error reported."]


# --------------------------------------------------------------------------- #
# Stale finding / artifact rebinds / reappearance after artifact change
# --------------------------------------------------------------------------- #


def test_binding_is_provenance_not_identity(tmp_path):
    """A decided issue stays decided across artifact rebinds: the binding is
    recorded in details (stale-binding provenance) but is NOT part of the
    dedupe identity."""
    stmt = "Derived macro value diverges from the source table."
    f1 = ingest_verification_findings(tmp_path, "P05", BACKEND_HOH,
                                      [vfinding(stmt)], run_id="r1",
                                      artifact_sha256=SHA_A)
    record_decision(tmp_path, f1.findings[0], disposition=Disposition.ACCEPTED_LIMITATION,
                    reason="source table rounding documented", decided_by="operator")
    # artifact changed -> new binding; same finding reported again
    f2 = ingest_verification_findings(tmp_path, "P05", BACKEND_HOH,
                                      [vfinding(stmt)], run_id="r2",
                                      artifact_sha256=SHA_B)
    assert dedupe_key(f1.findings[0]) == dedupe_key(f2.findings[0])
    assert f2.findings[0].details["external"]["artifact_sha256"] == SHA_B
    (loaded,) = _load_vf_findings(tmp_path)
    assert loaded.disposition == "ACCEPTED_LIMITATION"  # still closed, with provenance
    assert loaded.disposition_reason and "durable decision" in loaded.disposition_reason


def test_finding_changed_after_artifact_change_reopens(tmp_path):
    """When the artifact change alters the finding itself (new statement),
    it is a NEW issue: the old decision must NOT close it."""
    old = ingest_verification_findings(tmp_path, "P05", BACKEND_HOH,
                                       [vfinding("Macro m reports 42, source 43.")],
                                       run_id="r1", artifact_sha256=SHA_A)
    record_decision(tmp_path, old.findings[0], disposition=Disposition.RESOLVED,
                    reason="macro regenerated", decided_by="operator")
    ingest_verification_findings(tmp_path, "P05", BACKEND_HOH,
                                 [vfinding("Macro m reports 44, source 43.")],
                                 run_id="r2", artifact_sha256=SHA_B)
    (loaded,) = _load_vf_findings(tmp_path)
    assert loaded.disposition is None  # reopened honestly: different issue
    assert "44" in loaded.statement


def test_closed_finding_reappearing_identically_stays_closed(tmp_path):
    """Provider keeps reporting the same finding after the artifact change:
    the AUTHOR_DECISION binds the issue, not the artifact state."""
    stmt = "Reproduction command for table 2 missing."
    f1 = ingest_verification_findings(tmp_path, "P05", BACKEND_HOH,
                                      [vfinding(stmt, kind="reproducibility")],
                                      run_id="r1", artifact_sha256=SHA_A)
    record_decision(tmp_path, f1.findings[0], disposition=Disposition.AUTHOR_DECISION,
                    reason="table 2 hand-built, documented", decided_by="operator")
    ingest_verification_findings(tmp_path, "P05", BACKEND_HOH,
                                 [vfinding(stmt, kind="reproducibility")],
                                 run_id="r2", artifact_sha256=SHA_B)
    (loaded,) = _load_vf_findings(tmp_path)
    assert loaded.disposition == "AUTHOR_DECISION"


# --------------------------------------------------------------------------- #
# Finding for a claim PF does not know
# --------------------------------------------------------------------------- #


def test_unknown_claim_ref_flagged_not_dropped(tmp_path):
    claims = tmp_path / "claims"
    save_claims(claims / "claims.yaml",
                ClaimGraph(claims=[Claim(claim_id="C-01", statement="s")]))
    report = ingest_verification_findings(
        tmp_path, "P05", BACKEND_HOH,
        [vfinding(claim_refs=["C-01", "C-999"])],
        run_id="r", known_claim_ids={"C-01"},
    )
    ext = report.findings[0].details["external"]
    assert ext["unknown_claim_refs"] == ["C-999"]  # visible mismatch
    assert report.findings[0].claim_refs == ["C-01", "C-999"]  # never dropped


def test_known_claims_not_flagged(tmp_path):
    report = ingest_verification_findings(
        tmp_path, "P05", BACKEND_HOH, [vfinding(claim_refs=["C-01"])],
        run_id="r", known_claim_ids={"C-01"},
    )
    assert "unknown_claim_refs" not in report.findings[0].details["external"]


# --------------------------------------------------------------------------- #
# U5 integration: provider finding blocks closure; PF decision unblocks
# --------------------------------------------------------------------------- #


def _ctx(ws: Workspace) -> NodeContext:
    return NodeContext(workspace=ws, run_id="wp8-test",
                       config=PaperFactoryConfig(), providers=ProvidersConfig(),
                       policy=ProviderPolicyConfig(), marking=MarkingRegistry(),
                       offline=True, strict=False)


def test_provider_major_finding_blocks_u5_until_pf_decides(tmp_path):
    ws = Workspace(tmp_path)
    ctx = _ctx(ws)
    vf = vfinding(severity=Severity.MAJOR, claim_refs=["C-01"])
    report = ingest_verification_findings(ws.reviews_dir, "P05", BACKEND_HOH, [vf],
                                          run_id=ctx.run_id, artifact_sha256=SHA_A)
    # a provider finding NEVER sets a gate verdict — U5 is where it blocks
    state, note = closure_mod._u5(ctx)
    assert state == "FAIL"
    assert "unresolved CRITICAL/MAJOR" in note
    # PF decides — via the durable-decision mechanism, not the provider
    record_decision(ws.reviews_dir, report.findings[0],
                    disposition=Disposition.AUTHOR_DECISION,
                    reason="provider finding reviewed: not applicable",
                    decided_by="operator")
    # regeneration (next run) must not wipe the decision (real-pilot-3)
    ingest_verification_findings(ws.reviews_dir, "P05", BACKEND_HOH, [vf],
                                 run_id=ctx.run_id, artifact_sha256=SHA_A)
    state, note = closure_mod._u5(ctx)
    assert state == "PASS", note
    assert "none blocking" in note


def test_no_decision_written_by_provider(tmp_path):
    """decisions.jsonl is PF-written only: ingest never touches it."""
    ws = Workspace(tmp_path)
    ingest_verification_findings(ws.reviews_dir, "P05", BACKEND_HOH,
                                 [vfinding()], run_id="r")
    assert not (ws.reviews_dir / "decisions.jsonl").exists()
