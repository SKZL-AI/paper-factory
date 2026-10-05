"""Contract tests for the Reproduction Capsule (WP4): round-trips, strictness,
schema-version fail-visible, control-char rejection, and the exact documented
capsule_digest semantics (field list, order-invariance, exclusion policy)."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from paper_factory.reproduction import (
    EnvironmentIdentity,
    ExecutionReceipt,
    FileRef,
    NondeterminismDecl,
    ParameterDecl,
    ReproductionCapsule,
    SemanticRule,
)
from paper_factory.verification import BackendIdentity

SHA = "a" * 64
SHA_B = "b" * 64
NOW = datetime(2026, 10, 4, 12, 0, 0, tzinfo=UTC)
LATER = datetime(2026, 10, 4, 12, 5, 0, tzinfo=UTC)


def backend() -> BackendIdentity:
    return BackendIdentity(kind="pf_native", name="paper-factory",
                           version="1.3.0-dev")


def environment() -> EnvironmentIdentity:
    return EnvironmentIdentity(python_version="3.11.4", platform="linux-x86_64")


def capsule(**over) -> ReproductionCapsule:
    base = {
        "capsule_id": "cap-1",
        "command": ["python3", "compute.py"],
        "code_refs": [FileRef(rel_path="compute.py", sha256=SHA)],
        "input_refs": [FileRef(rel_path="input.csv", sha256=SHA_B)],
        "environment": environment(),
        "expected_outputs": ["summary.json"],
        "producer": backend(),
    }
    base.update(over)
    return ReproductionCapsule(**base)


def receipt(**over) -> ExecutionReceipt:
    base = {
        "receipt_id": "r-1",
        "execution_id": "exec-1",
        "capsule_id": "cap-1",
        "capsule_digest": SHA,
        "status": "completed",
        "exit_code": 0,
        "outputs": [FileRef(rel_path="summary.json", sha256=SHA)],
        "stdout_sha256": SHA_B,
        "stderr_sha256": SHA,
        "backend": backend(),
        "started_at": NOW,
        "finished_at": LATER,
    }
    base.update(over)
    return ExecutionReceipt(**base)


def roundtrip(model):
    return type(model).model_validate_json(model.model_dump_json())


# ---------------------------------------------------------------- round-trips


def test_capsule_roundtrip():
    c = capsule(parameters=[ParameterDecl(name="alpha", value="1")],
                nondeterministic_outputs=[NondeterminismDecl(
                    pattern="run_*.log", reason="wall-clock timestamps in log")],
                semantic_rules=[SemanticRule(rule_id="t1", applies_to="*.json",
                                             tolerance=1e-6)],
                provenance_refs=["docs/pilot.md"])
    assert roundtrip(c) == c


def test_receipt_roundtrip():
    assert roundtrip(receipt()) == receipt()


def test_file_ref_and_decl_roundtrips():
    assert roundtrip(FileRef(rel_path="a/b.json", sha256=SHA)) == \
        FileRef(rel_path="a/b.json", sha256=SHA)
    assert roundtrip(environment()) == environment()
    assert roundtrip(ParameterDecl(name="k", value="v", deterministic=False)) == \
        ParameterDecl(name="k", value="v", deterministic=False)


# ---------------------------------------------------------------- strictness


@pytest.mark.parametrize("model", [
    capsule(),
    receipt(),
    FileRef(rel_path="a", sha256=SHA),
    environment(),
    ParameterDecl(name="k", value="v"),
    NondeterminismDecl(pattern="*.log", reason="r"),
    SemanticRule(rule_id="t", applies_to="*.json", tolerance=0.1),
])
def test_extra_fields_forbidden(model):
    payload = model.model_dump(mode="json")
    payload["provider_pane_id"] = "leak"
    with pytest.raises(ValidationError):
        type(model).model_validate(payload)


def test_wrong_schema_version_capsule():
    payload = capsule().model_dump(mode="json")
    payload["schema_version"] = 2
    with pytest.raises(ValidationError):
        ReproductionCapsule.model_validate(payload)


def test_wrong_schema_version_receipt():
    payload = receipt().model_dump(mode="json")
    payload["schema_version"] = 2
    with pytest.raises(ValidationError):
        ExecutionReceipt.model_validate(payload)


def test_invalid_sha256_file_ref():
    with pytest.raises(ValidationError):
        FileRef(rel_path="x", sha256="not-hex")


def test_control_chars_rejected_in_rel_path_and_command():
    for bad in ("evil\n" + "c" * 64, "a\rb", "a\x00b"):
        with pytest.raises(ValidationError):
            FileRef(rel_path=bad, sha256=SHA)
    with pytest.raises(ValidationError):
        capsule(command=["python3", "evil\narg"])


@pytest.mark.parametrize("bad_cwd", ["/abs/path", "..", "a/../b", "a\\b"])
def test_cwd_must_be_safe_relative(bad_cwd):
    with pytest.raises(ValidationError):
        capsule(cwd=bad_cwd)


def test_cwd_defaults_and_normalizes():
    assert capsule().cwd == "."
    assert capsule(cwd="sub/dir").cwd == "sub/dir"
    assert capsule(cwd="./sub/").cwd == "./sub/"


# ---------------------------------------------------------------- digest


def test_digest_matches_documented_canonical_format():
    """Pin the documented serialization: json.dumps(payload, sort_keys=True,
    separators=(",", ":")) over exactly the digest field list."""
    c = capsule()
    payload = {
        "schema_version": 1,
        "command": ["python3", "compute.py"],
        "cwd": ".",
        "code_refs": [{"rel_path": "compute.py", "sha256": SHA}],
        "config_refs": [],
        "input_refs": [{"rel_path": "input.csv", "sha256": SHA_B}],
        "parameters": [],
        "environment": {"python_version": "3.11.4",
                        "platform": "linux-x86_64",
                        "tool_versions": {}},
    }
    expected = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert c.capsule_digest == expected


def test_digest_order_invariant_in_refs_and_parameters():
    c1 = capsule(code_refs=[
        FileRef(rel_path="a.py", sha256=SHA),
        FileRef(rel_path="b.py", sha256=SHA_B)],
        parameters=[ParameterDecl(name="p1", value="1"),
                    ParameterDecl(name="p2", value="2")])
    c2 = capsule(code_refs=[
        FileRef(rel_path="b.py", sha256=SHA_B),
        FileRef(rel_path="a.py", sha256=SHA)],
        parameters=[ParameterDecl(name="p2", value="2"),
                    ParameterDecl(name="p1", value="1")])
    assert c1.capsule_digest == c2.capsule_digest


@pytest.mark.parametrize("mutate", [
    {"capsule_id": "different-id"},
    {"expected_outputs": ["other.json"]},
    {"nondeterministic_outputs": [NondeterminismDecl(pattern="*.log",
                                                      reason="r")]},
    {"semantic_rules": [SemanticRule(rule_id="t", applies_to="*.json",
                                      tolerance=0.1)]},
    {"producer": BackendIdentity(kind="external", name="x", version="0")},
    {"provenance_refs": ["something"]},
    {"parameters": [ParameterDecl(name="seed", value="42",
                                   deterministic=False)]},
])
def test_digest_excludes_identity_and_comparison_policy(mutate):
    """Identifiers, producer, provenance, expected outputs, comparison policy
    and non-deterministic parameters must NOT move the semantic digest."""
    assert capsule(**mutate).capsule_digest == capsule().capsule_digest


@pytest.mark.parametrize("mutate", [
    {"command": ["python3", "other.py"]},
    {"cwd": "sub"},
    {"code_refs": [FileRef(rel_path="compute.py", sha256=SHA_B)]},
    {"input_refs": []},
    {"parameters": [ParameterDecl(name="alpha", value="1")]},
    {"environment": EnvironmentIdentity(
        python_version="3.11.4", platform="linux-x86_64",
        tool_versions={"numpy": "2.1"})},
])
def test_digest_changes_with_semantic_content(mutate):
    assert capsule(**mutate).capsule_digest != capsule().capsule_digest


def test_digest_stable_across_serialization():
    c = capsule(parameters=[ParameterDecl(name="k", value="v")])
    assert ReproductionCapsule.model_validate_json(
        c.model_dump_json()).capsule_digest == c.capsule_digest


# ---------------------------------------------------------------- receipts


def test_receipt_timestamps_outside_digest_identity():
    """execution identity and timing are per-run data: two receipts for the
    same capsule may differ in everything except capsule_digest/content."""
    r1 = receipt(receipt_id="r1", execution_id="e1", started_at=NOW,
                 finished_at=LATER)
    r2 = receipt(receipt_id="r2", execution_id="e2",
                 started_at=datetime(2026, 10, 5, 9, 0, 0, tzinfo=UTC),
                 finished_at=datetime(2026, 10, 5, 9, 1, 0, tzinfo=UTC))
    assert r1.capsule_digest == r2.capsule_digest
    assert r1.execution_id != r2.execution_id
