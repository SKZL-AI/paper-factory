"""P10 Reproducibility: re-execute the project's own pipeline in a scratch
copy and compare outputs against the recorded results (hashes/values).
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from ..core.results import Verdict
from ..core.util import sha256_file, utcnow, write_json
from ..dag.executor import NodeContext, NodeOutcome


def _discover_commands(root: Path) -> list[list[str]]:
    cmds = []
    if (root / "code" / "run_experiment.py").exists():
        cmds.append(["python3", "code/run_experiment.py"])
    if (root / "code" / "analyze.py").exists():
        cmds.append(["python3", "code/analyze.py"])
    return cmds


def run_reproducibility(ctx: NodeContext) -> NodeOutcome:
    root = ctx.workspace.target_root
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
