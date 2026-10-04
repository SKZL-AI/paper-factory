"""Pilot differential: compare PF-native node verdicts with stored HoH/VeriHarness
receipts for existing local pilot workspaces — offline, read-only, no new papers.

WP7 / plan §3 Phase 12 + §5 Abweichung 2: NO live HoH replays (quota discipline),
no network, no LLM calls. The differential is computed purely from what the pilot
workspace already persisted:

- ``runs.sqlite`` (opened ``mode=ro``): ``nodes`` (native verdict = status),
  ``receipts`` (kind='hoh' / kind='shadow' rows), node ``detail`` JSON
  (``hoh_verdict`` / ``hoh_run_id`` / ``hoh_blocked_kind`` when a live HoH run
  was recorded at the time).
- ``receipts/hoh/`` / ``receipts/shadow/`` on disk.

Where no HoH evidence is stored (the case for all current pilots), the VH side is
honestly reported as UNAVAILABLE → DifferentialOutcome.PROVIDER_UNAVAILABLE.
Verdicts are compared with ``paper_factory.verification.shadow.compare``; native
and shadow ``VerificationResult`` objects are constructed from the stored data
(backend ``pf_native`` vs ``veriharness``). Cost is never measurable offline and
is reported as such.

Usage:
    python -m scripts.pilot_differential --pilots-dir pilots \
        --pilots pilot-03-massinv-paper1 real-pilot-01-rerun --out-dir docs/reports
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from paper_factory.core.results import Verdict
from paper_factory.verification.contract import BackendIdentity, VerificationResult
from paper_factory.verification.shadow import DifferentialOutcome, compare

WORKSPACE_DIRNAME = ".paper-factory"
COST_NOTE = (
    "not measurable offline — no live HoH replay was run (quota discipline); "
    "live cost evidence remains reserved for scripts/run_live_hoh.py"
)
LIMITATION_NOTE = (
    "Differential computed from stored pilot state only (runs.sqlite + receipt "
    "tree), read-only. No live HoH replay was executed (plan §5 Abweichung 2, "
    "quota discipline); the VH side is therefore UNAVAILABLE/PROVIDER_UNAVAILABLE "
    "wherever no HoH receipt was persisted historically. Semantic equivalence is "
    "N/A in that case — it is a documented gap, not a PASS."
)
HISTORICAL_RESOLUTION = (
    "documented, not resolved post-hoc — historical stored data, no re-run"
)


def _scrub_home(text: str) -> str:
    """Committed reports must not carry absolute home paths: shorten the
    home prefix to '~' (still unambiguous for a human reader)."""
    home = str(Path.home())
    return text.replace(home, "~") if home not in ("", "/") else text


def _display_path(p: Path) -> str:
    """Repo-relative when inside the repo, home-scrubbed otherwise — never an
    absolute /home/... path in a committed report."""
    try:
        return str(p.resolve().relative_to(REPO))
    except ValueError:
        return _scrub_home(str(p))


# --------------------------------------------------------------------------- #
# Extraction (read-only)
# --------------------------------------------------------------------------- #


def open_readonly(db_path: Path) -> sqlite3.Connection:
    """Open the pilot DB strictly read-only (URI mode=ro)."""
    uri = f"file:{db_path.resolve()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def find_workspace(pilot_dir: Path) -> Path | None:
    """Locate the .paper-factory workspace below a pilot dir (direct or via project/)."""
    for cand in (pilot_dir / WORKSPACE_DIRNAME, pilot_dir / "project" / WORKSPACE_DIRNAME):
        if (cand / "runs.sqlite").exists():
            return cand
    return None


def _parse_detail(raw: str | None) -> tuple[dict[str, Any] | None, str | None]:
    """Parse the node detail JSON. Corrupt JSON -> (None, warning)."""
    if raw is None:
        return None, None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None, f"corrupt detail JSON skipped: {raw[:80]!r}"
    if not isinstance(parsed, dict):
        return None, f"non-object detail skipped: {raw[:80]!r}"
    return parsed, None


@dataclass
class PilotState:
    pilot: str
    workspace: Path
    runs: list[dict[str, Any]]
    nodes: dict[str, list[dict[str, Any]]]  # run_id -> node rows (detail parsed)
    receipts: dict[str, list[dict[str, Any]]]  # run_id -> receipt rows
    warnings: list[str] = field(default_factory=list)


def extract_pilot(pilot_dir: Path, pilot_name: str | None = None) -> PilotState:
    """Read a pilot workspace fully read-only. Never writes to the DB."""
    name = pilot_name or pilot_dir.resolve().name
    ws = find_workspace(pilot_dir)
    if ws is None:
        raise FileNotFoundError(f"no {WORKSPACE_DIRNAME}/runs.sqlite under {pilot_dir}")
    state = PilotState(pilot=name, workspace=ws, runs=[], nodes={}, receipts={})
    with open_readonly(ws / "runs.sqlite") as conn:
        state.runs = [dict(r) for r in conn.execute(
            "SELECT run_id, created_at, status FROM runs ORDER BY created_at"
        )]
        for row in conn.execute(
            "SELECT run_id, node_id, status, started_at, finished_at, detail FROM nodes"
        ):
            detail, warn = _parse_detail(row["detail"])
            if warn:
                state.warnings.append(f"{row['run_id']}/{row['node_id']}: {warn}")
            state.nodes.setdefault(row["run_id"], []).append(
                {
                    "run_id": row["run_id"],
                    "node_id": row["node_id"],
                    "status": row["status"],
                    "started_at": row["started_at"],
                    "finished_at": row["finished_at"],
                    "detail": detail,
                }
            )
        for row in conn.execute(
            "SELECT receipt_id, run_id, node_id, kind, path, sha256, created_at FROM receipts"
        ):
            state.receipts.setdefault(row["run_id"], []).append(dict(row))
    return state


# --------------------------------------------------------------------------- #
# Differential
# --------------------------------------------------------------------------- #


def _pf_version() -> str:
    try:
        from importlib.metadata import version

        return version("paper-factory")
    except Exception:  # noqa: BLE001 — version is nice-to-have, never blocking
        return "unknown"


def _to_verdict(status: str) -> Verdict | None:
    try:
        return Verdict(status)
    except ValueError:
        return None


def _native_result(node: dict[str, Any], package_id: str) -> VerificationResult:
    verdict = _to_verdict(node["status"]) or Verdict.UNAVAILABLE
    started = _parse_ts(node["started_at"]) or datetime.now(UTC)
    finished = _parse_ts(node["finished_at"]) or started
    return VerificationResult(
        package_id=package_id,
        backend=BackendIdentity(
            kind="pf_native", name=f"pf_native:{node['node_id']}", version=_pf_version()
        ),
        verdict=verdict,
        artifact_sha256=None,  # pilots persist no per-node artifact binding — honest None
        started_at=started,
        finished_at=finished,
    )


def _hoh_result(
    node: dict[str, Any], package_id: str, hoh_receipts: list[dict[str, Any]]
) -> VerificationResult:
    """Reconstruct the stored HoH side, or an honest UNAVAILABLE result."""
    detail = node.get("detail") or {}
    now = datetime.now(UTC)
    base = {
        "package_id": package_id,
        "backend": BackendIdentity(kind="veriharness", name="hoh", version="stored-receipt"),
    }
    if "hoh_verdict" in detail:
        verdict = _to_verdict(str(detail["hoh_verdict"])) or Verdict.UNAVAILABLE
        return VerificationResult(
            verdict=verdict,
            started_at=now,
            finished_at=now,
            raw_receipt_refs=[r["receipt_id"] for r in hoh_receipts],
            **base,
        )
    reason = detail.get("hoh_reason") or (
        "no HoH receipt stored for this node in the pilot workspace; "
        "live replay out of scope (quota discipline, plan §5 Abweichung 2)"
    )
    return VerificationResult(
        verdict=Verdict.UNAVAILABLE,
        started_at=now,
        finished_at=now,
        failure_reason=reason,
        raw_receipt_refs=[r["receipt_id"] for r in hoh_receipts],
        **base,
    )


def _parse_ts(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _duration_s(node: dict[str, Any]) -> float | None:
    start, end = _parse_ts(node["started_at"]), _parse_ts(node["finished_at"])
    if start and end:
        return round((end - start).total_seconds(), 3)
    return None


def differential_for_node(
    pilot: str,
    run_id: str,
    node: dict[str, Any],
    run_receipts: list[dict[str, Any]],
) -> dict[str, Any]:
    """One node's differential row: native vs stored-VH, via shadow.compare."""
    node_id = node["node_id"]
    package_id = f"pilot-diff-{pilot}-{run_id}-{node_id}"
    hoh_receipts = [r for r in run_receipts if r.get("node_id") == node_id and r["kind"] == "hoh"]
    shadow_receipts = [
        r for r in run_receipts if r.get("node_id") == node_id and r["kind"] == "shadow"
    ]

    native = _native_result(node, package_id)
    hoh = _hoh_result(node, package_id, hoh_receipts)
    receipt = compare(native, hoh, node_id=node_id)

    hoh_detail = (node.get("detail") or {})
    outcome = receipt.outcome
    if outcome is DifferentialOutcome.SEMANTIC_MATCH:
        # honest label: verdicts agree but the agreement is NOT artifact-provable
        equivalence = "yes (unbound)"
    elif outcome is DifferentialOutcome.MATCH:
        equivalence = "yes"
    elif outcome is DifferentialOutcome.MISMATCH:
        equivalence = "no"
    else:
        equivalence = "N/A"

    mismatches = []
    if outcome is DifferentialOutcome.MISMATCH:
        mismatches.append(
            f"native {native.verdict.value} vs VH {hoh.verdict.value}"
            + (f" (hoh_run_id={hoh_detail['hoh_run_id']})" if hoh_detail.get("hoh_run_id") else "")
        )
    if outcome is DifferentialOutcome.INCOMPARABLE:
        mismatches.append("conflicting artifact bindings; verdict equality not provable")

    return {
        "pilot": pilot,
        "run_id": run_id,
        "node_id": node_id,
        "native_verdict": native.verdict.value,
        "vh_verdict": None if outcome is DifferentialOutcome.PROVIDER_UNAVAILABLE else hoh.verdict.value,
        "vh_backend": "veriharness" if hoh.verdict is not Verdict.UNAVAILABLE else "veriharness (offline reconstruction)",
        "artifact_identity": {
            "native_artifact_sha256": receipt.native_artifact_sha256,
            "vh_artifact_sha256": receipt.shadow_artifact_sha256,
            "hoh_receipts": len(hoh_receipts),
            "shadow_receipts": len(shadow_receipts),
        },
        "semantic_equivalence": equivalence,
        "outcome": outcome.value,
        "mismatches": mismatches,
        "resolution": HISTORICAL_RESOLUTION if mismatches else None,
        "degraded": native.verdict is Verdict.DEGRADED,
        "timing": {
            "started_at": node["started_at"],
            "finished_at": node["finished_at"],
            "duration_s": _duration_s(node),
        },
        "cost": COST_NOTE,
        "rationale": receipt.rationale,
        "detail_excerpt": _scrub_home(_detail_excerpt(node.get("detail"))),
    }


