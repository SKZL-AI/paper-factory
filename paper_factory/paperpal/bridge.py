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


def _word_report_content_valid(item: Path) -> bool:
    """Content validation for word_auto JSON reports: a report whose checks
    all carry an 'error' (or which has no checks at all) is a hollow artifact
    — real Paperpal evidence needs at least one check with actual results.
    Only applied to JSON reports with a 'checks' object; plain-text reports
    are unaffected."""
    if item.suffix.lower() != ".json":
        return True
    try:
        d = json.loads(item.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    checks = d.get("checks")
    if not isinstance(checks, dict):
        return True  # not a word-session report shape — provenance decides
    if not checks:
        return False
    return any(isinstance(c, dict) and "error" not in c for c in checks.values())


def _norm_sha(v: Any) -> str | None:
    """Normalize a sha256 for comparison (case/whitespace-tolerant; reviewer
    B5). Non-strings are coerced; a missing value stays None."""
    if v is None:
        return None
    return str(v).strip().lower()


def _bound_staged_sha(item: Path) -> str | None:
    """The staged-DOCX sha256 an inbox item is bound to (provenance sidecar),
    or None when the item carries no exact-artifact binding."""
    sidecar = item.with_name(item.name + ".provenance.json")
    if not sidecar.exists():
        return None
    try:
        v = json.loads(sidecar.read_text(encoding="utf-8")).get("docx_sha256_staged")
    except (json.JSONDecodeError, OSError):
        return None
    return _norm_sha(v)


def _check_artifact_binding(inbox_items: list[Path], item_classes: dict[str, str],
                            current_docx_sha: str | None
                            ) -> tuple[str | None, dict[str, str]]:
    """Exact-artifact binding (post-pilot-01 audit): external Paperpal evidence
    must bind to the CURRENT staged DOCX. `content was identical` is not
    evidence — only the hash chain manuscript→docx→staged→inbox counts.

    Returns (aggregate, per_item): aggregate is None when there is nothing to
    bind (no external evidence), else exact | stale | unbound | unverifiable;
    per_item keeps each external item's binding visible (reviewer B4: an
    exact+stale mix must not hide the stale item)."""
    external = [p for p in inbox_items
                if item_classes.get(p.name) == "external_paperpal_declared"]
    if not external:
        return None, {}
    current = _norm_sha(current_docx_sha)
    if not current:
        # renderer failed: the current artifact does not exist, so NO inbox
        # evidence can be verified against it (reviewer B R3-F5)
        return "unverifiable", {p.name: "unverifiable" for p in external}
    per_item: dict[str, str] = {}
    for p in external:
        sha = _bound_staged_sha(p)
        per_item[p.name] = ("exact" if sha == current
                            else ("stale" if sha else "unbound"))
    if any(v == "exact" for v in per_item.values()):
        aggregate = "exact"
    elif any(v == "stale" for v in per_item.values()):
        aggregate = "stale"  # bound to an older render
    else:
        aggregate = "unbound"  # e.g. header-declared text without a sidecar sha
    return aggregate, per_item


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
    # content validation for word-session JSON reports: a report whose checks
    # all errored is a hollow artifact, not Paperpal evidence (observed
    # 2026-10-02: pane tab-click failure delivered an error-only report that
    # would otherwise have passed P31 on provenance+binding alone)
    invalid_items = [p.name for p in inbox_items
                     if item_classes[p.name] == "external_paperpal_declared"
                     and not _word_report_content_valid(p)]
    for name in invalid_items:
        item_classes[name] = "invalid_hollow_report"
    evidence_class = ("external_paperpal_declared"
                      if any(c == "external_paperpal_declared" for c in item_classes.values())
                      else ("operator_check" if any(c == "operator_check"
                                                    for c in item_classes.values())
                            else ("invalid" if invalid_items else
                                  ("operator_check" if item_classes else "none"))))
    state: dict[str, Any] = {"checked_at": utcnow(), "run_id": ctx.run_id,
                             "outbox": out_candidate.name,
                             "inbox_items": [p.name for p in inbox_items],
                             "item_classes": item_classes,
                             "invalid_items": invalid_items,
                             "item_sha256": {p.name: sha256_file(p) for p in inbox_items},
                             "evidence_class": evidence_class}
    if mode == "word_auto":
        # versioned DOCX outbox (figures/tables/arxiv-style) + adapter
        # receipts; the Word session itself is driven by the orchestrating
        # agent through scripts/run_paperpal_word.py — P31 PASSes only when
        # real Paperpal-declared inbox evidence exists AND that evidence binds
        # to the CURRENT staged DOCX (exact-artifact binding, post-pilot-01
        # audit): evidence produced against an older render is stale, never
        # PASS. The render is SKIPPED when the newest versioned DOCX still
        # binds the unchanged source (reviewer B R3-B1: unconditional
        # re-rendering made convergence impossible).
        from .docx_outbox import reuse_or_build_docx_outbox
        try:
            prov = reuse_or_build_docx_outbox(ctx.workspace, ctx.run_id)
            if prov:
                state["docx_outbox"] = prov["docx"]["name"]
                state["docx_outbox_sha256"] = prov["docx"]["sha256"]
                state["docx_outbox_source_sha256"] = prov["source"]["sha256"]
                state["docx_reused"] = bool(prov.get("reused"))
        except Exception as e:  # a broken renderer must degrade, not crash P31
            state["docx_outbox_error"] = str(e)
        binding, per_item = _check_artifact_binding(
            inbox_items, item_classes, state.get("docx_outbox_sha256"))
        state["artifact_binding"] = binding
        state["artifact_binding_items"] = per_item
    write_json(ctx.workspace.reports_dir / "paperpal_state.json", state)
    if evidence_class == "external_paperpal_declared":
        binding = state.get("artifact_binding")
        if mode == "word_auto" and binding != "exact":
            return NodeOutcome(Verdict.HUMAN_REQUIRED,
                               {"bridge": "word_auto",
                                "evidence_class": evidence_class,
                                "artifact_binding": binding,
                                "reason": ("inbox Paperpal evidence is not bound to the "
                                           "current staged DOCX (binding=%s) — re-run "
                                           "Paperpal on the current outbox DOCX" % binding)})
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
