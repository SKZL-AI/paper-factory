"""Node handler registry. Each pipeline module registers its handler here;
nodes without a registered handler report NOT_RUN (never silently PASS)."""

from __future__ import annotations

import json
import os
from pathlib import Path

from ..core.results import Verdict
from ..state.inventory import collect_inventory
from .executor import Handler, NodeContext, NodeOutcome
from .nodes import Node


def _safe_receipt_part(s: str) -> str:
    """Allowlist sanitizing for receipt path components (run_id/node_id):
    anything outside [A-Za-z0-9._-] becomes '-', so a hostile run_id can
    never traverse out of receipts/shadow/."""
    return "".join(c if (c.isalnum() or c in "._-") else "-" for c in s)


def _doctor(ctx: NodeContext, node: Node) -> NodeOutcome:
    from ..core.util import write_json

    inv = collect_inventory()
    write_json(ctx.workspace.reports_dir / "doctor_inventory.json", inv)
    missing_core = [
        t for t in ("python3", "git", "pdflatex") if not inv["tools"].get(t, {}).get("present")
    ]
    if missing_core:
        return NodeOutcome(Verdict.FAIL, {"missing_core_tools": missing_core})
    degraded = [
        t
        for t in ("latexmk", "dot", "qpdf", "pdftotext")
        if not inv["tools"].get(t, {}).get("present")
    ]
    detail = {"missing_optional_tools": degraded}
    return NodeOutcome(Verdict.DEGRADED if degraded else Verdict.PASS, detail)


def _lazy(module: str, func: str) -> Handler:
    def run(ctx: NodeContext, node: Node) -> NodeOutcome:
        import importlib

        mod = importlib.import_module(module)
        return getattr(mod, func)(ctx)

    return run


def _compose(ctx: NodeContext, section: str) -> NodeOutcome:
    from ..manuscript.compose import run_section_compose

    return run_section_compose(ctx, section)


def _chain(ctx: NodeContext, handlers: list) -> NodeOutcome:
    """Run handlers in order; worst verdict wins (FAIL > DEGRADED > PASS)."""
    order = {
        Verdict.PASS: 0,
        Verdict.DEGRADED: 1,
        Verdict.FAIL: 2,
        Verdict.HUMAN_REQUIRED: 3,
        Verdict.NOT_RUN: 4,
    }
    worst = NodeOutcome(Verdict.PASS, {})
    details = []
    for h in handlers:
        out = h(ctx, None)
        details.append(out.detail)
        if order.get(out.verdict, 5) > order.get(worst.verdict, 0):
            worst = out
    worst.detail = {"chain": details}
    return worst


