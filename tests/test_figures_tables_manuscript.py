"""End-to-end tests for the figures/tables/manuscript pipeline modules against
the synthetic fixture project. Matplotlib is forced to the non-interactive Agg
backend BEFORE any pyplot import can happen.

The chain runs off the real statistics node
(paper_factory.statistics.metrics.run_statistics). (History: while
metrics.py had a three-dot relative-import bug, a stand-in wrote
paper_metrics.json; the strict-xfail sentinel flipped XPASS when the fix
landed and the chain was switched back — correction recorded, not deleted.)
"""
# ruff: noqa: I001  (matplotlib.use("Agg") must run before any pyplot import)
import matplotlib

matplotlib.use("Agg")

import csv
import shutil
import statistics
from pathlib import Path

import pytest

from paper_factory.core.config import (MarkingRegistry, PaperFactoryConfig,
                                       ProviderPolicyConfig, ProvidersConfig)
from paper_factory.core.results import Verdict
from paper_factory.core.util import read_json, sha256_file, utcnow, write_json
from paper_factory.dag.executor import NodeContext
from paper_factory.figures.build import run_figure_generation, run_figure_plan
from paper_factory.manuscript.scaffold import run_manuscript_architecture, run_section_check
from paper_factory.statistics.metrics import run_statistics
from paper_factory.state.store import Workspace
from paper_factory.tables.build import run_table_generation, run_table_plan

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "synthetic_project"

_DESIGN_PARAMS = {"seed", "load", "iteration", "run", "n"}


@pytest.fixture()
def ctx(tmp_path):
    """Workspace in tmp_path; only results/ is copied over from the fixture
    (the fixture itself is never modified)."""
    shutil.copytree(FIXTURE / "results", tmp_path / "results")
    ws = Workspace(tmp_path)
    context = NodeContext(workspace=ws, run_id="test-run",
                          config=PaperFactoryConfig(), providers=ProvidersConfig(),
                          policy=ProviderPolicyConfig(), marking=MarkingRegistry(),
                          offline=True, strict=True)
    outcome = run_statistics(context)
    assert outcome.verdict in (Verdict.PASS, Verdict.DEGRADED)
    import json as _json
    metrics = _json.loads((ws.reports_dir / 'paper_metrics.json').read_text())
    assert metrics["metrics"], "fixture must yield numeric metrics"
    return context


def test_statistics_module_importable():
    """Regression: metrics.py had a three-dot relative import (fixed 2026-09-21)."""
    import paper_factory.statistics.metrics  # noqa: F401


def test_figure_plan(ctx):
    outcome = run_figure_plan(ctx)
    assert outcome.verdict == Verdict.PASS
    plan_path = ctx.workspace.reports_dir / "figure_plan.json"
    assert plan_path.exists()
    plan = read_json(plan_path)
    assert plan["figures"], "expected at least one planned figure"
    by_id = {f["figure_id"]: f for f in plan["figures"]}
    assert "fig_experiment_runs__fpr" in by_id
    fpr = by_id["fig_experiment_runs__fpr"]
    assert fpr["kind"] == "line"
    assert fpr["group_field"] == "filter"
    assert fpr["x_field"] == "load"
    # determinism: same inputs -> same figure set
    assert read_json(ctx.workspace.reports_dir / "figure_plan.json")["figures"] == plan["figures"]


def test_figure_generation(ctx):
    assert run_figure_plan(ctx).verdict == Verdict.PASS
    outcome = run_figure_generation(ctx)
    assert outcome.verdict == Verdict.PASS, outcome.detail
    manifest_path = ctx.workspace.reports_dir / "figures_manifest.json"
    assert manifest_path.exists()
    manifest = read_json(manifest_path)
    assert manifest["source_script"] == "paper_factory/figures/build.py"
    assert manifest["build_command"]
    figures_dir = ctx.workspace.paper_dir / "figures"
    assert len(manifest["figures"]) == outcome.detail["figures"] > 0
    for entry in manifest["figures"]:
        assert entry["input_data_hashes"], entry["figure_id"]
        assert entry["caption"] and "<<PF:" not in entry["caption"], \
            "captions are generated deterministically, no placeholders"
        assert entry["validation"]["axis_labels_set"] is True
        assert entry["validation"]["files_nonempty"] is True
        for ext in ("pdf", "svg", "png"):
            p = figures_dir / f"{entry['figure_id']}.{ext}"
            assert p.exists(), f"missing {p}"
            assert p.stat().st_size > 0, f"empty {p}"


