"""WP7 proof: same Reproduction Capsule → local runner AND Snakemake backend.

Executes the deterministic synthetic pilot (tests/fixtures/repro_pilot) once
via LocalReproductionRunner and once via SnakemakeBackend on separate copies,
then classifies the pair with compare_executions. The proof gate from
docs/reports/DEEP_RESEARCH_DELTA_POST_V1_2.md §3.2: identical output hashes
→ REPRODUCED_EXACT.

Real local CPU execution of a tiny stdlib script — no network, no LLM, no
HoH. Fails visibly (exit 1) when snakemake is not installed or the
classification is not REPRODUCED_EXACT.

The machine-readable JSON contains only relative paths and hashes — no
absolute paths leave this script.

Usage:
    python -m scripts.proof_wp7_snakemake --out-dir docs/reports
"""
from __future__ import annotations

import argparse
import json
import platform
import shutil
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from paper_factory.reproduction import (
    LocalReproductionRunner,
    ReproductionCapsule,
    SnakemakeBackend,
    SnakemakeUnavailableError,
    compare_executions,
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

    capsule = ReproductionCapsule.model_validate_json(
        (FIXTURE / "capsule.json").read_text(encoding="utf-8"))
    # swap the interpreter for this run so the committed JSON stays free of
    # absolute paths; command[1:] is identical for both sides
    capsule = capsule.model_copy(
        update={"command": [sys.executable, *capsule.command[1:]]})

    work = Path(tempfile.mkdtemp(prefix="pf-wp7-proof-"))
    root_local = work / "local" / "pilot"
    root_snake = work / "snakemake" / "pilot"
    root_local.parent.mkdir(parents=True)
    root_snake.parent.mkdir(parents=True)
    shutil.copytree(FIXTURE, root_local)
    shutil.copytree(FIXTURE, root_snake)

    local_receipt = LocalReproductionRunner().run(capsule, root_local)
    try:
        snake_receipt = SnakemakeBackend().run(capsule, root_snake,
                                               run_dir=work / "snakemake-run")
    except SnakemakeUnavailableError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    comparison = compare_executions(local_receipt, snake_receipt, capsule)

    result = {
        "proof": "V1_3_WP7_SNAKEMAKE_PROOF",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "capsule": {
            "capsule_id": capsule.capsule_id,
            "capsule_digest": capsule.capsule_digest,
            "command": capsule.command[1:],  # argv without interpreter path
        },
        "snakemake_version": snake_receipt.backend.version,
        "python_version": platform.python_version(),
        "platform": platform.platform(aliased=True),
        "sides": {
            "local_runner": _receipt_side(local_receipt),
            "snakemake_backend": _receipt_side(snake_receipt),
        },
        "comparison": {
            "classification": comparison.classification.value,
            "differing_outputs": list(comparison.differing_outputs),
            "missing_outputs": list(comparison.missing_outputs),
            "notes": list(comparison.notes),
        },
    }
    json_path = out_dir / "V1_3_WP7_SNAKEMAKE_PROOF.json"
    json_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                         encoding="utf-8")

    md = _render_markdown(result)
    md_path = out_dir / "V1_3_WP7_SNAKEMAKE_PROOF.md"
    md_path.write_text(md, encoding="utf-8")

    print(f"classification: {comparison.classification.value}")
    print(f"snakemake: {result['snakemake_version']}")
    print(f"wrote: {md_path.relative_to(REPO)}")
    print(f"wrote: {json_path.relative_to(REPO)}")
    return 0 if comparison.classification.value == "REPRODUCED_EXACT" else 1


def _render_markdown(result: dict) -> str:
    sides = result["sides"]
    comp = result["comparison"]
    rows = []
    outputs_a = sides["local_runner"]["outputs"]
    outputs_b = sides["snakemake_backend"]["outputs"]
    for rel_path in sorted(set(outputs_a) | set(outputs_b)):
        rows.append(
            f"| `{rel_path}` | `{outputs_a.get(rel_path, '—')}` | "
            f"`{outputs_b.get(rel_path, '—')}` |")

    return f"""# v1.3 WP7 — Snakemake as first workflow consumer: proof

Generated: {result['generated_at_utc']}

## Gate

From `docs/reports/DEEP_RESEARCH_DELTA_POST_V1_2.md` §3.2: the same capsule
run via the PF native local runner and via the Snakemake backend must
produce identical output hashes (`REPRODUCED_EXACT`), or honestly justified
semantic equality. This run: **{comp['classification']}**.

## Method

- Capsule: `{result['capsule']['capsule_id']}` (digest
  `{result['capsule']['capsule_digest']}`), the deterministic synthetic
  pilot `tests/fixtures/repro_pilot`, executed twice on separate copies of
  the fixture root.
- Side A: `LocalReproductionRunner` (backend
  `{sides['local_runner']['backend']['kind']}/
  {sides['local_runner']['backend']['name']}`
  {sides['local_runner']['backend']['version']}).
- Side B: `SnakemakeBackend` (backend
  `{sides['snakemake_backend']['backend']['kind']}/
  {sides['snakemake_backend']['backend']['name']}`
  {sides['snakemake_backend']['backend']['version']}), one generated rule
  per capsule, `--cores 1`, staged run directory outside the capsule root.
- Classification: `compare_executions` (WP6 differential). Real local CPU
  only — no network, no LLM, no HoH.

## Environment

- Snakemake {result['snakemake_version']} (optional extra, not a core
  dependency)
- Python {result['python_version']}, {result['platform']}

## Output hashes (SHA-256)

| output (rel. to capsule root) | local runner | snakemake backend |
|---|---|---|
{chr(10).join(rows)}

Both sides exit_code={sides['local_runner']['exit_code']}/
{sides['snakemake_backend']['exit_code']}, status
`{sides['local_runner']['status']}`/`{sides['snakemake_backend']['status']}`.
Machine-readable twin: `V1_3_WP7_SNAKEMAKE_PROOF.json` (same directory).

## Honest limits

- One rule per capsule: the adapter maps the capsule contract onto
  Snakemake, it does not orchestrate workflows; Snakemake is never PF's
  orchestrator.
- The staged execution protects the caller's tree from `.snakemake`
  metadata; output hashes are unaffected (staged inputs are verified
  byte-identical before the run).
- Same hard limits as the local runner: not a sandbox; writes outside the
  workdir subtree are not detected by the snapshot diff.

## Reproduce

    python -m scripts.proof_wp7_snakemake --out-dir docs/reports
"""


if __name__ == "__main__":
    raise SystemExit(main())
