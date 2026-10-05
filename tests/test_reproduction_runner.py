"""Runner tests for WP5: real subprocess executions of the deterministic
synthetic pilot (tests/fixtures/repro_pilot) plus adversarial cases for
declared-input integrity, undeclared outputs, failure and timeout. No network,
no LLM: test commands are small Python one-liners on tempfiles."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

from paper_factory.reproduction import (
    CapsuleIntegrityError,
    FileRef,
    LocalReproductionRunner,
    ReproductionCapsule,
    UndeclaredOutputError,
    sha256_file,
)

FIXTURE = Path(__file__).parent / "fixtures" / "repro_pilot"


def pilot_capsule() -> ReproductionCapsule:
    """Load the pre-built pilot capsule; swap the interpreter for the test's
    own executable so the committed JSON stays free of absolute paths."""
    c = ReproductionCapsule.model_validate_json(
        (FIXTURE / "capsule.json").read_text(encoding="utf-8"))
    return c.model_copy(update={"command": [sys.executable, *c.command[1:]]})


def pilot_root(tmp_path: Path) -> Path:
    root = tmp_path / "pilot"
    shutil.copytree(FIXTURE, root)
    return root


def test_pilot_runs_and_hashes_outputs(tmp_path):
    root = pilot_root(tmp_path)
    receipt = LocalReproductionRunner().run(pilot_capsule(), root)

    assert receipt.status == "completed"
    assert receipt.exit_code == 0
    assert receipt.failure_reason is None
    by_path = {f.rel_path: f.sha256 for f in receipt.outputs}
    assert by_path == {
        "summary.json": sha256_file(root / "summary.json"),
        "table.txt": sha256_file(root / "table.txt"),
    }
    assert all(len(h) == 64 for h in by_path.values())


def test_pilot_reproduction_two_runs_identical(tmp_path):
    """The WP5 pilot proof: same capsule, two executions → identical output
    hashes and capsule_digest; only per-run identity differs."""
    root_a = pilot_root(tmp_path / "a")
    root_b = pilot_root(tmp_path / "b")
    capsule = pilot_capsule()
    r1 = LocalReproductionRunner().run(capsule, root_a)
    r2 = LocalReproductionRunner().run(capsule, root_b)

    assert {(f.rel_path, f.sha256) for f in r1.outputs} == \
        {(f.rel_path, f.sha256) for f in r2.outputs}
    assert r1.capsule_digest == r2.capsule_digest
    assert r1.execution_id != r2.execution_id
    assert r1.started_at != r2.started_at


def test_pilot_summary_content_is_deterministic(tmp_path):
    root = pilot_root(tmp_path)
    LocalReproductionRunner().run(pilot_capsule(), root)
    summary = json.loads((root / "summary.json").read_text(encoding="utf-8"))
    assert summary == {"max": 4.75, "mean": 2.875, "min": 1.5, "n": 4,
                       "spread": 3.25}


def test_declared_input_hash_mismatch_fails_visible(tmp_path):
    root = pilot_root(tmp_path)
    (root / "input.csv").write_text("name,value\nx,999\n", encoding="utf-8")
    with pytest.raises(CapsuleIntegrityError, match="hash mismatch"):
        LocalReproductionRunner().run(pilot_capsule(), root)


def test_declared_input_missing_fails_visible(tmp_path):
    root = pilot_root(tmp_path)
    (root / "input.csv").unlink()
    with pytest.raises(CapsuleIntegrityError, match="missing"):
        LocalReproductionRunner().run(pilot_capsule(), root)


def _script_capsule(tmp_path, code: str, outputs):
    root = tmp_path / "case"
    root.mkdir()
    script = root / "case.py"
    script.write_text(code, encoding="utf-8")
    capsule = ReproductionCapsule(
        capsule_id="case-1",
        command=[sys.executable, "case.py"],
        code_refs=[FileRef(rel_path="case.py", sha256=sha256_file(script))],
        environment={"python_version": "3", "platform": "test"},
        expected_outputs=outputs,
        producer={"kind": "pf_native", "name": "test", "version": "0"},
    )
    return capsule, root


def test_undeclared_output_fails_visible(tmp_path):
    capsule, root = _script_capsule(
        tmp_path,
        "from pathlib import Path\n"
        "Path('summary.json').write_text('{}')\n"
        "Path('scratch.bin').write_text('undeclared')\n",
        outputs=["summary.json"])
    with pytest.raises(UndeclaredOutputError, match="scratch.bin"):
        LocalReproductionRunner().run(capsule, root)


def test_undeclared_modified_input_fails_visible(tmp_path):
    capsule, root = _script_capsule(
        tmp_path,
        "from pathlib import Path\n"
        "p = Path('case.py')\n"
        "p.write_text(p.read_text() + '# touched\\n')\n"
        "Path('summary.json').write_text('{}')\n",
        outputs=["summary.json"])
    with pytest.raises(UndeclaredOutputError, match="case.py"):
        LocalReproductionRunner().run(capsule, root)


def test_deleted_declared_input_fails_visible(tmp_path):
    """Deletion detection (review B-MINOR-1): a process that deletes a
    declared input destroys evidence the capsule is bound to — fail-visible,
    not a silent pass."""
    root = tmp_path / "case"
    root.mkdir()
    (root / "case.py").write_text("pass\n", encoding="utf-8")
    (root / "input.csv").write_text("v\n1\n", encoding="utf-8")
    capsule = ReproductionCapsule(
        capsule_id="case-del",
        command=[sys.executable, "case.py"],
        code_refs=[FileRef(rel_path="case.py",
                           sha256=sha256_file(root / "case.py"))],
        input_refs=[FileRef(rel_path="input.csv",
                            sha256=sha256_file(root / "input.csv"))],
        environment={"python_version": "3", "platform": "test"},
        expected_outputs=["summary.json"],
        producer={"kind": "pf_native", "name": "test", "version": "0"},
    )
    # run 1: deletes the declared input before the runner even snapshots? No —
    # the deletion must happen INSIDE the executed process, so the capsule
    # command itself removes the input (case.py is bound, so drive the
    # deletion from a helper the command invokes).
    (root / "case.py").write_text(
        "from pathlib import Path\n"
        "Path('input.csv').unlink()\n"
        "Path('summary.json').write_text('{}')\n",
        encoding="utf-8")
    capsule = capsule.model_copy(update={
        "code_refs": [FileRef(rel_path="case.py",
                              sha256=sha256_file(root / "case.py"))]})
    with pytest.raises(UndeclaredOutputError, match="input.csv"):
        LocalReproductionRunner().run(capsule, root)


def test_declared_nondeterministic_output_allowed(tmp_path):
    capsule, root = _script_capsule(
        tmp_path,
        "from pathlib import Path\n"
        "Path('summary.json').write_text('{}')\n"
        "Path('run.log').write_text('log line\\n')\n",
        outputs=["summary.json"])
    capsule = capsule.model_copy(update={
        "nondeterministic_outputs": [{"pattern": "run.log",
                                      "reason": "diagnostic log"}]})
    # NOTE: run.log is still an undeclared *write* — the capsule must also
    # expect it. Declared-nondeterministic only relaxes the differential.
    capsule = capsule.model_copy(update={"expected_outputs":
                                         ["summary.json", "run.log"]})
    receipt = LocalReproductionRunner().run(capsule, root)
    assert receipt.status == "completed"
    assert {f.rel_path for f in receipt.outputs} == {"summary.json", "run.log"}


def test_nonzero_exit_recorded_not_raised(tmp_path):
    capsule, root = _script_capsule(
        tmp_path,
        "import sys\nsys.stderr.write('boom\\n')\nsys.exit(3)\n",
        outputs=["summary.json"])
    (root / "summary.json").write_text("{}", encoding="utf-8")
    receipt = LocalReproductionRunner().run(capsule, root)
    assert receipt.status == "failed"
    assert receipt.exit_code == 3
    assert "code 3" in receipt.failure_reason
    assert len(receipt.stderr_sha256) == 64


def test_timeout_recorded_not_raised(tmp_path):
    capsule, root = _script_capsule(
        tmp_path,
        "import time\ntime.sleep(30)\n"
        "from pathlib import Path\nPath('summary.json').write_text('{}')\n",
        outputs=["summary.json"])
    receipt = LocalReproductionRunner().run(capsule, root, timeout=1.0)
    assert receipt.status == "timeout"
    assert receipt.exit_code is None
    assert "timeout" in receipt.failure_reason


def test_cwd_semantics(tmp_path):
    capsule, root = _script_capsule(
        tmp_path,
        "from pathlib import Path\n"
        "Path('summary.json').write_text('{}')\n",
        outputs=["sub/summary.json"])
    sub = root / "sub"
    sub.mkdir()
    # script lives at root but runs in sub/; relocate it there
    script = root / "case.py"
    script.rename(sub / "case.py")
    capsule = capsule.model_copy(update={
        "cwd": "sub",
        "command": [sys.executable, "case.py"],
        "code_refs": [FileRef(rel_path="sub/case.py",
                              sha256=sha256_file(sub / "case.py"))],
    })
    receipt = LocalReproductionRunner().run(capsule, root)
    assert receipt.status == "completed"
    # output rel_paths are always relative to the capsule root, never cwd
    assert [f.rel_path for f in receipt.outputs] == ["sub/summary.json"]


def test_missing_capsule_root_fails(tmp_path):
    with pytest.raises(FileNotFoundError):
        LocalReproductionRunner().run(pilot_capsule(), tmp_path / "nope")


def test_pilot_capsule_fixture_loads_and_is_coherent():
    """The committed fixture JSON must be loadable, and its declared hashes
    must match the committed files (pre-run verification, from the fixture)."""
    capsule = ReproductionCapsule.model_validate_json(
        (FIXTURE / "capsule.json").read_text(encoding="utf-8"))
    for ref in [*capsule.code_refs, *capsule.config_refs, *capsule.input_refs]:
        assert sha256_file(FIXTURE / ref.rel_path) == ref.sha256
    assert len(capsule.capsule_digest) == 64