def test_table_plan_and_generation(ctx):
    assert run_table_plan(ctx).verdict == Verdict.PASS
    plan = read_json(ctx.workspace.reports_dir / "table_plan.json")
    assert plan["tables"], "expected at least one planned table"
    assert {"n", "mean", "std"} <= set(plan["tables"][0]["columns"])

    outcome = run_table_generation(ctx)
    assert outcome.verdict == Verdict.PASS, outcome.detail
    tex_path = ctx.workspace.paper_dir / "generated" / "tables.tex"
    text = tex_path.read_text(encoding="utf-8")
    assert "\\toprule" in text
    assert "\\midrule" in text
    assert "\\bottomrule" in text
    # a real metric value, recomputed independently straight from the CSV
    with open(ctx.workspace.target_root / "results" / "experiment_runs.csv",
              newline="", encoding="utf-8") as fh:
        fpr_vals = [float(r["fpr"]) for r in csv.DictReader(fh)]
    expected = f"{statistics.fmean(fpr_vals):.6g}"
    assert expected in text, f"metric mean {expected} not found in tables.tex"
    manifest = read_json(ctx.workspace.reports_dir / "tables_manifest.json")
    assert manifest["output"]["sha256"]
    assert manifest["tables"], "manifest must list rendered tables"


def test_manuscript_architecture_and_idempotency(ctx):
    outcome = run_manuscript_architecture(ctx)
    assert outcome.verdict == Verdict.PASS
    paper = ctx.workspace.paper_dir
    main = (paper / "main.tex").read_text(encoding="utf-8")
    assert "\\input{generated/numbers.tex}" in main
    assert "\\input{generated/tables.tex}" in main
    for section in ("abstract", "introduction", "methods", "results", "discussion"):
        assert (paper / "sections" / f"{section}.tex").exists()
    manifest = read_json(ctx.workspace.reports_dir / "manifest_manuscript.json")
    assert manifest["created"] == 6 and manifest["kept_existing"] == 0
    assert all(f["sha256"] for f in manifest["files"])

    # idempotency: existing content is never overwritten, only reported
    results_path = paper / "sections" / "results.tex"
    results_path.write_text("\\section{Results}\n\\label{sec:results}\ncustom\n",
                            encoding="utf-8")
    outcome2 = run_manuscript_architecture(ctx)
    assert outcome2.verdict == Verdict.PASS
    assert results_path.read_text(encoding="utf-8").endswith("custom\n")
    manifest2 = read_json(ctx.workspace.reports_dir / "manifest_manuscript.json")
    status = {f["path"]: f["status"] for f in manifest2["files"]}
    assert status["paper/sections/results.tex"] == "kept_existing"
    assert manifest2["kept_existing"] == 6 and manifest2["created"] == 0


def test_section_check(ctx):
    run_manuscript_architecture(ctx)
    # fresh scaffold still contains placeholders -> FAIL
    outcome = run_section_check(ctx, "results")
    assert outcome.verdict == Verdict.FAIL
    assert outcome.detail["placeholders"] > 0

    # finished prose without placeholders, consistent \label/\ref -> PASS
    results_path = ctx.workspace.paper_dir / "sections" / "results.tex"
    results_path.write_text(
        "\\section{Results}\n\\label{sec:results}\n"
        "As Section~\\ref{sec:results} shows, cuckoo beats bloom.\n",
        encoding="utf-8")
    ok = run_section_check(ctx, "results")
    assert ok.verdict == Verdict.PASS, ok.detail

    # dangling ref -> FAIL
    results_path.write_text(
        "\\section{Results}\n\\label{sec:results}\nSee \\ref{tab:does_not_exist}.\n",
        encoding="utf-8")
    bad = run_section_check(ctx, "results")
    assert bad.verdict == Verdict.FAIL
    assert bad.detail["dangling_refs"] == ["tab:does_not_exist"]

    # missing file -> FAIL
    missing = run_section_check(ctx, "appendix")
    assert missing.verdict == Verdict.FAIL
