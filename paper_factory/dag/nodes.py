"""The PAPER FACTORY DAG (P00–P37), declarative.

kind:
  deterministic  — pure code, no model
  agent          — needs a model via the provider router
  verification   — runs through the VeriHarness/HoH adapter
  human_gate     — stops for a human decision

Parallelism is derived from `deps`; the executor runs any node whose deps are
all satisfied (PASS or DEGRADED) and records honest terminal states otherwise.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Node:
    id: str
    name: str
    kind: str  # deterministic | agent | verification | human_gate
    deps: tuple[str, ...] = ()
    writes_final_prose: bool = False
    veriharness: bool = False  # verification-grade node → HoH run
    optional: bool = False     # UNAVAILABLE must not fail the pipeline
    tags: tuple[str, ...] = field(default_factory=tuple)


NODES: tuple[Node, ...] = (
    Node("P00", "Doctor", "deterministic"),
    Node("P01", "Intake", "deterministic", deps=("P00",)),
    Node("P02", "Context Mining", "agent", deps=("P01",)),
    Node("P03", "Research Reconstruction", "agent", deps=("P02",)),
    Node("P04", "Evidence Inventory", "verification", deps=("P01", "P03"), veriharness=True),
    Node("P05", "Result Integrity Audit", "verification", deps=("P04",), veriharness=True),
    Node("P06", "Literature Discovery", "deterministic", deps=("P01",)),
    Node("P07", "Prior-Art / Novelty Attack", "verification", deps=("P06", "P03"), veriharness=True),
    Node("P08", "Claim Graph", "agent", deps=("P04", "P05", "P07")),
    Node("P09", "Statistics", "verification", deps=("P04",), veriharness=True),
    Node("P10", "Reproducibility", "verification", deps=("P09",), veriharness=True),
    Node("P11", "Figure Planning", "agent", deps=("P09",)),
    Node("P12", "Table Planning", "agent", deps=("P09",)),
    Node("P13", "Figure Generation", "deterministic", deps=("P11",)),
    Node("P14", "Table Generation", "deterministic", deps=("P12",)),
    Node("P15", "Manuscript Architecture", "agent", deps=("P08", "P13", "P14")),
    Node("P16", "Methods", "agent", deps=("P15",), writes_final_prose=True, veriharness=True),
    Node("P17", "Results", "agent", deps=("P15",), writes_final_prose=True, veriharness=True),
    Node("P18", "Introduction / Related Work", "agent", deps=("P15", "P06", "P07"),
         writes_final_prose=True, veriharness=True),
    Node("P19", "Discussion / Limitations", "agent", deps=("P16", "P17"), writes_final_prose=True),
    Node("P20", "Abstract / Title", "agent", deps=("P16", "P17", "P18", "P19"),
         writes_final_prose=True, veriharness=True),
    Node("P21", "Citation Audit", "deterministic", deps=("P18", "P06")),
    Node("P22", "Numbers / Units / Symbols Audit", "deterministic", deps=("P17", "P13", "P14")),
    Node("P23", "Methods Review", "agent", deps=("P16",)),
    Node("P24", "Statistics Review", "agent", deps=("P09", "P17")),
    Node("P25", "Adversarial Reviewer 2", "agent", deps=("P16", "P17", "P18", "P19", "P20")),
    Node("P26", "Reproducibility Review", "agent", deps=("P10", "P17")),
    Node("P27", "Remediation", "agent", deps=("P21", "P22", "P23", "P24", "P25", "P26"),
         writes_final_prose=True),
    Node("P28", "Scientific Freeze", "deterministic", deps=("P27",)),
    Node("P29", "Language Review", "agent", deps=("P28",)),
    Node("P30", "Semantic Diff", "agent", deps=("P29",)),
    Node("P31", "Paperpal", "deterministic", deps=("P30",), optional=True),
    Node("P32", "Venue Compliance", "deterministic", deps=("P28",)),
    Node("P33", "Clean Export / Secret Scan", "deterministic", deps=("P31", "P32")),
    Node("P34", "Independent Clean Rebuild", "deterministic", deps=("P33",)),
    Node("P35", "Global Closure", "deterministic", deps=("P34",)),
    Node("P36", "Human Final Sign-Off", "human_gate", deps=("P35",)),
    Node("P37", "Optional External Submission", "human_gate", deps=("P36",), optional=True),
)

NODE_MAP: dict[str, Node] = {n.id: n for n in NODES}


def dependents() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {n.id: [] for n in NODES}
    for n in NODES:
        for d in n.deps:
            out[d].append(n.id)
    return out


def topo_order() -> list[str]:
    indeg = {n.id: len(n.deps) for n in NODES}
    ready = sorted([nid for nid, d in indeg.items() if d == 0])
    order: list[str] = []
    deps = dependents()
    while ready:
        nid = ready.pop(0)
        order.append(nid)
        for child in deps[nid]:
            indeg[child] -= 1
            if indeg[child] == 0:
                ready.append(child)
        ready.sort()
    if len(order) != len(NODES):
        raise ValueError("DAG has a cycle")
    return order
