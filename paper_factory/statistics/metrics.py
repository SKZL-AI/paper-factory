"""P09 Statistics: derive paper metrics from raw artifacts, never hand-typed.

Chain: raw (results/*.csv) → normalized → analysis → paper_metrics.json →
LaTeX macros (paper/generated/numbers.tex). Also computes the statistical
audit facts (n, std, CI, missing data) that reviews and closure rely on.
"""
from __future__ import annotations

import csv
import json
import math
import re
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


# --- GAP-003: contextual number→metric binding -------------------------------
# layout zones are not prose: grid environments, markdown tables, column specs
_GRID_ENV = re.compile(
    r"\\begin\{(?:tabular|tabularx|longtable|array|supertabular)\*?\}.*?"
    r"\\end\{(?:tabular|tabularx|longtable|array|supertabular)\*?\}", re.S)
_MD_TABLE_ROW = re.compile(r"(?m)^\s*\|.*\|\s*$")
_LAYOUT_DIM = re.compile(r"\b\d+(?:\.\d+)?\s*\\(?:linewidth|textwidth|columnwidth"
                         r"|paperwidth|pt|mm|cm|em|ex)\b")
_RATIO_PAT = re.compile(r"\b(\d+(?:\.\d+)?)\s*(?:x\b|-\s*fold\b)", re.I)
_COUNT_PAT = re.compile(
    r"\b\d+\s*/\s*\d+\b"                                     # 9/9 cells
    r"|\b[nN]\s*=\s*\d+\b"                                   # n = 18
    r"|\b\d+\s*(?:seeds|runs|cells|configs|configurations|universes|tokens|"
    r"experiments|baselines|models|arms|iterations|epochs)\b", re.I)
_DEC_PAT = re.compile(r"\b\d+\.\d+\b(?!\s*%)")               # 0.021 (1+ decimals; % handled by _PCT_PAT)
_PCT_PAT = re.compile(r"\b\d+(?:\.\d+)?\s*%")
_SEMANTIC_SKIP = re.compile(
    r"\b(within|window|threshold|froze|frozen|tolerance|budget"
    r"|approximately|approx\.?|roughly)\b", re.I)
_RESULT_CUE = re.compile(
    r"\b(achiev|reach|improv|outperform|faster|slower|significant|lower|higher|"
    r"reduc|gain|win|better|beat)", re.I)

# field-name aliases for context binding (word-boundary matched, case-insensitive)
_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "fpr": ("false-positive rate", "false positive rate", "fpr"),
    "nll": ("nll", "negative log-likelihood", "negative log", "log-loss", "loss"),
    "ppl": ("ppl", "perplexity"),
    "latency": ("latency",),
    "throughput": ("throughput",),
    "energy": ("energy",),
    "accuracy": ("accuracy",),
    "time": ("runtime", "run time"),
}
# dimension qualifiers in metric field names carry no sentence meaning of their
# own — relation words included: 'A_minus_B' must not bind to any sentence that
# merely says 'minus' (pilot FP class; the word names a different contrast)
_FIELD_DIM_TOKENS = {"ratio", "factor", "fold", "diff", "rate", "score", "mean",
                     "std", "rel", "abs", "minus", "plus", "vs", "versus",
                     "contrast", "delta", "change"}
# comparative sentences assert DIFFERENCES, not levels — they may only bind to
# metrics whose field signals derived semantics (diff/ratio/contrast/…)
_COMPARATIVE = re.compile(
    r"\b(?:worse|better|higher|lower|faster|slower|more|less)\s+than\b"
    r"|\bdiffer(?:ence|ences|s|ent)?\b|\bminus\b|\bcontrasts?\b|\bspread\b", re.I)
_DIFF_FIELD = re.compile(r"diff|minus|delta|ratio|factor|fold|contrast|change|"
                         r"drop|gain|spread", re.I)
# exceptive/negation markers directly before an anchor disqualify it
# (reviewer B R1): "Latency, unlike the loss, reaches 5.0" — the number still
# belongs to latency. 'while'/'but' are NOT exceptive: neutral clauses.
_EXCEPTIVE = re.compile(
    r"\b(?:unlike|not|never|rather\s+than|instead\s+of|as\s+opposed\s+to|"
    r"versus|vs\.?|except)\b", re.I)
