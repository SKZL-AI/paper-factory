"""P08 Claim graph builder (deterministic core): extract candidate empirical
claims from drafts/notes, link to evidence, mark UNSUPPORTED what no artifact
can carry. Drafts are T4 — they propose claims, they never prove them.
"""
from __future__ import annotations

import json
import re
from typing import Any

from ..core.results import ClaimStatus, Verdict
from ..core.util import utcnow, write_json
from ..dag.executor import NodeContext, NodeOutcome
from .graph import Claim, ClaimGraph, save_claims

CLAIM_CUE = re.compile(
    r"([^.]*\b(?:faster|slower|speedup|latency|throughput|improve[sd]?|outperform|"
    r"reduc(?:es|ed)|significant|achieves?|reaches?|reaching|lower|higher)\b[^.]*\.)",
    re.IGNORECASE)
NUM = re.compile(r"\b\d+(?:\.\d+)?%?\b")

# claim text keyword → required metric field hints. If no metric field matches,
# the claim cannot be supported by the artifacts.
REQUIRED_METRIC_HINTS = {
    "faster": ("time", "latency", "speed", "runtime", "duration"),
    "slower": ("time", "latency", "speed", "runtime", "duration"),
    "speedup": ("time", "latency", "speed", "runtime"),
    "latency": ("latency", "time"),
    "throughput": ("throughput", "ops"),
    "significant": ("test", "pvalue", "ci"),
}

# LaTeX structure that makes a candidate a fragment, not a claim (GAP-005:
# the pilot extracted \hypertarget lines and table rows as "claims"). Refs,
# cites, labels and captions are normalized away by _clean_for_extraction and
# must NOT reject an otherwise clean sentence (reviewer B-E2).
_STRUCT_CMD = re.compile(
    r"\\(?:hypertarget|(?:sub)*section|begin|end|toprule|midrule|"
    r"bottomrule|noalign|linewidth|input|include|import|documentclass)\b")
_HEADING_MD = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", re.MULTILINE)
_HEADING_TEX = re.compile(r"\\(?:sub)*section(?:\[[^]]*\])?\s*\{([^}]*)\}")


def _is_structural_fragment(cand: str) -> bool:
    """Reject candidates that are markup, not scientific statements."""
    if _STRUCT_CMD.search(cand):
        return True
    if "&" in cand or "\\\\" in cand:  # table row / cell fragment
        return True
    stripped = cand.strip()
    if not stripped[:1].isalpha():  # a sentence starts with a letter
        return True
    if len(stripped.split()) < 6 or sum(ch.isalpha() for ch in stripped) < 20:
        return True  # too little prose to carry a scientific claim
    return False


def _section_at(text: str, pos: int) -> str | None:
    """Nearest markdown/LaTeX heading above pos — path-aware claim provenance."""
    section = None
    for m in list(_HEADING_MD.finditer(text)) + list(_HEADING_TEX.finditer(text)):
        if m.start() <= pos:
            section = m.group(1).strip()
        else:
            break
    return section


def _clean_for_extraction(text: str) -> str:
    """Markup that is not a scientific statement is removed BEFORE candidate
    extraction, so a \\section/\\hypertarget block cannot glue itself onto the
    following sentence (GAP-005 pilot debris). Heading text survives as a
    markdown-ish heading so _section_at still works. Floats and lists are
    UNWRAPPED, not dropped — their captions/items are prose and can carry
    result claims (reviewer B-E2); only pure grid/math environments drop out.
    Inline macros (fonts, caption, \\cite, \\ref, \\url, $…$ math, …) are all
    folded to their text argument first — a brace-carrying macro inside a
    caption must never strand the whole sentence (reviewer B round 3).
    """
    text = _HEADING_TEX.sub(lambda m: f"\n## {m.group(1)}\n", text)
    text = re.sub(r"\\hypertarget\{[^}]*\}\{[^}]*\}", "\n", text)
    # canonical nesting is table/figure > tabular: unwrap the float first, then
    # drop the grid environment inside; the caption text stays
    prev = None
    while prev != text:
        prev = text
        text = re.sub(r"\\begin\{(?:table|figure)\*?\}(.*?)\\end\{(?:table|figure)\*?\}",
                      lambda m: "\n" + m.group(1) + "\n", text, flags=re.DOTALL)
    text = re.sub(r"\\begin\{(?:tabular|tabularx|array|equation|align)\*?\}.*?"
                  r"\\end\{(?:tabular|tabularx|array|equation|align)\*?\}",
                  "\n", text, flags=re.DOTALL)
    # lists: keep item prose, drop scaffolding
    text = re.sub(r"\\(?:begin|end)\{(?:itemize|enumerate|description)\*?\}", "\n", text)
    text = re.sub(r"\\item\b(?:\[[^]]*\])?", "\n", text)
    # refs/cites/labels/urls/inline-math fold to tokens BEFORE any brace rule
    text = re.sub(r"\\label\{[^}]*\}", "", text)
    text = re.sub(r"\\(?:page|eq|auto)?ref\{[^}]*\}", " REF ", text)
    text = re.sub(r"\\cite\w*(?:\[[^]]*\])*\{[^}]*\}", " CITE ", text)
    text = re.sub(r"\\url\{([^}]*)\}", r"\1", text)
    text = re.sub(r"\$([^$]*)\$",
                  lambda m: m.group(1).replace("{", "").replace("}", ""), text)
    # every remaining simple command unwraps to its argument (caption, textbf,
    # emph, …) — one generic fixpoint kills the whole wrapper class
    prev = None
    while prev != text:
        prev = text
        text = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^]]*\])?\s*\{([^{}]*)\}", r" \1 ", text)
    # leftover bare structural command lines
    text = re.sub(r"^\s*\\(?:noalign|toprule|midrule|bottomrule)\b.*$", "",
                  text, flags=re.MULTILINE)
    # brace-less no-op commands must not kill a sentence they precede
    # (reviewer B round 4: \noindent/\par at sentence start)
    text = re.sub(r"(?m)^\s*\\(?:noindent|par|medskip|bigskip|smallskip|"
                  r"newpage|clearpage|vspace|hspace)\b\s*(\{[^}]*\})?\s*", "", text)
    return text


