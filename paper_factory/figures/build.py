"""P10 Figures: deterministic figure plan from paper_metrics.json, then
rendering of the planned figures from raw results/*.csv with matplotlib
(Agg backend only, never interactive).

Numbers come from the source CSVs, never hand-typed. Every rendered figure
is recorded in reports/figures_manifest.json with input data hashes, plot
parameters, a caption placeholder and a reproducible build command.
Series are distinguished by marker AND linestyle (Okabe-Ito palette), so
no encoding relies on color alone (colorblind-safe).
"""
from __future__ import annotations

import argparse
import csv
import statistics
import sys
from pathlib import Path
from typing import Any

from ..core.results import Verdict
from ..core.util import read_json, sha256_file, utcnow, write_json
from ..dag.executor import NodeContext, NodeOutcome

_SOURCE_SCRIPT = "paper_factory/figures/build.py"

# Okabe-Ito colorblind-safe palette.
_PALETTE = ["#000000", "#E69F00", "#56B4E9", "#009E73",
            "#F0E442", "#0072B2", "#D55E00", "#CC79A7"]
_MARKERS = ["o", "s", "^", "D", "v", "P", "X", "*"]
_LINESTYLES = ["-", "--", "-.", ":"]
_HATCHES = ["", "//", "xx", "..", "\\\\", "++"]
_MAX_SERIES = 12

# Same design-parameter exclusion as statistics.metrics: these are inputs,
# not outcomes, and become candidate x-axes instead of plotted metrics.
_DESIGN_PARAMS = {"seed", "load", "iteration", "run", "n"}


def _column_kinds(path: Path) -> tuple[list[str], list[dict[str, str]], dict[str, dict[str, Any]]]:
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    kinds: dict[str, dict[str, Any]] = {}
    for f in fields:
        cells = [(r.get(f) or "").strip() for r in rows]
        nonempty = [c for c in cells if c]
        numeric = bool(nonempty)
        for c in nonempty:
            try:
                float(c)
            except ValueError:
                numeric = False
                break
        kinds[f] = {"numeric": numeric, "unique": len(set(nonempty))}
    return fields, rows, kinds


def _pick_group_field(fields: list[str], kinds: dict[str, dict[str, Any]], nrows: int) -> str | None:
    """Categorical column usable for series grouping: more than one distinct
    value, but not a per-row identifier (unique < nrows). Deterministic:
    fewest distinct values first, ties broken by header order."""
    candidates = [
        f for f in fields
        if not kinds[f]["numeric"] and 1 < kinds[f]["unique"] < max(nrows, 2)
        and kinds[f]["unique"] <= _MAX_SERIES
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda f: (kinds[f]["unique"], fields.index(f)))


def _pick_x_field(fields: list[str], kinds: dict[str, dict[str, Any]], nrows: int) -> str | None:
    """Numeric design parameter usable as x-axis. Deterministic: most
    distinct values first (richest axis), ties broken by header order."""
    candidates = [
        f for f in fields
        if kinds[f]["numeric"] and f.lower() in _DESIGN_PARAMS
        and 1 < kinds[f]["unique"] < max(nrows, 2)
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda f: (-kinds[f]["unique"], fields.index(f)))


