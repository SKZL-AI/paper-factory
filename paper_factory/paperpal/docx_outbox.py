"""Versioned DOCX outbox for the Paperpal/Word bridge (consultant brief D).

Paperpal works on DOCX, not on LaTeX/markdown. This module renders the
richest available canonical manuscript into a versioned, fully-provenanced
DOCX the Word session will open:

    source selection (richest first):
      1. draft/*.md — the complete paper text (DRAFT_ASSISTED pilots)
      2. paper/main.tex — the PF-built manuscript
    staging:
      - broken absolute image paths (e.g. chat-export '/mnt/data/…') are
        rewritten to the draft-local figure files when the basename or the
        numbered order matches a present PNG/JPEG (never silently dropped)
    render:
      - pandoc with a generated arXiv-style reference.docx (Times-family
        serif, 10pt body, justified, compact headings, bordered tables);
        figures embedded at their declared size, captions kept
    provenance (consultant D):
      source path + sha256, docx sha256, conversion method, generated_at,
      run_id, figure/table counts — written next to the DOCX as
      '<name>.provenance.json'

The function never touches the source manuscript; the staged markdown lives
in the workspace and is itself hashed.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Any

from ..core.util import sha256_file, utcnow, write_json

_IMG_TAG = re.compile(r'<img\s+[^>]*?src="([^"]+)"[^>]*?/?>', re.I | re.S)
_IMG_ATTR = re.compile(r'(\w[\w-]*)="([^"]*)"')
_IMG_EXTS = {".png", ".jpg", ".jpeg", ".gif"}


def _rewrite_image_paths(text: str, figure_dir: Path) -> tuple[str, list[dict]]:
    """Map broken absolute chat-export paths onto the draft-local figures
    AND convert raw-HTML <img> tags to pandoc image syntax — the docx writer
    silently drops raw HTML, which would lose every figure (found by test,
    2026-10-01). Strategy per <img>: exact basename match in figure_dir
    first, else ordinal match (imageN → N-th sorted figure). Never drops a
    figure — an unmappable path is reported in the mapping list with
    ok=False and the tag preserved."""
    figures = sorted(p for p in figure_dir.iterdir()
                     if p.suffix.lower() in _IMG_EXTS) if figure_dir.is_dir() else []
    mapping: list[dict] = []

    def sub(m: re.Match) -> str:
        tag = m.group(0)
        src = m.group(1)
        attrs = dict(_IMG_ATTR.findall(tag))
        name = Path(src).name
        hit = next((p for p in figures if p.name == name), None)
        if hit is None:
            num = re.search(r"(\d+)", name)
            if num and figures:
                idx = int(num.group(1)) - 1
                hit = figures[idx] if 0 <= idx < len(figures) else None
        if hit is None:
            mapping.append({"from": src, "to": None, "ok": False})
            return tag
        # basename matches are exact; ordinal fallback is a GUESS by
        # position — visible in the sidecar, never silent (reviewer B R3-F2)
        conf = "basename" if hit.name == name else "ordinal"
        mapping.append({"from": src, "to": hit.name, "ok": True,
                        "confidence": conf})
        cap = attrs.get("title") or attrs.get("alt") or hit.stem
        cap = cap.replace("[", "(").replace("]", ")")
        width = ""
        style = attrs.get("style", "")
        wm = re.search(r"width:([\d.]+in)", style)
        if wm:
            width = f"{{width={wm.group(1)}}}"
        return f"\n\n![{cap}]({hit.name}){width}\n\n"

    return _IMG_TAG.sub(sub, text), mapping


def _patch_styles(styles: str) -> str:
    """arXiv-like typography onto pandoc's default reference styles
    (pandoc 3.1.3 reality: fonts live in theme1.xml, body size in
    docDefaults w:sz, style blocks carry <w:name> before <w:pPr> —
    reviewer B R3-F1). Serif body (Times via theme), 10pt, justified body
    paragraphs, black bold headings. Kept deliberately minimal — Word stays
    the layout authority."""
    # body default 10pt (half-points): docDefaults sz 24 → 20
    styles = re.sub(r'(<w:docDefaults>.*?<w:sz w:val=")\d+("\s*/>)',
                    r"\g<1>20\g<2>", styles, count=1, flags=re.S)
    # justify body paragraphs: jc goes AFTER spacing/ind inside pPr
    # (CT_PPr child order), and pPr goes AFTER qFormat in the style block
    # (CT_Style order) — wrong order can trigger Word's 'unreadable content'
    # repair (reviewer B R3 restfinding)
    styles = re.sub(
        r'(<w:style [^>]*w:styleId="BodyText"[^>]*>.*?<w:pPr>.*?)(</w:pPr>)',
        r'\1<w:jc w:val="both" />\2', styles, flags=re.S)
    styles = re.sub(
        r'(<w:style [^>]*w:styleId="FirstParagraph"[^>]*>.*?<w:qFormat />)',
        r'\1<w:pPr><w:jc w:val="both" /></w:pPr>', styles, flags=re.S)
    # headings: black instead of theme blue (arXiv look)
    styles = re.sub(r'(<w:style [^>]*w:styleId="Heading\d"[^>]*>.*?)'
                    r'<w:color w:val="[0-9A-Fa-f]{6}"[^/]*/>',
                    r'\1<w:color w:val="000000" />', styles, flags=re.S)
    return styles


def _patch_theme(theme: str) -> str:
    """pandoc's reference styles reference theme fonts (minorHAnsi = body,
    majorHAnsi = headings) — the actual typeface lives in theme1.xml."""
    return re.sub(r'<a:latin typeface="[^"]*"\s*/>',
                  '<a:latin typeface="Times New Roman" />', theme)


def ensure_reference_docx(cache_dir: Path) -> Path:
    """Generate the arXiv-style reference.docx from pandoc's default data
    file (no extra dependencies: zipfile + regex on styles.xml)."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    ref = cache_dir / "arxiv_style_reference_v3.docx"
    if ref.exists():
        return ref
    default = subprocess.run(
        ["pandoc", "--print-default-data-file", "reference.docx"],
        capture_output=True, check=True).stdout
    import io
    src = zipfile.ZipFile(io.BytesIO(default))
    styles = _patch_styles(src.read("word/styles.xml").decode("utf-8"))
    theme = _patch_theme(src.read("word/theme/theme1.xml").decode("utf-8"))
    out = zipfile.ZipFile(ref, "w", zipfile.ZIP_DEFLATED)
    for item in src.infolist():
        if item.filename == "word/styles.xml":
            data = styles.encode("utf-8")
        elif item.filename == "word/theme/theme1.xml":
            data = theme.encode("utf-8")
        else:
            data = src.read(item.filename)
        out.writestr(item, data)
    out.close()
    return ref


