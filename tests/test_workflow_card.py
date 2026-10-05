"""WP11 tests: Workflow Card — derived, human/LLM-readable summary.

Hard rules pinned here: the card is derived exclusively from canonical
machine evidence, the disclaimer appears in the module docstring, the
structured output and the Markdown rendering, and the card is never a gate
input (it has no verdict field and is marked derived=true)."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import paper_factory.export.workflow_card as workflow_card_module
from paper_factory.export.workflow_card import (
    CARD_DISCLAIMER,
    CARD_JSON_FILENAME,
    CARD_MARKDOWN_FILENAME,
    build_workflow_card,
    render_workflow_card_markdown,
    write_workflow_card,
)
from paper_factory.reproduction import (
    LocalReproductionRunner,
    NondeterminismDecl,
    ReproductionCapsule,
    compare_executions,
)

FIXTURE = Path(__file__).parent / "fixtures" / "repro_pilot"


def pilot_capsule() -> ReproductionCapsule:
    c = ReproductionCapsule.model_validate_json(
        (FIXTURE / "capsule.json").read_text(encoding="utf-8"))
    return c.model_copy(update={"command": [sys.executable, *c.command[1:]]})


def pilot_run(tmp_path: Path, runs: int = 2):
    capsule = pilot_capsule()
    runner = LocalReproductionRunner()
    receipts = []
    for i in range(runs):
        root = tmp_path / f"run{i}"
        shutil.copytree(FIXTURE, root)
        receipts.append(runner.run(capsule, root))
    return capsule, receipts


# --------------------------------------------------------------------------- #
# Derivation honesty (the WP11 hard rule)
# --------------------------------------------------------------------------- #


def test_disclaimer_in_module_docstring():
    assert "never a source of truth" in workflow_card_module.__doc__
    assert "gate" in workflow_card_module.__doc__


def test_disclaimer_in_structured_card(tmp_path):
    capsule, receipts = pilot_run(tmp_path)
    card = build_workflow_card(capsule, receipts)
    assert card["derived"] is True
    assert card["disclaimer"] == CARD_DISCLAIMER
    assert "never a source of truth" in card["disclaimer"]
    assert "never a gate input" in card["disclaimer"]


def test_disclaimer_leads_the_markdown(tmp_path):
    capsule, receipts = pilot_run(tmp_path)
    card = build_workflow_card(capsule, receipts)
    md = render_workflow_card_markdown(card)
    assert md.index("DERIVED SUMMARY") < md.index("## Capsule")
    assert CARD_DISCLAIMER in md


def test_card_has_no_verdict_field(tmp_path):
    """Gate-honesty: the card cannot be mistaken for a verification
    verdict — the vocabulary simply does not exist in it."""
    capsule, receipts = pilot_run(tmp_path)
    card = build_workflow_card(capsule, receipts)
    blob = json.dumps(card)
    for forbidden in ('"verdict"', '"Verdict"', '"gate"', '"passed"'):
        assert forbidden not in blob


# --------------------------------------------------------------------------- #
# Content: built only from canonical evidence
# --------------------------------------------------------------------------- #


def test_card_reflects_capsule_identity_and_inputs(tmp_path):
    capsule, receipts = pilot_run(tmp_path)
    card = build_workflow_card(capsule, receipts)
    assert card["capsule"]["capsule_id"] == capsule.capsule_id
    assert card["capsule"]["capsule_digest"] == capsule.capsule_digest
    assert card["capsule"]["command"] == capsule.command
    assert card["capsule"]["provenance_refs"] == capsule.provenance_refs
    assert card["inputs"] == [r.model_dump() for r in capsule.input_refs]
    assert card["environment"]["python_version"] == \
        capsule.environment.python_version
    assert card["environment"]["platform"] == capsule.environment.platform


def test_card_runs_carry_output_hashes(tmp_path):
    capsule, receipts = pilot_run(tmp_path)
    card = build_workflow_card(capsule, receipts)
    assert len(card["runs"]) == 2
    for run, receipt in zip(card["runs"], receipts):
        assert run["execution_id"] == receipt.execution_id
        assert run["status"] == "completed"
        assert run["exit_code"] == 0
        assert run["failure_reason"] is None
        assert run["outputs"] == [f.model_dump() for f in receipt.outputs]
        assert run["duration_seconds"] >= 0.0


def test_card_reproduction_status_from_comparison(tmp_path):
    capsule, receipts = pilot_run(tmp_path)
    comparison = compare_executions(receipts[0], receipts[1], capsule)
    card = build_workflow_card(capsule, receipts, comparison)
    repro = card["reproduction"]
    assert repro["executions"] == 2
    assert repro["comparison"]["classification"] == "REPRODUCED_EXACT"
    assert repro["comparison"]["differing_outputs"] == []
    md = render_workflow_card_markdown(card)
    assert "REPRODUCED_EXACT" in md


def test_card_reproduction_status_none_without_comparison(tmp_path):
    capsule, receipts = pilot_run(tmp_path)
    card = build_workflow_card(capsule, receipts)
    assert card["reproduction"]["comparison"] is None
    md = render_workflow_card_markdown(card)
    assert "none (fewer than two executions" in md


def test_card_records_failures_and_limitations(tmp_path):
    capsule, receipts = pilot_run(tmp_path, runs=1)
    failed = receipts[0].model_copy(update={
        "execution_id": "exec-failed", "status": "failed", "exit_code": 2,
        "failure_reason": "synthetic failure", "outputs": []})
    card = build_workflow_card(capsule, [receipts[0], failed])
    failed_runs = [r for r in card["runs"] if r["status"] != "completed"]
    assert [r["execution_id"] for r in failed_runs] == ["exec-failed"]
    assert any("exec-failed" in lim and "failed" in lim
               for lim in card["limitations"])
    md = render_workflow_card_markdown(card)
    assert "synthetic failure" in md
    assert "exec-failed" in md


def test_card_reports_declared_nondeterminism_as_limitation(tmp_path):
    capsule, receipts = pilot_run(tmp_path)
    decl = NondeterminismDecl(pattern="summary.json",
                              reason="timestamp embedded")
    capsule = capsule.model_copy(
        update={"nondeterministic_outputs": [decl]})
    card = build_workflow_card(capsule, receipts)
    assert card["declared_nondeterminism"] == [decl.model_dump()]
    assert any("summary.json" in lim and "nondeterministic" in lim
               for lim in card["limitations"])


def test_card_without_executions_is_honest(tmp_path):
    capsule = pilot_capsule()
    card = build_workflow_card(capsule, [])
    assert card["runs"] == []
    assert card["reproduction"] == {"executions": 0, "comparison": None}
    md = render_workflow_card_markdown(card)
    assert "no executions recorded" in md
    assert CARD_DISCLAIMER in md


# --------------------------------------------------------------------------- #
# File output
# --------------------------------------------------------------------------- #


def test_write_workflow_card_outputs_both_formats(tmp_path):
    capsule, receipts = pilot_run(tmp_path, runs=1)
    json_path, md_path = write_workflow_card(capsule, receipts, tmp_path)
    assert json_path.name == CARD_JSON_FILENAME
    assert md_path.name == CARD_MARKDOWN_FILENAME
    loaded = json.loads(json_path.read_text(encoding="utf-8"))
    assert loaded == build_workflow_card(capsule, receipts)
    assert CARD_DISCLAIMER in md_path.read_text(encoding="utf-8")
