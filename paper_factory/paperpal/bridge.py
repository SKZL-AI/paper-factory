"""P31 Paperpal bridge. No API integration exists on this machine (checked);
default is the manual bridge: outbox → human → inbox, then semantic diff.
Absence is HUMAN_REQUIRED, never PASS-by-default.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core.results import Verdict
from ..core.util import utcnow, write_json
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

    inbox_items = list(inbox.glob("*")) if inbox.exists() else []
    state = {"checked_at": utcnow(), "outbox": out_candidate.name,
             "inbox_items": [p.name for p in inbox_items]}
    write_json(ctx.workspace.reports_dir / "paperpal_state.json", state)
    if inbox_items:
        return NodeOutcome(Verdict.PASS, {"bridge": "manual", "inbox_items": len(inbox_items),
                                          "semantic_diff_required": True})
    return NodeOutcome(Verdict.HUMAN_REQUIRED,
                       {"reason": "paperpal manual bridge awaiting inbox delivery",
                        "action_file": str(marker)})