_BASE_HANDLERS: dict[str, Handler] = {
    "P00": _doctor,
    "P01": _lazy("paper_factory.context.intake", "run_intake"),
    "P02": _lazy("paper_factory.context.mining", "run_context_mining"),
    "P03": _lazy("paper_factory.reviews.runners", "run_research_reconstruction"),
    "P04": _lazy("paper_factory.evidence.inventory", "run_evidence_inventory"),
    "P05": _lazy("paper_factory.statistics.metrics", "run_integrity_audit"),
    "P06": _lazy("paper_factory.literature.discovery", "run_literature_discovery"),
    "P07": _lazy("paper_factory.literature.novelty", "run_novelty_attack"),
    "P08": _lazy("paper_factory.claims.builder", "run_claim_graph"),
    "P09": _lazy("paper_factory.statistics.metrics", "run_statistics"),
    "P10": _lazy("paper_factory.statistics.reproducibility", "run_reproducibility"),
    "P11": _lazy("paper_factory.figures.build", "run_figure_plan"),
    "P12": _lazy("paper_factory.tables.build", "run_table_plan"),
    "P13": _lazy("paper_factory.figures.build", "run_figure_generation"),
    "P14": _lazy("paper_factory.tables.build", "run_table_generation"),
    "P15": lambda ctx, node: _chain(
        ctx,
        [
            _lazy("paper_factory.manuscript.scaffold", "run_manuscript_architecture"),
        ],
    ),
    "P16": lambda ctx, node: _compose(ctx, "methods"),
    "P17": lambda ctx, node: _compose(ctx, "results"),
    "P18": lambda ctx, node: _compose(ctx, "introduction"),
    "P19": lambda ctx, node: _compose(ctx, "discussion"),
    "P20": lambda ctx, node: _chain(
        ctx,
        [
            lambda c, n: _compose(c, "abstract"),
            _lazy("paper_factory.manuscript.compose", "run_finalize_main"),
            _lazy("paper_factory.manuscript.scaffold", "run_manuscript_structure_check"),
        ],
    ),
    # audit BEFORE build (release audit 2026-10-02): the verified registry
    # metadata (authors/year) must land in the same run's references.bib —
    # building in P15 read the PREVIOUS run's audit (upgraded: 0)
    "P21": lambda ctx, node: _chain(
        ctx,
        [
            _lazy("paper_factory.literature.verify", "run_citation_audit"),
            _lazy("paper_factory.literature.verify", "build_references"),
        ],
    ),
    "P22": _lazy("paper_factory.statistics.numbers_audit", "run_numbers_units_audit"),
    "P23": _lazy("paper_factory.reviews.runners", "run_methods_review"),
    "P24": _lazy("paper_factory.reviews.runners", "run_statistics_review"),
    "P25": _lazy("paper_factory.reviews.runners", "run_adversarial_review"),
    "P26": _lazy("paper_factory.reviews.runners", "run_reproducibility_review"),
    "P27": _lazy("paper_factory.reviews.remediation", "run_remediation"),
    "P28": _lazy("paper_factory.reviews.remediation", "run_scientific_freeze"),
    "P29": _lazy("paper_factory.reviews.runners", "run_language_review"),
    "P30": _lazy("paper_factory.reviews.runners", "run_semantic_diff"),
    "P31": _lazy("paper_factory.paperpal.bridge", "run_paperpal"),
    "P32": _lazy("paper_factory.venue.compliance", "run_venue_compliance"),
    "P33": _lazy("paper_factory.release.export", "run_clean_export"),
    "P34": _lazy("paper_factory.release.export", "run_clean_rebuild"),
    "P35": _lazy("paper_factory.release.closure", "run_global_closure"),
    "P36": _lazy("paper_factory.release.signoff", "run_human_signoff"),
    "P37": lambda ctx, node: NodeOutcome(
        Verdict.NOT_RUN, {"reason": "no external submission is ever automatic"}
    ),
}

# verification-grade nodes that route through the HoH adapter when the config
# enables them (quota-aware subset; default P05 only — see VerificationCfg.hoh_nodes)
VERIHARNESS_CAPABLE = {"P04", "P05", "P07", "P09", "P10", "P16", "P17", "P18", "P20"}


def _pf_version() -> str:
    try:
        from importlib.metadata import version

        return version("paper-factory")
    except Exception:  # noqa: BLE001 — version is nice-to-have, never blocking
        return "unknown"


def _write_node_spec(workspace, node_id: str, node: Node | None) -> Path:
    name = node.name if node is not None else node_id
    spec = workspace.sub("hoh-specs") / f"{node_id}.md"
    spec.write_text(
        f"# PF verification node {node_id}: {name}\n\n"
        f"Work package: add a `VERIFICATION.md` to this repository that\n"
        f"documents exactly how the experiment results are reproduced\n"
        f"(commands, expected artifacts). Keep it factual and short.\n\n"
        f"## Acceptance criteria\n"
        f"- K1: `python3 code/analyze.py` exits 0 (analysis reproduces)\n"
        f"- K2: `test -s results/summary.json` (result artifact exists)\n"
        f"- K3: `test -s VERIFICATION.md` (documentation written)\n"
        f"- K4: `grep -q analyze VERIFICATION.md` (docs name the analysis)\n",
        encoding="utf-8",
    )
    return spec


