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


# --------------------------------------------------------------------------- #
# CLI wiring: shadow_nodes from the config must reach build_handlers (F2) —
# before the fix both CLI call-sites dropped it, making shadow config a
# silent no-op outside of direct build_handlers() callers.
# --------------------------------------------------------------------------- #


def test_cli_wires_shadow_nodes_config_into_handlers(tmp_path, monkeypatch):
    import argparse

    from paper_factory.cli import main as cli_main

    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    (config_dir / "paper-factory.yaml").write_text(
        'version: 1\nverification:\n  hoh_nodes: []\n  shadow_nodes: ["P05"]\n',
        encoding="utf-8",
    )
    captured: dict[str, list] = {}
    real_build = cli_main.build_handlers

    def spy(hoh_nodes, cfg_shadow_nodes=None):
        captured["hoh"] = list(hoh_nodes or [])
        captured["shadow"] = list(cfg_shadow_nodes or [])
        return real_build(hoh_nodes, cfg_shadow_nodes)

    monkeypatch.setattr(cli_main, "build_handlers", spy)
    args = argparse.Namespace(root=str(tmp_path / "proj"), config_dir=str(config_dir),
                              run_id=None, offline=False, strict=False, target=None)
    assert cli_main.cmd_plan(args) == 0
    assert captured["shadow"] == ["P05"], "CLI dropped verification.shadow_nodes"

    # the handler built through the CLI path must actually record a shadow receipt
    monkeypatch.setattr(
        VeriharnessAdapter, "verify", lambda self, package: make_result(Verdict.PASS)
    )
    ws = Workspace(tmp_path / "proj2")
    outcome = spy(captured["hoh"], captured["shadow"])["P05"](_ctx(ws), NODE)
    assert outcome.detail["shadow_outcome"] == DifferentialOutcome.SEMANTIC_MATCH.value
    assert any(r["kind"] == "shadow" for r in ws.receipts_for("shadow-test", "P05"))


# --------------------------------------------------------------------------- #
# F7: a node listed in BOTH hoh_nodes and shadow_nodes must cost exactly ONE
# adapter.verify() run — the shared result feeds the shadow differential and
# the HoH gate (previously: two independent full HoH runs per node).
# --------------------------------------------------------------------------- #


def _build_dual_handler(monkeypatch, base_verdict=Verdict.PASS):
    def fake_base(ctx: NodeContext, node) -> NodeOutcome:
        return NodeOutcome(base_verdict, {"base": "stub"})

    monkeypatch.setattr(handlers_mod, "_BASE_HANDLERS", {"P05": fake_base})
    return build_handlers(["P05"], ["P05"])["P05"]


def _fake_verify_with_receipt(self: VeriharnessAdapter, package: WorkPackage, verdict=Verdict.PASS):
    run_id = "PF-deadbeef-P05"
    rdir = self.ws.receipts_dir / "hoh" / run_id
    rdir.mkdir(parents=True, exist_ok=True)
    receipt = rdir / "receipt1.json"
    receipt.write_text('{"ok": true}\n', encoding="utf-8")
    result = make_result(verdict)
    return result.model_copy(update={
        "backend": result.backend.model_copy(update={"detail": {"run_id": run_id}}),
        "raw_receipt_refs": [str(receipt)],
    })


def test_dual_node_calls_verify_exactly_once_and_records_both_kinds(tmp_path, monkeypatch):
    calls: list[WorkPackage] = []

    def counting_verify(self, package):
        calls.append(package)
        return _fake_verify_with_receipt(self, package)

    monkeypatch.setattr(VeriharnessAdapter, "verify", counting_verify)
    monkeypatch.setattr(VeriharnessAdapter, "doctor",
                        lambda self: {"present": True, "herdr": True, "bwrap": True})
    handler = _build_dual_handler(monkeypatch, base_verdict=Verdict.PASS)
    ws = Workspace(tmp_path)
    outcome = handler(_ctx(ws), NODE)
    assert len(calls) == 1, f"hoh∩shadow must be ONE verify() run, got {len(calls)}"
    assert outcome.verdict == Verdict.PASS
    # both planes recorded, receipts kind-separated
    assert outcome.detail["shadow_outcome"] == DifferentialOutcome.SEMANTIC_MATCH.value
    assert outcome.detail["hoh_verdict"] == "PASS"
    assert outcome.detail["hoh_receipts"] == 1
    kinds = {r["kind"] for r in ws.receipts_for("shadow-test", "P05")}
    assert kinds == {"shadow", "hoh"}


