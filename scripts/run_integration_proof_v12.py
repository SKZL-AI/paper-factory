"""v1.2 REAL VeriHarness integration proof (Phase 3+4, release evidence gap).

One REAL provider-backed differential run over the productive contract path:
Paper Factory WorkPackage -> run_shadow() -> native PF result + real
VeriHarness/HoH run -> VerificationResult -> DifferentialReceipt.

This is an explicit live/field test, NOT a unit test. It spends LLM quota
(planner + developer + QA dispatches via the installed CLIs) and must never
run inside pytest. Evidence lands in docs/reports/v1_2_integration_proof.json
and feeds docs/reports/V1_2_REAL_VERIHARNESS_INTEGRATION_PROOF.md.
"""
import json
import os
import shutil
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
TARGET = REPO / "pilots" / "integration-proof-v12" / "project"
SPEC = TARGET / ".paper-factory" / "proof-spec.md"
EVIDENCE = REPO / "docs" / "reports" / "v1_2_integration_proof.json"
# VeriHarness source checkout: read-only identity evidence (git rev-parse only).
# Public-repo hygiene: never a hardcoded home path; overridable per machine.
VERIHARNESS_REPO = Path(
    os.environ.get("PF_VERIHARNESS_REPO", "~/veriharness")
).expanduser()

sys.path.insert(0, str(REPO))

from paper_factory.adapters.veriharness.adapter import VeriharnessAdapter
from paper_factory.core.results import Verdict
from paper_factory.core.util import sha256_file, utcnow
from paper_factory.state.store import Workspace
from paper_factory.verification.contract import (
    ArtifactRef,
    BackendIdentity,
    VerificationResult,
    WorkPackage,
    artifact_binding,
)
from paper_factory.verification.shadow import run_shadow


def utcnow_dt() -> datetime:
    return datetime.now(UTC)


_HOME = str(Path.home())


