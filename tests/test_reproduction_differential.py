"""Adversarial tests for the Reproduction Differential (WP6): every
classification pinned, including the honest-refusal cases (semantic without a
declared rule is NEVER semantic; a rule without content evidence is a
MISMATCH, not a semantic pass)."""
from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from paper_factory.reproduction import (
    ExecutionReceipt,
    FileRef,
    NondeterminismDecl,
    ReproClassification,
    ReproductionCapsule,
    SemanticRule,
    compare_executions,
)
from paper_factory.verification import BackendIdentity

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
NOW = datetime(2026, 10, 4, tzinfo=UTC)


def backend():
    return BackendIdentity(kind="pf_native", name="test", version="0")


def capsule(**over) -> ReproductionCapsule:
    base = {
        "capsule_id": "cap-1",
        "command": ["python3", "x.py"],
        "environment": {"python_version": "3", "platform": "test"},
        "expected_outputs": ["summary.json"],
        "producer": backend(),
    }
    base.update(over)
    return ReproductionCapsule(**base)


def receipt(outputs, digest="d" * 64, **over) -> ExecutionReceipt:
    base = {
        "receipt_id": "r1", "execution_id": "e1", "capsule_id": "cap-1",
        "capsule_digest": digest, "status": "completed", "exit_code": 0,
        "outputs": [FileRef(rel_path=p, sha256=h) for p, h in outputs],
        "backend": backend(), "started_at": NOW, "finished_at": NOW,
    }
    base.update(over)
    return ExecutionReceipt(**base)


# ---------------------------------------------------------------- basics


def test_exact_same_hashes():
    r = receipt([("summary.json", SHA_A), ("table.txt", SHA_B)])
    res = compare_executions(r, receipt([("table.json", SHA_A)]))
    assert res.classification is ReproClassification.MISMATCH  # sanity: paths matter
    res = compare_executions(r, receipt([("summary.json", SHA_A),
                                         ("table.txt", SHA_B)]))
    assert res.classification is ReproClassification.REPRODUCED_EXACT
    assert res.differing_outputs == ()


def test_incomparable_different_digest():
    a = receipt([("summary.json", SHA_A)])
    b = receipt([("summary.json", SHA_A)], digest="e" * 64)
    res = compare_executions(a, b)
    assert res.classification is ReproClassification.INCOMPARABLE


@pytest.mark.parametrize("over_a,over_b", [
    ({"status": "failed", "exit_code": None, "failure_reason": "boom"}, {}),
    ({"status": "timeout", "exit_code": None, "failure_reason": "t"}, {}),
    ({"exit_code": 1}, {}),
    ({}, {"status": "failed", "exit_code": None, "failure_reason": "boom"}),
])
def test_unavailable_when_a_side_did_not_cleanly_run(over_a, over_b):
    a = receipt([("summary.json", SHA_A)], **over_a)
    b = receipt([("summary.json", SHA_A)], **over_b)
    assert compare_executions(a, b).classification is \
        ReproClassification.UNAVAILABLE


def test_missing_output_is_mismatch():
    a = receipt([("summary.json", SHA_A), ("table.txt", SHA_B)])
    b = receipt([("summary.json", SHA_A)])
    res = compare_executions(a, b)
    assert res.classification is ReproClassification.MISMATCH
    assert res.missing_outputs == ("table.txt",)


# ---------------------------------------------------------------- mismatch


def test_mismatch_same_digest_no_explanation():
    a = receipt([("summary.json", SHA_A)])
    b = receipt([("summary.json", SHA_B)])
    res = compare_executions(a, b)
    assert res.classification is ReproClassification.MISMATCH
    assert res.differing_outputs == ("summary.json",)


def test_mismatch_without_capsule_even_if_difference_small():
    a = receipt([("summary.json", SHA_A)])
    b = receipt([("summary.json", SHA_B)])
    res = compare_executions(a, b, capsule=None)
    assert res.classification is ReproClassification.MISMATCH


# ---------------------------------------------------------------- nondeterminism


def test_nondeterministic_declared():
    cap = capsule(nondeterministic_outputs=[
        NondeterminismDecl(pattern="run_*.log", reason="timestamps")])
    a = receipt([("summary.json", SHA_A), ("run_1.log", SHA_A)])
    b = receipt([("summary.json", SHA_A), ("run_1.log", SHA_B)])
    res = compare_executions(a, b, cap)
    assert res.classification is ReproClassification.NONDETERMINISTIC_DECLARED


def test_nondeterministic_decl_does_not_cover_other_files():
    cap = capsule(nondeterministic_outputs=[
        NondeterminismDecl(pattern="run_*.log", reason="timestamps")])
    a = receipt([("summary.json", SHA_A), ("run_1.log", SHA_A)])
    b = receipt([("summary.json", SHA_B), ("run_1.log", SHA_B)])
    res = compare_executions(a, b, cap)
    assert res.classification is ReproClassification.MISMATCH


def test_nondeterminism_declaration_required():
    a = receipt([("summary.json", SHA_A)])
    b = receipt([("summary.json", SHA_B)])
    # even WITH a semantic-style tolerance mindset, no declaration → MISMATCH
    assert compare_executions(a, b, capsule()).classification is \
        ReproClassification.MISMATCH


# ---------------------------------------------------------------- semantic


def _json_bytes(obj) -> bytes:
    return json.dumps(obj, sort_keys=True).encode()