def test_dual_node_verdict_downgrade_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(VeriharnessAdapter, "verify",
                        lambda self, package: _fake_verify_with_receipt(self, package, Verdict.FAIL))
    monkeypatch.setattr(VeriharnessAdapter, "doctor",
                        lambda self: {"present": True, "herdr": True, "bwrap": True})
    handler = _build_dual_handler(monkeypatch, base_verdict=Verdict.PASS)
    ws = Workspace(tmp_path)
    outcome = handler(_ctx(ws), NODE)
    assert outcome.verdict == Verdict.FAIL  # HoH gate downgrade still applies
    assert outcome.detail["note"] == "HoH verification failed"
    assert outcome.detail["shadow_outcome"] == DifferentialOutcome.MISMATCH.value


def test_hoh_result_from_verify_keeps_top_level_backend_evidence_fields():
    """WP2 (review A MINOR): backend.detail fields that live OUTSIDE
    hoh_detail (evidence_note, herdr=False from the --no-herdr trade-off)
    must survive the verify() -> HohResult mapping — never silently dropped."""
    from paper_factory.dag.handlers import _hoh_result_from_verify

    res = make_result(Verdict.PASS)
    res = res.model_copy(update={
        "backend": res.backend.model_copy(update={"detail": {
            "run_id": "PF-noherdr1-P05",
            "herdr": False,
            "evidence_note": "--no-herdr: keine A01/A02/A12-Akzeptanz-Evidenz",
            "hoh_detail": {"run_rc": 0, "stage": "qa"},
        }})
    })
    mapped = _hoh_result_from_verify("P05", res)
    assert mapped.detail["evidence_note"] == (
        "--no-herdr: keine A01/A02/A12-Akzeptanz-Evidenz"
    )
    assert mapped.detail["herdr"] is False
    # the pre-existing hoh_detail content is untouched by the copy
    assert mapped.detail["run_rc"] == 0 and mapped.detail["stage"] == "qa"


def test_dual_node_no_herdr_evidence_note_reaches_node_detail(tmp_path, monkeypatch):
    """End-to-end through the dual handler: the evidence reservation set by
    verify() at backend.detail top level lands on the node outcome via the
    gate (hoh_evidence_note) — before the WP2 fix it vanished in
    _hoh_result_from_verify."""
    def fake_verify(self, package):
        res = _fake_verify_with_receipt(self, package)
        return res.model_copy(update={
            "backend": res.backend.model_copy(update={"detail": {
                **res.backend.detail,
                "herdr": False,
                "evidence_note": "--no-herdr: keine A01/A02/A12-Akzeptanz-Evidenz",
            }})
        })

    monkeypatch.setattr(VeriharnessAdapter, "verify", fake_verify)
    monkeypatch.setattr(VeriharnessAdapter, "doctor",
                        lambda self: {"present": True, "herdr": True, "bwrap": True})
    handler = _build_dual_handler(monkeypatch, base_verdict=Verdict.PASS)
    ws = Workspace(tmp_path)
    outcome = handler(_ctx(ws), NODE)
    assert outcome.verdict == Verdict.PASS
    assert outcome.detail["hoh_evidence_note"] == (
        "--no-herdr: keine A01/A02/A12-Akzeptanz-Evidenz"
    )


# --------------------------------------------------------------------------- #
# F5/F6: the shadow receipt write is atomic (tmp + os.replace, no .tmp
# leftovers) and the receipt path sanitizes run_id/node_id (a "../evil"
# run_id must stay inside receipts/shadow/).
# --------------------------------------------------------------------------- #


def test_shadow_receipt_write_is_atomic_without_tmp_leftovers(tmp_path, monkeypatch):
    handler = _build_shadow_handler(monkeypatch, base_verdict=Verdict.PASS)
    monkeypatch.setattr(
        VeriharnessAdapter, "verify", lambda self, package: make_result(Verdict.PASS)
    )
    ws = Workspace(tmp_path)
    outcome = handler(_ctx(ws), NODE)
    receipt_path = Path(outcome.detail["shadow_receipt"])
    assert receipt_path.exists()
    json.loads(receipt_path.read_text(encoding="utf-8"))  # complete, parseable JSON
    shadow_dir = ws.receipts_dir / "shadow"
    assert not list(shadow_dir.glob("*.tmp")), "no .tmp residue after the atomic replace"


