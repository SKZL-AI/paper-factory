"""Issue ledger (L15): every issue found — by reviewers or ourselves — is
either fixed immediately or tracked here with reason and priority. Nothing is
silently dropped.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .util import append_jsonl, read_jsonl, utcnow


def record_issue(state_dir: Path, *, title: str, severity: str, found_by: str,
                 action: str,  # "fixed_now" | "tracked"
                 reason: str, priority: str = "medium",
                 source: str | None = None) -> dict[str, Any]:
    entries = read_jsonl(state_dir / "issue_ledger.jsonl")
    entry = {
        "issue_id": f"ISS-{len(entries) + 1:03d}",
        "recorded_at": utcnow(),
        "title": title,
        "severity": severity,
        "found_by": found_by,
        "action": action,
        "reason": reason,
        "priority": priority,
        "source": source,
        "status": "open" if action == "tracked" else "fixed",
    }
    append_jsonl(state_dir / "issue_ledger.jsonl", entry)
    return entry


def resolve_issue(state_dir: Path, issue_id: str, resolution: str) -> None:
    entries = read_jsonl(state_dir / "issue_ledger.jsonl")
    for e in entries:
        if e["issue_id"] == issue_id and e["status"] == "open":
            e["status"] = "fixed"
            e["resolved_at"] = utcnow()
            e["resolution"] = resolution
    path = state_dir / "issue_ledger.jsonl"
    parked = path.with_suffix(f".jsonl.v1.{utcnow().replace(':', '')}")
    if path.exists():
        path.rename(parked)
    for e in entries:
        append_jsonl(path, e)


def open_issues(state_dir: Path) -> list[dict[str, Any]]:
    return [e for e in read_jsonl(state_dir / "issue_ledger.jsonl") if e["status"] == "open"]
