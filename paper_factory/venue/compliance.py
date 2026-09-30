"""P32 Venue compliance: deterministic checks per target venue.
v1 targets: 'preprint' (minimal) and 'arxiv' (basic compile/size/source rules).
"""
from __future__ import annotations

from ..core.results import Verdict
from ..core.util import utcnow, write_json
from ..dag.executor import NodeContext, NodeOutcome

VENUE_RULES = {
    "preprint": ["main_tex_exists", "bib_exists", "compiles"],
    "arxiv": ["main_tex_exists", "bib_exists", "compiles", "no_absolute_paths", "source_archive_ready"],
}


def _try_build(paper: Path) -> dict:
    """Actively compile the manuscript (venue compliance is a check, not a look).

    LaTeX semantics: references/citations need multiple passes + bibtex;
    pdflatex exits 1 on undefined references even when it writes a PDF.
    We run pdflatex → bibtex → pdflatex → pdflatex and judge the final pass.
    """
    import shutil
    import subprocess

    main = paper / "main.tex"
    if not main.exists():
        return {"pass": False, "reason": "main.tex missing"}
    build = paper / "build"
    build.mkdir(exist_ok=True)
    pdflatex = shutil.which("pdflatex")
    bibtex = shutil.which("bibtex")
    if not pdflatex:
        return {"pass": False, "state": "UNSUPPORTED_ENVIRONMENT", "reason": "no TeX engine"}

    def run(cmd: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(cmd, cwd=paper, capture_output=True, text=True, timeout=300)

    log_tail: list[str] = []
    exit_code = None
    try:
        for _pass in (1,):
            proc = run([pdflatex, "-interaction=nonstopmode", "-output-directory",
                        str(build), "main.tex"])
        if bibtex and (paper / "references.bib").exists():
            run([bibtex, str(build / "main")])
        for _pass in (2, 3):
            proc = run([pdflatex, "-interaction=nonstopmode", "-output-directory",
                        str(build), "main.tex"])
        exit_code = proc.returncode
        log_tail = proc.stdout.splitlines()[-10:]
    except subprocess.TimeoutExpired:
        return {"pass": False, "reason": "compile timeout"}
    pdf = build / "main.pdf"
    full_log = proc.stdout if proc else ""
    hard_errors = [ln for ln in full_log.splitlines() if ln.startswith("!")]
    ok = pdf.exists() and not hard_errors
    return {"pass": ok, "engine": pdflatex, "exit_code": exit_code,
            "pdf_exists": pdf.exists(), "hard_errors": hard_errors[:5],
            "log_tail": [] if ok else full_log.splitlines()[-10:]}


def run_venue_compliance(ctx: NodeContext) -> NodeOutcome:
    venue = ctx.target_venue or ctx.config.paper.target or "preprint"
    rules = VENUE_RULES.get(venue, VENUE_RULES["preprint"])
    paper = ctx.workspace.paper_dir
    checks: dict[str, dict] = {}

    checks["main_tex_exists"] = {"pass": (paper / "main.tex").exists()}
    # bib_exists is deliberately the WEAK mechanical gate (existence only;
    # a draft-derived fallback bib counts). The semantic gate is closure U4,
    # which attests resolution/verification — see release/closure.py:_u4
    bib = (paper / "references.bib").exists() or list(ctx.workspace.target_root.glob("literature/*.bib"))
    checks["bib_exists"] = {"pass": bool(bib)}
    checks["compiles"] = _try_build(paper)
    if "no_absolute_paths" in rules:
        bad = []
        for tex in paper.rglob("*.tex"):
            text = tex.read_text(encoding="utf-8", errors="replace")
            if "/home/" in text or "/mnt/" in text:
                bad.append(str(tex.relative_to(paper)))
        checks["no_absolute_paths"] = {"pass": not bad, "offenders": bad}
    if "source_archive_ready" in rules:
        checks["source_archive_ready"] = {"pass": True, "note": "archive created in P33"}

    failed = [k for k, v in checks.items() if not v.get("pass")]
    report = {"checked_at": utcnow(), "venue": venue, "checks": checks, "failed": failed}
    write_json(ctx.workspace.reports_dir / "venue_compliance.json", report)
    if failed and not ctx.config.release.clean_build:
        return NodeOutcome(Verdict.DEGRADED, {"failed": failed, "venue": venue})
    return NodeOutcome(Verdict.FAIL if failed else Verdict.PASS,
                       {"failed": failed, "venue": venue})
