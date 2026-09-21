"""Origin receipts: every write to a protected final-prose path is recorded
with full invocation identity. Feeds closure invariants U11/U12/U13.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core.util import append_jsonl, read_jsonl, sha256_file, utcnow


def record_origin(workspace, *, rel_path: str, abs_path: Path, role: str,
                  backend: dict[str, Any], run_id: str, node_id: str,
                  invocation_receipt: str | None = None) -> dict[str, Any]:
    rec = {
        "recorded_at": utcnow(),
        "rel_path": rel_path,
        "sha256": sha256_file(abs_path) if abs_path.exists() else None,
        "role": role,
        "run_id": run_id,
        "node_id": node_id,
        "backend": backend,
        "invocation_receipt": invocation_receipt,
        "writes_final_prose": True,
    }
    append_jsonl(workspace.receipts_dir / "origin_receipts.jsonl", rec)
    return rec


def origin_receipts(workspace) -> list[dict[str, Any]]:
    return read_jsonl(workspace.receipts_dir / "origin_receipts.jsonl")


def protected_files(workspace, patterns: list[str]) -> list[str]:
    from .firewall import is_protected

    paper_dir = workspace.paper_dir
    out = []
    if paper_dir.exists():
        for p in sorted(paper_dir.rglob("*")):
            if p.is_file():
                rel = str(p.relative_to(workspace.root))
                if is_protected(rel, patterns):
                    out.append(rel)
    return out