def test_semantic_with_declared_rule_and_content():
    cap = capsule(semantic_rules=[
        SemanticRule(rule_id="float-tol", applies_to="*.json",
                     tolerance=1e-6)])
    a = receipt([("summary.json", SHA_A)])
    b = receipt([("summary.json", SHA_B)])
    res = compare_executions(
        a, b, cap,
        content_a=lambda p: _json_bytes({"mean": 2.9}),
        content_b=lambda p: _json_bytes({"mean": 2.9 + 1e-9}),
    )
    assert res.classification is ReproClassification.REPRODUCED_SEMANTIC


def test_semantic_without_rule_is_never_semantic():
    cap = capsule()  # no semantic_rules declared
    a = receipt([("summary.json", SHA_A)])
    b = receipt([("summary.json", SHA_B)])
    res = compare_executions(
        a, b, cap,
        content_a=lambda p: _json_bytes({"mean": 2.9}),
        content_b=lambda p: _json_bytes({"mean": 2.9 + 1e-12}),
    )
    assert res.classification is ReproClassification.MISMATCH


def test_semantic_rule_without_content_loaders_is_mismatch():
    """Hashes alone can never prove float equality — without content evidence
    an applicable rule cannot be evaluated, so the output stays unexplained."""
    cap = capsule(semantic_rules=[
        SemanticRule(rule_id="float-tol", applies_to="*.json",
                     tolerance=1e-6)])
    a = receipt([("summary.json", SHA_A)])
    b = receipt([("summary.json", SHA_B)])
    assert compare_executions(a, b, cap).classification is \
        ReproClassification.MISMATCH


def test_semantic_rule_exceeded_tolerance_is_mismatch():
    cap = capsule(semantic_rules=[
        SemanticRule(rule_id="float-tol", applies_to="*.json",
                     tolerance=1e-6)])
    a = receipt([("summary.json", SHA_A)])
    b = receipt([("summary.json", SHA_B)])
    res = compare_executions(
        a, b, cap,
        content_a=lambda p: _json_bytes({"mean": 2.9}),
        content_b=lambda p: _json_bytes({"mean": 2.9 + 0.1}),
    )
    assert res.classification is ReproClassification.MISMATCH


def test_semantic_rule_on_non_json_content_is_mismatch():
    cap = capsule(semantic_rules=[
        SemanticRule(rule_id="float-tol", applies_to="*", tolerance=1e-6)])
    a = receipt([("table.txt", SHA_A)])
    b = receipt([("table.txt", SHA_B)])
    res = compare_executions(a, b, cap,
                             content_a=lambda p: b"not json",
                             content_b=lambda p: b"not json!")
    assert res.classification is ReproClassification.MISMATCH


def test_semantic_only_for_paths_covered_by_rule():
    cap = capsule(semantic_rules=[
        SemanticRule(rule_id="float-tol", applies_to="results/*.json",
                     tolerance=1e-6)])
    outputs = [("results/a.json", SHA_A), ("results/b.json", SHA_A)]
    a = receipt(outputs)
    b = receipt([("results/a.json", SHA_B), ("results/b.json", SHA_C)])
    loaders = {"results/a.json": ({"v": 1.0}, {"v": 1.0 + 1e-9}),
               "results/b.json": ({"v": 1.0}, {"v": 2.0})}
    res = compare_executions(
        a, b, cap,
        content_a=lambda p: _json_bytes(loaders[p][0]),
        content_b=lambda p: _json_bytes(loaders[p][1]),
    )
    assert res.classification is ReproClassification.MISMATCH
    assert "results/b.json" in res.notes[0]


def test_semantic_and_nondeterminism_mixed():
    cap = capsule(
        nondeterministic_outputs=[NondeterminismDecl(pattern="run.log",
                                                     reason="clock")],
        semantic_rules=[SemanticRule(rule_id="t", applies_to="*.json",
                                     tolerance=1e-6)])
    a = receipt([("summary.json", SHA_A), ("run.log", SHA_A)])
    b = receipt([("summary.json", SHA_B), ("run.log", SHA_C)])
    res = compare_executions(
        a, b, cap,
        content_a=lambda p: _json_bytes({"v": 1.0}),
        content_b=lambda p: _json_bytes({"v": 1.0 + 1e-9}),
    )
    assert res.classification is ReproClassification.REPRODUCED_SEMANTIC
    assert set(res.differing_outputs) == {"summary.json", "run.log"}


# ---------------------------------------------------------------- end-to-end


def test_pilot_end_to_end_exact_reproduction(tmp_path):
    """Two real runner executions of the committed pilot capsule classify as
    REPRODUCED_EXACT (integration of WP4+WP5+WP6 without any backend magic)."""
    import shutil
    import sys
    from pathlib import Path

    from paper_factory.reproduction import LocalReproductionRunner

    fixture = Path(__file__).parent / "fixtures" / "repro_pilot"
    cap = ReproductionCapsule.model_validate_json(
        (fixture / "capsule.json").read_text(encoding="utf-8"))
    cap = cap.model_copy(update={"command": [sys.executable, *cap.command[1:]]})

    runner = LocalReproductionRunner()
    roots = []
    for tag in ("a", "b"):
        root = tmp_path / tag
        shutil.copytree(fixture, root)
        roots.append(root)
    r1 = runner.run(cap, roots[0])
    r2 = runner.run(cap, roots[1])
    assert compare_executions(r1, r2, cap).classification is \
        ReproClassification.REPRODUCED_EXACT


def test_comparison_result_value_equality():
    a = compare_executions(receipt([("s.json", SHA_A)]),
                           receipt([("s.json", SHA_A)]))
    b = compare_executions(receipt([("s.json", SHA_A)]),
                           receipt([("s.json", SHA_A)]))
    assert a == b
    assert "REPRODUCED_EXACT" in repr(a)
