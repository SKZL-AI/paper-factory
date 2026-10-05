"""WP12 Pilot C: failure injections against the v1.3 synthetic repro pilot.

Three honest failure demonstrations against the capsule declared by
``pilots/v1-3-repro-synth/project`` (Pilot A of the v1.3 pilot matrix).
Each injection runs on a fresh copy in a tempfile scratch directory — the
pilot workspace itself is never modified. Real local execution only: no
network, no LLM, no HoH.

- C1 broken capsule:   ``capsule.json`` replaced with invalid JSON.
  Expectation: P10 FAIL with a visible "capsule invalid" reason (v1.3 makes
  a broken declaration a hard gate, not a silent skip).
- C2 output tampering: ``pilot_compute.py`` patched so the second execution
  diverges (uuid nonce in ``summary.json``; the capsule's code hash is
  updated honestly, so the declared code is exactly what runs). The two
  capsule executions then produce different output hashes.
  Expectation: classification MISMATCH → P10 FAIL, differing outputs on
  record.
- C3 backend unavailability: SnakemakeBackend with an empty PATH, executed
  via the system interpreter whose bin directory has no ``snakemake``.
  Expectation: SnakemakeUnavailableError (fail-visible, no fake receipt) —
  the honest UNAVAILABLE path. A positive control via the PF venv
  interpreter (snakemake installed) proves the probe is wired correctly.

The script fails visibly (exit 1) when any injection does NOT produce its
expected honest result — an unexpected PASS here would be a v1.3 defect.

The machine-readable JSON contains only relative paths and hashes — no
absolute paths leave this script. Requires Pilot A to have been built
(``pilots/v1-3-repro-synth/project/.paper-factory/reproduction/capsule.json``).

Usage:
    python -m scripts.pilot_injections_v13 --out-dir docs/reports/v1_3
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

PILOT = REPO / "pilots" / "v1-3-repro-synth" / "project"
CONFIG = REPO / "tests" / "e2e-config"
NONCE_ANCHOR = '    "spread": round(values[-1] - values[0], 6),'
NONCE_PATCH = (
    NONCE_ANCHOR + '\n    "nonce": __import__("uuid").uuid4().hex,'
)


def _utc() -> str:
    return datetime.now(UTC).isoformat()


def _sha256_text(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def _run_dag(project: Path, run_id: str) -> dict:
    """One real offline DAG execution; returns P10 status + detail + report."""
    proc = subprocess.run(
        [sys.executable, "-m", "paper_factory.cli.main",
         "--root", str(project), "--config-dir", str(CONFIG),
         "complete", "--offline", "--run-id", run_id],
        capture_output=True, text=True, timeout=600,
    )
    out = json.loads(proc.stdout)
    db = project / ".paper-factory" / "runs.sqlite"
    uri = f"file:{db}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    row = conn.execute(
        "SELECT status, detail FROM nodes WHERE run_id=? AND node_id='P10'",
        (run_id,)).fetchone()
    conn.close()
    report_path = project / ".paper-factory" / "reports" / "reproducibility.json"
    report = (json.loads(report_path.read_text(encoding="utf-8"))
              if report_path.exists() else None)
    return {
        "run_id": run_id,
        "cli_exit_code": proc.returncode,
        "overall": out["overall"],
        "p10_status": out["statuses"].get("P10"),
        "p10_detail": json.loads(row[1]) if row and row[1] else None,
        "reproducibility_report": report,
    }


def _fresh_copy(tmp: Path, name: str) -> Path:
    dst = tmp / name
    shutil.copytree(PILOT, dst, ignore=shutil.ignore_patterns("runs.sqlite*"))
    # our own scratch copy: stale reports/run state from Pilot A must not
    # leak into an injection as false evidence
    reports = dst / ".paper-factory" / "reports"
    if reports.exists():
        shutil.rmtree(reports)
    return dst


def injection_c1(tmp: Path) -> dict:
    proj = _fresh_copy(tmp, "c1-broken-capsule")
    cap = proj / ".paper-factory" / "reproduction" / "capsule.json"
    cap.write_text("{not json", encoding="utf-8")
    result = _run_dag(proj, "v13-inj-c1")
    detail = result["p10_detail"] or {}
    expected = (
        result["p10_status"] == "FAIL"
        and "invalid" in (detail.get("reason") or "")
        and result["reproducibility_report"] is None  # gate fired before any run
    )
    return {
        "injection": "C1-broken-capsule",
        "method": "capsule.json replaced with invalid JSON ({not json)",
        "expectation": "P10 FAIL, visible 'capsule invalid' reason, no execution",
        "observed": {
            "p10_status": result["p10_status"],
            "p10_reason": detail.get("reason"),
            "report_written": result["reproducibility_report"] is not None,
        },
        "expected_outcome_observed": expected,
    }


def injection_c2(tmp: Path) -> dict:
    proj = _fresh_copy(tmp, "c2-output-tampering")
    script = proj / "pilot_compute.py"
    src = script.read_text(encoding="utf-8")
    assert NONCE_ANCHOR in src, "pilot_compute.py patch anchor missing"
    patched = src.replace(NONCE_ANCHOR, NONCE_PATCH, 1)
    script.write_text(patched, encoding="utf-8")
    # honest declaration: the capsule records exactly the code that runs
    cap_path = proj / ".paper-factory" / "reproduction" / "capsule.json"
    capsule = json.loads(cap_path.read_text(encoding="utf-8"))
    patched_sha = _sha256_text(patched)
    for ref in capsule["code_refs"]:
        if ref["rel_path"] == "pilot_compute.py":
            ref["sha256"] = patched_sha
    cap_path.write_text(json.dumps(capsule, indent=2) + "\n", encoding="utf-8")

    result = _run_dag(proj, "v13-inj-c2")
    report = result["reproducibility_report"] or {}
    receipts = report.get("receipts", [])
    out_hashes = [
        {o["rel_path"]: o["sha256"] for o in r.get("outputs", [])}
        for r in receipts
    ]
    diverged = len(out_hashes) == 2 and out_hashes[0] != out_hashes[1]
    expected = (
        result["p10_status"] == "FAIL"
        and report.get("classification") == "MISMATCH"
        and diverged
        and len(report.get("differing_outputs", [])) > 0
    )
    return {
        "injection": "C2-output-tampering",
        "method": (
            "pilot_compute.py patched with a uuid nonce per execution "
            "(code hash in the capsule updated to match); run 1 and run 2 "
            "of the same declared capsule therefore diverge"
        ),
        "patched_script_sha256": patched_sha,
        "expectation": "classification MISMATCH, P10 FAIL, differing outputs recorded",
        "observed": {
            "p10_status": result["p10_status"],
            "classification": report.get("classification"),
            "differing_outputs": report.get("differing_outputs"),
            "run_output_hashes": out_hashes,
            "runs_diverged": diverged,
        },
        "expected_outcome_observed": expected,
    }


def injection_c3(tmp: Path) -> dict:
    proj = _fresh_copy(tmp, "c3-backend-unavailable")
    cap_path = proj / ".paper-factory" / "reproduction" / "capsule.json"
    # Negative probe: the venv interpreter (has pydantic + snakemake
    # installed) is invoked through a symlink in a fresh scratch bin dir
    # with PATH emptied. CPython's venv detection follows the symlink for
    # site-packages, but `Path(sys.executable).parent` is the scratch dir —
    # which contains no `snakemake`. Both probe paths (PATH, interpreter
    # bin dir) therefore miss, exactly as the capability probe documents.
    # This is a real negative, not a mock: the probe code is PF production
    # code and the environment genuinely has no reachable binary.
    bin_dir = tmp / "c3-bin"
    bin_dir.mkdir()
    (bin_dir / "python3").symlink_to(Path(sys.executable).resolve())
    probe = (
        "import json, sys\n"
        f"sys.path.insert(0, {str(REPO)!r})\n"
        "from paper_factory.reproduction.capsule import ReproductionCapsule\n"
        "from paper_factory.reproduction.snakemake_backend import (\n"
        "    SnakemakeBackend, SnakemakeUnavailableError, snakemake_binary)\n"
        f"cap = ReproductionCapsule.model_validate_json(open({str(cap_path)!r}).read())\n"
        "result = {'probe_binary': snakemake_binary()}\n"
        "try:\n"
        f"    receipt = SnakemakeBackend().run(cap, {str(proj)!r})\n"
        "    result['outcome'] = 'UNEXPECTED_RUN'\n"
        "    result['status'] = receipt.status\n"
        "except SnakemakeUnavailableError as exc:\n"
        "    result['outcome'] = 'UNAVAILABLE'\n"
        "    result['exception'] = 'SnakemakeUnavailableError'\n"
        "    result['message'] = str(exc)\n"
        "print(json.dumps(result))\n"
    )
    # negative: scratch-interpreter symlink, empty PATH, no snakemake anywhere
    env = dict(os.environ, PATH="")
    neg = subprocess.run([str(bin_dir / "python3"), "-c", probe],
                         capture_output=True, text=True, timeout=300,
                         env=env, cwd=REPO)
    neg_out = json.loads(neg.stdout.strip().splitlines()[-1])
    # positive control: PF venv python, normal PATH → backend is wired correctly
    pos = subprocess.run([sys.executable, "-c", probe], capture_output=True,
                         text=True, timeout=300, cwd=REPO)
    pos_out = json.loads(pos.stdout.strip().splitlines()[-1])

    expected = (
        neg_out["outcome"] == "UNAVAILABLE"
        and neg_out["probe_binary"] is None
        and pos_out.get("status") == "completed"
    )
    # committed reports must not carry absolute home paths
    if isinstance(pos_out.get("probe_binary"), str):
        pos_out["probe_binary"] = pos_out["probe_binary"].replace(
            str(Path.home()), "~")
    return {
        "injection": "C3-backend-unavailable",
        "method": (
            "SnakemakeBackend probed with PATH emptied, via a symlink to the "
            "PF venv interpreter placed in a fresh scratch bin dir that has "
            "no snakemake binary (both probe paths miss)"
        ),
        "negative_interpreter": (
            "venv python3 via fresh scratch-dir symlink, PATH=\"\""
        ),
        "expectation": (
            "SnakemakeUnavailableError (fail-visible, honest UNAVAILABLE — "
            "no fake receipt); positive control via the PF venv must run"
        ),
        "observed": {
            "negative_probe": {k: v for k, v in neg_out.items() if k != "message"},
            "negative_message_sha256": _sha256_text(neg_out.get("message", "")),
            "positive_control": pos_out,
        },
        "expected_outcome_observed": expected,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out-dir", type=Path, default=REPO / "docs" / "reports")
    args = parser.parse_args()

    cap = PILOT / ".paper-factory" / "reproduction" / "capsule.json"
    if not cap.exists():
        raise SystemExit(
            f"Pilot A capsule not found: {cap.relative_to(REPO)} — "
            "build pilots/v1-3-repro-synth/project first (see "
            "docs/reports/V1_3_PILOT_MATRIX.md)")

    results = []
    with tempfile.TemporaryDirectory(prefix="pf-inject-") as tmp_s:
        tmp = Path(tmp_s)
        for fn in (injection_c1, injection_c2, injection_c3):
            print(f"running {fn.__name__} ...")
            results.append(fn(tmp))

    all_expected = all(r["expected_outcome_observed"] for r in results)
    payload = {
        "generated_at": _utc(),
        "pilot": "pilots/v1-3-repro-synth/project",
        "capsule_digest": json.loads(cap.read_text(encoding="utf-8")).get(
            "capsule_digest", "see capsule.json (computed property)"),
        "environment": {
            "python": platform.python_version(),
            "platform": f"{sys.platform}-{platform.machine()}",
        },
        "summary": {
            "injections": len(results),
            "expected_outcome_observed": sum(
                1 for r in results if r["expected_outcome_observed"]),
            "all_expected": all_expected,
        },
        "injections": results,
    }
    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "V1_3_PILOT_INJECTIONS.json"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                         encoding="utf-8")
    print(f"wrote: {json_path.relative_to(REPO)}")
    for r in results:
        flag = "OK  " if r["expected_outcome_observed"] else "FAIL"
        print(f"  [{flag}] {r['injection']}")
    return 0 if all_expected else 1


if __name__ == "__main__":
    raise SystemExit(main())