def run_figure_plan(ctx: NodeContext) -> NodeOutcome:
    """Derive a figure plan from reports/paper_metrics.json.

    One figure per numeric metric group: a line suggestion (metric vs design
    parameter, one series per category) when the source CSV has a categorical
    grouping column and a numeric design parameter, else a bar suggestion.
    """
    metrics_path = ctx.workspace.reports_dir / "paper_metrics.json"
    if not metrics_path.exists():
        # honest degradation, not a hard failure: with no derived metrics
        # there is nothing to plan figures from — recorded, not blocking
        return NodeOutcome(Verdict.DEGRADED,
                           {"reason": "no paper_metrics.json — no figures derivable"})
    doc = read_json(metrics_path)
    metrics: dict[str, Any] = doc.get("metrics") or {}
    if not metrics:
        return NodeOutcome(Verdict.DEGRADED,
                           {"reason": "paper_metrics.json has no metrics — no figures derivable"})
    plan: dict[str, Any] = {"planned_at": utcnow(), "metrics_sha256": sha256_file(metrics_path),
                            "figures": [], "skipped": []}

    by_source: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for key in sorted(metrics):
        by_source.setdefault(metrics[key]["source"], []).append((key, metrics[key]))

    for source in sorted(by_source):
        csv_path = ctx.workspace.target_root / source
        if not csv_path.exists():
            for key, _m in by_source[source]:
                plan["skipped"].append({"metric_key": key, "reason": f"source {source} missing"})
            continue
        fields, rows, kinds = _column_kinds(csv_path)
        group_field = _pick_group_field(fields, kinds, len(rows))
        x_field = _pick_x_field(fields, kinds, len(rows))
        seen_fields: set[str] = set()
        for key, m in by_source[source]:
            # grouped metrics share (source, field): one figure per outcome field
            if m["field"] in seen_fields:
                continue
            seen_fields.add(m["field"])
            figure_id = f"fig_{Path(source).stem}__{m['field']}".replace("-", "_")
            kind = "line" if (group_field and x_field) else "bar"
            if kind == "line":
                title = f"{m['field']} vs {x_field} by {group_field}"
            else:
                title = f"{m['field']} per row ({Path(source).stem})"
            plan["figures"].append({
                "figure_id": figure_id,
                "kind": kind,
                "source": source,
                "metric_key": key,
                "y_field": m["field"],
                "x_field": x_field,
                "group_field": group_field,
                "title": title,
                "caption": "Generated from hashed source data; see manifest for input hashes and parameters.",
                "outputs": {ext: f"paper/figures/{figure_id}.{ext}" for ext in ("pdf", "svg", "png")},
            })

    write_json(ctx.workspace.reports_dir / "figure_plan.json", plan)
    if not plan["figures"]:
        return NodeOutcome(Verdict.DEGRADED, {"reason": "no plottable metrics found",
                                              "skipped": plan["skipped"]})
    return NodeOutcome(Verdict.PASS, {"figures": len(plan["figures"]),
                                      "skipped": len(plan["skipped"])})


def _render_figure(ctx: NodeContext, fig: dict[str, Any], plt: Any, out_dir: Path) -> tuple[dict[str, Any], str | None]:
    fid = fig["figure_id"]
    entry: dict[str, Any] = {
        "figure_id": fid, "kind": fig["kind"], "source": fig["source"],
        "input_data_hashes": {},
        "parameters": {"kind": fig["kind"], "x_field": fig["x_field"],
                       "y_field": fig["y_field"], "group_field": fig["group_field"],
                       "palette": "okabe-ito", "series_encoding": "color+marker+linestyle",
                       "png_dpi": 150},
        "caption": fig["caption"],
        "files": {}, "validation": {},
    }
    csv_path = ctx.workspace.target_root / fig["source"]
    if not csv_path.exists():
        entry["validation"]["error"] = "source_missing"
        return entry, f"{fid}: source {fig['source']} missing"
    entry["input_data_hashes"][fig["source"]] = sha256_file(csv_path)
    _fields, rows, _kinds = _column_kinds(csv_path)

    figobj, ax = plt.subplots(figsize=(6, 4))
    if fig["kind"] == "line":
        groups = sorted({(r.get(fig["group_field"]) or "").strip() for r in rows})
        for i, g in enumerate(groups):
            pts: dict[float, list[float]] = {}
            for r in rows:
                if (r.get(fig["group_field"]) or "").strip() != g:
                    continue
                try:
                    x = float(r[fig["x_field"]])
                    y = float(r[fig["y_field"]])
                except (KeyError, TypeError, ValueError):
                    continue
                pts.setdefault(x, []).append(y)
            xs = sorted(pts)
            means = [statistics.fmean(pts[x]) for x in xs]
            stds = [statistics.stdev(pts[x]) if len(pts[x]) > 1 else 0.0 for x in xs]
            ax.errorbar(xs, means, yerr=stds, label=g,
                        color=_PALETTE[i % len(_PALETTE)],
                        marker=_MARKERS[i % len(_MARKERS)],
                        linestyle=_LINESTYLES[i % len(_LINESTYLES)],
                        capsize=3, linewidth=1.5, markersize=5)
        ax.set_xlabel(fig["x_field"])
        ax.set_ylabel(f"{fig['y_field']} (mean ± std)")
        ax.legend()
    else:  # bar
        vals: list[float] = []
        labels: list[str] = []
        for idx, r in enumerate(rows):
            try:
                vals.append(float(r[fig["y_field"]]))
            except (KeyError, TypeError, ValueError):
                continue
            labels.append(str(idx))
        bars = ax.bar(labels, vals,
                      color=[_PALETTE[i % len(_PALETTE)] for i in range(len(vals))],
                      edgecolor="black")
        for bar, hatch in zip(bars, [_HATCHES[i % len(_HATCHES)] for i in range(len(vals))]):
            bar.set_hatch(hatch)
        ax.set_xlabel("row")
        ax.set_ylabel(fig["y_field"])
    ax.set_title(fig["title"])

    validation = {"axis_labels_set": bool(ax.get_xlabel()) and bool(ax.get_ylabel()),
                  "files_nonempty": True}
    files: dict[str, Any] = {}
    ok = validation["axis_labels_set"]
    for ext in ("pdf", "svg", "png"):
        p = out_dir / f"{fid}.{ext}"
        if ext == "png":
            figobj.savefig(p, dpi=150, bbox_inches="tight")
        else:
            figobj.savefig(p, bbox_inches="tight")
        if p.exists() and p.stat().st_size > 0:
            files[ext] = {"path": str(p.relative_to(ctx.workspace.root)),
                          "sha256": sha256_file(p), "bytes": p.stat().st_size}
        else:
            validation["files_nonempty"] = False
            ok = False
    plt.close(figobj)
    entry["files"] = files
    entry["validation"] = validation
    if not ok:
        return entry, f"{fid}: validation failed {validation}"
    return entry, None