def _find_source(ws: Any) -> tuple[Path, str] | None:
    """The manuscript source the DOCX renders from (draft markdown preferred,
    else the composed LaTeX). Multiple versioned drafts: the HIGHEST version
    wins (paper1_v1_3_1.md over paper1_v1_3_0.md) — never the stale one."""
    root = ws.target_root
    drafts = sorted(root.glob("draft/*.md"))

    def _ver(p: Path) -> tuple:
        m = re.findall(r"_v(\d+)_(\d+)(?:_(\d+))?", p.name)
        return tuple(int(x or 0) for x in m[-1]) if m else (0, 0, 0)

    if drafts:
        return max(drafts, key=_ver), "markdown"
    if (ws.paper_dir / "main.tex").exists():
        return ws.paper_dir / "main.tex", "latex"
    return None


#: versioned outbox renders carry a fixed-width UTC timestamp in the name —
#: name order == time order, and planted lookalikes are not "versions"
DOCX_NAME_RE = re.compile(r"^paper-(\d{8})T(\d+)Z\.docx$")


def _future_dated(name: str, skew_hours: int = 24) -> bool:
    """True when the embedded timestamp is unparseable or in the future
    (reviewer B R4 N-B1: a planted far-future but regex-conform name must not
    become 'newest' and gate-DoS the chain)."""
    from datetime import datetime, timedelta, timezone

    m = DOCX_NAME_RE.match(name)
    if not m:
        return False
    try:
        ts = datetime.strptime(m.group(1) + m.group(2)[:6], "%Y%m%d%H%M%S")
        ts = ts.replace(tzinfo=timezone.utc)
    except ValueError:
        return True  # unparseable timestamps are not legitimate renders
    return ts > datetime.now(timezone.utc) + timedelta(hours=skew_hours)