def _detail_excerpt(detail: dict[str, Any] | None, limit: int = 160) -> str:
    if not detail:
        return ""
    text = json.dumps(detail, ensure_ascii=False, sort_keys=True)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def run_differential(state: PilotState, run_id: str | None = None) -> dict[str, Any]:
    """Differential for one pilot. Uses the latest run unless run_id is given."""
    if not state.runs:
        return {
            "pilot": state.pilot,
            "workspace": _display_path(state.workspace),
            "run_id": None,
            "rows": [],
            "warnings": state.warnings + ["no runs recorded in runs.sqlite"],
            "limitations": LIMITATION_NOTE,
        }
    chosen = run_id or state.runs[-1]["run_id"]
    if chosen not in {r["run_id"] for r in state.runs}:
        raise KeyError(f"run {chosen} not in pilot {state.pilot}")
    run_receipts = state.receipts.get(chosen, [])
    nodes = sorted(state.nodes.get(chosen, []), key=lambda n: n["node_id"])
    rows = [differential_for_node(state.pilot, chosen, n, run_receipts) for n in nodes]
    return {
        "pilot": state.pilot,
        "workspace": _display_path(state.workspace),
        "run_id": chosen,
        "run_count": len(state.runs),
        "run_created_at": next((r["created_at"] for r in state.runs if r["run_id"] == chosen), None),
        "rows": rows,
        "warnings": state.warnings,
        "limitations": LIMITATION_NOTE,
    }