def _scrub(obj: Any) -> Any:
    """Committed evidence must not carry absolute home paths (public repo):
    shorten the home prefix to '~', recursively. Mirrors pilot_differential."""
    if isinstance(obj, str):
        return obj.replace(_HOME, "~") if _HOME not in ("", "/") else obj
    if isinstance(obj, dict):
        return {k: _scrub(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_scrub(v) for v in obj]
    return obj


def native_fn(package: WorkPackage) -> VerificationResult:
    """PF-native side: deterministic reproduction of the acceptance checks.

    Verdict PASS means: the native checks (K1 analyze reproduces, K2 result
    artifact exists) hold in the real workspace. This mirrors what the P05
    base handler establishes natively. The binding uses the same
    artifact_binding() rule over the package artifacts (by construction,
    documented in shadow.compare's MATCH rationale).
    """
    import subprocess

    started = utcnow_dt()
    analyze = TARGET / "code" / "analyze.py"
    summary = TARGET / "results" / "summary.json"
    checks: dict[str, bool] = {}
    proc = subprocess.run(
        [sys.executable, str(analyze)], cwd=TARGET, capture_output=True, timeout=120, check=False
    )
    checks["K1_analyze_exits_0"] = proc.returncode == 0
    checks["K2_summary_exists"] = summary.is_file() and summary.stat().st_size > 0
    verdict = Verdict.PASS if all(checks.values()) else Verdict.FAIL
    return VerificationResult(
        package_id=package.package_id,
        backend=BackendIdentity(
            kind="pf_native",
            name="pf_native:integration-proof",
            version="1.2.0.dev0",
            detail={"checks": checks},
        ),
        verdict=verdict,
        artifact_sha256=artifact_binding(package.artifacts),
        started_at=started,
        finished_at=utcnow_dt(),
    )


class _RolePresetBackend:
    """VerificationBackend-compatible wrapper pinning HoH roles for this proof.

    The live field test (runs PF-73ed7828 / PF-581db7b3 / PF-7aeb552c) showed
    the developer role stalling in the herdr pane across CLI versions (kimi
    welcome screen, codex empty pane — herdr's 5 s state-change window ->
    agent_prompt_stalled). The default invocation therefore keeps
    use_herdr=False (subprocess dispatch) and planner/developer/qa all on
    codex (the claude planner violated the DevelopmentPlan contract in
    attempt 4 — `description` instead of `command`).

    WP12 (v1.3 pilot matrix): the runtime flags `--herdr` / `--roles`
    allow the one-shot field retry on the herdr path with claude roles
    (claude historically worked via herdr). Trade-offs when running on the
    subprocess path: no A01/A02/A12 pane evidence, developer == qa harness
    (no independence claim).
    """

    def __init__(self, adapter: VeriharnessAdapter, **roles: object) -> None:
        self._adapter = adapter
        self._roles = roles

    def identity(self):
        return self._adapter.identity()

    def capabilities(self):
        return self._adapter.capabilities()

    def verify(self, package: WorkPackage) -> VerificationResult:
        return self._adapter.verify(package, **self._roles)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--herdr", action="store_true",
                        help="WP12 field retry: dispatch through herdr panes "
                             "instead of the subprocess fallback")
    parser.add_argument("--roles", default="codex",
                        choices=["codex", "claude"],
                        help="CLI for planner/developer/qa (default codex; "
                             "claude spends claude quota)")
    parser.add_argument("--evidence", type=Path, default=EVIDENCE,
                        help="evidence JSON path (WP12 herdr attempts must "
                             "use their own dated file — never overwrite "
                             "the v1.2 proof evidence)")
    args = parser.parse_args()
    use_herdr = args.herdr
    role = args.roles
    evidence_path = args.evidence

    started_wall = utcnow()
    evidence: dict = {
        "proof": "v1.2 REAL VeriHarness integration proof",
        "started_at": started_wall,
        "pf_head": None,
        "veriharness": {},
        "work_package": {},
        "native": {},
        "veriharness_result": {},
        "differential": {},
        "runtime": {},
        "cleanup": {},
        "note": "",
    }

    import subprocess

    evidence["pf_head"] = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=REPO, capture_output=True, text=True, check=False
    ).stdout.strip()
    vh_head = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=VERIHARNESS_REPO,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    evidence["veriharness"] = {"package": "hoh", "version": "0.1.0", "commit": vh_head}

    if TARGET.exists():
        archive = REPO / ".archiv" / f"integration-proof-v12.v1.{utcnow().replace(':', '')}"
        archive.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(TARGET), str(archive))
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(REPO / "fixtures" / "synthetic_project", TARGET)
    (TARGET / ".paper-factory").mkdir(exist_ok=True)

    ws = Workspace(TARGET)
    adapter = VeriharnessAdapter(ws)
    diag = adapter.doctor()
    evidence["doctor"] = diag
    if not (diag["present"] and diag["herdr"]):
        evidence["note"] = "DEGRADED_RUNTIME: hoh or herdr unavailable — no live proof possible"
        evidence_path.write_text(
        json.dumps(_scrub(evidence), indent=2, default=str), encoding="utf-8"
    )
        return 2

    SPEC.write_text(
        "# PF-v1.2 integration proof: result integrity of the synthetic filter benchmark\n\n"
        "Work package: add a `VERIFICATION.md` to this repository that documents\n"
        "exactly how the experiment results are reproduced (commands, expected\n"
        "artifacts). Keep it factual and short. Do NOT modify code/ or results/.\n\n"
        "## Acceptance criteria\n"
        "- K1: `python3 code/analyze.py` exits 0 (analysis reproduces)\n"
        "- K2: `test -s results/summary.json` (result artifact exists)\n"
        "- K3: `test -s VERIFICATION.md` (documentation written)\n"
        "- K4: `grep -q analyze VERIFICATION.md` (docs name the analysis)\n\n"
        "## Planner contract hint (DevelopmentPlan JSON)\n"
        "Every acceptance check MUST use the exact field names of the HoH\n"
        "contract: `check_id`, `command` (shell command string), `expect_exit`\n"
        "(integer, 0 for success). Example element:\n"
        '{"check_id": "K1", "command": "python3 code/analyze.py", "expect_exit": 0}\n'
        "Do not use `description`-only checks.\n",
        encoding="utf-8",
    )

    artifacts = [
        ArtifactRef(
            rel_path="code/analyze.py",
            sha256=sha256_file(TARGET / "code" / "analyze.py"),
            kind="source",
        ),
        ArtifactRef(
            rel_path="results/summary.json",
            sha256=sha256_file(TARGET / "results" / "summary.json"),
            kind="result",
        ),
    ]
    package = WorkPackage(
        package_id="v12-integration-proof-P05",
        node_id="P05",
        spec_markdown=SPEC.read_text(encoding="utf-8"),
        artifacts=artifacts,
        acceptance_criteria=["K1", "K2", "K3", "K4"],
        provenance={"proof": "v1.2 integration proof", "fixture": "synthetic_project"},
    )
    evidence["work_package"] = {
        "package_id": package.package_id,
        "artifacts": [a.model_dump() for a in artifacts],
        "binding": artifact_binding(artifacts),
    }

    try:
        backend = _RolePresetBackend(
            adapter, planner=role, developer=role, qa=role, use_herdr=use_herdr
        )
        native, receipt = run_shadow(native_fn, backend, package)
        evidence["native"] = {
            "verdict": native.verdict.value,
            "artifact_sha256": native.artifact_sha256,
            "checks": native.backend.detail.get("checks"),
        }
        evidence["veriharness_result"] = {
            "verdict": receipt.shadow_verdict.value if receipt.shadow_verdict else None,
            "artifact_sha256": receipt.shadow_artifact_sha256,
            "backend": receipt.shadow_backend.model_dump() if receipt.shadow_backend else None,
            "provider_status": receipt.provider_status,
        }
        evidence["differential"] = json.loads(receipt.model_dump_json())
        evidence["hoh_run_id"] = (
            receipt.shadow_backend.detail.get("run_id") if receipt.shadow_backend else None
        )
    except Exception:  # noqa: BLE001 — live proof must record any failure as evidence
        evidence["note"] = traceback.format_exc()[-2000:]

    # P-4: receipt SHAs into the evidence — the copied HoH receipts are
    # registered with their content hashes, so "SHA-registriert" is literal.
    if evidence.get("hoh_run_id"):
        receipt_dir = ws.receipts_dir / "hoh" / evidence["hoh_run_id"]
        if receipt_dir.is_dir():
            evidence["receipts"] = [
                {"file": f.name, "sha256": sha256_file(f)}
                for f in sorted(receipt_dir.glob("*.json"))
            ]

    evidence["finished_at"] = utcnow()
    evidence["runtime"]["wall_clock"] = f"{started_wall} -> {evidence['finished_at']}"
    evidence["runtime"]["network"] = "LLM CLI dispatches only (claude/codex subscriptions)"
    evidence["runtime"]["llm_usage"] = (
        f"planner={role}, developer={role}, qa={role}, iterations=1, "
        + ("herdr pane dispatch (WP12 field retry)"
           if use_herdr else
           "--no-herdr (subprocess dispatch; herdr pane stalls with new CLI "
           "TUIs — evidence trade-off documented: no A01/A02/A12 pane evidence)")
    )
    evidence["runtime"]["cost"] = "subscription quota, not measurable per-run"

    # foreign-resource safety: no herdr tabs outside the proof run may be touched
    tabs = subprocess.run(
        ["herdr", "tab", "list"], capture_output=True, text=True, timeout=30, check=False
    ).stdout
    evidence["cleanup"]["herdr_tabs_after"] = [
        line.strip() for line in tabs.splitlines() if "PF-" in line
    ]

    evidence_path.write_text(
        json.dumps(_scrub(evidence), indent=2, default=str), encoding="utf-8"
    )
    print(json.dumps({
        "native": evidence["native"].get("verdict"),
        "veriharness": evidence["veriharness_result"].get("verdict"),
        "differential": evidence["differential"].get("outcome"),
        "run_id": evidence.get("hoh_run_id"),
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