def _run_shadow_differential(
    ctx: NodeContext,
    node: Node | None,
    node_id: str,
    adapter,
    outcome: NodeOutcome,
    shadow_result=None,
) -> None:
    """Shadow mode (plan §3 Phase 5): compare the PF-native result with the
    HoH backend's verdict for the same package and record the difference.

    The node verdict is NEVER changed by shadow — MISMATCH is only visible
    via outcome.detail and the DifferentialReceipt on disk.

    ``shadow_result``: a precomputed VerificationResult from ONE shared
    adapter.verify() call (node listed in hoh_nodes AND shadow_nodes — a
    single verify feeds both planes, never two full HoH runs). When None,
    run_shadow invokes the backend itself (shadow-only nodes, unchanged).
    """
    from datetime import UTC, datetime

    from ..core.util import sha256_file, write_json
    from ..verification.contract import BackendIdentity, VerificationResult, WorkPackage
    from ..verification.shadow import compare, run_shadow

    if ctx.offline:
        outcome.detail["shadow"] = "NOT_RUN"
        outcome.detail["shadow_reason"] = "offline mode"
        return
    spec = _write_node_spec(ctx.workspace, node_id, node)
    package = WorkPackage(
        package_id=f"shadow-{node_id}-{ctx.run_id}",
        node_id=node_id,
        spec_markdown=spec.read_text(encoding="utf-8"),
    )
    started_at = datetime.now(UTC)

    def native_fn(package: WorkPackage) -> VerificationResult:
        # The native side is whatever the deterministic/agent handler already
        # produced; PF-native results carry no artifact binding here (honest
        # None, not a fabricated hash).
        return VerificationResult(
            package_id=package.package_id,
            backend=BackendIdentity(
                kind="pf_native", name=f"pf_native:{node_id}", version=_pf_version()
            ),
            verdict=outcome.verdict,
            artifact_sha256=None,
            started_at=started_at,
            finished_at=datetime.now(UTC),
        )

    if shadow_result is None:
        _, receipt = run_shadow(native_fn, adapter, package)
    else:
        receipt = compare(native_fn(package), shadow_result, node_id=node_id)
    # Sanitized path components (F6) + atomic write via tmp + os.replace (F5):
    # a crash mid-write must never leave a truncated receipt behind, and a
    # hostile run_id must never escape receipts/shadow/.
    safe_name = f"{_safe_receipt_part(node_id)}-{_safe_receipt_part(ctx.run_id)}.json"
    receipt_path = ctx.workspace.receipts_dir / "shadow" / safe_name
    tmp_path = receipt_path.with_name(receipt_path.name + ".tmp")
    write_json(tmp_path, json.loads(receipt.model_dump_json()))
    os.replace(tmp_path, receipt_path)
    ctx.workspace.record_receipt(
        receipt_path.name, ctx.run_id, node_id, "shadow", receipt_path, sha256_file(receipt_path)
    )
    outcome.detail["shadow_outcome"] = receipt.outcome.value
    outcome.detail["shadow_receipt"] = str(receipt_path)


def _hoh_result_from_verify(node_id: str, res):
    """Map a generic verify() VerificationResult onto the legacy HohResult
    shape (same field derivation as VeriharnessAdapter.verify_work_package),
    so the HoH gate can consume a SHARED verify() result."""
    from ..adapters.veriharness.adapter import HohResult
    from ..core.util import sha256_file

    hoh_detail = dict(res.backend.detail.get("hoh_detail") or {})
    executed = "run_rc" in hoh_detail
    receipts = [
        {"receipt_file": Path(p).name, "copied_to": p, "sha256": sha256_file(Path(p))}
        for p in res.raw_receipt_refs
    ]
    return HohResult(
        run_id=res.backend.detail.get("run_id", ""),
        verdict=res.verdict,
        accepted=True if res.verdict == Verdict.PASS else (False if executed else None),
        blocked_kind=res.backend.detail.get("blocked_kind"),
        stage=hoh_detail.get("stage"),
        receipts=receipts,
        detail=hoh_detail,
    )


def _apply_hoh_gate(ctx: NodeContext, node_id: str, result, outcome: NodeOutcome) -> None:
    """Record the HoH side (detail fields + kind="hoh" receipts) and apply the
    verification-grade verdict semantics: a node whose config demands HoH
    verification does not keep a bare PASS without it."""
    outcome.detail["hoh_run_id"] = result.run_id
    outcome.detail["hoh_verdict"] = result.verdict.value
    outcome.detail["hoh_receipts"] = len(result.receipts)
    outcome.detail["hoh_blocked_kind"] = result.blocked_kind
    for r in result.receipts:
        ctx.workspace.record_receipt(
            r["receipt_file"],
            ctx.run_id,
            node_id,
            "hoh",
            ctx.workspace.receipts_dir / "hoh" / result.run_id / r["receipt_file"],
            r["sha256"],
        )
    if outcome.verdict == Verdict.PASS:
        if result.verdict == Verdict.FAIL:
            outcome.verdict = Verdict.FAIL
            outcome.detail["note"] = "HoH verification failed"
        elif result.verdict != Verdict.PASS:
            outcome.verdict = Verdict.DEGRADED
            outcome.detail["note"] = (
                "deterministic work passed; HoH verification "
                "incomplete/degraded — recorded honestly"
            )


