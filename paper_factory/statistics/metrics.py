"""P09 Statistics: derive paper metrics from raw artifacts, never hand-typed.

Chain: raw (results/*.csv) → normalized → analysis → paper_metrics.json →
LaTeX macros (paper/generated/numbers.tex). Also computes the statistical
audit facts (n, std, CI, missing data) that reviews and closure rely on.
"""
from __future__ import annotations

import csv
import json
import math
import statistics
from pathlib import Path
from typing import Any

from ..core.results import Verdict
from ..core.util import sha256_file, utcnow, write_json
from ..dag.executor import NodeContext, NodeOutcome
from .quantitative import PFGET_ACCESSOR_LINE


def _mean_ci(values: list[float]) -> dict[str, Any]:
    n = len(values)
    mean = statistics.fmean(values)
    if n < 2:
        return {"n": n, "mean": mean, "std": None, "ci95": None,
                "small_sample": True,
                "note": "n<2: no spread estimable"}
    std = statistics.stdev(values)
    se = std / math.sqrt(n)
    # t-based CI with normal approximation fallback (small-n honesty: flagged)
    ci = 1.96 * se
    return {"n": n, "mean": mean, "std": std, "se": se, "ci95_halfwidth": ci,
            "small_sample": n < 5,
            "note": "normal-approx CI; n<5 flagged small_sample" if n < 5 else "normal-approx CI"}


_MISSING_SENTINELS = {"", "na", "n/a", "nan", "null", "none", "-"}

# replication axes / identifiers are never grouping columns and never outcomes
_EXCLUDE_NAMES = {"seed", "seeds", "seed_id", "random_seed", "rng_seed", "iteration",
                  "iter", "run", "runs", "run_id", "runid", "n", "rep", "reps",
                  "replicate", "trial", "trials", "index", "idx", "id", "fold",
                  "epoch", "step"}

# numeric columns with these names are design axes when they repeat across rows;
# repetition alone is NOT sufficient (a repeated measurement is an outcome —
# GAP-001 mirror bug, reviewer F2). Vocabulary + repetition = design.
_DESIGN_NAMES = {"load", "arm", "condition", "cond", "group", "batch", "level",
                 "temperature", "temp", "treatment", "cell", "config", "variant",
                 "setup", "design", "dataset", "lr", "learning_rate", "batch_size",
                 "depth", "width", "layers", "dim", "model_size"}


def _is_missing(s: str) -> bool:
    return s.strip().lower() in _MISSING_SENTINELS


def _parse_value(s: str) -> float | None:
    """Finite float or None. nan/inf never reach statistics (reviewer F1/F10)."""
    try:
        v = float(s)
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def macro_base_names(keys: list[str]) -> dict[str, str]:
    """Deterministic, collision-safe macro base names (reviewer F7).

    Sanitize (strip _ and -, '.' -> 'p'); when two keys sanitize to the same
    base, both get a content-hash suffix so neither silently overwrites.
    """
    def sanitize(k: str) -> str:
        return k.replace("-", "_").replace(".", "p").replace("_", "")

    bases: dict[str, str] = {}
    by_base: dict[str, list[str]] = {}
    for k in keys:
        by_base.setdefault(sanitize(k), []).append(k)
    import hashlib
    for base, ks in by_base.items():
        if len(ks) == 1:
            bases[ks[0]] = base
        else:
            for k in ks:
                bases[k] = f"{base}x{hashlib.sha256(k.encode()).hexdigest()[:6]}"
    return bases


def expected_macro_entries(metrics: dict[str, Any]) -> dict[str, str]:
    """The macro definitions that generated/numbers.tex MUST contain for the
    given metrics — shared by the generator (P09) and the closure binding
    check (U2), so provenance is verified, not just asserted (reviewer F3)."""
    entries: dict[str, str] = {}
    bases = macro_base_names(list(metrics.keys()))
    for key, stat in metrics.items():
        base = bases[key]
        entries[f"{base}mean"] = f"{stat['mean']:.6g}"
        if stat.get("std") is not None:
            entries[f"{base}std"] = f"{stat['std']:.6g}"
        entries[f"{base}n"] = str(stat["n"])
    return entries


