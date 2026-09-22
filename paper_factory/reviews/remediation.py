"""P27 Remediation: structured findings → allowed corrections. Reviewer prose
is never copied into the manuscript (U15); corrections derive from primary
evidence. Every step is logged.

Also owns the canonical scientific-freeze manifest (P28): ONE function hashes
the protected manuscript set, used both when freezing and when U6 verifies.
"""
from __future__ import annotations

from pathlib import Path

from ..claims.graph import load_claims, save_claims
from ..core.results import ClaimStatus, Disposition, Severity, Verdict
from ..core.util import sha256_file, utcnow, write_json
from ..dag.executor import NodeContext, NodeOutcome
from .framework import load_reviews, save_review


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
    ws = ctx.workspace
    reviews, invalid = load_reviews(ws.reviews_dir)
    if invalid:
        # fail closed: a corrupt review artifact could hide CRITICAL/MAJOR
        # findings — it must be repaired or archived by a human, not skipped
        return NodeOutcome(Verdict.FAIL, {"reason": "REVIEW_ARTIFACT_INVALID",
                                          "invalid": invalid})
    entries: list[dict] = []

    claims_path = ws.claims_dir / "claims.yaml"
    graph = load_claims(claims_path)

    for review in reviews:
        for f in review.findings:
            if f.severity not in (Severity.CRITICAL, Severity.MAJOR) or f.disposition is not None:
                continue
            entry = {"finding_id": f.finding_id, "category": f.category,
                     "severity": f.severity.value, "at": utcnow(),
                     "reviewer_prose_copied": False}
            if f.category in ("statistics", "methods", "adversarial"):
                # significance/unsupported claims: retire them from the claim graph
                retired = []
                for c in graph.claims:
                    if c.status in (ClaimStatus.UNSUPPORTED, ClaimStatus.PROPOSED,
                                    ClaimStatus.CONTRADICTED):
                        c.status = ClaimStatus.RETIRED
                        retired.append(c.claim_id)
                entry.update(action="retire_unsupported_claims", retired=retired)
                # verification-based disposition: resolved iff the post-condition
                # demonstrably holds AFTER the pass — CONTRADICTED claims must not
                # slip through with a vacuous "resolved".
                outstanding = [c.claim_id for c in graph.claims
                               if c.status in (ClaimStatus.UNSUPPORTED, ClaimStatus.PROPOSED,
                                               ClaimStatus.CONTRADICTED)]
                if not outstanding:
                    f.disposition = Disposition.RESOLVED
                    f.disposition_reason = ("post-condition verified: no unsupported or proposed "
                                            f"claims remain (retired this pass: {retired})")
                else:
                    entry["outstanding_after"] = outstanding  # stays undisposed → blocks closure
            elif f.category == "citation" or f.category == "adversarial" and "citation" in f.statement:
                # drop unverifiable citations from the manuscript bibliography
                from ..literature.verify import build_references, _audit_entries, parse_bib

                rebuild = build_references(ctx)
                bib = ws.paper_dir / "references.bib"
                final_records, final_findings, _ = _audit_entries(
                    ctx, parse_bib(bib)) if bib.exists() else ([], [], None)
                write_json(ws.reports_dir / "citation_audit_final.json",
                           {"audited_at": utcnow(), "entries": final_records,
                            "findings": final_findings, "post_remediation": True})
                remaining = [x for x in final_findings if x.get("severity") == "CRITICAL"]
                entry.update(action="drop_unverifiable_citation",
                             remaining_critical=len(remaining))
                f.disposition = Disposition.RESOLVED if not remaining else None
                f.disposition_reason = ("false citation removed from generated references "
                                        "and re-audited" if not remaining else None)
            else:
                entry.update(action="deferred", note="no deterministic remediation; needs writer")
            entries.append(entry)

    if entries:
        save_claims(claims_path, graph)
        # persist updated dispositions
        for review in reviews:
            save_review(ws.reviews_dir, review)
    write_json(ws.reports_dir / "remediation_log.json", {"logged_at": utcnow(), "entries": entries})
    unresolved = [e for e in entries if e["action"] == "deferred"]
    verdict = Verdict.PASS if not unresolved else Verdict.DEGRADED
    return NodeOutcome(verdict, {"remediated": len(entries) - len(unresolved),
                                 "deferred": len(unresolved)})


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