# window before an anchor mention, sized for the longest marker + article
_EXCEPTIVE_ANCHOR_WINDOW = 20
# universal quantifier near a dimension word ('at every load', 'per load')
# disables the point-anchor exemption and demands the value hold for EVERY
# bound group (reviewer B R2)
_UNIVERSAL = re.compile(r"\b(?:every|each|all|any|per)\b", re.I)
# number-negation must reach verb-distance: 'does not reach a latency of 5.0'
# negates the whole assertion (reviewer B W3/X4: stems, no trailing boundary).
# The negation itself is then EVALUATED against the bound metrics — never
# silently skipped (X2: 'does not reach 5.0' with latency=5.0 is a false claim).
_NEGATION_VERB = re.compile(
    r"\b(?:not|never|n't)\b[^.;?!]{0,28}?\b(?:reach|is|was|were|be|become|"
    r"remain|stand|lie|stay|fall|drop|rise|improve|get|exceed|surpass|top|climb)", re.I)
# cap/floor polarity inside a negated claim (X3): 'never exceeds C' claims
# metric ≤ C; 'never below C' claims metric ≥ C
_CAP_WORDS = re.compile(r"\b(?:exceed|surpass|above|over|top|higher\s+than|"
                        r"greater\s+than|more\s+than)", re.I)
_FLOOR_WORDS = re.compile(r"\b(?:below|under|less\s+than|fewer\s+than|"
                          r"lower\s+than)", re.I)
_RANGE_PAT = re.compile(
    r"\bbetween\s+(\d+(?:\.\d+)?)\s+and\s+(\d+(?:\.\d+)?)\b"
    r"|\b(\d+(?:\.\d+)?)\s*(?:to|–|—)\s*(\d+(?:\.\d+)?)\b", re.I)


_UNVERIFIABLE_CAP = 10  # per draft — reviewer B S5: visibility must not flood


def _unverifiable_emit(seen: dict[float, int], val: float) -> bool:
    """Dedupe + cap unverifiable_number notes per draft: the first _CAP
    distinct values are emitted, the rest collapses into a counter."""
    if val in seen or len(seen) >= _UNVERIFIABLE_CAP:
        seen[val] = seen.get(val, 0) + 1
        return False
    seen[val] = 1
    return True


def _sentence_spans(text: str) -> list[tuple[int, int]]:
    """Sentence-ish spans with offsets; decimals (0.021) never split."""
    spans = []
    start = 0
    for m in re.finditer(r"(?<=[.!?])\s+(?=[A-Z\\$0-9\"'])|(?<=\n)\s*\n", text):
        spans.append((start, m.start()))
        start = m.end()
    spans.append((start, len(text)))
    return [(a, b) for a, b in spans if text[a:b].strip()]


def _alias_hit(alias: str, sent: str) -> bool:
    """Aliases match with letter boundaries (reviewer A F-B / B S4): 'gloss'
    must not bind the 'loss' alias. A trailing English plural-s is allowed
    (reviewer B R4): 'losses' binds 'loss'."""
    stem = re.escape(alias)
    return re.search(rf"(?<![a-z0-9]){stem}(?:e?s)?(?![a-z0-9])", sent) is not None


def _bound_metrics(sentence: str, metrics: dict[str, Any]) -> list[str]:
    """Bind a sentence to metric keys: every content token of the field name
    (word-boundary) or a declared alias must appear in the sentence."""
    sent = sentence.lower()
    bound = []
    for key, m in metrics.items():
        field = str(m.get("field", "")).lower()
        if not field:
            continue
        if any(_alias_hit(a, sent) for a in _FIELD_ALIASES.get(field, ())):
            bound.append(key)
            continue
        content = [t for t in re.split(r"[^a-z0-9]+", field)
                   if len(t) >= 3 and t not in _FIELD_DIM_TOKENS]
        if content and all(re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])",
                                     sent) for t in content):
            bound.append(key)
    return bound


