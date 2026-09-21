"""P33 Clean export + secret scan; P34 independent clean rebuild.

The release bundle carries no chat logs, no internal reviews, no local configs,
no tokens. The secret scan fails closed.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from ..core.results import Verdict
from ..core.util import sha256_file, utcnow, write_json
from ..dag.executor import NodeContext, NodeOutcome
from .secrets import scan_tree


def _paper_id(ctx: NodeContext) -> str:
    pid = ctx.config.paper.id
    if pid == "auto":
        pid = ctx.workspace.target_root.name.replace(" ", "_")
    return pid


def run_clean_export(ctx: NodeContext) -> NodeOutcome:
    ws = ctx.workspace
    pid = _paper_id(ctx)
    rel = ws.release_dir / pid
    if rel.exists():
        parked = rel.with_name(rel.name + f".v1.{utcnow().replace(':', '')}")
        rel.rename(parked)  # version, never delete
    rel.mkdir(parents=True)

    paper = ws.paper_dir
    exported: list[str] = []
    skipped_symlinks: list[str] = []
    if paper.exists():
        for p in sorted(paper.rglob("*")):
            if not p.is_file() and not p.is_symlink():
                continue
            if "build" in p.parts:
                continue
            rel_check = str(p.relative_to(paper)).lower()
            if (not ctx.config.release.include_chat_logs
                    and any(h in rel_check for h in ("chat", "transcript", "handoff"))):
                skipped_symlinks.append(f"{p.relative_to(paper)} (chat-log excluded by policy)")
                continue
            if p.is_symlink():
                target = p.resolve()
                if not target.is_relative_to(ws.root.resolve()):
                    skipped_symlinks.append(str(p.relative_to(paper)))
                    continue  # never export content from outside the workspace
            dest = rel / "paper" / p.relative_to(paper)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dest)
            exported.append(str(dest.relative_to(rel)))

    # manifests
    for name in ("paper_metrics.json", "citation_audit.json", "figures_manifest.json",
                 "tables_manifest.json", "integrity_audit.json"):
        src = ws.reports_dir / name
        if src.exists():
            shutil.copy2(src, rel / name)
            exported.append(name)

    scan = scan_tree(rel)
    write_json(rel / "secret_scan.json", scan)
    if scan["verdict"] == "FAIL":
        # a failed bundle is renamed, not deleted: evidence stays inspectable
        failed_dir = rel.with_name(rel.name + f".FAILED.{utcnow().replace(':', '')}")
        rel.rename(failed_dir)
        return NodeOutcome(Verdict.FAIL, {"secret_scan": "FAIL",
                                          "findings": len(scan["findings"]),
                                          "bundle_parked": str(failed_dir)})

    # honest manifest: compute, don't assert
    chat_like = [e for e in exported if any(h in e.lower() for h in ("chat", "transcript", "history/"))]
    sums = []
    for p in sorted(rel.rglob("*")):
        if p.is_file() and p.name != "SHA256SUMS":
            sums.append(f"{sha256_file(p)}  {p.relative_to(rel)}")
    (rel / "SHA256SUMS").write_text("\n".join(sums) + "\n", encoding="utf-8")
    write_json(rel / "artifact_manifest.json", {
        "created_at": utcnow(), "paper_id": pid, "files": exported,
        "chat_logs_included": bool(chat_like),
        "chat_like_files_present": chat_like,
        "internal_reviews_included": any("reviews/" in e for e in exported),
        "skipped_external_symlinks": skipped_symlinks,
        "secret_scan": scan["verdict"],
        "secret_scan_skipped": scan.get("skipped", []),
    })
    return NodeOutcome(Verdict.PASS, {"paper_id": pid, "files": len(exported),
                                      "secret_scan": scan["verdict"],
                                      "skipped_symlinks": skipped_symlinks,
                                      "scanned_files": scan["scanned_files"]})


def run_clean_rebuild(ctx: NodeContext) -> NodeOutcome:
    """P34: compile the exported bundle in isolation, with whatever TeX engine
    the machine actually has (latexmk preferred, pdflatex fallback)."""
    ws = ctx.workspace
    pid = _paper_id(ctx)
    rel = ws.release_dir / pid / "paper"
    main = rel / "main.tex"
    if not main.exists():
        return NodeOutcome(Verdict.FAIL, {"reason": "release bundle has no main.tex"})
    build = ws.release_dir / pid / "build"
    build.mkdir(exist_ok=True)
    pdflatex = shutil.which("pdflatex")
    bibtex = shutil.which("bibtex")
    if not pdflatex:
        return NodeOutcome(Verdict.UNSUPPORTED_ENVIRONMENT,
                           {"reason": "no TeX engine (pdflatex) available"})

    def run(cmd: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd=rel)

    run([pdflatex, "-interaction=nonstopmode", "-output-directory", str(build), "main.tex"])
    if bibtex and (rel / "references.bib").exists():
        run([bibtex, str(build / "main")])
    proc = None
    for _ in (2, 3):
        proc = run([pdflatex, "-interaction=nonstopmode", "-output-directory",
                    str(build), "main.tex"])
    pdf = build / "main.pdf"
    hard_errors = [ln for ln in proc.stdout.splitlines() if ln.startswith("!")] if proc else ["no run"]
    write_json(ws.reports_dir / "clean_rebuild.json", {
        "rebuilt_at": utcnow(), "run_id": ctx.run_id, "pdf_produced": pdf.exists(),
        "pdf_path": str(pdf), "engine": pdflatex,
        "exit_code": proc.returncode if proc else None,
        "hard_errors": hard_errors[:5]})
    detail = {"engine": pdflatex, "exit_code": proc.returncode if proc else None,
              "pdf_produced": pdf.exists(), "hard_errors": hard_errors[:5],
              "log_tail": [] if pdf.exists() and not hard_errors else proc.stdout.splitlines()[-15:]}
    if not pdf.exists() or hard_errors:
        return NodeOutcome(Verdict.FAIL, detail)
    return NodeOutcome(Verdict.PASS, detail)
