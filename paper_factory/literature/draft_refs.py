"""Draft reference lists → bibliography (GAP: real pilot 3).

DRAFT_ASSISTED/MIXED_EVIDENCE projects often carry their bibliography as a
markdown '## References' section, never as .bib. Without this bridge the
citation audit (P21) and bibliography build (P15) degrade and venue
compliance fails on bib_exists — although the references exist.

Every parsed entry carries an explicit T4 provenance note ('parsed from draft
reference list — verify before citation'): the draft is NOT authority. The
downstream citation audit (Crossref/OpenAlex) is what verifies them; false
entries are excluded by build_references as usual.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

# public: the claims builder cuts drafts at this heading before extraction
# (reviewer A R2 N-B) — reference lists are bibliographic debris, not claims
REFS_HEADING_RE = re.compile(r"^#{1,6}\s*(?:references|bibliography|literatur"
                             r"(?:verzeichnis)?)\s*$", re.I | re.M)
_REFS_HEADING = REFS_HEADING_RE  # internal alias
_ENTRY_MARK = re.compile(r"\\?\[(\d+)\\?\]")
_URL = re.compile(r"https?://[^\s)\]]+")
_YEAR = re.compile(r"\b(19|20)\d{2}\b")
# old-style arXiv ids carry a slash (cs/0601001, hep-th/9901001, math.GT/…);
# the char class must span it (reviewer A R2 N-A)
_ARXIV = re.compile(r"arxiv\.org/(?:abs|pdf)/((?:[a-z][a-z\-]*(?:\.[A-Z]{2})?/)?[\d.]+)",
                    re.I)
_DOI_URL = re.compile(r"doi\.org/([^\s)\]]+)", re.I)
_DOI_BARE = re.compile(r"\bdoi:\s*(10\.\d{4,9}/[^\s)\]]+)", re.I)

T4_NOTE_MARK = "parsed from draft reference list"
_PROVENANCE = (T4_NOTE_MARK + " (T4) — verify before citation")

# the derived file's own name — never counts as a "real" bibliography
DERIVED_NAME = "parsed_from_draft.bib"


def _esc(s: str) -> str:
    return s.replace("{", "").replace("}", "").strip()


def _split_authors_title(head: str) -> tuple[str, str]:
    """Author/title boundary: full-name style splits at the first '. ';
    initial style ('Doe, K. and Roe, L. Title.') must split after the LAST
    initial, or the title inherits half the author list (reviewer A-F2).
    A single LEADING initial ('A. First study…') is a first-name initial,
    not the boundary — then the first '. ' split applies."""
    initials = [m for m in re.finditer(r"\b[A-Z]\.\s+", head)]
    initials = [m for m in initials if m.start() != 0]
    if len(initials) >= 2 or (len(initials) == 1 and " and " in head[:initials[0].start()]):
        cut = initials[-1].end()
        return head[:cut].rstrip(". ").strip(), head[cut:].strip()
    if ". " in head:
        return tuple(head.split(". ", 1))  # type: ignore[return-value]
    return "", head


def parse_markdown_refs(text: str) -> str:
    """Parse a markdown reference section into bib entries (string).
    Entries are marked by [N] / \\[N\\] labels. Returns '' when no reference
    section or no entries are found."""
    m = _REFS_HEADING.search(text)
    if not m:
        return ""
    body = text[m.end():]
    # split into entries at [N] markers
    parts = _ENTRY_MARK.split(body)
    entries: list[str] = []
    seen_keys: set[str] = set()
    # parts alternates: [pre, num, text, num, text, …]
    for i in range(1, len(parts) - 1, 2):
        num, raw = parts[i], parts[i + 1]
        raw = " ".join(raw.split())
        if len(raw) < 15:
            continue
        key = f"draftref{num}"
        if key in seen_keys:
            # misnumbered/duplicated draft markers are everyday — suffix, never
            # emit duplicate bib keys (reviewer A-F4)
            suffix = ord("b")
            while f"{key}{chr(suffix)}" in seen_keys:
                suffix += 1
            key = f"{key}{chr(suffix)}"
        seen_keys.add(key)
        url_m = _URL.search(raw)
        url = url_m.group(0) if url_m else None
        year_m = None
        for ym in _YEAR.finditer(raw):
            year_m = ym  # last year wins (access dates come last)
        year = year_m.group(0) if year_m else None
        # authors/title: text before the first sentence boundary that
        # introduces venue/year markup — kept conservative: everything up to
        # the URL or the trailing year block
        head = raw[:url_m.start()].strip() if url_m else raw
        head = re.sub(r"\s*,?\s*" + _YEAR.pattern + r"\.?\s*$", "", head)
        authors, title = _split_authors_title(head)
        fields = [f"  title = {{{_esc(title)}}}"]
        if authors:
            fields.append(f"  author = {{{_esc(authors)}}}")
        if year:
            fields.append(f"  year = {{{year}}}")
        ax = _ARXIV.search(url or "")
        doi_m = _DOI_URL.search(url or "") or _DOI_BARE.search(raw)
        doi = doi_m.group(1).rstrip(".") if doi_m else None
        if ax:
            # trailing sentence punctuation must not leak into the eprint —
            # it feeds the synthesized DataCite DOI downstream
            fields.append(f"  eprint = {{{ax.group(1).rstrip('.')}}}")
            fields.append("  archivePrefix = {arXiv}")
        if doi:
            fields.append(f"  doi = {{{doi}}}")
        if url:
            fields.append(f"  url = {{{url.rstrip('.')}}}")
        fields.append(f"  note = {{{_PROVENANCE}}}")
        entries.append("@misc{%s,\n%s\n}" % (key, ",\n".join(fields)))
    return "\n\n".join(entries) + ("\n" if entries else "")


def _versioned_rename(path: Path) -> Path:
    """Versioned displacement (never delete). Same-second collisions get a
    counter suffix — POSIX rename would otherwise silently overwrite an
    earlier version in the chain (reviewer A R2 N-D)."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = path.with_name(f"{path.name}.v1.{ts}")
    n = 2
    while dest.exists():
        dest = path.with_name(f"{path.name}.v1.{ts}.{n}")
        n += 1
    path.rename(dest)
    return dest


def ensure_draft_bib(root: Path) -> Path | None:
    """Draft-derived bibliography as FALLBACK only. Real .bib files always
    win — and when a real one exists, the stale derived file is displaced
    (versioned rename, never deleted, never silently mixed into the chain —
    reviewer B P3-1). With no real bib, the derived file self-refreshes on
    content change (old content versioned, reviewer A-F6). Returns the path
    or None."""
    real = [b for b in sorted(root.glob("literature/*.bib")) + sorted(root.glob("*.bib"))
            if b.name != DERIVED_NAME]
    derived = root / "literature" / DERIVED_NAME
    if real:
        if derived.exists():
            _versioned_rename(derived)
        return None
    for draft in sorted(root.glob("draft/*.md")) + sorted(root.glob("draft/*.tex")):
        bib = parse_markdown_refs(draft.read_text(encoding="utf-8", errors="replace"))
        if bib:
            if derived.exists() and derived.read_text(encoding="utf-8") != bib:
                _versioned_rename(derived)
            if not derived.exists():
                derived.parent.mkdir(parents=True, exist_ok=True)
                derived.write_text(bib, encoding="utf-8")
            return derived
    return None