def test_shadow_receipt_path_sanitizes_run_id_traversal(tmp_path, monkeypatch):
    handler = _build_shadow_handler(monkeypatch, base_verdict=Verdict.PASS)
    monkeypatch.setattr(
        VeriharnessAdapter, "verify", lambda self, package: make_result(Verdict.PASS)
    )
    ws = Workspace(tmp_path)
    ctx = _ctx(ws)
    ctx.run_id = "../evil"  # traversal attempt — must be neutralized
    outcome = handler(ctx, NODE)
    receipt_path = Path(outcome.detail["shadow_receipt"]).resolve()
    shadow_dir = (ws.receipts_dir / "shadow").resolve()
    assert receipt_path.is_relative_to(shadow_dir), f"receipt escaped shadow dir: {receipt_path}"
    assert ".." not in receipt_path.parts  # flat filename, no traversal component
    # the recorded receipt row points at the same sanitized in-tree path
    rows = ws.receipts_for("../evil", "P05", kind="shadow")
    assert len(rows) == 1
    assert Path(rows[0]["path"]).resolve().is_relative_to(shadow_dir)


# --------------------------------------------------------------------------- #
# MATCH im DAG-Pfad: when the node recorded receipts THIS run, the shadow
# package carries them as artifacts and the native side binds them via the
# same artifact_binding rule as the backend — a PASS with the identical
# binding becomes MATCH (before this fix only SEMANTIC_MATCH was reachable).
# --------------------------------------------------------------------------- #


def _build_shadow_handler_with_recording_base(monkeypatch, record: bool):
    def fake_base(ctx: NodeContext, node) -> NodeOutcome:
        if record:
            from paper_factory.core.util import sha256_file

            # a node OUTPUT receipt (kind="report") — the kind of receipt the
            # artifact binding accepts; verification kinds (hoh/shadow) are
            # excluded by _node_artifact_refs (review F-1)
            receipt = ctx.workspace.receipts_dir / "reports" / "P05-report.json"
            receipt.parent.mkdir(parents=True, exist_ok=True)
            receipt.write_text('{"ok": true}\n', encoding="utf-8")
            ctx.workspace.record_receipt(
                receipt.name, ctx.run_id, "P05", "report", receipt, sha256_file(receipt)
            )
        return NodeOutcome(Verdict.PASS, {"base": "stub"})

    monkeypatch.setattr(handlers_mod, "_BASE_HANDLERS", {"P05": fake_base})
    return build_handlers([], ["P05"])["P05"]


def test_shadow_with_node_receipt_reaches_match(tmp_path, monkeypatch):
    from paper_factory.core.util import sha256_file
    from paper_factory.verification.contract import artifact_binding

    seen: dict[str, WorkPackage] = {}

    def fake_verify(self, package: WorkPackage) -> VerificationResult:
        seen["package"] = package
        return make_result(Verdict.PASS, sha=artifact_binding(package.artifacts))

    monkeypatch.setattr(VeriharnessAdapter, "verify", fake_verify)
    handler = _build_shadow_handler_with_recording_base(monkeypatch, record=True)
    ws = Workspace(tmp_path)
    outcome = handler(_ctx(ws), NODE)
    assert outcome.verdict == Verdict.PASS  # shadow never changes the verdict
    # the shadow package carries the node receipt as artifact (ws-root-relative)
    assert len(seen["package"].artifacts) == 1
    art = seen["package"].artifacts[0]
    assert art.rel_path == "receipts/reports/P05-report.json"
    assert art.sha256 == sha256_file(ws.root / art.rel_path)
    # same verdict + same binding on both sides -> MATCH, not just SEMANTIC_MATCH
    assert outcome.detail["shadow_outcome"] == DifferentialOutcome.MATCH.value
    receipt = json.loads(Path(outcome.detail["shadow_receipt"]).read_text(encoding="utf-8"))
    assert receipt["outcome"] == "MATCH"
    assert receipt["native_artifact_sha256"] == receipt["shadow_artifact_sha256"] == art.sha256


def test_shadow_without_node_receipt_stays_semantic_match(tmp_path, monkeypatch):
    def fake_verify(self, package: WorkPackage) -> VerificationResult:
        assert package.artifacts == []
        return make_result(Verdict.PASS)

    monkeypatch.setattr(VeriharnessAdapter, "verify", fake_verify)
    handler = _build_shadow_handler_with_recording_base(monkeypatch, record=False)
    ws = Workspace(tmp_path)
    outcome = handler(_ctx(ws), NODE)
    assert outcome.detail["shadow_outcome"] == DifferentialOutcome.SEMANTIC_MATCH.value


# --------------------------------------------------------------------------- #
# Fixloop aa4de1f (review F-1 MAJOR + F-2/A-8/A-9/F-3):
# F-1: on RESUME (same run_id) attempt-1 verification receipts (kinds hoh/
#      shadow) must never enter attempt-2's artifact binding.
# F-2: receipts_for order is deterministic (created_at, receipt_id) and
#      created_at survives re-records -> the [:20] binding window is stable.
# F-3: rows without sha256 or with paths outside the workspace are skipped.
# --------------------------------------------------------------------------- #


