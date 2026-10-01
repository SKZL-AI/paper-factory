"""P31 Paperpal bridge. No API integration exists on this machine (checked);
default is the manual bridge: outbox → human → inbox, then semantic diff.
Absence is HUMAN_REQUIRED, never PASS-by-default.

Provenance honesty: an inbox artifact is only external Paperpal evidence when
it is explicitly declared as such (sidecar `<name>.provenance.json` with
{"source": "paperpal"} or a first-lines header `source: paperpal`). Anything
undeclared is an operator check — valuable, but a weaker evidence class, and
never reported as an external Paperpal result.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..core.results import Verdict
from ..core.util import sha256_file, utcnow, write_json
from ..dag.executor import NodeContext, NodeOutcome

ACTION_REQUIRED = """# PAPERPAL_ACTION_REQUIRED

Paper Factory has no usable Paperpal API integration on this machine.

## What to do
1. Take the manuscript candidate from `outbox/` (file listed below).
2. Run Paperpal checks: language, references, submission readiness.
3. Put the Paperpal report (and any edited manuscript) into `inbox/`.
4. Resume: `paper-factory complete --resume`

## Rules
- Default mode is report/check — Paperpal is NOT the authoritative final writer.
- If you let Paperpal rewrite prose, say so: it counts as `external_prose_origin`
  and forces a semantic diff (claim strength, causality, numbers, limitations).
"""


_SOURCE_HEADER = re.compile(r"(?im)^\s*source\s*:\s*([a-z0-9_-]+)\s*$")


def _classify_inbox_item(path: Path) -> str:
    """Fail-closed provenance: undeclared items are operator checks, never
    external Paperpal evidence. An external claim must be explicit."""
    sidecar = path.with_name(path.name + ".provenance.json")
    if sidecar.exists():
        try:
            src = str(json.loads(sidecar.read_text(encoding="utf-8")).get("source", ""))
        except (json.JSONDecodeError, OSError):
            src = ""
        return "external_paperpal_declared" if src.strip().lower() == "paperpal" else "operator_check"
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:2000]
    except OSError:
        return "operator_check"
    m = _SOURCE_HEADER.search(head)
    if m:
        return "external_paperpal_declared" if m.group(1).lower() == "paperpal" else "operator_check"
    return "operator_check"


def run_paperpal(ctx: NodeContext) -> NodeOutcome:
    outbox = ctx.workspace.paperpal_outbox
    inbox = ctx.workspace.paperpal_inbox
    mode = ctx.config.paperpal.mode

    if mode == "disabled":
        return NodeOutcome(Verdict.DEGRADED, {"reason": "paperpal disabled by config"})
    if mode == "auto" or mode == "api":
        # No supported API was found during inventory — fall through to bridge.
        pass

    candidate = ctx.workspace.paper_dir / "main.tex"
    marker = outbox / "PAPERPAL_ACTION_REQUIRED.md"
    if not candidate.exists():
        return NodeOutcome(Verdict.DEGRADED, {"reason": "no manuscript candidate yet"})
    out_candidate = outbox / "main.tex"
    if not out_candidate.exists():
        out_candidate.write_text(candidate.read_text(encoding="utf-8"), encoding="utf-8")
    marker.write_text(ACTION_REQUIRED + f"\n\n- outbox file: `{out_candidate.name}`\n- created: {utcnow()}\n",
                      encoding="utf-8")

    inbox_items = sorted(p for p in inbox.glob("*") if p.is_file()
                         and not p.name.endswith(".provenance.json")) if inbox.exists() else []
    item_classes = {p.name: _classify_inbox_item(p) for p in inbox_items}
    evidence_class = ("external_paperpal_declared"
                      if any(c == "external_paperpal_declared" for c in item_classes.values())
                      else ("operator_check" if item_classes else "none"))
    state: dict[str, Any] = {"checked_at": utcnow(), "outbox": out_candidate.name,
                             "inbox_items": [p.name for p in inbox_items],
                             "item_classes": item_classes,
                             "item_sha256": {p.name: sha256_file(p) for p in inbox_items},
                             "evidence_class": evidence_class}
    if mode == "word_auto":
        # versioned DOCX outbox (figures/tables/arxiv-style) + adapter
        # receipts; the Word session itself is driven by the orchestrating
        # agent through scripts/run_paperpal_word.py — P31 PASSes only when
        # real Paperpal-declared inbox evidence exists (bridge unchanged).
        # NOTE (reviewer B R3-F5): with a broken renderer the state records
        # docx_outbox_error and NO docx_outbox — a PASS then still requires
        # external inbox evidence (which is bound to ITS staged DOCX via
        # sidecar sha256); a fresh build failure never fabricates evidence.
        from .docx_outbox import build_docx_outbox
        try:
            prov = build_docx_outbox(ctx.workspace, ctx.run_id)
            if prov:
                state["docx_outbox"] = prov["docx"]["name"]
                state["docx_outbox_sha256"] = prov["docx"]["sha256"]
                state["docx_outbox_source_sha256"] = prov["source"]["sha256"]
        except Exception as e:  # a broken renderer must degrade, not crash P31
            state["docx_outbox_error"] = str(e)
    write_json(ctx.workspace.reports_dir / "paperpal_state.json", state)
    if evidence_class == "external_paperpal_declared":
        return NodeOutcome(Verdict.PASS, {"bridge": "manual",
                                          "evidence_class": evidence_class,
                                          "inbox_items": len(inbox_items),
                                          "semantic_diff_required": True})
    if evidence_class == "operator_check":
        return NodeOutcome(Verdict.DEGRADED,
                           {"reason": "manual operator check only — no external Paperpal evidence",
                            "evidence_class": evidence_class,
                            "inbox_items": len(inbox_items)})
    return NodeOutcome(Verdict.HUMAN_REQUIRED,
                       {"reason": "paperpal manual bridge awaiting inbox delivery",
                        "action_file": str(marker)})
