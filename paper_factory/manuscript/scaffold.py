"""P12 Manuscript scaffold: deterministic LaTeX skeleton with explicit
<<PF:...>> prose placeholders (no LLM here). main.tex wires in the
generated artifacts (generated/numbers.tex, generated/tables.tex).

Idempotent: existing files are never overwritten; they are left untouched
and recorded as 'kept_existing' in reports/manifest_manuscript.json.
"""
from __future__ import annotations

import re
from typing import Any

from ..core.results import Verdict
from ..core.util import sha256_file, utcnow, write_json
from ..dag.executor import NodeContext, NodeOutcome

SECTIONS = ["abstract", "introduction", "methods", "results", "discussion"]

_MAIN_TEX = r"""% scaffold by paper-factory — prose placeholders are marked <<PF:...>>
\documentclass[11pt]{article}
\usepackage[utf8]{inputenc}
\usepackage{booktabs}
\usepackage{graphicx}
\input{generated/numbers.tex}
\title{<<PF:title>>}
\author{<<PF:authors>>}
\date{<<PF:date>>}
\begin{document}
\maketitle
\begin{abstract}
\input{sections/abstract}
\end{abstract}
\input{sections/introduction}
\input{sections/methods}
\input{sections/results}
\input{generated/tables.tex}
\input{sections/discussion}
\bibliographystyle{plain}
\bibliography{references}
\end{document}
"""

_SECTION_TEX = {
    "abstract": "% Abstract — replace every <<PF:...>> placeholder with final prose.\n"
                "<<PF:abstract:prose>>\n\n<<PF:abstract:keywords>>\n",
    "introduction": "\\section{Introduction}\n\\label{sec:introduction}\n\n"
                    "<<PF:introduction:motivation>>\n\n<<PF:introduction:contributions>>\n",
    "methods": "\\section{Methods}\n\\label{sec:methods}\n\n"
               "<<PF:methods:setup>>\n\n<<PF:methods:metrics>>\n",
    "results": "\\section{Results}\n\\label{sec:results}\n\n"
               "<<PF:results:prose>>\n\n"
               "% Tables are available via generated/tables.tex (labels tab:*) — use \\ref{tab:...}.\n"
               "% Figures live in figures/ (PDF) — include with \\includegraphics, label fig:*.\n",
    "discussion": "\\section{Discussion}\n\\label{sec:discussion}\n\n"
                  "<<PF:discussion:interpretation>>\n\n<<PF:discussion:limitations>>\n",
}

_PLACEHOLDER_RE = re.compile(r"<<PF:")
_LABEL_RE = re.compile(r"\\label\{([^}]+)\}")
_REF_RE = re.compile(r"\\(?:ref|eqref|autoref|pageref)\{([^}]+)\}")


def run_manuscript_architecture(ctx: NodeContext) -> NodeOutcome:
    """Create paper/main.tex + paper/sections/*.tex in the workspace paper_dir.
    Existing files are kept untouched (status 'kept_existing')."""
    paper = ctx.workspace.paper_dir
    targets: dict[str, str] = {"main.tex": _MAIN_TEX}
    for section in SECTIONS:
        targets[f"sections/{section}.tex"] = _SECTION_TEX[section]

    files: list[dict[str, Any]] = []
    created = kept = 0
    for rel in sorted(targets):
        path = paper / rel
        if path.exists():
            status = "kept_existing"
            kept += 1
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(targets[rel], encoding="utf-8")
            status = "created"
            created += 1
        files.append({"path": f"paper/{rel}", "sha256": sha256_file(path), "status": status})

    manifest = {"generated_at": utcnow(), "files": files,
                "created": created, "kept_existing": kept}
    write_json(ctx.workspace.reports_dir / "manifest_manuscript.json", manifest)
    return NodeOutcome(Verdict.PASS, {"created": created, "kept_existing": kept})


def run_section_check(ctx: NodeContext, section: str) -> NodeOutcome:
    """Check one section file: no <<PF:...>> placeholders left, no dangling
    \\ref (label must exist somewhere under paper/), no duplicate \\label."""
    name = section if section.endswith(".tex") else f"{section}.tex"
    path = ctx.workspace.paper_dir / "sections" / name
    if not path.exists():
        return NodeOutcome(Verdict.FAIL, {"section": section, "reason": "file missing",
                                          "expected": f"paper/sections/{name}"})
    text = path.read_text(encoding="utf-8", errors="replace")
    placeholders = len(_PLACEHOLDER_RE.findall(text))
    labels = _LABEL_RE.findall(text)
    refs = _REF_RE.findall(text)

    all_labels: set[str] = set()
    paper = ctx.workspace.paper_dir
    if paper.exists():
        for other in sorted(paper.rglob("*.tex")):
            all_labels.update(_LABEL_RE.findall(other.read_text(encoding="utf-8",
                                                                errors="replace")))
    dangling = sorted(set(refs) - all_labels)
    duplicates = sorted({lbl for lbl in labels if labels.count(lbl) > 1})

    problems: list[str] = []
    if placeholders:
        problems.append(f"{placeholders} <<PF:...>> placeholder(s) remaining")
    if dangling:
        problems.append(f"dangling \\ref(s): {dangling}")
    if duplicates:
        problems.append(f"duplicate \\label(s): {duplicates}")

    detail = {"section": section, "placeholders": placeholders,
              "labels": labels, "refs": refs, "dangling_refs": dangling,
              "duplicate_labels": duplicates, "problems": problems}
    write_json(ctx.workspace.reports_dir / f"section_check_{section.replace('.tex', '')}.json",
               {"checked_at": utcnow(), **detail,
                "verdict": (Verdict.FAIL if problems else Verdict.PASS).value})
    if problems:
        return NodeOutcome(Verdict.FAIL, detail)
    return NodeOutcome(Verdict.PASS, detail)


def run_manuscript_structure_check(ctx: NodeContext) -> NodeOutcome:
    """All-sections wiring of run_section_check into the DAG (P20): catches
    surviving <<PF:...>> placeholders, dangling \\ref and duplicate \\label
    across the composed manuscript — e.g. when a compose node was skipped or
    failed upstream. Not redundant with P22 (numbers/units only)."""
    per_section: dict[str, str] = {}
    problems: dict[str, list[str]] = {}
    for section in SECTIONS:
        outcome = run_section_check(ctx, section)
        per_section[section] = outcome.verdict.value
        if outcome.verdict == Verdict.FAIL:
            problems[section] = outcome.detail.get("problems", [])
    summary = {"checked_at": utcnow(), "sections": per_section,
               "verdict": (Verdict.FAIL if problems else Verdict.PASS).value}
    write_json(ctx.workspace.reports_dir / "manuscript_structure_check.json", summary)
    if problems:
        return NodeOutcome(Verdict.FAIL, {"sections": per_section, "problems": problems})
    return NodeOutcome(Verdict.PASS, {"sections": per_section})
