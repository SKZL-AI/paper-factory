"""Literature verification: every final citation gets a verification record.
Never invent citations. Offline → DEGRADED, never silently skipped.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from ..core.results import Verdict
from ..core.util import sha256_json, utcnow, write_json
from ..dag.executor import NodeContext, NodeOutcome

CROSSREF = "https://api.crossref.org/works/"
OPENALEX = "https://api.openalex.org/works/doi:"
_UA = {"User-Agent": "paper-factory/0.1 (mailto:paper-factory@local)"}


def resolve_doi(doi: str, timeout: int = 20) -> dict[str, Any]:
    """Verify a DOI against Crossref, then OpenAlex as a second source."""
    rec: dict[str, Any] = {"doi": doi, "checked_at": utcnow(), "sources": {}}
    for name, base in (("crossref", CROSSREF), ("openalex", OPENALEX)):
        url = base + urllib.parse.quote(doi)
        try:
            req = urllib.request.Request(url, headers=_UA)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = json.loads(resp.read().decode())
            rec["sources"][name] = {"status": "found", "http": 200}
            if name == "crossref":
                msg = body.get("message", {})
                rec["title"] = (msg.get("title") or [None])[0]
                rec["container"] = (msg.get("container-title") or [None])[0]
                rec["published"] = msg.get("published-print") or msg.get("published-online")
        except urllib.error.HTTPError as exc:
            rec["sources"][name] = {"status": "not_found" if exc.code == 404 else f"http_{exc.code}"}
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            rec["sources"][name] = {"status": "error", "error": str(exc)[:200]}
    found = any(s.get("status") == "found" for s in rec["sources"].values())
    errors = all(s.get("status") == "error" for s in rec["sources"].values())
    rec["verdict"] = "VERIFIED" if found else ("UNKNOWN_NETWORK" if errors else "NOT_FOUND")
    return rec


_DOI = re.compile(r"doi\s*=\s*[{\"]?([^}\s,\"]+)", re.IGNORECASE)
_TITLE = re.compile(r"title\s*=\s*[\{\"](.+?)[}\"]\s*,", re.DOTALL | re.IGNORECASE)
_EPRINT = re.compile(r"eprint\s*=\s*[{\"]?([^}\s,\"]+)", re.IGNORECASE)
# arXiv version suffixes come in any case (v2, V2) — the DataCite namespace is
# versionless, an unstripped suffix 404s a REAL paper (reviewer A R3-1/R4-1)
_EPRINT_VERSION = re.compile(r"v\d+$", re.IGNORECASE)
_NOTE = re.compile(r"note\s*=\s*[\{\"](.+?)[}\"]\s*(?:[,}]|$)",
                   re.DOTALL | re.IGNORECASE)
_ENTRY_START = re.compile(r"@\w+\s*\{\s*([^,\s]+)\s*,")


def _entry_splits(text: str) -> list[tuple[str, str, str]]:
    """(key, body, raw) per entry, span-delimited by the NEXT entry start —
    never by a closing brace. A naive `[^@]*` body silently truncates entries
    whose fields hold an `@` (email, URL userinfo), and a copy built from such
    a truncation loses the T4 provenance note (reviewer B R4-F1); an entry
    with `@` before its first brace was dropped from the manuscript bib
    entirely (silent, neither kept nor dropped_false)."""
    starts = list(_ENTRY_START.finditer(text))
    out = []
    for i, m in enumerate(starts):
        end = starts[i + 1].start() if i + 1 < len(starts) else len(text)
        raw = text[m.start():end].strip()
        out.append((m.group(1).strip(), text[m.end():end], raw))
    return out


def parse_bib(path: Path) -> list[dict[str, Any]]:
    from .draft_refs import T4_NOTE_MARK
    text = path.read_text(encoding="utf-8", errors="replace")
    entries = []
    for key, body, _raw in _entry_splits(text):
        doi = _DOI.search(body)
        title = _TITLE.search(body)
        eprint = _EPRINT.search(body)
        note = _NOTE.search(body)
        entries.append({"key": key, "doi": doi.group(1) if doi else None,
                        "title": re.sub(r"\s+", " ", title.group(1)).strip() if title else None,
                        "eprint": eprint.group(1) if eprint else None,
                        "note": note.group(1).strip() if note else None,
                        # content-bound: survives build_references copies and
                        # nasty note payloads (reviewer B R2-F2 / A R3-4)
                        "t4_derived": T4_NOTE_MARK in body})
    return entries


def _audit_entries(ctx: NodeContext, entries: list[dict[str, Any]]) -> tuple[list, list, Verdict]:
    records, findings = [], []
    if ctx.offline:
        for e in entries:
            records.append({"key": e["key"], "doi": e.get("doi"), "verdict": "NOT_RUN",
                            "reason": "offline mode",
                            "t4_derived": e.get("t4_derived", False)})
        return records, findings, Verdict.DEGRADED
    for e in entries:
        doi = e.get("doi")
        doi_source = "bib"
        if not doi and e.get("eprint"):
            # arXiv preprints carry an official DataCite DOI — verify THAT
            # instead of shrugging "no doi" (reviewer B R2-F1: unverifiable
            # must never masquerade as resolved; a fake arXiv id resolves to
            # NOT_FOUND and becomes a false_citation, exactly as it should).
            # The DOI namespace is VERSIONLESS — a `v2` suffix would 404 a
            # real paper (reviewer A R3-1)
            eprint = _EPRINT_VERSION.sub("", e["eprint"])
            doi = f"10.48550/arXiv.{eprint}"
            doi_source = "arxiv_synthesized"
        if not doi:
            t4 = e.get("t4_derived", False)
            records.append({"key": e["key"],
                            "verdict": "UNVERIFIABLE_T4" if t4 else "NO_DOI",
                            "title": e.get("title"),
                            "t4_derived": t4})
            if t4:
                # a T4 draft-derived reference that nothing can verify is a
                # MAJOR — closure U4 must not attest resolution for it
                findings.append({"severity": "MAJOR", "kind": "unverifiable_citation",
                                 "key": e["key"]})
            else:
                findings.append({"severity": "MINOR", "kind": "no_doi", "key": e["key"]})
            continue
        rec = resolve_doi(doi)
        rec["key"] = e["key"]
        rec["claimed_title"] = e.get("title")
        rec["t4_derived"] = e.get("t4_derived", False)
        rec["doi_source"] = doi_source
        records.append(rec)
        if rec["verdict"] == "NOT_FOUND":
            findings.append({"severity": "CRITICAL", "kind": "false_citation",
                             "key": e["key"], "doi": doi})
        elif rec["verdict"] == "UNKNOWN_NETWORK":
            findings.append({"severity": "MAJOR", "kind": "unverifiable_network",
                             "key": e["key"], "doi": doi})
    verdict = (Verdict.DEGRADED
               if any(f["kind"] in ("unverifiable_network", "unverifiable_citation")
                      for f in findings) else Verdict.PASS)
    return records, findings, verdict


def run_citation_audit(ctx: NodeContext) -> NodeOutcome:
    """P21: audit the manuscript bibliography if it exists, else the source
    bibliography. The node PASSes when the audit executed completely; findings
    carry the red (closure U4 enforces resolution)."""
    root = ctx.workspace.target_root
    # draft-derived fallback FIRST: it displaces itself (versioned) when a real
    # bib exists, so the glob below never mixes stale T4 entries into a real
    # chain (reviewer B P3-1)
    from .draft_refs import DERIVED_NAME, ensure_draft_bib
    ensure_draft_bib(root)
    manuscript_bib = ctx.workspace.paper_dir / "references.bib"
    bib_files = [manuscript_bib] if manuscript_bib.exists() else (
        sorted(root.glob("literature/*.bib")) + sorted(root.glob("*.bib")))
    if not bib_files:
        return NodeOutcome(Verdict.DEGRADED, {"reason": "no bibliography found"})
    entries = []
    for b in bib_files:
        for e in parse_bib(b):
            e["bib_file"] = str(b)
            # B-c / B R2-F2 / A R3-4: T4 provenance is bound to the ENTRY SPAN
            # by parse_bib (survives copies into references.bib and hostile
            # note payloads); the derived filename is an additional signal
            e["t4_derived"] = bool(e.get("t4_derived")) or b.name == DERIVED_NAME
            entries.append(e)

    records, findings, verdict = _audit_entries(ctx, entries)
    report = {"audited_at": utcnow(), "offline": ctx.offline, "entries": records,
              "findings": findings, "bib_files": [str(b) for b in bib_files],
              "records_sha256": sha256_json(records)}
    write_json(ctx.workspace.reports_dir / "citation_audit.json", report)
    return NodeOutcome(verdict, {"entries": len(entries),
                                 "critical": sum(1 for f in findings if f["severity"] == "CRITICAL"),
                                 "findings": len(findings),
                                 "offline": ctx.offline})


def build_references(ctx: NodeContext) -> NodeOutcome:
    """Build paper/references.bib from the source bibliography, excluding
    entries proven false by a citation audit (records the exclusion)."""
    root = ctx.workspace.target_root
    from .draft_refs import ensure_draft_bib
    ensure_draft_bib(root)  # fallback + self-displacement before globbing (B P3-1)
    src_bibs = sorted(root.glob("literature/*.bib")) + sorted(root.glob("*.bib"))
    if not src_bibs:
        return NodeOutcome(Verdict.DEGRADED, {"reason": "no source bibliography"})
    excluded: set[str] = set()
    audit_path = ctx.workspace.reports_dir / "citation_audit.json"
    if audit_path.exists():
        audit = json.loads(audit_path.read_text())
        excluded = {f["key"] for f in audit.get("findings", [])
                    if f.get("kind") == "false_citation"}
    kept, dropped = [], []
    out_lines = []
    for b in src_bibs:
        text = b.read_text(encoding="utf-8", errors="replace")
        # span-delimited copy: the old _BIB_ENTRY ([^@]* body) truncated at '@'
        # inside fields — the T4 provenance note (and with it the MAJOR
        # unverifiable_citation classification downstream) was lost on the
        # manuscript path (reviewer B R4-F1)
        for key, _body, raw in _entry_splits(text):
            if key in excluded:
                dropped.append(key)
                continue
            kept.append(key)
            out_lines.append(raw + "\n")
    dest = ctx.workspace.paper_dir / "references.bib"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(out_lines), encoding="utf-8")
    write_json(ctx.workspace.reports_dir / "references_build.json",
               {"built_at": utcnow(), "kept": kept, "dropped_false": sorted(dropped)})
    return NodeOutcome(Verdict.PASS, {"kept": len(kept), "dropped_false": sorted(dropped)})
