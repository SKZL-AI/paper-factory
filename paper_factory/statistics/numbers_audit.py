"""P22: manuscript numbers must come from generated macros, not raw literals."""
from __future__ import annotations

import re

from ..core.results import Verdict
from ..core.util import utcnow, write_json
from ..dag.executor import NodeContext, NodeOutcome

RAW_DECIMAL = re.compile(r"\b0?\.\d{2,}\b")


def run_numbers_units_audit(ctx: NodeContext) -> NodeOutcome:
    paper = ctx.workspace.paper_dir
    sections = (sorted(paper.glob("sections/*.tex")) + [paper / "main.tex"]) if paper.exists() else []
    sections = [s for s in sections if s.exists()]
    if not sections:
        return NodeOutcome(Verdict.NOT_RUN, {"reason": "no manuscript sections yet"})
    findings = []
    for s in sections:
        text = s.read_text(encoding="utf-8", errors="replace")
        for m in RAW_DECIMAL.finditer(text):
            prefix = text[max(0, m.start() - 45):m.start()]
            if "\\pf" in prefix.split("{")[-1] or prefix.rstrip().endswith(("}", "\\")):
                continue  # macro expansion value, not a hand-typed literal
            line_start = text.rfind("\n", 0, m.start()) + 1
            line = text[line_start:text.find("\n", m.start())]
            if line.strip().startswith("%"):
                continue
            findings.append({"file": s.name, "value": m.group(0),
                             "note": "raw decimal in prose; use \\pf… macro from numbers.tex"})
    report = {"audited_at": utcnow(), "findings": findings}
    write_json(ctx.workspace.reports_dir / "numbers_units_audit.json", report)
    return NodeOutcome(Verdict.PASS, {"raw_numbers": len(findings)})
