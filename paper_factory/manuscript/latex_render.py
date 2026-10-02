"""Full-manuscript arXiv-style LaTeX rendering (final publication artifact).

The thin `paper/` scaffold is the PF-internal evidence manuscript; the
canonical full paper text lives in `draft/*.md` for DRAFT_ASSISTED projects
(same source the Paperpal DOCX renders from). This module renders that source
into a classic single-column arXiv cs.AI look (Times via mathptmx, microtype,
natbib numbered, booktabs/longtable) — a REPRESENTATION TRANSFORM, not new
scientific content: the markdown source is hashed into the provenance record
and the LaTeX derives from it deterministically (pandoc).

    source md  →  citation remap ([4,5] → \\cite{draftref4,draftref5})
               →  image path rewrite (shared with the DOCX outbox)
               →  head parse (title/authors/abstract/keywords)
               →  pandoc body  →  template assembly  →  paper_final/

Nothing here edits the source. All outputs are sha256-recorded.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from ..core.util import sha256_file, utcnow, write_json

_TEMPLATE = r"""% paper-factory full-manuscript render (arXiv cs.AI preprint style)
\documentclass[11pt,a4paper]{article}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{mathptmx}
\usepackage{microtype}
\usepackage[a4paper,margin=1in,headheight=14pt]{geometry}
\usepackage{amsmath,amssymb}
\usepackage{graphicx}
\usepackage{booktabs}
\usepackage{longtable}
\usepackage{array}
\usepackage{xcolor}
\usepackage[font=small,labelfont=bf]{caption}
\usepackage{enumitem}
\usepackage{calc}
\usepackage{fancyvrb}
\usepackage{ulem}
\usepackage{etoolbox}
\usepackage[numbers,sort&compress]{natbib}
\usepackage[hidelinks]{hyperref}
\usepackage{cleveref}
\setlength{\parskip}{0.35em}
\setlength{\parindent}{0pt}
\captionsetup{skip=6pt}
<<EXTRA_PREAMBLE>>
\title{<<TITLE>>}
\author{<<AUTHORS>>}
\date{<<DATE>>}
\begin{document}
\maketitle
\begin{abstract}
<<ABSTRACT>>
\end{abstract}
<<KEYWORDS>>
<<BODY>>
\bibliographystyle{unsrtnat}
\bibliography{references}
\end{document}
"""

_CITE_MD = re.compile(r"\\\[(\d+(?:\s*,\s*\d+)*)\\\]")

#: pdflatex/T1 cannot typeset these directly; map to math/text commands.
_UNICODE_MAP = {
    "Α": "$A$", "Β": "$B$", "Γ": "$\\Gamma$", "Δ": "$\\Delta$",
    "Ε": "$E$", "Ζ": "$Z$", "Η": "$H$", "Θ": "$\\Theta$",
    "Ι": "$I$", "Κ": "$K$", "Λ": "$\\Lambda$", "Μ": "$M$",
    "Ν": "$N$", "Ξ": "$\\Xi$", "Ο": "$O$", "Π": "$\\Pi$",
    "Ρ": "$P$", "Σ": "$\\Sigma$", "Τ": "$T$", "Υ": "$\\Upsilon$",
    "Φ": "$\\Phi$", "Χ": "$X$", "Ψ": "$\\Psi$", "Ω": "$\\Omega$",
    "α": "$\\alpha$", "β": "$\\beta$", "γ": "$\\gamma$", "δ": "$\\delta$",
    "ε": "$\\varepsilon$", "ζ": "$\\zeta$", "η": "$\\eta$", "θ": "$\\theta$",
    "ι": "$\\iota$", "κ": "$\\kappa$", "λ": "$\\lambda$", "μ": "$\\mu$",
    "ν": "$\\nu$", "ξ": "$\\xi$", "π": "$\\pi$", "ρ": "$\\rho$",
    "σ": "$\\sigma$", "τ": "$\\tau$", "υ": "$\\upsilon$", "φ": "$\\phi$",
    "χ": "$\\chi$", "ψ": "$\\psi$", "ω": "$\\omega$",
    "±": "$\\pm$", "∓": "$\\mp$", "×": "$\\times$", "÷": "$\\div$",
    "≤": "$\\leq$", "≥": "$\\geq$", "≠": "$\\neq$", "≈": "$\\approx$",
    "≡": "$\\equiv$", "∈": "$\\in$", "∉": "$\\notin$", "⊂": "$\\subset$",
    "⊆": "$\\subseteq$", "∪": "$\\cup$", "∩": "$\\cap$", "∅": "$\\emptyset$",
    "∞": "$\\infty$", "∂": "$\\partial$", "∇": "$\\nabla$", "√": "$\\sqrt{}$",
    "→": "$\\to$", "←": "$\\leftarrow$", "↔": "$\\leftrightarrow$",
    "⇒": "$\\Rightarrow$", "↦": "$\\mapsto$", "↑": "$\\uparrow$",
    "↓": "$\\downarrow$", "∝": "$\\propto$", "∼": "$\\sim$",
    "−": "--",  # unicode minus in text -> en dash
    "…": r"\ldots{}", " ": "~", "‐": "-", "‑": "-",
    "–": "--", "—": "---",
    "“": "``", "”": "''", "‘": "`", "’": "'",
    "•": r"\textbullet{}", "·": r"\textperiodcentered{}",
    "✓": r"\checkmark{}", "✗": r"$\times$", "⚠": r"\textbf{!}",
    "①": "(1)", "②": "(2)", "③": "(3)", "④": "(4)", "⑤": "(5)",
    "⑥": "(6)", "⑦": "(7)", "⑧": "(8)", "⑨": "(9)",
}


def _map_unicode(tex: str) -> str:
    for uc, rep in _UNICODE_MAP.items():
        tex = tex.replace(uc, rep)
    return tex
_HEAD_NUM = re.compile(r"^(#{1,4})\s+\d+(?:\.\d+)*\.?\s+", re.M)
_ABSTRACT_RE = re.compile(r"^\*\*Abstract\.\*\*\s*(.+?)(?=^\*\*|\Z)", re.S | re.M)
_KEYWORDS_RE = re.compile(r"^\*\*Keywords?:\*\*\s*(.+)$", re.M)
_BOLD_LINE = re.compile(r"^\*\*(.+?)\*\*\s*$", re.M)
_BOLD_BLOCK = re.compile(r"^\*\*(.+?)\*\*\s*$", re.S | re.M)


def _remap_citations(text: str, valid_keys: set[str] | None = None
                     ) -> tuple[str, int, list[str]]:
    """`\\[4,5,18\\]` (escaped numeric cites in the draft) → raw-LaTeX
    \\cite{draftref4,draftref5,draftref18}. When valid_keys is given (the
    shipped bibliography's keys), out-of-range numbers stay literal and are
    reported — a miscounted draft reference must not become an undefined
    \\cite (release audit A MIN-8). Returns (text, mapped, unmapped)."""
    mapped = 0
    unmapped: list[str] = []

    def sub(m: re.Match) -> str:
        nonlocal mapped
        keys = [f"draftref{int(x)}" for x in m.group(1).split(",")]
        if valid_keys is not None and any(k not in valid_keys for k in keys):
            unmapped.append(m.group(1))
            return m.group(0)  # leave the literal marker, honestly visible
        mapped += 1
        return f"`\\cite{{{','.join(keys)}}}`{{=latex}}"

    return _CITE_MD.sub(sub, text), mapped, unmapped


def _strip_numbering(text: str) -> str:
    """'# 1. Introduction' → '# Introduction' (article numbers sections
    itself; explicit draft numbers would double). Fenced code blocks are
    passed through untouched (a '# 1.' comment in code is not a heading)."""
    out: list[str] = []
    in_fence = False
    for ln in text.split("\n"):
        if ln.strip().startswith("```"):
            in_fence = not in_fence
            out.append(ln)
            continue
        out.append(ln if in_fence else _HEAD_NUM.sub(r"\1 ", ln))
    return "\n".join(out)


def _split_head(text: str) -> tuple[dict[str, str], str, dict[str, Any]]:
    """Split the draft head (title/author/meta/abstract/keywords block) from
    the body. Preservation contract (release audit A CRIT-1/2): every
    non-empty head line is either claimed by a metadata field or kept in the
    body — NOTHING is dropped. Returns (meta, body, accounting)."""
    meta: dict[str, str] = {}
    lines = text.split("\n")
    first_head = next((i for i, ln in enumerate(lines) if ln.startswith("# ")),
                      len(lines))
    head_lines, body_lines = lines[:first_head], lines[first_head:]
    consumed: set[int] = set()

    def _claim_block(pred, strip_re: str, key: str) -> None:
        for i, ln in enumerate(head_lines):
            if i in consumed or not pred(ln):
                continue
            buf: list[str] = []
            j = i
            # multi-line block: until blank line OR the next bold label
            # (reviewer A R2-A4: '**Keywords:**' directly after the abstract
            # must not be absorbed INTO the abstract)
            while j < len(head_lines) and head_lines[j].strip():
                if j > i and head_lines[j].strip().startswith("**"):
                    break
                buf.append(head_lines[j].strip().rstrip("\\").strip())
                consumed.add(j)
                j += 1
            joined = " ".join(buf)
            m = re.match(strip_re, joined)
            meta[key] = (m.group(1) if m else joined).strip()
            return

    _claim_block(lambda ln: ln.strip().startswith("**Abstract"),
                 r"\*\*Abstract\.?\*\*\s*(.*)", "abstract")
    _claim_block(lambda ln: bool(re.match(r"\s*\*\*Keywords?:", ln)),
                 r"\s*\*\*Keywords?:\*\*\s*(.*)", "keywords")

    # title: first bold block over unconsumed lines (may span two lines);
    # label blocks like '**Note:** …' are never a title
    i = 0
    while i < len(head_lines):
        if i in consumed or not head_lines[i].strip().startswith("**"):
            i += 1
            continue
        j = i
        buf: list[str] = []
        while j < len(head_lines) and head_lines[j].strip():
            buf.append(head_lines[j].strip().rstrip("\\").strip())
            j += 1
        block = " ".join(buf)
        m = _BOLD_BLOCK.match(block)
        if m and not m.group(1).strip().rstrip(".:").lower() in ("note",):
            label = m.group(1).strip()
            if not label.endswith(".") or len(label.split()) > 3:
                meta["title"] = " ".join(m.group(1).split())
                consumed.update(range(i, j))
                break
        i += 1

    for i, ln in enumerate(head_lines):
        if i in consumed:
            continue
        s = ln.strip().rstrip("\\").strip()
        if not s:
            continue
        if "affiliation" not in meta and "|" in s:
            meta["affiliation"] = s.replace("\\|", "|")
            consumed.add(i)
        elif ("author" not in meta and "**" not in s
              and not re.search(r"(?i)institut|universit|department|laborator"
                                r"|center|centre|gmbh|inc\b|corp", s)
              and re.match(r"^[A-ZÄÖÜ][\w.'’-]+( [\w.'’-]+)+$", s)):
            meta["author"] = s
            consumed.add(i)
        elif re.search(r"\b(19|20)\d\d\b", s) or re.search(r"\bv\d+\.\d+", s):
            # version/date identity lines (release audit A CRIT-2): ALL of
            # them ship in \date, joined — the version must survive.
            # A wrapped tail line ('…cutoff\nunchanged') belongs to the date
            # block, not to the body: consume short label-less continuations
            meta.setdefault("_dates", [])
            meta["_dates"].append(s.replace("\\|", "|"))
            consumed.add(i)
            k = i + 1
            # a wrapped tail ('…cutoff  \nunchanged') belongs to the date
            # block only when the previous line FORCES a markdown hard break
            # (two trailing spaces) — otherwise short content lines must stay
            # in the body (reviewer A R2-A3)
            while (k < len(head_lines) and head_lines[k].strip()
                   and k not in consumed and "**" not in head_lines[k]
                   and len(head_lines[k].strip()) < 60
                   and not re.search(r"\b(19|20)\d\d\b", head_lines[k])
                   and head_lines[k - 1].endswith("  ")):
                meta["_dates"].append(head_lines[k].strip().rstrip("\\")
                                      .strip().replace("\\|", "|"))
                consumed.add(k)
                k += 1
    if meta.get("_dates"):
        meta["date_line"] = " \\\\ ".join(meta.pop("_dates"))

    rest = [head_lines[i] for i in range(len(head_lines))
            if i not in consumed and head_lines[i].strip()]
    body = "\n".join(rest + [""] + body_lines).strip() + "\n"
    accounting = {
        "head_lines_nonempty": sum(1 for ln in head_lines if ln.strip()),
        "consumed": len(consumed),
        "kept_in_body": len(rest),
        "fields": sorted(k for k in meta if not k.startswith("_")),
    }
    return meta, body, accounting


def _strip_note_fields(bib: str) -> str:
    """Brace-balanced removal of note={...} fields (nested braces safe —
    reviewer A R2-A6). The pipeline bib keeps the note (T4 span binding);
    only the shipped arXiv copy is stripped."""
    pat = re.compile(r"(?i)\n[ \t]*note[ \t]*=")
    out: list[str] = []
    i = 0
    while True:
        m = pat.search(bib, i)
        if not m:
            out.append(bib[i:])
            break
        out.append(bib[i:m.start()])
        j = m.end()
        while j < len(bib) and bib[j] in " \t":
            j += 1
        if j < len(bib) and bib[j] == "{":
            depth = 0
            while j < len(bib):
                if bib[j] == "{":
                    depth += 1
                elif bib[j] == "}":
                    depth -= 1
                    if depth == 0:
                        j += 1
                        break
                j += 1
            if j < len(bib) and bib[j] == ",":
                j += 1
            i = j
        else:
            k = bib.find(",", j)
            i = k + 1 if k != -1 else len(bib)
    return "".join(out)


def _tex_escape_text(s: str) -> str:
    for a, b in (("\\", r"\textbackslash{}"), ("&", r"\&"), ("%", r"\%"),
                 ("$", r"\$"), ("#", r"\#"), ("_", r"\_"), ("{", r"\{"),
                 ("}", r"\}"), ("~", r"\textasciitilde{}"), ("^", r"\textasciicircum{}")):
        s = s.replace(a, b)
    return s


def render_full_manuscript(workspace: Any, out_dir: Path, run_id: str) -> dict[str, Any]:
    """Render the canonical manuscript into an arXiv-style LaTeX tree at
    out_dir (main.tex, sections body, figures/, references.bib). Returns the
    provenance record (also written as render_provenance.json)."""
    from ..paperpal.docx_outbox import _find_source, _rewrite_image_paths

    ws = workspace
    found = _find_source(ws)
    if not found:
        raise FileNotFoundError("no manuscript source (draft/*.md or paper/main.tex)")
    source, kind = found
    if kind != "markdown":
        raise ValueError(f"full-manuscript render expects markdown, got {kind}")

    text = source.read_text(encoding="utf-8", errors="replace")
    # combining-mark normalization: pdflatex/T1 cannot typeset U+0301-style
    # sequences (registry metadata, chat exports) — NFC-compose once, early
    import unicodedata
    text = unicodedata.normalize("NFC", text)
    text, image_map = _rewrite_image_paths(text, source.parent)
    # citation bound check against the shipped bibliography (A MIN-8)
    bib = ws.paper_dir / "references.bib"
    valid_keys: set[str] | None = None
    if bib.exists():
        valid_keys = set(re.findall(r"@\w+\{([^,\s]+)", bib.read_text(
            encoding="utf-8", errors="replace")))
    text, n_cites, cites_unmapped = _remap_citations(text, valid_keys)
    text = _strip_numbering(text)
    meta, body_md, head_accounting = _split_head(text)
    # the draft's own manual reference list is replaced by the bibliography
    body_md = re.split(r"^#\s+References\s*$", body_md, flags=re.M)[0]

    proc = subprocess.run(
        ["pandoc", "--from=markdown", "--to=latex", "--wrap=none"],
        input=body_md, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(f"pandoc failed: {proc.stderr[:500]}")
    body_tex = _map_unicode(proc.stdout)
    # QA (Phase 8): pandoc turns the img alt text into \caption{} — the alt
    # text carries its own "Figure N:" label, which LaTeX then prefixes again
    # ("Figure 1: Figure 1: …"). Strip the label inside the caption; the
    # draft's own extended caption paragraph stays untouched.
    body_tex = re.sub(r"\\caption\{(?:Figure|Fig\.?|Table)\s*\d+\s*[:.]\s*",
                      r"\\caption{", body_tex)
    # images are referenced by basename after _rewrite_image_paths; make the
    # LaTeX graphicspath point at figures/ BEFORE the TikZ upgrade rewrite
    body_tex = re.sub(r"(\\includegraphics(?:\[[^]]*\])?\{)([^}/]+)(\})",
                      r"\1figures/\2\3", body_tex)
    # pandoc sizes images from their DPI metadata (e.g. width=6.55in,
    # height=\textheight) which overflows a 1in-margin A4 text block — clamp
    # to the line width, keep aspect ratio (drop the height)
    body_tex = re.sub(
        r"\\includegraphics\[(?:width=([0-9.]+)in)?[^]]*\]",
        lambda m: (r"\includegraphics[width=\linewidth]"
                   if not m.group(1) or float(m.group(1)) > 6.2
                   else m.group(0)),
        body_tex)

    out_dir.mkdir(parents=True, exist_ok=True)
    fig_dir = out_dir / "figures"
    fig_dir.mkdir(exist_ok=True)
    import shutil

    figs: list[str] = []
    for entry in image_map:
        src = source.parent / entry.get("to", "")
        if entry.get("ok") and src.is_file():
            shutil.copy2(src, fig_dir / src.name)
            figs.append(src.name)
    # vector upgrade: figure stems with a known TikZ spec are re-rendered as
    # vector PDFs (content transcribed verbatim from the raster reference);
    # any failure keeps the PNG — never a silent swap
    tikz_used: list[str] = []
    tikz_errors: dict[str, str] = {}
    known = {Path(f).stem for f in figs}
    if known:
        import tempfile

        from ..figures.tikz_diagrams import KNOWN_SPECS, render_diagram
        with tempfile.TemporaryDirectory(prefix="pf-tikz-") as tdir:
            for stem in sorted(known):
                if stem not in KNOWN_SPECS:
                    continue
                try:
                    res = render_diagram(KNOWN_SPECS[stem](), tdir, stem)
                    shutil.copy2(res["pdf"], fig_dir / f"{stem}.pdf")
                    body_tex = body_tex.replace(f"figures/{stem}.png",
                                                f"figures/{stem}.pdf")
                    tikz_used.append(stem)
                except Exception as exc:
                    tikz_errors[stem] = str(exc)[:200]

    if bib.exists():
        # shipped copy: internal provenance notes never print in the rendered
        # bibliography (the pipeline bib keeps them for T4 span binding)
        bib_text = _strip_note_fields(bib.read_text(encoding="utf-8",
                                                    errors="replace"))
        (out_dir / "references.bib").write_text(
            unicodedata.normalize("NFC", bib_text), encoding="utf-8")

    title = meta.get("title") or "Paper Factory manuscript"
    author = meta.get("author", "")
    aff = meta.get("affiliation", "")
    authors = _tex_escape_text(author)
    if aff:
        parts = [_tex_escape_text(x.strip()) for x in aff.split("|")]
        authors += "\\\\[2pt] \\small " + " \\\\ ".join(parts)
    abstract = meta.get("abstract", "")
    keywords = meta.get("keywords", "")
    date_line = meta.get("date_line", "")
    date_tex = " \\\\ ".join(_tex_escape_text(p.strip())
                            for p in date_line.split(" \\\\ ")) if date_line else ""
    tex = (_TEMPLATE
           .replace("<<EXTRA_PREAMBLE>>", "")
           .replace("<<TITLE>>", _tex_escape_text(title))
           .replace("<<AUTHORS>>", authors)
           .replace("<<DATE>>", date_tex)
           .replace("<<ABSTRACT>>", _md_inline(abstract))
           .replace("<<KEYWORDS>>",
                    ("\\begin{center}\\small\\textbf{Keywords:} "
                     + _md_inline(keywords) + "\\end{center}") if keywords else "")
           .replace("<<BODY>>", body_tex))
    (out_dir / "main.tex").write_text(tex, encoding="utf-8")

    prov = {
        "purpose": "arxiv_full_manuscript_render",
        "source": {"path": str(source), "sha256": sha256_file(source), "kind": kind},
        "outputs": {p.relative_to(out_dir).as_posix(): sha256_file(p)
                    for p in sorted(out_dir.rglob("*")) if p.is_file()},
        "figures": figs,
        "head_accounting": head_accounting,
        "citations_unmapped": cites_unmapped,
        "figures_tikz_vector": tikz_used,
        "figures_tikz_errors": tikz_errors,
        "citations_remapped": n_cites,
        "meta_parsed": sorted(meta),
        "generated_at": utcnow(),
        "run_id": run_id,
    }
    write_json(out_dir / "render_provenance.json", prov)
    return prov


def _md_inline(text: str) -> str:
    """Tiny inline-markdown → LaTeX for abstract/keywords (**bold**, *it*,
    `code`, bare URLs). Block structure is not handled here."""
    s = _tex_escape_text(text)
    s = re.sub(r"\*\*(.+?)\*\*", r"\\textbf{\1}", s)
    s = re.sub(r"(?<!\w)\*([^*\n]+)\*(?!\w)", r"\\textit{\1}", s)
    s = re.sub(r"`([^`]+)`", r"\\texttt{\1}", s)
    s = re.sub(r"(https?://[^\s\\{}]+)", r"\\url{\1}", s)
    s = s.replace("\n\n", "\n\n\\par\n\n")
    return _map_unicode(s)
