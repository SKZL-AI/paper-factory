"""Regression tests for gaps found by REAL PILOT 01 (MassInv Paper A).

GAP-001 (core): the design-parameter heuristic in run_statistics classified
every numeric column of a SMALL aggregated table (<=12 rows, all values
distinct) as a design parameter, leaving no outcome fields -> P09 DEGRADED
on real contrast tables. A design parameter must REPEAT across rows; a
numeric column whose values are all unique is a measurement, not a grouping
axis.

GAP-002 (core): figure/table planning hard-FAILed when paper_metrics.json was
missing, which killed 25 downstream nodes. Honest verdict is DEGRADED
(nothing derivable), letting independent work continue — FAIL blocks the DAG,
DEGRADED is recorded and reported.
"""
from __future__ import annotations

from pathlib import Path

from paper_factory.core.config import (MarkingRegistry, PaperFactoryConfig,
                                       ProviderPolicyConfig, ProvidersConfig)
from paper_factory.core.results import Verdict
from paper_factory.dag.executor import NodeContext
from paper_factory.figures.build import run_figure_plan
from paper_factory.state.store import Workspace
from paper_factory.statistics.metrics import run_statistics
from paper_factory.tables.build import run_table_plan


def _ctx(tmp_path: Path) -> NodeContext:
    return NodeContext(workspace=Workspace(tmp_path), run_id="test-pilot-gaps",
                       config=PaperFactoryConfig(), providers=ProvidersConfig(),
                       policy=ProviderPolicyConfig(), marking=MarkingRegistry(),
                       offline=True, strict=True)


def test_gap001_small_contrast_table_yields_outcome_metrics(tmp_path):
    # real MassInv shape: 12 rows, every numeric value distinct (aggregated
    # per-cell results) — previously ALL numeric columns became "design params"
    results = tmp_path / "results"
    results.mkdir()
    (results / "k4_recompute.csv").write_text(
        "arm,cell,nll,ppl\n"
        + "".join(f"muon@5000,cell_{i},{4.6 + i * 0.1:.4f},{100 + i}\n"
                  for i in range(12)),
        encoding="utf-8")
    ctx = _ctx(tmp_path)
    outcome = run_statistics(ctx)
    assert outcome.verdict == Verdict.PASS, outcome.detail
    import json
    metrics = json.loads(
        (ctx.workspace.reports_dir / "paper_metrics.json").read_text())["metrics"]
    assert any(m["field"] == "nll" for m in metrics.values()), metrics.keys()
    assert any(m["field"] == "ppl" for m in metrics.values()), metrics.keys()


def test_gap001_repeating_numeric_column_still_a_design_parameter(tmp_path):
    # the heuristic's purpose must survive: values that REPEAT across rows
    # remain grouping axes (regression guard for the fixture behavior)
    results = tmp_path / "results"
    results.mkdir()
    rows = ["seed,load,fpr"]
    for seed in (42, 43, 44):
        for load in ("0.90", "0.95"):
            rows.append(f"{seed},{load},{0.01 + seed * 1e-4 + float(load):.6f}")
    (results / "experiment_runs.csv").write_text("\n".join(rows) + "\n",
                                                 encoding="utf-8")
    ctx = _ctx(tmp_path)
    outcome = run_statistics(ctx)
    assert outcome.verdict == Verdict.PASS, outcome.detail
    import json
    metrics = json.loads(
        (ctx.workspace.reports_dir / "paper_metrics.json").read_text())["metrics"]
    assert any(m["group"].get("load") == "0.90" for m in metrics.values())


def test_gap002_figure_plan_degrades_without_metrics(tmp_path):
    ctx = _ctx(tmp_path)
    outcome = run_figure_plan(ctx)
    assert outcome.verdict == Verdict.DEGRADED  # honest: nothing derivable


def test_gap002_table_plan_degrades_without_metrics(tmp_path):
    ctx = _ctx(tmp_path)
    outcome = run_table_plan(ctx)
    assert outcome.verdict == Verdict.DEGRADED