def reuse_or_build_docx_outbox(workspace: Any, run_id: str) -> dict[str, Any] | None:
    """Render-skip (reviewer B R3-B1, livelock fix): P31 runs on every
    pipeline pass, and every fresh render would instantly stale the evidence
    an operator bound to the previous DOCX — the binding could never converge.
    When the newest versioned DOCX is anchored by ALL of: provenance sidecar
    (source hash == current source), file hash == sidecar hash, AND an
    append-only render event in the workspace ledger (reviewer B R4 N-B2:
    sidecar alone proves File==Record, not File==Render(Source) — a
    content-swapped DOCX with an updated sidecar must NOT be reused), the
    artifact is unchanged: reuse it. Anything else renders fresh."""
    ws = workspace
    found = _find_source(ws)
    if not found:
        return None
    source, _kind = found
    src_sha = sha256_file(source)
    outbox = ws.paperpal_outbox
    versions = sorted(p for p in outbox.glob("paper-*.docx")
                      if p.is_file() and DOCX_NAME_RE.match(p.name)
                      and not _future_dated(p.name))
    if versions:
        newest = versions[-1]
        try:
            prov = json.loads(
                (outbox / f"{newest.name}.provenance.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            prov = None
        if prov and not newest.is_symlink():
            docx_sha = (prov.get("docx") or {}).get("sha256")
            if ((prov.get("source") or {}).get("sha256") == src_sha
                    and docx_sha == sha256_file(newest)
                    and _render_event_anchored(ws, newest.name, docx_sha, src_sha)):
                prov = dict(prov)
                prov["reused"] = True
                prov["reused_at"] = utcnow()
                return prov
    return build_docx_outbox(workspace, run_id)


def _render_event_anchored(ws: Any, name: str, docx_sha: str, src_sha: str) -> bool:
    """The workspace ledger holds an append-only event for every real render
    (written by build_docx_outbox). Reuse requires the exact triple
    (name, docx_sha256, source_sha256) to exist there."""
    for ev in ws.events_of_kind("paperpal_docx_rendered"):
        p = ev.get("payload") or {}
        if (p.get("name") == name and p.get("docx_sha256") == docx_sha
                and p.get("source_sha256") == src_sha):
            return True
    return False


def build_docx_outbox(workspace: Any, run_id: str) -> dict[str, Any] | None:
    """Render the versioned Paperpal DOCX. Returns the provenance dict
    (also written as sidecar), or None when no manuscript source exists."""
    ws = workspace
    found = _find_source(ws)
    if not found:
        return None
    source, kind = found

    staging = ws.paperpal_outbox / "_staging"
    if staging.exists():
        # versioned displacement, never delete (house rule)
        displaced = staging.with_name(f"_staging.v1.{utcnow().replace(':', '').replace('-', '')}")
        n = 2
        while displaced.exists():
            displaced = staging.with_name(f"{displaced.name}.{n}")
            n += 1
        staging.rename(displaced)
    staging.mkdir(parents=True)

    text = source.read_text(encoding="utf-8", errors="replace")
    mapping: list[dict] = []
    if kind == "markdown":
        text, mapping = _rewrite_image_paths(text, source.parent)
        staged = staging / source.name
        staged.write_text(text, encoding="utf-8")
        for p in sorted(source.parent.iterdir()):
            if p.suffix.lower() in _IMG_EXTS:
                shutil.copy2(p, staging / p.name)
        in_path = staged
    else:
        in_path = source

    ref = ensure_reference_docx(ws.paperpal_outbox / "_cache")
    ts = utcnow().replace(":", "").replace("-", "").replace(".", "")
    docx = ws.paperpal_outbox / f"paper-{ts}.docx"
    cmd = ["pandoc", str(in_path), "-o", str(docx),
           "--resource-path", str(staging),
           "--reference-doc", str(ref)]
    if kind == "latex":
        cmd.append("--from=latex")
    subprocess.run(cmd, check=True, capture_output=True)

    prov: dict[str, Any] = {
        "purpose": "paperpal_word_outbox",
        "source": {"path": str(source), "sha256": sha256_file(source),
                   "kind": kind},
        "docx": {"path": str(docx), "name": docx.name,
                 "sha256": sha256_file(docx), "bytes": docx.stat().st_size},
        "conversion": {"method": f"pandoc {kind}->docx + arxiv_style_reference",
                       "reference_docx": ref.name},
        "figures": mapping,
        "generated_at": utcnow(),
        "run_id": run_id,
    }
    write_json(ws.paperpal_outbox / f"{docx.name}.provenance.json", prov)
    # anchor the render in the append-only workspace ledger (N-B2): reuse and
    # closure revalidation can then distinguish a real render from a swapped
    # file with a hand-updated sidecar
    ws.event(run_id, "paperpal_docx_rendered", node_id="P31",
             payload={"name": docx.name, "docx_sha256": prov["docx"]["sha256"],
                      "source_sha256": prov["source"]["sha256"]})
    return prov
