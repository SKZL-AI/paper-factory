"""v1.4 WP-A/WP-B proof: backend conformance suite + three-way reproduction.

Runs the deterministic synthetic pilot capsule (tests/fixtures/repro_pilot)
once per registered backend (local runner, Snakemake, Nextflow) on separate
copies, classifies every pair with compare_executions (expect pairwise
REPRODUCED_EXACT), then executes the pytest conformance suite
(tests/conformance) and records its per-backend verdict matrix.

Real local CPU execution of tiny stdlib scripts — no network (beyond the
one-time Nextflow install itself), no LLM, no HoH. Fails visibly (exit 1)
when a backend is unavailable, any classification is not REPRODUCED_EXACT,
or any conformance case fails. The machine-readable JSON contains only
relative paths and hashes — no absolute paths leave this script; the
conformance suite runs under a fresh pytest basetemp (never the shared
/tmp/pytest-of-sai tree).

Usage:
    python -m scripts.proof_v14_nextflow_conformance --out-dir docs/reports
"""
from __future__ import annotations

import argparse
import json
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from itertools import combinations
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from paper_factory.reproduction import (
    LocalReproductionRunner,
    NextflowBackend,
    ReproductionCapsule,
    SnakemakeBackend,
    compare_executions,
    nextflow_binary,
    snakemake_binary,
)

FIXTURE = REPO / "tests" / "fixtures" / "repro_pilot"


def _receipt_side(receipt) -> dict:
    return {
        "backend": receipt.backend.model_dump(mode="json"),
        "status": receipt.status,
        "exit_code": receipt.exit_code,
        "failure_reason": receipt.failure_reason,
        "capsule_digest": receipt.capsule_digest,
        "outputs": {f.rel_path: f.sha256 for f in receipt.outputs},
        "stdout_sha256": receipt.stdout_sha256,
        "stderr_sha256": receipt.stderr_sha256,
    }


def _java_version() -> str:
    try:
        proc = subprocess.run(["java", "-version"], capture_output=True,
                              timeout=30, check=False)
        blob = (proc.stdout + proc.stderr).decode("utf-8", "replace")
        match = re.search(r'version\s+"([^"]+)"', blob)
        return match.group(1) if match else "unknown"
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"


def run_three_way(capsule: ReproductionCapsule, work: Path) -> dict:
    """One execution per backend on separate copies; pairwise differential."""
    sides: dict[str, dict] = {}
    receipts = {}
    backends = {
        "local_runner": (LocalReproductionRunner(), None),
        "snakemake_backend": (SnakemakeBackend(), "snakemake-run"),
        "nextflow_backend": (NextflowBackend(), "nextflow-run"),
    }
    for side, (runner, run_dir_name) in backends.items():
        root = work / side / "pilot"
        root.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(FIXTURE, root)
        kwargs = {"timeout": 300.0}
        if run_dir_name is not None:
            kwargs["run_dir"] = work / run_dir_name
        receipt = runner.run(capsule, root, **kwargs)
        receipts[side] = receipt
        sides[side] = _receipt_side(receipt)

    comparisons = []
    for a_name, b_name in combinations(sorted(receipts), 2):
        comparison = compare_executions(receipts[a_name], receipts[b_name],
                                        capsule)
        comparisons.append({
            "a": a_name,
            "b": b_name,
            "classification": comparison.classification.value,
            "differing_outputs": list(comparison.differing_outputs),
            "missing_outputs": list(comparison.missing_outputs),
            "notes": list(comparison.notes),
        })
    return {"sides": sides, "comparisons": comparisons}


_VERDICT_RE = re.compile(
    r"^(tests/conformance/[^:]+)::([A-Za-z0-9_]+)(?:\[([^\]]+)\])?\s+"
    r"(PASSED|SKIPPED|FAILED)")


def run_conformance_matrix(basetemp: Path) -> dict:
    """Execute the pytest conformance suite under a fresh basetemp and parse
    the per-case verdicts into {case: {backend: verdict}}."""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/conformance",
         "-v", "--tb=no", f"--basetemp={basetemp}"],
        cwd=REPO, capture_output=True, text=True, timeout=1800, check=False)
    matrix: dict[str, dict[str, str]] = {}
    for line in proc.stdout.splitlines():
        match = _VERDICT_RE.match(line.strip())
        if not match:
            continue
        _, case, param, verdict = match.groups()
        entry = matrix.setdefault(case, {})
        key = param or "all"
        entry[key] = verdict
    return {
        "pytest_exit_code": proc.returncode,
        "cases": matrix,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default="docs/reports",
                        help="report destination, relative to the repo root")
    args = parser.parse_args()
    out_dir = (REPO / args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if snakemake_binary() is None:
        print("FAIL: snakemake not installed (optional extra 'snakemake')",
              file=sys.stderr)
        return 1
    if nextflow_binary() is None:
        print("FAIL: nextflow not installed (binary launcher; see report)",
              file=sys.stderr)
        return 1

    capsule = ReproductionCapsule.model_validate_json(
        (FIXTURE / "capsule.json").read_text(encoding="utf-8"))
    capsule = capsule.model_copy(
        update={"command": [sys.executable, *capsule.command[1:]]})

    work = Path(tempfile.mkdtemp(prefix="pf-v14-proof-"))
    three_way = run_three_way(capsule, work)
    matrix = run_conformance_matrix(work / "pytest-basetemp")

    ok = all(c["classification"] == "REPRODUCED_EXACT"
             for c in three_way["comparisons"])
    ok = ok and matrix["pytest_exit_code"] == 0

    result = {
        "proof": "V1_4_NEXTFLOW_CONFORMANCE_PROOF",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "capsule": {
            "capsule_id": capsule.capsule_id,
            "capsule_digest": capsule.capsule_digest,
            "command": capsule.command[1:],
        },
        "environment": {
            "python_version": platform.python_version(),
            "platform": platform.platform(aliased=True),
            "java_version": _java_version(),
            "snakemake_version": three_way["sides"]["snakemake_backend"]
            ["backend"]["version"],
            "nextflow_version": three_way["sides"]["nextflow_backend"]
            ["backend"]["version"],
        },
        "three_way": three_way,
        "conformance_matrix": matrix,
    }
    json_path = out_dir / "V1_4_NEXTFLOW_CONFORMANCE_PROOF.json"
    json_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                         encoding="utf-8")

    md_path = out_dir / "V1_4_NEXTFLOW_CONFORMANCE_PROOF.md"
    md_path.write_text(_render_markdown(result), encoding="utf-8")

    print(f"three-way pairwise: "
          f"{[c['classification'] for c in three_way['comparisons']]}")
    print(f"conformance suite exit: {matrix['pytest_exit_code']}")
    print(f"wrote: {md_path.relative_to(REPO)}")
    print(f"wrote: {json_path.relative_to(REPO)}")
    return 0 if ok else 1


