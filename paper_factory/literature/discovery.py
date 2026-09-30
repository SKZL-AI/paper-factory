"""P06 Literature discovery: deterministic metadata APIs (Crossref, OpenAlex,
Semantic Scholar). Query terms derive from intake/claims, results are stored
with verification records. Offline → DEGRADED with reason.
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
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


# GAP-013 (real pilot 2): a fallback query of literally "project" pulled 10
# thematically foreign works (NCEP, GTEx, warships). Query derivation must use
# real project vocabulary: drafts → README heading → config paper title →
# directory name — with generic words filtered out at every step.
_GENERIC_WORDS = {"project", "main", "repo", "work", "code", "src", "home",
                  "data", "results", "test", "pilot", "paper", "draft",
                  "untitled", "new", "final", "version", "the", "a", "an",
                  "and", "of", "for", "with", "on", "in"}
# provenance tags in parentheses are not query vocabulary — but only TAG-like
# parens are stripped (pilot/rev/version/year markers); content parens like
# "(Is All You Need)" stay (reviewer B: the paren may BE the content)
_TAG_PAREN = re.compile(
    r"\s*\((?:[^()]*(?:pilot|rev(?:ision)?|version|v\d|draft|pf|20\d\d)[^()]*)\)",
    re.IGNORECASE)


def _strip_tag_parens(title: str) -> str:
    prev = None
    while prev != title:  # iterate to fixpoint for adjacent tags
        prev = title
        title = _TAG_PAREN.sub("", title)
    return title.strip()


def _clean_title(title: str) -> str:
    """Markdown/markup hygiene (reviewer A-F4): bold/italic markers, links
    and trailing heading #'s are not query vocabulary."""
    title = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", title)  # [text](url) → text
    title = re.sub(r"[*_`]+", "", title)
    title = re.sub(r"\s*#+\s*$", "", title)
    return _strip_tag_parens(title.strip())


def _useful(query: str) -> bool:
    """A query is useful when at least one content word is non-generic.
    Unicode-aware (A-F3: CJK titles count); pure digits (years) are never
    content (A-F6); 2-letter all-caps abbreviations (AI, ML) count."""
    tokens = [t for t in re.split(r"[^\w]+", query) if t]
    content = [t for t in tokens
               if t.lower() not in _GENERIC_WORDS and not t.isdigit()
               and (len(t) > 2 or (len(t) == 2 and t.isupper()))]
    return bool(content) and len(query.strip()) >= 4


def derive_queries(ctx: NodeContext) -> list[str]:
    """Deterministic query derivation. Stages in priority order — draft
    title/keywords → README heading → config paper title → directory name —
    with fall-through on USELESSNESS, not just absence (A-F2). Generic
    results are dropped: a thematically empty query is worse than none
    (GAP-013)."""
    root = ctx.workspace.target_root

    def _stage_drafts() -> list[str]:
        out: list[str] = []
        for draft in sorted(root.glob("draft/*.md")) + sorted(root.glob("draft/*.tex")):
            text = draft.read_text(encoding="utf-8", errors="replace")
            m = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
            if m:
                out.append(_clean_title(m.group(1)))
            # line-anchored with mandatory colon (A-F1): prose mentioning
            # 'keywords' mid-sentence is not a keyword line
            for kw in re.findall(
                    r"^\s*(?:keywords?|Schlüsselwörter)\s*:\s*(.+)$",
                    text, re.IGNORECASE | re.MULTILINE):
                out.append(kw.strip())
        return out

    def _stage_readme() -> list[str]:
        readme = root / "README.md"
        if not readme.exists():
            return []
        m = re.search(r"^#\s+(.+)$",
                      readme.read_text(encoding="utf-8", errors="replace"), re.MULTILINE)
        return [_clean_title(m.group(1))] if m else []

    def _stage_config() -> list[str]:
        return [_clean_title(ctx.config.paper.title)] if ctx.config.paper.title else []

    def _stage_dirname() -> list[str]:
        return [root.name.replace("_", " ").replace("-", " ")]

    queries: list[str] = []
    for stage in (_stage_drafts, _stage_readme, _stage_config, _stage_dirname):
        useful = [q for q in stage() if _useful(q)]
        if useful:
            queries = useful
            break
    seen: set[str] = set()
    return [q for q in queries
            if not (q.casefold() in seen or seen.add(q.casefold()))][:5]


def run_literature_discovery(ctx: NodeContext) -> NodeOutcome:
    if ctx.offline:
        return NodeOutcome(Verdict.DEGRADED, {"reason": "offline mode — literature discovery not run",
                                              "literature": "NOT_RUN"})
    queries = derive_queries(ctx)
    if not queries:
        # GAP-013: no usable project vocabulary — an empty/generic query must
        # never reach the APIs (it returns thematically foreign noise)
        write_json(ctx.workspace.reports_dir / "literature_discovery.json",
                   {"discovered_at": utcnow(), "queries": {}, "unique_works": {}})
        return NodeOutcome(Verdict.DEGRADED,
                           {"reason": "no usable query vocabulary (drafts/README/title "
                                      "all missing or generic — GAP-013 filter)",
                            "literature": "NOT_RUN"})
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
