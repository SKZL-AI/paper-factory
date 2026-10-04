"""Shadow/differential mode tests (plan §3, Phase 5) — all offline/mocked.

No real HoH/herdr/LLM calls: the adapter's verify() is replaced with fixed
results or exceptions. The handlers integration test stubs the base handler
so nothing outside the shadow machinery runs.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from paper_factory.adapters.veriharness.adapter import VeriharnessAdapter
from paper_factory.core.config import (
    MarkingRegistry,
    PaperFactoryConfig,
    ProviderPolicyConfig,
    ProvidersConfig,
)
from paper_factory.core.results import Verdict
from paper_factory.dag import handlers as handlers_mod
from paper_factory.dag.executor import NodeContext, NodeOutcome
from paper_factory.dag.handlers import build_handlers
from paper_factory.dag.nodes import NODES
from paper_factory.state.store import Workspace
from paper_factory.verification.contract import (
    BackendIdentity,
    ExecutionReceipt,
    VerificationResult,
    WorkPackage,
)
from paper_factory.verification.shadow import (
    DifferentialOutcome,
    DifferentialReceipt,
    compare,
    run_shadow,
)

SHA_A = "a" * 64
SHA_B = "b" * 64
NOW = datetime(2026, 10, 4, 12, 0, 0, tzinfo=UTC)
LATER = datetime(2026, 10, 4, 12, 5, 0, tzinfo=UTC)
NODE = next(n for n in NODES if n.id == "P05")


def make_result(
    verdict: Verdict,
    *,
    sha: str | None = None,
    backend: BackendIdentity | None = None,
    failure_reason: str | None = None,
    package_id: str = "wp-p05-1",
) -> VerificationResult:
    return VerificationResult(
        package_id=package_id,
        backend=backend or BackendIdentity(kind="veriharness", name="hoh", version="0.1.0"),
        verdict=verdict,
        artifact_sha256=sha,
        started_at=NOW,
        finished_at=LATER,
        failure_reason=failure_reason,
    )


def native_result(verdict: Verdict, *, sha: str | None = None) -> VerificationResult:
    return make_result(
        verdict,
        sha=sha,
        backend=BackendIdentity(kind="pf_native", name="pf_native:P05", version="1.2.0.dev0"),
    )


# --------------------------------------------------------------------------- #
# compare(): precise outcome boundaries
# --------------------------------------------------------------------------- #


def test_match_same_verdict_same_artifact():
    receipt = compare(
        native_result(Verdict.PASS, sha=SHA_A), make_result(Verdict.PASS, sha=SHA_A), node_id="P05"
    )
    assert receipt.outcome == DifferentialOutcome.MATCH
    assert receipt.node_id == "P05"
    assert receipt.package_id == "wp-p05-1"
    assert receipt.native_backend.kind == "pf_native"
    assert receipt.shadow_backend.kind == "veriharness"


def test_semantic_match_same_verdict_both_artifacts_unbound():
    receipt = compare(native_result(Verdict.PASS), make_result(Verdict.PASS), node_id="P05")
    assert receipt.outcome == DifferentialOutcome.SEMANTIC_MATCH
    assert "not artifact-provable" in receipt.rationale


def test_incomparable_same_verdict_differing_artifacts():
    receipt = compare(
        native_result(Verdict.PASS, sha=SHA_A), make_result(Verdict.PASS, sha=SHA_B), node_id="P05"
    )
    assert receipt.outcome == DifferentialOutcome.INCOMPARABLE
    assert SHA_A in receipt.rationale and SHA_B in receipt.rationale


def test_incomparable_same_verdict_one_side_unbound():
    receipt = compare(
        native_result(Verdict.PASS), make_result(Verdict.PASS, sha=SHA_A), node_id="P05"
    )
    assert receipt.outcome == DifferentialOutcome.INCOMPARABLE


def test_mismatch_differing_verdicts_names_both_sides():
    receipt = compare(native_result(Verdict.PASS), make_result(Verdict.FAIL), node_id="P05")
    assert receipt.outcome == DifferentialOutcome.MISMATCH
    assert "PASS" in receipt.rationale and "FAIL" in receipt.rationale
    assert receipt.shadow_verdict == Verdict.FAIL


def test_provider_unavailable_when_shadow_unavailable():
    receipt = compare(
        native_result(Verdict.PASS),
        make_result(Verdict.UNAVAILABLE, failure_reason="hoh executable not found"),
        node_id="P05",
    )
    assert receipt.outcome == DifferentialOutcome.PROVIDER_UNAVAILABLE
    assert receipt.provider_status == "hoh executable not found"
    assert receipt.native_verdict == Verdict.PASS  # native side untouched


# --------------------------------------------------------------------------- #
# run_shadow(): provider failure containment
# --------------------------------------------------------------------------- #


class _OkBackend:
    def __init__(self, result: VerificationResult):
        self.result = result
        self.packages: list[WorkPackage] = []

    def identity(self):
        return self.result.backend

    def capabilities(self):
        return []

    def verify(self, package: WorkPackage) -> VerificationResult:
        self.packages.append(package)
        return self.result


class _RaisingBackend:
    def identity(self):
        return BackendIdentity(kind="veriharness", name="hoh", version="0.1.0")

    def capabilities(self):
        return []

    def verify(self, package):
        raise RuntimeError("hoh exploded")


def make_package() -> WorkPackage:
    return WorkPackage(package_id="wp-p05-1", node_id="P05", spec_markdown="# spec\nreproduce\n")


def test_run_shadow_returns_native_unchanged_and_compares():
    backend = _OkBackend(make_result(Verdict.PASS, sha=SHA_A))
    native = native_result(Verdict.PASS, sha=SHA_A)
    seen: list[WorkPackage] = []

    def native_fn(package: WorkPackage) -> VerificationResult:
        seen.append(package)
        return native

    returned_native, receipt = run_shadow(native_fn, backend, make_package())
    assert returned_native is native  # exact object, never re-wrapped
    assert seen == backend.packages  # both sides saw the SAME package
    assert receipt.outcome == DifferentialOutcome.MATCH
    assert receipt.node_id == "P05"


def test_run_shadow_backend_exception_is_provider_unavailable():
    native = native_result(Verdict.PASS)
    returned_native, receipt = run_shadow(lambda p: native, _RaisingBackend(), make_package())
    assert returned_native is native  # native result unchanged, not downgraded
    assert receipt.outcome == DifferentialOutcome.PROVIDER_UNAVAILABLE
    assert "hoh exploded" in receipt.provider_status
    assert receipt.shadow_verdict == Verdict.UNAVAILABLE


def test_differential_receipt_roundtrip():
    receipt = compare(
        native_result(Verdict.PASS),
        make_result(Verdict.UNAVAILABLE, failure_reason="offline provider"),
        node_id="P05",
    )
    restored = DifferentialReceipt.model_validate_json(receipt.model_dump_json())
    assert restored == receipt


# --------------------------------------------------------------------------- #
# contract: new optional receipts[] field on VerificationResult
# --------------------------------------------------------------------------- #


def test_verification_result_receipts_default_empty():
    res = make_result(Verdict.PASS)
    assert res.receipts == []


def test_verification_result_receipts_roundtrip():
    res = make_result(Verdict.PASS, sha=SHA_A)
    res.receipts.append(
        ExecutionReceipt(receipt_id="r1", backend=res.backend, artifact_sha256=SHA_A, sha256=SHA_B)
    )
    restored = VerificationResult.model_validate_json(res.model_dump_json())
    assert restored == res
    assert restored.receipts[0].receipt_id == "r1"


# --------------------------------------------------------------------------- #
# handlers integration: shadow via build_handlers (base handler stubbed)
# --------------------------------------------------------------------------- #


def _ctx(ws: Workspace, *, offline: bool = False) -> NodeContext:
    return NodeContext(
        workspace=ws,
        run_id="shadow-test",
        config=PaperFactoryConfig(),
        providers=ProvidersConfig(),
        policy=ProviderPolicyConfig(),
        marking=MarkingRegistry(),
        offline=offline,
        strict=False,
    )


def _build_shadow_handler(monkeypatch, base_verdict=Verdict.PASS):
    def fake_base(ctx: NodeContext, node) -> NodeOutcome:
        return NodeOutcome(base_verdict, {"base": "stub"})

    monkeypatch.setattr(handlers_mod, "_BASE_HANDLERS", {"P05": fake_base})
    return build_handlers([], ["P05"])["P05"]


def test_handlers_shadow_records_receipt_and_never_changes_verdict(tmp_path, monkeypatch):
    handler = _build_shadow_handler(monkeypatch, base_verdict=Verdict.PASS)
    # shadow side disagrees hard — the node verdict must still stay untouched
    monkeypatch.setattr(
        VeriharnessAdapter, "verify", lambda self, package: make_result(Verdict.FAIL)
    )
    ws = Workspace(tmp_path)
    outcome = handler(_ctx(ws), NODE)
    assert outcome.verdict == Verdict.PASS  # MISMATCH is visible, never applied
    assert outcome.detail["shadow_outcome"] == DifferentialOutcome.MISMATCH.value
    receipt_path = Path(outcome.detail["shadow_receipt"])
    assert receipt_path.exists()
    recorded = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert recorded["outcome"] == "MISMATCH"
    assert recorded["native_verdict"] == "PASS" and recorded["shadow_verdict"] == "FAIL"
    rows = ws.receipts_for("shadow-test", "P05")
    assert any(r["kind"] == "shadow" for r in rows)


def test_handlers_shadow_semantic_match_path(tmp_path, monkeypatch):
    handler = _build_shadow_handler(monkeypatch, base_verdict=Verdict.PASS)
    seen_packages: list[WorkPackage] = []

    def fake_verify(self, package: WorkPackage) -> VerificationResult:
        seen_packages.append(package)
        return make_result(Verdict.PASS)  # both sides unbound -> SEMANTIC_MATCH

    monkeypatch.setattr(VeriharnessAdapter, "verify", fake_verify)
    ws = Workspace(tmp_path)
    outcome = handler(_ctx(ws), NODE)
    assert outcome.verdict == Verdict.PASS
    assert outcome.detail["shadow_outcome"] == DifferentialOutcome.SEMANTIC_MATCH.value
    assert len(seen_packages) == 1
    assert seen_packages[0].node_id == "P05"
    assert seen_packages[0].spec_markdown.startswith("# PF verification node P05")


def test_handlers_shadow_offline_runs_nothing(tmp_path, monkeypatch):
    handler = _build_shadow_handler(monkeypatch)
    called = []

    def fake_verify(self, package):
        called.append(package)
        return make_result(Verdict.PASS)

    monkeypatch.setattr(VeriharnessAdapter, "verify", fake_verify)
    ws = Workspace(tmp_path)
    outcome = handler(_ctx(ws, offline=True), NODE)
    assert outcome.verdict == Verdict.PASS
    assert outcome.detail["shadow"] == "NOT_RUN"
    assert outcome.detail["shadow_reason"] == "offline mode"
    assert called == []
    assert not (ws.receipts_dir / "shadow").exists()


def test_handlers_shadow_provider_exception_is_contained(tmp_path, monkeypatch):
    handler = _build_shadow_handler(monkeypatch, base_verdict=Verdict.DEGRADED)
    monkeypatch.setattr(
        VeriharnessAdapter,
        "verify",
        lambda self, package: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    ws = Workspace(tmp_path)
    outcome = handler(_ctx(ws), NODE)  # must not raise
    assert outcome.verdict == Verdict.DEGRADED
    assert outcome.detail["shadow_outcome"] == DifferentialOutcome.PROVIDER_UNAVAILABLE.value
    receipt = json.loads(Path(outcome.detail["shadow_receipt"]).read_text(encoding="utf-8"))
    assert "boom" in receipt["provider_status"]
