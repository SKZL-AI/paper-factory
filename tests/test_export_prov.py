"""WP10 tests: W3C-PROV (PROV-JSON) export over the shared ExportBundle.

EXPORT ONLY: the assertions pin the defined exported invariants (every
content hash of the capsule/receipts appears as a content-addressed entity;
used/wasGeneratedBy/wasDerivedFrom/wasAssociatedWith cover exactly the
evidence-backed relations) — round-trip into PF is not claimed and not
possible by design.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

from paper_factory.export._shared import ExportError
from paper_factory.export.prov import (
    PF_NAMESPACE,
    PF_PREFIX,
    build_prov_document,
    write_prov_document,
)
from paper_factory.reproduction import (
    LocalReproductionRunner,
    ReproductionCapsule,
)

FIXTURE = Path(__file__).parent / "fixtures" / "repro_pilot"


def pilot_capsule() -> ReproductionCapsule:
    c = ReproductionCapsule.model_validate_json(
        (FIXTURE / "capsule.json").read_text(encoding="utf-8"))
    return c.model_copy(update={"command": [sys.executable, *c.command[1:]]})


def pilot_receipts(tmp_path: Path, runs: int = 2):
    capsule = pilot_capsule()
    runner = LocalReproductionRunner()
    receipts = []
    for i in range(runs):
        root = tmp_path / f"run{i}"
        shutil.copytree(FIXTURE, root)
        receipts.append(runner.run(capsule, root))
    return capsule, receipts


# --------------------------------------------------------------------------- #
# Document structure (PROV-JSON conventions)
# --------------------------------------------------------------------------- #


def test_prefixes_declared(tmp_path):
    capsule, receipts = pilot_receipts(tmp_path)
    doc = build_prov_document(capsule, receipts)
    assert doc["prefix"][PF_PREFIX] == PF_NAMESPACE
    assert "xsd" in doc["prefix"]


def test_capsule_entity_is_content_addressed(tmp_path):
    capsule, receipts = pilot_receipts(tmp_path)
    doc = build_prov_document(capsule, receipts)
    capsule_entity = doc["entity"][f"{PF_PREFIX}:capsule-"
                                   f"{capsule.capsule_digest}"]
    assert capsule_entity["pf:capsule_id"] == {
        "$": capsule.capsule_id, "type": "xsd:string"}
    assert capsule_entity["pf:capsule_digest"] == {
        "$": capsule.capsule_digest, "type": "xsd:string"}


def test_activity_carries_run_evidence(tmp_path):
    capsule, receipts = pilot_receipts(tmp_path)
    doc = build_prov_document(capsule, receipts)
    assert len(doc["activity"]) == len(receipts)
    for receipt in receipts:
        run = doc["activity"][f"{PF_PREFIX}:run-{receipt.execution_id}"]
        assert run["prov:startTime"] == receipt.started_at.isoformat()
        assert run["prov:endTime"] == receipt.finished_at.isoformat()
        assert run["pf:status"] == {"$": "completed", "type": "xsd:string"}
        assert run["pf:exit_code"] == {"$": "0", "type": "xsd:int"}


def test_agent_is_software_agent(tmp_path):
    capsule, receipts = pilot_receipts(tmp_path)
    doc = build_prov_document(capsule, receipts)
    receipt = receipts[0]
    agent = doc["agent"][f"{PF_PREFIX}:tool-{receipt.backend.kind}-"
                         f"{receipt.backend.name}"]
    assert agent["prov:type"] == {"$": "prov:SoftwareAgent",
                                  "type": "xsd:QName"}
    assert agent["pf:backend_version"] == {
        "$": receipt.backend.version, "type": "xsd:string"}


# --------------------------------------------------------------------------- #
# Core relations
# --------------------------------------------------------------------------- #


def _relation_pairs(doc: dict, relation: str, key_a: str, key_b: str) -> set:
    return {(stmt[key_a], stmt[key_b])
            for stmt in doc[relation].values()}


def test_used_covers_all_declared_refs(tmp_path):
    capsule, receipts = pilot_receipts(tmp_path)
    doc = build_prov_document(capsule, receipts)
    declared = {f"{PF_PREFIX}:file-{r.sha256}"
                for r in (*capsule.input_refs, *capsule.config_refs,
                          *capsule.code_refs)}
    used = _relation_pairs(doc, "used", "prov:activity", "prov:entity")
    run_ids = {f"{PF_PREFIX}:run-{r.execution_id}" for r in receipts}
    used_entities = {e for _, e in used}
    assert declared <= used_entities
    assert {a for a, _ in used} == run_ids


def test_was_generated_by_covers_all_outputs(tmp_path):
    capsule, receipts = pilot_receipts(tmp_path)
    doc = build_prov_document(capsule, receipts)
    gen = _relation_pairs(doc, "wasGeneratedBy", "prov:entity",
                          "prov:activity")
    for receipt in receipts:
        run_id = f"{PF_PREFIX}:run-{receipt.execution_id}"
        for ref in receipt.outputs:
            assert (f"{PF_PREFIX}:file-{ref.sha256}", run_id) in gen


def test_was_derived_from_links_outputs_to_consumed_evidence(tmp_path):
    capsule, receipts = pilot_receipts(tmp_path)
    doc = build_prov_document(capsule, receipts)
    derived = _relation_pairs(doc, "wasDerivedFrom", "prov:generatedEntity",
                              "prov:usedEntity")
    consumed = {f"{PF_PREFIX}:file-{r.sha256}"
                for r in (*capsule.input_refs, *capsule.code_refs)}
    for receipt in receipts:
        for ref in receipt.outputs:
            out_id = f"{PF_PREFIX}:file-{ref.sha256}"
            for source_id in consumed:
                assert (out_id, source_id) in derived


def test_was_associated_with_links_run_to_tool_with_capsule_plan(tmp_path):
    capsule, receipts = pilot_receipts(tmp_path)
    doc = build_prov_document(capsule, receipts)
    assoc = list(doc["wasAssociatedWith"].values())
    assert len(assoc) == len(receipts)
    for stmt in assoc:
        run_id = stmt["prov:activity"]
        assert run_id.startswith(f"{PF_PREFIX}:run-")
        assert stmt["prov:plan"] == (f"{PF_PREFIX}:capsule-"
                                     f"{capsule.capsule_digest}")
        assert stmt["prov:agent"].startswith(f"{PF_PREFIX}:tool-")


# --------------------------------------------------------------------------- #
# Exported invariants & fail-visible behaviour (shared mapping engine)
# --------------------------------------------------------------------------- #


def test_invariant_every_capsule_input_hash_appears_as_entity(tmp_path):
    capsule, receipts = pilot_receipts(tmp_path)
    doc = build_prov_document(capsule, receipts)
    for ref in capsule.input_refs:
        assert f"{PF_PREFIX}:file-{ref.sha256}" in doc["entity"]


def test_invariant_divergent_runs_yield_distinct_output_entities(tmp_path):
    """Content-addressed ids make variants explicit instead of merging them."""
    capsule, receipts = pilot_receipts(tmp_path, runs=1)
    out0 = receipts[0].outputs[0]
    other = out0.model_copy(update={"sha256": "1" * 64})
    outputs = [other] + list(receipts[0].outputs[1:])
    second = receipts[0].model_copy(update={
        "execution_id": "exec-second", "outputs": outputs})
    doc = build_prov_document(capsule, [receipts[0], second])
    assert f"{PF_PREFIX}:file-{out0.sha256}" in doc["entity"]
    assert f"{PF_PREFIX}:file-{'1' * 64}" in doc["entity"]


def test_capsule_only_document_has_no_relations(tmp_path):
    capsule = pilot_capsule()
    doc = build_prov_document(capsule, [])
    assert "activity" not in doc
    assert "used" not in doc
    # the declared computation itself is still exported as an entity
    assert f"{PF_PREFIX}:capsule-{capsule.capsule_digest}" in doc["entity"]


def test_completed_receipt_without_output_hashes_fails(tmp_path):
    capsule, receipts = pilot_receipts(tmp_path, runs=1)
    empty = receipts[0].model_copy(update={"outputs": []})
    with pytest.raises(ExportError, match="no output evidence"):
        build_prov_document(capsule, [empty])


def test_receipt_with_foreign_capsule_digest_fails(tmp_path):
    capsule, receipts = pilot_receipts(tmp_path, runs=1)
    foreign = receipts[0].model_copy(update={"capsule_digest": "e" * 64})
    with pytest.raises(ExportError, match="not the same declared"):
        build_prov_document(capsule, [foreign])


def test_write_prov_document_roundloads_identical(tmp_path):
    capsule, receipts = pilot_receipts(tmp_path)
    out_dir = tmp_path / "prov"
    path = write_prov_document(capsule, receipts, out_dir)
    assert path.name == "prov.json"
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded == build_prov_document(capsule, receipts)
