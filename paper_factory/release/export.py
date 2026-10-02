"""P33 Clean export + secret scan; P34 independent clean rebuild.

The release bundle carries no chat logs, no internal reviews, no local configs,
no tokens. The secret scan fails closed.

P33 additionally renders the FULL manuscript (draft/*.md) into an arXiv-style
LaTeX tree (`arxiv_src/`) via manuscript.latex_render; P34 compiles it,
assembles the arXiv upload tarball (comment-stripped sources + .bbl +
00README.XXX) and re-compiles the UNTARRED package in isolation (arXiv
simulation) with a pdffonts embedding check.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

from ..core.results import Verdict
from ..core.util import read_json, sha256_file, utcnow, write_json
from ..dag.executor import NodeContext, NodeOutcome
from .secrets import scan_tree


def _paper_id(ctx: NodeContext) -> str:
    pid = ctx.config.paper.id
    if pid == "auto":
        pid = ctx.workspace.target_root.name.replace(" ", "_")
    # the id becomes a directory name — never a path, never a dot-entry
    # (reviewer B F-MAJ-4 + R2-CRIT-1: '.'/'..' must be impossible)
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", pid) or pid in (".", ".."):
        raise ValueError(f"paper.id is not a safe identifier: {pid!r}")
    return pid


def run_clean_export(ctx: NodeContext) -> NodeOutcome:
    ws = ctx.workspace
    pid = _paper_id(ctx)
    rel = ws.release_dir / pid
    if rel.exists():
        # version, never delete; suffix guard: two exports inside the same
        # second must not collide on the parked name
        parked = rel.with_name(rel.name + f".v1.{utcnow().replace(':', '')}")
        n = 2
        while parked.exists():
            parked = rel.with_name(rel.name + f".v{n}.{utcnow().replace(':', '')}")
            n += 1
        rel.rename(parked)
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
            chat_excluded = (not ctx.config.release.include_chat_logs)
            rel_check = str(p.relative_to(paper)).lower()
            if (chat_excluded
                    and any(h in rel_check for h in ("chat", "transcript", "handoff"))):
                skipped_symlinks.append(f"{p.relative_to(paper)} (chat-log excluded by policy)")
                continue
            if p.is_symlink():
                target = p.resolve()
                if not target.is_relative_to(ws.root.resolve()):
                    skipped_symlinks.append(str(p.relative_to(paper)))
                    continue  # never export content from outside the workspace
                if not target.is_file():
                    skipped_symlinks.append(
                        f"{p.relative_to(paper)} (dangling or non-file symlink)")
                    continue
                # the policy filter must hold for the CONTENT, not just the
                # link name — a neutral link must not launder a chat log
                target_check = str(target.relative_to(ws.root.resolve())).lower()
                if (chat_excluded
                        and any(h in target_check for h in ("chat", "transcript", "handoff"))):
                    skipped_symlinks.append(
                        f"{p.relative_to(paper)} (symlink target excluded by chat policy)")
                    continue
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

    # full-manuscript arXiv-style render (representation transform of the
    # canonical draft — provenance in arxiv_src/render_provenance.json)
    arxiv_render: dict[str, str] = {}
    try:
        from ..manuscript.latex_render import render_full_manuscript
        prov = render_full_manuscript(ws, rel / "arxiv_src", ctx.run_id)
        arxiv_render = {"status": "rendered",
                        "source_sha256": prov["source"]["sha256"]}
    except Exception as exc:
        # never crash the export; P34 must see this as RENDER FAILED (not as
        # the benign 'no markdown source' case) — reviewer B F-MAJ-3
        arxiv_render = {"status": "error", "error": str(exc)[:300]}
    write_json(ws.reports_dir / "arxiv_render.json", arxiv_render)

    scan = scan_tree(rel, exclude_dirs=())  # everything shipped is scanned — no exclusions
    scan_path = rel / "secret_scan.json"
    write_json(scan_path, scan)
    if scan["verdict"] != "PASS":
        # a failed bundle is renamed, not deleted: evidence stays inspectable
        failed_dir = rel.with_name(rel.name + f".FAILED.{utcnow().replace(':', '')}")
        n = 2
        while failed_dir.exists():  # same-second re-failures must not collide
            failed_dir = rel.with_name(rel.name + f".FAILED.{utcnow().replace(':', '')}.{n}")
            n += 1
        rel.rename(failed_dir)
        parked_scan = failed_dir / "secret_scan.json"
        write_json(ws.reports_dir / "current_release.json", {
            "paper_id": pid, "status": "FAIL",
            "bundle": f"release/{failed_dir.name}",
            "secret_scan": f"release/{failed_dir.name}/secret_scan.json",
            "secret_scan_sha256": sha256_file(parked_scan),
            "exported_at": utcnow(), "run_id": ctx.run_id})
        return NodeOutcome(Verdict.FAIL, {"secret_scan": scan["verdict"],
                                          "findings": len(scan["findings"]),
                                          "symlinks": scan.get("symlinks", []),
                                          "bundle_parked": str(failed_dir)})

    # honest manifest: compute, don't assert — same exclusion vocabulary as
    # the export filter above
    chat_like = [e for e in exported
                 if any(h in e.lower() for h in ("chat", "transcript", "handoff"))]
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
        "secret_scan_symlinks": scan.get("symlinks", []),
        "secret_scan_encoding_fallbacks": scan.get("encoding_fallbacks", []),
    })
    # canonical pointer: U8 must bind to THIS bundle's scan, never to whatever
    # bundle happens to sort last (parked/FAILED/older releases stay visible
    # but are never confused with the active one). The pointer also pins the
    # FULL bundle content (every file + hash); P34 appends its build outputs.
    bundle_files = {p.relative_to(rel).as_posix(): sha256_file(p)
                    for p in sorted(rel.rglob("*")) if p.is_file() and not p.is_symlink()}
    write_json(ws.reports_dir / "current_release.json", {
        "paper_id": pid, "export_status": "PASS",
        "bundle": f"release/{pid}",
        "secret_scan": f"release/{pid}/secret_scan.json",
        "secret_scan_sha256": sha256_file(scan_path),
        "bundle_files": bundle_files,
        "exported_at": utcnow(), "run_id": ctx.run_id})
    return NodeOutcome(Verdict.PASS, {"paper_id": pid, "files": len(exported),
                                      "secret_scan": scan["verdict"],
                                      "skipped_symlinks": skipped_symlinks,
                                      "arxiv_render": arxiv_render,
                                      "scanned_files": scan["scanned_files"]})


_MISSING_PKG_RE = re.compile(r"! LaTeX Error: File `([^']+)' not found")


def _compile_tex(src_dir: Path, build_dir: Path, pdflatex: str, bibtex: str | None
                 ) -> dict:
    """pdflatex + bibtex + 2x pdflatex cycle. Returns a build report dict;
    a missing-package error is classified, never hidden."""
    build_dir.mkdir(parents=True, exist_ok=True)

    def run(cmd: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=300,
                              cwd=src_dir)

    run([pdflatex, "-interaction=nonstopmode", "-output-directory",
         str(build_dir), "main.tex"])
    if bibtex and (src_dir / "references.bib").exists():
        # bibtex must write .bbl/.blg into the BUILD dir: texmf openout_any=p
        # forbids absolute output paths (reviewer B R3-CRIT-1), and BIBINPUTS
        # lets bibtex find references.bib in the source dir from there. Note:
        # bibtex exits 0 even when it cannot open the database — the caller's
        # unresolved-citation gate is the real check.
        import os
        env = dict(os.environ, BIBINPUTS=str(src_dir))
        run2 = lambda cmd: subprocess.run(cmd, capture_output=True, text=True,
                                          timeout=300, cwd=build_dir, env=env)
        run2([bibtex, "main"])
    proc = None
    out = ""
    # up to 5 passes: natbib/hyperref/cleveref resolution can need more than
    # the textbook two (aux is read before the bbl within a run, so the bbl
    # only lands in the aux for the NEXT run) — stop when nothing is open
    for _ in range(5):
        proc = run([pdflatex, "-interaction=nonstopmode", "-output-directory",
                    str(build_dir), "main.tex"])
        out = proc.stdout
        if "undefined" not in out and "Rerun to get" not in out:
            break
    unresolved = bool(re.search(r"Citation .* undefined", out))
    hard_errors = [ln for ln in out.splitlines() if ln.startswith("!")] or ([] if proc else ["no run"])
    missing = _MISSING_PKG_RE.search(out)
    pdf = build_dir / "main.pdf"
    return {"pdf_produced": pdf.exists(), "pdf_path": str(pdf),
            "exit_code": proc.returncode if proc else None,
            "hard_errors": hard_errors[:5],
            "unresolved_citations": unresolved,
            "missing_package": missing.group(1) if missing else None,
            "log_tail": [] if pdf.exists() and not hard_errors else out.splitlines()[-15:]}


_VERB_ENV_RE = re.compile(
    r"\\(begin|end)\{(verbatim\*?|Verbatim\*?|lstlisting|minted)\}")


def _strip_comments(tex: str) -> str:
    """Own minimal comment stripper (arXiv upload hygiene): full-line comments
    are dropped, trailing unescaped %.. removed; verbatim-like environments
    (verbatim/Verbatim/lstlisting/minted, starred too) are passed through
    RAW (reviewer B F-CRIT-1: stripping inside them silently changes shipped
    content). Blank lines survive (LaTeX paragraph breaks). Environment
    markers are recognized only in the COMMENT-STRIPPED core — a marker
    mentioned inside a comment must not disable stripping for the rest of
    the file (reviewer B F-MAJ-1)."""
    out: list[str] = []
    in_verb = False

    def strip_line(line: str) -> str:
        res: list[str] = []
        i = 0
        while i < len(line):
            if line[i] == "\\" and i + 1 < len(line):
                res.append(line[i:i + 2])
                i += 2
                continue
            if line[i] == "%":
                break
            res.append(line[i])
            i += 1
        return "".join(res).rstrip()

    for line in tex.split("\n"):
        if in_verb:
            out.append(line)
            if re.search(r"\\end\s*\{(verbatim\*?|Verbatim\*?|lstlisting|minted)\}",
                         line):
                in_verb = False
            continue
        core = strip_line(line)
        begin = re.search(
            r"\\begin\s*\{(verbatim\*?|Verbatim\*?|lstlisting|minted)\}", core)
        if begin:
            # single-line environments: the raw line may carry the end marker
            # AFTER a % that comment-stripping removed from the core
            # (reviewer B R2-MAJ-1) — check the raw line past the begin too
            end = re.search(
                r"\\end\s*\{(verbatim\*?|Verbatim\*?|lstlisting|minted)\}",
                core) or re.search(
                r"\\end\s*\{(verbatim\*?|Verbatim\*?|lstlisting|minted)\}",
                line[begin.start():])
            if not end:
                in_verb = True
            out.append(line)  # keep the begin line raw
            continue
        if not core and not line.strip():
            out.append("")  # blank line: paragraph break — keep
        elif core:
            out.append(core)
    return "\n".join(out)


_ARXIV_NAME_RE = re.compile(r"^[A-Za-z0-9_+.,=-]+$")


def _build_arxiv_package(ctx: NodeContext, rel: Path, pid: str,
                         pdflatex: str, bibtex: str | None) -> dict:
    """Assemble + verify the arXiv upload package from the exported
    arxiv_src/: comment-stripped sources, .bbl, 00README.XXX, filename
    validation, tarball, untar-and-rebuild simulation, pdffonts check."""
    ws = ctx.workspace
    src = rel / "arxiv_src"
    report: dict = {"built_at": utcnow(), "run_id": ctx.run_id}
    if not (src / "main.tex").exists():
        # 'skipped' is only honest when there IS no markdown manuscript to
        # render; a crashed render with a present source is a deliverable
        # failure, never a quiet skip (reviewer B F-MAJ-3)
        from ..paperpal.docx_outbox import _find_source
        found = _find_source(ws)
        marker = read_json(ws.reports_dir / "arxiv_render.json") \
            if (ws.reports_dir / "arxiv_render.json").exists() else {}
        if found and found[1] == "markdown":
            report["status"] = "render_failed"
            report["reason"] = ("markdown manuscript exists but no arxiv_src "
                                f"was rendered: {marker.get('error', 'unknown')}")
        else:
            report["status"] = "skipped"
            report["reason"] = "no markdown manuscript source — LaTeX-by-design project"
        return report

    build = rel / "build_arxiv"
    rep = _compile_tex(src, build, pdflatex, bibtex)
    report["build"] = rep
    if rep["missing_package"]:
        report["status"] = "unsupported_environment"
        report["reason"] = f"missing LaTeX package: {rep['missing_package']}"
        return report
    if not rep["pdf_produced"] or rep["hard_errors"]:
        report["status"] = "build_failed"
        return report

    with tempfile.TemporaryDirectory(prefix="pf-arxiv-") as tmp:
        stage = Path(tmp) / "src"
        # never ship aux/output artifacts, hidden files or the internal
        # render provenance (arXiv rules: no .aux/.log/.out, no dotfiles).
        # symlinks=True keeps links AS links so we can reject them —
        # dereferencing would smuggle out-of-workspace content into the
        # tarball (reviewer B F-MAJ-2)
        _NO_SHIP = {".aux", ".log", ".out", ".toc", ".synctex.gz"}
        shutil.copytree(src, stage, symlinks=True,
                        ignore=lambda d, names: [
                            n for n in names
                            if n.startswith(".") or n == "render_provenance.json"
                            or Path(n).suffix in _NO_SHIP])
        leaked_links = [str(p.relative_to(stage))
                        for p in sorted(stage.rglob("*")) if p.is_symlink()]
        report["symlinks_rejected"] = leaked_links
        if leaked_links:
            report["status"] = "verification_failed"
            report["reason"] = f"symlinks in arxiv_src rejected: {leaked_links[:5]}"
            return report
        # .bbl from the verified build (arXiv-safe route: precompiled)
        bbl = build / "main.bbl"
        if bbl.exists():
            shutil.copy2(bbl, stage / "main.bbl")
        (stage / "00README.XXX").write_text("main.tex toplevelfile\n",
                                            encoding="utf-8")
        # comment stripping + rebuild verification
        for tex in sorted(stage.rglob("*.tex")):
            stripped = _strip_comments(tex.read_text(encoding="utf-8"))
            tex.write_text(stripped, encoding="utf-8")
        # filename + content validation
        bad_names = [str(p.relative_to(stage)) for p in sorted(stage.rglob("*"))
                     if not all(_ARXIV_NAME_RE.match(part) for part in
                                p.relative_to(stage).parts)]
        bad_refs = []
        for txt_file in sorted(stage.rglob("*.tex")) + sorted(stage.rglob("*.bib")):
            for ln in txt_file.read_text(encoding="utf-8").splitlines():
                # local path leakage — but never a URL scheme (https://…)
                if re.search(r"(/home/|/mnt/|/etc/|/Users/|/tmp/|~/|"
                             r"\b[A-Za-z]:[\\/]|(?<![\w.:])//)", ln):
                    bad_refs.append(f"{txt_file.name}: {ln.strip()[:80]}")
        report["bad_filenames"] = bad_names
        report["absolute_path_refs"] = bad_refs[:5]
        # repack
        tar_path = rel / f"arxiv-{pid}.tar.gz"
        with tarfile.open(tar_path, "w:gz") as tf:
            for p in sorted(stage.rglob("*")):
                tf.add(p, arcname=p.relative_to(stage).as_posix())
        report["tarball"] = str(tar_path)
        report["tarball_sha256"] = sha256_file(tar_path)
        report["tarball_bytes"] = tar_path.stat().st_size
        # arXiv simulation: untar fresh and rebuild from the package alone
        sim = Path(tmp) / "sim"
        sim.mkdir()
        with tarfile.open(tar_path) as tf:
            tf.extractall(sim, filter="data")
        sim_build = Path(tmp) / "sim_build"
        sim_rep = _compile_tex(sim, sim_build, pdflatex, None)  # bbl bundled
        report["sim_build"] = sim_rep
        fonts_ok = None
        if sim_rep["pdf_produced"]:
            pf = shutil.which("pdffonts")
            if pf:
                out = subprocess.run([pf, str(sim_build / "main.pdf")],
                                     capture_output=True, text=True).stdout
                rows = [ln.split() for ln in out.splitlines()[2:] if ln.strip()]
                # columns: name type encoding emb sub uni object-ID — the id
                # is TWO tokens, so emb/sub/uni sit at -5/-4/-3
                not_embedded, type3 = [], []
                for r in rows:
                    if len(r) >= 7 and r[-2].isdigit() and r[-1].isdigit():
                        emb, font_type = r[-5], " ".join(r[1:-6])
                        if emb == "no":
                            not_embedded.append(r[0])
                        if font_type == "Type 3":
                            type3.append(r[0])
                if rows:
                    fonts_ok = not not_embedded
                report["fonts_not_embedded"] = not_embedded
                report["fonts_type3"] = type3  # arXiv-tolerated, reported
            else:
                report["fonts_check"] = "unavailable (pdffonts missing)"
        report["fonts_all_embedded"] = fonts_ok

    ok = (not report["bad_filenames"] and not report["absolute_path_refs"]
          and report["sim_build"]["pdf_produced"]
          and not report["sim_build"]["hard_errors"]
          and not report["sim_build"].get("unresolved_citations")
          and report.get("fonts_all_embedded") is not False)
    report["status"] = "ok" if ok else "verification_failed"
    return report


def run_clean_rebuild(ctx: NodeContext) -> NodeOutcome:
    """P34: compile the exported bundle in isolation, with whatever TeX engine
    the machine actually has (latexmk preferred, pdflatex fallback). Also
    builds + verifies the arXiv upload package when arxiv_src/ was exported."""
    ws = ctx.workspace
    pid = _paper_id(ctx)
    rel = ws.release_dir / pid / "paper"
    main = rel / "main.tex"
    if not main.exists():
        return NodeOutcome(Verdict.FAIL, {"reason": "release bundle has no main.tex"})
    build = ws.release_dir / pid / "build"
    pdflatex = shutil.which("pdflatex")
    bibtex = shutil.which("bibtex")
    if not pdflatex:
        return NodeOutcome(Verdict.UNSUPPORTED_ENVIRONMENT,
                           {"reason": "no TeX engine (pdflatex) available"})

    rep = _compile_tex(rel, build, pdflatex, bibtex)
    if rep["missing_package"]:
        return NodeOutcome(Verdict.UNSUPPORTED_ENVIRONMENT,
                           {"reason": f"missing LaTeX package: {rep['missing_package']}",
                            "package": rep["missing_package"]})
    pdf = Path(rep["pdf_path"])
    write_json(ws.reports_dir / "clean_rebuild.json", {
        "rebuilt_at": utcnow(), "run_id": ctx.run_id, "pdf_produced": rep["pdf_produced"],
        "pdf_path": rep["pdf_path"], "engine": pdflatex,
        "exit_code": rep["exit_code"], "hard_errors": rep["hard_errors"]})
    # pin the build outputs into the active release manifest — after this,
    # every byte of the bundle (export set + build artifacts) is hash-pinned
    # and U8 can treat ANY unpinned file in the bundle as tampering
    pointer_path = ws.reports_dir / "current_release.json"
    if pointer_path.exists():
        pointer = read_json(pointer_path)
        if pointer.get("export_status") == "PASS" and pointer.get("bundle") == f"release/{pid}":
            files = pointer.setdefault("bundle_files", {})
            for p in sorted(build.rglob("*")):
                if p.is_file() and not p.is_symlink():
                    files[f"build/{p.relative_to(build).as_posix()}"] = sha256_file(p)
            write_json(pointer_path, pointer)

    # arXiv upload package (full manuscript): build, strip, tar, untar-rebuild,
    # pdffonts — failure here is a real deliverable failure, honestly FAIL
    arxiv = _build_arxiv_package(ctx, ws.release_dir / pid, pid, pdflatex, bibtex)
    write_json(ws.reports_dir / "arxiv_check.json", arxiv)
    if pointer_path.exists():
        pointer = read_json(pointer_path)
        if pointer.get("export_status") == "PASS" and pointer.get("bundle") == f"release/{pid}":
            files = pointer.setdefault("bundle_files", {})
            # pin build_arxiv on EVERY path (also failures — an unpinned file
            # is indistinguishable from tampering for U8; reviewer B F-MIN-3)
            build_arxiv = ws.release_dir / pid / "build_arxiv"
            if build_arxiv.exists():
                for p in sorted(build_arxiv.rglob("*")):
                    if p.is_file() and not p.is_symlink():
                        files[f"build_arxiv/{p.relative_to(build_arxiv).as_posix()}"] = sha256_file(p)
            if arxiv.get("tarball"):
                tar = Path(arxiv["tarball"])
                if tar.exists():
                    files[tar.name] = sha256_file(tar)
            write_json(pointer_path, pointer)

    detail = {"engine": pdflatex, "exit_code": rep["exit_code"],
              "pdf_produced": rep["pdf_produced"], "hard_errors": rep["hard_errors"],
              "log_tail": rep["log_tail"], "arxiv": arxiv.get("status")}
    if not rep["pdf_produced"] or rep["hard_errors"]:
        return NodeOutcome(Verdict.FAIL, detail)
    if arxiv.get("status") not in ("ok", "skipped"):
        detail["arxiv_detail"] = {k: v for k, v in arxiv.items()
                                  if k in ("status", "reason", "bad_filenames",
                                           "fonts_not_embedded")}
        return NodeOutcome(Verdict.FAIL, detail)
    return NodeOutcome(Verdict.PASS, detail)
