"""Workflow Card (WP11): compact, human- and LLM-readable summary of a
reproduction capsule and its execution evidence.

DERIVED ONLY. This card is a pure projection of canonical machine evidence
(ReproductionCapsule, ExecutionReceipts, optional ReproductionComparison)
via the same validated ExportBundle as the RO-Crate/PROV exporters. It is
never a source of truth and never a gate input: PF-internal provenance and
receipts in state/store.py stay authoritative, and every gate in the P00–P37
DAG reads the canonical state, never this card. The disclaimer below is
part of every card, in the structured output and the Markdown rendering.

Scope honesty: the card reports only what the evidence shows. The capsule
carries no free-text "purpose" field, so none is invented; provenance_refs
are listed verbatim. Limitations are derived from declared evidence
(nondeterminism declarations, semantic rules, failed runs), not from
assumptions.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..reproduction.capsule import ExecutionReceipt, ReproductionCapsule
from ..reproduction.differential import ReproductionComparison
from ._shared import ExportBundle

CARD_SCHEMA_VERSION = 1
CARD_KIND = "paper_factory.workflow_card"
CARD_DISCLAIMER = (
    "DERIVED SUMMARY: built exclusively from canonical machine evidence "
    "(ReproductionCapsule + ExecutionReceipts). This card is never a source "
    "of truth and never a gate input — PF-internal provenance and receipts "
    "remain authoritative.")
CARD_JSON_FILENAME = "workflow_card.json"
CARD_MARKDOWN_FILENAME = "workflow_card.md"


def _receipt_view(receipt: ExecutionReceipt) -> dict[str, Any]:
    duration = (receipt.finished_at - receipt.started_at).total_seconds()
    return {
        "execution_id": receipt.execution_id,
        "receipt_id": receipt.receipt_id,
        "status": receipt.status,
        "exit_code": receipt.exit_code,
        "backend": {
            "kind": receipt.backend.kind,
            "name": receipt.backend.name,
            "version": receipt.backend.version,
        },
        "started_at": receipt.started_at.isoformat(),
        "finished_at": receipt.finished_at.isoformat(),
        "duration_seconds": round(duration, 3),
        "failure_reason": receipt.failure_reason,
        "outputs": [
            {"rel_path": f.rel_path, "sha256": f.sha256}
            for f in receipt.outputs
        ],
        "stdout_sha256": receipt.stdout_sha256,
        "stderr_sha256": receipt.stderr_sha256,
    }


def build_workflow_card(
    capsule: ReproductionCapsule,
    receipts: list[ExecutionReceipt] | tuple[ExecutionReceipt, ...] = (),
    comparison: ReproductionComparison | None = None,
) -> dict[str, Any]:
    """Build the structured card (a plain JSON-serialisable dict). Raises
    ExportError on missing/mandatory-data violations (see _shared)."""
    bundle = ExportBundle.build(capsule, receipts)
    env = capsule.environment
    card: dict[str, Any] = {
        "schema_version": CARD_SCHEMA_VERSION,
        "kind": CARD_KIND,
        "derived": True,
        "disclaimer": CARD_DISCLAIMER,
        "capsule": {
            "capsule_id": capsule.capsule_id,
            "capsule_digest": capsule.capsule_digest,
            "command": list(capsule.command),
            "cwd": capsule.cwd,
            "producer": {
                "kind": capsule.producer.kind,
                "name": capsule.producer.name,
                "version": capsule.producer.version,
            },
            "provenance_refs": list(capsule.provenance_refs),
        },
        "environment": {
            "python_version": env.python_version,
            "platform": env.platform,
            "tool_versions": dict(sorted(env.tool_versions.items())),
            "dependency_lock_ref": (env.dependency_lock_ref.model_dump()
                                    if env.dependency_lock_ref else None),
            "container_image": env.container_image,
        },
        "inputs": [r.model_dump() for r in bundle.inputs],
        "configs": [r.model_dump() for r in bundle.configs],
        "code": [r.model_dump() for r in bundle.code],
        "parameters": [p.model_dump() for p in capsule.parameters],
        "expected_outputs": list(capsule.expected_outputs),
        "declared_nondeterminism": [d.model_dump()
                                    for d in capsule.nondeterministic_outputs],
        "semantic_rules": [s.model_dump() for s in capsule.semantic_rules],
        "runs": [_receipt_view(r) for r in bundle.receipts],
        "reproduction": {
            "executions": len(bundle.receipts),
            "comparison": None,
        },
        "limitations": [],
    }
    if comparison is not None:
        card["reproduction"]["comparison"] = {
            "classification": comparison.classification.value,
            "differing_outputs": list(comparison.differing_outputs),
            "missing_outputs": list(comparison.missing_outputs),
            "notes": list(comparison.notes),
        }
    limitations: list[str] = []
    for decl in capsule.nondeterministic_outputs:
        limitations.append(
            f"output '{decl.pattern}' is declared nondeterministic "
            f"({decl.reason})")
    for rule in capsule.semantic_rules:
        limitations.append(
            f"output '{rule.applies_to}' is accepted by semantic rule "
            f"{rule.rule_id} ({rule.kind}, tolerance={rule.tolerance}) — "
            "hash equality is not claimed for it")
    failed = [r for r in bundle.receipts if r.status != "completed"]
    for receipt in failed:
        limitations.append(
            f"execution {receipt.execution_id} ended with status="
            f"{receipt.status} ({receipt.failure_reason or 'no reason'})")
    card["limitations"] = limitations
    return card


def render_workflow_card_markdown(card: dict[str, Any]) -> str:
    """Render the structured card as Markdown (human- and LLM-readable)."""
    capsule = card["capsule"]
    env = card["environment"]
    lines: list[str] = [
        f"# Workflow Card — {capsule['capsule_id']}",
        "",
        f"> ⚠️ {card['disclaimer']}",
        "",
        "## Capsule",
        "",
        f"- **capsule_id:** `{capsule['capsule_id']}`",
        f"- **capsule_digest:** `{capsule['capsule_digest']}`",
        f"- **command:** `{' '.join(capsule['command'])}`",
        f"- **cwd:** `{capsule['cwd']}`",
        (f"- **producer:** {capsule['producer']['kind']}/"
         f"{capsule['producer']['name']} {capsule['producer']['version']}"),
    ]
    if capsule["provenance_refs"]:
        lines.append(f"- **provenance_refs:** "
                     f"{', '.join(capsule['provenance_refs'])}")

    lines += [
        "",
        "## Environment",
        "",
        (f"- **python:** {env['python_version']} · **platform:** "
         f"{env['platform']}"),
    ]
    for name, version in env["tool_versions"].items():
        lines.append(f"- **tool {name}:** {version}")
    if env["dependency_lock_ref"]:
        lines.append(f"- **dependency lock:** "
                     f"`{env['dependency_lock_ref']['rel_path']}`")
    if env["container_image"]:
        lines.append(f"- **container image:** `{env['container_image']}`")

    def _files(title: str, refs: list[dict[str, str]]) -> None:
        lines.extend(["", f"## {title}", ""])
        if not refs:
            lines.append("_none declared_")
            return
        for ref in refs:
            lines.append(f"- `{ref['rel_path']}` — sha256 "
                         f"`{ref['sha256']}`")

    _files("Inputs", card["inputs"])
    _files("Configuration", card["configs"])
    _files("Code", card["code"])

    if card["parameters"]:
        lines += ["", "## Parameters", ""]
        for p in card["parameters"]:
            det = "deterministic" if p["deterministic"] else "runtime-varying"
            lines.append(f"- `{p['name']}` = `{p['value']}` ({det})")
    if card["expected_outputs"]:
        lines += ["", "## Expected outputs", ""]
        for pattern in card["expected_outputs"]:
            lines.append(f"- `{pattern}`")

    lines += ["", "## Runs", ""]
    if not card["runs"]:
        lines.append("_no executions recorded_")
    for run in card["runs"]:
        lines.append(
            f"- `{run['execution_id']}` — **{run['status']}** "
            f"(exit {run['exit_code']}) via {run['backend']['kind']}/"
            f"{run['backend']['name']} {run['backend']['version']}, "
            f"{run['duration_seconds']}s")
        if run["failure_reason"]:
            lines.append(f"  - failure: {run['failure_reason']}")
        for out in run["outputs"]:
            lines.append(f"  - output `{out['rel_path']}` — sha256 "
                         f"`{out['sha256']}`")

    repro = card["reproduction"]
    lines += ["", "## Reproduction status", ""]
    lines.append(f"- **executions:** {repro['executions']}")
    comparison = repro["comparison"]
    if comparison is not None:
        lines.append(f"- **comparison:** {comparison['classification']}")
        if comparison["differing_outputs"]:
            lines.append("- **differing outputs:** "
                         + ", ".join(f"`{p}`"
                                     for p in comparison["differing_outputs"]))
        if comparison["missing_outputs"]:
            lines.append("- **missing outputs:** "
                         + ", ".join(f"`{p}`"
                                     for p in comparison["missing_outputs"]))
        for note in comparison["notes"]:
            lines.append(f"- note: {note}")
    else:
        lines.append("- **comparison:** none (fewer than two executions or "
                     "not compared)")

    lines += ["", "## Limitations", ""]
    if card["limitations"]:
        for limitation in card["limitations"]:
            lines.append(f"- {limitation}")
    else:
        lines.append("- none declared in the capsule evidence")
    lines.append("")
    return "\n".join(lines)


def write_workflow_card(
    capsule: ReproductionCapsule,
    receipts: list[ExecutionReceipt] | tuple[ExecutionReceipt, ...],
    target_dir: str | Path,
    comparison: ReproductionComparison | None = None,
) -> tuple[Path, Path]:
    """Write `workflow_card.json` and `workflow_card.md` into `target_dir`."""
    card = build_workflow_card(capsule, receipts, comparison)
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)
    json_path = target / CARD_JSON_FILENAME
    json_path.write_text(
        json.dumps(card, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    md_path = target / CARD_MARKDOWN_FILENAME
    md_path.write_text(render_workflow_card_markdown(card), encoding="utf-8")
    return json_path, md_path
