"""Durable author/operator decisions (real-pilot-3 finding, 2026-10-01).

Review nodes regenerate their review JSONs on every run — a disposition
hand-set (or delegated-set) on a Finding was silently wiped by the next run,
reopening an already-decided MAJOR (the 7.4 AUTHOR_DECISION died this way
twice). Decisions therefore live in an append-only store that survives
regeneration:

    reviews/decisions.jsonl   (one JSON object per line, never rewritten)

A decision binds the finding by its CANONICAL dedupe_key (kind + section +
evidence identity — not the prose string and not the per-run finding_id),
so it applies to the same underlying issue in every future run, across all
reviewer duplicates (GAP-010). Latest decision for a key wins; nothing is
ever deleted.

Closing dispositions still require provenance (A-G3): a decision without
decided_by + reason is invalid and is surfaced, not applied.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..core.results import CLOSED_DISPOSITIONS, Disposition
from ..core.util import utcnow
from .framework import Finding, _stmt_hash, dedupe_key, legacy_dedupe_key

DECISIONS_NAME = "decisions.jsonl"


def _key_json(f: Finding) -> str:
    return json.dumps(dedupe_key(f), default=str, sort_keys=True)


def _legacy_key_json(f: Finding) -> str:
    return json.dumps(legacy_dedupe_key(f), default=str, sort_keys=True)


def record_decision(reviews_dir: Path, finding: Finding, *,
                    disposition: Disposition, reason: str, decided_by: str,
                    evidence: dict[str, Any] | None = None) -> Path:
    """Append a decision. Closing dispositions REQUIRE decided_by + reason
    (a bare claim is not evidence)."""
    if disposition in CLOSED_DISPOSITIONS and not (reason.strip() and decided_by.strip()):
        raise ValueError("closing decision requires decided_by + reason")
    path = reviews_dir / DECISIONS_NAME
    reviews_dir.mkdir(parents=True, exist_ok=True)
    entry = {
        "at": utcnow(),
        "dedupe_key": _key_json(finding),
        "disposition": disposition.value,
        "reason": reason,
        "decided_by": decided_by,
        "evidence": evidence or {},
        "finding_id_at_decision": finding.finding_id,
        "kind": finding.kind,
        "statement_head": finding.statement[:120],
        # full-statement hash: statement_head is truncated at 120 chars, so it
        # cannot prove identity for longer statements (reviewer A R4 T-1)
        "statement_hash": _stmt_hash(finding.statement),
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return path


def load_decisions(reviews_dir: Path) -> tuple[dict[str, dict], list[str], set[str]]:
    """Latest decision per canonical key, plus the set of legacy keys that any
    line in the log has already migrated (across ALL lines, not just the
    latest-per-key view — a shadowed receipt must still count, reviewer A
    C-1/M-2). Corrupt lines are reported, never silently skipped (a broken
    decision could hide a human veto)."""
    path = reviews_dir / DECISIONS_NAME
    latest: dict[str, dict] = {}
    invalid: list[str] = []
    migrated_from: set[str] = set()
    if not path.exists():
        return latest, invalid, migrated_from
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        try:
            d = json.loads(line)
            if "dedupe_key" not in d or "disposition" not in d:
                raise KeyError("missing dedupe_key/disposition")
            latest[d["dedupe_key"]] = d
            if d.get("migrated_from_legacy_key"):
                migrated_from.add(d["migrated_from_legacy_key"])
        except Exception as exc:
            invalid.append(f"line {i + 1}: {type(exc).__name__}: {exc}")
    return latest, invalid, migrated_from


def _apply(f: Finding, d: dict) -> bool:
    """Apply one decision entry to one finding. Returns True when applied."""
    try:
        disp = Disposition(d["disposition"])
    except (ValueError, KeyError, TypeError):
        # an entry without a valid disposition is invalid, never a
        # silent skip nor a crash (reviewer A R3-1)
        return False
    if disp in CLOSED_DISPOSITIONS and not (d.get("reason") and d.get("decided_by")):
        return False  # closing without provenance never applies
    f.disposition = disp
    f.disposition_reason = ("durable decision "
                            f"{d.get('at', '?')}: {d.get('reason', '')}")
    f.resolved_by = d.get("decided_by")
    return True


def _norm_text(s: str) -> str:
    return " ".join(str(s).lower().split())


def _statement_matches(candidate: Finding, d: dict) -> bool | None:
    """Does the candidate finding look like the issue the decision was taken
    on? Legacy keys are claim_refs-weak (reviewer A M-1): the stored
    statement evidence is the only link back to the ORIGINAL issue.
    Preference order (reviewer A R4 T-1): a full statement_hash proves
    identity; a statement_head proves it only when it was NOT truncated
    (len < 120 — a truncated head is a shared prefix, not an identity);
    otherwise unverifiable.
    Returns True/False, or None when identity cannot be proven."""
    h = d.get("statement_hash")
    if h:
        return _stmt_hash(candidate.statement) == h
    head = d.get("statement_head")
    if not head:
        return None
    head_s = str(head)
    if len(head_s) >= 120:
        return None  # possibly truncated — a shared prefix is not identity
    return _norm_text(candidate.statement) == _norm_text(head_s)


def apply_decisions(reviews: list, reviews_dir: Path) -> list[str]:
    """Apply durable decisions onto freshly generated findings. Returns
    invalid-decision markers (caller surfaces them as findings).

    Legacy migration (post-pilot-01 release audit): decisions recorded under
    the pre-hardening dedupe_key schema (claim_refs-only identity, no
    statement discrimination) are rebound ONLY when the legacy key matches
    exactly one current issue AND the stored statement_head confirms the
    candidate IS the original issue — an ambiguous or unverifiable legacy key
    is surfaced as DECISION_KEY_AMBIGUOUS and never applied (no false-close
    inheritance). A migration receipt is appended only when the target key is
    not already governed by a different (e.g. newer human) decision, and a
    legacy key that any log line already migrated is never re-migrated
    (reviewer A C-1/M-2: no receipt growth, no shadowing)."""
    latest, invalid, already_migrated = load_decisions(reviews_dir)
    markers = [f"DECISION_ARTIFACT_INVALID: {x}" for x in invalid]
    if not latest:
        return markers
    all_findings = [f for review in reviews for f in review.findings]
    migrated: list[dict] = []
    for key, d in latest.items():
        applied = False
        for f in all_findings:
            if _key_json(f) == key:
                applied = _apply(f, d) or applied
        if applied:
            continue
        if d.get("migrated_from_legacy_key"):
            continue  # receipts never take the legacy path themselves
        if key in already_migrated:
            continue  # legacy key already superseded by its migration receipt
        # legacy rebind: match against the OLD schema; duplicates of the same
        # underlying issue (folded into several reviews) share ONE new key
        candidates = [f for f in all_findings if _legacy_key_json(f) == key]
        distinct = {_key_json(f): f for f in candidates}
        confirmed = [f for f in distinct.values()
                     if _statement_matches(f, d) is True]
        unverifiable = any(_statement_matches(f, d) is None
                           for f in distinct.values())
        if len(distinct) == 1 and confirmed:
            new_key = next(iter(distinct))
            if new_key in latest:
                # a different (newer) decision already governs the target
                # issue — the legacy entry must not shadow it (C-1)
                continue
            if any(_apply(f, d) for f in candidates):
                migrated.append({"from": key, "to": new_key, "decision": d})
        elif distinct:
            why = (f"matches {len(distinct)} distinct current findings"
                   if len(distinct) > 1 else
                   ("carries no statement_head — original issue unverifiable"
                    if unverifiable else
                    "statement_head does not match the candidate — "
                    "different issue than the one decided"))
            markers.append(
                f"DECISION_KEY_AMBIGUOUS: legacy decision key {why} — "
                f"NOT applied (recorded {d.get('at', '?')}, "
                f"kind={d.get('kind', '?')}); re-record the decision "
                "against the current schema")
    if migrated:
        # persist the migration append-only: future runs bind the new key
        # directly; the legacy entry stays in the log (correction by addition)
        path = reviews_dir / DECISIONS_NAME
        with path.open("a", encoding="utf-8") as fh:
            for m in migrated:
                d = m["decision"]
                fh.write(json.dumps({
                    "at": utcnow(),
                    "dedupe_key": m["to"],
                    "disposition": d["disposition"],
                    "reason": d.get("reason", ""),
                    "decided_by": d.get("decided_by", ""),
                    "evidence": d.get("evidence", {}),
                    "kind": d.get("kind"),
                    "statement_head": d.get("statement_head", ""),
                    "statement_hash": d.get("statement_hash"),
                    "migrated_from_legacy_key": m["from"],
                }, ensure_ascii=False) + "\n")
    return markers
