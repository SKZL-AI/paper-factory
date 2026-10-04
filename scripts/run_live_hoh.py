"""One live VeriHarness/HoH run for the P05 verification node against a fresh
copy of the synthetic fixture. Writes paper_factory/state/e2e_hoh_evidence.json.
Quota-spending: planner + developer + QA dispatches via the installed CLIs.
"""
import json
import shutil
import sys
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TARGET = Path("/tmp/pf-hoh-live")
SPEC = REPO / "paper_factory/state/hoh_live_spec.md"

sys.path.insert(0, str(REPO))

from paper_factory.adapters.veriharness.adapter import VeriharnessAdapter  # noqa: E402
from paper_factory.core.util import utcnow  # noqa: E402
from paper_factory.state.store import Workspace  # noqa: E402


def main() -> int:
    if TARGET.exists():
        shutil.move(str(TARGET), str(REPO / ".archiv" / f"pf-hoh-live.v1.{utcnow().replace(':', '')}"))
    shutil.copytree(REPO / "fixtures" / "synthetic_project", TARGET)
    ws = Workspace(TARGET)
    adapter = VeriharnessAdapter(ws)
    diag = adapter.doctor()
    evidence = {"started_at": utcnow(), "doctor": diag, "run_id": None,
                "verdict": "NOT_RUN", "receipts": [], "note": ""}
    if not (diag["present"] and diag["herdr"]):
        evidence["note"] = "DEGRADED_RUNTIME: hoh or herdr unavailable"
        (REPO / "paper_factory/state/e2e_hoh_evidence.json").write_text(json.dumps(evidence, indent=2))
        return 2

    SPEC.write_text(
        "# PF-P05: Result integrity of the synthetic filter benchmark\n\n"
        "Work package: add a `VERIFICATION.md` to this repository that documents\n"
        "exactly how the experiment results are reproduced (commands, expected\n"
        "artifacts). Keep it factual and short.\n\n"
        "## Acceptance criteria\n"
        "- K1: `python3 code/analyze.py` exits 0 (analysis reproduces)\n"
        "- K2: `test -s results/summary.json` (result artifact exists)\n"
        "- K3: `test -s VERIFICATION.md` (documentation written)\n"
        "- K4: `grep -q analyze VERIFICATION.md` (docs name the analysis)\n",
        encoding="utf-8")

    try:
        result = adapter.verify_work_package("P05", SPEC, planner="claude",
                                             developer="kimi", qa="codex", iterations=1)
        evidence.update({
            "run_id": result.run_id,
            "verdict": result.verdict.value,
            "accepted": result.accepted,
            "blocked_kind": result.blocked_kind,
            "stage": result.stage,
            "receipts": result.receipts,
            "detail": {k: v for k, v in result.detail.items() if k != "run_summary"},
            "finished_at": utcnow(),
        })
    except Exception:
        evidence["note"] = traceback.format_exc()[-2000:]
        evidence["finished_at"] = utcnow()
    (REPO / "paper_factory/state/e2e_hoh_evidence.json").write_text(
        json.dumps(evidence, indent=2, default=str))
    print(json.dumps({k: evidence[k] for k in ("run_id", "verdict", "accepted", "blocked_kind")},
                     indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
