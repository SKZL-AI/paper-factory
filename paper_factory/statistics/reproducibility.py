"""P10 Reproducibility: re-execute the project's own pipeline in a scratch
copy and compare outputs against the recorded results (hashes/values).

v1.3: a project may declare a versioned reproduction capsule at
``.paper-factory/reproduction/capsule.json``. When present, the capsule path
takes precedence over command discovery: the capsule is executed twice with
the native local runner and the two execution receipts are compared with the
reproduction differential. The capsule path is stricter (declared inputs,
content-addressed digest, undeclared-output detection) and makes P10 a real
PASS/FAIL gate instead of an honest DEGRADED note.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from ..core.results import Verdict
from ..core.util import sha256_file, utcnow, write_json
from ..dag.executor import NodeContext, NodeOutcome
from ..reproduction.capsule import ReproductionCapsule
from ..reproduction.differential import ReproClassification, compare_executions
from ..reproduction.runner import LocalReproductionRunner

CAPSULE_REL = Path(".paper-factory") / "reproduction" / "capsule.json"


def _discover_commands(root: Path) -> list[list[str]]:
    cmds = []
    if (root / "code" / "run_experiment.py").exists():
        cmds.append(["python3", "code/run_experiment.py"])
    if (root / "code" / "analyze.py").exists():
        cmds.append(["python3", "code/analyze.py"])
    return cmds


def _run_capsule_path(ctx: NodeContext, capsule_path: Path) -> NodeOutcome:
    root = ctx.workspace.target_root
    try:
        capsule = ReproductionCapsule.model_validate_json(
            capsule_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return NodeOutcome(Verdict.FAIL, {
            "reason": f"reproduction capsule invalid: {exc}",
            "capsule": str(capsule_path)})

    runner = LocalReproductionRunner()
    receipts = []
    # scratch copy (tempdir is PF-scratch; no deletes outside it)
    with tempfile.TemporaryDirectory(prefix="pf-repro-") as tmp:
        for _ in range(2):
            work = Path(tempfile.mkdtemp(prefix="capsule-run-", dir=tmp))
            shutil.copytree(root, work, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns(
                                ".paper-factory", ".git", "__pycache__",
                                "node_modules"))
            receipts.append(runner.run(capsule, work))

    comparison = compare_executions(receipts[0], receipts[1], capsule)
    report = {
        "checked_at": utcnow(),
        "mode": "capsule",
        "capsule_id": capsule.capsule_id,
        "capsule_digest": capsule.capsule_digest,
        "classification": comparison.classification.value,
        "differing_outputs": list(comparison.differing_outputs),
        "missing_outputs": list(comparison.missing_outputs),
        "notes": list(comparison.notes),
        "receipts": [json.loads(r.model_dump_json()) for r in receipts],
    }
    write_json(ctx.workspace.reports_dir / "reproducibility.json", report)

    cls = comparison.classification
    if cls is ReproClassification.REPRODUCED_EXACT:
        return NodeOutcome(Verdict.PASS, {
            "capsule_digest": capsule.capsule_digest,
            "classification": cls.value})
    if cls in (ReproClassification.REPRODUCED_SEMANTIC,
               ReproClassification.NONDETERMINISTIC_DECLARED):
        return NodeOutcome(Verdict.PASS, {
            "capsule_digest": capsule.capsule_digest,
            "classification": cls.value,
            "note": "accepted via declared semantic rules / nondeterminism "
                    "declarations — recorded honestly"})
    if cls is ReproClassification.UNAVAILABLE:
        return NodeOutcome(Verdict.DEGRADED, {
            "reason": "capsule execution unavailable",
            "notes": list(comparison.notes)})
    return NodeOutcome(Verdict.FAIL, {
        "reason": f"reproduction {cls.value}",
        "capsule_digest": capsule.capsule_digest,
        "differing_outputs": list(comparison.differing_outputs),
        "notes": list(comparison.notes)})


def run_reproducibility(ctx: NodeContext) -> NodeOutcome:
    root = ctx.workspace.target_root
    capsule_path = root / CAPSULE_REL
    if capsule_path.exists():
        return _run_capsule_path(ctx, capsule_path)
    cmds = _discover_commands(root)
    if not cmds:
        return NodeOutcome(Verdict.DEGRADED, {"reason": "no reproduction commands discovered"})

    recorded = {}
    for f in (root / "results").glob("*.json"):
        recorded[f.name] = sha256_file(f)
    for f in (root / "results").glob("*.csv"):
        recorded[f.name] = sha256_file(f)

    # scratch copy (tempdir is PF-scratch; no deletes outside it)
    with tempfile.TemporaryDirectory(prefix="pf-repro-") as tmp:
        work = Path(tmp) / "proj"
        shutil.copytree(root, work, ignore=shutil.ignore_patterns(
            ".paper-factory", ".git", "__pycache__", "node_modules"))
        runs = []
        for cmd in cmds:
            proc = subprocess.run(cmd, cwd=work, capture_output=True, text=True, timeout=600)
            runs.append({"cmd": cmd, "exit_code": proc.returncode})
        reproduced = {}
        for f in (work / "results").glob("*.json"):
            reproduced[f.name] = sha256_file(f)
        for f in (work / "results").glob("*.csv"):
            reproduced[f.name] = sha256_file(f)

    matches = {k: reproduced.get(k) == v for k, v in recorded.items()}
    report = {"checked_at": utcnow(), "commands": runs,
              "deterministic_reproduction": all(matches.values()),
              "mismatches": [k for k, ok in matches.items() if not ok]}
    write_json(ctx.workspace.reports_dir / "reproducibility.json", report)
    if any(r["exit_code"] != 0 for r in runs):
        return NodeOutcome(Verdict.FAIL, {"reason": "reproduction command failed", "commands": runs})
    if not all(matches.values()):
        return NodeOutcome(Verdict.DEGRADED, {"mismatches": report["mismatches"],
                                              "note": "non-deterministic outputs — recorded honestly"})
    return NodeOutcome(Verdict.PASS, {"files_reproduced": len(recorded)})
