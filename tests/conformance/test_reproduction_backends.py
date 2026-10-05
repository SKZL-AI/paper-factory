"""WP-A conformance suite: every case in `reproduction_backends.BACKENDS`
instantiated per registered backend (local, snakemake, nextflow).

Real local executions only — deterministic stdlib scripts and the synthetic
pilot fixture; no LLM, no HoH, no network. External backends skip honestly
when their binary is missing.
"""
from __future__ import annotations

import re
import tempfile
from pathlib import Path

import pytest

from paper_factory.reproduction import (
    CapsuleIntegrityError,
    LocalReproductionRunner,
    NondeterminismDecl,
    ReproClassification,
    UndeclaredOutputError,
    compare_executions,
)

from .reproduction_backends import (
    BACKENDS,
    ensure_available,
    pilot_capsule,
    pilot_root,
    script_capsule,
)

parametrized = pytest.mark.parametrize("backend", BACKENDS,
                                     ids=[b.name for b in BACKENDS])


# --------------------------------------------------------------------------- #
# 1. input binding
# --------------------------------------------------------------------------- #

@parametrized
def test_input_binding_hash_mismatch_fails_before_execution(backend, tmp_path):
    """A declared ref whose content changed must abort BEFORE anything runs:
    CapsuleIntegrityError, no receipt, and (external) no run directory."""
    ensure_available(backend)
    root = pilot_root(tmp_path)
    (root / "input.csv").write_text("name,value\nx,999\n", encoding="utf-8")
    run_dir = tmp_path / "run"
    with pytest.raises(CapsuleIntegrityError, match="hash mismatch"):
        backend.invoke(backend.factory(), pilot_capsule(), root, run_dir, 60.0)
    # the caller's tree is untouched and no backend scratch was created
    assert not (root / "summary.json").exists()
    if backend.has_external_binary:
        assert not run_dir.exists()


# --------------------------------------------------------------------------- #
# 2./3. output binding + undeclared outputs
# --------------------------------------------------------------------------- #

@parametrized
def test_output_binding_collects_declared_outputs(backend, tmp_path):
    ensure_available(backend)
    capsule = pilot_capsule()
    receipt = backend.invoke(backend.factory(), capsule,
                             pilot_root(tmp_path), tmp_path / "run", 120.0)
    assert receipt.status == "completed"
    assert receipt.exit_code == 0
    by_path = {f.rel_path: f.sha256 for f in receipt.outputs}
    assert set(by_path) == {"summary.json", "table.txt"}
    assert all(re.fullmatch(r"[0-9a-f]{64}", h) for h in by_path.values())
    # local-runner reference hashes must match byte for byte
    ref = LocalReproductionRunner().run(capsule, pilot_root(tmp_path, "ref"))
    assert by_path == {f.rel_path: f.sha256 for f in ref.outputs}


@parametrized
def test_undeclared_output_fails_visible(backend, tmp_path):
    ensure_available(backend)
    root = tmp_path / "case"
    root.mkdir()
    capsule = script_capsule(
        root,
        "from pathlib import Path\n"
        "Path('summary.json').write_text('{}')\n"
        "Path('scratch.bin').write_text('undeclared')\n",
        outputs=["summary.json"])
    with pytest.raises(UndeclaredOutputError, match="scratch.bin"):
        backend.invoke(backend.factory(), capsule, root, tmp_path / "run", 60.0)


# --------------------------------------------------------------------------- #
# 4. environment / backend identity
# --------------------------------------------------------------------------- #

@parametrized
def test_receipt_carries_honest_backend_identity(backend, tmp_path):
    ensure_available(backend)
    receipt = backend.invoke(backend.factory(), pilot_capsule(),
                             pilot_root(tmp_path), tmp_path / "run", 120.0)
    if backend.name == "local":
        assert receipt.backend.kind == "pf_native"
        assert receipt.backend.version
    else:
        assert receipt.backend.kind == "external"
        assert receipt.backend.name == backend.name
        assert receipt.backend.version and receipt.backend.version != "unknown"
        assert re.search(r"\d+\.\d+", receipt.backend.version)


# --------------------------------------------------------------------------- #
# 5./6. failure + timeout
# --------------------------------------------------------------------------- #

@parametrized
def test_failed_job_recorded_in_receipt_not_raised(backend, tmp_path):
    ensure_available(backend)
    root = tmp_path / "case"
    root.mkdir()
    capsule = script_capsule(
        root,
        "import sys\nsys.stderr.write('boom\\n')\nsys.exit(3)\n",
        outputs=["summary.json"])
    (root / "summary.json").write_text("{}", encoding="utf-8")
    receipt = backend.invoke(backend.factory(), capsule, root,
                             tmp_path / "run", 60.0)
    assert receipt.status == "failed"
    assert receipt.exit_code not in (0, None)
    assert receipt.failure_reason
    assert len(receipt.stderr_sha256) == 64


