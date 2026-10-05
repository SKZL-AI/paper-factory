"""P10 capsule path: a project that declares
``.paper-factory/reproduction/capsule.json`` is reproduced via the native
local runner and classified with the reproduction differential, instead of the
legacy command-discovery heuristic."""
from __future__ import annotations

import json
import platform
import sys
from pathlib import Path

from paper_factory.core.config import (
    MarkingRegistry,
    PaperFactoryConfig,
    ProviderPolicyConfig,
    ProvidersConfig,
)
from paper_factory.core.results import Verdict
from paper_factory.dag.executor import NodeContext
from paper_factory.reproduction.capsule import (
    EnvironmentIdentity,
    FileRef,
    ReproductionCapsule,
    sha256_file,
)
from paper_factory.state.store import Workspace
from paper_factory.statistics.reproducibility import run_reproducibility
from paper_factory.verification.contract import BackendIdentity

ANALYZE = (
    "import csv, json, pathlib\n"
    "rows = list(csv.DictReader(open('input.csv')))\n"
    "vals = [int(r['v']) for r in rows]\n"
    "pathlib.Path('results').mkdir(exist_ok=True)\n"
    "pathlib.Path('results/summary.json').write_text(json.dumps("
    "{'n': len(vals), 'total': sum(vals)}, sort_keys=True))\n"
)


def _ctx(tmp_path: Path) -> NodeContext:
    return NodeContext(workspace=Workspace(tmp_path), run_id="test-p10-capsule",
                       config=PaperFactoryConfig(), providers=ProvidersConfig(),
                       policy=ProviderPolicyConfig(), marking=MarkingRegistry(),
                       offline=True, strict=True)


def _env() -> EnvironmentIdentity:
    return EnvironmentIdentity(
        python_version=platform.python_version(),
        platform=f"{sys.platform}-{platform.machine()}",
    )


def _producer() -> BackendIdentity:
    return BackendIdentity(kind="pf_native", name="p10-capsule-test",
                           version="test")


def _write_project(root: Path, *, analyze: str = ANALYZE,
                   input_csv: str = "v\n1\n2\n3\n") -> None:
    (root / "code").mkdir(parents=True)
    (root / "code" / "analyze.py").write_text(analyze)
    (root / "input.csv").write_text(input_csv)


def _write_capsule(root: Path, *, expected=("results/*.json",)) -> Path:
    capsule = ReproductionCapsule(
        capsule_id="p10-test-capsule",
        command=[sys.executable, "code/analyze.py"],
        code_refs=[FileRef(rel_path="code/analyze.py",
                           sha256=sha256_file(root / "code" / "analyze.py"))],
        input_refs=[FileRef(rel_path="input.csv",
                            sha256=sha256_file(root / "input.csv"))],
        environment=_env(),
        expected_outputs=list(expected),
        producer=_producer(),
    )
    cap = root / ".paper-factory" / "reproduction" / "capsule.json"
    cap.parent.mkdir(parents=True, exist_ok=True)
    cap.write_text(capsule.model_dump_json(indent=2))
    return cap


def test_p10_capsule_path_passes_on_deterministic_project(tmp_path: Path):
    _write_project(tmp_path)
    _write_capsule(tmp_path)
    outcome = run_reproducibility(_ctx(tmp_path))
    assert outcome.verdict is Verdict.PASS
    assert outcome.detail["classification"] == "REPRODUCED_EXACT"
    report = json.loads((tmp_path / ".paper-factory" / "reports"
                         / "reproducibility.json").read_text())
    assert report["mode"] == "capsule"
    assert len(report["receipts"]) == 2
    assert {r["capsule_digest"] for r in report["receipts"]} == {
        report["capsule_digest"]}


def test_p10_capsule_mismatch_fails(tmp_path: Path):
    # seeded-but-varying output: the project itself is nondeterministic
    _write_project(tmp_path, analyze=(
        "import pathlib, uuid\n"
        "pathlib.Path('results').mkdir(exist_ok=True)\n"
        "pathlib.Path('results/summary.json').write_text("
        "'{\"id\": \"' + uuid.uuid4().hex + '\"}')\n"
    ))
    _write_capsule(tmp_path)
    outcome = run_reproducibility(_ctx(tmp_path))
    assert outcome.verdict is Verdict.FAIL
    assert "MISMATCH" in outcome.detail["reason"]


def test_p10_capsule_invalid_json_fails_visibly(tmp_path: Path):
    _write_project(tmp_path)
    cap = tmp_path / ".paper-factory" / "reproduction" / "capsule.json"
    cap.parent.mkdir(parents=True, exist_ok=True)
    cap.write_text("{not json")
    outcome = run_reproducibility(_ctx(tmp_path))
    assert outcome.verdict is Verdict.FAIL
    assert "invalid" in outcome.detail["reason"]


def test_p10_without_capsule_keeps_legacy_discovery(tmp_path: Path):
    # no capsule, no discoverable commands -> honest DEGRADED (v1.2 behavior)
    outcome = run_reproducibility(_ctx(tmp_path))
    assert outcome.verdict is Verdict.DEGRADED
    assert "no reproduction commands" in outcome.detail["reason"]