# --------------------------------------------------------------------------- #
# Reports
# --------------------------------------------------------------------------- #


def _status_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["native_verdict"]] = counts.get(r["native_verdict"], 0) + 1
    return counts


def render_markdown(result: dict[str, Any]) -> str:
    rows = result["rows"]
    lines = [
        f"# Pilot Differential — {result['pilot']} (v1.2 WP7, Phase 12)",
        "",
        f"- Workspace: `{result['workspace']}` (read-only, sqlite mode=ro)",
        (
            f"- Run: `{result.get('run_id')}` of {result.get('run_count', 1)} recorded run(s), "
            f"created {result.get('run_created_at')}"
        ),
        f"- Generated: {datetime.now(UTC).isoformat()}",
        "",
        "## Method & Limitation",
        "",
        LIMITATION_NOTE,
        "",
        "Cost: " + COST_NOTE + ".",
        "",
        "## Node Differential",
        "",
        "| Node | Native verdict | VH verdict | Semantic equivalence | Outcome | Mismatches | Timing (s) |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        timing = r["timing"]["duration_s"]
        timing_s = f"{timing}" if timing is not None else "n/a"
        mismatches = "; ".join(r["mismatches"]) or "—"
        lines.append(
            f"| {r['node_id']} | {r['native_verdict']} | {r['vh_verdict'] or 'UNAVAILABLE (no stored receipt)'} "
            f"| {r['semantic_equivalence']} | {r['outcome']} | {mismatches} | {timing_s} |"
        )
    lines += ["", "## Verdict Distribution (native)", ""]
    for verdict, count in sorted(_status_counts(rows).items()):
        lines.append(f"- {verdict}: {count}")
    degraded = [r["node_id"] for r in rows if r["degraded"]]
    lines += ["", "## Degraded States (native DEGRADED)", ""]
    lines.append(", ".join(degraded) if degraded else "none")
    mismatch_rows = [r for r in rows if r["mismatches"]]
    lines += ["", "## Mismatches", ""]
    if mismatch_rows:
        for r in mismatch_rows:
            lines.append(f"- {r['node_id']}: {'; '.join(r['mismatches'])} — {r['resolution']}")
    else:
        lines.append(
            "none — with the honest caveat that the VH side is UNAVAILABLE for every "
            "node without a stored HoH receipt (see Limitation), so no native↔VH "
            "mismatch can exist in this dataset by construction."
        )
    if result["warnings"]:
        lines += ["", "## Warnings", ""] + [f"- {w}" for w in result["warnings"]]
    lines += [
        "",
        "## Notes",
        "",
        "- Resolution policy for historical data: documented, never resolved post-hoc.",
        (
            "- Live HoH replay (with real cost/timing evidence) is reserved for the explicit "
            "live path `scripts/run_live_hoh.py` and is not part of this acceptance gate."
        ),
        "",
    ]
    return "\n".join(lines)


def render_summary(results: list[dict[str, Any]]) -> str:
    lines = [
        "# Pilot Differential — Summary (v1.2 WP7, Phase 12)",
        "",
        f"Generated: {datetime.now(UTC).isoformat()}",
        "",
        (
            "Offline differential over stored pilot state only — no live HoH replays, no "
            "network, no LLM calls (plan §5 Abweichung 2, quota discipline). "
            "Per-pilot details: `V1_2_PILOT_DIFFERENTIAL_<pilot>.md`."
        ),
        "",
        "| Pilot | Run | Nodes | Native PASS | Native DEGRADED | Native FAIL/other | Stored HoH receipts | Shadow receipts | Mismatches | Outcome distribution |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for res in results:
        rows = res["rows"]
        counts = _status_counts(rows)
        hoh_n = sum(r["artifact_identity"]["hoh_receipts"] for r in rows)
        shadow_n = sum(r["artifact_identity"]["shadow_receipts"] for r in rows)
        mism = sum(1 for r in rows if r["mismatches"])
        out_counts: dict[str, int] = {}
        for r in rows:
            out_counts[r["outcome"]] = out_counts.get(r["outcome"], 0) + 1
        other = len(rows) - counts.get("PASS", 0) - counts.get("DEGRADED", 0) - counts.get("FAIL", 0)
        dist = ", ".join(f"{k}:{v}" for k, v in sorted(out_counts.items())) or "—"
        lines.append(
            f"| {res['pilot']} | {res.get('run_id')} | {len(rows)} | {counts.get('PASS', 0)} "
            f"| {counts.get('DEGRADED', 0)} | {counts.get('FAIL', 0) + other} | {hoh_n} | {shadow_n} "
            f"| {mism} | {dist} |"
        )
    lines += [
        "",
        "## Headline Limitation",
        "",
        LIMITATION_NOTE,
        "",
        (
            "Cost was not measurable for any pilot (offline reconstruction from stored "
            "state; live cost evidence requires the explicit live path "
            "`scripts/run_live_hoh.py`)."
        ),
        "",
        "## Reading Guide",
        "",
        (
            "- `PROVIDER_UNAVAILABLE` rows mean: the pilot ran without persisting any HoH "
            "result for that node, and this WP deliberately did not re-run HoH. It is a "
            "documented gap (Phase-12 acceptance under §5 Abweichung 2), not a PASS."
        ),
        (
            "- `MATCH`/`SEMANTIC_MATCH`/`MISMATCH`/`INCOMPARABLE` rows would appear for "
            "nodes with stored `hoh_verdict` receipts and are produced by "
            "`verification.shadow.compare`."
        ),
        "",
    ]
    return "\n".join(lines)


def write_reports(
    results: list[dict[str, Any]], out_dir: Path, write_files: bool = True
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for res in results:
        md = render_markdown(res)
        md_path = out_dir / f"V1_2_PILOT_DIFFERENTIAL_{res['pilot']}.md"
        json_path = out_dir / f"V1_2_PILOT_DIFFERENTIAL_{res['pilot']}.json"
        if write_files:
            md_path.write_text(md, encoding="utf-8")
            json_path.write_text(
                json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        written += [md_path, json_path]
    summary_path = out_dir / "V1_2_PILOT_DIFFERENTIAL_SUMMARY.md"
    if write_files:
        summary_path.write_text(render_summary(results), encoding="utf-8")
    written.append(summary_path)
    return written


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--pilots-dir",
        type=Path,
        default=REPO / "pilots",
        help="directory containing pilot workspaces (default: <repo>/pilots)",
    )
    parser.add_argument(
        "--pilots",
        nargs="+",
        required=True,
        help="pilot directory names under --pilots-dir (or absolute paths)",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=REPO / "docs" / "reports",
        help="report output directory (default: <repo>/docs/reports)",
    )
    args = parser.parse_args(argv)

    results = []
    for name in args.pilots:
        pilot_dir = Path(name)
        if not pilot_dir.is_absolute():
            pilot_dir = args.pilots_dir / name
        state = extract_pilot(pilot_dir)
        result = run_differential(state)
        results.append(result)
        rows = result["rows"]
        mism = sum(1 for r in rows if r["mismatches"])
        print(
            f"[{state.pilot}] run={result.get('run_id')} nodes={len(rows)} "
            f"mismatches={mism} warnings={len(result['warnings'])}"
        )

    written = write_reports(results, args.out_dir)
    print("wrote:")
    for p in written:
        print(f"  {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
