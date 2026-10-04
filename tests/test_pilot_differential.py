"""Pilot differential tests (plan §3 Phase 12) — all offline.

The synthetic mini-SQLite in tmp_path uses the exact schema from
``state/store.py``. Real pilot DBs are never touched; the read-only test only
asserts that a write against a mode=ro connection fails.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import pilot_differential as pd

from paper_factory.state.store import SCHEMA
from paper_factory.verification.shadow import DifferentialOutcome


@pytest.fixture
def pilot_ws(tmp_path: Path) -> Path:
    """Synthetic pilot workspace with the production schema."""
    ws = tmp_path / "proj" / ".paper-factory"
    ws.mkdir(parents=True)
    conn = sqlite3.connect(ws / "runs.sqlite")
    conn.executescript(SCHEMA)
    conn.execute(
        "INSERT INTO runs(run_id, created_at, target_root, status) VALUES (?,?,?,?)",
        ("run-1", "2026-10-01T10:00:00Z", str(tmp_path), "OPEN"),
    )
    conn.execute(
        "INSERT INTO runs(run_id, created_at, target_root, status) VALUES (?,?,?,?)",
        ("run-2", "2026-10-02T10:00:00Z", str(tmp_path), "OPEN"),
    )
    nodes = [
        ("run-2", "P04", "PASS", "2026-10-02T10:00:10Z", "2026-10-02T10:00:12Z",
         json.dumps({"evidence_count": 3})),
        ("run-2", "P05", "DEGRADED", "2026-10-02T10:01:00Z", "2026-10-02T10:01:05Z",
         json.dumps({"findings": 1, "hoh_verdict": "FAIL", "hoh_run_id": "PF-abc12345-P05",
                     "hoh_blocked_kind": None})),
        ("run-2", "P10", "DEGRADED", None, None,
         json.dumps({"reason": "no reproduction commands discovered"})),
        ("run-2", "P32", "FAIL", "2026-10-02T10:02:00Z", "2026-10-02T10:02:01Z", None),
    ]
    conn.executemany(
        "INSERT INTO nodes(run_id, node_id, status, started_at, finished_at, detail, attempts)"
        " VALUES (?,?,?,?,?,?,1)",
        nodes,
    )
    conn.execute(
        "INSERT INTO receipts(receipt_id, run_id, node_id, kind, path, sha256, created_at)"
        " VALUES (?,?,?,?,?,?,?)",
        ("rcpt-1", "run-2", "P05", "hoh", "receipts/hoh/PF-abc12345-P05/x.json", "a" * 64,
         "2026-10-02T10:01:06Z"),
    )
    conn.commit()
    conn.close()
    return tmp_path / "proj"


def test_extract_pilot_reads_nodes_and_receipts(pilot_ws: Path):
    state = pd.extract_pilot(pilot_ws, "synthetic")
    assert state.pilot == "synthetic"
    assert [r["run_id"] for r in state.runs] == ["run-1", "run-2"]
    run2 = {n["node_id"]: n for n in state.nodes["run-2"]}
    assert run2["P04"]["status"] == "PASS"
    assert run2["P04"]["detail"]["evidence_count"] == 3
    assert run2["P32"]["detail"] is None  # NULL detail is fine
    assert state.receipts["run-2"][0]["kind"] == "hoh"


def test_run_differential_uses_latest_run_and_maps_verdicts(pilot_ws: Path):
    state = pd.extract_pilot(pilot_ws, "synthetic")
    result = pd.run_differential(state)
    assert result["run_id"] == "run-2"  # latest of the two recorded runs
    rows = {r["node_id"]: r for r in result["rows"]}
    assert rows["P04"]["native_verdict"] == "PASS"
    assert rows["P05"]["native_verdict"] == "DEGRADED"
    # stored hoh_verdict FAIL vs native DEGRADED -> real MISMATCH via shadow.compare
    assert rows["P05"]["vh_verdict"] == "FAIL"
    assert rows["P05"]["outcome"] == DifferentialOutcome.MISMATCH.value
    assert rows["P05"]["semantic_equivalence"] == "no"
    assert rows["P05"]["mismatches"], "mismatch must be named, not silently dropped"
    assert rows["P05"]["resolution"] == pd.HISTORICAL_RESOLUTION
    assert rows["P05"]["artifact_identity"]["hoh_receipts"] == 1
    assert "hoh_run_id=PF-abc12345-P05" in rows["P05"]["mismatches"][0]


def test_missing_hoh_receipt_yields_provider_unavailable(pilot_ws: Path):
    state = pd.extract_pilot(pilot_ws, "synthetic")
    result = pd.run_differential(state)
    rows = {r["node_id"]: r for r in result["rows"]}
    for node_id in ("P04", "P10", "P32"):
        assert rows[node_id]["outcome"] == DifferentialOutcome.PROVIDER_UNAVAILABLE.value
        assert rows[node_id]["vh_verdict"] is None
        assert rows[node_id]["semantic_equivalence"] == "N/A"
        assert rows[node_id]["mismatches"] == []
    # cost honesty: never a fabricated number
    assert "not measurable" in rows["P04"]["cost"]


def test_corrupt_detail_json_is_skipped_with_warning(pilot_ws: Path):
    conn = sqlite3.connect(pilot_ws / ".paper-factory" / "runs.sqlite")
    conn.execute(
        "UPDATE nodes SET detail=? WHERE run_id='run-2' AND node_id='P32'", ("{not json",)
    )
    conn.commit()
    conn.close()
    state = pd.extract_pilot(pilot_ws, "synthetic")
    assert any("P32" in w and "corrupt" in w for w in state.warnings)
    result = pd.run_differential(state)
    row = next(r for r in result["rows"] if r["node_id"] == "P32")
    assert row["native_verdict"] == "FAIL"  # status still read; only detail dropped
    assert any("P32" in w for w in result["warnings"])


def test_report_generation_renders_sections(pilot_ws: Path, tmp_path: Path):
    state = pd.extract_pilot(pilot_ws, "synthetic")
    result = pd.run_differential(state)
    md = pd.render_markdown(result)
    assert md.startswith("# Pilot Differential — synthetic")
    assert "## Node Differential" in md
    assert "## Mismatches" in md
    assert "P05" in md
    assert pd.LIMITATION_NOTE.splitlines()[0][:60] in md
    summary = pd.render_summary([result])
    assert "# Pilot Differential — Summary" in summary
    assert "synthetic" in summary
    out = tmp_path / "out"
    written = pd.write_reports([result], out)
    assert (out / "V1_2_PILOT_DIFFERENTIAL_synthetic.md").exists()
    assert (out / "V1_2_PILOT_DIFFERENTIAL_synthetic.json").exists()
    assert (out / "V1_2_PILOT_DIFFERENTIAL_SUMMARY.md").exists()
    assert len(written) == 3
    loaded = json.loads((out / "V1_2_PILOT_DIFFERENTIAL_synthetic.json").read_text())
    assert loaded["rows"][0]["node_id"]


def test_readonly_connection_rejects_writes(pilot_ws: Path):
    conn = pd.open_readonly(pilot_ws / ".paper-factory" / "runs.sqlite")
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("INSERT INTO runs(run_id, created_at, target_root) VALUES ('x','y','z')")
    conn.close()


def test_degraded_states_and_timing_are_reported(pilot_ws: Path):
    state = pd.extract_pilot(pilot_ws, "synthetic")
    result = pd.run_differential(state)
    rows = {r["node_id"]: r for r in result["rows"]}
    assert rows["P05"]["degraded"] is True
    assert rows["P04"]["degraded"] is False
    assert rows["P04"]["timing"]["duration_s"] == pytest.approx(2.0)
    assert rows["P10"]["timing"]["duration_s"] is None  # no timestamps stored


def test_unknown_run_id_raises(pilot_ws: Path):
    state = pd.extract_pilot(pilot_ws, "synthetic")
    with pytest.raises(KeyError):
        pd.run_differential(state, run_id="nope")