def run_figure_generation(ctx: NodeContext) -> NodeOutcome:
    """Render every figure in reports/figure_plan.json to PDF+SVG+PNG under
    paper/figures/ and write reports/figures_manifest.json. FAIL if any
    planned figure is missing or invalid."""
    plan_path = ctx.workspace.reports_dir / "figure_plan.json"
    if not plan_path.exists():
        return NodeOutcome(Verdict.DEGRADED,
                           {"reason": "no figure_plan.json — planning degraded upstream"})
    plan = read_json(plan_path)
    figures: list[dict[str, Any]] = plan.get("figures") or []
    if not figures:
        return NodeOutcome(Verdict.DEGRADED, {"reason": "figure plan is empty — nothing to render"})

    import matplotlib

    matplotlib.use("Agg")  # non-interactive backend, forced before pyplot import
    import matplotlib.pyplot as plt

    out_dir = ctx.workspace.paper_dir / "figures"
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "generated_at": utcnow(),
        "source_script": _SOURCE_SCRIPT,
        "build_command": f"{sys.executable} -m paper_factory.figures.build --target {ctx.workspace.target_root}",
        "plan_sha256": sha256_file(plan_path),
        "figures": [],
    }
    failures: list[str] = []
    for fig in figures:
        entry, err = _render_figure(ctx, fig, plt, out_dir)
        manifest["figures"].append(entry)
        if err:
            failures.append(err)
    write_json(ctx.workspace.reports_dir / "figures_manifest.json", manifest)
    if failures:
        return NodeOutcome(Verdict.FAIL, {"failed": failures,
                                          "rendered": len(manifest["figures"]) - len(failures)})
    return NodeOutcome(Verdict.PASS, {"figures": len(manifest["figures"])})


def main(argv: list[str] | None = None) -> int:
    """Manual rebuild entry point referenced by figures_manifest.build_command."""
    from ..core.config import (
        MarkingRegistry,
        PaperFactoryConfig,
        ProviderPolicyConfig,
        ProvidersConfig,
    )
    from ..state.store import Workspace

    parser = argparse.ArgumentParser(description="Rebuild planned figures for a target project")
    parser.add_argument("--target", required=True, help="target project root containing results/")
    args = parser.parse_args(argv)
    ctx = NodeContext(workspace=Workspace(Path(args.target)), run_id="manual-figures",
                      config=PaperFactoryConfig(), providers=ProvidersConfig(),
                      policy=ProviderPolicyConfig(), marking=MarkingRegistry(), offline=True)
    plan = run_figure_plan(ctx)
    if not plan.verdict.is_ok:
        print(f"figure_plan: {plan.verdict.value} {plan.detail}")
        return 1
    gen = run_figure_generation(ctx)
    print(f"figure_generation: {gen.verdict.value} {gen.detail}")
    return 0 if gen.verdict.is_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
