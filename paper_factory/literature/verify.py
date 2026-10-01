"""Literature verification: every final citation gets a verification record.
Never invent citations. Offline → DEGRADED, never silently skipped.
"""
from __future__ import annotations

import json
import re
import html
import unicodedata
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
# DataCite is the REGISTRY of every arXiv DOI — OpenAlex does not index them
# all (10.48550/arXiv.1706.03762 404s on OpenAlex while DataCite resolves it,
# pilot-3 prep 2026-10-01); without this source a real arXiv citation becomes
# a false false_citation CRITICAL
DATACITE = "https://api.datacite.org/dois/"
_UA = {"User-Agent": "paper-factory/0.1 (mailto:paper-factory@local)"}


def resolve_doi(doi: str, timeout: int = 20) -> dict[str, Any]:
    """Verify a DOI against Crossref, then OpenAlex and DataCite as second
    sources."""
    rec: dict[str, Any] = {"doi": doi, "checked_at": utcnow(), "sources": {}}
    for name, base in (("crossref", CROSSREF), ("openalex", OPENALEX),
                       ("datacite", DATACITE)):
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
            elif name == "openalex" and rec.get("title") is None:
                # DataCite-registered DOIs are never in Crossref — without
                # these fallbacks their identity check was always unjudgeable
                # (reviewer A F1). An EMPTY string is no title and must not
                # block the next fallback (reviewer A D3)
                t = body.get("title") or body.get("display_name")
                rec["title"] = t if isinstance(t, str) and t.strip() else None
            elif name == "datacite" and rec.get("title") is None:
                # registrant payloads are noisy: data/attributes may be null
                # or non-dict (JSON:API allows data:null) — never crash the
                # whole audit on one odd payload (reviewer A D1 / B R5-1).
                # Prefer the original (untyped, lang-less) title over
                # translations (reviewer B R5-3)
                data = body.get("data")
                attrs = data.get("attributes") if isinstance(data, dict) else None
                titles = attrs.get("titles") if isinstance(attrs, dict) else None
                if isinstance(titles, list):
                    cands = [x for x in titles if isinstance(x, dict)]
                    # original title first: untyped beats TranslatedTitle,
                    # lang-less/English beats other languages — even when ALL
                    # entries carry a lang (reviewer B R6-1)
                    cands.sort(key=lambda x: (x.get("titleType") is not None,
                                              (x.get("lang") or "en") != "en"))
                    rec["title"] = next(
                        (v for x in cands
                         if isinstance((v := x.get("title")), str) and v.strip()),
                        None)
        except urllib.error.HTTPError as exc:
            rec["sources"][name] = {"status": "not_found" if exc.code == 404 else f"http_{exc.code}"}
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            rec["sources"][name] = {"status": "error", "error": str(exc)[:200]}
    found = any(s.get("status") == "found" for s in rec["sources"].values())
    # only an answered 404 is evidence of absence — rate limits (429), 5xx
    # and network errors all mean we cannot KNOW (reviewer A D2 / B R6):
    # NOT_FOUND (CRITICAL, entry dropped) requires every reachable registry
    # to have answered 404, anything less stays UNKNOWN_NETWORK (entry kept)
    statuses = [str(s.get("status")) for s in rec["sources"].values()]
    # 404 is recorded as "not_found"; any "http_<code>" here is non-404
    # (429, 5xx) — a server answer that is NOT evidence of absence
    unknowable = any(s == "error" or s.startswith("http_") for s in statuses)
    rec["verdict"] = "VERIFIED" if found else ("UNKNOWN_NETWORK" if unknowable else "NOT_FOUND")
    return rec


_DOI = re.compile(r"doi\s*=\s*[{\"]?([^}\s,\"]+)", re.IGNORECASE)


def _bib_field(body: str, name: str) -> str | None:
    """Brace-aware BibTeX field extraction. A regex with a mandatory trailing
    comma misses a legal last-field title (reviewer A F2) and truncates titles
    containing `},` (A F8); balanced-brace scanning handles both."""
    m = re.search(rf"(?<![A-Za-z]){re.escape(name)}\s*=\s*", body, re.IGNORECASE)
    if not m:
        return None
    i = m.end()
    while i < len(body) and body[i] in " \t\r\n":
        i += 1
    if i >= len(body):
        return None
    if body[i] == "{":
        depth = 0
        for j in range(i, len(body)):
            if body[j] == "{":
                depth += 1
            elif body[j] == "}":
                depth -= 1
                if depth == 0:
                    return body[i + 1:j]
        return None
    if body[i] == '"':
        end = body.find('"', i + 1)
        return body[i + 1:end] if end != -1 else None
    bare = re.match(r"[^,}\s]+", body[i:])
    return bare.group(0) if bare else None