def _extract_candidates(text: str) -> list[tuple[int, str]]:
    return [(m.start(), m.group(1).strip()) for m in CLAIM_CUE.finditer(text)
            if NUM.search(m.group(1))]


def run_claim_graph(ctx: NodeContext) -> NodeOutcome:
    root = ctx.workspace.target_root
    graph = ClaimGraph()

    metrics_path = ctx.workspace.reports_dir / "paper_metrics.json"
    metrics: dict[str, Any] = {}
    if metrics_path.exists():
        metrics = json.loads(metrics_path.read_text(encoding="utf-8")).get("metrics", {})

    n = 0
    unsupported = 0
    audit_findings: list[dict] = []
    for draft in sorted(root.glob("draft/*.md")) + sorted(root.glob("draft/*.tex")):
        text = _clean_for_extraction(
            draft.read_text(encoding="utf-8", errors="replace"))
        rel = str(draft.relative_to(root))
        for pos, cand in _extract_candidates(text):
            if _is_structural_fragment(cand):
                continue  # markup debris is not a claim (GAP-005)
            n += 1
            cid = f"C{n:03d}"
            section = _section_at(text, pos)
            source = f"{rel}#§{section}" if section else rel
            lower = cand.lower()
            status = ClaimStatus.UNSUPPORTED
            note = "no deterministic metric binding for this claim shape"
            bound: list[str] = []

            def _bind(hints: tuple[str, ...]) -> list[str]:
                # letter-boundary hints (A N-C): "ci" must not match inside
                # "specificity", "test" not inside "latest" — snake_case
                # separators are fine, letters are not
                def _m(field: str, hint: str) -> bool:
                    return re.search(rf"(?<![a-z]){re.escape(hint)}(?![a-z])",
                                     field) is not None
                return sorted(k for k, v in metrics.items()
                              if any(_m(str(v.get("field", "")).lower(), h)
                                     for h in hints))

            # F4: a significance claim must FIRST satisfy the test-artifact
            # requirement — cue order must never let "significantly faster"
            # bind a latency metric while skipping the test
            sig = "significant" in lower
            cue_hints = next((hints for cue, hints in REQUIRED_METRIC_HINTS.items()
                              if cue != "significant" and cue in lower), None)
            metric_bound = _bind(cue_hints) if cue_hints else []
            if sig:
                test_bound = _bind(REQUIRED_METRIC_HINTS["significant"])
                if not test_bound:
                    note = "significance claimed but no statistical test artifact exists"
                elif cue_hints and not metric_bound:
                    note = f"no metric field matches required hints {cue_hints}"
                else:
                    status = ClaimStatus.EVIDENCE_FOUND
                    note = None
                    bound = sorted(set(test_bound) | set(metric_bound))
            elif cue_hints:
                if metric_bound:
                    status = ClaimStatus.EVIDENCE_FOUND
                    note = None
                    bound = metric_bound
                else:
                    note = f"no metric field matches required hints {cue_hints}"
            if status == ClaimStatus.UNSUPPORTED:
                unsupported += 1
                # claim-bound finding: remediation may only retire claims it can
                # point to (GAP-004) — the unbound global sweep is gone
                audit_findings.append({
                    "severity": "MAJOR", "kind": "unsupported_claim",
                    "claim_id": cid, "draft": rel,
                    "excerpt": cand[:160],
                    "note": note,
                })
            graph.claims.append(Claim(
                claim_id=cid, type="empirical",
                statement=cand[:500], status=status,
                evidence=bound,  # concrete metric ids — never a placeholder (GAP-005)
                source=source,
                risk={"overclaim": "high" if status == ClaimStatus.UNSUPPORTED else "low"},
            ))
    save_claims(ctx.workspace.claims_dir / "claims.yaml", graph)
    write_json(ctx.workspace.reports_dir / "claims_audit.json",
               {"audited_at": utcnow(), "findings": audit_findings})
    detail = {"claims": len(graph.claims), "unsupported": unsupported}
    if unsupported:
        # honest: claims exist that no artifact carries — pipeline continues,
        # closure (U1) will fail until remediation retires them
        return NodeOutcome(Verdict.DEGRADED, detail)
    return NodeOutcome(Verdict.PASS if n else Verdict.DEGRADED,
                       detail if n else {"reason": "no candidate claims found"})
