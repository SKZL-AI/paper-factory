"""Node handler registry. Each pipeline module registers its handler here;
nodes without a registered handler report NOT_RUN (never silently PASS)."""
from __future__ import annotations

from ..core.results import Verdict
from ..state.inventory import collect_inventory
from .executor import Handler, NodeContext, NodeOutcome
from .nodes import Node


def _doctor(ctx: NodeContext, node: Node) -> NodeOutcome:
    from ..core.util import write_json

    inv = collect_inventory()
    write_json(ctx.workspace.reports_dir / "doctor_inventory.json", inv)
    missing_core = [
        t for t in ("python3", "git", "pdflatex")
        if not inv["tools"].get(t, {}).get("present")
    ]
    if missing_core:
        return NodeOutcome(Verdict.FAIL, {"missing_core_tools": missing_core})
    degraded = [
        t for t in ("latexmk", "dot", "qpdf", "pdftotext")
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
    order = {Verdict.PASS: 0, Verdict.DEGRADED: 1, Verdict.FAIL: 2,
             Verdict.HUMAN_REQUIRED: 3, Verdict.NOT_RUN: 4}
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
    "P15": lambda ctx, node: _chain(ctx, [
        _lazy("paper_factory.manuscript.scaffold", "run_manuscript_architecture"),
        _lazy("paper_factory.literature.verify", "build_references"),
    ]),
    "P16": lambda ctx, node: _compose(ctx, "methods"),
    "P17": lambda ctx, node: _compose(ctx, "results"),
    "P18": lambda ctx, node: _compose(ctx, "introduction"),
    "P19": lambda ctx, node: _compose(ctx, "discussion"),
    "P20": lambda ctx, node: _chain(ctx, [
        lambda c, n: _compose(c, "abstract"),
        _lazy("paper_factory.manuscript.compose", "run_finalize_main"),
    ]),
    "P21": _lazy("paper_factory.literature.verify", "run_citation_audit"),
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
    "P36": lambda ctx, node: NodeOutcome(Verdict.HUMAN_REQUIRED,
                                         {"reason": "final sign-off is a human decision"}),
    "P37": lambda ctx, node: NodeOutcome(Verdict.NOT_RUN,
                                         {"reason": "no external submission is ever automatic"}),
}

# verification-grade nodes that route through the HoH adapter when the config
# enables them (quota-aware subset; default P05 only — see VerificationCfg.hoh_nodes)
VERIHARNESS_CAPABLE = {"P04", "P05", "P07", "P09", "P10", "P16", "P17", "P18", "P20"}


def build_handlers(cfg_hoh_nodes: list[str] | None = None) -> dict[str, Handler]:
    enabled = set(cfg_hoh_nodes if cfg_hoh_nodes is not None else ["P05"]) & VERIHARNESS_CAPABLE
    handlers: dict[str, Handler] = dict(_BASE_HANDLERS)
    for nid in enabled:
        base = handlers.get(nid)
        if base is None:
            continue

        def make_wrapped(node_id: str, base_handler: Handler) -> Handler:
            def wrapped(ctx: NodeContext, node: Node) -> NodeOutcome:
                from ..adapters.veriharness.adapter import VeriharnessAdapter

                outcome = base_handler(ctx, node)
                adapter = VeriharnessAdapter(ctx.workspace)
                diag = adapter.doctor()
                if ctx.offline:
                    outcome.detail["hoh"] = "NOT_RUN"
                    outcome.detail["hoh_reason"] = "offline mode"
                    return outcome
                if not (diag.get("present") and diag.get("herdr")):
                    outcome.detail["hoh"] = "NOT_RUN"
                    outcome.detail["hoh_reason"] = ("DEGRADED_RUNTIME" if diag.get("present")
                                                    else "hoh missing")
                    return outcome
                spec = ctx.workspace.sub("hoh-specs") / f"{node_id}.md"
                spec.write_text(
                    f"# PF verification node {node_id}: {node.name}\n\n"
                    f"Work package: add a `VERIFICATION.md` to this repository that\n"
                    f"documents exactly how the experiment results are reproduced\n"
                    f"(commands, expected artifacts). Keep it factual and short.\n\n"
                    f"## Acceptance criteria\n"
                    f"- K1: `python3 code/analyze.py` exits 0 (analysis reproduces)\n"
                    f"- K2: `test -s results/summary.json` (result artifact exists)\n"
                    f"- K3: `test -s VERIFICATION.md` (documentation written)\n"
                    f"- K4: `grep -q analyze VERIFICATION.md` (docs name the analysis)\n",
                    encoding="utf-8")
                result = adapter.verify_work_package(node_id, spec)
                outcome.detail["hoh_run_id"] = result.run_id
                outcome.detail["hoh_verdict"] = result.verdict.value
                outcome.detail["hoh_receipts"] = len(result.receipts)
                outcome.detail["hoh_blocked_kind"] = result.blocked_kind
                for r in result.receipts:
                    ctx.workspace.record_receipt(
                        r["receipt_file"], ctx.run_id, node_id, "hoh",
                        ctx.workspace.receipts_dir / "hoh" / result.run_id / r["receipt_file"],
                        r["sha256"])
                # Verification-grade semantics: a node whose config demands HoH
                # verification does not keep a bare PASS without it.
                if outcome.verdict == Verdict.PASS:
                    if result.verdict == Verdict.FAIL:
                        outcome.verdict = Verdict.FAIL
                        outcome.detail["note"] = "HoH verification failed"
                    elif result.verdict != Verdict.PASS:
                        outcome.verdict = Verdict.DEGRADED
                        outcome.detail["note"] = ("deterministic work passed; HoH verification "
                                                  "incomplete/degraded — recorded honestly")
                return outcome

            return wrapped

        handlers[nid] = make_wrapped(nid, base)
    return handlers


HANDLERS: dict[str, Handler] = build_handlers()
