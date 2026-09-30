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


_BIB_ENTRY = re.compile(r"@\w+\s*\{\s*([^,]+),([^@]*)\}", re.DOTALL)
_DOI = re.compile(r"doi\s*=\s*[{\"]?([^}\s,\"]+)", re.IGNORECASE)
_TITLE = re.compile(r"title\s*=\s*[\{\"](.+?)[}\"]\s*,", re.DOTALL | re.IGNORECASE)


def parse_bib(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    entries = []
    for m in _BIB_ENTRY.finditer(text):
        key, body = m.group(1).strip(), m.group(2)
        doi = _DOI.search(body)
        title = _TITLE.search(body)
        entries.append({"key": key, "doi": doi.group(1) if doi else None,
                        "title": re.sub(r"\s+", " ", title.group(1)).strip() if title else None})
    return entries


def _audit_entries(ctx: NodeContext, entries: list[dict[str, Any]]) -> tuple[list, list, Verdict]:
    records, findings = [], []
    if ctx.offline:
        for e in entries:
            records.append({"key": e["key"], "doi": e.get("doi"), "verdict": "NOT_RUN",
                            "reason": "offline mode"})
        return records, findings, Verdict.DEGRADED
    for e in entries:
        if not e.get("doi"):
            records.append({"key": e["key"], "verdict": "NO_DOI", "title": e.get("title")})
            findings.append({"severity": "MINOR", "kind": "no_doi", "key": e["key"]})
            continue
        rec = resolve_doi(e["doi"])
        rec["key"] = e["key"]
        rec["claimed_title"] = e.get("title")
        records.append(rec)
        if rec["verdict"] == "NOT_FOUND":
            findings.append({"severity": "CRITICAL", "kind": "false_citation",
                             "key": e["key"], "doi": e["doi"]})
        elif rec["verdict"] == "UNKNOWN_NETWORK":
            findings.append({"severity": "MAJOR", "kind": "unverifiable_network",
                             "key": e["key"], "doi": e["doi"]})
    verdict = Verdict.DEGRADED if any(f["kind"] == "unverifiable_network" for f in findings) else Verdict.PASS
    return records, findings, verdict


def run_citation_audit(ctx: NodeContext) -> NodeOutcome:
    """P21: audit the manuscript bibliography if it exists, else the source
    bibliography. The node PASSes when the audit executed completely; findings
    carry the red (closure U4 enforces resolution)."""
    root = ctx.workspace.target_root
    manuscript_bib = ctx.workspace.paper_dir / "references.bib"
    bib_files = [manuscript_bib] if manuscript_bib.exists() else (
        sorted(root.glob("literature/*.bib")) + sorted(root.glob("*.bib")))
    if not bib_files:
        return NodeOutcome(Verdict.DEGRADED, {"reason": "no bibliography found"})
    entries = []
    for b in bib_files:
        for e in parse_bib(b):
            e["bib_file"] = str(b)
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
        for m in _BIB_ENTRY.finditer(text):
            key = m.group(1).strip()
            if key in excluded:
                dropped.append(key)
                continue
            kept.append(key)
            out_lines.append("@" + text[m.start():m.end()].lstrip("@").strip() + "\n")
    dest = ctx.workspace.paper_dir / "references.bib"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(out_lines), encoding="utf-8")
    write_json(ctx.workspace.reports_dir / "references_build.json",
               {"built_at": utcnow(), "kept": kept, "dropped_false": sorted(dropped)})
    return NodeOutcome(Verdict.PASS, {"kept": len(kept), "dropped_false": sorted(dropped)})
