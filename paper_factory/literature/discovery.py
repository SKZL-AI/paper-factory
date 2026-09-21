"""P06 Literature discovery: deterministic metadata APIs (Crossref, OpenAlex,
Semantic Scholar). Query terms derive from intake/claims, results are stored
with verification records. Offline → DEGRADED with reason.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from ..core.results import Verdict
from ..core.util import utcnow, write_json
from ..dag.executor import NodeContext, NodeOutcome
from .verify import _UA


def _get(url: str, timeout: int = 25) -> dict[str, Any] | None:
    try:
        req = urllib.request.Request(url, headers=_UA)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return None


def search_openalex(query: str, per_page: int = 5) -> list[dict[str, Any]]:
    url = ("https://api.openalex.org/works?search=" + urllib.parse.quote(query)
           + f"&per-page={per_page}")
    data = _get(url)
    if not data:
        return []
    out = []
    for w in data.get("results", []):
        out.append({"source": "openalex", "id": w.get("id"), "doi": w.get("doi"),
                    "title": w.get("title"), "year": w.get("publication_year"),
                    "cited_by": w.get("cited_by_count")})
    return out


def search_crossref(query: str, rows: int = 5) -> list[dict[str, Any]]:
    url = ("https://api.crossref.org/works?query=" + urllib.parse.quote(query)
           + f"&rows={rows}")
    data = _get(url)
    if not data:
        return []
    out = []
    for item in data.get("message", {}).get("items", []):
        out.append({"source": "crossref", "doi": item.get("DOI"),
                    "title": (item.get("title") or [None])[0],
                    "container": (item.get("container-title") or [None])[0],
                    "year": ((item.get("issued") or {}).get("date-parts") or [[None]])[0][0]})
    return out


def derive_queries(ctx: NodeContext) -> list[str]:
    """Deterministic query derivation from intake + draft title/keywords."""
    root = ctx.workspace.target_root
    queries: list[str] = []
    import re

    for draft in sorted(root.glob("draft/*.md")) + sorted(root.glob("draft/*.tex")):
        text = draft.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"^#\s+(.+)$", text, re.M)
        if m:
            queries.append(m.group(1).strip())
        kw = re.findall(r"(?:keywords?|Schlüsselwörter)[:\s]+(.+)", text, re.I)
        queries.extend(k.strip() for k in kw)
    if not queries:
        queries.append(root.name.replace("_", " "))
    # dedupe, keep order
    seen = set()
    return [q for q in queries if not (q in seen or seen.add(q))][:5]


def run_literature_discovery(ctx: NodeContext) -> NodeOutcome:
    if ctx.offline:
        return NodeOutcome(Verdict.DEGRADED, {"reason": "offline mode — literature discovery not run",
                                              "literature": "NOT_RUN"})
    queries = derive_queries(ctx)
    found: dict[str, Any] = {"discovered_at": utcnow(), "queries": {}, "unique_works": {}}
    for q in queries:
        works = search_openalex(q) + search_crossref(q)
        found["queries"][q] = works
        for w in works:
            key = w.get("doi") or w.get("id") or w.get("title")
            if key:
                found["unique_works"][key] = w
    write_json(ctx.workspace.reports_dir / "literature_discovery.json", found)
    if not found["unique_works"]:
        return NodeOutcome(Verdict.DEGRADED, {"reason": "no works discovered (network?)",
                                              "queries": queries})
    return NodeOutcome(Verdict.PASS, {"queries": len(queries),
                                      "unique_works": len(found["unique_works"])})