def _metric_anchor(sentence: str, metrics: dict[str, Any], key: str) -> int | None:
    """Position of the nearest binding mention of this metric in the sentence —
    the anchor for number↔metric assignment (reviewer B S1)."""
    sent = sentence.lower()
    field = str(metrics[key].get("field", "")).lower()
    positions = []
    for alias in _FIELD_ALIASES.get(field, ()):
        stem = re.escape(alias)
        positions += [m.start() for m in re.finditer(
            rf"(?<![a-z0-9]){stem}(?:e?s)?(?![a-z0-9])", sent)]
    content = [t for t in re.split(r"[^a-z0-9]+", field)
               if len(t) >= 3 and t not in _FIELD_DIM_TOKENS]
    if content:
        token_hits = []
        for t in content:
            hits = [m.start() for m in re.finditer(
                rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", sent)]
            if not hits:
                token_hits = []
                break
            token_hits.append(min(hits))
        positions += token_hits
    return min(positions) if positions else None


def _num_scale_match(a: float, b: float) -> bool:
    """Scale-aware equality for group anchors: 90 matches 0.90 via the
    percent convention; otherwise exact-ish. There is deliberately NO ×100
    direction — reviewer A F-A: 0.009×100≈0.9 would make every small rate an
    'anchor' of a 0.90 design point."""
    tol = max(1e-9, 1e-6 * abs(b))
    return abs(a - b) <= tol or abs(a / 100.0 - b) <= tol


def _refine_to_groups(bound: list[str], metrics: dict[str, Any],
                      sent_vals: list[float]) -> list[str]:
    """If the sentence anchors a design point (mentions a group value),
    restrict the comparison to exactly those metric groups."""
    refined = []
    for k in bound:
        for gv in (metrics[k].get("group") or {}).values():
            try:
                gvf = float(gv)
            except (TypeError, ValueError):
                continue
            if any(_num_scale_match(sv, gvf) for sv in sent_vals):
                refined.append(k)
                break
    return refined or bound


def _group_values(bound: list[str], metrics: dict[str, Any]) -> list[float]:
    vals = []
    for k in bound:
        for gv in (metrics[k].get("group") or {}).values():
            try:
                vals.append(float(gv))
            except (TypeError, ValueError):
                continue
    return vals


def run_integrity_audit(ctx: NodeContext) -> NodeOutcome:
    """P05: cross-check numbers asserted in drafts against derived metrics.

    Two deterministic checks:
    1. significance_without_test — 'p < x' / 'significant' claims with no
       computed statistical test artifact (MAJOR).
    2. number_mismatch — CONTEXTUALLY bound only (GAP-003): a draft number is
       flagged only when the sentence names the metric (field tokens/alias)
       and the value is off beyond tolerance. Layout zones, counts, design-
       point anchors and spread/threshold language never enter the check;
       unbindable result numbers become MINOR unverifiable_number notes.
       Significance contexts (p < …) are excluded from the number scan.
    """
    root = ctx.workspace.target_root
    metrics_path = ctx.workspace.reports_dir / "paper_metrics.json"
    findings: list[dict[str, Any]] = []
    drafts = sorted(root.glob("draft/*.md")) + sorted(root.glob("draft/*.tex"))

    sig_pat = re.compile(r"(p\s*[<≤=]\s*0?\.\d+|statistically significant|significant\b)",
                         re.I)

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
        raw = d.read_text(encoding="utf-8", errors="replace")
        # Layout zones (grid environments, markdown tables, column specs,
        # typographic dimensions) are not scientific content — mask them ONCE,
        # up front, so significance spans and number spans share one coordinate
        # system (the masked text keeps prose intact).
        text = _GRID_ENV.sub(" ", raw)
        text = _MD_TABLE_ROW.sub(" ", text)
        text = _LAYOUT_DIM.sub(" ", text)
        # significance detection (prose-level, p-value-aware); adjacent hits
        # within 40 chars collapse into one finding ('significant (p < 0.05)'
        # is one expression — reviewer A F-F)
        raw_spans = sorted(m.span() for m in sig_pat.finditer(text))
        sig_spans = []
        for sp in raw_spans:
            if sig_spans and sp[0] <= sig_spans[-1][1] + 40:
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
        # --- number audit: context-bound only (GAP-003) ---------------------
        # 'vs.'/'e.g.'/… must never split a sentence (reviewer A F-C): mask the
        # period with a same-length placeholder before sentence splitting
        text = re.sub(r"\b(?:vs|e\.g|i\.e|cf|Fig|fig|approx)\.", lambda m: m.group(0)[:-1] + "\x00", text)
        unverifiable_seen: dict[float, int] = {}
        unverifiable_suppressed = 0
        for a, b in _sentence_spans(text):
            sent = text[a:b]
            sent_nums: list[tuple[int, float, bool, str]] = []  # (pos, val, pct, raw)
            for m in _DEC_PAT.finditer(sent):
                sent_nums.append((a + m.start(), float(m.group(0)), False, m.group(0)))
            for m in _PCT_PAT.finditer(sent):
                sent_nums.append((a + m.start(), float(m.group(0).rstrip("%").strip()),
                                  True, m.group(0)))
            for m in _RATIO_PAT.finditer(sent):
                sent_nums.append((a + m.start(), float(m.group(1)), False, m.group(1)))
            if not sent_nums:
                continue
            count_spans = [m.span() for m in _COUNT_PAT.finditer(sent)]
            bound = _bound_metrics(sent, metrics) if true_values else []
            anchors = {k: _metric_anchor(sent, metrics, k) for k in bound}
            comparative_hits = list(_COMPARATIVE.finditer(sent))
            semantic_skip = bool(_SEMANTIC_SKIP.search(sent))
            refined = _refine_to_groups(bound, metrics, [v for _, v, _, _ in sent_nums])
            range_match = _RANGE_PAT.search(sent)
            # a range claim ('between lo and hi', 'lo to hi') is checked ONCE
            # per sentence against the bound group's observed min/max
            range_consumed = False
            if range_match and bound and not semantic_skip:
                lo_s = range_match.group(1) or range_match.group(3)
                hi_s = range_match.group(2) or range_match.group(4)
                means = [true_values[k] for k in refined]
                lo_ok = abs(float(lo_s) - min(means)) <= 0.05 * abs(min(means)) + 1e-12
                hi_ok = abs(float(hi_s) - max(means)) <= 0.05 * abs(max(means)) + 1e-12
                if not (lo_ok and hi_ok):
                    findings.append({
                        "severity": "MAJOR", "kind": "number_mismatch",
                        "draft": str(d.relative_to(root)),
                        "span": [a + range_match.start(), a + range_match.end()],
                        "value": [float(lo_s), float(hi_s)],
                        "bound_metrics": refined,
                        "expected": {"min": min(means), "max": max(means)},
                        "note": "draft range contradicts the contextually bound "
                                "metric group's observed min/max"})
                range_consumed = True
            for pos, val, is_pct, raw_num in sent_nums:
                rel = pos - a
                if any(sp[0] - 12 <= pos <= sp[1] + 2 for sp in sig_spans):
                    continue  # part of a p-value expression, not a result number
                if any(cs[0] <= rel < cs[1] for cs in count_spans):
                    continue  # counts are not metric means (9/9, n=18, 3 seeds)
                if range_consumed and range_match.start() <= rel <= range_match.end():
                    continue  # endpoint of the range claim handled above
                # S3: the comparative guard applies only when the keyword
                # actually modifies THIS number (±20 chars) — otherwise the
                # claim reads as a level claim and is checked as one
                comparative_here = any(
                    min(abs(m.start() - rel), abs(m.end() - rel)) <= 20
                    for m in comparative_hits)
                bound_n = bound
                if comparative_here:
                    bound_n = [k for k in bound
                               if _DIFF_FIELD.search(str(metrics[k].get("field", "")))]
                # S1: nearest-anchor assignment — a number compares against the
                # metric(s) named CLOSEST to it, never against every metric the
                # sentence happens to mention. R1: an exceptive marker directly
                # BEFORE an anchor ('unlike the loss') disqualifies that anchor;
                # a negation directly BEFORE the number ('is not 5.0') makes the
                # whole assertion negative — no equality check applies.
                # a negation reaching verb-distance before the number is not
                # skipped but EVALUATED below against the bound metric (X2) —
                # after the same nearest-anchor assignment any claim gets
                neg_m = _NEGATION_VERB.search(sent, max(0, rel - 30), rel)
                if bound_n:
                    def _clean_anchor(anchor: int) -> bool:
                        window = sent[max(0, anchor - _EXCEPTIVE_ANCHOR_WINDOW):anchor]
                        return _EXCEPTIVE.search(window) is None

                    dists = {k: abs(anchors[k] - rel) for k in bound_n
                             if anchors[k] is not None and _clean_anchor(anchors[k])}
                    if dists:
                        nearest = min(dists.values())
                        bound_n = sorted(k for k, dd in dists.items()
                                         if dd <= nearest + 1)
                if not bound_n:
                    if _RESULT_CUE.search(sent):
                        if _unverifiable_emit(unverifiable_seen, val):
                            findings.append({
                                "severity": "MINOR", "kind": "unverifiable_number",
                                "draft": str(d.relative_to(root)), "span": [pos, pos],
                                "value": val,
                                "note": "result-like number without resolvable metric "
                                        "binding — not asserted wrong, flagged for "
                                        "visibility (no invented assignment)"})
                        else:
                            unverifiable_suppressed += 1
                    continue
                if semantic_skip:
                    continue  # 'within a window'/threshold language ≠ mean claim
                if neg_m:
                    # X2/X3: evaluate the negated claim itself — 'does not
                    # reach 5.0' with latency=5.0 is a FALSE negation (MAJOR),
                    # with latency=1.0 a true one (clean). Cap/floor polarity:
                    # 'never exceeds 5.0' claims metric ≤ 5.0.
                    region = sent[neg_m.start():rel]
                    decimals = len(raw_num.rstrip("%").split(".")[1]) if "." in raw_num else 0
                    round_unit = 0.5 * 10 ** (-decimals)
                    refined_n = _refine_to_groups(bound_n, metrics,
                                                  [v for _, v, _, _ in sent_nums])
                    violation = None
                    for k in refined_n:
                        tv = true_values[k]
                        tol = max(0.05 * abs(tv), round_unit)
                        if _CAP_WORDS.search(region):
                            if tv > val + tol:
                                violation = (k, tv, f"cap violated: derived {tv} > {val}")
                        elif _FLOOR_WORDS.search(region):
                            if tv < val - tol:
                                violation = (k, tv, f"floor violated: derived {tv} < {val}")
                        elif abs(tv - val) <= tol:
                            violation = (k, tv, f"draft negates a derived value: {tv}")
                        if violation:
                            break
                    if violation:
                        vk, vt, why = violation
                        findings.append({
                            "severity": "MAJOR", "kind": "number_mismatch",
                            "draft": str(d.relative_to(root)), "span": [pos, pos],
                            "value": val, "bound_metrics": [vk],
                            "expected": {vk: vt},
                            "note": f"negated draft claim contradicts the contextually "
                                    f"bound metric: {why}"})
                    continue  # negated claims are fully handled here
                # Y3: positive cap/floor idioms without a negation marker
                # ('stays below 5.0', 'is above 5.0') are polarity claims —
                # evaluated as such, never as equality (a true floor claim must
                # not false-flag)
                # polarity words must PRECEDE the number in the claim role
                # ('stays below 5.0') — a trailing 'under load' is a
                # prepositional phrase, not a polarity claim
                pol_region = sent[max(0, rel - 15):rel]
                if not comparative_here and (
                        _FLOOR_WORDS.search(pol_region) or _CAP_WORDS.search(pol_region)):
                    decimals = len(raw_num.rstrip("%").split(".")[1]) if "." in raw_num else 0
                    round_unit = 0.5 * 10 ** (-decimals)
                    refined_p = _refine_to_groups(bound_n, metrics,
                                                  [v for _, v, _, _ in sent_nums])
                    violation = None
                    for k in refined_p:
                        tv = true_values[k]
                        tol = max(0.05 * abs(tv), round_unit)
                        if _FLOOR_WORDS.search(pol_region) and tv > val + tol:
                            violation = (k, tv, f"floor violated: derived {tv} > {val}")
                        elif _CAP_WORDS.search(pol_region) and tv < val - tol:
                            violation = (k, tv, f"cap violated: derived {tv} < {val}")
                        if violation:
                            break
                    if violation:
                        vk, vt, why = violation
                        findings.append({
                            "severity": "MAJOR", "kind": "number_mismatch",
                            "draft": str(d.relative_to(root)), "span": [pos, pos],
                            "value": val, "bound_metrics": [vk],
                            "expected": {vk: vt},
                            "note": f"polarity claim contradicts the contextually "
                                    f"bound metric: {why}"})
                    continue  # polarity claims are fully handled here
                # S2: design-anchor exemption only when the sentence NAMES the
                # dimension ('at 90% load' — the word 'load' must be present).
                # R2: a universal quantifier near the dimension ('at EVERY
                # load') disables the exemption and binds all groups instead.
                anchor_ok = False
                universal = False
                sent_l = sent.lower()
                for k in bound_n:
                    for gk, gv in (metrics[k].get("group") or {}).items():
                        dim_re = (rf"(?<![a-z0-9]){re.escape(str(gk).lower())}s?"
                                  rf"(?![a-z0-9])")
                        dim_hits = list(re.finditer(dim_re, sent_l))
                        if not dim_hits:
                            continue
                        if any(_UNIVERSAL.search(
                                sent_l[max(0, m.start() - 25):m.end() + 10])
                                for m in dim_hits):
                            universal = True
                        try:
                            gvf = float(gv)
                        except (TypeError, ValueError):
                            continue
                        # X1: the anchor exemption binds only the number that IS
                        # the design point's ARGUMENT ('at 95% load', 'at load
                        # 0.90') — between number and dimension word only pure
                        # connectors may stand, never other content (a RESULT
                        # number equal to the design value is never exempted)
                        # X1/Y1: the anchor exemption binds only the number that
                        # IS the design point's argument — whitespace/=/% between
                        # number and dimension word, nothing else. Any connector
                        # WORD ('at', 'of') between them means the number is the
                        # predicate, not the argument: 'is 0.90 at load' asserts
                        # a result, 'at 0.90 load' names the design point
                        def _is_design_argument() -> bool:
                            num_end = rel + len(raw_num)
                            for m in dim_hits:
                                if num_end <= m.start():
                                    between = sent_l[num_end:m.start()]
                                elif m.end() <= rel:
                                    between = sent_l[m.end():rel]
                                else:
                                    continue  # overlap — not a clean role span
                                between = between.replace(str(gk).lower(), " ")
                                if re.fullmatch(r"[\s@:=(/%-]*", between):
                                    return True
                            return False

                        if (_num_scale_match(val, gvf) and not universal
                                and _is_design_argument()):
                            anchor_ok = True
                if anchor_ok:
                    continue  # named design-point anchor, not a result number
                # a universal claim spans ALL bound groups — no refinement
                refined = bound_n if universal else _refine_to_groups(
                    bound_n, metrics, [v for _, v, _, _ in sent_nums])
                # percent scaling scales the tolerance with the value: 4.9% has
                # rounding unit 0.05% = 0.0005 in fraction units, not 0.05
                decimals = len(raw_num.rstrip("%").split(".")[1]) if "." in raw_num else 0
                round_unit = 0.5 * 10 ** (-decimals)
                scaled = [(val / 100.0, round_unit / 100.0), (val, round_unit)] if is_pct \
                    else [(val, round_unit)]
                if universal:
                    # the sentence claims the value for EVERY design point —
                    # it must hold against every bound group (R2)
                    matched = all(
                        any(abs(c - true_values[k]) <= max(0.05 * abs(true_values[k]), ru)
                            for c, ru in scaled)
                        for k in refined)
                else:
                    matched = any(
                        abs(c - true_values[k]) <= max(0.05 * abs(true_values[k]), ru)
                        for c, ru in scaled for k in refined)
                if matched:
                    continue  # matches the contextually bound metric(s)
                findings.append({
                    "severity": "MAJOR", "kind": "number_mismatch",
                    "draft": str(d.relative_to(root)), "span": [pos, pos],
                    "value": val,
                    "bound_metrics": refined,
                    "expected": {k: true_values[k] for k in refined},
                    "percent_scaled": is_pct,
                    "note": f"draft number {val} contradicts the contextually bound "
                            f"metric(s) {refined} (expected "
                            f"{[round(true_values[k], 6) for k in refined]})",
                })
        if unverifiable_suppressed:
            # R5: suppressed notes collapse into ONE visible marker per draft —
            # never a silent overflow
            findings.append({
                "severity": "MINOR", "kind": "unverifiable_number",
                "draft": str(d.relative_to(root)), "value": None,
                "note": f"{unverifiable_suppressed} further unverifiable number(s) "
                        f"suppressed (dedupe/cap of {_UNVERIFIABLE_CAP} per draft)"})
    report = {"audited_at": utcnow(), "findings": findings,
              "drafts_checked": [str(d.relative_to(root)) for d in drafts]}
    write_json(ctx.workspace.reports_dir / "integrity_audit.json", report)
    # The audit PASSes when it executed completely; findings carry the red and
    # flow into reviews (P23–P26) and closure (U2/U5), which is where blocking
    # happens — after remediation (P27) had its chance.
    return NodeOutcome(Verdict.PASS, {"findings": len(findings),
                                      "kinds": sorted({f["kind"] for f in findings})})