_LATEX_ACCENTS = {"'": "́", '"': "̈", "`": "̀", "^": "̂",
                  "~": "̃", "=": "̄", ".": "̇", "c": "̧",
                  "u": "̆", "v": "̌", "H": "̋", "k": "̨"}
_LATEX_CHARS = {"ss": "ß", "ae": "æ", "oe": "œ", "aa": "å", "o": "ø",
                "i": "i", "j": "j", "l": "ł",
                "AE": "Æ", "OE": "Œ", "AA": "Å", "O": "Ø", "L": "Ł"}


def _latex_unescape(s: str) -> str:
    """Resolve standard BibTeX title escapes to Unicode BEFORE normalizing:
    special chars first (`\\i` must become ASCII i — the dotless ı has no
    NFKD decomposition and would asymmetrically vanish), then accent macros
    (`{\\"o}`, `\\'e`, `{\\`e}`…), then formatting macros (`\\emph{…}` keeps
    its argument). Without this every correctly-escaped bib title mismatches
    its clean Crossref title (reviewer B B-1 / reviewer A F5)."""
    s = re.sub(r"\\(ss|ae|oe|aa|AE|OE|AA|[oOiIjJlL])\b",
               lambda m: _LATEX_CHARS[m.group(1)], s)
    # no `\s*` after the letter: it would eat the word boundary behind an
    # unbraced accent (`Caf\'e Central` → `cafécentral`, reviewer B R2-2)
    s = re.sub(r"\{?\s*\\(['\"`^~=.cuvHk])\s*\{?([A-Za-z])\}?\}?",
               lambda m: m.group(2) + _LATEX_ACCENTS[m.group(1)], s)
    return re.sub(r"\\[a-zA-Z]+", "", s)


def _norm_title(s: str) -> str:
    """Canonical title form for identity comparison: LaTeX escapes resolved,
    unicode-decomposed, diacritics stripped, case folded, BibTeX
    transliteration folded (Mueller ≈ Müller, reviewer A F6), every
    non-alphanumeric run (punctuation, dashes, curly quotes, braces,
    whitespace) becomes one space. Harmless typographic variation must not
    fail; a DIFFERENT paper's title can never survive this."""
    # HTML entities first — registrant-supplied DataCite titles carry &amp;
    # etc. (reviewer B R5-2); applied to BOTH sides via this one function
    s = html.unescape(s)
    s = _latex_unescape(s)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.casefold()
    s = s.replace("ue", "u").replace("oe", "o").replace("ae", "a")
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _titles_match(claimed: str | None, resolved: str | None) -> bool | None:
    """None = unjudgeable: a title is missing or carries fewer than two
    tokens — a one-word/degenerate title can never prove identity
    (reviewer A F3/F7) and must never fabricate a mismatch either.
    True = canonical equality, or a token-boundary prefix where the longer
    RAW title carries a subtitle separator — the 'Title: Subtitle'
    convention (A F4). A plain longer title is a different work
    ('Gaussian Processes' ≠ 'Gaussian Processes for Machine Learning',
    reviewer B R2-3 / A N10). Deliberately no fuzzy tolerance beyond that."""
    if not claimed or not resolved:
        return None
    a, b = _norm_title(claimed), _norm_title(resolved)
    if len(a.split()) < 2 or len(b.split()) < 2:
        return None
    if a == b:
        return True
    # subtitle tolerance is ONE-DIRECTIONAL: only a longer RESOLVED title with
    # a subtitle separator (':', en/em-dash, or spaced hyphen — the 'Title:
    # Subtitle' convention, A F4/P1) proves the same work. A claimed-side
    # extension ('X: A Closer Look' resolving to plain 'X') is a different
    # work at the original's DOI (reviewer B R3-2).
    if len(a) < len(b) and re.search(r"[:–—]| - ", resolved):
        return b.startswith(a + " ")
    return False


_EPRINT = re.compile(r"eprint\s*=\s*[{\"]?([^}\s,\"]+)", re.IGNORECASE)
# arXiv version suffixes come in any case (v2, V2) — the DataCite namespace is
# versionless, an unstripped suffix 404s a REAL paper (reviewer A R3-1/R4-1)
_EPRINT_VERSION = re.compile(r"v\d+$", re.IGNORECASE)