@parametrized
def test_timeout_recorded_not_raised(backend, tmp_path):
    ensure_available(backend)
    root = tmp_path / "case"
    root.mkdir()
    capsule = script_capsule(
        root,
        "import time\ntime.sleep(30)\n"
        "from pathlib import Path\nPath('summary.json').write_text('{}')\n",
        outputs=["summary.json"])
    receipt = backend.invoke(backend.factory(), capsule, root,
                             tmp_path / "run", timeout=1.0)
    assert receipt.status == "timeout"
    assert receipt.exit_code is None
    assert "timeout" in receipt.failure_reason


# --------------------------------------------------------------------------- #
# 7. duplicate execution
# --------------------------------------------------------------------------- #

@parametrized
def test_duplicate_execution_reproduced_exact(backend, tmp_path):
    ensure_available(backend)
    capsule = pilot_capsule()
    first = backend.invoke(backend.factory(), capsule,
                           pilot_root(tmp_path, "a"), tmp_path / "run-a", 120.0)
    second = backend.invoke(backend.factory(), capsule,
                            pilot_root(tmp_path, "b"), tmp_path / "run-b", 120.0)
    result = compare_executions(first, second, capsule)
    assert result.classification is ReproClassification.REPRODUCED_EXACT
    assert result.differing_outputs == ()
    assert result.missing_outputs == ()


# --------------------------------------------------------------------------- #
# 8. partial outputs
# --------------------------------------------------------------------------- #

@parametrized
def test_partial_outputs_recorded_and_differenced(backend, tmp_path,
                                                  monkeypatch):
    """A job that exits 0 but omits an expected output must never pass
    silently. Two honest behaviours exist: wrappers that declare outputs in
    the generated workflow (snakemake) fail the job outright; runners that
    collect outputs post-hoc (local, nextflow) record only what exists and
    the differential says MISMATCH/missing. Both are conformance-clean; a
    receipt claiming completion with the full output set would not be."""
    ensure_available(backend)

    def build(root_name: str, partial: bool):
        root = tmp_path / root_name
        root.mkdir()
        capsule = script_capsule(
            root,
            "import os\nfrom pathlib import Path\n"
            "Path('out1.txt').write_text('one\\n')\n"
            "Path('out2.txt').write_text('two\\n')\n"
            "if os.environ.get('PF_CONFORMANCE_PARTIAL'):\n"
            "    os.remove('out2.txt')\n",
            outputs=["out1.txt", "out2.txt"])
        if partial:
            monkeypatch.setenv("PF_CONFORMANCE_PARTIAL", "1")
        else:
            monkeypatch.delenv("PF_CONFORMANCE_PARTIAL", raising=False)
        receipt = backend.invoke(backend.factory(), capsule, root,
                                 tmp_path / f"run-{root_name}", 60.0)
        monkeypatch.delenv("PF_CONFORMANCE_PARTIAL", raising=False)
        return capsule, receipt

    capsule, full = build("full", partial=False)
    _, partial_receipt = build("partial", partial=True)

    assert full.status == "completed"
    assert {f.rel_path for f in full.outputs} == {"out1.txt", "out2.txt"}
    if partial_receipt.status == "completed":
        # post-hoc collection: fewer outputs, still honest; the
        # differential classifies the missing output as MISMATCH
        assert {f.rel_path for f in partial_receipt.outputs} == {"out1.txt"}
        result = compare_executions(full, partial_receipt, capsule)
        assert result.classification is ReproClassification.MISMATCH
        assert result.missing_outputs == ("out2.txt",)
    else:
        # the generated workflow declares the outputs: the wrapper fails
        # the job; nothing clean to compare -> UNAVAILABLE
        assert partial_receipt.status == "failed"
        assert partial_receipt.failure_reason
        result = compare_executions(full, partial_receipt, capsule)
        assert result.classification is ReproClassification.UNAVAILABLE


# --------------------------------------------------------------------------- #
# 9. cleanup: no scratch leaks, caller root unpolluted
# --------------------------------------------------------------------------- #

@parametrized
def test_cleanup_no_scratch_leak_with_private_run_dir(backend, tmp_path,
                                                      monkeypatch):
    ensure_available(backend)
    if not backend.has_external_binary:
        pytest.skip("local runner creates no backend scratch")
    probe = Path(tempfile.gettempdir())
    before = {p.name for p in probe.glob(backend.leak_glob)}
    capsule = pilot_capsule()
    receipt = backend.factory().run(capsule, pilot_root(tmp_path), timeout=120.0)
    assert receipt.status == "completed"
    leftover = {p.name for p in probe.glob(backend.leak_glob)} - before
    assert leftover == set(), f"leaked run directories: {leftover}"


@parametrized
def test_cleanup_caller_root_never_polluted(backend, tmp_path):
    """External backends stage: outputs and backend metadata must land in the
    run directory, never in the caller's capsule root. The local runner runs
    in place by design — there only backend-metadata absence applies."""
    ensure_available(backend)
    root = pilot_root(tmp_path)
    receipt = backend.invoke(backend.factory(), pilot_capsule(), root,
                             tmp_path / "run", 120.0)
    assert receipt.status == "completed"
    for meta in backend.metadata_dirs:
        assert not (root / meta).exists(), f"caller root polluted: {meta}"
    if backend.has_external_binary:
        assert not (root / "summary.json").exists()
        assert not (root / "table.txt").exists()
        # the staged copy (the audit trail) holds the real outputs instead
        staged = list((tmp_path / "run").rglob("summary.json"))
        assert staged, "no staged outputs found in the run directory"


