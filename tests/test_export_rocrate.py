"""WP9 conformance tests: RO-Crate 1.3 / Process Run Crate 0.6 export.

Local structural assertions only (NO online validator, NO network): the
required properties come from the profile requirements table
(researchobject.org/workflow-run-crate/profiles/process_run_crate, read
2026-10-05). Round-trip is not claimed — defined exported invariants are
pinned instead (every content hash of the capsule/receipts appears in the
crate; every action result references a File entity with the same hash).
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

from paper_factory.export._shared import ExportError
from paper_factory.export.rocrate import (
    METADATA_FILENAME,
    PROCESS_RUN_PROFILE_ID,
    RO_CRATE_CONTEXT,
    RO_CRATE_SPEC_ID,
    WORKFLOW_RUN_CONTEXT,
    build_rocrate,
    write_rocrate,
)
from paper_factory.reproduction import (
    ExecutionReceipt,
    LocalReproductionRunner,
    ReproductionCapsule,
)

FIXTURE = Path(__file__).parent / "fixtures" / "repro_pilot"


def pilot_capsule() -> ReproductionCapsule:
    c = ReproductionCapsule.model_validate_json(
        (FIXTURE / "capsule.json").read_text(encoding="utf-8"))
    return c.model_copy(update={"command": [sys.executable, *c.command[1:]]})


def pilot_receipts(tmp_path: Path, runs: int = 2) -> tuple[ReproductionCapsule,
                                                          list[ExecutionReceipt]]:
    capsule = pilot_capsule()
    runner = LocalReproductionRunner()
    receipts = []
    for i in range(runs):
        root = tmp_path / f"run{i}"
        shutil.copytree(FIXTURE, root)
        receipts.append(runner.run(capsule, root))
    return capsule, receipts


def graph_by_id(crate: dict) -> dict:
    return {e["@id"]: e for e in crate["@graph"]}


# --------------------------------------------------------------------------- #
# Structural conformance (profile requirements)
# --------------------------------------------------------------------------- #


def test_context_and_metadata_entity(tmp_path):
    capsule, receipts = pilot_receipts(tmp_path)
    crate = build_rocrate(capsule, receipts)
    assert crate["@context"] == [RO_CRATE_CONTEXT, WORKFLOW_RUN_CONTEXT]
    meta = graph_by_id(crate)[METADATA_FILENAME]
    assert meta["@type"] == "CreativeWork"
    assert meta["conformsTo"] == {"@id": RO_CRATE_SPEC_ID}
    assert meta["about"] == {"@id": "./"}


def test_root_dataset_conforms_to_process_run_profile(tmp_path):
    capsule, receipts = pilot_receipts(tmp_path)
    crate = build_rocrate(capsule, receipts)
    graph = graph_by_id(crate)
    root = graph["./"]
    assert root["@type"] == "Dataset"
    assert root["conformsTo"] == {"@id": PROCESS_RUN_PROFILE_ID}
    assert graph[PROCESS_RUN_PROFILE_ID]["@type"] == "CreativeWork"
    # every CreateAction is mentioned from the root dataset (profile SHOULD)
    action_ids = {e["@id"] for e in crate["@graph"] if e.get("@type")
                  == "CreateAction"}
    mentioned = {m["@id"] for m in root["mentions"]}
    assert action_ids <= mentioned


def test_software_application_required_properties(tmp_path):
    capsule, receipts = pilot_receipts(tmp_path)
    crate = build_rocrate(capsule, receipts)
    tools = [e for e in crate["@graph"]
             if "SoftwareApplication" in _types(e)]
    assert tools, "profile requires a SoftwareApplication"
    for tool in tools:
        assert tool["@id"].startswith("#tool-")
        assert tool["name"]
        assert tool["softwareVersion"]


def _types(entity: dict) -> list[str]:
    t = entity.get("@type", [])
    return t if isinstance(t, list) else [t]


def test_create_action_required_properties(tmp_path):
    capsule, receipts = pilot_receipts(tmp_path)
    crate = build_rocrate(capsule, receipts)
    actions = [e for e in crate["@graph"] if e.get("@type") == "CreateAction"]
    assert len(actions) == len(receipts)
    graph = graph_by_id(crate)
    for action, receipt in zip(actions, receipts):
        assert action["@id"] == f"#{receipt.execution_id}"
        assert action["instrument"]["@id"] in graph
        assert action["endTime"] == receipt.finished_at.isoformat()
        assert action["startTime"] == receipt.started_at.isoformat()
        assert action["actionStatus"] == \
            "http://schema.org/CompletedActionStatus"
        assert "error" not in action
        for ref in action["object"]:
            assert ref["@id"] in graph


def test_failed_run_maps_to_failed_action_status(tmp_path):
    capsule, receipts = pilot_receipts(tmp_path, runs=1)
    failed = receipts[0].model_copy(update={
        "status": "failed", "exit_code": 1,
        "failure_reason": "boom", "outputs": []})
    crate = build_rocrate(capsule, [failed])
    action = next(e for e in crate["@graph"]
                  if e.get("@type") == "CreateAction")
    assert action["actionStatus"] == "http://schema.org/FailedActionStatus"
    assert action["error"] == "boom"


def test_every_file_entity_carries_sha256(tmp_path):
    capsule, receipts = pilot_receipts(tmp_path)
    crate = build_rocrate(capsule, receipts)
    files = [e for e in crate["@graph"] if "File" in _types(e)]
    assert files
    for entity in files:
        assert len(entity["sha256"]) == 64


def test_environment_as_formal_parameters(tmp_path):
    capsule, receipts = pilot_receipts(tmp_path)
    crate = build_rocrate(capsule, receipts)
    graph = graph_by_id(crate)
    action = next(e for e in crate["@graph"]
                  if e.get("@type") == "CreateAction")
    env_names = {graph[r["@id"]]["name"]: graph[r["@id"]]["value"]
                 for r in action["environment"]}
    assert env_names["python_version"] == capsule.environment.python_version
    assert env_names["platform"] == capsule.environment.platform


# --------------------------------------------------------------------------- #
# Exported invariants (round-trip is NOT claimed)
# --------------------------------------------------------------------------- #


def test_invariant_every_capsule_input_hash_appears(tmp_path):
    capsule, receipts = pilot_receipts(tmp_path)
    crate = build_rocrate(capsule, receipts)
    file_hashes = {e["sha256"] for e in crate["@graph"]
                   if "File" in _types(e)}
    for ref in capsule.input_refs:
        assert ref.sha256 in file_hashes


def test_invariant_every_receipt_output_hash_appears(tmp_path):
    capsule, receipts = pilot_receipts(tmp_path)
    crate = build_rocrate(capsule, receipts)
    graph = graph_by_id(crate)
    file_hashes = {e["sha256"] for e in crate["@graph"]
                   if "File" in _types(e)}
    for receipt in receipts:
        for ref in receipt.outputs:
            assert ref.sha256 in file_hashes
            # each result reference resolves to a File with the SAME hash
            action = graph[f"#{receipt.execution_id}"]
            result_ids = {r["@id"] for r in action["result"]}
            matching = [e for e in crate["@graph"] if e["@id"] in result_ids
                        and e.get("sha256") == ref.sha256]
            assert matching, f"no result File entity for {ref.rel_path}"


def test_invariant_capsule_digest_mentioned(tmp_path):
    capsule, receipts = pilot_receipts(tmp_path)
    crate = build_rocrate(capsule, receipts)
    graph = graph_by_id(crate)
    assert graph["#capsule-digest"]["value"] == capsule.capsule_digest
    assert graph["./"]["identifier"] == capsule.capsule_id


def test_declared_nondeterministic_variants_get_distinct_ids(tmp_path):
    """Two runs producing different content for one path must not silently
    merge into one File entity: each variant keeps its own hash, the path
    ids become content-addressed and carry alternateName."""
    capsule, receipts = pilot_receipts(tmp_path, runs=1)
    out0 = receipts[0].outputs[0]
    other = out0.model_copy(update={"sha256": "0" * 64})
    # build a receipt whose outputs differ in the first entry
    outputs = [other] + list(receipts[0].outputs[1:])
    second = receipts[0].model_copy(update={
        "execution_id": "exec-second", "outputs": outputs})
    crate = build_rocrate(capsule, [receipts[0], second])
    files = [e for e in crate["@graph"] if "File" in _types(e)
             and e.get("name") == out0.rel_path]
    assert len(files) == 2
    assert {f["sha256"] for f in files} == {out0.sha256, "0" * 64}
    assert all(f["@id"].startswith("variants/") for f in files)
    assert all(f["alternateName"] == out0.rel_path for f in files)


# --------------------------------------------------------------------------- #
# Fail-visible on missing mandatory data
# --------------------------------------------------------------------------- #


def test_completed_receipt_without_output_hashes_fails(tmp_path):
    capsule, receipts = pilot_receipts(tmp_path, runs=1)
    empty = receipts[0].model_copy(update={"outputs": []})
    with pytest.raises(ExportError, match="no output evidence"):
        build_rocrate(capsule, [empty])


def test_receipt_with_foreign_capsule_digest_fails(tmp_path):
    capsule, receipts = pilot_receipts(tmp_path, runs=1)
    foreign = receipts[0].model_copy(update={"capsule_digest": "f" * 64})
    with pytest.raises(ExportError, match="not the same declared"):
        build_rocrate(capsule, [foreign])


def test_receipt_with_foreign_capsule_id_fails(tmp_path):
    capsule, receipts = pilot_receipts(tmp_path, runs=1)
    foreign = receipts[0].model_copy(update={"capsule_id": "other-capsule"})
    with pytest.raises(ExportError, match="does not belong"):
        build_rocrate(capsule, [foreign])


def test_no_receipts_fails_for_rocrate(tmp_path):
    capsule = pilot_capsule()
    with pytest.raises(ExportError, match="at least one ExecutionReceipt"):
        build_rocrate(capsule, [])


# --------------------------------------------------------------------------- #
# File output
# --------------------------------------------------------------------------- #


def test_write_rocrate_roundloads_identical(tmp_path):
    capsule, receipts = pilot_receipts(tmp_path)
    out_dir = tmp_path / "crate"
    path = write_rocrate(capsule, receipts, out_dir)
    assert path.name == METADATA_FILENAME
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded == build_rocrate(capsule, receipts)