def _load_csv(path: Path) -> tuple[list[str], list[dict[str, str]], list[str]]:
    with open(path, newline="", encoding="utf-8-sig") as fh:  # -sig strips BOM (reviewer F5)
        reader = csv.DictReader(fh)
        raw_fields = list(reader.fieldnames or [])
        stripped = [f.strip() for f in raw_fields]
        warnings = []
        if len(stripped) != len(set(stripped)):
            dupes = sorted({f for f in stripped if stripped.count(f) > 1})
            warnings.append(f"duplicate header columns shadowed: {dupes}")
        fields = []
        seen_fields: set[str] = set()
        for f in stripped:
            if f not in seen_fields:  # duplicate headers shadow; keep first (R5/F-R4)
                fields.append(f)
                seen_fields.add(f)
        rows = [{k.strip(): v for k, v in r.items()} for r in reader if k_is_str(r)]
        return fields, rows, warnings


def k_is_str(row: dict) -> bool:
    return all(isinstance(k, str) for k in row)


def run_statistics(ctx: NodeContext) -> NodeOutcome:
    root = ctx.workspace.target_root
    results_dir = root / "results"
    if not results_dir.is_dir():
        return NodeOutcome(Verdict.DEGRADED, {"reason": "no results/ directory — no metrics derivable"})

    metrics: dict[str, Any] = {"computed_at": utcnow(), "sources": {}, "metrics": {},
                               "audit": {"missing_cells": 0, "missing_group_keys": 0,
                                         "exclusions": [], "classification": {},
                                         "small_samples": [], "randomization": "recorded_in_source",
                                         "grouping": "grouped by detected design columns "
                                                     "(see classification); single global group "
                                                     "when none are present"}}
    macro_header = ["% generated by paper-factory statistics — do not hand-edit",
                    "\\makeatletter",
                    PFGET_ACCESSOR_LINE,
                    "\\makeatother"]

    for csv_path in sorted(results_dir.glob("*.csv")):
        fields, rows, warnings = _load_csv(csv_path)
        src_key = str(csv_path.relative_to(root))
        metrics["sources"][src_key] = {"sha256": sha256_file(csv_path), "rows": len(rows)}
        for w in warnings:
            metrics["audit"]["exclusions"].append({"source": src_key, "reason": w})
        # numeric = at least one parseable value and every non-missing cell parses;
        # missing = sentinel OR non-finite (nan/inf) — both audited identically (R2)
        numeric_fields = []
        for f in fields:
            vals = [(r.get(f) or "").strip() for r in rows]
            present = [v for v in vals
                       if not _is_missing(v) and not (_try_float(v) and _parse_value(v) is None)]
            n_missing = len(vals) - len(present)
            if n_missing:
                metrics["audit"]["missing_cells"] += n_missing
                metrics["audit"]["exclusions"].append(
                    {"column": f, "missing": n_missing, "source": src_key})
            if present and all(_try_float(v) for v in present):
                numeric_fields.append(f)
        # replication axes / identifiers are neither group keys nor outcomes
        excluded = [f for f in fields if f.lower() in _EXCLUDE_NAMES]
        for f in excluded:
            metrics["audit"]["classification"][f] = {"class": "excluded",
                                                     "reason": "replication axis / identifier name"}
        # identifier text columns (unique per row) are never group keys;
        # text columns above the group-cardinality cap are dropped VISIBLY (R6)
        text_fields = []
        for f in fields:
            if f in numeric_fields or f in excluded:
                continue
            distinct_text = len({(r.get(f, "").strip()) for r in rows
                                 if not _is_missing(r.get(f, ""))})
            if 1 < distinct_text <= 12:
                text_fields.append(f)
                reason = "categorical grouping column"
                if f.lower() in _DESIGN_NAMES:
                    # a design-named column that failed numeric parsing (garbage
                    # cells) falls back to text grouping — visibly, not silently
                    reason = ("design-vocabulary name but non-numeric cells — "
                              "grouped as text")
                metrics["audit"]["classification"][f] = {
                    "class": "text_group", "distinct": distinct_text, "reason": reason}
            else:
                metrics["audit"]["classification"][f] = {
                    "class": "ignored_text", "distinct": distinct_text,
                    "reason": "text column outside group-cardinality window (1<d<=12)"}
        # design parameters: numeric, repeating across rows, and named like a
        # design axis (load, condition, …). Repetition alone is NOT sufficient —
        # a repeated measurement (binary success, ternary error counts) is an
        # outcome, not a grouping axis (GAP-001 mirror bug, post-pilot review).
        design_nums = []
        for f in numeric_fields:
            if f in excluded:
                continue
            vals = [_parse_value(r.get(f, "")) for r in rows]
            present = [v for v in vals if v is not None]
            distinct = len(set(present))
            if f.lower() in _DESIGN_NAMES and 1 < distinct < len(rows):
                design_nums.append(f)
                metrics["audit"]["classification"][f] = {
                    "class": "design", "reason": "design-vocabulary name, repeats across rows",
                    "distinct": distinct}
        group_cols = text_fields + design_nums
        outcome_fields = []
        for f in numeric_fields:
            if f in excluded or f in design_nums:
                continue
            vals = [_parse_value(r.get(f, "")) for r in rows]
            present = [v for v in vals if v is not None]
            if len(set(present)) > 1:
                outcome_fields.append(f)
                # sharpened reason (R1): an off-vocabulary repeating column is a
                # visible classification decision, not silently "a measurement"
                reason = ("distinct measurement" if len(set(present)) == len(rows)
                          else "repeats across rows but name not in design vocabulary "
                               "— classified outcome")
                metrics["audit"]["classification"][f] = {
                    "class": "outcome", "reason": reason,
                    "distinct": len(set(present))}

        groups: dict[tuple, list[dict[str, str]]] = {}
        display: dict[tuple, tuple[str, ...]] = {}
        for r in rows:
            norm_key = []
            disp = []
            row_unattributable = False
            for c in group_cols:
                raw = (r.get(c, "") or "").strip()
                if c in design_nums:
                    v = _parse_value(raw)
                    if v is None:
                        row_unattributable = True
                        norm_key.append(None)
                        disp.append("(missing)")
                        continue
                    norm_key.append(v)      # group by VALUE, not raw string (F6)
                    disp.append(raw)
                elif _is_missing(raw):
                    row_unattributable = True
                    norm_key.append(None)
                    disp.append("(missing)")
                else:
                    norm_key.append(raw)
                    disp.append(raw)
            if row_unattributable:
                # a row without full group identity cannot be attributed to any
                # condition — it is counted, but forms no (pseudo-)group (F-R3)
                metrics["audit"]["missing_group_keys"] += 1
                continue
            nk = tuple(norm_key)
            groups.setdefault(nk, []).append(r)
            display.setdefault(nk, tuple(disp))

        for gkey, grows in sorted(groups.items(), key=lambda kv: tuple(
                (str(x) for x in kv[0]))):
            disp = display[gkey]
            gname = "__".join(f"{c}{v}" for c, v in zip(group_cols, disp) if v)
            for f in outcome_fields:
                vals = []
                for r in grows:
                    cell = (r.get(f) or "").strip()
                    v = _parse_value(cell)
                    if v is None:
                        continue  # sentinel and non-finite cells were already
                        # counted in the per-column audit pass (F-R2: no double count)
                    vals.append(v)
                if not vals:
                    continue
                stat = _mean_ci(vals)
                key = f"{csv_path.stem}__{f}" + (f"__{gname}" if gname else "")
                metrics["metrics"][key] = {"source": src_key, "field": f,
                                           "group": dict(zip(group_cols, disp)), **stat}
                if stat.get("small_sample"):
                    metrics["audit"]["small_samples"].append(key)

    macro_lines = macro_header
    bases = macro_base_names(list(metrics["metrics"].keys()))
    for key, stat in metrics["metrics"].items():
        base = bases[key]
        macro_lines.append(f"\\expandafter\\gdef\\csname pf@{base}mean\\endcsname{{{stat['mean']:.6g}}}")
        if stat.get("std") is not None:
            macro_lines.append(f"\\expandafter\\gdef\\csname pf@{base}std\\endcsname{{{stat['std']:.6g}}}")
        macro_lines.append(f"\\expandafter\\gdef\\csname pf@{base}n\\endcsname{{{stat['n']}}}")

    # persist the audit even when no metrics were derivable (R4): the
    # classification/exclusion trail is exactly what a DEGRADED diagnosis needs.
    # Downstream nodes degrade on empty metrics identically (they test content).
    write_json(ctx.workspace.reports_dir / "paper_metrics.json", metrics)
    gen = ctx.workspace.paper_dir / "generated"
    gen.mkdir(parents=True, exist_ok=True)
    (gen / "numbers.tex").write_text("\n".join(macro_lines) + "\n", encoding="utf-8")

    if not metrics["metrics"]:
        return NodeOutcome(Verdict.DEGRADED, {"reason": "no numeric outcome fields found",
                                              "sources": metrics["sources"]})

    return NodeOutcome(Verdict.PASS, {"metric_count": len(metrics["metrics"]),
                                      "small_samples": metrics["audit"]["small_samples"]})


