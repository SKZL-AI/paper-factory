"""Map external verification findings into PF-owned review findings (plan §3, Phase 6).

PF stays the owner of review-finding identity, severity, and closure semantics:
`reviews.framework.Finding` is the durable artifact, `unresolved_blocking` and
`dedupe_key` keep working over mapped findings. The external identity
(statement_hash, backend name/version) is preserved in `details` — never in a
PF required field — so provider semantics cannot leak into the review plane.

Mapping rules (documented fallbacks, never invented values):
- severity: 1:1, same enum (`core.results.Severity`).
- category: `vfinding.kind` when it is one of the allowed review categories
  (methods | statistics | novelty | citation | reproducibility | adversarial |
  language | compliance — the documented value set of `Finding.category`);
  otherwise the documented fallback `compliance` with the original kind kept in
  `details["category_fallback"]`. `Finding.kind` always carries the raw
  external kind.
- claim_refs: the review `Finding` has a native `claim_refs` field — it is used.
- Duplicates (same statement_hash + same backend): folded into ONE finding,
  `details["duplicate_count"]` = n; claim/evidence refs are unioned so nothing
  is silently dropped.
- Conflict (same statement_hash + same backend, but differing severity/kind):
  ALL findings are kept, each marked `details["conflict"] = True` — visible,
  never silently merged (durable-decision hardening: weak identities must not
  false-close each other).
- Distinct statement_hash: always distinct findings, even for one backend.
"""
from __future__ import annotations

from ..reviews.framework import Finding
from .contract import BackendIdentity, VerificationFinding

# Documented value set of Finding.category (reviews/framework.py:19).
_ALLOWED_CATEGORIES = frozenset(
    {"methods", "statistics", "novelty", "citation", "reproducibility",
     "adversarial", "language", "compliance"}
)

# Documented fallback when the external kind is not an allowed review category.
_FALLBACK_CATEGORY = "compliance"


def _safe_id_part(s: str) -> str:
    return "".join(c if (c.isalnum() or c in "._-") else "_" for c in s)


def _external_details(backend: BackendIdentity, vf: VerificationFinding) -> dict:
    return {
        "external": {
            "backend": backend.name,
            "backend_kind": backend.kind,
            "backend_version": backend.version,
            "statement_hash": vf.statement_hash,
        },
    }


def map_external_findings(
    vfindings: list[VerificationFinding],
    backend: BackendIdentity,
) -> list[Finding]:
    """Map external `VerificationFinding`s to PF-owned review `Finding`s.

    Returns findings in stable input order (first occurrence of each group).
    Duplicates fold, conflicts stay visible, everything else maps 1:1.
    """
    groups: dict[tuple[str, str], list[VerificationFinding]] = {}
    for vf in vfindings:
        key = (backend.name, vf.statement_hash)
        groups.setdefault(key, []).append(vf)

    out: list[Finding] = []
    for (backend_name, statement_hash), members in groups.items():
        first = members[0]
        same_shape = all(
            m.severity == first.severity and m.kind == first.kind for m in members
        )
        conflict = len(members) > 1 and not same_shape

        if conflict:
            # Same statement_hash + same backend, different severity/kind:
            # keep ALL findings, visibly marked — never merge silently.
            for i, vf in enumerate(members, start=1):
                out.append(_to_finding(backend, vf, backend_name, statement_hash,
                                       suffix=f"-{i}", conflict=True))
        else:
            # Duplicate fold: union claim/evidence refs, count occurrences.
            claim_refs = sorted({ref for m in members for ref in m.claim_refs})
            evidence_refs = list(dict.fromkeys(
                ev.evidence_id for m in members for ev in m.evidence_refs
            ))
            details = _external_details(backend, first)
            if len(members) > 1:
                details["duplicate_count"] = len(members)
            out.append(_to_finding(
                backend, first, backend_name, statement_hash,
                claim_refs=claim_refs, evidence_refs=evidence_refs, details=details,
            ))
    return out


def _to_finding(
    backend: BackendIdentity,
    vf: VerificationFinding,
    backend_name: str,
    statement_hash: str,
    suffix: str = "",
    conflict: bool = False,
    claim_refs: list[str] | None = None,
    evidence_refs: list[str] | None = None,
    details: dict | None = None,
) -> Finding:
    kind = vf.kind
    category = kind if kind in _ALLOWED_CATEGORIES else _FALLBACK_CATEGORY
    details = dict(details) if details is not None else _external_details(backend, vf)
    if category != kind:
        details["category_fallback"] = kind
    if conflict:
        details["conflict"] = True
    return Finding(
        finding_id=f"VF-{_safe_id_part(backend_name)}-{statement_hash[:16]}{suffix}",
        reviewer=f"verification:{_safe_id_part(backend_name)}",
        severity=vf.severity,
        category=category,
        statement=vf.statement,
        evidence_refs=evidence_refs if evidence_refs is not None
        else [ev.evidence_id for ev in vf.evidence_refs],
        claim_refs=claim_refs if claim_refs is not None else list(vf.claim_refs),
        kind=kind,
        details=details,
    )
