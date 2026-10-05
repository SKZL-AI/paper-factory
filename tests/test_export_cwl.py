"""WP-C tests: CWL v1.2 CommandLineTool export.

EXPORT ONLY: structural assertions and exported invariants only (NO cwltool,
NO online validator, NO network — cwltool is not a project dependency). The
pinned invariants: every declared file (path + sha256), every parameter
(default / determinism flag) and every expected output path of the capsule
appears in the CWL document; command argv is preserved exactly.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

from paper_factory.export._shared import ExportError
from paper_factory.export.cwl import (
    CWL_CLASS,
    CWL_VERSION,
    PF_CWL_NAMESPACE,
    build_cwl_tool,
    write_cwl_tool,
)
from paper_factory.reproduction import ReproductionCapsule

FIXTURE = Path(__file__).parent / "fixtures" / "repro_pilot"

SHA256_PATTERN = r"[0-9a-f]{64}"


def pilot_capsule() -> ReproductionCapsule:
    c = ReproductionCapsule.model_validate_json(
        (FIXTURE / "capsule.json").read_text(encoding="utf-8"))
    return c.model_copy(update={"command": [sys.executable, *c.command[1:]]})


def inputs_by_id(doc: dict) -> dict:
    return {i["id"]: i for i in doc["inputs"]}


# --------------------------------------------------------------------------- #
# Document structure (CWL v1.2 conventions)
# --------------------------------------------------------------------------- #


def test_document_structure():
    doc = build_cwl_tool(pilot_capsule())
    assert doc["cwlVersion"] == CWL_VERSION
    assert doc["class"] == CWL_CLASS
    assert doc["id"].startswith("cwl-")
    assert doc["$namespaces"] == {"pf": PF_CWL_NAMESPACE}


def test_command_preserved_exactly():
    capsule = pilot_capsule()
    doc = build_cwl_tool(capsule)
    assert doc["baseCommand"] == capsule.command[0]
    assert doc["arguments"] == capsule.command[1:]
    # argv reconstruction: baseCommand + arguments is the full capsule argv
    assert [doc["baseCommand"], *doc["arguments"]] == capsule.command


# --------------------------------------------------------------------------- #
# Declared files: inputs + hashes + staging
# --------------------------------------------------------------------------- #


def test_every_declared_file_is_a_file_input_with_its_hash():
    capsule = pilot_capsule()
    doc = build_cwl_tool(capsule)
    inputs = inputs_by_id(doc)
    for ref, role in (
        *[(r, "input") for r in capsule.input_refs],
        *[(r, "config") for r in capsule.config_refs],
        *[(r, "code") for r in capsule.code_refs],
    ):
        match = [i for i in inputs.values()
                 if i.get("pf:rel_path") == ref.rel_path]
        assert len(match) == 1, f"rel_path {ref.rel_path!r} not unique"
        entry = match[0]
        assert entry["type"] == "File"
        assert entry["pf:sha256"] == ref.sha256
        assert entry["pf:role"] == role


def test_staging_requirement_lists_every_declared_file_at_its_rel_path():
    capsule = pilot_capsule()
    doc = build_cwl_tool(capsule)
    (staging,) = [r for r in doc["requirements"]
                  if r["class"] == "InitialWorkDirRequirement"]
    entrynames = {e["entryname"] for e in staging["listing"]}
    declared = {r.rel_path for r in (*capsule.input_refs,
                                     *capsule.config_refs,
                                     *capsule.code_refs)}
    assert entrynames == declared
    for entry in staging["listing"]:
        assert entry["entry"].startswith("$(inputs.file_")


def test_dependency_lock_is_staged_and_declared():
    capsule = pilot_capsule()
    lock = {"rel_path": "requirements.lock",
            "sha256": "a487603cefcf181583cb697952dcd3eaf71632ec2a31c9f541055e9904689a48"}
    capsule = _with(capsule, environment={
        **capsule.environment.model_dump(mode="python"),
        "dependency_lock_ref": lock})
    doc = build_cwl_tool(capsule)
    inputs = inputs_by_id(doc)
    match = [i for i in inputs.values() if i.get("pf:rel_path") == lock["rel_path"]]
    assert len(match) == 1
    assert match[0]["pf:sha256"] == lock["sha256"]
    assert match[0]["pf:role"] == "dependency_lock"
    (staging,) = [r for r in doc["requirements"]
                  if r["class"] == "InitialWorkDirRequirement"]
    assert any(e["entryname"] == "requirements.lock"
               for e in staging["listing"])


# --------------------------------------------------------------------------- #
# Parameters
# --------------------------------------------------------------------------- #


def parameterized_capsule() -> ReproductionCapsule:
    capsule = pilot_capsule()
    return _with(capsule, parameters=[
        {"name": "alpha", "value": "0.05", "deterministic": True},
        {"name": "seed", "value": "runtime", "deterministic": False},
    ])


def _with(capsule: ReproductionCapsule, **updates) -> ReproductionCapsule:
    """Rebuild the capsule with `updates` applied — model_copy(update=...) would
    insert raw dicts the strict model (and capsule_digest) cannot consume."""
    data = capsule.model_dump(mode="python")
    data.update(updates)
    return ReproductionCapsule.model_validate(data)


def test_deterministic_parameter_exports_default():
    doc = build_cwl_tool(parameterized_capsule())
    entry = inputs_by_id(doc)["param_alpha"]
    assert entry["type"] == "string"
    assert entry["default"] == "0.05"
    assert entry["pf:deterministic"] is True


def test_nondeterministic_parameter_exports_without_default():
    doc = build_cwl_tool(parameterized_capsule())
    entry = inputs_by_id(doc)["param_seed"]
    assert "default" not in entry
    assert entry["pf:deterministic"] is False


# --------------------------------------------------------------------------- #
# Outputs
# --------------------------------------------------------------------------- #


def test_every_expected_output_is_a_glob_output():
    capsule = pilot_capsule()
    doc = build_cwl_tool(capsule)
    globs = {o["outputBinding"]["glob"] for o in doc["outputs"]}
    assert set(capsule.expected_outputs) <= globs
    for out in doc["outputs"]:
        if out["pf:rel_path"] in capsule.expected_outputs:
            assert out["type"] == "File"


def test_declared_nondeterministic_pattern_is_array_output_with_reason():
    capsule = _with(pilot_capsule(), nondeterministic_outputs=[
        {"pattern": "traces/*.log", "reason": "timestamped trace files"}])
    doc = build_cwl_tool(capsule)
    nd = [o for o in doc["outputs"] if o.get("pf:nondeterministic_reason")]
    assert len(nd) == 1
    assert nd[0]["type"] == {"type": "array", "items": "File"}
    assert nd[0]["outputBinding"]["glob"] == "traces/*.log"
    assert "timestamped trace files" in nd[0]["doc"]


# --------------------------------------------------------------------------- #
# Environment & contract metadata
# --------------------------------------------------------------------------- #


def test_container_image_maps_to_docker_hint():
    capsule = pilot_capsule()
    capsule = _with(capsule, environment={
        **capsule.environment.model_dump(mode="python"),
        "container_image": "python:3.11-slim"})
    doc = build_cwl_tool(capsule)
    (hint,) = doc["hints"]
    assert hint["class"] == "DockerRequirement"
    assert hint["dockerPull"] == "python:3.11-slim"
    assert doc["pf:environment"]["container_image"] == "python:3.11-slim"


def test_no_container_image_means_no_docker_hint():
    doc = build_cwl_tool(pilot_capsule())
    assert "hints" not in doc


def test_contract_metadata_on_document():
    capsule = pilot_capsule()
    doc = build_cwl_tool(capsule)
    assert doc["pf:capsule_id"] == capsule.capsule_id
    assert doc["pf:capsule_digest"] == capsule.capsule_digest
    assert doc["pf:cwd"] == capsule.cwd
    assert doc["pf:environment"]["python_version"] == \
        capsule.environment.python_version
    assert doc["pf:environment"]["platform"] == capsule.environment.platform
    assert doc["pf:provenance_refs"] == list(capsule.provenance_refs)


def test_comparison_policy_carried_as_metadata():
    capsule = _with(pilot_capsule(), semantic_rules=[
        {"rule_id": "r1", "applies_to": "summary.json",
         "kind": "float_tolerance", "tolerance": 1e-6}])
    doc = build_cwl_tool(capsule)
    rules = doc["pf:comparison_policy"]["semantic_rules"]
    assert rules == [{"rule_id": "r1", "applies_to": "summary.json",
                      "kind": "float_tolerance", "tolerance": 1e-6}]


# --------------------------------------------------------------------------- #
# Adversarial / fail-visible
# --------------------------------------------------------------------------- #


def test_input_identifier_collision_is_fail_visible():
    capsule = pilot_capsule()
    # "input-csv" slugs to the same CWL identifier as the existing "input.csv"
    extra = {"rel_path": "input-csv",
             "sha256": "e0b2b4b8838bcf298dfe6e578c7b7a3ac37496d77b267a272442539bec4e6b83"}
    with pytest.raises(ExportError):
        build_cwl_tool(_with(
            capsule, code_refs=[*capsule.model_dump(mode="python")["code_refs"],
                                extra]))


def test_hash_format_pinned_on_file_inputs():
    import re
    doc = build_cwl_tool(pilot_capsule())
    for entry in inputs_by_id(doc).values():
        if entry.get("pf:role"):
            assert re.fullmatch(SHA256_PATTERN, entry["pf:sha256"])


# --------------------------------------------------------------------------- #
# Serialization: written file parses as JSON AND YAML (valid CWL document)
# --------------------------------------------------------------------------- #


def test_written_document_parses_as_json_and_yaml(tmp_path):
    capsule = pilot_capsule()
    path = write_cwl_tool(capsule, tmp_path / "tool.cwl")
    raw = path.read_text(encoding="utf-8")
    assert json.loads(raw) == build_cwl_tool(capsule)
    assert yaml.safe_load(raw) == build_cwl_tool(capsule)
