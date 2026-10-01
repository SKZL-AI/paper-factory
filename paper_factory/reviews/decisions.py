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
from .framework import Finding, dedupe_key

DECISIONS_NAME = "decisions.jsonl"


def _key_json(f: Finding) -> str:
    return json.dumps(dedupe_key(f), default=str, sort_keys=True)


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
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return path


def load_decisions(reviews_dir: Path) -> tuple[dict[str, dict], list[str]]:
    """Latest decision per canonical key. Corrupt lines are reported, never
    silently skipped (a broken decision could hide a human veto)."""
    path = reviews_dir / DECISIONS_NAME
    latest: dict[str, dict] = {}
    invalid: list[str] = []
    if not path.exists():
        return latest, invalid
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        try:
            d = json.loads(line)
            if "dedupe_key" not in d or "disposition" not in d:
                raise KeyError("missing dedupe_key/disposition")
            latest[d["dedupe_key"]] = d
        except Exception as exc:
            invalid.append(f"line {i + 1}: {type(exc).__name__}: {exc}")
    return latest, invalid


def apply_decisions(reviews: list, reviews_dir: Path) -> list[str]:
    """Apply durable decisions onto freshly generated findings. Returns
    invalid-decision markers (caller surfaces them as findings)."""
    latest, invalid = load_decisions(reviews_dir)
    for review in reviews:
        for f in review.findings:
            d = latest.get(_key_json(f))
            if not d:
                continue
            try:
                disp = Disposition(d["disposition"])
            except (ValueError, KeyError, TypeError):
                # an entry without a valid disposition is invalid, never a
                # silent skip nor a crash (reviewer A R3-1)
                continue
            if disp in CLOSED_DISPOSITIONS and not (d.get("reason") and d.get("decided_by")):
                continue  # closing without provenance never applies
            f.disposition = disp
            f.disposition_reason = ("durable decision "
                                    f"{d.get('at', '?')}: {d.get('reason', '')}")
            f.resolved_by = d.get("decided_by")
    return [f"DECISION_ARTIFACT_INVALID: {x}" for x in invalid]
