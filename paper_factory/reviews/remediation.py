"""P27 Remediation: structured findings → allowed corrections. Reviewer prose
is never copied into the manuscript (U15); corrections derive from primary
evidence. Remediation actions append to a ledger (never overwritten). A
finding is RESOLVED only when its own finding-specific post-condition is
verified against the persisted artifact — and, for claims, against the
protected manuscript surface (GAP-004).

Also owns the canonical scientific-freeze manifest (P28): ONE function hashes
the protected manuscript set, used both when freezing and when U6 verifies.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..claims.graph import ClaimGraph, load_claims, save_claims
from ..core.results import (CLOSED_DISPOSITIONS, ClaimStatus, Disposition, Severity,
                            Verdict)
from ..core.util import sha256_file, utcnow, write_json
from ..dag.executor import NodeContext, NodeOutcome
from ..statistics.quantitative import manuscript_tex_files, normalize_tex
from .framework import Finding, dedupe_key, load_reviews, save_review


def compute_freeze_manifest(paper: Path) -> dict[str, str]:
    """Canonical hash manifest of the manuscript tree (build/ excluded).
    Keys are posix-relative paths; both the freeze (P28) and the closure
    verification (U6) must use this single implementation. Symlinks are NOT
    followed (they could point outside the workspace) — they are recorded
    separately by compute_freeze_symlinks."""
    frozen: dict[str, str] = {}
    if paper.exists():
        for p in sorted(paper.rglob("*")):
            if p.is_file() and not p.is_symlink() and "build" not in p.parts:
                frozen[p.relative_to(paper).as_posix()] = sha256_file(p)
    return frozen


def compute_freeze_symlinks(paper: Path,
                            allowed_root: Path | None = None) -> tuple[dict[str, str],
                                                                       dict[str, str]]:
    """Symlink map of the manuscript tree: (relpath → link target,
    relpath → pinned content hash). Content is pinned only when the resolved
    target stays inside allowed_root (and is a regular file) — external
    targets are recorded by name and never read."""
    links: dict[str, str] = {}
    hashes: dict[str, str] = {}
    if paper.exists():
        root_resolved = allowed_root.resolve() if allowed_root is not None else None
        for p in sorted(paper.rglob("*")):
            if p.is_symlink() and "build" not in p.parts:
                rel = p.relative_to(paper).as_posix()
                links[rel] = str(p.readlink())
                if root_resolved is not None:
                    try:
                        target = p.resolve()
                        target.relative_to(root_resolved)
                        if target.is_file():
                            hashes[rel] = sha256_file(target)
                    except (ValueError, OSError):
                        pass  # external or dangling: name-pinned only
    return links, hashes


def run_remediation(ctx: NodeContext) -> NodeOutcome:
    """P27: every CRITICAL/MAJOR finding gets a finding-specific disposition.

    GAP-004: RESOLVED requires the finding's OWN post-condition, verified
    against the mutated artifact (bound claim RETIRED in claims.yaml; the
    specific citation key gone from references.bib). A global side-condition
    ("no unsupported claims remain anywhere") or a no-op action never closes
    a finding. Findings the deterministic core cannot fix truthfully (e.g.
    number_mismatch — U15 forbids rewriting protected prose) become DEFERRED
    with a concrete required action, and keep blocking closure via U5.
    """
    ws = ctx.workspace
    reviews, invalid = load_reviews(ws.reviews_dir)
    if invalid:
        # fail closed: a corrupt review artifact could hide CRITICAL/MAJOR
        # findings — it must be repaired or archived by a human, not skipped
        return NodeOutcome(Verdict.FAIL, {"reason": "REVIEW_ARTIFACT_INVALID",
                                          "invalid": invalid})
    claims_path = ws.claims_dir / "claims.yaml"
    graph = load_claims(claims_path)
    entries: list[dict] = []
    counts = {"resolved": 0, "deferred": 0, "unresolved": 0, "invalid": 0,
              "not_applicable": 0, "duplicates": 0}

    # GAP-010: the same underlying issue folded into several reviewer reports
    # is remediated ONCE; the disposition then propagates to every duplicate
    # (reviewer roles stay intact on the Finding objects)
    pending: list[Finding] = []
    for review in reviews:
        for f in review.findings:
            if f.severity not in (Severity.CRITICAL, Severity.MAJOR):
                continue
            if f.disposition in CLOSED_DISPOSITIONS:
                continue  # already closed (incl. human AUTHOR_DECISION)
            pending.append(f)

    # G1 (reviewer B): the anti-forgery excerpt↔statement check runs over ALL
    # claim-kind findings BEFORE deduplication — a forged duplicate must never
    # inherit a clean representative's RESOLVED. Missing refs or mismatched
    # excerpts are INVALID here; missing excerpts stay DEFERRED via the main
    # path (N1 rule).
    by_id = graph.by_id()
    for f in list(pending):
        kind = f.kind or _classify_legacy(f)
        if kind not in _CLAIM_KINDS or not f.claim_refs:
            continue
        excerpt = " ".join(normalize_tex(str(f.details.get("excerpt") or ""),
                                         strip_comments=False).split())
        missing = [c for c in f.claim_refs if c not in by_id]
        mismatched = []
        if excerpt:
            for cid in f.claim_refs:
                if cid in by_id:
                    stmt = " ".join(normalize_tex(by_id[cid].statement,
                                                  strip_comments=False).split())
                    if excerpt not in stmt and stmt not in excerpt:
                        mismatched.append(cid)
        if missing or mismatched:
            f.disposition = Disposition.INVALID_REMEDIATION_ARTIFACT
            f.disposition_reason = (f"broken claim binding (missing={missing}, "
                                    f"excerpt_mismatch={mismatched})")
            entries.append({"finding_id": f.finding_id, "kind": kind,
                            "action": "none", "at": utcnow(),
                            "reviewer_prose_copied": False,
                            "post_condition": "finding excerpt matches bound claims",
                            "verification": {"result": "invalid",
                                             "missing": missing,
                                             "mismatched": mismatched}})
            counts["invalid"] += 1
            pending.remove(f)

    representatives: dict[tuple, Finding] = {}
    duplicates: list[tuple[tuple, Finding]] = []
    for f in pending:
        k = dedupe_key(f)
        if k in representatives:
            duplicates.append((k, f))
        else:
            representatives[k] = f
            kind = f.kind or _classify_legacy(f)
            entry = {"finding_id": f.finding_id, "kind": kind, "category": f.category,
                     "severity": f.severity.value, "at": utcnow(),
                     "reviewer_prose_copied": False}

            if kind in _CLAIM_KINDS:
                _remediate_claim_finding(ctx, f, graph, claims_path, entry, counts)
                graph = load_claims(claims_path)  # the helper persists; refresh view
            elif kind in _CITATION_KINDS or f.category == "citation":
                _remediate_citation_finding(ctx, f, entry, counts)
            elif kind == "number_mismatch":
                d = f.details
                loc = d.get("draft") or f.affected_section or "?"
                expected = d.get("expected")
                if isinstance(expected, dict):
                    exp_txt = ", ".join(f"{k.split('__')[-1]}={v}"
                                        for k, v in list(expected.items())[:3])
                else:
                    exp_txt = str(expected if expected is not None
                                  else d.get("true_value", "?"))
                bound_txt = ", ".join(str(b)[:60] for b in (d.get("bound_metrics") or [])) \
                    or str(d.get("closest_metric") or "?")
                f.disposition = Disposition.DEFERRED
                f.disposition_reason = (
                    f"correcting draft number {d.get('value')} at {loc} requires an "
                    f"allowed writer (U15 forbids auto-editing protected prose); derived "
                    f"value(s): {exp_txt} (bound: {bound_txt})")
                entry.update(
                    action="defer",
                    post_condition=f"{loc} no longer asserts {d.get('value')} at that location",
                    verification={"result": "deferred", "required_action": f.disposition_reason})
                counts["deferred"] += 1
            else:
                f.disposition = Disposition.DEFERRED
                f.disposition_reason = (f"no deterministic remediation for kind={kind!r} "
                                        f"category={f.category!r}; needs writer or human")
                entry.update(action="defer",
                             post_condition="finding-specific correction by allowed writer",
                             verification={"result": "deferred"})
                counts["deferred"] += 1
            entries.append(entry)

    for k, f in duplicates:
        rep = representatives[k]
        f.disposition = rep.disposition
        f.disposition_reason = rep.disposition_reason
        f.resolved_by = rep.resolved_by
        entries.append({"finding_id": f.finding_id, "action": "duplicate",
                        "duplicate_of": rep.finding_id, "at": utcnow(),
                        "reviewer_prose_copied": False,
                        "disposition": rep.disposition.value if rep.disposition else None})
        counts["duplicates"] += 1

    if entries:
        for review in reviews:
            save_review(ws.reviews_dir, review)
    # G7: the log is a ledger — new actions append; a run without actions must
    # never erase the record of earlier ones
    log_path = ws.reports_dir / "remediation_log.json"
    prior_entries: list[dict] = []
    if log_path.exists():
        try:
            prior_entries = json.loads(log_path.read_text(encoding="utf-8")).get("entries", [])
        except (json.JSONDecodeError, OSError):
            prior_entries = [{"kind": "REMEDIATION_LOG_CORRUPT", "at": utcnow()}]
    if entries or not log_path.exists():
        write_json(log_path, {"logged_at": utcnow(), "run_id": ctx.run_id,
                              "entries": prior_entries + entries,
                              "summary": counts, "entries_this_run": len(entries)})
    if counts["invalid"]:
        verdict = Verdict.FAIL  # broken evidence chain — repair, never route around
    elif counts["deferred"] or counts["unresolved"]:
        verdict = Verdict.DEGRADED  # honest: findings remain open, U5 will block
    else:
        verdict = Verdict.PASS
    return NodeOutcome(verdict, {"remediated": counts["resolved"],
                                 "deferred": counts["deferred"],
                                 "unresolved": counts["unresolved"],
                                 "invalid": counts["invalid"],
                                 "not_applicable": counts["not_applicable"],
                                 "duplicates": counts["duplicates"]})


def _presence_stream(text: str, is_latex: bool = True) -> str:
    """Normalize for claim-presence matching across the Markdown↔LaTeX boundary
    (reviewer B round 2): case-folded and fully whitespace-free so that
    `mass\\_inv` == `mass_inv`, `by~half` == `by half`, `\\textbf{X}` == `X`
    and capitalization cannot evade the check. is_latex=False for the claim
    side: draft statements are markdown/plain text, where `%` is a literal
    percent sign — LaTeX comment stripping would amputate the statement."""
    body = normalize_tex(text, strip_comments=is_latex)
    # fold refs/cites to the same tokens the draft-side cleaner uses, so a
    # claim carried over verbatim matches on both sides (reviewer A N-B)
    body = re.sub(r"\\cite\w*(?:\[[^]]*\])*\{[^}]*\}", " CITE ", body)
    body = re.sub(r"\\(?:page|eq|auto)?ref\{[^}]*\}", " REF ", body)
    body = (body.replace("\\_", "_").replace("\\&", "&").replace("\\#", "#")
                .replace("~", " "))
    body = re.sub(r"\\[a-zA-Z]+\*?", "", body)  # commands carry no claim text
    body = re.sub(r"\\(.)", r"\1", body)       # remaining escapes: \% → %, \. → .
    body = body.replace("{", "").replace("}", "").replace("$", "")
    return re.sub(r"\s+", "", body).casefold()


def _claim_printed(statement: str, body_stream: str, window: int = 60) -> bool:
    """Windowed containment of the normalized claim in the normalized
    manuscript stream — a >240-char claim whose only the tail is printed is
    still caught (reviewer B a9), while paraphrase-level divergence is a human
    review matter, not a substring job."""
    s = _presence_stream(statement, is_latex=False)
    if not s:
        return False
    if len(s) <= window:
        return s in body_stream
    return any(s[i:i + window] in body_stream
               for i in range(0, len(s) - window + 1, window // 2))


def _manuscript_surface_files(paper: Path) -> list[Path]:
    """The claim-presence surface == the U2 manuscript surface, except that
    generated/ IS printed prose (a claim in generated/captions.tex is printed —
    reviewer B a7). One canonical traversal (quantitative.manuscript_tex_files)
    so the surfaces can never drift apart (reviewer B-P1)."""
    return manuscript_tex_files(paper, include_generated=True)


_CLAIM_KINDS = {"unsupported_claim", "significance_without_test"}
_CITATION_KINDS = {"false_citation", "no_doi", "unverifiable_citation"}


def _classify_legacy(f: "Finding") -> str | None:
    """Kind inference for findings from before structured folding (e.g.
    historical pilot artifacts). Conservative: when in doubt, None → DEFERRED."""
    s = f.statement.lower()
    if "number" in s and ("metric" in s or "mismatch" in s):
        return "number_mismatch"
    if "significan" in s or "unsupported" in s:
        return "unsupported_claim"
    if f.category == "citation" or "citation" in s or "doi" in s:
        return "citation_generic"
    return None


def _remediate_claim_finding(ctx: NodeContext, f: "Finding", graph: ClaimGraph,
                             claims_path: Path, entry: dict, counts: dict) -> None:
    """Retire exactly the claims bound to this finding — and verify the claim
    is also gone from the printed manuscript. Graph retirement alone is
    bookkeeping: the finding is RESOLVED only when the protected manuscript
    no longer asserts the claim (reviewer B-B1)."""
    if not f.claim_refs:
        f.disposition = Disposition.DEFERRED
        f.disposition_reason = (f"{f.kind} finding without claim binding cannot be "
                                "verified — needs an allowed writer to remove the "
                                "statement or a human to bind the claim")
        entry.update(action="defer",
                     post_condition="bound claim retired OR statement removed by writer",
                     verification={"result": "deferred", "reason": "no claim_refs"})
        counts["deferred"] += 1
        return
    by_id = graph.by_id()
    missing = [c for c in f.claim_refs if c not in by_id]
    if missing:
        f.disposition = Disposition.INVALID_REMEDIATION_ARTIFACT
        f.disposition_reason = f"claim_refs not in claim graph: {missing}"
        entry.update(action="none", post_condition="claim_refs exist in graph",
                     verification={"result": "invalid", "missing": missing})
        counts["invalid"] += 1
        return
    # binding sanity (reviewer A-G6 + N1): the binding is only verifiable when
    # the finding carries the claim excerpt AND it matches the bound claim's
    # statement (both sides normalized identically). No excerpt → the binding
    # cannot be verified at all → DEFERRED, never a blind retirement.
    excerpt = " ".join(normalize_tex(str(f.details.get("excerpt") or ""),
                                     strip_comments=False).split())
    if not excerpt:
        f.disposition = Disposition.DEFERRED
        f.disposition_reason = (f"{f.kind} finding without excerpt — claim binding "
                                "unverifiable; needs re-review or human binding")
        entry.update(action="defer",
                     post_condition="finding carries a verifiable claim excerpt",
                     verification={"result": "deferred", "reason": "no excerpt"})
        counts["deferred"] += 1
        return
    mismatched = []
    for cid in f.claim_refs:
        stmt = " ".join(normalize_tex(by_id[cid].statement, strip_comments=False).split())
        if excerpt not in stmt and stmt not in excerpt:
            mismatched.append(cid)
    if mismatched:
        f.disposition = Disposition.INVALID_REMEDIATION_ARTIFACT
        f.disposition_reason = (f"finding excerpt does not match bound claim statements: "
                                f"{mismatched}")
        entry.update(action="none", post_condition="finding excerpt matches bound claims",
                     verification={"result": "invalid", "mismatched": mismatched})
        counts["invalid"] += 1
        return
    conflicts = [c for c in f.claim_refs if by_id[c].status == ClaimStatus.VERIFIED]
    if conflicts:
        # a finding says 'unsupported', the graph says VERIFIED with evidence —
        # a substantive conflict for a human, never a silent retirement
        f.disposition = Disposition.UNRESOLVED
        f.disposition_reason = f"bound claims are VERIFIED, refusing to retire: {conflicts}"
        entry.update(action="none", post_condition="conflict resolved by human",
                     verification={"result": "conflict", "verified_claims": conflicts})
        counts["unresolved"] += 1
        return
    verification: dict[str, Any] = {"claims": {}}
    for cid in f.claim_refs:
        verification["claims"][cid] = {"before": by_id[cid].status.value}
        if by_id[cid].status != ClaimStatus.RETIRED:
            by_id[cid].status = ClaimStatus.RETIRED
    save_claims(claims_path, graph)
    # B2: verify against the persisted artifact, not the in-memory objects
    reloaded = load_claims(claims_path).by_id()
    for cid in f.claim_refs:
        verification["claims"][cid]["after"] = reloaded[cid].status.value
    retired_in_graph = all(reloaded[c].status == ClaimStatus.RETIRED for c in f.claim_refs)
    # B1: the claim must also be gone from the protected manuscript surface —
    # otherwise the paper still prints what the graph withdrew. Presence is
    # checked window-wise over markup-invariant streams, including generated/
    # captions (reviewer B r2). Each file is matched twice: as printed (LaTeX
    # comment rules — a claim hidden in a comment is not asserted) and as raw
    # source (a claim sitting in a comment is still source presence worth a
    # human look — fail-closed over-blocking is the honest direction).
    printed_in = []
    for tex in _manuscript_surface_files(ctx.workspace.paper_dir):
        raw = tex.read_text(encoding="utf-8", errors="replace")
        streams = (_presence_stream(raw, is_latex=True),
                   _presence_stream(raw, is_latex=False))
        for cid in f.claim_refs:
            if any(_claim_printed(reloaded[cid].statement, s) for s in streams):
                printed_in.append(f"{cid}@{tex.relative_to(ctx.workspace.paper_dir)}")
    verification["retired_in_graph"] = retired_in_graph
    verification["printed_in_manuscript"] = printed_in
    entry.update(action="retire_bound_claims", bound=list(f.claim_refs),
                 post_condition=("bound claims RETIRED in claims.yaml AND claim text "
                                 "absent from the protected manuscript"),
                 verification=verification)
    if not retired_in_graph:
        f.disposition = Disposition.UNRESOLVED
        f.disposition_reason = f"persisted graph does not show retirement: {verification}"
        counts["unresolved"] += 1
    elif printed_in:
        f.disposition = Disposition.DEFERRED
        f.disposition_reason = (
            f"claims retired in the graph but still printed in the manuscript "
            f"({printed_in}); removing the prose requires an allowed writer (U15)")
        counts["deferred"] += 1
    else:
        f.disposition = Disposition.RESOLVED
        f.resolved_by = "paper-factory/remediation"
        f.disposition_reason = (f"bound claims retired (verified on disk) and absent "
                                f"from the manuscript: {list(f.claim_refs)}")
        counts["resolved"] += 1


def _remediate_citation_finding(ctx: NodeContext, f: "Finding", entry: dict,
                                counts: dict) -> None:
    """Drop the specific unverifiable citation and verify THAT key is gone —
    by parsed-entry equality, not substring (reviewer A-G4). A finding about a
    citation that was never in the bibliography is stale, not a remediation
    success (A-G5)."""
    key = f.details.get("doi") or f.details.get("key")
    if not key:
        f.disposition = Disposition.DEFERRED
        f.disposition_reason = ("citation finding without doi/key binding cannot be "
                                "verified — needs a human to identify the entry")
        entry.update(action="defer", post_condition="specific citation removed",
                     verification={"result": "deferred", "reason": "no doi/key"})
        counts["deferred"] += 1
        return
    from ..literature.verify import _audit_entries, build_references, parse_bib

    bib = ctx.workspace.paper_dir / "references.bib"

    def _present(entries: list[dict]) -> bool:
        # DOIs are case-insensitive per spec (reviewer A-N3)
        key_l = key.lower()
        return any(key_l in (str(e.get("doi") or "").lower(), str(e.get("key") or "").lower())
                   for e in entries)

    pre_entries = parse_bib(bib) if bib.exists() else []
    if not _present(pre_entries):
        f.disposition = Disposition.NOT_APPLICABLE
        f.resolved_by = "paper-factory/remediation"
        f.disposition_reason = (f"citation {key} is not present in references.bib — "
                                "nothing to remediate (stale finding)")
        entry.update(action="none",
                     post_condition="citation absent (stale finding)",
                     verification={"result": "not_applicable", "key": key,
                                   "present_before": False})
        counts["not_applicable"] += 1
        return
    build_references(ctx)
    post_entries = parse_bib(bib) if bib.exists() else []
    final_records, final_findings, _ = _audit_entries(
        ctx, post_entries) if bib.exists() else ([], [], None)
    write_json(ctx.workspace.reports_dir / "citation_audit_final.json",
               {"audited_at": utcnow(), "entries": final_records,
                "findings": final_findings, "post_remediation": True,
                "offline": ctx.offline})
    still_present = _present(post_entries)
    crit_for_key = [x for x in final_findings
                    if x.get("severity") == "CRITICAL" and key in json.dumps(x)]
    verification = {"key": key, "present_before": True,
                    "still_present": still_present,
                    "critical_remaining_for_key": len(crit_for_key)}
    entry.update(action="drop_unverifiable_citation", bound=key,
                 post_condition=f"{key} absent from parsed references.bib entries and no CRITICAL re-audit finding",
                 verification=verification)
    if not still_present and not crit_for_key:
        f.disposition = Disposition.RESOLVED
        f.resolved_by = "paper-factory/remediation"
        f.disposition_reason = f"citation {key} removed (parsed-entry verified) and re-audit clean for this key"
        counts["resolved"] += 1
    else:
        f.disposition = Disposition.UNRESOLVED
        f.disposition_reason = f"citation {key} still present/critical: {verification}"
        counts["unresolved"] += 1


def run_scientific_freeze(ctx: NodeContext) -> NodeOutcome:
    """P28: freeze the manuscript + evidence state by hash."""
    ws = ctx.workspace
    paper = ws.paper_dir
    frozen = compute_freeze_manifest(paper)
    links, link_hashes = compute_freeze_symlinks(paper, allowed_root=ws.root)
    main = paper / "main.tex"
    record = {"frozen_at": utcnow(), "files": frozen, "symlinks": links,
              "symlink_hashes": link_hashes,
              "main_tex_sha256": sha256_file(main) if main.exists() else None}
    write_json(ws.reports_dir / "scientific_freeze.json", record)
    if not main.exists():
        return NodeOutcome(Verdict.DEGRADED, {"reason": "no manuscript to freeze"})
    return NodeOutcome(Verdict.PASS, {"files_frozen": len(frozen)})