def _synth_doi(doi: str | None, eprint: str | None) -> str | None:
    """The verifiable identifier of an entry: its DOI, or — for arXiv
    preprints — the official DataCite DOI. The namespace is VERSIONLESS, an
    unstripped `v2` suffix 404s a real paper (reviewer A R3-1/R4-1). One
    canonical place: audit, exclusion and remediation must never diverge on
    this (reviewer B R2-1)."""
    if doi:
        return doi
    if eprint:
        return f"10.48550/arXiv.{_EPRINT_VERSION.sub('', eprint)}"
    return None
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
        title = _bib_field(body, "title")
        eprint = _EPRINT.search(body)
        note = _NOTE.search(body)
        # line-anchored, not _bib_field: a draft can INJECT the literal
        # string 'x-pf-title-cut = false' into its own title text; the real
        # field always starts its own line (reviewer A R2-R1)
        cut = re.search(r"(?m)^\s*x-pf-title-cut\s*=\s*\{?\s*true", body,
                        re.IGNORECASE)
        url = _bib_field(body, "url")
        entries.append({"key": key, "doi": doi.group(1) if doi else None,
                        "title": re.sub(r"\s+", " ", title).strip() if title else None,
                        "eprint": eprint.group(1) if eprint else None,
                        "note": note.group(1).strip() if note else None,
                        "url": url.strip() if url else None,
                        # parser-narrowed draft title: prefix-only identity
                        # matches on it are unjudgeable (reviewer A R2-B1)
                        "title_cut": bool(cut),
                        # content-bound: survives build_references copies and
                        # nasty note payloads (reviewer B R2-F2 / A R3-4)
                        "t4_derived": T4_NOTE_MARK in body})
    return entries