def test_node_artifact_refs_exclude_verification_receipts_across_attempts(tmp_path):
    from paper_factory.core.util import sha256_file
    from paper_factory.dag.handlers import _node_artifact_refs

    ws = Workspace(tmp_path)
    ws.root.mkdir(parents=True, exist_ok=True)
    ctx = _ctx(ws)

    def record(receipt_id: str, kind: str, path: Path, sha: str | None) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")
        ws.record_receipt(receipt_id, ctx.run_id, "P05", kind, path, sha)

    # attempt 1: node output receipt + verification receipts of this run
    record("out.json", "report", ws.root / "reports" / "out.json", None)
    ws.receipts_for(ctx.run_id, "P05")  # touch
    out_path = ws.root / "reports" / "out.json"
    out_path.write_text("attempt-1", encoding="utf-8")
    ws.record_receipt("out.json", ctx.run_id, "P05", "report", out_path, sha256_file(out_path))
    record(
        "shadow.json", "shadow",
        ws.receipts_dir / "shadow" / "P05-attempt1.json", "a" * 64,
    )
    record(
        "hoh.json", "hoh",
        ws.receipts_dir / "hoh" / "PF-x" / "receipt.json", "b" * 64,
    )
    # attempt 2 (resume under the SAME run_id): the output changed and the
    # shadow receipt was os.replace-overwritten on disk (stale sha in DB)
    out_path.write_text("attempt-2-content", encoding="utf-8")
    ws.record_receipt("out.json", ctx.run_id, "P05", "report", out_path, sha256_file(out_path))

    arts = _node_artifact_refs(ctx, "P05")
    assert [a.rel_path for a in arts] == ["reports/out.json"], (
        "binding must contain only node OUTPUT receipts — never hoh/shadow, "
        "not even from the node's own earlier attempt"
    )
    assert arts[0].sha256 == sha256_file(out_path)  # current content, not a stale attempt-1 sha


def test_receipts_for_window_stable_across_re_record(tmp_path):
    from paper_factory.core.util import sha256_file
    from paper_factory.dag.handlers import _node_artifact_refs

    ws = Workspace(tmp_path)
    ws.root.mkdir(parents=True, exist_ok=True)
    ctx = _ctx(ws)
    for i in range(25):
        p = ws.root / f"out{i:02d}.json"
        p.write_text(f"{i}", encoding="utf-8")
        ws.record_receipt(p.name, ctx.run_id, "P05", "report", p, sha256_file(p))
    before_ids = [r["receipt_id"] for r in ws.receipts_for(ctx.run_id, "P05")]
    before_window = [a.rel_path for a in _node_artifact_refs(ctx, "P05")]
    assert len(before_window) == 20  # the cap binds the FIRST 20 deterministically
    # re-record an EARLY receipt (same content): rowid would wander with a
    # plain INSERT OR REPLACE, the deterministic order must not
    early = ws.root / "out00.json"
    ws.record_receipt(early.name, ctx.run_id, "P05", "report", early, sha256_file(early))
    assert [r["receipt_id"] for r in ws.receipts_for(ctx.run_id, "P05")] == before_ids
    assert [a.rel_path for a in _node_artifact_refs(ctx, "P05")] == before_window


def test_node_artifact_refs_skips_rows_without_sha_and_outside_paths(tmp_path):
    from paper_factory.core.util import sha256_file
    from paper_factory.dag.handlers import _node_artifact_refs

    ws = Workspace(tmp_path)
    ws.root.mkdir(parents=True, exist_ok=True)
    ctx = _ctx(ws)
    good = ws.root / "ok.json"
    good.write_text("ok", encoding="utf-8")
    ws.record_receipt("ok.json", ctx.run_id, "P05", "report", good, sha256_file(good))
    # receipt without sha256 -> skipped
    ws.record_receipt("nosha.json", ctx.run_id, "P05", "report", ws.root / "nosha.json", None)
    # receipt path outside the workspace -> skipped (resolve-escape guard)
    outside = tmp_path / "outside.json"
    outside.write_text("x", encoding="utf-8")
    ws.record_receipt("outside.json", ctx.run_id, "P05", "report", outside, sha256_file(outside))
    arts = _node_artifact_refs(ctx, "P05")
    assert [a.rel_path for a in arts] == ["ok.json"]


def test_match_rationale_declares_binding_by_construction():
    """A-8: MATCH must not read as an independent artifact audit — the binding
    is caller-declared and identical by construction."""
    receipt = compare(
        native_result(Verdict.PASS, sha=SHA_A), make_result(Verdict.PASS, sha=SHA_A), node_id="P05"
    )
    assert receipt.outcome == DifferentialOutcome.MATCH
    assert "identical by construction" in receipt.rationale
    assert "did not independently re-hash" in receipt.rationale