def _unavailable_verify_result(adapter, package, exc):
    """VerificationResult standing in for a backend that raised (same shape
    run_shadow builds for its provider-exception containment)."""
    from datetime import UTC, datetime

    from ..verification.contract import BackendIdentity, VerificationResult

    try:
        backend_id = adapter.identity()
    except Exception:  # noqa: BLE001
        backend_id = BackendIdentity(kind="external", name="unknown", version="unknown")
    now = datetime.now(UTC)
    return VerificationResult(
        package_id=package.package_id,
        backend=backend_id,
        verdict=Verdict.UNAVAILABLE,
        started_at=now,
        finished_at=now,
        failure_reason=f"shadow backend raised: {exc!r}",
    )


def build_handlers(
    cfg_hoh_nodes: list[str] | None = None, cfg_shadow_nodes: list[str] | None = None
) -> dict[str, Handler]:
    enabled = set(cfg_hoh_nodes if cfg_hoh_nodes is not None else ["P05"]) & VERIHARNESS_CAPABLE
    shadow_enabled = set(cfg_shadow_nodes or []) & VERIHARNESS_CAPABLE
    wrapped_nodes = enabled | shadow_enabled
    handlers: dict[str, Handler] = dict(_BASE_HANDLERS)
    for nid in wrapped_nodes:
        base = handlers.get(nid)
        if base is None:
            continue

        def make_wrapped(
            node_id: str, base_handler: Handler, *, hoh: bool, shadow: bool
        ) -> Handler:
            def wrapped(ctx: NodeContext, node: Node) -> NodeOutcome:
                from ..adapters.veriharness.adapter import VeriharnessAdapter

                outcome = base_handler(ctx, node)
                adapter = VeriharnessAdapter(ctx.workspace)
                if hoh and shadow:
                    from ..verification.contract import WorkPackage
                    # Review fix F7: a node in BOTH lists gets exactly ONE
                    # adapter.verify() call; the result feeds the shadow
                    # differential AND the HoH gate. Receipts stay recorded
                    # per kind ("shadow" + "hoh"); the verdict downgrade
                    # semantics are unchanged.
                    if ctx.offline:
                        outcome.detail["shadow"] = "NOT_RUN"
                        outcome.detail["shadow_reason"] = "offline mode"
                        outcome.detail["hoh"] = "NOT_RUN"
                        outcome.detail["hoh_reason"] = "offline mode"
                        return outcome
                    diag = adapter.doctor()
                    if not (diag.get("present") and diag.get("herdr")):
                        reason = "DEGRADED_RUNTIME" if diag.get("present") else "hoh missing"
                        outcome.detail["shadow"] = "NOT_RUN"
                        outcome.detail["shadow_reason"] = reason
                        outcome.detail["hoh"] = "NOT_RUN"
                        outcome.detail["hoh_reason"] = reason
                        return outcome
                    spec = _write_node_spec(ctx.workspace, node_id, node)
                    package = WorkPackage(
                        package_id=f"shadow-{node_id}-{ctx.run_id}",
                        node_id=node_id,
                        spec_markdown=spec.read_text(encoding="utf-8"),
                    )
                    try:
                        shared = adapter.verify(package)
                    except Exception as exc:
                        # shadow side stays contained (PROVIDER_UNAVAILABLE
                        # receipt, like run_shadow); the HoH side stays
                        # fail-visible — nothing is swallowed.
                        _run_shadow_differential(
                            ctx, node, node_id, adapter, outcome,
                            shadow_result=_unavailable_verify_result(adapter, package, exc),
                        )
                        raise
                    _run_shadow_differential(ctx, node, node_id, adapter, outcome,
                                             shadow_result=shared)
                    _apply_hoh_gate(ctx, node_id, _hoh_result_from_verify(node_id, shared),
                                    outcome)
                    return outcome
                if shadow:
                    _run_shadow_differential(ctx, node, node_id, adapter, outcome)
                if not hoh:
                    return outcome
                diag = adapter.doctor()
                if ctx.offline:
                    outcome.detail["hoh"] = "NOT_RUN"
                    outcome.detail["hoh_reason"] = "offline mode"
                    return outcome
                if not (diag.get("present") and diag.get("herdr")):
                    outcome.detail["hoh"] = "NOT_RUN"
                    outcome.detail["hoh_reason"] = (
                        "DEGRADED_RUNTIME" if diag.get("present") else "hoh missing"
                    )
                    return outcome
                spec = _write_node_spec(ctx.workspace, node_id, node)
                result = adapter.verify_work_package(node_id, spec)
                _apply_hoh_gate(ctx, node_id, result, outcome)
                return outcome

            return wrapped

        handlers[nid] = make_wrapped(nid, base, hoh=nid in enabled, shadow=nid in shadow_enabled)
    return handlers


HANDLERS: dict[str, Handler] = build_handlers()