def _try_float(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def run_integrity_audit(ctx: NodeContext) -> NodeOutcome:
    """P05: cross-check numbers asserted in drafts against derived metrics.

    Two deterministic checks:
    1. significance_without_test — 'p < x' / 'significant' claims with no
       computed statistical test artifact (MAJOR).
    2. number_mismatch — a draft decimal in the *range* of a derived metric
       (0.5x–2x) but >5% off from every metric: close enough to be a misquote.
       Significance contexts (p < …) are excluded from the number scan.
    """
    import re

    root = ctx.workspace.target_root
    metrics_path = ctx.workspace.reports_dir / "paper_metrics.json"
    findings: list[dict[str, Any]] = []
    drafts = sorted(root.glob("draft/*.md")) + sorted(root.glob("draft/*.tex"))

    sig_pat = re.compile(r"(p\s*[<≤=]\s*0?\.\d+|statistically significant|significant\b)",
                         re.I)
    num_pat = re.compile(r"\b\d+\.\d{2,}%?\b")

    metrics: dict[str, Any] = {}
    true_values: dict[str, float] = {}
    has_test_artifact = False
    if metrics_path.exists():
        metrics = json.loads(metrics_path.read_text(encoding="utf-8")).get("metrics", {})
        true_values = {k: v["mean"] for k, v in metrics.items()}
    # a statistical test artifact is a results/analysis file carrying an actual
    # p-value/statistic field — not a filename that happens to contain "test"
    for candidate in list((root / "results").glob("*.json")) + list((root / "analysis").glob("*.json")):
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        text = json.dumps(data).lower()
        if any(k in text for k in ('"p_value"', '"pvalue"', '"p"', '"statistic"', '"test_name"')):
            if '"p_value"' in text or '"pvalue"' in text or '"statistic"' in text:
                has_test_artifact = True
                break

    for d in drafts:
        text = d.read_text(encoding="utf-8", errors="replace")
        raw_spans = sorted(m.span() for m in sig_pat.finditer(text))
        sig_spans = []
        for sp in raw_spans:  # dedupe overlapping matches (alternation hits twice)
            if sig_spans and sp[0] <= sig_spans[-1][1]:
                continue
            sig_spans.append(sp)
        if sig_spans and not has_test_artifact:
            for sp in sig_spans:
                findings.append({
                    "severity": "MAJOR", "kind": "significance_without_test",
                    "draft": str(d.relative_to(root)), "span": list(sp),
                    "excerpt": text[max(0, sp[0] - 60):sp[1] + 40].strip()[:160],
                    "note": "significance claimed; no statistical test artifact exists",
                })
        for m in num_pat.finditer(text):
            if any(sp[0] - 12 <= m.start() <= sp[1] + 2 for sp in sig_spans):
                continue  # part of a p-value expression, not a result number
            val = float(m.group(0).rstrip("%"))
            if not true_values:
                continue
            decimals = len(m.group(0).split(".")[1]) if "." in m.group(0) else 0
            round_unit = 0.5 * 10 ** (-decimals)  # rounding unit of the printed value

            def matches(t: float) -> bool:
                tol = max(0.05 * abs(t), round_unit)  # 5% or print-rounding, whichever is looser
                return abs(val - t) <= tol

            if any(matches(t) for t in true_values.values()):
                continue  # matches a metric within tolerance
            in_range = [k for k, t in true_values.items()
                        if t and 0.5 * abs(t) <= abs(val) <= 2.0 * abs(t)]
            if in_range:
                closest = min(true_values, key=lambda k: abs(true_values[k] - val))
                findings.append({
                    "severity": "MAJOR", "kind": "number_mismatch",
                    "draft": str(d.relative_to(root)), "value": val,
                    "closest_metric": closest, "true_value": true_values[closest],
                    "note": "draft number within metric range but off every derived metric "
                            "(tolerance: 5% or print rounding unit)",
                })
    report = {"audited_at": utcnow(), "findings": findings,
              "drafts_checked": [str(d.relative_to(root)) for d in drafts]}
    write_json(ctx.workspace.reports_dir / "integrity_audit.json", report)
    # The audit PASSes when it executed completely; findings carry the red and
    # flow into reviews (P23–P26) and closure (U2/U5), which is where blocking
    # happens — after remediation (P27) had its chance.
    return NodeOutcome(Verdict.PASS, {"findings": len(findings),
                                      "kinds": sorted({f["kind"] for f in findings})})
