"""P02 Context Mining: ingest visible chat transcripts / research notes as T3
provenance. Hidden chain-of-thought is never recovered — only visible
transcripts, tool traces, summaries and authored notes.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..core.results import Verdict
from ..core.util import sha256_file, utcnow, write_json
from ..dag.executor import NodeContext, NodeOutcome

KEY_PATTERNS = {
    "hypotheses": re.compile(r"\b(hypothes[ie]s|vermutung|we hypothesize|annahme)\b", re.I),
    "decisions": re.compile(r"\b(decid|entscheid|beschlossen|we will|festgelegt)\b", re.I),
    "failed_experiments": re.compile(r"\b(fail|fehlgeschlag|did not work|nicht funktioniert|negative result)\b", re.I),
    "successful_experiments": re.compile(r"\b(success|erfolg|worked|bestätigt|confirmed)\b", re.I),
    "open_questions": re.compile(r"\b(open question|offene frage|todo|unklar|unclear|\?)\s*$", re.I | re.M),
}


def _read_jsonl_messages(path: Path) -> list[dict[str, Any]]:
    msgs = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                msgs.append(obj)
        except json.JSONDecodeError:
            msgs.append({"role": "unknown", "text": line})
    return msgs


def _read_text_messages(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    return [{"role": "document", "text": chunk} for chunk in re.split(r"\n\s*\n", text) if chunk.strip()]


def run_context_mining(ctx: NodeContext) -> NodeOutcome:
    root = ctx.workspace.target_root
    intake_path = ctx.workspace.reports_dir / "intake_report.json"
    chat_paths: list[str] = []
    if intake_path.exists():
        intake = json.loads(intake_path.read_text(encoding="utf-8"))
        chat_paths = [e["path"] for e in intake.get("inputs", {}).get("chats", [])]
    for extra in ctx.config.inputs.chats.extra_paths:
        p = root / extra
        if p.is_dir():
            chat_paths.extend(str(f.relative_to(root)) for f in sorted(p.rglob("*")) if f.is_file())
        elif p.is_file():
            chat_paths.append(extra)

    if not ctx.config.inputs.chats.enabled:
        return NodeOutcome(Verdict.SKIPPED_DEPENDENCY, {"reason": "chat ingestion disabled"})

    extracted: dict[str, Any] = {
        "mined_at": utcnow(),
        "tier": "T3",
        "hidden_chain_of_thought": "forbidden_and_not_attempted",
        "sources": [],
        "chronology": [],
        "hypotheses": [], "decisions": [], "failed_experiments": [],
        "successful_experiments": [], "open_questions": [], "terminology": [],
    }
    for rel in chat_paths:
        path = root / rel
        if not path.exists():
            continue
        msgs = (_read_jsonl_messages(path) if path.suffix == ".jsonl" else _read_text_messages(path))
        src = {"path": rel, "sha256": sha256_file(path), "messages": len(msgs)}
        extracted["sources"].append(src)
        for m in msgs:
            text = str(m.get("text", ""))
            ts = m.get("ts") or m.get("timestamp")
            if ts:
                extracted["chronology"].append({"ts": ts, "source": rel,
                                                "preview": text[:160]})
            for key, pat in KEY_PATTERNS.items():
                if pat.search(text):
                    extracted[key].append({"source": rel, "excerpt": text[:300]})
    out = ctx.workspace.context_dir / "context_summary.json"
    write_json(out, extracted)
    detail = {"sources": len(extracted["sources"]),
              "chronology_entries": len(extracted["chronology"])}
    if not extracted["sources"]:
        return NodeOutcome(Verdict.DEGRADED, {**detail, "reason": "no chat/history artifacts found"})
    return NodeOutcome(Verdict.PASS, detail)