def _verify_url_entry(e: dict[str, Any]) -> dict[str, Any]:
    """Authoritative-URL verification branch of _audit_entries. Returns
    {"record", "findings"}. The URL verdict taxonomy lives in url_verify;
    identity discipline is identical to the DOI path (incl. the cut-title
    prefix downgrade, reviewer A R2-B1)."""
    from .url_verify import verify_authoritative_url
    rec = verify_authoritative_url(e["url"])
    rec["key"] = e["key"]
    rec["claimed_title"] = e.get("title")
    rec["t4_derived"] = e.get("t4_derived", False)
    findings: list[dict] = []
    verdict = rec["verdict"]
    if verdict == "VERIFIED_AUTHORITATIVE_URL":
        match = _titles_match(e.get("title"), rec.get("title"))
        if match is True and e.get("title_cut"):
            exact = _norm_title(e.get("title") or "") == \
                _norm_title(rec.get("title") or "")
            if not exact:
                match = None
        rec["identity_check"] = ("match" if match is True else
                                 "unjudgeable" if match is None else "mismatch")
        if match is False:
            rec["verdict"] = "IDENTITY_MISMATCH"
            findings.append({"severity": "CRITICAL",
                             "kind": "citation_identity_mismatch",
                             "key": e["key"], "url": e["url"],
                             "claimed_title": e.get("title"),
                             "resolved_title": rec.get("title")})
        elif match is None:
            findings.append({"severity": "MINOR",
                             "kind": "identity_unjudgeable",
                             "key": e["key"], "url": e["url"]})
    elif verdict == "NOT_FOUND":
        findings.append({"severity": "CRITICAL", "kind": "false_url_citation",
                         "key": e["key"], "url": e["url"]})
    elif verdict == "UNKNOWN_NETWORK":
        findings.append({"severity": "MAJOR", "kind": "unverifiable_network",
                         "key": e["key"], "url": e["url"]})
    else:
        # NOT_AUTHORITATIVE_URL / REDIRECT_DOMAIN_CHANGED / NOT_HTTPS: the
        # URL cannot vouch for the work — the entry stands as unverifiable
        # as if it had no identifier at all
        if e.get("t4_derived"):
            findings.append({"severity": "MAJOR", "kind": "unverifiable_citation",
                             "key": e["key"]})
        else:
            findings.append({"severity": "MINOR", "kind": "no_doi",
                             "key": e["key"]})
    return {"record": rec, "findings": findings}


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
            # NOT_FOUND and becomes a false_citation, exactly as it should)
            doi = _synth_doi(None, e["eprint"])
            doi_source = "arxiv_synthesized"
        if not doi and e.get("url"):
            # authoritative-URL path: works without any DOI exist (W3C RECs,
            # official software docs). The URL must retrieve, stay on the
            # authoritative domain, and carry the cited title — a random blog
            # with a matching title is never 'verified' (consultant brief
            # 2026-10-01)
            rec = _verify_url_entry(e)
            records.append(rec["record"])
            findings.extend(rec["findings"])
            continue
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
        if rec["verdict"] == "VERIFIED":
            # resolvable ≠ correct: compare the resolved work's title against
            # the cited one. A real DOI belonging to a DIFFERENT paper is the
            # strongest false-citation class there is (final acceptance 2026-10-01)
            match = _titles_match(e.get("title"), rec.get("title"))
            if match is True and e.get("title_cut"):
                # the draft-ref parser NARROWED this title — a prefix-only
                # match could be manufactured by the cut itself (the author
                # never wrote a short title), so only full equality proves
                # identity here (reviewer A R2-B1)
                exact = _norm_title(e.get("title") or "") == \
                    _norm_title(rec.get("title") or "")
                if not exact:
                    match = None
            rec["identity_check"] = ("match" if match is True else
                                     "unjudgeable" if match is None else "mismatch")
            if match is False:
                rec["verdict"] = "IDENTITY_MISMATCH"
                findings.append({"severity": "CRITICAL",
                                 "kind": "citation_identity_mismatch",
                                 "key": e["key"], "doi": doi,
                                 "claimed_title": e.get("title"),
                                 "resolved_title": rec.get("title")})
            elif match is None:
                # unjudgeable must be VISIBLE (reviewer A recommendation d):
                # a MINOR on the record beats a silent bypass hole
                findings.append({"severity": "MINOR",
                                 "kind": "identity_unjudgeable",
                                 "key": e["key"], "doi": doi})
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
    excluded: list[dict] = []
    audit_path = ctx.workspace.reports_dir / "citation_audit.json"
    if audit_path.exists():
        audit = json.loads(audit_path.read_text())
        # proven-wrong citations never reach the manuscript bib: the DOI does
        # not resolve (false_citation) or resolves to a DIFFERENT work
        # (citation_identity_mismatch)
        excluded = [f for f in audit.get("findings", [])
                    if f.get("kind") in ("false_citation",
                                         "false_url_citation",
                                         "citation_identity_mismatch")]

    def _excluded(key: str, body: str) -> bool:
        # bound to (key, doi): a stale finding must not drop an entry whose
        # DOI the author has since corrected under the same key (reviewer B-2).
        # Findings without a DOI keep the legacy key-only behaviour. The
        # entry's verifiable identifier is the SYNTHESIZED DataCite DOI for
        # eprint-only entries — else a proven-fake arXiv citation survives
        # every rebuild (reviewer B R2-1). URL findings bind to (key, url)
        # the same way: a corrected URL under the same key survives.
        doi_m = _DOI.search(body)
        ep_m = _EPRINT.search(body)
        entry_doi = (_synth_doi(doi_m.group(1) if doi_m else None,
                                ep_m.group(1) if ep_m else None) or "").lower()
        # Zotero/web exports write doi={https://doi.org/…} — the ENTRY side is
        # normalized exactly like the finding side (reviewer A P3)
        entry_doi = entry_doi.removeprefix("https://doi.org/").removeprefix("http://doi.org/")
        entry_url = (_bib_field(body, "url") or "").strip().lower()
        for f in excluded:
            if f.get("key") != key:
                continue
            f_doi = str(f.get("doi") or "").lower()
            f_doi = f_doi.removeprefix("https://doi.org/").removeprefix("http://doi.org/")
            if f_doi:
                if f_doi == entry_doi:
                    return True
                continue
            f_url = str(f.get("url") or "").strip().lower()
            if f_url:
                if f_url == entry_url:
                    return True
                continue
            return True
        return False

    kept, dropped = [], []
    out_lines = []
    for b in src_bibs:
        text = b.read_text(encoding="utf-8", errors="replace")
        # span-delimited copy: the old _BIB_ENTRY ([^@]* body) truncated at '@'
        # inside fields — the T4 provenance note (and with it the MAJOR
        # unverifiable_citation classification downstream) was lost on the
        # manuscript path (reviewer B R4-F1)
        for key, body, raw in _entry_splits(text):
            if _excluded(key, body):
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
