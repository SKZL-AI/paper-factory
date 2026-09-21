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


def _intake(ctx: NodeContext, node: Node) -> NodeOutcome:
    from ..context.intake import run_intake

    return run_intake(ctx)


def _context_mining(ctx: NodeContext, node: Node) -> NodeOutcome:
    from ..context.mining import run_context_mining

    return run_context_mining(ctx)


def _evidence_inventory(ctx: NodeContext, node: Node) -> NodeOutcome:
    from ..evidence.inventory import run_evidence_inventory

    return run_evidence_inventory(ctx)


HANDLERS: dict[str, Handler] = {
    "P00": _doctor,
    "P01": _intake,
    "P02": _context_mining,
    "P04": _evidence_inventory,
}