def _render_markdown(result: dict) -> str:
    env = result["environment"]
    sides = result["three_way"]["sides"]
    comps = result["three_way"]["comparisons"]
    matrix = result["conformance_matrix"]["cases"]

    all_outputs = sorted({p for s in sides.values() for p in s["outputs"]})
    hash_rows = []
    for rel_path in all_outputs:
        cells = " | ".join(
            f"`{sides[side]['outputs'].get(rel_path, '—')}`" for side in
            ["local_runner", "snakemake_backend", "nextflow_backend"])
        hash_rows.append(f"| `{rel_path}` | {cells} |")

    comp_lines = []
    for comp in comps:
        comp_lines.append(
            f"- `{comp['a']}` vs `{comp['b']}`: **{comp['classification']}** "
            f"(differing: {comp['differing_outputs'] or '—'}, "
            f"missing: {comp['missing_outputs'] or '—'})")

    backends = ["local", "snakemake", "nextflow"]
    matrix_rows = []
    for case in sorted(matrix):
        verdicts = matrix[case]
        cells = " | ".join(
            {"PASSED": "PASS", "SKIPPED": "SKIP", "FAILED": "FAIL"}.get(
                verdicts.get(b, "—"), verdicts.get(b, "—")) for b in backends)
        matrix_rows.append(f"| `{case}` | {cells} |")

    return f"""# v1.4 WP-A/WP-B — Backend Conformance Suite + Nextflow: proof

Generated: {result['generated_at_utc']}

## Gate

The same capsule (`{result['capsule']['capsule_id']}`, digest
`{result['capsule']['capsule_digest']}`) run via the PF native local runner,
the Snakemake backend and the Nextflow backend must produce identical
output hashes — pairwise `REPRODUCED_EXACT`. This run:
**{comps[0]['classification'] if all(c['classification'] == comps[0]['classification'] for c in comps) else 'MIXED'}** on all three pairs.

## Environment

- Python {env['python_version']}, {env['platform']}
- Java {env['java_version']}
- Snakemake {env['snakemake_version']} (optional extra, not a core dependency)
- Nextflow {env['nextflow_version']} (binary launcher, deliberately NOT a
  pip extra — install: `curl -s https://get.nextflow.io -o nextflow`,
  then place the launcher on PATH, in PF's venv bin dir, or in
  `<repo>/tools/`; the backend probes exactly those locations, PATH first)

## Method

- Capsule: deterministic synthetic pilot `tests/fixtures/repro_pilot`,
  executed once per backend on separate copies (staged run directories for
  the external backends, outside the caller's capsule root).
- Interpreters/consoles: real local CPU only — no LLM, no HoH.
- Classification: `compare_executions` (WP6 differential).
- Conformance: `tests/conformance` (parametrized per backend), verdict
  matrix below.

## Output hashes (SHA-256)

| output (rel. to capsule root) | local runner | snakemake backend | nextflow backend |
|---|---|---|---|
{chr(10).join(hash_rows)}

Pairwise classifications:

{chr(10).join(comp_lines)}

## Conformance matrix (WP-A suite, this run)

| case | local | snakemake | nextflow |
|---|---|---|---|
{chr(10).join(matrix_rows)}

Verdict legend: PASS = case passed for this backend; SKIP = case not
applicable to this backend (local runner has no external binary and creates
no backend scratch) or its binary is missing (then ALL cases of that backend
skip). pytest exit code: {result['conformance_matrix']['pytest_exit_code']}.

## Honest limits

- One rule / one process per capsule: the adapters map the capsule contract
  onto Snakemake/Nextflow, they do not orchestrate workflows; neither engine
  is ever PF's orchestrator.
- The Nextflow process deliberately declares no outputs: output evidence is
  PF's own post-hoc hash collection (identical semantics to the local
  runner). Consequence, pinned by the `partial_outputs` conformance case:
  a job that omits an expected output is recorded with fewer outputs and
  classified MISMATCH by the differential, while Snakemake's generated rule
  fails the job at the wrapper. Both behaviours are conformance-clean.
- The receipt's `exit_code` for the external backends is the wrapper's exit
  code (WP7 review B-MINOR-4 applies unchanged to WP-B).
- Same hard limits as the local runner: not a sandbox; writes outside the
  workdir subtree are not detected by the snapshot diff.

## Reproduce

    python -m scripts.proof_v14_nextflow_conformance --out-dir docs/reports

Machine-readable twin: `V1_4_NEXTFLOW_CONFORMANCE_PROOF.json` (same
directory; relative paths and hashes only).
"""


if __name__ == "__main__":
    raise SystemExit(main())
