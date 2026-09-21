"""P01 Intake: detect the input mode and register what the project carries.

Modes: CODE_ONLY, DATA_ONLY, DRAFT_ASSISTED, MIXED_EVIDENCE.
A draft is never authoritative — it is T4 prose at most.
"""
from __future__ import annotations

from pathlib import Path

from ..core.results import Verdict
from ..core.util import sha256_file, utcnow, write_json
from ..dag.executor import NodeContext, NodeOutcome

CODE_EXT = {".py", ".r", ".jl", ".ipynb", ".sh", ".c", ".cpp", ".rs", ".js", ".ts"}
DATA_EXT = {".csv", ".tsv", ".parquet", ".arrow", ".json", ".jsonl", ".db", ".sqlite", ".sqlite3", ".duckdb"}
DRAFT_EXT = {".tex", ".md"}
BIB_EXT = {".bib"}
CHAT_HINTS = ("chat", "transcript", "handoff", "session", "history", "export")


def _scan(root: Path) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {"code": [], "data": [], "drafts": [], "bib": [], "chats": []}
    skip_dirs = {".git", ".paper-factory", "node_modules", "__pycache__", ".venv", "venv"}
    for p in sorted(root.rglob("*")):
        if not p.is_file() or any(part in skip_dirs for part in p.parts):
            continue
        rel = str(p.relative_to(root))
        ext = p.suffix.lower()
        lower = rel.lower()
        if any(h in lower for h in CHAT_HINTS) and ext in {".jsonl", ".json", ".md", ".txt"}:
            found["chats"].append(rel)
        elif ext in CODE_EXT:
            found["code"].append(rel)
        elif ext in DATA_EXT:
            found["data"].append(rel)
        elif ext in BIB_EXT:
            found["bib"].append(rel)
        elif ext in DRAFT_EXT and any(
            k in lower for k in ("draft", "paper", "manuscript", "preprint")
        ):
            found["drafts"].append(rel)
    return found


def classify(found: dict[str, list[str]], requested: str = "auto") -> str:
    if requested != "auto":
        return requested
    has_code = bool(found["code"])
    # results/ are experiment OUTPUTS (derived); data/ + databases are the DATA track
    has_results = any(p.startswith("results/") for p in found["data"])
    has_data = any(not p.startswith("results/") for p in found["data"])
    has_draft = bool(found["drafts"])
    has_chats = bool(found["chats"])
    has_bib = bool(found["bib"])
    if has_draft and (has_code or has_data or has_results):
        return "MIXED_EVIDENCE"
    if has_code and has_data:
        return "MIXED_EVIDENCE"
    if has_chats and (has_code or has_data or has_results or has_draft):
        return "MIXED_EVIDENCE"
    if has_bib and (has_code or has_data or has_results):
        return "MIXED_EVIDENCE"
    if has_draft:
        return "DRAFT_ASSISTED"
    if has_code:
        return "CODE_ONLY"
    if has_data or has_results:
        return "DATA_ONLY"
    return "EMPTY"


def run_intake(ctx: NodeContext) -> NodeOutcome:
    root = ctx.workspace.target_root
    found = _scan(root)
    mode = classify(found, ctx.config.inputs.mode)
    hashed = {
        kind: [{"path": rel, "sha256": sha256_file(root / rel)} for rel in paths]
        for kind, paths in found.items()
    }
    report = {
        "detected_at": utcnow(),
        "target_root": str(root),
        "input_mode": mode,
        "inputs": hashed,
        "draft_is_authoritative": False,
        "notes": "Drafts and chat artifacts are provenance (T3/T4), never empirical evidence.",
    }
    write_json(ctx.workspace.reports_dir / "intake_report.json", report)
    if mode == "EMPTY":
        return NodeOutcome(Verdict.FAIL, {"reason": "no usable inputs found", "mode": mode})
    return NodeOutcome(Verdict.PASS, {"input_mode": mode,
                                      "counts": {k: len(v) for k, v in found.items()}})
