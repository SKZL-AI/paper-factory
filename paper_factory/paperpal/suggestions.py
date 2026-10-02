"""Paperpal suggestion dispositions (Phase 1, release 2026-10-02).

Every captured Paperpal suggestion gets a stable id, a provenance-bound
record and a final disposition. The state lives append-only in
`<project>/.paper-factory/paperpal/suggestions.jsonl` — a disposition is
never rewritten, a correction appends a newer entry for the same id.

Dispositions (closed set):
  APPLIED_SAFE                      mechanical fix, invariance gates passed
  APPLIED_SEMANTICALLY_VERIFIED     semantic rewrite, dual-review approved
  REJECTED_NO_IMPROVEMENT
  REJECTED_SCIENTIFIC_RISK
  REJECTED_EVIDENCE_CONFLICT
  REJECTED_STYLE_ONLY
  NOT_APPLICABLE

Invariance gate for auto-apply (SAFE): the change must not alter any number,
citation, math token or protected scientific term — computed over the actual
before→after pair, never assumed from the category.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from ..core.util import utcnow

DISPOSITIONS = (
    "APPLIED_SAFE",
    "APPLIED_SEMANTICALLY_VERIFIED",
    "REJECTED_NO_IMPROVEMENT",
    "REJECTED_SCIENTIFIC_RISK",
    "REJECTED_EVIDENCE_CONFLICT",
    "REJECTED_STYLE_ONLY",
    "NOT_APPLICABLE",
)

_NUMBER = re.compile(r"\d")
_CITATION = re.compile(r"\[\d|draftref|arXiv|doi|et al", re.I)
_MATH = re.compile(r"[=≈≤≥∑∏√±×÷]|\$")
# scientific terms whose alteration always forces human/reviewer judgment
_PROTECTED = re.compile(
    r"(?i)\b(claim|evidence|proof|proven|significant|hypothes|conclud|"
    r"result|baseline|ablation|ablat|outperform|state-of-the-art|sota|"
    r"limitation|caveat|assumption|guarantee)\b")


def suggestion_id(category: str, context: str, before: str, after: str) -> str:
    """Stable identity across runs: category + normalized context + pair."""
    norm = " ".join(f"{category}|{context}|{before}|{after}".lower().split())
    return "ps-" + hashlib.sha256(norm.encode()).hexdigest()[:12]


def invariance_report(before: str, after: str) -> dict[str, Any]:
    """What the change touches. Any True gate blocks APPLIED_SAFE."""
    def nums(s: str) -> list[str]:
        return re.findall(r"\d+(?:[.,]\d+)*", s)

    def cites(s: str) -> list[str]:
        return re.findall(r"\[[\d,\s]+\]", s)

    def math_tokens(s: str) -> list[str]:
        return re.findall(r"[=≈≤≥∑∏√±×÷$]|[A-Za-z]_[a-zA-Z]+", s)

    return {
        "numbers_changed": nums(before) != nums(after),
        "citations_changed": cites(before) != cites(after),
        "math_changed": math_tokens(before) != math_tokens(after),
        "protected_terms_changed": (
            sorted(set(_PROTECTED.findall(before.lower())))
            != sorted(set(_PROTECTED.findall(after.lower())))),
        "before": before,
        "after": after,
    }


def auto_safe_ok(before: str, after: str) -> tuple[bool, dict[str, Any]]:
    rep = invariance_report(before, after)
    blocked = {k: v for k, v in rep.items()
               if k.endswith("_changed") and v}
    return (not blocked), rep


def append_disposition(path: Path, record: dict[str, Any]) -> None:
    if record.get("disposition") not in DISPOSITIONS:
        raise ValueError(f"unknown disposition: {record.get('disposition')}")
    if not record.get("rationale"):
        raise ValueError("disposition requires a rationale")
    record = dict(record, at=utcnow())
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_dispositions(path: Path) -> dict[str, dict[str, Any]]:
    """Latest disposition per suggestion_id (append-only log)."""
    latest: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return latest
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        d = json.loads(line)
        if "suggestion_id" not in d or "disposition" not in d:
            raise ValueError(f"corrupt disposition line {i + 1}")
        latest[d["suggestion_id"]] = d
    return latest


_WS = re.compile(r"\s+")


def _norm(s: str) -> str:
    return _WS.sub(" ", s).strip()


def _norm_with_map(text: str) -> tuple[str, list[int]]:
    """Whitespace-collapsed copy + map: normalized index → original index."""
    out: list[str] = []
    idx_map: list[int] = []
    prev_ws = False
    for i, ch in enumerate(text):
        if ch.isspace():
            if not prev_ws:
                out.append(" ")
                idx_map.append(i)
            prev_ws = True
        else:
            out.append(ch)
            idx_map.append(i)
            prev_ws = False
    return "".join(out), idx_map


def locate_change(text: str, context: str, before: str) -> tuple[int, int]:
    """Locate (context, before) in the draft text. The DOCX/pane roundtrip
    collapses newlines; the draft keeps them — so matching runs on a
    whitespace-normalized view with an index map back to the original text.
    Returns (start, end) of `before` in ORIGINAL coordinates. Raises on
    not-found or ambiguity — never guess."""
    if not before.strip():
        raise ValueError("empty before-span")
    ntext, nmap = _norm_with_map(text)
    ctx = _norm(context)
    needle = _norm(before)
    # context probe (pane cards truncate long sentences — tolerate prefix)
    idx = -1
    ctx_len = 0
    for cut in range(len(ctx), max(20, int(len(ctx) * 0.6)) - 1, -1):
        probe = ctx[:cut]
        hits = [m.start() for m in re.finditer(re.escape(probe), ntext)]
        if len(hits) == 1:
            idx = hits[0]
            ctx_len = len(probe)
            break
        if len(hits) > 1:
            break  # ambiguous context — refuse
    if idx < 0:
        raise ValueError("context not found or ambiguous")
    window = ntext[idx:idx + ctx_len + len(needle) + 200]
    matches = [m.start() for m in re.finditer(re.escape(needle), window)]
    if len(matches) != 1:
        raise ValueError(f"before-span not unique in context ({len(matches)})")
    nstart = idx + matches[0]
    nend = nstart + len(needle)
    return nmap[nstart], (nmap[nend - 1] + 1 if nend - 1 < len(nmap)
                          else len(text))


def apply_to_markdown(text: str, context: str, before: str, after: str
                      ) -> tuple[str, dict[str, Any]]:
    """Apply exactly one dispositioned change. Fails closed: no match or
    ambiguity → exception, caller records REJECTED/NOT_APPLICABLE instead."""
    ok, inv = auto_safe_ok(before, after)
    start, end = locate_change(text, context, before)
    new = text[:start] + after + text[end:]
    receipt = {
        "before": before, "after": after,
        "span": [start, end],
        "invariance": {k: v for k, v in inv.items() if k.endswith("_changed")},
        "auto_safe_ok": ok,
    }
    return new, receipt
