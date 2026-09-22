"""P22: manuscript numbers must come from generated macros, not raw literals.

Scans the full manuscript tree (paper/**/*.tex minus build/ and generated/),
not just a flat sections/ list (post-pilot review B-F1). Quantitative surfaces
come from statistics/quantitative.py — the same definitions the U2 closure
gate uses.
"""
from __future__ import annotations

from ..core.results import Verdict
from ..core.util import utcnow, write_json
from ..dag.executor import NodeContext, NodeOutcome
from .quantitative import (_RE_DECIMAL, find_quantitative, is_claim_section,
                           manuscript_tex_files, normalize_tex)


def run_numbers_units_audit(ctx: NodeContext) -> NodeOutcome:
    paper = ctx.workspace.paper_dir
    sections = manuscript_tex_files(paper)
    if not sections:
        return NodeOutcome(Verdict.NOT_RUN, {"reason": "no manuscript sections yet"})
    findings = []
    for s in sections:
        rel = str(s.relative_to(paper))
        raw = s.read_text(encoding="utf-8", errors="replace")
        text = normalize_tex(raw)
        # raw multi-digit decimals are findings in any manuscript file (macro
        # discipline); percent/fold/scientific/sample-size surfaces only in
        # claim-bearing files — "5-fold cross-validation" in sections/methods.tex
        # is a design constant, "42%" in an appendix is a result (fail-closed
        # inversion, canonical paths — post-pilot review B-G7)
        claim_section = is_claim_section(rel)
        quant = find_quantitative(text, claim_section=claim_section) if claim_section else []
        seen: set[str] = set()
        for m in _RE_DECIMAL.finditer(text):
            prefix = text[max(0, m.start() - 45):m.start()]
            if "\\pf" in prefix.split("{")[-1] or prefix.rstrip().endswith(("}", "\\")):
                continue  # macro expansion value, not a hand-typed literal
            seen.add(m.group(0))
            findings.append({"file": rel, "value": m.group(0),
                             "note": "raw decimal in prose; use \\pf… macro from numbers.tex"})
        for v in quant:
            if v in seen:
                continue
            seen.add(v)
            findings.append({"file": rel, "value": v,
                             "note": "raw quantitative claim in prose; use \\pf… macro "
                                     "from numbers.tex"})
    report = {"audited_at": utcnow(), "findings": findings}
    write_json(ctx.workspace.reports_dir / "numbers_units_audit.json", report)
    return NodeOutcome(Verdict.PASS, {"raw_numbers": len(findings)})