# --------------------------------------------------------------------------- #
# 10. nondeterminism declarations
# --------------------------------------------------------------------------- #

@parametrized
def test_nondeterminism_declaration_classified_honestly(backend, tmp_path,
                                                        monkeypatch):
    """Same capsule, genuinely differing output: declared →
    NONDETERMINISTIC_DECLARED; undeclared → MISMATCH."""
    ensure_available(backend)

    def run_once(root_name: str, declared: bool):
        root = tmp_path / root_name
        root.mkdir()
        capsule = script_capsule(
            root,
            "import uuid\nfrom pathlib import Path\n"
            "Path('stable.txt').write_text('fixed\\n')\n"
            "Path('run.id').write_text(str(uuid.uuid4()) + '\\n')\n",
            outputs=["stable.txt", "run.id"])
        if declared:
            capsule = capsule.model_copy(update={"nondeterministic_outputs": [
                NondeterminismDecl(pattern="run.id",
                                   reason="unique run identifier")]})
        receipt = backend.invoke(backend.factory(), capsule, root,
                                 tmp_path / f"run-{root_name}", 60.0)
        return capsule, receipt

    declared_capsule, first = run_once("decl-a", declared=True)
    _, second = run_once("decl-b", declared=True)
    result = compare_executions(first, second, declared_capsule)
    assert result.classification is ReproClassification.NONDETERMINISTIC_DECLARED
    assert result.differing_outputs == ("run.id",)

    undeclared_capsule, third = run_once("undecl-a", declared=False)
    _, fourth = run_once("undecl-b", declared=False)
    result = compare_executions(third, fourth, undeclared_capsule)
    assert result.classification is ReproClassification.MISMATCH
    assert result.differing_outputs == ("run.id",)


# --------------------------------------------------------------------------- #
# 11. receipt generation
# --------------------------------------------------------------------------- #

@parametrized
def test_receipt_mandatory_fields_and_digest(backend, tmp_path):
    ensure_available(backend)
    capsule = pilot_capsule()
    receipt = backend.invoke(backend.factory(), capsule,
                             pilot_root(tmp_path), tmp_path / "run", 120.0)
    assert receipt.receipt_id and receipt.execution_id
    assert receipt.capsule_id == capsule.capsule_id
    assert receipt.capsule_digest == capsule.capsule_digest
    assert re.fullmatch(r"[0-9a-f]{64}", receipt.capsule_digest)
    assert receipt.status == "completed"
    assert receipt.backend is not None
    assert receipt.started_at <= receipt.finished_at
    assert re.fullmatch(r"[0-9a-f]{64}", receipt.stdout_sha256)
    assert re.fullmatch(r"[0-9a-f]{64}", receipt.stderr_sha256)
    assert receipt.failure_reason is None


# --------------------------------------------------------------------------- #
# 12. availability
# --------------------------------------------------------------------------- #

@parametrized
def test_unavailable_fails_visible_when_binary_missing(backend, tmp_path,
                                                       monkeypatch):
    if not backend.has_external_binary:
        pytest.skip("local runner has no external binary (always available)")
    ensure_available(backend)  # need the real module to patch its resolver
    monkeypatch.setattr(backend.binary_module, backend.binary_attr,
                        lambda: None)
    with pytest.raises(backend.unavailable_exc):
        backend.invoke(backend.factory(), pilot_capsule(),
                       pilot_root(tmp_path), tmp_path / "run", 60.0)


# --------------------------------------------------------------------------- #
# Three-way proof gate: the same capsule on every registered backend
# --------------------------------------------------------------------------- #

def test_three_way_reproduced_exact(tmp_path):
    """v1.4 proof gate: identical capsule run via local + snakemake +
    nextflow must be pairwise REPRODUCED_EXACT. Skips honestly while any
    registered backend is unavailable."""
    missing = [b.name for b in BACKENDS if not b.available]
    if missing:
        pytest.skip(f"backends unavailable: {missing}")

    from itertools import combinations

    capsule = pilot_capsule()
    receipts = {}
    for spec in BACKENDS:
        receipts[spec.name] = spec.invoke(
            spec.factory(), capsule, pilot_root(tmp_path, spec.name),
            tmp_path / f"run-{spec.name}", timeout=180.0)
        assert receipts[spec.name].status == "completed"

    for a_name, b_name in combinations(sorted(receipts), 2):
        result = compare_executions(receipts[a_name], receipts[b_name],
                                    capsule)
        assert result.classification is ReproClassification.REPRODUCED_EXACT, \
            f"{a_name} vs {b_name}: {result}"
        assert result.differing_outputs == ()
        assert result.missing_outputs == ()
