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

from paper_factory.core.config import (
    MarkingRegistry,
    PaperFactoryConfig,
    ProviderPolicyConfig,
    ProvidersConfig,
)
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


# ---------------------------------------------------------------------------
# POST-PILOT-01 INTEGRITY AUDIT (on top of the frozen pilot snapshot 96b1a9c)
# ---------------------------------------------------------------------------
import json

from paper_factory.dag.executor import run_status_overall
from paper_factory.paperpal.bridge import run_paperpal
from paper_factory.release.closure import run_global_closure


def _write_manuscript(ctx, sections: dict[str, str]) -> None:
    paper = ctx.workspace.paper_dir
    (paper / "sections").mkdir(parents=True, exist_ok=True)
    (paper / "main.tex").write_text("\\documentclass{article}\n\\begin{document}\nbody\n"
                                    "\\end{document}\n", encoding="utf-8")
    for name, text in sections.items():
        (paper / "sections" / name).write_text(text, encoding="utf-8")


def _write_numbers_audit(ctx, findings=None) -> None:
    (ctx.workspace.reports_dir / "numbers_units_audit.json").write_text(
        json.dumps({"audited_at": "t", "findings": findings or []}), encoding="utf-8")


def _closure_states(ctx):
    outcome = run_global_closure(ctx)
    report = json.loads((ctx.workspace.reports_dir / "global_closure.json").read_text())
    return outcome, {uid: r["state"] for uid, r in report["invariants"].items()}


# --- GAP-002 false-green: quantitative claim without metric provenance ------
# Invariant: a quantitative scientific claim without T0/T1 metric provenance
# must NEVER reach P35 PASS (FAIL or HUMAN_REQUIRED per existing semantics).
# P11–P14 stay DEGRADED (GAP-002); the block must come from closure (U2).

def test_gap002_quantitative_claim_without_metrics_fails_closure(tmp_path):
    ctx = _ctx(tmp_path)
    # integer-percent claim evades the P22 raw-decimal regex by design of that
    # regex; the closure-level provenance gate must catch it instead
    _write_manuscript(ctx, {"results.tex":
                            "Our method reduces latency by 42\\% over the baseline.\n"})
    _write_numbers_audit(ctx, findings=[])  # P22 ran and found no raw decimals
    # NOTE: no paper_metrics.json — no admissible T0/T1 metric provenance
    outcome, states = _closure_states(ctx)
    assert states["U2"] == "FAIL", states
    assert outcome.verdict in (Verdict.FAIL, Verdict.HUMAN_REQUIRED)
    assert outcome.verdict != Verdict.PASS


def test_gap002_fold_claim_without_metrics_fails_closure(tmp_path):
    ctx = _ctx(tmp_path)
    _write_manuscript(ctx, {"results.tex": "We observe a 2.5-fold improvement.\n"})
    _write_numbers_audit(ctx, findings=[])
    outcome, states = _closure_states(ctx)
    assert states["U2"] == "FAIL", states
    assert outcome.verdict != Verdict.PASS


def test_gap002_pfget_macro_without_metric_binding_fails_closure(tmp_path):
    ctx = _ctx(tmp_path)
    # manuscript asserts a number via provenance macro, but no metrics artifact
    # backs the macro (paper_metrics.json missing, numbers.tex absent)
    _write_manuscript(ctx, {"results.tex": "The mean is $\\pfget{foomean}$.\n"})
    _write_numbers_audit(ctx, findings=[])
    outcome, states = _closure_states(ctx)
    assert states["U2"] == "FAIL", states
    assert outcome.verdict != Verdict.PASS


def test_gap002_undefined_pfget_macro_fails_even_with_metrics(tmp_path):
    ctx = _ctx(tmp_path)
    _write_manuscript(ctx, {"results.tex": "The mean is $\\pfget{unknownkeymean}$.\n"})
    _write_numbers_audit(ctx, findings=[])
    # metrics exist but the used macro is not among the generated ones
    (ctx.workspace.reports_dir / "paper_metrics.json").write_text(json.dumps(
        {"computed_at": "t", "sources": {}, "metrics": {"realkey": {"mean": 1.0}}}),
        encoding="utf-8")
    gen = ctx.workspace.paper_dir / "generated"
    gen.mkdir(parents=True, exist_ok=True)
    (gen / "numbers.tex").write_text(
        "\\expandafter\\gdef\\csname pf@realkeymean\\endcsname{1.0}\n", encoding="utf-8")
    outcome, states = _closure_states(ctx)
    assert states["U2"] == "FAIL", states
    assert outcome.verdict != Verdict.PASS


def test_gap002_theoretical_manuscript_without_metrics_not_blocked(tmp_path):
    ctx = _ctx(tmp_path)
    _write_manuscript(ctx, {"results.tex":
                            "We discuss the qualitative implications of the framework.\n"})
    _write_numbers_audit(ctx, findings=[])
    _, states = _closure_states(ctx)
    assert states["U2"] == "PASS", states


def test_gap002_metrics_backed_macros_pass(tmp_path):
    ctx = _ctx(tmp_path)
    _write_manuscript(ctx, {"results.tex": "The mean is $\\pfget{realkeymean}$ "
                                           "(n=$\\pfget{realkeyn}$).\n"})
    _write_numbers_audit(ctx, findings=[])
    (ctx.workspace.reports_dir / "paper_metrics.json").write_text(json.dumps(
        {"computed_at": "t", "sources": {}, "metrics": {"realkey": {"mean": 1.0, "n": 3}}}),
        encoding="utf-8")
    gen = ctx.workspace.paper_dir / "generated"
    gen.mkdir(parents=True, exist_ok=True)
    (gen / "numbers.tex").write_text(
        "\\expandafter\\gdef\\csname pf@realkeymean\\endcsname{1}\n"
        "\\expandafter\\gdef\\csname pf@realkeyn\\endcsname{3}\n", encoding="utf-8")
    _, states = _closure_states(ctx)
    assert states["U2"] == "PASS", states


# --- Paperpal provenance: operator check is not an external Paperpal PASS ----

_PILOT_INBOX_TEXT = (
    "PILOT-01 language/consistency check — performed MANUALLY by the operator (no Paperpal "
    "API exists on this machine; the bridge was used as designed). Scope: the PF-generated "
    "manuscript candidate in outbox/ (deterministic template prose). Spot-check result: "
    "language consistent, no external prose rewrite performed (therefore no "
    "external_prose_origin event). This is an honest manual bridge entry, not a Paperpal "
    "product.\n")


def test_paperpal_operator_check_is_not_external_pass(tmp_path):
    ctx = _ctx(tmp_path)
    _write_manuscript(ctx, {})
    ctx.workspace.paperpal_inbox  # ensure inbox dir exists
    (ctx.workspace.paperpal_inbox / "language_check_report.txt").write_text(
        _PILOT_INBOX_TEXT, encoding="utf-8")
    outcome = run_paperpal(ctx)
    state = json.loads((ctx.workspace.reports_dir / "paperpal_state.json").read_text())
    assert state["evidence_class"] == "operator_check"
    assert outcome.verdict == Verdict.DEGRADED  # honest: not a Paperpal product
    _, states = _closure_states(ctx)
    assert states["U9"] == "DEGRADED", states
    # no external edits happened, so there is nothing to reconcile — honest NOT_RUN
    assert states["U16"] == "NOT_RUN", states


def test_paperpal_declared_external_passes_and_reconciles(tmp_path):
    ctx = _ctx(tmp_path)
    _write_manuscript(ctx, {})
    (ctx.workspace.paperpal_inbox / "paperpal_report.txt").write_text(
        "source: paperpal\nlanguage check passed; no prose rewrite.\n", encoding="utf-8")
    outcome = run_paperpal(ctx)
    state = json.loads((ctx.workspace.reports_dir / "paperpal_state.json").read_text())
    assert state["evidence_class"] == "external_paperpal_declared"
    assert outcome.verdict == Verdict.PASS
    (ctx.workspace.reports_dir / "semantic_diff.json").write_text(json.dumps(
        {"checked_at": "t", "external_edits": True,
         "reconciliation": "claim strength/numbers re-validated"}), encoding="utf-8")
    _, states = _closure_states(ctx)
    assert states["U9"] == "PASS", states
    assert states["U16"] == "PASS", states


def test_paperpal_external_edits_without_semantic_diff_fail(tmp_path):
    ctx = _ctx(tmp_path)
    _write_manuscript(ctx, {})
    (ctx.workspace.paperpal_inbox / "paperpal_report.txt").write_text(
        "source: paperpal\nedited manuscript attached.\n", encoding="utf-8")
    run_paperpal(ctx)
    _, states = _closure_states(ctx)
    assert states["U9"] == "PASS", states
    assert states["U16"] == "FAIL", states  # external edits, no reconciliation artifact


def test_u9_legacy_undeclared_inbox_is_human_required(tmp_path):
    ctx = _ctx(tmp_path)
    _write_manuscript(ctx, {})
    # pre-audit state shape: inbox items recorded, no provenance classification
    (ctx.workspace.reports_dir / "paperpal_state.json").write_text(json.dumps(
        {"checked_at": "t", "outbox": "main.tex",
         "inbox_items": ["language_check_report.txt"]}), encoding="utf-8")
    _, states = _closure_states(ctx)
    assert states["U9"] == "HUMAN_REQUIRED", states


# --- overall-state aggregation: one canonical function for CLI + dashboard ---

from paper_factory.dag.nodes import NODE_MAP as _NODE_MAP


def _all_pass(**overrides: str) -> dict[str, str]:
    base = {nid: "PASS" for nid in _NODE_MAP}
    base.update(overrides)
    return base


def test_overall_fail_dominates():
    assert run_status_overall({"P35": Verdict.FAIL, "P00": Verdict.PASS}) == "FAILED"


def test_overall_human_required_beats_degraded_and_pass():
    s = _all_pass(P36="HUMAN_REQUIRED", P00="DEGRADED")
    assert run_status_overall(s) == "HUMAN_REQUIRED"


def test_overall_degraded_is_not_a_blind_pass():
    # 0 FAIL, 0 HUMAN_REQUIRED, 1 DEGRADED — must not surface as CLOSED/PASS
    assert run_status_overall(_all_pass(P00="DEGRADED")) == "DEGRADED"


def test_overall_all_pass_is_closed():
    assert run_status_overall(_all_pass()) == "CLOSED"


def test_overall_degraded_closure_is_not_closed():
    assert run_status_overall(_all_pass(P35="DEGRADED")) == "DEGRADED"


def test_overall_required_skip_is_incomplete():
    assert run_status_overall(_all_pass(P35="SKIPPED_DEPENDENCY")) == "INCOMPLETE"


def test_overall_missing_required_node_is_incomplete():
    # an absent node is unproven, never a silent skip (reviewer B-F4)
    s = _all_pass()
    del s["P35"]
    assert run_status_overall(s) == "INCOMPLETE"
    assert run_status_overall({"P00": "PASS"}) == "INCOMPLETE"


def test_overall_accepts_string_statuses_for_dashboard():
    # dashboard reads JSON (plain strings) — one canonical function, both inputs
    assert run_status_overall(_all_pass(P00="DEGRADED")) == "DEGRADED"
    assert run_status_overall(_all_pass()) == "CLOSED"
    assert run_status_overall({"P35": "FAIL"}) == "FAILED"
    assert run_status_overall({"P35": "HUMAN_REQUIRED"}) == "HUMAN_REQUIRED"


def test_overall_unknown_state_is_never_closed():
    assert run_status_overall(_all_pass(P00="SOMETHING_ELSE")) == "INCOMPLETE"
    assert run_status_overall({"XX9": "PASS", "P35": "PASS"}) == "INCOMPLETE"


# ---------------------------------------------------------------------------
# Dual-review round: regression tests for the verified reviewer findings
# ---------------------------------------------------------------------------
from paper_factory.statistics.numbers_audit import run_numbers_units_audit


def _stats(tmp_path, csv_text):
    results = tmp_path / "results"
    results.mkdir(parents=True, exist_ok=True)
    (results / "data.csv").write_text(csv_text, encoding="utf-8")
    ctx = _ctx(tmp_path)
    outcome = run_statistics(ctx)
    mp = ctx.workspace.reports_dir / "paper_metrics.json"
    data = json.loads(mp.read_text()) if mp.exists() else {}
    return outcome, data


# Reviewer A-F1: a single nan cell crashed P09 (DAG-wide FAIL cascade)
def test_ra_f1_nan_cell_is_missing_not_crash(tmp_path):
    outcome, data = _stats(tmp_path, "method,score\na,0.5\na,nan\nb,0.7\nb,0.9\n")
    assert outcome.verdict == Verdict.PASS, outcome.detail
    assert data["audit"]["missing_cells"] >= 1
    by_method = {m["group"].get("method"): m for m in data["metrics"].values()}
    assert by_method["a"]["n"] == 1 and by_method["b"]["n"] == 2


# Reviewer A-F2: binary outcomes (success rates) were misclassified as design
def test_ra_f2_binary_outcome_stays_outcome(tmp_path):
    rows = ["method,success"] + [f"m{i % 2},{i % 2}" for i in range(20)]
    outcome, data = _stats(tmp_path, "\n".join(rows) + "\n")
    assert outcome.verdict == Verdict.PASS, outcome.detail
    assert any(m["field"] == "success" for m in data["metrics"].values())
    assert data["audit"]["classification"]["success"]["class"] == "outcome"


# Reviewer A-F3: 13+ design levels flipped to junk outcome; audit overclaimed
def test_ra_f3_high_cardinality_design_not_pooled(tmp_path):
    rows = ["temperature,seed,score"]
    for t in range(13):
        for s in (1, 2, 3):
            rows.append(f"{t},{s},{0.5 + t * 0.01}")
    outcome, data = _stats(tmp_path, "\n".join(rows) + "\n")
    assert outcome.verdict == Verdict.PASS, outcome.detail
    assert data["audit"]["classification"]["temperature"]["class"] == "design"
    for m in data["metrics"].values():
        assert m["field"] == "score"
        assert m["n"] == 3 and m["group"].get("temperature") is not None
    assert "never pooled" not in json.dumps(data["audit"])


# Reviewer A-F4: replication axes by other names (seed_id, iteration) split groups
def test_ra_f4_seed_id_is_replication_not_group(tmp_path):
    rows = ["seed_id,load,fpr"]
    for seed in (1, 2, 3):
        for load in ("0.90", "0.95"):
            rows.append(f"{seed},{load},{0.01 + seed * 1e-4:.6f}")
    outcome, data = _stats(tmp_path, "\n".join(rows) + "\n")
    assert outcome.verdict == Verdict.PASS, outcome.detail
    for m in data["metrics"].values():
        assert set(m["group"]) == {"load"}, m
        assert m["n"] == 3 and m["std"] is not None


# Reviewer A-F5: numeric identifiers produced junk metrics; BOM defeats names
def test_ra_f5_numeric_ids_and_bom_seed_excluded(tmp_path):
    rows = ["﻿seed,run_id,score", "1,1001,0.5", "2,1002,0.7", "3,1003,0.9"]
    outcome, data = _stats(tmp_path, "\n".join(rows) + "\n")
    assert outcome.verdict == Verdict.PASS, outcome.detail
    fields = {m["field"] for m in data["metrics"].values()}
    assert fields == {"score"}, fields


# Reviewer A-F6: grouping by raw string split one condition into phantom groups
def test_ra_f6_numeric_groups_by_value_not_string(tmp_path):
    rows = ["load,score", "0.90,0.5", "0.9,0.6", "0.950,0.7", "0.95,0.8"]
    outcome, data = _stats(tmp_path, "\n".join(rows) + "\n")
    assert outcome.verdict == Verdict.PASS, outcome.detail
    groups = sorted(m["group"]["load"] for m in data["metrics"].values())
    assert len(groups) == 2, groups  # 0.9 and 0.95, each n=2


# Reviewer A-F7: macro key sanitization collided (gpt-4 vs gpt_4), metric lost
def test_ra_f7_macro_key_collision_preserves_both(tmp_path):
    rows = ["arm,score", "gpt-4,0.7", "gpt_4,0.9"]
    outcome, data = _stats(tmp_path, "\n".join(rows) + "\n")
    assert outcome.verdict == Verdict.PASS, outcome.detail
    assert len(data["metrics"]) == 2, list(data["metrics"])
    nt = (tmp_path / ".paper-factory" / "paper" / "generated" / "numbers.tex").read_text()
    import re as _re
    bases = _re.findall(r"\\csname pf@(.+?)\\endcsname", nt)
    assert len(bases) == len(set(bases)), "macro definition collision"


# Reviewer A-F8: n=1 metrics escaped the small_samples audit list
def test_ra_f8_singleton_metrics_flagged_small(tmp_path):
    rows = ["method,score", "a,0.5", "b,0.9"]
    outcome, data = _stats(tmp_path, "\n".join(rows) + "\n")
    assert outcome.verdict == Verdict.PASS, outcome.detail
    assert len(data["audit"]["small_samples"]) == 2


# Reviewer A-F9: sentinel "N/A" flipped the only outcome column to text
def test_ra_f9_sentinel_counts_as_missing_keeps_outcome(tmp_path):
    rows = ["method,score", "a,0.5", "a,0.7", "b,N/A", "b,0.9"]
    outcome, data = _stats(tmp_path, "\n".join(rows) + "\n")
    assert outcome.verdict == Verdict.PASS, outcome.detail
    assert any(m["field"] == "score" for m in data["metrics"].values())
    assert data["audit"]["missing_cells"] >= 1


# Reviewer B-F1: claims outside flat sections/*.tex were invisible to P22/U2
def test_rb_f1_quantitative_claim_in_root_tex_fails(tmp_path):
    ctx = _ctx(tmp_path)
    _write_manuscript(ctx, {"results.tex": "Clean prose.\n"})
    (ctx.workspace.paper_dir / "extra.tex").write_text(
        "We reduce latency by 42\\%.\n", encoding="utf-8")
    audit = run_numbers_units_audit(ctx)
    assert audit.detail["raw_numbers"] >= 1
    _, states = _closure_states(ctx)
    assert states["U2"] == "FAIL", states


def test_rb_f1_nested_sections_scanned(tmp_path):
    ctx = _ctx(tmp_path)
    _write_manuscript(ctx, {"results.tex": "Clean prose.\n"})
    nested = ctx.workspace.paper_dir / "sections" / "appendix"
    nested.mkdir(parents=True)
    (nested / "extra.tex").write_text("A 2.5-fold improvement.\n", encoding="utf-8")
    audit = run_numbers_units_audit(ctx)
    assert audit.detail["raw_numbers"] >= 1


# Reviewer B-F2: regex evasion forms (LaTeX spacing, unicode, APA dot, words)
def test_rb_f2_evasion_forms_are_detected():
    from paper_factory.statistics.quantitative import find_quantitative, normalize_tex
    evasions = ["42\\,\\%", "42~\\%", "42\\;\\%", "42 percent", "42 Prozent",
                "42％", "2.5‐fold", "2.5–fold", "twofold", "1.2e-3",
                "N = 1284", "p < .05", "0,42"]
    for e in evasions:
        assert find_quantitative(normalize_tex(e), claim_section=True), e


def test_rb_f2_non_quantitative_prose_stays_clean():
    from paper_factory.statistics.quantitative import find_quantitative, normalize_tex
    clean = ["We discuss the qualitative implications.",
             "Python 3.11 was used for all tooling.",
             "5-fold cross-validation is a design constant here."]
    for c in clean:
        assert not find_quantitative(normalize_tex(c), claim_section=False), c


# Reviewer B-F3: existence is not binding — unrelated metrics + raw claim failed
def test_rb_f3_raw_claim_with_unrelated_metrics_fails(tmp_path):
    ctx = _ctx(tmp_path)
    _write_manuscript(ctx, {"results.tex": "We reduce latency by 42\\%.\n"})
    (ctx.workspace.reports_dir / "paper_metrics.json").write_text(json.dumps(
        {"computed_at": "t", "sources": {}, "metrics": {"unrelated": {"mean": 0.11, "n": 3}}}),
        encoding="utf-8")
    audit = run_numbers_units_audit(ctx)
    assert audit.detail["raw_numbers"] >= 1
    _, states = _closure_states(ctx)
    assert states["U2"] == "FAIL", states


def test_rb_f3_macro_value_divergence_fails(tmp_path):
    ctx = _ctx(tmp_path)
    _write_manuscript(ctx, {"results.tex": "The mean is $\\pfget{realkeymean}$.\n"})
    (ctx.workspace.reports_dir / "paper_metrics.json").write_text(json.dumps(
        {"computed_at": "t", "sources": {}, "metrics": {"realkey": {"mean": 0.11, "n": 3}}}),
        encoding="utf-8")
    gen = ctx.workspace.paper_dir / "generated"
    gen.mkdir(parents=True, exist_ok=True)
    (gen / "numbers.tex").write_text(  # hand-written forgery: value is not the metric
        "\\expandafter\\gdef\\csname pf@realkeymean\\endcsname{99.9}\n", encoding="utf-8")
    audit = run_numbers_units_audit(ctx)
    assert audit.detail["raw_numbers"] == 0  # nothing raw; the forgery is in the binding
    _, states = _closure_states(ctx)
    assert states["U2"] == "FAIL", states


# ---------------------------------------------------------------------------
# Dual-review round 2: regression tests for reviewer re-review findings
# ---------------------------------------------------------------------------

def test_rb_g1_control_space_and_empty_group_evasion_fails(tmp_path):
    ctx = _ctx(tmp_path)
    _write_manuscript(ctx, {"results.tex": "We cut loss by 42\\ \\% and 42{}\\%.\n"})
    audit = run_numbers_units_audit(ctx)
    assert audit.detail["raw_numbers"] >= 1  # identical surfaces dedupe by value
    _, states = _closure_states(ctx)
    assert states["U2"] == "FAIL", states


def test_rb_g2_speedup_phrases_are_quantitative(tmp_path):
    from paper_factory.statistics.quantitative import find_quantitative, normalize_tex
    for phrase in ["a 2.5x speedup", "2.5 times faster", "a 2.5× improvement",
                   "3.1x", "1.7 times lower"]:
        assert find_quantitative(normalize_tex(phrase), claim_section=True), phrase
    # and they fail closure without metrics
    ctx = _ctx(tmp_path)
    _write_manuscript(ctx, {"results.tex": "We achieve a 2.5x speedup.\n"})
    run_numbers_units_audit(ctx)
    _, states = _closure_states(ctx)
    assert states["U2"] == "FAIL", states


def test_rb_g5_spaced_pfget_and_raw_csname_bind_fail_closed(tmp_path):
    for use in ("$\\pfget {fakeacc}$", "\\csname pf@fakeacc\\endcsname"):
        ctx = _ctx(tmp_path / "a" if use.startswith("$") else tmp_path / "b")
        _write_manuscript(ctx, {"results.tex": f"The value is {use}.\n"})
        run_numbers_units_audit(ctx)
        (ctx.workspace.reports_dir / "paper_metrics.json").write_text(json.dumps(
            {"computed_at": "t", "sources": {}, "metrics": {"realkey": {"mean": 0.11, "n": 3}}}),
            encoding="utf-8")
        gen = ctx.workspace.paper_dir / "generated"
        gen.mkdir(parents=True, exist_ok=True)
        (gen / "numbers.tex").write_text(
            "\\expandafter\\gdef\\csname pf@fakeacc\\endcsname{99.9}\n", encoding="utf-8")
        _, states = _closure_states(ctx)
        assert states["U2"] == "FAIL", (use, states)


def test_rb_g6_nested_build_dir_is_scanned(tmp_path):
    ctx = _ctx(tmp_path)
    _write_manuscript(ctx, {"results.tex": "Clean.\n"})
    nested = ctx.workspace.paper_dir / "sections" / "build"
    nested.mkdir(parents=True)
    (nested / "x.tex").write_text("We reduce latency by 42\\%.\n", encoding="utf-8")
    audit = run_numbers_units_audit(ctx)
    assert audit.detail["raw_numbers"] >= 1


def test_rb_g7_appendix_methods_tex_is_claim_bearing(tmp_path):
    ctx = _ctx(tmp_path)
    _write_manuscript(ctx, {"results.tex": "Clean.\n"})
    nested = ctx.workspace.paper_dir / "sections" / "appendix"
    nested.mkdir(parents=True)
    (nested / "methods.tex").write_text("A 2.5-fold improvement, N = 1284 runs.\n",
                                        encoding="utf-8")
    audit = run_numbers_units_audit(ctx)
    assert audit.detail["raw_numbers"] >= 1


def test_rb_g8_per_cent_forms_detected():
    from paper_factory.statistics.quantitative import find_quantitative, normalize_tex
    for phrase in ["42 per cent", "a 42-percent reduction", "0.5 points"]:
        assert find_quantitative(normalize_tex(phrase), claim_section=True), phrase


def test_ra_r2_nonfinite_cells_audited_as_missing(tmp_path):
    outcome, data = _stats(tmp_path, "method,score\na,0.5\na,inf\nb,0.7\nb,0.9\n")
    assert outcome.verdict == Verdict.PASS, outcome.detail
    assert data["audit"]["missing_cells"] >= 1
    assert any(e.get("column") == "score" for e in data["audit"]["exclusions"])


def test_ra_r3_text_sentinel_is_no_phantom_group(tmp_path):
    rows = ["method,load,score",
            "a,0.90,0.5", "a,0.95,0.55", "b,0.90,0.7", "b,0.95,0.75",
            "N/A,0.90,0.6", "N/A,0.95,0.65"]
    outcome, data = _stats(tmp_path, "\n".join(rows) + "\n")
    assert outcome.verdict == Verdict.PASS, outcome.detail
    assert data["audit"]["missing_group_keys"] >= 1
    assert not any("N/A" in str(m["group"].values()) for m in data["metrics"].values())


def test_ra_r4_audit_persisted_on_degraded(tmp_path):
    # only a replication axis: nothing derivable, but the classification audit
    # must survive the DEGRADED verdict (diagnosability)
    outcome, data = _stats(tmp_path, "seed,score\n1,0.5\n2,0.5\n")
    assert outcome.verdict == Verdict.DEGRADED
    assert data["audit"]["classification"]["seed"]["class"] == "excluded"


# ---------------------------------------------------------------------------
# Dual-review round 3: regression tests
# ---------------------------------------------------------------------------

def test_rb_h1_alias_macro_in_generated_fails(tmp_path):
    ctx = _ctx(tmp_path)
    _write_manuscript(ctx, {"results.tex": "The gain is \\x{}.\n"})
    run_numbers_units_audit(ctx)
    (ctx.workspace.reports_dir / "paper_metrics.json").write_text(json.dumps(
        {"computed_at": "t", "sources": {}, "metrics": {"realkey": {"mean": 0.11, "n": 3}}}),
        encoding="utf-8")
    gen = ctx.workspace.paper_dir / "generated"
    gen.mkdir(parents=True, exist_ok=True)
    (gen / "more.tex").write_text("\\newcommand{\\x}{99.9\\%}\n", encoding="utf-8")
    _, states = _closure_states(ctx)
    assert states["U2"] == "FAIL", states


def test_rb_h2_inline_comment_cannot_split_macro_call(tmp_path):
    ctx = _ctx(tmp_path)
    _write_manuscript(ctx, {"results.tex": "The value is $\\pfget % sneaky\n{fakeacc}$.\n"})
    run_numbers_units_audit(ctx)
    (ctx.workspace.reports_dir / "paper_metrics.json").write_text(json.dumps(
        {"computed_at": "t", "sources": {}, "metrics": {"realkey": {"mean": 0.11, "n": 3}}}),
        encoding="utf-8")
    gen = ctx.workspace.paper_dir / "generated"
    gen.mkdir(parents=True, exist_ok=True)
    (gen / "numbers.tex").write_text(
        "\\expandafter\\gdef\\csname pf@fakeacc\\endcsname{99.9}\n", encoding="utf-8")
    _, states = _closure_states(ctx)
    assert states["U2"] == "FAIL", states


def test_rb_h3_relax_percent_wordfold_variants_detected():
    from paper_factory.statistics.quantitative import find_quantitative, normalize_tex
    for phrase in ["42\\relax\\%", "42\\percent", "a three-fold increase",
                   "2.5 times as fast", "42\\/\\%"]:
        assert find_quantitative(normalize_tex(phrase), claim_section=True), phrase


def test_ra_fr0_compose_output_binds_in_closure(tmp_path):
    # the deterministic composer must produce macro references that U2 accepts
    # (dotted group values: load=0.90 → pf@…load0p90…)
    from paper_factory.manuscript.compose import _compose_section
    ctx = _ctx(tmp_path)
    results = tmp_path / "results"
    results.mkdir()
    rows = ["seed,load,fpr"]
    for seed in (42, 43, 44):
        for load in ("0.90", "0.95"):
            rows.append(f"{seed},{load},{0.01 + seed * 1e-4 + float(load):.6f}")
    (results / "data.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    outcome = run_statistics(ctx)
    assert outcome.verdict == Verdict.PASS, outcome.detail
    text = _compose_section("results", ctx)
    sections = ctx.workspace.paper_dir / "sections"
    sections.mkdir(parents=True, exist_ok=True)
    (sections / "results.tex").write_text(text, encoding="utf-8")
    run_numbers_units_audit(ctx)
    _, states = _closure_states(ctx)
    assert states["U2"] == "PASS", states


def test_ra_fr2_nonfinite_counted_exactly_once(tmp_path):
    outcome, data = _stats(tmp_path, "method,score\na,0.5\na,inf\nb,0.7\nb,0.9\n")
    assert outcome.verdict == Verdict.PASS, outcome.detail
    assert data["audit"]["missing_cells"] == 1, data["audit"]


def test_ra_fr3_real_missing_label_does_not_merge_with_sentinel(tmp_path):
    rows = ["method,score",
            "(missing),0.5", "(missing),0.6", "a,0.7", "a,0.8", "N/A,0.9"]
    outcome, data = _stats(tmp_path, "\n".join(rows) + "\n")
    assert outcome.verdict == Verdict.PASS, outcome.detail
    groups = {m["group"].get("method"): m["n"] for m in data["metrics"].values()}
    assert groups.get("(missing)") == 2  # real label keeps its own n


# ---------------------------------------------------------------------------
# Dual-review round 4: regression tests (generated/ allowlist, U3 binding,
# url-aware comment strip)
# ---------------------------------------------------------------------------

def _seed_metrics_and_manuscript(tmp_path):
    """Minimal valid provenance state: metrics + bound numbers.tex + manuscript."""
    ctx = _ctx(tmp_path)
    _write_manuscript(ctx, {"results.tex": "The mean is $\\pfget{realkeymean}$.\n"})
    run_numbers_units_audit(ctx)
    (ctx.workspace.reports_dir / "paper_metrics.json").write_text(json.dumps(
        {"computed_at": "t", "sources": {}, "metrics": {"realkey": {"mean": 0.11, "n": 3}}}),
        encoding="utf-8")
    gen = ctx.workspace.paper_dir / "generated"
    gen.mkdir(parents=True, exist_ok=True)
    (gen / "numbers.tex").write_text(
        "% generated by paper-factory statistics — do not hand-edit\n"
        "\\makeatletter\n"
        "\\newcommand{\\pfget}[1]{\\ifcsname pf@#1\\endcsname\\csname pf@#1\\endcsname"
        "\\else\\textbf{??}\\fi}\n"
        "\\makeatother\n"
        "\\expandafter\\gdef\\csname pf@realkeymean\\endcsname{0.11}\n"
        "\\expandafter\\gdef\\csname pf@realkeyn\\endcsname{3}\n", encoding="utf-8")
    return ctx


def test_rb_j0_canonical_generated_content_passes(tmp_path):
    ctx = _seed_metrics_and_manuscript(tmp_path)
    _, states = _closure_states(ctx)
    assert states["U2"] == "PASS", states


def test_rb_j1_let_alias_and_csname_def_fail(tmp_path):
    for extra in ("\\let\\myget\\pfget\n",
                  "\\csname newcommand\\endcsname{\\x}{99.9\\%}\n",
                  "\\expandafter\\gdef\\csname pf@fakeacc\\endcsname{99.9}\n"):
        ctx = _seed_metrics_and_manuscript(tmp_path / ("c" + str(abs(hash(extra)) % 1000)))
        numbers = ctx.workspace.paper_dir / "generated" / "numbers.tex"
        numbers.write_text(numbers.read_text() + extra, encoding="utf-8")
        _, states = _closure_states(ctx)
        assert states["U2"] == "FAIL", (extra, states)


def _write_empty_figures_manifest(ctx):
    (ctx.workspace.reports_dir / "figures_manifest.json").write_text(
        json.dumps({"generated_at": "t", "figures": []}), encoding="utf-8")


def test_rb_j2_table_value_edit_fails(tmp_path):
    ctx = _seed_metrics_and_manuscript(tmp_path)
    gen = ctx.workspace.paper_dir / "generated"
    table = gen / "tables.tex"
    table.write_text("% generated by paper-factory tables\n"
                     "\\begin{tabular}{lr}\\toprule metric & value \\\\\n"
                     "\\midrule acc & 0.11 \\\\\n\\bottomrule\\end{tabular}\n",
                     encoding="utf-8")
    import hashlib
    good = hashlib.sha256(table.read_bytes()).hexdigest()
    (ctx.workspace.reports_dir / "tables_manifest.json").write_text(json.dumps({
        "generated_at": "t", "tables": [],
        "input_data_hashes": {"reports/paper_metrics.json":
                              hashlib.sha256((ctx.workspace.reports_dir
                                              / "paper_metrics.json").read_bytes()).hexdigest()},
        "output": {"path": "paper/generated/tables.tex", "sha256": good, "bytes": 1}}),
        encoding="utf-8")
    _write_empty_figures_manifest(ctx)
    _, states = _closure_states(ctx)
    assert states["U3"] == "PASS", states  # baseline: intact table passes
    # post-generation edit of a table value must be caught
    table.write_text(table.read_text().replace("0.11", "99.9"), encoding="utf-8")
    _write_empty_figures_manifest(ctx)
    _, states = _closure_states(ctx)
    assert states["U3"] == "FAIL", states


def test_rb_j2_input_drift_fails(tmp_path):
    ctx = _seed_metrics_and_manuscript(tmp_path)
    (ctx.workspace.reports_dir / "tables_manifest.json").write_text(json.dumps({
        "generated_at": "t", "tables": [],
        "input_data_hashes": {"reports/paper_metrics.json": "0" * 64}}), encoding="utf-8")
    _write_empty_figures_manifest(ctx)
    _, states = _closure_states(ctx)
    assert states["U3"] == "FAIL", states


def test_rb_j3_url_percent_does_not_hide_claim(tmp_path):
    ctx = _ctx(tmp_path)
    _write_manuscript(ctx, {"results.tex":
                            "Using \\url{http://x.org/50%20off} we reduced latency by 42\\%.\n"})
    audit = run_numbers_units_audit(ctx)
    assert audit.detail["raw_numbers"] >= 1  # the 42\% after the URL stays visible
    _, states = _closure_states(ctx)
    assert states["U2"] == "FAIL", states


def test_rb_j4_def_in_generated_comment_is_no_violation(tmp_path):
    ctx = _seed_metrics_and_manuscript(tmp_path)
    numbers = ctx.workspace.paper_dir / "generated" / "numbers.tex"
    numbers.write_text(numbers.read_text() + "% note: \\def\\x{1} in a comment is inert\n",
                       encoding="utf-8")
    _, states = _closure_states(ctx)
    assert states["U2"] == "PASS", states


# ---------------------------------------------------------------------------
# Dual-review round 5: regression tests
# ---------------------------------------------------------------------------

def test_rb_k1_accessor_redefinition_fails(tmp_path):
    ctx = _seed_metrics_and_manuscript(tmp_path)
    numbers = ctx.workspace.paper_dir / "generated" / "numbers.tex"
    forged = numbers.read_text().replace(
        "\\newcommand{\\pfget}[1]{\\ifcsname pf@#1\\endcsname\\csname pf@#1\\endcsname"
        "\\else\\textbf{??}\\fi}",
        "\\newcommand{\\pfget}[1]{99.9\\%}")
    assert forged != numbers.read_text()  # the replacement actually happened
    numbers.write_text(forged, encoding="utf-8")
    _, states = _closure_states(ctx)
    assert states["U2"] == "FAIL", states


def test_rb_k2_csname_def_in_tables_tex_fails(tmp_path):
    ctx = _seed_metrics_and_manuscript(tmp_path)
    gen = ctx.workspace.paper_dir / "generated"
    (gen / "tables.tex").write_text(
        "% tables\n\\csname newcommand\\endcsname{\\x}{99.9\\%}\n", encoding="utf-8")
    _, states = _closure_states(ctx)
    assert states["U2"] == "FAIL", states


def test_rb_k3_href_percent_does_not_hide_claim(tmp_path):
    ctx = _ctx(tmp_path)
    _write_manuscript(ctx, {"results.tex":
                            "See \\href{http://x.org/50%20off}{the dataset}: latency fell 42\\%.\n"})
    audit = run_numbers_units_audit(ctx)
    assert audit.detail["raw_numbers"] >= 1
    _, states = _closure_states(ctx)
    assert states["U2"] == "FAIL", states


def test_rb_k4_verb_star_does_not_hide_claim():
    from paper_factory.statistics.quantitative import find_quantitative, normalize_tex
    text = "Code \\verb*|a%b| shows it; we reduced latency by 42\\%."
    assert any("42" in h for h in find_quantitative(normalize_tex(text), claim_section=True))


def test_rb_k5_output_without_pin_fails(tmp_path):
    ctx = _seed_metrics_and_manuscript(tmp_path)
    _write_empty_figures_manifest(ctx)
    (ctx.workspace.reports_dir / "tables_manifest.json").write_text(json.dumps({
        "generated_at": "t", "tables": [],
        "output": {"path": "paper/generated/tables.tex"}}), encoding="utf-8")  # no sha256
    _, states = _closure_states(ctx)
    assert states["U3"] == "FAIL", states


# ---------------------------------------------------------------------------
# Dual-review round 6: regression tests
# ---------------------------------------------------------------------------

def test_rb_l1_input_into_build_dir_fails(tmp_path):
    ctx = _seed_metrics_and_manuscript(tmp_path)
    build = ctx.workspace.paper_dir / "build"
    build.mkdir(parents=True)
    (build / "aliases.tex").write_text("\\newcommand{\\x}{99.9\\%}\n", encoding="utf-8")
    main = ctx.workspace.paper_dir / "main.tex"
    main.write_text(main.read_text() + "\\input{build/aliases}\n", encoding="utf-8")
    _, states = _closure_states(ctx)
    assert states["U2"] == "FAIL", states


def test_rb_l1_input_escape_paper_root_fails(tmp_path):
    ctx = _seed_metrics_and_manuscript(tmp_path)
    main = ctx.workspace.paper_dir / "main.tex"
    main.write_text(main.read_text() + "\\input{../../outside}\n", encoding="utf-8")
    _, states = _closure_states(ctx)
    assert states["U2"] == "FAIL", states


def test_rb_l1_input_into_generated_and_sections_allowed(tmp_path):
    ctx = _seed_metrics_and_manuscript(tmp_path)
    main = ctx.workspace.paper_dir / "main.tex"
    main.write_text(main.read_text() + "\\input{generated/tables}\n\\input{sections/results}\n",
                    encoding="utf-8")
    _, states = _closure_states(ctx)
    assert states["U2"] == "PASS", states


def test_rb_l2_path_pipe_form_does_not_hide_claim():
    from paper_factory.statistics.quantitative import find_quantitative, normalize_tex
    text = "See \\path|http://x.org/50%20off| for data: latency fell 42\\%."
    assert any("42" in h for h in find_quantitative(normalize_tex(text), claim_section=True))


def test_rb_l3_entry_with_path_but_no_pin_fails(tmp_path):
    ctx = _seed_metrics_and_manuscript(tmp_path)
    _write_empty_figures_manifest(ctx)
    artifact = ctx.workspace.paper_dir / "generated" / "tables.tex"
    artifact.write_text("% tables\n\\begin{tabular}{lr}\\end{tabular}\n", encoding="utf-8")
    (ctx.workspace.reports_dir / "tables_manifest.json").write_text(json.dumps({
        "generated_at": "t",
        "tables": [{"table_id": "t1", "path": "paper/generated/tables.tex"}]}),
        encoding="utf-8")
    _, states = _closure_states(ctx)
    assert states["U3"] == "FAIL", states


# ---------------------------------------------------------------------------
# Dual-review round 7: regression tests
# ---------------------------------------------------------------------------

def test_rb_m1_undeclared_figure_reference_fails(tmp_path):
    ctx = _seed_metrics_and_manuscript(tmp_path)
    figs = ctx.workspace.paper_dir / "figures"
    figs.mkdir(parents=True)
    (figs / "fake.pdf").write_bytes(b"%PDF-1.4 fabricated")
    results = ctx.workspace.paper_dir / "sections" / "results.tex"
    results.write_text(results.read_text() + "\n\\includegraphics{figures/fake}\n",
                       encoding="utf-8")
    _write_empty_figures_manifest(ctx)  # empty manifest: figure not declared
    (ctx.workspace.reports_dir / "tables_manifest.json").write_text(json.dumps({
        "generated_at": "t", "tables": []}), encoding="utf-8")
    _, states = _closure_states(ctx)
    assert states["U3"] == "FAIL", states


def test_rb_m1_declared_pinned_figure_passes(tmp_path):
    import hashlib
    ctx = _seed_metrics_and_manuscript(tmp_path)
    figs = ctx.workspace.paper_dir / "figures"
    figs.mkdir(parents=True)
    payload = b"%PDF-1.4 real figure"
    (figs / "real.pdf").write_bytes(payload)
    results = ctx.workspace.paper_dir / "sections" / "results.tex"
    results.write_text(results.read_text() + "\n\\includegraphics{figures/real}\n",
                       encoding="utf-8")
    (ctx.workspace.reports_dir / "figures_manifest.json").write_text(json.dumps({
        "generated_at": "t",
        "figures": [{"figure_id": "f1", "files": {"pdf": {
            "path": "paper/figures/real.pdf",
            "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)}}}]}),
        encoding="utf-8")
    (ctx.workspace.reports_dir / "tables_manifest.json").write_text(json.dumps({
        "generated_at": "t", "tables": []}), encoding="utf-8")
    _, states = _closure_states(ctx)
    assert states["U3"] == "PASS", states


def test_rb_m2_dot_slash_input_bypass_fails(tmp_path):
    ctx = _seed_metrics_and_manuscript(tmp_path)
    build = ctx.workspace.paper_dir / "build"
    build.mkdir(parents=True)
    (build / "x.tex").write_text("irrelevant\n", encoding="utf-8")
    main = ctx.workspace.paper_dir / "main.tex"
    main.write_text(main.read_text() + "\\input{./build/x}\n", encoding="utf-8")
    _, states = _closure_states(ctx)
    assert states["U2"] == "FAIL", states


def test_rb_m3_import_package_bypass_fails(tmp_path):
    ctx = _seed_metrics_and_manuscript(tmp_path)
    main = ctx.workspace.paper_dir / "main.tex"
    main.write_text(main.read_text() + "\\import{build/}{x}\n", encoding="utf-8")
    _, states = _closure_states(ctx)
    assert states["U2"] == "FAIL", states


def test_rb_m5_list_form_outputs_are_fail_closed(tmp_path):
    ctx = _seed_metrics_and_manuscript(tmp_path)
    _write_empty_figures_manifest(ctx)
    (ctx.workspace.reports_dir / "tables_manifest.json").write_text(json.dumps({
        "generated_at": "t", "tables": [],
        "output": ["paper/generated/tables.tex"]}), encoding="utf-8")  # list, no pins
    _, states = _closure_states(ctx)
    assert states["U3"] == "FAIL", states


# ---------------------------------------------------------------------------
# Dual-review round 8: regression tests
# ---------------------------------------------------------------------------

def test_rb_n1_includegraphics_star_form_bound(tmp_path):
    ctx = _seed_metrics_and_manuscript(tmp_path)
    figs = ctx.workspace.paper_dir / "figures"
    figs.mkdir(parents=True)
    (figs / "fake.pdf").write_bytes(b"%PDF-1.4 fabricated")
    results = ctx.workspace.paper_dir / "sections" / "results.tex"
    results.write_text(results.read_text() + "\n\\includegraphics*{figures/fake}\n",
                       encoding="utf-8")
    _write_empty_figures_manifest(ctx)
    (ctx.workspace.reports_dir / "tables_manifest.json").write_text(json.dumps({
        "generated_at": "t", "tables": []}), encoding="utf-8")
    _, states = _closure_states(ctx)
    assert states["U3"] == "FAIL", states


def test_rb_n2_pgfimage_bound(tmp_path):
    ctx = _seed_metrics_and_manuscript(tmp_path)
    figs = ctx.workspace.paper_dir / "figures"
    figs.mkdir(parents=True)
    (figs / "fake.pdf").write_bytes(b"%PDF-1.4 fabricated")
    results = ctx.workspace.paper_dir / "sections" / "results.tex"
    results.write_text(results.read_text() + "\n\\pgfimage{figures/fake}\n",
                       encoding="utf-8")
    _write_empty_figures_manifest(ctx)
    (ctx.workspace.reports_dir / "tables_manifest.json").write_text(json.dumps({
        "generated_at": "t", "tables": []}), encoding="utf-8")
    _, states = _closure_states(ctx)
    assert states["U3"] == "FAIL", states


# ---------------------------------------------------------------------------
# Dual-review round 9: regression tests
# ---------------------------------------------------------------------------

def test_rb_n1_space_star_form_bound(tmp_path):
    ctx = _seed_metrics_and_manuscript(tmp_path)
    figs = ctx.workspace.paper_dir / "figures"
    figs.mkdir(parents=True)
    (figs / "fake.pdf").write_bytes(b"%PDF-1.4 fabricated")
    results = ctx.workspace.paper_dir / "sections" / "results.tex"
    results.write_text(results.read_text() + "\n\\includegraphics *{figures/fake}\n",
                       encoding="utf-8")
    _write_empty_figures_manifest(ctx)
    (ctx.workspace.reports_dir / "tables_manifest.json").write_text(json.dumps({
        "generated_at": "t", "tables": []}), encoding="utf-8")
    _, states = _closure_states(ctx)
    assert states["U3"] == "FAIL", states


def test_rb_o1_sibling_graphics_commands_bound(tmp_path):
    for cmd in ("\\pgfuseimage", "\\includepdf", "\\includesvg"):
        ctx = _ctx(tmp_path / ("o1_" + cmd.strip("\\")))
        _write_manuscript(ctx, {"results.tex": f"Clean.\n{cmd}{{figures/fake}}\n"})
        run_numbers_units_audit(ctx)
        _write_empty_figures_manifest(ctx)
        (ctx.workspace.reports_dir / "tables_manifest.json").write_text(json.dumps({
            "generated_at": "t", "tables": []}), encoding="utf-8")
        _, states = _closure_states(ctx)
        assert states["U3"] == "FAIL", (cmd, states)


def test_rb_o2_tables_tex_without_manifest_pin_fails(tmp_path):
    ctx = _seed_metrics_and_manuscript(tmp_path)
    gen = ctx.workspace.paper_dir / "generated"
    (gen / "tables.tex").write_text("% tables\n\\begin{tabular}{lr}\\end{tabular}\n",
                                    encoding="utf-8")
    _write_empty_figures_manifest(ctx)
    # manifest declares nothing about the existing tables.tex
    (ctx.workspace.reports_dir / "tables_manifest.json").write_text(json.dumps({
        "generated_at": "t", "tables": []}), encoding="utf-8")
    _, states = _closure_states(ctx)
    assert states["U3"] == "FAIL", states


# ---------------------------------------------------------------------------
# Post-pilot audit: CLI process-exit contract — exit 0 <=> overall == "CLOSED"
# ---------------------------------------------------------------------------

import json as _json
import subprocess as _sp

import pytest as _pytest

from paper_factory.cli.main import main as _cli_main
from paper_factory.dag.executor import (
    EXIT_DEGRADED,
    EXIT_FAILED,
    EXIT_HUMAN_REQUIRED,
    EXIT_INCOMPLETE,
    EXIT_UNKNOWN,
    OVERALL_EXIT_CODES,
    exit_code_for_overall,
)
from paper_factory.dag.nodes import NODE_MAP

_EXIT_REPO = Path(__file__).resolve().parents[1]
_EXIT_CONFIG = Path(__file__).resolve().parent / "e2e-config"

_OVERALL_FIXTURES = {
    "EMPTY": {},
    "FAILED": {"P01": "PASS", "P35": "FAIL"},
    "HUMAN_REQUIRED": {"P01": "PASS", "P31": "HUMAN_REQUIRED"},
    "INCOMPLETE": {"P01": "PASS", "P02": "PASS"},
    "DEGRADED": {**{nid: "PASS" for nid in NODE_MAP}, "P33": "DEGRADED"},
    "CLOSED": {nid: "PASS" for nid in NODE_MAP},
}


def test_gap_exit_mapping_zero_iff_closed():
    for overall, code in OVERALL_EXIT_CODES.items():
        assert exit_code_for_overall(overall) == code
        assert (code == 0) == (overall == "CLOSED"), (overall, code)


def test_gap_exit_unknown_overall_fails_closed():
    assert exit_code_for_overall("SOME_FUTURE_STATE") == EXIT_UNKNOWN
    assert exit_code_for_overall("") == EXIT_UNKNOWN
    assert EXIT_UNKNOWN != 0


@_pytest.mark.parametrize("expected", sorted(_OVERALL_FIXTURES))
def test_gap_exit_aggregation_feeds_exit_code(expected):
    overall = run_status_overall(dict(_OVERALL_FIXTURES[expected]))
    assert overall == expected, (expected, overall)
    code = exit_code_for_overall(overall)
    assert (code == 0) == (overall == "CLOSED")


class _StubExecutor:
    """Command-level seam: the real CLI path (argparse, JSON, exit mapping)
    with only DAG execution replaced — no quota, no network."""

    statuses: dict = {}

    def __init__(self, ctx, handlers):
        pass

    def plan(self):
        return []

    def execute(self, resume=True):
        return dict(self.statuses)


@_pytest.mark.parametrize("overall", sorted(_OVERALL_FIXTURES))
def test_gap_exit_cli_complete_exit_codes(tmp_path, monkeypatch, capsys, overall):
    statuses = {k: Verdict(v) for k, v in _OVERALL_FIXTURES[overall].items()}
    monkeypatch.setattr("paper_factory.cli.main.Executor",
                        lambda ctx, handlers: _stub_with(statuses))
    rc = _cli_main(["--root", str(tmp_path), "--config-dir", str(_EXIT_CONFIG),
                    "complete"])
    out = _json.loads(capsys.readouterr().out)
    assert out["overall"] == overall
    assert out["exit_code"] == rc, "JSON must not claim a state the exit code denies"
    assert rc == OVERALL_EXIT_CODES[overall]
    assert (rc == 0) == (overall == "CLOSED")


def _stub_with(statuses):
    stub = _StubExecutor.__new__(_StubExecutor)
    stub.statuses = statuses
    return stub


def test_gap_exit_cli_run_and_resume_entrypoints_obey(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("paper_factory.cli.main.Executor",
                        lambda ctx, handlers: _stub_with(
                            {k: Verdict(v) for k, v in
                             _OVERALL_FIXTURES["DEGRADED"].items()}))
    rc_run = _cli_main(["--root", str(tmp_path), "--config-dir", str(_EXIT_CONFIG),
                        "run"])
    assert rc_run == EXIT_DEGRADED
    out = _json.loads(capsys.readouterr().out)
    assert out["exit_code"] == rc_run and out["overall"] == "DEGRADED"

    monkeypatch.setattr("paper_factory.cli.main.Executor",
                        lambda ctx, handlers: _stub_with(
                            {k: Verdict(v) for k, v in
                             _OVERALL_FIXTURES["HUMAN_REQUIRED"].items()}))
    rc_resume = _cli_main(["--root", str(tmp_path), "--config-dir", str(_EXIT_CONFIG),
                           "resume", "--run-id", "whatever"])
    assert rc_resume == EXIT_HUMAN_REQUIRED
    out = _json.loads(capsys.readouterr().out)
    assert out["exit_code"] == rc_resume and out["overall"] == "HUMAN_REQUIRED"


def test_gap_exit_cli_closed_real_subprocess(tmp_path):
    """True process boundary, zero quota: a workspace whose nodes are all
    PASS-seeded must let `complete --resume` reach CLOSED and exit 0 — proving
    exit 0 is reachable AND that it requires the canonical CLOSED state."""
    rid = "exit-contract-closed"
    ws = Workspace(tmp_path)
    ws.create_run(rid)
    for nid in NODE_MAP:
        ws.set_node_status(rid, nid, "PASS", {})
    proc = _sp.run(
        [str(_EXIT_REPO / ".venv/bin/paper-factory"),
         "--root", str(tmp_path), "--config-dir", str(_EXIT_CONFIG),
         "complete", "--resume", "--offline", "--run-id", rid],
        capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr[-500:]
    out = _json.loads(proc.stdout)
    assert out["overall"] == "CLOSED"
    assert out["exit_code"] == 0


def test_gap_exit_cli_degraded_real_subprocess(tmp_path):
    """Same boundary from the other side: all PASS except P35 (re-run by
    resume; closure on an artifact-empty workspace honestly DEGRADES) must
    exit non-zero and must not print CLOSED."""
    rid = "exit-contract-degraded"
    ws = Workspace(tmp_path)
    ws.create_run(rid)
    for nid in NODE_MAP:
        if nid != "P35":
            ws.set_node_status(rid, nid, "PASS", {})
    proc = _sp.run(
        [str(_EXIT_REPO / ".venv/bin/paper-factory"),
         "--root", str(tmp_path), "--config-dir", str(_EXIT_CONFIG),
         "complete", "--resume", "--offline", "--run-id", rid],
        capture_output=True, text=True, timeout=120)
    out = _json.loads(proc.stdout)
    assert proc.returncode == EXIT_DEGRADED, (proc.returncode, out["overall"])
    assert out["overall"] == "DEGRADED"
    assert out["exit_code"] == proc.returncode


def test_gap_exit_cli_failed_real_subprocess(tmp_path):
    """Deterministic FAILED at the process boundary: an undisposed MAJOR
    review finding makes U5 FAIL (same mechanism as e2e test_09), so P35 FAILs
    and the CLI must exit EXIT_FAILED, never 0."""
    from paper_factory.reviews.framework import Finding, ReviewReport, save_review
    rid = "exit-contract-failed"
    ws = Workspace(tmp_path)
    ws.create_run(rid)
    for nid in NODE_MAP:
        if nid != "P35":
            ws.set_node_status(rid, nid, "PASS", {})
    save_review(ws.reviews_dir, ReviewReport(
        review_id="ZZ-planted-exit", reviewer="test",
        findings=[Finding(finding_id="ZZ-1", reviewer="test", severity="MAJOR",
                          category="methods", statement="planted undisposed major")]))
    proc = _sp.run(
        [str(_EXIT_REPO / ".venv/bin/paper-factory"),
         "--root", str(tmp_path), "--config-dir", str(_EXIT_CONFIG),
         "complete", "--resume", "--offline", "--run-id", rid],
        capture_output=True, text=True, timeout=120)
    out = _json.loads(proc.stdout)
    assert proc.returncode == EXIT_FAILED, (proc.returncode, out["overall"])
    assert out["overall"] == "FAILED"
    assert out["exit_code"] == proc.returncode


def test_gap_exit_release_stub_fails_closed(tmp_path):
    """Reviewer B (post-pilot audit): the release stub must not exit 0 while
    reporting NOT_RUN — exit 0 is reserved for real success."""
    proc = _sp.run(
        [str(_EXIT_REPO / ".venv/bin/paper-factory"),
         "--root", str(tmp_path), "--config-dir", str(_EXIT_CONFIG), "release"],
        capture_output=True, text=True, timeout=60)
    out = _json.loads(proc.stdout)
    assert out["release"] == "NOT_RUN"
    assert proc.returncode == EXIT_INCOMPLETE


# ---------------------------------------------------------------------------
# GAP-004: remediation integrity — a finding is RESOLVED only when its own
# concrete post-condition is verified. Global sweeps and vacuous
# post-conditions ("no unsupported claims remain") are gone.
# ---------------------------------------------------------------------------

from paper_factory.claims.builder import run_claim_graph
from paper_factory.claims.graph import Claim, ClaimGraph, load_claims, save_claims
from paper_factory.core.results import ClaimStatus, Disposition, Severity
from paper_factory.release.closure import _u5
from paper_factory.reviews.framework import (
    Finding,
    ReviewReport,
    load_reviews,
    save_review,
)
from paper_factory.reviews.remediation import run_remediation
from paper_factory.reviews.runners import run_methods_review


def _g4_finding(fid: str, kind=None, category="methods", claim_refs=None,
                details=None, statement="finding", severity="MAJOR") -> Finding:
    return Finding(finding_id=fid, reviewer="test", severity=Severity(severity),
                   category=category, statement=statement, kind=kind,
                   claim_refs=claim_refs or [], details=details or {})


def _g4_review(ctx, findings, review_id="T27-review"):
    save_review(ctx.workspace.reviews_dir,
                ReviewReport(review_id=review_id, reviewer="test", findings=findings))


def _g4_claims(ctx, *claims: Claim):
    ctx.workspace.claims_dir.mkdir(parents=True, exist_ok=True)
    save_claims(ctx.workspace.claims_dir / "claims.yaml", ClaimGraph(claims=list(claims)))


def test_gap004_pilot_vacuous_resolution_repro(tmp_path):
    """Exact pilot shape: P23-methods-F01 (number_mismatch) was RESOLVED via
    'no unsupported claims remain' with retired=[] — a post-condition the
    action never influenced. That must be impossible now."""
    ctx = _ctx(tmp_path)
    _g4_claims(ctx, Claim(claim_id="C001", statement="supported claim",
                          status=ClaimStatus.EVIDENCE_FOUND, evidence=["E1"]))
    _g4_review(ctx, [_g4_finding(
        "P23-methods-F01", kind="number_mismatch",
        statement="draft number 0.17 within metric range but off every derived metric",
        details={"draft": "draft/manuscript.tex", "value": 0.17,
                 "closest_metric": "M1", "true_value": 0.2085757256})])
    outcome = run_remediation(ctx)
    reviews, _ = load_reviews(ctx.workspace.reviews_dir)
    f = reviews[0].findings[0]
    assert f.disposition != Disposition.RESOLVED, "vacuous resolution is back"
    assert f.disposition == Disposition.DEFERRED
    assert "0.17" in (f.disposition_reason or ""), "reason must bind the concrete number"
    # the claim graph was NOT touched as a side effect
    graph = load_claims(ctx.workspace.claims_dir / "claims.yaml")
    assert graph.claims[0].status == ClaimStatus.EVIDENCE_FOUND
    assert outcome.verdict == Verdict.DEGRADED


def test_gap004_noop_action_never_resolves(tmp_path):
    """Old behavior retired [] claims and still RESOLVED — a no-op action can
    never satisfy a finding-specific post-condition."""
    ctx = _ctx(tmp_path)
    _g4_claims(ctx)
    _g4_review(ctx, [_g4_finding(f"F{i:02d}", kind="number_mismatch",
                                 details={"draft": "draft/m.tex", "value": 1.23 + i,
                                          "true_value": 2.0, "closest_metric": "M"})
                     for i in range(3)])
    outcome = run_remediation(ctx)
    reviews, _ = load_reviews(ctx.workspace.reviews_dir)
    assert all(f.disposition == Disposition.DEFERRED for f in reviews[0].findings)
    log = _json.loads((ctx.workspace.reports_dir / "remediation_log.json").read_text())
    assert len(log["entries"]) == 3
    for e in log["entries"]:
        assert e["post_condition"], "every entry needs a finding-specific post-condition"
        assert e["verification"] is not None


def test_gap004_bound_unsupported_claim_resolves(tmp_path):
    """Positive control: a finding bound to claim C001 IS auto-remediable —
    retire exactly C001, verify per-claim before/after."""
    ctx = _ctx(tmp_path)
    _g4_claims(ctx,
               Claim(claim_id="C001", statement="40% faster lookup",
                     status=ClaimStatus.UNSUPPORTED),
               Claim(claim_id="C002", statement="other claim",
                     status=ClaimStatus.UNSUPPORTED))
    _g4_review(ctx, [_g4_finding("F01", kind="unsupported_claim", claim_refs=["C001"],
                                 category="statistics",
                                 details={"excerpt": "40% faster lookup"})])
    outcome = run_remediation(ctx)
    reviews, _ = load_reviews(ctx.workspace.reviews_dir)
    f = reviews[0].findings[0]
    assert f.disposition == Disposition.RESOLVED
    assert f.resolved_by
    graph = load_claims(ctx.workspace.claims_dir / "claims.yaml")
    by_id = graph.by_id()
    assert by_id["C001"].status == ClaimStatus.RETIRED
    assert by_id["C002"].status == ClaimStatus.UNSUPPORTED, "no global sweep"
    log = _json.loads((ctx.workspace.reports_dir / "remediation_log.json").read_text())
    v = log["entries"][0]["verification"]
    assert v["claims"]["C001"]["before"] == "UNSUPPORTED"
    assert v["claims"]["C001"]["after"] == "RETIRED"
    assert outcome.verdict == Verdict.PASS


def test_gap004_unbound_claim_finding_defers(tmp_path):
    ctx = _ctx(tmp_path)
    _g4_claims(ctx, Claim(claim_id="C001", statement="x", status=ClaimStatus.UNSUPPORTED))
    _g4_review(ctx, [_g4_finding("F01", kind="unsupported_claim", category="statistics")])
    outcome = run_remediation(ctx)
    reviews, _ = load_reviews(ctx.workspace.reviews_dir)
    assert reviews[0].findings[0].disposition == Disposition.DEFERRED
    graph = load_claims(ctx.workspace.claims_dir / "claims.yaml")
    assert graph.claims[0].status == ClaimStatus.UNSUPPORTED, "unbound must not retire"
    assert outcome.verdict == Verdict.DEGRADED


def test_gap004_claim_ref_missing_from_graph_is_invalid(tmp_path):
    ctx = _ctx(tmp_path)
    _g4_claims(ctx, Claim(claim_id="C001", statement="x", status=ClaimStatus.UNSUPPORTED))
    _g4_review(ctx, [_g4_finding("F01", kind="unsupported_claim", claim_refs=["C999"],
                                 category="methods")])
    outcome = run_remediation(ctx)
    reviews, _ = load_reviews(ctx.workspace.reviews_dir)
    assert reviews[0].findings[0].disposition == Disposition.INVALID_REMEDIATION_ARTIFACT
    assert outcome.verdict == Verdict.FAIL, "broken evidence chain must fail closed"


def test_gap004_verified_claim_not_retired(tmp_path):
    """A finding claiming 'unsupported' against a VERIFIED claim is a real
    conflict — never silently retire verified evidence."""
    ctx = _ctx(tmp_path)
    _g4_claims(ctx, Claim(claim_id="C001", statement="x", status=ClaimStatus.VERIFIED,
                          evidence=["E1"]))
    _g4_review(ctx, [_g4_finding("F01", kind="unsupported_claim", claim_refs=["C001"],
                                 category="statistics", details={"excerpt": "x"})])
    outcome = run_remediation(ctx)
    reviews, _ = load_reviews(ctx.workspace.reviews_dir)
    assert reviews[0].findings[0].disposition == Disposition.UNRESOLVED
    graph = load_claims(ctx.workspace.claims_dir / "claims.yaml")
    assert graph.claims[0].status == ClaimStatus.VERIFIED
    assert outcome.verdict == Verdict.DEGRADED


def test_gap004_false_citation_bound_resolution(tmp_path, monkeypatch):
    """Citation remediation verifies the SPECIFIC key is gone — not just
    'some rebuild happened'."""
    ctx = _ctx(tmp_path)
    _g4_claims(ctx)
    ctx.workspace.paper_dir.mkdir(parents=True, exist_ok=True)
    bib = ctx.workspace.paper_dir / "references.bib"
    bib.write_text("@article{x, doi={10.9999/fake.bloom.2024}}\n", encoding="utf-8")
    _g4_review(ctx, [_g4_finding("F01", kind="false_citation", category="citation",
                                 details={"doi": "10.9999/fake.bloom.2024"})])

    from paper_factory.literature import verify

    def _rebuild_drops_key(ctx_):
        bib.write_text("@article{ok, doi={10.1/real}}\n", encoding="utf-8")

    monkeypatch.setattr(verify, "build_references", _rebuild_drops_key)
    monkeypatch.setattr(verify, "_audit_entries", lambda ctx_, entries: ([], [], None))
    outcome = run_remediation(ctx)
    reviews, _ = load_reviews(ctx.workspace.reviews_dir)
    assert reviews[0].findings[0].disposition == Disposition.RESOLVED
    assert outcome.verdict == Verdict.PASS


def test_gap004_false_citation_surviving_key_is_unresolved(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path)
    _g4_claims(ctx)
    ctx.workspace.paper_dir.mkdir(parents=True, exist_ok=True)
    bib = ctx.workspace.paper_dir / "references.bib"
    bib.write_text("@article{x, doi={10.9999/fake.bloom.2024}}\n", encoding="utf-8")
    _g4_review(ctx, [_g4_finding("F01", kind="false_citation", category="citation",
                                 details={"doi": "10.9999/fake.bloom.2024"})])

    from paper_factory.literature import verify
    monkeypatch.setattr(verify, "build_references", lambda ctx_: None)  # no-op rebuild
    monkeypatch.setattr(verify, "_audit_entries", lambda ctx_, entries: ([], [], None))
    outcome = run_remediation(ctx)
    reviews, _ = load_reviews(ctx.workspace.reviews_dir)
    assert reviews[0].findings[0].disposition == Disposition.UNRESOLVED
    assert outcome.verdict == Verdict.DEGRADED


def test_gap004_u5_closed_set_semantics(tmp_path):
    cases = [(None, True), (Disposition.DEFERRED, True),
             (Disposition.UNRESOLVED, True),
             (Disposition.INVALID_REMEDIATION_ARTIFACT, True),
             (Disposition.RESOLVED, False),
             (Disposition.AUTHOR_DECISION, False),
             (Disposition.ACCEPTED_LIMITATION, False)]
    for i, (disp, blocks) in enumerate(cases):
        ctx = _ctx(tmp_path / f"case{i}")
        f = _g4_finding(f"F-{disp}", severity="MAJOR")
        f.disposition = disp
        if disp in (Disposition.RESOLVED, Disposition.AUTHOR_DECISION,
                    Disposition.ACCEPTED_LIMITATION):
            f.resolved_by = "human"
            f.disposition_reason = "documented decision"
        _g4_review(ctx, [f], review_id=f"R-{i}")
        state, _ = _u5(ctx)
        assert (state == "FAIL") == blocks, (disp, state)


def test_gap004_closing_disposition_needs_provenance(tmp_path):
    """A-G3: AUTHOR_DECISION without resolved_by/reason is an assertion, not a
    closure — it must block like an undisposed finding."""
    for i, (by, reason, blocks) in enumerate([
            (None, None, True), ("human", None, True), (None, "why", True),
            ("human", "documented decision", False)]):
        ctx = _ctx(tmp_path / f"prov{i}")
        f = _g4_finding(f"F{i}", severity="CRITICAL")
        f.disposition = Disposition.AUTHOR_DECISION
        f.resolved_by = by
        f.disposition_reason = reason
        _g4_review(ctx, [f], review_id=f"RP-{i}")
        state, _ = _u5(ctx)
        assert (state == "FAIL") == blocks, (by, reason, state)


def test_gap004_builder_emits_bound_unsupported_findings(tmp_path):
    """The unsupported-claim enforcement path moves from an unbound global
    sweep to a finding bound to the claim id."""
    draft = tmp_path / "draft"
    draft.mkdir()
    (draft / "paper.md").write_text(
        "Our index achieves 40% faster lookup than the baseline.\n", encoding="utf-8")
    ctx = _ctx(tmp_path)
    run_claim_graph(ctx)
    audit = _json.loads((ctx.workspace.reports_dir / "claims_audit.json").read_text())
    bound = [f for f in audit["findings"]
             if f["kind"] == "unsupported_claim" and f.get("claim_id")]
    assert bound, "builder must emit claim-bound findings for unsupported claims"
    run_methods_review(ctx)
    reviews, _ = load_reviews(ctx.workspace.reviews_dir)
    folded = [f for r in reviews for f in r.findings if f.kind == "unsupported_claim"]
    assert folded and folded[0].claim_refs == [bound[0]["claim_id"]]


def test_gap004_folding_preserves_structure(tmp_path):
    """The review fold must not strip kind/details — that data loss was the
    first break in the finding->action->post-condition chain."""
    ctx = _ctx(tmp_path)
    ctx.workspace.reports_dir.mkdir(parents=True, exist_ok=True)
    (ctx.workspace.reports_dir / "integrity_audit.json").write_text(_json.dumps({
        "findings": [{"severity": "MAJOR", "kind": "number_mismatch",
                      "draft": "draft/m.tex", "value": 0.17,
                      "closest_metric": "M1", "true_value": 0.2086,
                      "note": "draft number within metric range"}],
    }), encoding="utf-8")
    run_methods_review(ctx)
    reviews, _ = load_reviews(ctx.workspace.reviews_dir)
    f = [f_ for r in reviews for f_ in r.findings][0]
    assert f.kind == "number_mismatch"
    assert f.details["value"] == 0.17
    assert f.details["true_value"] == 0.2086
    assert "0.17" in f.statement, "statement must identify the concrete number"


def test_gap004_legacy_finding_without_kind_defers_safely(tmp_path):
    """Old-shape findings (no kind/details, e.g. historical pilot artifacts)
    get an honest DEFERRED — never the old vacuous RESOLVED."""
    ctx = _ctx(tmp_path)
    _g4_claims(ctx)
    _g4_review(ctx, [_g4_finding("P23-methods-F01", category="methods",
                                 statement="draft number within metric range but off "
                                           "every derived metric")])
    outcome = run_remediation(ctx)
    reviews, _ = load_reviews(ctx.workspace.reviews_dir)
    assert reviews[0].findings[0].disposition == Disposition.DEFERRED
    assert outcome.verdict == Verdict.DEGRADED


# ---------------------------------------------------------------------------
# GAP-004 review round 1: reviewer A (G1-G8) + reviewer B (B1-B3) findings
# ---------------------------------------------------------------------------

def test_gap004_b1_claim_retired_but_still_printed_defers(tmp_path):
    """Reviewer B-B1 (MAJOR): retiring the claim in the graph while the
    manuscript still prints it must NOT resolve the finding."""
    ctx = _ctx(tmp_path)
    claim_text = "Our method outperforms all baselines by 42%."
    _g4_claims(ctx, Claim(claim_id="C001", statement=claim_text,
                          status=ClaimStatus.UNSUPPORTED))
    paper = ctx.workspace.paper_dir / "sections"
    paper.mkdir(parents=True, exist_ok=True)
    (ctx.workspace.paper_dir / "main.tex").write_text(
        "\\documentclass{article}\n", encoding="utf-8")
    (paper / "results.tex").write_text(claim_text + "\n", encoding="utf-8")
    _g4_review(ctx, [_g4_finding("F01", kind="unsupported_claim", claim_refs=["C001"],
                                 category="statistics",
                                 details={"excerpt": claim_text})])
    outcome = run_remediation(ctx)
    reviews, _ = load_reviews(ctx.workspace.reviews_dir)
    f = reviews[0].findings[0]
    assert f.disposition == Disposition.DEFERRED, f.disposition
    assert "still printed" in (f.disposition_reason or "")
    # the graph retirement is honest bookkeeping and stays — but blocked
    graph = load_claims(ctx.workspace.claims_dir / "claims.yaml")
    assert graph.by_id()["C001"].status == ClaimStatus.RETIRED
    state, _ = _u5(ctx)
    assert state == "FAIL"
    assert outcome.verdict == Verdict.DEGRADED


def test_gap004_b1_claim_gone_from_manuscript_resolves(tmp_path):
    ctx = _ctx(tmp_path)
    claim_text = "Our method outperforms all baselines by 42%."
    _g4_claims(ctx, Claim(claim_id="C001", statement=claim_text,
                          status=ClaimStatus.UNSUPPORTED))
    paper = ctx.workspace.paper_dir / "sections"
    paper.mkdir(parents=True, exist_ok=True)
    (ctx.workspace.paper_dir / "main.tex").write_text(
        "\\documentclass{article}\n", encoding="utf-8")
    (paper / "results.tex").write_text("Clean prose without the claim.\n",
                                       encoding="utf-8")
    _g4_review(ctx, [_g4_finding("F01", kind="unsupported_claim", claim_refs=["C001"],
                                 category="statistics",
                                 details={"excerpt": claim_text})])
    outcome = run_remediation(ctx)
    reviews, _ = load_reviews(ctx.workspace.reviews_dir)
    assert reviews[0].findings[0].disposition == Disposition.RESOLVED
    # B2: the verification reads the persisted artifact
    graph = load_claims(ctx.workspace.claims_dir / "claims.yaml")
    assert graph.by_id()["C001"].status == ClaimStatus.RETIRED
    assert outcome.verdict == Verdict.PASS


def test_gap004_g1_duplicate_claim_ids_fail_closed(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.workspace.claims_dir.mkdir(parents=True, exist_ok=True)
    (ctx.workspace.claims_dir / "claims.yaml").write_text(
        "claims:\n"
        "- {claim_id: C001, statement: a, status: VERIFIED, evidence: [E1]}\n"
        "- {claim_id: C001, statement: b, status: UNSUPPORTED}\n", encoding="utf-8")
    with _pytest.raises(ValueError, match="duplicate claim_id"):
        load_claims(ctx.workspace.claims_dir / "claims.yaml")
    state, note = _u5(ctx)  # no reviews → NOT_RUN; sanity that _u5 still works
    assert state == "NOT_RUN"


def test_gap004_g4_citation_substring_no_wedge(tmp_path, monkeypatch):
    """Reviewer A-G4: removing doi 10.9999/fake must not wedge on the
    substring-similar 10.9999/fake.longer entry that legitimately stays."""
    ctx = _ctx(tmp_path)
    ctx.workspace.paper_dir.mkdir(parents=True, exist_ok=True)
    bib = ctx.workspace.paper_dir / "references.bib"
    bib.write_text("@article{a, doi={10.9999/fake}}\n@article{b, doi={10.9999/fake.longer}}\n",
                   encoding="utf-8")
    _g4_review(ctx, [_g4_finding("F01", kind="false_citation", category="citation",
                                 details={"doi": "10.9999/fake"})])

    from paper_factory.literature import verify

    def _rebuild(ctx_):
        bib.write_text("@article{b, doi={10.9999/fake.longer}}\n", encoding="utf-8")

    monkeypatch.setattr(verify, "build_references", _rebuild)
    monkeypatch.setattr(verify, "_audit_entries", lambda ctx_, entries: ([], [], None))
    outcome = run_remediation(ctx)
    reviews, _ = load_reviews(ctx.workspace.reviews_dir)
    assert reviews[0].findings[0].disposition == Disposition.RESOLVED
    assert outcome.verdict == Verdict.PASS


def test_gap004_g5_stale_citation_finding_not_applicable(tmp_path):
    """A-G5: a finding about a citation that was never present is stale —
    NOT_APPLICABLE with provenance, never a fabricated 'removed' success."""
    ctx = _ctx(tmp_path)
    ctx.workspace.paper_dir.mkdir(parents=True, exist_ok=True)
    (ctx.workspace.paper_dir / "references.bib").write_text(
        "@article{ok, doi={10.1/real}}\n", encoding="utf-8")
    _g4_review(ctx, [_g4_finding("F01", kind="false_citation", category="citation",
                                 details={"doi": "10.0000/never-present"})])
    outcome = run_remediation(ctx)
    reviews, _ = load_reviews(ctx.workspace.reviews_dir)
    f = reviews[0].findings[0]
    assert f.disposition == Disposition.NOT_APPLICABLE
    assert f.resolved_by and "not present" in (f.disposition_reason or "")
    assert outcome.verdict == Verdict.PASS


def test_gap004_g6_excerpt_mismatch_is_invalid(tmp_path):
    """A-G6: a finding whose excerpt does not match the bound claim is a
    broken binding, not something to retire."""
    ctx = _ctx(tmp_path)
    _g4_claims(ctx, Claim(claim_id="C001", statement="completely different claim.",
                          status=ClaimStatus.UNSUPPORTED))
    _g4_review(ctx, [_g4_finding("F01", kind="unsupported_claim", claim_refs=["C001"],
                                 category="statistics",
                                 details={"excerpt": "40 percent faster lookup"})])
    outcome = run_remediation(ctx)
    reviews, _ = load_reviews(ctx.workspace.reviews_dir)
    assert reviews[0].findings[0].disposition == Disposition.INVALID_REMEDIATION_ARTIFACT
    graph = load_claims(ctx.workspace.claims_dir / "claims.yaml")
    assert graph.by_id()["C001"].status == ClaimStatus.UNSUPPORTED
    assert outcome.verdict == Verdict.FAIL


def test_gap004_g7_log_is_a_ledger_not_overwritten(tmp_path):
    ctx = _ctx(tmp_path)
    _g4_claims(ctx, Claim(claim_id="C001", statement="x", status=ClaimStatus.UNSUPPORTED))
    _g4_review(ctx, [_g4_finding("F01", kind="unsupported_claim", claim_refs=["C001"],
                                 category="statistics", details={"excerpt": "x"})])
    run_remediation(ctx)
    log1 = _json.loads((ctx.workspace.reports_dir / "remediation_log.json").read_text())
    assert len(log1["entries"]) == 1
    # second pass: finding already RESOLVED → no new entries → log untouched
    run_remediation(ctx)
    log2 = _json.loads((ctx.workspace.reports_dir / "remediation_log.json").read_text())
    assert len(log2["entries"]) == 1, "resume must not erase the ledger"
    # a second finding later appends instead of replacing
    _g4_review(ctx, [_g4_finding("F02", kind="number_mismatch",
                                 details={"draft": "d.tex", "value": 1.0,
                                          "true_value": 2.0, "closest_metric": "M"})],
               review_id="T27-review2")
    run_remediation(ctx)
    log3 = _json.loads((ctx.workspace.reports_dir / "remediation_log.json").read_text())
    assert len(log3["entries"]) == 2


def test_gap004_g8_missing_severity_defaults_closed(tmp_path):
    """A-G8: an audit finding without severity folds as MAJOR (visible at the
    U5 threshold), never as an invisible MINOR."""
    ctx = _ctx(tmp_path)
    ctx.workspace.reports_dir.mkdir(parents=True, exist_ok=True)
    (ctx.workspace.reports_dir / "integrity_audit.json").write_text(_json.dumps({
        "findings": [{"kind": "number_mismatch", "draft": "d.tex", "value": 1.0,
                      "true_value": 2.0, "closest_metric": "M"}],
    }), encoding="utf-8")
    run_methods_review(ctx)
    reviews, _ = load_reviews(ctx.workspace.reviews_dir)
    f = [f_ for r in reviews for f_ in r.findings][0]
    assert f.severity == Severity.MAJOR
    assert f.details.get("severity_defaulted") is True


def test_gap004_b3_closure_stamps_release_pointer(tmp_path):
    """Reviewer B-B3: the release pointer must carry the closure outcome, not
    a bare export PASS, once P35 has run."""
    from paper_factory.release.closure import run_global_closure

    ctx = _ctx(tmp_path)
    ctx.workspace.reports_dir.mkdir(parents=True, exist_ok=True)
    (ctx.workspace.reports_dir / "current_release.json").write_text(_json.dumps({
        "paper_id": "p", "export_status": "PASS", "bundle": "release/p"}),
        encoding="utf-8")
    outcome = run_global_closure(ctx)  # everything missing → FAIL/NOT_RUN mix
    pointer = _json.loads(
        (ctx.workspace.reports_dir / "current_release.json").read_text())
    assert pointer["export_status"] == "PASS"
    assert pointer.get("closure_overall") == outcome.verdict.value
    assert pointer["closure_overall"] != "PASS"


def test_gap004_b3_u8_requires_export_status(tmp_path):
    """U8 reads export_status (renamed from the misleading 'status'); a pointer
    without it fails closed."""
    ctx = _ctx(tmp_path)
    ctx.workspace.reports_dir.mkdir(parents=True, exist_ok=True)
    (ctx.workspace.reports_dir / "current_release.json").write_text(_json.dumps({
        "paper_id": "p", "bundle": "release/p"}), encoding="utf-8")
    from paper_factory.release.closure import _u8
    state, note = _u8(ctx)
    assert state == "FAIL", (state, note)


# ---------------------------------------------------------------------------
# GAP-004 review round 2 (reviewer B B1-rest + C1, reviewer A N1/N3/N4)
# ---------------------------------------------------------------------------

def _b1_case(tmp_path, claim_text: str, manuscript_text: str,
             generated: bool = False):
    ctx = _ctx(tmp_path)
    _g4_claims(ctx, Claim(claim_id="C001", statement=claim_text,
                          status=ClaimStatus.UNSUPPORTED))
    sub = "generated" if generated else "sections"
    d = ctx.workspace.paper_dir / sub
    d.mkdir(parents=True, exist_ok=True)
    (d / "results.tex").write_text(manuscript_text + "\n", encoding="utf-8")
    _g4_review(ctx, [_g4_finding("F01", kind="unsupported_claim", claim_refs=["C001"],
                                 category="statistics",
                                 details={"excerpt": claim_text})])
    outcome = run_remediation(ctx)
    reviews, _ = load_reviews(ctx.workspace.reviews_dir)
    return outcome, reviews[0].findings[0]


def test_gap004_b1r2_latex_escape_evasion_blocked(tmp_path):
    # statement from a markdown draft; manuscript prints the LaTeX-escaped form
    _, f = _b1_case(tmp_path, "The mass_inv estimator wins by 42%.",
                    "The mass\\_inv estimator wins by 42\\%.")
    assert f.disposition == Disposition.DEFERRED, f.disposition_reason


def test_gap004_b1r2_case_evasion_blocked(tmp_path):
    _, f = _b1_case(tmp_path, "the estimator outperforms every baseline by 42%.",
                    "THE ESTIMATOR OUTPERFORMS EVERY BASELINE BY 42\\%.")
    assert f.disposition == Disposition.DEFERRED


def test_gap004_b1r2_tilde_and_font_evasion_blocked(tmp_path):
    _, f = _b1_case(tmp_path, "The method cuts the cost by half in all runs.",
                    "The method cuts the cost by~half in \\textbf{all runs}.")
    assert f.disposition == Disposition.DEFERRED


def test_gap004_b1r2_generated_caption_counts_as_printed(tmp_path):
    # generated/captions.tex is protected prose; the exclusion is build/ only
    _, f = _b1_case(tmp_path, "The estimator wins by 42% in every configuration.",
                    "The estimator wins by 42\\% in every configuration.",
                    generated=True)
    assert f.disposition == Disposition.DEFERRED


def test_gap004_b1r2_long_claim_tail_print_caught(tmp_path):
    claim = ("The estimator outperforms every baseline by 42% " +
             "in each of the twelve configurations we measured " * 4 +
             "and the gap never closes.")
    assert len(claim) > 240
    tail = claim[100:]  # a substantial verbatim tail of the long claim
    _, f = _b1_case(tmp_path, claim, "Results. " + tail)
    assert f.disposition == Disposition.DEFERRED


def test_gap004_n1_claim_finding_without_excerpt_defers(tmp_path):
    """A-N1: excerpt-less claim findings can no longer retire blind."""
    ctx = _ctx(tmp_path)
    _g4_claims(ctx, Claim(claim_id="C001", statement="some claim",
                          status=ClaimStatus.UNSUPPORTED))
    _g4_review(ctx, [_g4_finding("F01", kind="unsupported_claim", claim_refs=["C001"],
                                 category="statistics")])
    outcome = run_remediation(ctx)
    reviews, _ = load_reviews(ctx.workspace.reviews_dir)
    assert reviews[0].findings[0].disposition == Disposition.DEFERRED
    graph = load_claims(ctx.workspace.claims_dir / "claims.yaml")
    assert graph.by_id()["C001"].status == ClaimStatus.UNSUPPORTED
    assert outcome.verdict == Verdict.DEGRADED


def test_gap004_n3_doi_case_insensitive(tmp_path, monkeypatch):
    """DOIs are case-insensitive: 10.9999/FAKE in the bib must match a finding
    for 10.9999/fake — not be waved through as stale."""
    ctx = _ctx(tmp_path)
    ctx.workspace.paper_dir.mkdir(parents=True, exist_ok=True)
    bib = ctx.workspace.paper_dir / "references.bib"
    bib.write_text("@article{x, doi={10.9999/FAKE}}\n", encoding="utf-8")
    _g4_review(ctx, [_g4_finding("F01", kind="false_citation", category="citation",
                                 details={"doi": "10.9999/fake"})])

    from paper_factory.literature import verify
    monkeypatch.setattr(verify, "build_references", lambda ctx_: None)  # no-op
    monkeypatch.setattr(verify, "_audit_entries", lambda ctx_, entries: ([], [], None))
    outcome = run_remediation(ctx)
    reviews, _ = load_reviews(ctx.workspace.reviews_dir)
    f = reviews[0].findings[0]
    assert f.disposition == Disposition.UNRESOLVED  # real finding, removal failed
    assert f.disposition != Disposition.NOT_APPLICABLE
    assert outcome.verdict == Verdict.DEGRADED


def test_gap004_n4_final_citation_audit_carries_offline_flag(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path)
    ctx.workspace.paper_dir.mkdir(parents=True, exist_ok=True)
    (ctx.workspace.paper_dir / "references.bib").write_text(
        "@article{x, doi={10.9999/fake}}\n", encoding="utf-8")
    _g4_review(ctx, [_g4_finding("F01", kind="false_citation", category="citation",
                                 details={"doi": "10.9999/fake"})])

    from paper_factory.literature import verify
    monkeypatch.setattr(verify, "build_references", lambda ctx_: None)
    monkeypatch.setattr(verify, "_audit_entries", lambda ctx_, entries: ([], [], None))
    run_remediation(ctx)
    audit = _json.loads(
        (ctx.workspace.reports_dir / "citation_audit_final.json").read_text())
    assert audit["offline"] is True  # ctx fixture runs offline
    assert audit["post_remediation"] is True


def test_gap004_c1_p34_pins_build_outputs(tmp_path, monkeypatch):
    """Reviewer B-C1 (MAJOR): after the export_status rename, P34 must still
    pin its build outputs into bundle_files — otherwise U8 always fails on
    unpinned build/ files and no clean pipeline can ever close."""
    from paper_factory.release import export as export_mod

    ctx = _ctx(tmp_path)
    pid = "testpaper"
    bundle = ctx.workspace.release_dir / pid
    paper = bundle / "paper"
    paper.mkdir(parents=True)
    (paper / "main.tex").write_text("\\documentclass{article}\\begin{document}x\\end{document}\n",
                                    encoding="utf-8")
    ctx.workspace.reports_dir.mkdir(parents=True, exist_ok=True)
    (ctx.workspace.reports_dir / "current_release.json").write_text(_json.dumps({
        "paper_id": pid, "export_status": "PASS", "bundle": f"release/{pid}",
        "bundle_files": {"paper/main.tex": "abc"}}), encoding="utf-8")
    # PDFlatex may be absent in CI — the pin logic is what we test, not TeX
    monkeypatch.setattr(export_mod.shutil, "which", lambda name: "/usr/bin/pdflatex")

    def _fake_run(cmd, **kw):
        build = bundle / "build"
        build.mkdir(exist_ok=True)
        (build / "main.pdf").write_bytes(b"%PDF-1.4 fake")
        (build / "main.aux").write_text("\\relax\n", encoding="utf-8")
        return export_mod.subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(export_mod.subprocess, "run", _fake_run)
    monkeypatch.setattr(export_mod, "_paper_id", lambda ctx_: pid)
    outcome = export_mod.run_clean_rebuild(ctx)
    assert outcome.verdict == Verdict.PASS, outcome.detail
    pointer = _json.loads(
        (ctx.workspace.reports_dir / "current_release.json").read_text())
    assert "build/main.pdf" in pointer["bundle_files"]
    assert "build/main.aux" in pointer["bundle_files"]
    assert pointer["bundle_files"]["paper/main.tex"] == "abc"  # export pins kept


def test_gap004_p1_nested_build_dir_is_manuscript_surface(tmp_path):
    """Reviewer B-P1: sections/build/x.tex is printable via \\input — the
    presence surface must match the U2 surface (top-level build/ only)."""
    ctx = _ctx(tmp_path)
    claim = "The estimator wins by 42% in every configuration."
    _g4_claims(ctx, Claim(claim_id="C001", statement=claim, status=ClaimStatus.UNSUPPORTED))
    d = ctx.workspace.paper_dir / "sections" / "build"
    d.mkdir(parents=True)
    (d / "x.tex").write_text(claim + "\n", encoding="utf-8")
    _g4_review(ctx, [_g4_finding("F01", kind="unsupported_claim", claim_refs=["C001"],
                                 category="statistics", details={"excerpt": claim})])
    run_remediation(ctx)
    reviews, _ = load_reviews(ctx.workspace.reviews_dir)
    assert reviews[0].findings[0].disposition == Disposition.DEFERRED


def test_gap004_p1_inpaper_symlink_followed(tmp_path):
    """B-P1 n2: an in-paper symlink is manuscript surface (U2 parity)."""
    ctx = _ctx(tmp_path)
    claim = "The estimator wins by 42% in every configuration."
    _g4_claims(ctx, Claim(claim_id="C001", statement=claim, status=ClaimStatus.UNSUPPORTED))
    paper = ctx.workspace.paper_dir
    (paper / "sections").mkdir(parents=True)
    target = paper / "build"
    target.mkdir()
    (target / "x.tex").write_text(claim + "\n", encoding="utf-8")
    (paper / "sections" / "link.tex").symlink_to("../build/x.tex")
    _g4_review(ctx, [_g4_finding("F01", kind="unsupported_claim", claim_refs=["C001"],
                                 category="statistics", details={"excerpt": claim})])
    run_remediation(ctx)
    reviews, _ = load_reviews(ctx.workspace.reviews_dir)
    assert reviews[0].findings[0].disposition == Disposition.DEFERRED


def test_gap004_p1_escaping_symlink_never_read(tmp_path):
    """An escaping symlink is never followed (guard parity with U2/freeze) —
    and must not crash the remediation."""
    ctx = _ctx(tmp_path)
    claim = "The estimator wins by 42% in every configuration."
    _g4_claims(ctx, Claim(claim_id="C001", statement=claim, status=ClaimStatus.UNSUPPORTED))
    paper = ctx.workspace.paper_dir
    (paper / "sections").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.tex").write_text(claim + "\n", encoding="utf-8")
    (paper / "sections" / "evil.tex").symlink_to(str(outside / "secret.tex"))
    _g4_review(ctx, [_g4_finding("F01", kind="unsupported_claim", claim_refs=["C001"],
                                 category="statistics", details={"excerpt": claim})])
    outcome = run_remediation(ctx)  # must not raise, must not read outside
    reviews, _ = load_reviews(ctx.workspace.reviews_dir)
    # content lives outside the manuscript: not our finding to block on here
    # (the escape itself is pinned by the freeze manifest / U6)
    assert reviews[0].findings[0].disposition == Disposition.RESOLVED
    assert outcome.verdict == Verdict.PASS


# ---------------------------------------------------------------------------
# GAP-005: claim <-> evidence sharpness — no LaTeX fragments as claims, no
# generic evidence_ledger placeholder as primary proof (U1 fail-closed)
# ---------------------------------------------------------------------------

from paper_factory.release.closure import _u1

_PILOT_LIKE_DRAFT = r"""Adam and decoupled weight decay separate gradient transformation from regularization semantics, achieving 12% lower drift.
\hypertarget{2-experimental-program}{%
\section{Experimental Program}}
Thus the historical MMAV configuration is lower-loss in all 9/9 matched cells, with a seed-robust 0.9 improvement.
43\linewidth}@{}}\n\toprule\noalign{}
Claim & Current status & Safe interpretation \\
"""


def _g5_claim(cid, status, evidence, ctype="empirical"):
    return Claim(claim_id=cid, statement="s", status=status, evidence=evidence,
                 type=ctype)


def test_gap005_latex_fragments_are_not_claims(tmp_path):
    """Pilot repro: \\hypertarget/\\section lines and table-row fragments were
    extracted as claims (C002/C004/C006/C007). Only real sentences survive."""
    draft = tmp_path / "draft"
    draft.mkdir()
    (draft / "paper.tex").write_text(_PILOT_LIKE_DRAFT, encoding="utf-8")
    ctx = _ctx(tmp_path)
    run_claim_graph(ctx)
    graph = load_claims(ctx.workspace.claims_dir / "claims.yaml")
    statements = [c.statement for c in graph.claims]
    assert len(graph.claims) == 2, statements  # the two real sentences only
    assert not any("hypertarget" in s or "\\" in s.split(" ")[0] or "&" in s
                   for s in statements), statements


def test_gap005_claim_records_source_path(tmp_path):
    draft = tmp_path / "draft"
    draft.mkdir()
    (draft / "paper.md").write_text(
        "Our method achieves 12% lower latency than baseline.\n", encoding="utf-8")
    ctx = _ctx(tmp_path)
    run_claim_graph(ctx)
    graph = load_claims(ctx.workspace.claims_dir / "claims.yaml")
    assert graph.claims and graph.claims[0].source
    assert "draft/paper.md" in graph.claims[0].source


def test_gap005_builder_binds_concrete_metric_ids(tmp_path):
    """EVIDENCE_FOUND must name the concrete metrics, not 'evidence_ledger'."""
    draft = tmp_path / "draft"
    draft.mkdir()
    (draft / "paper.md").write_text(
        "Our method achieves 12% lower latency than baseline.\n", encoding="utf-8")
    ctx = _ctx(tmp_path)
    ctx.workspace.reports_dir.mkdir(parents=True, exist_ok=True)
    (ctx.workspace.reports_dir / "paper_metrics.json").write_text(_json.dumps({
        "metrics": {"M1": {"field": "latency_ms", "mean": 42.0, "n": 3},
                    "M2": {"field": "accuracy", "mean": 0.9, "n": 3}},
        "sources": [], "audit": {}}), encoding="utf-8")
    run_claim_graph(ctx)
    graph = load_claims(ctx.workspace.claims_dir / "claims.yaml")
    assert len(graph.claims) == 1
    ev = graph.claims[0].evidence
    assert ev == ["M1"], ev  # the latency metric, not the accuracy one
    assert "evidence_ledger" not in ev


def test_gap005_placeholder_evidence_fails_u1(tmp_path):
    ctx = _ctx(tmp_path)
    _g4_claims(ctx, _g5_claim("C001", ClaimStatus.EVIDENCE_FOUND, ["evidence_ledger"]))
    state, note = _u1(ctx)
    assert state == "FAIL", note
    assert "placeholder" in note or "unresolvable" in note


def test_gap005_dangling_evidence_ref_fails_u1(tmp_path):
    ctx = _ctx(tmp_path)
    _g4_claims(ctx, _g5_claim("C001", ClaimStatus.VERIFIED, ["E999"]))
    state, note = _u1(ctx)
    assert state == "FAIL", note


def test_gap005_metric_key_and_ledger_id_resolve_u1(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.workspace.reports_dir.mkdir(parents=True, exist_ok=True)
    (ctx.workspace.reports_dir / "paper_metrics.json").write_text(_json.dumps({
        "metrics": {"M1": {"field": "latency_ms", "mean": 42.0}}}), encoding="utf-8")
    ctx.workspace.evidence_dir.mkdir(parents=True, exist_ok=True)
    (ctx.workspace.evidence_dir / "evidence_ledger.jsonl").write_text(
        _json.dumps({"evidence_id": "E001", "tier": "T0", "path": "results/x.csv"}) + "\n",
        encoding="utf-8")
    _g4_claims(ctx,
               _g5_claim("C001", ClaimStatus.EVIDENCE_FOUND, ["M1"]),
               _g5_claim("C002", ClaimStatus.VERIFIED, ["E001"]))
    state, note = _u1(ctx)
    assert state == "PASS", note


def test_gap005_file_path_evidence_resolves_u1(tmp_path):
    ctx = _ctx(tmp_path)
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "x.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    _g4_claims(ctx, _g5_claim("C001", ClaimStatus.EVIDENCE_FOUND, ["results/x.csv"]))
    state, note = _u1(ctx)
    assert state == "PASS", note


def test_gap005_evidence_found_without_any_evidence_fails(tmp_path):
    ctx = _ctx(tmp_path)
    _g4_claims(ctx, _g5_claim("C001", ClaimStatus.EVIDENCE_FOUND, []))
    state, note = _u1(ctx)
    assert state == "FAIL", note


# ---------------------------------------------------------------------------
# GAP-005 review round 1: E1 (evidence scope), E2 (extraction recall),
# F3 (type bypass), F4 (cue order), F5/E3 (ledger integrity)
# ---------------------------------------------------------------------------

def test_gap005_e1_absolute_path_evidence_fails(tmp_path):
    ctx = _ctx(tmp_path)
    _g4_claims(ctx, _g5_claim("C001", ClaimStatus.VERIFIED, ["/etc/hostname"]))
    state, note = _u1(ctx)
    assert state == "FAIL", note


def test_gap005_e1_pipeline_bookkeeping_is_not_evidence(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.workspace.reports_dir.mkdir(parents=True, exist_ok=True)
    (ctx.workspace.reports_dir / "paper_metrics.json").write_text(
        _json.dumps({"metrics": {}}), encoding="utf-8")
    _g4_claims(ctx, _g5_claim(
        "C001", ClaimStatus.VERIFIED, [".paper-factory/reports/paper_metrics.json"]))
    state, note = _u1(ctx)
    assert state == "FAIL", note


def test_gap005_e1_symlink_escape_evidence_fails(tmp_path):
    # target root is tmp_path/"proj"; the symlink points OUTSIDE of it
    proj = tmp_path / "proj"
    ctx = _ctx(proj)
    (proj / "results").mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("x\n", encoding="utf-8")
    link = proj / "results" / "out.csv"
    link.symlink_to(outside)
    _g4_claims(ctx, _g5_claim("C001", ClaimStatus.VERIFIED, ["results/out.csv"]))
    state, note = _u1(ctx)
    assert state == "FAIL", note


def test_gap005_e2_float_caption_claim_extracted(tmp_path):
    """Canonical float shape must not swallow the caption's claim."""
    draft = tmp_path / "draft"
    draft.mkdir()
    (draft / "paper.tex").write_text(
        "\\begin{table}\n\\begin{tabular}{lr}\na & 1\\\\\n\\end{tabular}\n"
        "\\caption{Our estimator achieves 12% lower latency than the baseline.}\n"
        "\\end{table}\n", encoding="utf-8")
    ctx = _ctx(tmp_path)
    run_claim_graph(ctx)
    graph = load_claims(ctx.workspace.claims_dir / "claims.yaml")
    assert len(graph.claims) == 1
    assert "lower latency" in graph.claims[0].statement


def test_gap005_e2_itemize_and_leading_macro_claims_extracted(tmp_path):
    draft = tmp_path / "draft"
    draft.mkdir()
    (draft / "paper.tex").write_text(
        "\\begin{itemize}\n\\item \\textbf{We observe 15% lower energy} under load.\n"
        "\\end{itemize}\n", encoding="utf-8")
    ctx = _ctx(tmp_path)
    run_claim_graph(ctx)
    graph = load_claims(ctx.workspace.claims_dir / "claims.yaml")
    assert len(graph.claims) == 1, [c.statement for c in graph.claims]


def test_gap005_f3_type_field_is_no_sharpness_bypass(tmp_path):
    """A 'methodological' claim carrying placeholder evidence still fails —
    but a non-empirical claim with NO evidence asserted is out of U1 scope."""
    ctx = _ctx(tmp_path / "a")
    _g4_claims(ctx, _g5_claim("C001", ClaimStatus.EVIDENCE_FOUND,
                              ["evidence_ledger"], ctype="methodological"))
    state, note = _u1(ctx)
    assert state == "FAIL", note
    ctx2 = _ctx(tmp_path / "b")
    _g4_claims(ctx2, _g5_claim("C001", ClaimStatus.EVIDENCE_FOUND, [],
                               ctype="conceptual"))
    state2, _ = _u1(ctx2)
    assert state2 == "PASS", state2


def test_gap005_f4_significance_needs_test_artifact_first(tmp_path):
    """'significantly faster' must not bind a latency metric while skipping
    the statistical-test requirement."""
    draft = tmp_path / "draft"
    draft.mkdir()
    (draft / "paper.md").write_text(
        "Our index is significantly faster by 40% under load.\n", encoding="utf-8")
    ctx = _ctx(tmp_path)
    ctx.workspace.reports_dir.mkdir(parents=True, exist_ok=True)
    (ctx.workspace.reports_dir / "paper_metrics.json").write_text(_json.dumps({
        "metrics": {"M1": {"field": "latency_ms", "mean": 42.0}}}), encoding="utf-8")
    run_claim_graph(ctx)
    graph = load_claims(ctx.workspace.claims_dir / "claims.yaml")
    assert graph.claims[0].status == ClaimStatus.UNSUPPORTED, graph.claims[0]
    # with a test artifact present, the claim binds BOTH test and latency metrics
    (ctx.workspace.reports_dir / "paper_metrics.json").write_text(_json.dumps({
        "metrics": {"M1": {"field": "latency_ms", "mean": 42.0},
                    "T1": {"field": "welch_test_pvalue", "mean": 0.03}}}), encoding="utf-8")
    run_claim_graph(ctx)
    graph = load_claims(ctx.workspace.claims_dir / "claims.yaml")
    c = graph.claims[0]
    assert c.status == ClaimStatus.EVIDENCE_FOUND
    assert set(c.evidence) == {"M1", "T1"}


def test_gap005_f5_nondict_ledger_line_fails_clean(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.workspace.evidence_dir.mkdir(parents=True, exist_ok=True)
    (ctx.workspace.evidence_dir / "evidence_ledger.jsonl").write_text(
        '["not", "a", "dict"]\n', encoding="utf-8")
    _g4_claims(ctx, _g5_claim("C001", ClaimStatus.VERIFIED, ["E001"]))
    state, note = _u1(ctx)
    assert state == "FAIL"
    assert "not an object" in note


def test_gap005_e3_duplicate_ledger_ids_fail(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.workspace.evidence_dir.mkdir(parents=True, exist_ok=True)
    (ctx.workspace.evidence_dir / "evidence_ledger.jsonl").write_text(
        '{"evidence_id": "E001", "tier": "T0"}\n'
        '{"evidence_id": "E001", "tier": "T3"}\n', encoding="utf-8")
    _g4_claims(ctx, _g5_claim("C001", ClaimStatus.VERIFIED, ["E001"]))
    state, note = _u1(ctx)
    assert state == "FAIL"
    assert "duplicate" in note


def test_gap005_e2_caption_optarg_and_nested_braces(tmp_path):
    """B round 2: \\caption[short]{…} and captions with inner font braces must
    not silently drop the claim."""
    draft = tmp_path / "draft"
    draft.mkdir()
    (draft / "paper.tex").write_text(
        "\\begin{table}\n\\caption[Short]{Our estimator achieves 42\\% lower "
        "latency than \\textbf{all} baselines overall.}\n\\end{table}\n",
        encoding="utf-8")
    ctx = _ctx(tmp_path)
    run_claim_graph(ctx)
    graph = load_claims(ctx.workspace.claims_dir / "claims.yaml")
    assert len(graph.claims) == 1, [c.statement for c in graph.claims]
    assert "lower latency" in graph.claims[0].statement


def test_gap005_na_real_evidence_ledger_filename_resolves(tmp_path):
    """A N-A: a concrete file named evidence_ledger.csv is legitimate evidence;
    only the bare placeholder token is vague."""
    ctx = _ctx(tmp_path)
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "evidence_ledger.csv").write_text("a\n1\n",
                                                              encoding="utf-8")
    _g4_claims(ctx, _g5_claim("C001", ClaimStatus.EVIDENCE_FOUND,
                              ["results/evidence_ledger.csv"]))
    state, note = _u1(ctx)
    assert state == "PASS", note


def test_gap005_nb_cite_token_symmetry_in_presence_check(tmp_path):
    """A N-B (MINOR): draft cleaning turns \\cite{...} into CITE; the
    manuscript presence check must fold cites identically, else a verbatim
    printed claim evades the B1 check."""
    ctx = _ctx(tmp_path)
    draft = tmp_path / "draft"
    draft.mkdir()
    (draft / "paper.md").write_text(
        "We achieve 42% lower latency than \\cite{baseline2020} in every "
        "configuration tested here.\n", encoding="utf-8")
    run_claim_graph(ctx)
    graph = load_claims(ctx.workspace.claims_dir / "claims.yaml")
    assert len(graph.claims) == 1
    claim = graph.claims[0]
    assert claim.status == ClaimStatus.UNSUPPORTED  # no metrics seeded
    # the manuscript prints the same sentence as LaTeX
    paper = ctx.workspace.paper_dir / "sections"
    paper.mkdir(parents=True, exist_ok=True)
    (paper / "results.tex").write_text(
        "We achieve 42\\% lower latency than \\cite{baseline2020} in every "
        "configuration tested here.\n", encoding="utf-8")
    run_methods_review(ctx)  # folds claims_audit -> finding with claim_refs
    outcome = run_remediation(ctx)
    reviews, _ = load_reviews(ctx.workspace.reviews_dir)
    f = [f_ for r in reviews for f_ in r.findings
         if f_.kind == "unsupported_claim"][0]
    assert f.disposition == Disposition.DEFERRED, (f.disposition, f.disposition_reason)
    assert "still printed" in (f.disposition_reason or "")
    assert outcome.verdict == Verdict.DEGRADED


def test_gap005_nc_hint_word_boundaries(tmp_path):
    """A N-C: 'specificity' must not satisfy the test-artifact hint 'ci';
    a real test field must."""
    draft = tmp_path / "draft"
    draft.mkdir()
    (draft / "paper.md").write_text(
        "The effect is significant at 0.01 across all seeds.\n", encoding="utf-8")
    ctx = _ctx(tmp_path)
    ctx.workspace.reports_dir.mkdir(parents=True, exist_ok=True)
    (ctx.workspace.reports_dir / "paper_metrics.json").write_text(_json.dumps({
        "metrics": {"M1": {"field": "specificity", "mean": 0.9}}}), encoding="utf-8")
    run_claim_graph(ctx)
    graph = load_claims(ctx.workspace.claims_dir / "claims.yaml")
    assert graph.claims[0].status == ClaimStatus.UNSUPPORTED
    (ctx.workspace.reports_dir / "paper_metrics.json").write_text(_json.dumps({
        "metrics": {"M1": {"field": "specificity", "mean": 0.9},
                    "T1": {"field": "welch_test_pvalue", "mean": 0.03}}}), encoding="utf-8")
    run_claim_graph(ctx)
    graph = load_claims(ctx.workspace.claims_dir / "claims.yaml")
    assert graph.claims[0].status == ClaimStatus.EVIDENCE_FOUND
    assert graph.claims[0].evidence == ["T1"]


@_pytest.mark.parametrize("macro", [
    "\\cite{x21}", "\\ref{fig:a}", "$x_{1}$", "\\url{http://x/y}",
])
def test_gap005_e2_caption_with_brace_macros_extracted(tmp_path, macro):
    """B round 3: a caption carrying a brace-macro must not strand the claim."""
    draft = tmp_path / "draft"
    draft.mkdir()
    (draft / "paper.tex").write_text(
        "\\begin{table}\n\\caption{We improve accuracy by 42\\% over " + macro +
        " baselines overall.}\n\\end{table}\n", encoding="utf-8")
    ctx = _ctx(tmp_path)
    run_claim_graph(ctx)
    graph = load_claims(ctx.workspace.claims_dir / "claims.yaml")
    assert len(graph.claims) == 1, (macro, [c.statement for c in graph.claims])


def test_gap005_braceless_noop_command_at_sentence_start(tmp_path):
    """B round 4 MINOR: \\noindent/\\par before a sentence must not drop it."""
    draft = tmp_path / "draft"
    draft.mkdir()
    (draft / "paper.tex").write_text(
        "\\noindent We improve accuracy by 42\\% over every baseline tested.\n",
        encoding="utf-8")
    ctx = _ctx(tmp_path)
    run_claim_graph(ctx)
    graph = load_claims(ctx.workspace.claims_dir / "claims.yaml")
    assert len(graph.claims) == 1, [c.statement for c in graph.claims]


# ---------------------------------------------------------------------------
# GAP-003: contextual number-to-metric binding in the integrity audit.
# No more 0.5x-2x range gate over ALL metrics (pilot: ~20/44 false positives);
# a number is only flagged when a context/claim binding names the metric.
# ---------------------------------------------------------------------------

from paper_factory.statistics.metrics import run_integrity_audit


def _g3_ctx(tmp_path, metrics: dict, draft_text: str, name="paper.tex"):
    ctx = _ctx(tmp_path)
    ctx.workspace.reports_dir.mkdir(parents=True, exist_ok=True)
    (ctx.workspace.reports_dir / "paper_metrics.json").write_text(_json.dumps({
        "metrics": metrics, "sources": [], "audit": {}}), encoding="utf-8")
    draft = tmp_path / "draft"
    draft.mkdir()
    (draft / name).write_text(draft_text, encoding="utf-8")
    run_integrity_audit(ctx)
    audit = _json.loads(
        (ctx.workspace.reports_dir / "integrity_audit.json").read_text())
    return audit["findings"]


_FPR_METRICS = {
    "EXP__fpr__load0p50": {"field": "fpr", "mean": 0.0117, "n": 3,
                           "group": {"load": "0.50"}},
    "EXP__fpr__load0p90": {"field": "fpr", "mean": 0.0146333, "n": 3,
                           "group": {"load": "0.90"}},
    "EXP__fpr__load0p95": {"field": "fpr", "mean": 0.0201, "n": 3,
                           "group": {"load": "0.95"}},
}


def test_gap003_true_positive_alias_and_group_bound(tmp_path):
    """The synthetic planted defect must STILL be caught — via the alias
    'false-positive rate' and the group context '90% load'."""
    findings = _g3_ctx(tmp_path, _FPR_METRICS,
                       "The filter's false-positive rate climbs steeply, "
                       "reaching 0.021 at 90% load.\n")
    mm = [f for f in findings if f["kind"] == "number_mismatch"]
    assert len(mm) == 1, findings
    f = mm[0]
    assert abs(f["value"] - 0.021) < 1e-9
    # contextually bound: ONLY the load=0.90 metric is the comparison target
    assert f["bound_metrics"] == ["EXP__fpr__load0p90"]
    assert abs(f["expected"]["EXP__fpr__load0p90"] - 0.0146333) < 1e-9


def test_gap003_group_context_number_is_not_a_result(tmp_path):
    """'at 90% load' names the design point — the 90 must not be flagged."""
    findings = _g3_ctx(tmp_path, _FPR_METRICS,
                       "At 90% load the false-positive rate reaches 0.0146.\n")
    assert not [f for f in findings if f["kind"] == "number_mismatch"], findings


def test_gap003_layout_numbers_never_flagged(tmp_path):
    """Pilot FP class: \\linewidth column specs inside table environments."""
    tex = ("\\begin{tabularx}{\\linewidth}{@{}p{0.23\\linewidth}p{0.17\\linewidth}X@{}}\n"
           "\\toprule Family & Construction \\\\\n\\midrule a & b \\\\\n"
           "\\bottomrule\n\\end{tabularx}\n")
    metrics = {"M1": {"field": "loss", "mean": 0.18, "n": 3, "group": {}}}
    findings = _g3_ctx(tmp_path, metrics, tex)
    assert not [f for f in findings if f["kind"] == "number_mismatch"], findings


def test_gap003_threshold_semantics_not_equality(tmp_path):
    """Pilot FP class: a frozen decision threshold is not a measured value."""
    findings = _g3_ctx(tmp_path,
                       {"M1": {"field": "nll", "mean": 0.0613, "n": 1, "group": {}}},
                       "The program froze $0.069$ nats as a project decision "
                       "threshold before the analyses ran.\n")
    assert not [f for f in findings if f["kind"] == "number_mismatch"], findings


def test_gap003_window_spread_claim_not_equality(tmp_path):
    """Pilot FP class: 'losses lie within a 0.0360-nat window' is a spread
    statement, not a mean claim."""
    findings = _g3_ctx(tmp_path,
                       {"M1": {"field": "nll", "mean": 6.5126, "n": 1, "group": {}}},
                       "All eight final validation losses lie within a "
                       "0.0360-nat window, below the frozen threshold.\n")
    assert not [f for f in findings if f["kind"] == "number_mismatch"], findings


def test_gap003_unbound_number_is_informational_not_major(tmp_path):
    """No context binding → no invented assignment. A result-ish unbound
    number becomes a MINOR unverifiable note, never a MAJOR mismatch."""
    findings = _g3_ctx(tmp_path, _FPR_METRICS,
                       "The approach reaches 0.55 on the hidden split, a "
                       "marked improvement.\n")
    assert not [f for f in findings if f["kind"] == "number_mismatch"]
    info = [f for f in findings if f["kind"] == "unverifiable_number"]
    assert info and info[0]["severity"] == "MINOR"


def test_gap003_counts_are_not_metric_means(tmp_path):
    """'9/9 matched cells', '3 seeds', '18 configurations' — counts never
    bind to metric means."""
    findings = _g3_ctx(tmp_path,
                       {"M1": {"field": "nll", "mean": 9.5, "n": 1, "group": {}}},
                       "The configuration is lower-loss in all 9/9 matched "
                       "cells, across 3 seeds and 18 configurations.\n")
    assert not [f for f in findings if f["kind"] == "number_mismatch"], findings


def test_gap003_percent_scaling_bound(tmp_path):
    """Percent numbers compare scale-aware: 2.2% ~ 0.022 metric, not 2.2."""
    metrics = {"M1": {"field": "fpr", "mean": 0.022, "n": 3, "group": {}}}
    ok = _g3_ctx(tmp_path, metrics,
                 "The false-positive rate improves to 2.2% under load.\n")
    assert not [f for f in ok if f["kind"] == "number_mismatch"], ok
    bad = _g3_ctx(tmp_path / "b", metrics,
                  "The false-positive rate improves to 4.9% under load.\n")
    mm = [f for f in bad if f["kind"] == "number_mismatch"]
    assert len(mm) == 1 and abs(mm[0]["value"] - 4.9) < 1e-9, bad


def test_gap003_ratio_claim_binds_to_ratio_metric(tmp_path):
    """Load-bearing FN class from the pilot: a '2.9x' claim must be checked
    when a ratio metric binds — and must not invent a binding when none exists."""
    ratio_metrics = {"M1": {"field": "energy_ratio", "mean": 2.52, "n": 1,
                            "group": {}}}
    bad = _g3_ctx(tmp_path, ratio_metrics,
                  "The corrected step energy is 2.9x lower than the reference.\n")
    mm = [f for f in bad if f["kind"] == "number_mismatch"]
    assert len(mm) == 1 and abs(mm[0]["value"] - 2.9) < 1e-9, bad
    # no ratio metric anywhere -> informational, not a MAJOR
    plain = _g3_ctx(tmp_path / "b",
                    {"M2": {"field": "nll", "mean": 6.5, "n": 1, "group": {}}},
                    "The corrected step energy is 2.9x lower than the reference.\n")
    assert not [f for f in plain if f["kind"] == "number_mismatch"], plain


def test_gap003_pvalue_expression_not_a_result_number(tmp_path):
    """The 0.01 in 'significant at the 0.01 level' is a p-value threshold,
    never a metric value."""
    findings = _g3_ctx(tmp_path,
                       {"M1": {"field": "fpr", "mean": 0.013, "n": 3, "group": {}}},
                       "The false-positive rate drop is significant at the "
                       "0.01 level.\n")
    assert not [f for f in findings if f["kind"] == "number_mismatch"], findings


def test_gap003_range_claim_checked_against_group_minmax(tmp_path):
    """A bound range claim '(lo to hi)' compares against the group's observed
    min/max — wrong ranges are caught, right ranges pass."""
    findings = _g3_ctx(tmp_path, _FPR_METRICS,
                       "The false-positive rate across loads lies between "
                       "0.0117 and 0.0201 in all runs.\n")
    assert not [f for f in findings if f["kind"] == "number_mismatch"], findings
    bad = _g3_ctx(tmp_path / "b", _FPR_METRICS,
                  "The false-positive rate across loads lies between "
                  "0.0117 and 0.0340 in all runs.\n")
    mm = [f for f in bad if f["kind"] == "number_mismatch"]
    assert len(mm) == 1 and mm[0]["value"] == [0.0117, 0.0340], bad


# ---------------------------------------------------------------------------
# GAP-003 review round 1: S1-S3 (reviewer B MAJORs), S4/S5, F-A/F-C/F-E/F-F
# ---------------------------------------------------------------------------

def test_gap003_s1_number_binds_nearest_metric(tmp_path):
    """B-S1 (MAJOR): a wrong latency must not be whitewashed by an incidental
    loss metric with a coincidentally matching value."""
    metrics = {"L": {"field": "latency", "mean": 1.0, "n": 3, "group": {}},
               "N": {"field": "nll", "mean": 5.0, "n": 3, "group": {}}}
    bad = _g3_ctx(tmp_path, metrics,
                  "Our system reaches a latency of 5.0 in production while "
                  "the loss stays stable.\n")
    mm = [f for f in bad if f["kind"] == "number_mismatch"]
    assert len(mm) == 1, bad
    assert mm[0]["bound_metrics"] == ["L"]
    ok = _g3_ctx(tmp_path / "b", metrics,
                 "Our system reaches a latency of 1.0 in production while "
                 "the loss stays stable.\n")
    assert not [f for f in ok if f["kind"] == "number_mismatch"], ok


def test_gap003_s2_anchor_needs_dimension_name(tmp_path):
    """B-S2 + A F-A: 'The fpr is 0.90.' is a RESULT, not a design anchor —
    the exemption needs the dimension word ('load') in the sentence."""
    bad = _g3_ctx(tmp_path, _FPR_METRICS, "The fpr is 0.90.\n")
    mm = [f for f in bad if f["kind"] == "number_mismatch"]
    assert len(mm) == 1, bad
    ok = _g3_ctx(tmp_path / "b", _FPR_METRICS,
                 "The fpr is 0.0201 at 95% load.\n")
    assert not [f for f in ok if f["kind"] == "number_mismatch"], ok


def test_gap003_s2_no_x100_anchor(tmp_path):
    """A F-A: 0.009 is not an anchor of the 0.90 design point (no ×100)."""
    bad = _g3_ctx(tmp_path, _FPR_METRICS, "The fpr is 0.009 at 90% load.\n")
    mm = [f for f in bad if f["kind"] == "number_mismatch"]
    assert len(mm) == 1, bad


def test_gap003_s3_comparative_keyword_needs_proximity(tmp_path):
    """B-S3 (MAJOR): a comparative word far from the number does not
    downgrade the level check to MINOR."""
    metrics = {"L": {"field": "latency", "mean": 1.0, "n": 3, "group": {}}}
    bad = _g3_ctx(tmp_path, metrics,
                  "The latency spread across configs reaches 0.5 in our "
                  "production setup today.\n")
    mm = [f for f in bad if f["kind"] == "number_mismatch"]
    assert len(mm) == 1, bad
    # close comparative keyword → derived semantics honoured (diff metric)
    diff_metrics = {"D": {"field": "latency_diff", "mean": 0.1, "n": 3, "group": {}}}
    bad2 = _g3_ctx(tmp_path / "b", diff_metrics,
                   "The latency differs from the reference by 0.5 in every "
                   "configuration tested.\n")
    mm2 = [f for f in bad2 if f["kind"] == "number_mismatch"]
    assert len(mm2) == 1 and mm2[0]["bound_metrics"] == ["D"], bad2


def test_gap003_s4_alias_word_boundary(tmp_path):
    """B-S4/A F-B: 'gloss' must not bind the 'loss' alias."""
    metrics = {"N": {"field": "nll", "mean": 6.5, "n": 3, "group": {}}}
    findings = _g3_ctx(tmp_path, metrics,
                       "The gloss finish improves the look by 20% in photos.\n")
    assert not [f for f in findings if f["kind"] == "number_mismatch"], findings


def test_gap003_s5_unverifiable_capped(tmp_path):
    """B-S5: unverifiable_number notes dedupe and cap per draft."""
    sentences = " ".join(f"The system reaches 0.{10 + i} in trial number {i}."
                         for i in range(20))
    findings = _g3_ctx(tmp_path, _FPR_METRICS, sentences + "\n")
    info = [f for f in findings if f["kind"] == "unverifiable_number"
            and f.get("value") is not None]
    assert 0 < len(info) <= 10, len(info)


def test_gap003_fc_vs_does_not_split_sentence(tmp_path):
    """A F-C: 'vs.' keeps the sentence together — the baseline number stays
    in the bound context."""
    metrics = {"F1": {"field": "fpr", "mean": 0.021, "n": 3,
                      "group": {"system": "ours"}},
               "F2": {"field": "fpr", "mean": 0.050, "n": 3,
                      "group": {"system": "baseline"}}}
    findings = _g3_ctx(tmp_path, metrics,
                       "Our fpr is 0.021 vs. 0.050 for the baseline system.\n")
    assert not [f for f in findings if f["kind"] == "number_mismatch"], findings


def test_gap003_fe_deferral_reason_uses_expected(tmp_path):
    """A F-E: the remediation deferral reason must carry the derived
    value(s), never 'None'."""
    ctx = _ctx(tmp_path)
    _g4_claims(ctx)
    _g4_review(ctx, [_g4_finding(
        "F01", kind="number_mismatch",
        details={"draft": "draft/p.tex", "value": 0.021,
                 "bound_metrics": ["EXP__fpr__load0p90"],
                 "expected": {"EXP__fpr__load0p90": 0.0146333}})])
    run_remediation(ctx)
    reviews, _ = load_reviews(ctx.workspace.reviews_dir)
    reason = reviews[0].findings[0].disposition_reason or ""
    assert "0.0146333" in reason and "None" not in reason, reason
    assert "EXP__fpr__load0p90" in reason


def test_gap003_ff_significance_merges_adjacent_hits(tmp_path):
    """A F-F: 'significant (p < 0.05)' is ONE finding, not two."""
    findings = _g3_ctx(tmp_path, {},
                       "The drop is significant (p < 0.05) across seeds.\n")
    sig = [f for f in findings if f["kind"] == "significance_without_test"]
    assert len(sig) == 1, sig


# ---------------------------------------------------------------------------
# GAP-003 review round 2: R1 (decoy anchor), R2 (universal quantifier),
# R4 (plural alias), R5 (cap marker)
# ---------------------------------------------------------------------------

def test_gap003_r1_exceptive_marker_disqualifies_decoy_anchor(tmp_path):
    """B-R1 (MAJOR): 'Latency, unlike the loss, reaches 5.0' — the number
    belongs to latency, not to the closer 'loss'."""
    metrics = {"L": {"field": "latency", "mean": 1.0, "n": 3, "group": {}},
               "N": {"field": "nll", "mean": 5.0, "n": 3, "group": {}}}
    bad = _g3_ctx(tmp_path, metrics,
                  "Latency, unlike the loss, reaches 5.0 in production "
                  "every day.\n")
    mm = [f for f in bad if f["kind"] == "number_mismatch"]
    assert len(mm) == 1, bad
    assert mm[0]["bound_metrics"] == ["L"]


def test_gap003_r2_universal_quantifier_disables_anchor(tmp_path):
    """B-R2 (MAJOR): 'reaches 0.90 at every load' claims the value for ALL
    design points — no point-anchor exemption, and it must hold everywhere."""
    bad = _g3_ctx(tmp_path, _FPR_METRICS,
                  "The fpr reaches 0.0201 at every load we measured.\n")
    mm = [f for f in bad if f["kind"] == "number_mismatch"]
    assert len(mm) == 1, bad  # 0.0201 holds only at 0.95, not at 0.50/0.90
    # a value that genuinely holds at every load passes... construct that world
    uniform = {"M1": {"field": "fpr", "mean": 0.02, "n": 3, "group": {"load": "0.50"}},
               "M2": {"field": "fpr", "mean": 0.02, "n": 3, "group": {"load": "0.90"}}}
    ok = _g3_ctx(tmp_path / "b", uniform,
                 "The fpr reaches 0.02 at every load we measured.\n")
    assert not [f for f in ok if f["kind"] == "number_mismatch"], ok


def test_gap003_r4_plural_alias_binds(tmp_path):
    """B-R4: 'losses' binds the 'loss' alias."""
    metrics = {"N": {"field": "nll", "mean": 6.5, "n": 3, "group": {}}}
    ok = _g3_ctx(tmp_path, metrics,
                 "The losses reach 6.4 across seeds in this configuration.\n")
    assert not [f for f in ok if f["kind"] == "number_mismatch"], ok
    bad = _g3_ctx(tmp_path / "b", metrics,
                  "The losses reach 7.9 across seeds in this configuration.\n")
    assert len([f for f in bad if f["kind"] == "number_mismatch"]) == 1, bad


def test_gap003_r5_cap_overflow_leaves_marker(tmp_path):
    """B-R5: suppressed unverifiable notes leave one visible marker."""
    sentences = " ".join(f"The system reaches 0.{10 + i} in trial number {i}."
                         for i in range(25))
    findings = _g3_ctx(tmp_path, _FPR_METRICS, sentences + "\n")
    info = [f for f in findings if f["kind"] == "unverifiable_number"]
    markers = [f for f in info if f.get("value") is None]
    assert markers and "suppressed" in markers[0]["note"], info
    assert len(info) <= 11  # 10 emitted + 1 marker


def test_gap003_w1_long_exceptive_markers(tmp_path):
    """B-W1: 'rather than'/'as opposed to' must disqualify the decoy anchor
    even though they are longer than 12 chars."""
    metrics = {"L": {"field": "latency", "mean": 1.0, "n": 3, "group": {}},
               "N": {"field": "nll", "mean": 5.0, "n": 3, "group": {}}}
    for i, marker in enumerate(("rather than the", "as opposed to the")):
        bad = _g3_ctx(tmp_path / f"w{i}", metrics,
                      f"Latency, {marker} loss, reaches 5.0 in production "
                      "every day.\n")
        mm = [f for f in bad if f["kind"] == "number_mismatch"]
        assert len(mm) == 1 and mm[0]["bound_metrics"] == ["L"], (marker, bad)


def test_gap003_w2_result_number_is_never_the_anchor(tmp_path):
    """B-W2: a RESULT number equal to the design value is not exempted —
    only the mention ADJACENT to the dimension word is."""
    bad = _g3_ctx(tmp_path, _FPR_METRICS,
                  "In every single one of our test configurations at load "
                  "0.90, the fpr reaches 0.90.\n")
    mm = [f for f in bad if f["kind"] == "number_mismatch"]
    assert len(mm) == 1, bad
    # the adjacent mention still exempts (control)
    ok = _g3_ctx(tmp_path / "b", _FPR_METRICS,
                 "The fpr is 0.0201 at 95% load.\n")
    assert not [f for f in ok if f["kind"] == "number_mismatch"], ok
    # 'per' as distributive universal
    bad2 = _g3_ctx(tmp_path / "c", _FPR_METRICS,
                   "The fpr reaches 0.0201 per load we measured.\n")
    assert len([f for f in bad2 if f["kind"] == "number_mismatch"]) == 1, bad2


def test_gap003_w3_verb_distance_negation(tmp_path):
    """B-W3: 'does not reach a latency of 5.0' is a true negation, not a
    contradiction."""
    metrics = {"L": {"field": "latency", "mean": 1.0, "n": 3, "group": {}}}
    ok = _g3_ctx(tmp_path, metrics,
                  "The system does not reach a latency of 5.0 in production.\n")
    assert not [f for f in ok if f["kind"] == "number_mismatch"], ok
    # positive control still catches the wrong value
    bad = _g3_ctx(tmp_path / "b", metrics,
                  "The system does reach a latency of 5.0 in production.\n")
    assert len([f for f in bad if f["kind"] == "number_mismatch"]) == 1, bad


def test_gap003_x1_result_at_design_point_not_exempt(tmp_path):
    """B-X1: 'The fpr is 0.90 at 0.90 load.' — the first number is a RESULT,
    only the '0.90' argument of 'load' is the design mention."""
    bad = _g3_ctx(tmp_path, _FPR_METRICS,
                  "The fpr is 0.90 at 0.90 load in our setup.\n")
    mm = [f for f in bad if f["kind"] == "number_mismatch"]
    assert len(mm) == 1, bad


def test_gap003_x2_false_negation_caught(tmp_path):
    """B-X2: a negation of the TRUE value is a false claim — evaluate it."""
    metrics = {"L": {"field": "latency", "mean": 5.0, "n": 3, "group": {}}}
    bad = _g3_ctx(tmp_path, metrics,
                  "The system does not reach a latency of 5.0 in production.\n")
    mm = [f for f in bad if f["kind"] == "number_mismatch"]
    assert len(mm) == 1, bad
    # true negation stays clean
    ok = _g3_ctx(tmp_path / "b",
                 {"L": {"field": "latency", "mean": 1.0, "n": 3, "group": {}}},
                 "The system does not reach a latency of 5.0 in production.\n")
    assert not [f for f in ok if f["kind"] == "number_mismatch"], ok


def test_gap003_x3_cap_negation_polarity(tmp_path):
    """B-X3: 'never exceeds 5.0' claims metric <= 5.0 — violated when the
    derived value is 9.0, true when it is 1.0."""
    ok = _g3_ctx(tmp_path,
                 {"L": {"field": "latency", "mean": 1.0, "n": 3, "group": {}}},
                 "The latency never exceeds 5.0 in our measurements.\n")
    assert not [f for f in ok if f["kind"] == "number_mismatch"], ok
    bad = _g3_ctx(tmp_path / "b",
                  {"L": {"field": "latency", "mean": 9.0, "n": 3, "group": {}}},
                  "The latency never exceeds 5.0 in our measurements.\n")
    assert len([f for f in bad if f["kind"] == "number_mismatch"]) == 1, bad


def test_gap003_y1_result_before_at_load_not_exempt(tmp_path):
    """B-Y1: 'The fpr is 0.90 at load 0.90.' — the predicate number before
    'at load' is a RESULT, not the design argument."""
    bad = _g3_ctx(tmp_path, _FPR_METRICS,
                  "The fpr is 0.90 at load 0.90 in our setup.\n")
    mm = [f for f in bad if f["kind"] == "number_mismatch"]
    assert len(mm) == 1, bad
    # word order with the argument first stays clean
    ok = _g3_ctx(tmp_path / "b", _FPR_METRICS,
                 "The fpr at 0.90 load reaches 0.0146 in our setup.\n")
    assert not [f for f in ok if f["kind"] == "number_mismatch"], ok


def test_gap003_y3_positive_polarity_idioms(tmp_path):
    """B-Y3: 'stays below 5.0' is a floor claim — true for 1.0, violated
    for 9.0; 'stays above 5.0' mirrors."""
    ok = _g3_ctx(tmp_path,
                 {"L": {"field": "latency", "mean": 1.0, "n": 3, "group": {}}},
                 "The latency stays below 5.0 in all our tests.\n")
    assert not [f for f in ok if f["kind"] == "number_mismatch"], ok
    bad = _g3_ctx(tmp_path / "b",
                  {"L": {"field": "latency", "mean": 9.0, "n": 3, "group": {}}},
                  "The latency stays below 5.0 in all our tests.\n")
    assert len([f for f in bad if f["kind"] == "number_mismatch"]) == 1, bad
    ok2 = _g3_ctx(tmp_path / "c",
                  {"L": {"field": "latency", "mean": 9.0, "n": 3, "group": {}}},
                  "The latency stays above 5.0 in all our tests.\n")
    assert not [f for f in ok2 if f["kind"] == "number_mismatch"], ok2
    bad2 = _g3_ctx(tmp_path / "d",
                   {"L": {"field": "latency", "mean": 1.0, "n": 3, "group": {}}},
                   "The latency stays above 5.0 in all our tests.\n")
    assert len([f for f in bad2 if f["kind"] == "number_mismatch"]) == 1, bad2


# ---------------------------------------------------------------------------
# GAP-010: review finding dedupe — same underlying issue folded into P23/P24/
# P25 is remediated ONCE, disposition propagated, reviewer roles preserved.
# GAP-006: JSONL history parsing — journal entries without a 'text' field
# (note/state/job_id) must yield real previews, not 50 empty strings.
# ---------------------------------------------------------------------------

from paper_factory.context.mining import run_context_mining


def test_gap010_duplicate_findings_remediated_once(tmp_path):
    """The same number_mismatch folded into three reviewer reports must be
    remediated once and dispositioned everywhere — not three independent
    entries with three outcomes."""
    ctx = _ctx(tmp_path)
    _g4_claims(ctx)
    detail = {"draft": "draft/p.tex", "value": 0.021,
              "bound_metrics": ["M1"], "expected": {"M1": 0.0146}}
    for rid, reviewer in (("P23-methods", "methods_reviewer"),
                          ("P24-statistics", "statistics_reviewer"),
                          ("P25-adversarial", "adversarial_reviewer_2")):
        save_review(ctx.workspace.reviews_dir, ReviewReport(
            review_id=rid, reviewer=reviewer,
            findings=[_g4_finding(f"{rid}-F01", kind="number_mismatch",
                                  category="methods", details=detail)]))
    outcome = run_remediation(ctx)
    log = _json.loads((ctx.workspace.reports_dir / "remediation_log.json").read_text())
    acted = [e for e in log["entries"] if e.get("action") != "duplicate"]
    dupes = [e for e in log["entries"] if e.get("action") == "duplicate"]
    assert len(acted) == 1, log["entries"]
    assert len(dupes) == 2, log["entries"]
    reviews, _ = load_reviews(ctx.workspace.reviews_dir)
    dispositions = {f.finding_id: f.disposition for r in reviews for f in r.findings}
    assert len(set(dispositions.values())) == 1  # one issue, one outcome
    assert all(d == Disposition.DEFERRED for d in dispositions.values())
    # reviewer provenance stays intact
    assert {r.reviewer for r in reviews} == {"methods_reviewer", "statistics_reviewer",
                                             "adversarial_reviewer_2"}
    assert outcome.verdict == Verdict.DEGRADED


def test_gap010_different_issues_not_deduped(tmp_path):
    """Same kind but different scientific surface = different issues."""
    ctx = _ctx(tmp_path)
    _g4_claims(ctx)
    for i, val in enumerate((0.021, 0.033)):
        _g4_review(ctx, [_g4_finding(f"R-F{i}", kind="number_mismatch",
                                     category="methods",
                                     details={"draft": "draft/p.tex", "value": val,
                                              "bound_metrics": ["M1"],
                                              "expected": {"M1": 0.01}})],
                   review_id=f"R{i}")
    run_remediation(ctx)
    log = _json.loads((ctx.workspace.reports_dir / "remediation_log.json").read_text())
    acted = [e for e in log["entries"] if e.get("action") != "duplicate"]
    assert len(acted) == 2, log["entries"]


def test_gap010_u5_counts_unique_issues(tmp_path):
    """U5's note should surface the unique-issue count, not 3x noise."""
    ctx = _ctx(tmp_path)
    detail = {"draft": "draft/p.tex", "value": 0.021, "bound_metrics": ["M1"],
              "expected": {"M1": 0.0146}}
    for rid in ("A", "B", "C"):
        _g4_review(ctx, [_g4_finding(f"{rid}-F01", kind="number_mismatch",
                                     category="methods", details=detail)],
                   review_id=rid)
    state, note = _u5(ctx)
    assert state == "FAIL"
    assert "1 unique" in note, note


def test_gap006_jsonl_journal_entries_yield_previews(tmp_path):
    """Pilot repro: R_JOB_STATE_JOURNAL.jsonl — 187 chronology entries, all
    with empty preview. Journal-shaped lines must render real text."""
    hist = tmp_path / "history"
    hist.mkdir()
    (hist / "journal.jsonl").write_text(
        '{"job_id": "laneB_idx623", "note": "Registrierung: Lauf vom 2026-08-01, '
        'MUON_MATRIX_ADAMW_VECTOR bestätigt", "state": "DONE", "ts": "2026-08-06T16:49:44"}\n'
        '{"job_id": "laneB_idx624", "log": "/var/log/run.log", "state": "RUNNING", '
        '"ts": "2026-08-06T16:50:01"}\n', encoding="utf-8")
    ctx = _ctx(tmp_path)
    ctx.workspace.reports_dir.mkdir(parents=True, exist_ok=True)
    (ctx.workspace.reports_dir / "intake_report.json").write_text(_json.dumps({
        "inputs": {"chats": [{"path": "history/journal.jsonl"}]}}), encoding="utf-8")
    outcome = run_context_mining(ctx)
    summary = _json.loads(
        (ctx.workspace.context_dir / "context_summary.json").read_text())
    chron = summary["chronology"]
    assert len(chron) == 2
    assert all(c["preview"].strip() for c in chron), chron
    assert "MUON_MATRIX" in chron[0]["preview"]
    assert "laneB_idx624" in chron[1]["preview"]  # scalar-field fallback
    assert outcome.verdict == Verdict.PASS


def test_gap010_range_list_value_does_not_crash(tmp_path):
    """A-D1/D2 (MAJOR): GAP-003 range findings carry value=[lo,hi] — the
    dedupe key must canonicalize sequences, never TypeError."""
    ctx = _ctx(tmp_path)
    _g4_claims(ctx)
    detail = {"draft": "draft/p.tex", "value": [0.02, 0.03],
              "bound_metrics": ["M1"], "expected": {"min": 0.01, "max": 0.02}}
    _g4_review(ctx, [_g4_finding("F01", kind="number_mismatch",
                                 category="methods", details=detail)])
    outcome = run_remediation(ctx)  # must not raise TypeError
    assert outcome.verdict == Verdict.DEGRADED
    state, _ = _u5(ctx)
    assert state == "FAIL"  # DEFERRED blocks — no crash, no mask


def test_gap010_forged_excerpt_duplicate_not_resolved(tmp_path):
    """B-G1 (MAJOR): the G6 excerpt check runs over ALL claim findings before
    dedupe — a forged excerpt in a duplicate must not inherit RESOLVED."""
    ctx = _ctx(tmp_path)
    claim_text = "Our method outperforms all baselines by 42%."
    _g4_claims(ctx, Claim(claim_id="C001", statement=claim_text,
                          status=ClaimStatus.UNSUPPORTED))
    # clean representative (alphabetically first review id)
    _g4_review(ctx, [_g4_finding("F01", kind="unsupported_claim",
                                 claim_refs=["C001"], category="statistics",
                                 details={"excerpt": claim_text})],
               review_id="a_rev")
    # forged duplicate — same dedupe key, poisoned excerpt
    _g4_review(ctx, [_g4_finding("F02", kind="unsupported_claim",
                                 claim_refs=["C001"], category="statistics",
                                 details={"excerpt": "completely different text"})],
               review_id="z_rev")
    outcome = run_remediation(ctx)
    assert outcome.verdict == Verdict.FAIL  # INVALID propagates to verdict
    reviews, _ = load_reviews(ctx.workspace.reviews_dir)
    by_id = {f.finding_id: f for r in reviews for f in r.findings}
    assert by_id["F02"].disposition == Disposition.INVALID_REMEDIATION_ARTIFACT
    assert by_id["F01"].disposition == Disposition.RESOLVED  # clean one resolved


def test_gap010_unbound_findings_stay_unique_by_statement(tmp_path):
    """A-D4: two unbound findings with different statements must not collapse
    into '1 unique' in the U5 note."""
    ctx = _ctx(tmp_path)
    for i in range(2):
        f = _g4_finding(f"F{i}", kind=None, category="methods",
                        statement=f"distinct issue number {i} with no binding")
        _g4_review(ctx, [f], review_id=f"R{i}")
    state, note = _u5(ctx)
    assert state == "FAIL"
    assert "2 unique" in note, note


def test_gap006_preview_fallback_never_lifts_secret_keys(tmp_path):
    """A-D7: the scalar-field fallback must not render token/secret-like keys."""
    from paper_factory.context.mining import _message_text
    out = _message_text({"job_id": "J-42", "state": "failed",
                         "token": "sk-abc123-secret", "api_key": "xyz"})
    assert "sk-abc123-secret" not in out and "xyz" not in out
    assert "J-42" in out and "failed" in out


# ---------------------------------------------------------------------------
# GAP-2 (real pilot 2): DEGRADED metrics/tables nodes still emit VALID empty
# generated/*.tex — the scaffold references them unconditionally; venue
# compliance must fail for principled reasons (no bib), never 'file not found'
# ---------------------------------------------------------------------------

from paper_factory.manuscript.scaffold import run_manuscript_architecture
from paper_factory.release.closure import _generated_policy
from paper_factory.tables.build import run_table_generation
from paper_factory.venue.compliance import run_venue_compliance


def test_gap2_degraded_statistics_emits_valid_empty_numbers_tex(tmp_path):
    ctx = _ctx(tmp_path)  # no results/ directory
    outcome = run_statistics(ctx)
    assert outcome.verdict == Verdict.DEGRADED
    numbers = ctx.workspace.paper_dir / "generated" / "numbers.tex"
    assert numbers.exists()
    text = numbers.read_text(encoding="utf-8")
    assert "empty by design" in text
    from paper_factory.statistics.quantitative import PFGET_ACCESSOR_LINE
    assert PFGET_ACCESSOR_LINE in text
    violations, defs = _generated_policy(ctx.workspace.paper_dir)
    assert not violations, violations
    assert defs == {}, "empty numbers.tex must define zero pf@ macros"


def test_gap2_degraded_tables_emit_valid_empty_tables_tex(tmp_path):
    ctx = _ctx(tmp_path)  # no plan, no metrics
    outcome = run_table_generation(ctx)
    assert outcome.verdict == Verdict.DEGRADED
    tables = ctx.workspace.paper_dir / "generated" / "tables.tex"
    assert tables.exists()
    assert "empty by design" in tables.read_text(encoding="utf-8")


def test_gap2_manuscript_compiles_with_empty_generated(tmp_path):
    """The pilot-2 failure mode is gone: scaffold + empty generated files must
    compile; bib_exists may still fail — that one is principled."""
    ctx = _ctx(tmp_path)
    run_statistics(ctx)          # DEGRADED → empty numbers.tex
    run_table_generation(ctx)    # DEGRADED → empty tables.tex
    run_manuscript_architecture(ctx)
    outcome = run_venue_compliance(ctx)
    report = _json.loads(
        (ctx.workspace.reports_dir / "venue_compliance.json").read_text())
    assert report["checks"]["compiles"]["pass"], report["checks"]["compiles"]
    assert "bib_exists" in report["failed"]  # honest, principled failure
    assert outcome.verdict == Verdict.FAIL  # still FAIL — but for the real reason


# ---------------------------------------------------------------------------
# GAP-012 (real pilot 2): metric discovery is not results/-conventional —
# runs/, data/, fixtures/, config inputs.paths and SQLite tables all feed the
# same classification pipeline, read-only.
# ---------------------------------------------------------------------------

def test_gap012_runs_dir_csv_discovered(tmp_path):
    """Pilot-2 shape: metrics live in runs/, not results/."""
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "experiment.csv").write_text(
        "arm,cell,nll\n" + "".join(f"a{i%2},c{i%2},{4.5 + i * 0.1:.4f}\n"
                                   for i in range(6)), encoding="utf-8")
    ctx = _ctx(tmp_path)
    outcome = run_statistics(ctx)
    assert outcome.verdict == Verdict.PASS, outcome.detail
    metrics = _json.loads(
        (ctx.workspace.reports_dir / "paper_metrics.json").read_text())["metrics"]
    assert metrics, "runs/ CSV must produce metrics"
    assert any("runs/experiment.csv" in v["source"] for v in metrics.values())


def test_gap012_sqlite_tables_as_metric_source(tmp_path):
    """baseline.sqlite (pilot 2) shape: read-only per-table ingestion."""
    import sqlite3
    runs = tmp_path / "runs"
    runs.mkdir()
    db = runs / "baseline.sqlite"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE call_counts (scope TEXT, model TEXT, n_calls REAL)")
    con.executemany("INSERT INTO call_counts VALUES (?,?,?)",
                    [("a", "m1", 100 + i) for i in range(4)]
                    + [("b", "m1", 200 + i) for i in range(4)])
    con.commit()
    con.close()
    before = db.read_bytes()
    ctx = _ctx(tmp_path)
    outcome = run_statistics(ctx)
    assert outcome.verdict == Verdict.PASS, outcome.detail
    assert db.read_bytes() == before, "read-only: the DB must be untouched"
    metrics = _json.loads(
        (ctx.workspace.reports_dir / "paper_metrics.json").read_text())["metrics"]
    keys = list(metrics)
    assert any("baseline__call_counts__n_calls" in k for k in keys), keys
    # grouped by the repeating text columns (scope, model)
    means = sorted(round(v["mean"], 1) for v in metrics.values())
    assert 101.5 in means and 201.5 in means, means


def test_gap012_no_sources_still_degraded(tmp_path):
    ctx = _ctx(tmp_path)  # nothing at all
    outcome = run_statistics(ctx)
    assert outcome.verdict == Verdict.DEGRADED
    assert "no data sources" in outcome.detail["reason"]
    assert (ctx.workspace.paper_dir / "generated" / "numbers.tex").exists()


def test_gap012_config_inputs_paths_discovered(tmp_path):
    """config inputs.paths extends the discovery set."""
    extra = tmp_path / "measurements"
    extra.mkdir()
    (extra / "m.csv").write_text("seed,score\n1,0.5\n2,0.7\n3,0.6\n",
                                 encoding="utf-8")
    ctx = _ctx(tmp_path)
    ctx.config.inputs.paths = ["measurements"]
    outcome = run_statistics(ctx)
    assert outcome.verdict == Verdict.PASS
    metrics = _json.loads(
        (ctx.workspace.reports_dir / "paper_metrics.json").read_text())["metrics"]
    assert any("measurements/m.csv" in v["source"] for v in metrics.values())


# ---------------------------------------------------------------------------
# GAP-012 review round 1 (reviewer A D1-D5 / reviewer B D1-D3): scope guard,
# stem collision, WAL safety, corrupt-source resilience, audit transparency
# ---------------------------------------------------------------------------

import sqlite3 as _sqlite3


def _audit(ctx):
    return _json.loads(
        (ctx.workspace.reports_dir / "paper_metrics.json").read_text())["audit"]


def test_gap012_d1_same_filename_in_results_and_runs_both_kept(tmp_path):
    """D1: results/x.csv and runs/x.csv must never shadow each other."""
    (tmp_path / "results").mkdir()
    (tmp_path / "runs").mkdir()
    (tmp_path / "results" / "x.csv").write_text(
        "seed,score\n1,0.1\n2,0.2\n3,0.15\n", encoding="utf-8")
    (tmp_path / "runs" / "x.csv").write_text(
        "seed,score\n1,0.8\n2,0.9\n3,0.85\n", encoding="utf-8")
    ctx = _ctx(tmp_path)
    outcome = run_statistics(ctx)
    assert outcome.verdict == Verdict.PASS, outcome.detail
    data = _json.loads((ctx.workspace.reports_dir / "paper_metrics.json").read_text())
    sources = {m["source"] for m in data["metrics"].values()}
    assert sources == {"results/x.csv", "runs/x.csv"}, sources
    means = sorted(round(m["mean"], 2) for m in data["metrics"].values())
    assert means == [0.15, 0.85], means  # neither lost, each correctly bound


def test_gap012_d2_inputs_paths_escape_rejected(tmp_path):
    """D2: absolute and ../-escaping config paths are excluded, never read."""
    outside = tmp_path.parent / "outside_gap012"
    outside.mkdir(exist_ok=True)
    (outside / "leak.csv").write_text("seed,score\n1,9.9\n2,9.9\n", encoding="utf-8")
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "ok.csv").write_text(
        "seed,score\n1,0.5\n2,0.7\n3,0.6\n", encoding="utf-8")
    ctx = _ctx(tmp_path)
    ctx.config.inputs.paths = ["../outside_gap012", str(outside), "missing_dir"]
    outcome = run_statistics(ctx)
    assert outcome.verdict == Verdict.PASS, outcome.detail  # no crash
    data = _json.loads((ctx.workspace.reports_dir / "paper_metrics.json").read_text())
    sources = {m["source"] for m in data["metrics"].values()}
    assert sources == {"results/ok.csv"}, sources
    excl = _json.dumps(data["audit"]["exclusions"])
    assert "../outside_gap012" in excl and str(outside) in excl
    assert "missing_dir" in excl


def test_gap012_d2_symlinked_inputs_dir_escape_rejected(tmp_path):
    """D2b: an in-root symlink whose target is outside is rejected."""
    outside = tmp_path.parent / "outside_gap012_symlink"
    outside.mkdir(exist_ok=True)
    (outside / "leak.csv").write_text("seed,score\n1,9.9\n2,9.8\n", encoding="utf-8")
    (tmp_path / "alias").symlink_to(outside, target_is_directory=True)
    ctx = _ctx(tmp_path)
    ctx.config.inputs.paths = ["alias"]
    outcome = run_statistics(ctx)
    assert outcome.verdict == Verdict.DEGRADED  # nothing admissible left
    excl = _json.dumps(_audit(ctx)["exclusions"])
    assert "symlink escapes target root" in excl


def test_gap012_d2_symlinked_subdir_file_never_read(tmp_path):
    """D2c: discovery never returns a file resolving outside the root, even
    when reached through a symlinked subdirectory of a conventional dir."""
    outside = tmp_path.parent / "outside_gap012_sub"
    outside.mkdir(exist_ok=True)
    (outside / "leak.csv").write_text("seed,score\n1,9.9\n2,9.8\n", encoding="utf-8")
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "link").symlink_to(outside, target_is_directory=True)
    (tmp_path / "results" / "ok.csv").write_text(
        "seed,score\n1,0.5\n2,0.7\n3,0.6\n", encoding="utf-8")
    ctx = _ctx(tmp_path)
    outcome = run_statistics(ctx)
    assert outcome.verdict == Verdict.PASS, outcome.detail
    data = _json.loads((ctx.workspace.reports_dir / "paper_metrics.json").read_text())
    assert {m["source"] for m in data["metrics"].values()} == {"results/ok.csv"}


def test_gap012_d3_wal_db_reads_committed_state_without_sidecars(tmp_path):
    """D3: a WAL-mode DB with uncheckpointed commits must yield the CURRENT
    committed state — and PF must leave the original file + sidecars exactly
    as found (no checkpoint of the original, no new files)."""
    runs = tmp_path / "runs"
    runs.mkdir()
    db = runs / "live.sqlite"
    con = _sqlite3.connect(db)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE t (grp TEXT, val REAL)")
    con.executemany("INSERT INTO t VALUES ('a', ?)", [(float(i),) for i in range(3)])
    con.commit()
    # keep the WAL hot: an open second connection prevents auto-checkpoint
    hold = _sqlite3.connect(db)
    hold.execute("BEGIN")
    hold.execute("SELECT count(*) FROM t").fetchone()
    assert (runs / "live.sqlite-wal").exists()
    before = {p.name: p.read_bytes() for p in runs.iterdir()}
    ctx = _ctx(tmp_path)
    outcome = run_statistics(ctx)
    assert outcome.verdict == Verdict.PASS, outcome.detail
    data = _json.loads((ctx.workspace.reports_dir / "paper_metrics.json").read_text())
    assert any(m["field"] == "val" and m["n"] == 3 for m in data["metrics"].values()), \
        "committed WAL rows must be visible"
    after = {p.name: p.read_bytes() for p in runs.iterdir()}
    hold.rollback()
    hold.close()
    con.close()
    assert set(after) == set(before), "PF must not create sidecars"
    assert after == before, "PF must not modify the original DB or its WAL"


def test_gap012_d4_corrupt_sqlite_only_is_honest_degraded(tmp_path):
    """A corrupt SQLite file must not crash P09: exclusion + DEGRADED."""
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "broken.sqlite").write_bytes(b"this is not a sqlite database at all")
    ctx = _ctx(tmp_path)
    outcome = run_statistics(ctx)
    assert outcome.verdict == Verdict.DEGRADED, outcome.detail
    excl = _json.dumps(_audit(ctx)["exclusions"])
    assert "broken.sqlite" in excl and "unreadable" in excl


def test_gap012_d4_mixed_corrupt_and_valid_keeps_valid_metrics(tmp_path):
    """Corrupt + valid sources: valid metrics survive, exclusion stays visible."""
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "broken.db").write_bytes(b"garbage-not-sqlite")
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "ok.csv").write_text(
        "seed,score\n1,0.5\n2,0.7\n3,0.6\n", encoding="utf-8")
    ctx = _ctx(tmp_path)
    outcome = run_statistics(ctx)
    assert outcome.verdict == Verdict.PASS, outcome.detail
    data = _json.loads((ctx.workspace.reports_dir / "paper_metrics.json").read_text())
    assert any(m["source"] == "results/ok.csv" for m in data["metrics"].values())
    excl = _json.dumps(data["audit"]["exclusions"])
    assert "broken.db" in excl and "unreadable" in excl


def test_gap012_d4_weird_table_name_quoted(tmp_path):
    """Table names with quotes/spaces are handled via identifier quoting."""
    runs = tmp_path / "runs"
    runs.mkdir()
    db = runs / "weird.sqlite"
    con = _sqlite3.connect(db)
    con.execute('CREATE TABLE "weird ""table"" name" (grp TEXT, val REAL)')
    con.executemany('INSERT INTO "weird ""table"" name" VALUES (?,?)',
                    [("a", 0.5), ("a", 0.7), ("b", 0.9)])
    con.commit()
    con.close()
    ctx = _ctx(tmp_path)
    outcome = run_statistics(ctx)
    assert outcome.verdict == Verdict.PASS, outcome.detail
    data = _json.loads((ctx.workspace.reports_dir / "paper_metrics.json").read_text())
    assert any("weird" in m["source"] for m in data["metrics"].values())


def test_gap012_d5_caps_visible_in_audit(tmp_path):
    """D5: truncation policy is audit-visible, never silent."""
    outcome, data = _stats(tmp_path, "seed,score\n1,0.5\n2,0.7\n3,0.6\n")
    assert outcome.verdict == Verdict.PASS
    assert data["audit"]["caps"]["sqlite_row_cap"] == 200_000
    assert data["audit"]["caps"]["csv"] == "uncapped"


# ---------------------------------------------------------------------------
# GAP-012 review round 2 (B-D1 workspace self-ingestion, A-N1..N4)
# ---------------------------------------------------------------------------

def test_gap012_b_d1_dot_inputs_path_never_ingests_workspace_state(tmp_path):
    """B-D1 (MAJOR): inputs.paths=['.'] must not read .paper-factory/runs.sqlite
    (the pipeline's own bookkeeping) as a data source — self-referential
    provenance. Other data still flows."""
    state_db = tmp_path / ".paper-factory"
    state_db.mkdir()
    con = _sqlite3.connect(state_db / "runs.sqlite")
    con.execute("CREATE TABLE nodes (node_id TEXT, attempts REAL)")
    con.executemany("INSERT INTO nodes VALUES (?,?)",
                    [("P00", 1.0), ("P00", 2.0), ("P01", 1.0)])
    con.commit()
    con.close()
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "ok.csv").write_text(
        "seed,score\n1,0.5\n2,0.7\n3,0.6\n", encoding="utf-8")
    ctx = _ctx(tmp_path)
    ctx.config.inputs.paths = ["."]
    outcome = run_statistics(ctx)
    assert outcome.verdict == Verdict.PASS, outcome.detail
    data = _json.loads((ctx.workspace.reports_dir / "paper_metrics.json").read_text())
    assert not any(".paper-factory" in s for s in data["sources"]), data["sources"]
    assert {m["source"] for m in data["metrics"].values()} == {"results/ok.csv"}
    excl = _json.dumps(data["audit"]["exclusions"])
    assert "runs.sqlite" in excl  # visible, not silent


def test_gap012_a_n1_stem_mapping_is_injective(tmp_path):
    """A-N1: results/a__b.csv and results/a/b.csv must both survive."""
    (tmp_path / "results" / "a").mkdir(parents=True)
    (tmp_path / "results" / "a__b.csv").write_text(
        "seed,score\n1,1.0\n2,1.2\n3,1.1\n", encoding="utf-8")
    (tmp_path / "results" / "a" / "b.csv").write_text(
        "seed,score\n1,5.0\n2,5.2\n3,5.1\n", encoding="utf-8")
    ctx = _ctx(tmp_path)
    outcome = run_statistics(ctx)
    assert outcome.verdict == Verdict.PASS, outcome.detail
    data = _json.loads((ctx.workspace.reports_dir / "paper_metrics.json").read_text())
    means = sorted(round(m["mean"], 1) for m in data["metrics"].values())
    assert means == [1.1, 5.1], means  # no last-write-wins loss
    keys = list(data["metrics"])
    assert any(k.startswith("results/a__b__") for k in keys), keys
    assert any(k.startswith("results/a/b__") for k in keys), keys


def test_gap012_a_n2_symlinked_dir_escape_is_visible(tmp_path):
    """A-N2: a symlinked data dir inside results/ is never traversed AND the
    exclusion is audit-visible (previously: silently absent)."""
    outside = tmp_path.parent / "outside_gap012_n2"
    outside.mkdir(exist_ok=True)
    (outside / "leak.csv").write_text("seed,score\n1,9.9\n2,9.8\n", encoding="utf-8")
    (tmp_path / "results").mkdir(exist_ok=True)
    (tmp_path / "results" / "linkdir").symlink_to(outside, target_is_directory=True)
    (tmp_path / "results" / "ok.csv").write_text(
        "seed,score\n1,0.5\n2,0.7\n3,0.6\n", encoding="utf-8")
    ctx = _ctx(tmp_path)
    outcome = run_statistics(ctx)
    assert outcome.verdict == Verdict.PASS, outcome.detail
    data = _json.loads((ctx.workspace.reports_dir / "paper_metrics.json").read_text())
    assert {m["source"] for m in data["metrics"].values()} == {"results/ok.csv"}
    excl = _json.dumps(data["audit"]["exclusions"])
    assert "linkdir" in excl  # escape or not-traversed: visible either way


def test_gap012_a_n3_tableless_sqlite_is_visible(tmp_path):
    """A-N3: an empty SQLite store leaves an audit trace."""
    runs = tmp_path / "runs"
    runs.mkdir()
    _sqlite3.connect(runs / "empty.db").close()
    ctx = _ctx(tmp_path)
    outcome = run_statistics(ctx)
    assert outcome.verdict == Verdict.DEGRADED
    excl = _json.dumps(_audit(ctx)["exclusions"])
    assert "empty.db" in excl and "no user tables" in excl


def test_gap012_a_n4_wal_digest_covers_journal(tmp_path):
    """A-N4: with a live WAL, the source digest covers db+wal (the bytes the
    metrics were actually derived from), and says so."""
    runs = tmp_path / "runs"
    runs.mkdir()
    db = runs / "live.sqlite"
    con = _sqlite3.connect(db)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE t (grp TEXT, val REAL)")
    con.executemany("INSERT INTO t VALUES ('a', ?)", [(float(i),) for i in range(3)])
    con.commit()
    hold = _sqlite3.connect(db)  # keep the WAL hot
    hold.execute("BEGIN")
    hold.execute("SELECT count(*) FROM t").fetchone()
    ctx = _ctx(tmp_path)
    try:
        outcome = run_statistics(ctx)
        assert outcome.verdict == Verdict.PASS, outcome.detail
        data = _json.loads(
            (ctx.workspace.reports_dir / "paper_metrics.json").read_text())
        src = data["sources"]["runs/live.sqlite::t"]
        assert "note" in src and "-wal" in src["note"], src
        assert src["sha256"] != __import__("hashlib").sha256(
            db.read_bytes()).hexdigest(), "digest must cover more than the main file"
    finally:
        hold.rollback()
        hold.close()
        con.close()


# ---------------------------------------------------------------------------
# GAP-012 review round 3 (B-F1 field-level key collision, B-F2 dedupe order)
# ---------------------------------------------------------------------------

def test_gap012_b_f1_field_level_key_collision_keeps_both(tmp_path):
    """B-F1 (MAJOR): results/x__a.csv with column 'b' and results/x.csv with
    column 'a__b' both map to key results/x__a__b — no silent shadowing:
    both metrics survive with source-suffixed keys, visibly audited."""
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "x__a.csv").write_text(
        "seed,b\n1,1.4\n2,1.5\n3,1.6\n", encoding="utf-8")
    (tmp_path / "results" / "x.csv").write_text(
        "seed,a__b\n1,9.8\n2,9.85\n3,9.9\n", encoding="utf-8")
    ctx = _ctx(tmp_path)
    outcome = run_statistics(ctx)
    assert outcome.verdict == Verdict.PASS, outcome.detail
    data = _json.loads((ctx.workspace.reports_dir / "paper_metrics.json").read_text())
    means = sorted(round(m["mean"], 2) for m in data["metrics"].values())
    assert means == [1.5, 9.85], means  # BOTH survive
    sources = sorted(m["source"] for m in data["metrics"].values())
    assert sources == ["results/x.csv", "results/x__a.csv"], sources
    assert any("collision disambiguated" in str(e.get("reason", ""))
               for e in data["audit"]["exclusions"])


def test_gap012_b_f2_overlapping_dirs_no_double_exclusion(tmp_path):
    """B-F2: a hidden file reached via results/ AND '.' is excluded once."""
    (tmp_path / "results" / ".cache").mkdir(parents=True)
    (tmp_path / "results" / ".cache" / "h.csv").write_text(
        "seed,score\n1,0.5\n2,0.7\n3,0.6\n", encoding="utf-8")
    (tmp_path / "results" / "ok.csv").write_text(
        "seed,score\n1,0.5\n2,0.7\n3,0.6\n", encoding="utf-8")
    ctx = _ctx(tmp_path)
    ctx.config.inputs.paths = ["."]
    outcome = run_statistics(ctx)
    assert outcome.verdict == Verdict.PASS, outcome.detail
    audit = _audit(ctx)
    hits = [e for e in audit["exclusions"] if ".cache" in str(e.get("source", ""))]
    assert len(hits) == 1, hits


# ---------------------------------------------------------------------------
# GAP-012 review round 4 (A-F2 dedupe order trap, A-F1/B-NIT triple collision)
# ---------------------------------------------------------------------------

def test_gap012_a_f2_excluded_first_alias_later_still_ingests(tmp_path):
    """A-R4-F2 (MINOR): a file first seen via an excluded hidden path must
    still be ingestible via a later admissible configured alias — never
    silently dropped by early dedupe."""
    (tmp_path / "results" / ".hid").mkdir(parents=True)
    real = tmp_path / "results" / ".hid" / "real.csv"
    real.write_text("seed,score\n1,0.5\n2,0.7\n3,0.6\n", encoding="utf-8")
    # the reviewer scenario: an in-root symlinked DIRECTORY alias to the
    # hidden dir, configured explicitly via inputs.paths
    (tmp_path / "alias").symlink_to(tmp_path / "results" / ".hid",
                                    target_is_directory=True)
    ctx = _ctx(tmp_path)
    ctx.config.inputs.paths = ["alias"]
    outcome = run_statistics(ctx)
    data = _json.loads((ctx.workspace.reports_dir / "paper_metrics.json").read_text())
    # the hidden-path discovery is excluded and visible; the configured alias
    # is admissible (in-root target) and its content reaches the metrics
    assert outcome.verdict == Verdict.PASS, (outcome.detail, data["sources"])
    assert any("alias/real.csv" == s or s.endswith("alias/real.csv")
               for s in data["sources"]), data["sources"]


def test_gap012_triple_collision_all_suffixed(tmp_path):
    """A-F1/B-NIT: three sources on one base key — ALL get source suffixes,
    no bare keeper pretending to be canonical."""
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "a.csv").write_text(
        "seed,b__c\n1,1.0\n2,1.2\n3,1.1\n", encoding="utf-8")
    (tmp_path / "results" / "a__b.csv").write_text(
        "seed,c\n1,5.0\n2,5.2\n3,5.1\n", encoding="utf-8")
    db = tmp_path / "results" / "a.sqlite"
    con = _sqlite3.connect(db)
    con.execute("CREATE TABLE b (seed REAL, c REAL)")
    con.executemany("INSERT INTO b VALUES (?,?)", [(1, 9.8), (2, 9.85), (3, 9.9)])
    con.commit()
    con.close()
    ctx = _ctx(tmp_path)
    outcome = run_statistics(ctx)
    assert outcome.verdict == Verdict.PASS, outcome.detail
    data = _json.loads((ctx.workspace.reports_dir / "paper_metrics.json").read_text())
    means = sorted(round(m["mean"], 2) for m in data["metrics"].values())
    assert means == [1.1, 5.1, 9.85], means  # all three survive
    bare = [k for k in data["metrics"] if "__src" not in k]
    assert bare == [], bare  # no canonical-looking bare keeper


# ---------------------------------------------------------------------------
# GAP-013 (real pilot 2): literature queries from real project vocabulary,
# never the generic dir-name fallback ("project" → foreign works)
# ---------------------------------------------------------------------------

from paper_factory.literature.discovery import derive_queries, run_literature_discovery


def test_gap013_draft_title_and_keywords_win(tmp_path):
    (tmp_path / "draft").mkdir()
    (tmp_path / "draft" / "paper.md").write_text(
        "# Mass-Invariance in Attention\n\nkeywords: attention, renormalization\n",
        encoding="utf-8")
    ctx = _ctx(tmp_path)
    q = derive_queries(ctx)
    assert q[0] == "Mass-Invariance in Attention"
    assert any("attention" in x for x in q)


def test_gap013_readme_heading_when_no_draft(tmp_path):
    (tmp_path / "README.md").write_text("# TSCG 2.0 — Agent-Observation Compiler\n",
                                        encoding="utf-8")
    ctx = _ctx(tmp_path)
    assert derive_queries(ctx) == ["TSCG 2.0 — Agent-Observation Compiler"]


def test_gap013_config_title_parentheses_stripped(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.config.paper.title = "TSCG 2.0 — Agent-Observation Compiler (PF Pilot 2)"
    assert derive_queries(ctx) == ["TSCG 2.0 — Agent-Observation Compiler"]


def test_gap013_generic_dirname_filtered(tmp_path):
    """Pilot-2 repro: the dir name 'project' must NOT become a query."""
    generic = tmp_path / "project"
    generic.mkdir()
    ctx = _ctx(generic)
    ctx.config.paper.title = None
    assert derive_queries(ctx) == []


def test_gap013_no_vocabulary_degrades_without_api_call(tmp_path):
    """Empty query list → honest DEGRADED, no network attempt."""
    generic = tmp_path / "work"
    generic.mkdir()
    ctx = _ctx(generic)
    ctx.config.paper.title = None
    ctx.offline = False  # we test the vocabulary path, not the offline guard
    outcome = run_literature_discovery(ctx)
    assert outcome.verdict == Verdict.DEGRADED
    assert "GAP-013" in outcome.detail["reason"]


def test_gap013_real_dirname_still_works(tmp_path):
    real = tmp_path / "massinv_reopening"
    real.mkdir()
    ctx = _ctx(real)
    ctx.config.paper.title = None
    assert derive_queries(ctx) == ["massinv reopening"]


# ---------------------------------------------------------------------------
# GAP-013 review round (A-F1..F6, B: empty-pool novelty)
# ---------------------------------------------------------------------------

from paper_factory.literature.novelty import run_novelty_attack


def test_gap013_f1_prose_keywords_not_a_query(tmp_path):
    (tmp_path / "draft").mkdir()
    (tmp_path / "draft" / "paper.md").write_text(
        "# Sparse Retrieval\n\nWe describe the keywords used in our pipeline.\n",
        encoding="utf-8")
    ctx = _ctx(tmp_path)
    q = derive_queries(ctx)
    assert q == ["Sparse Retrieval"], q  # no prose leak


def test_gap013_f2_useless_title_falls_through_to_readme(tmp_path):
    (tmp_path / "draft").mkdir()
    (tmp_path / "draft" / "paper.md").write_text("# Results\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Sparse retrieval for low-resource languages\n",
                                        encoding="utf-8")
    ctx = _ctx(tmp_path)
    assert derive_queries(ctx) == ["Sparse retrieval for low-resource languages"]


def test_gap013_f3_unicode_and_abbrev_titles_survive(tmp_path):
    (tmp_path / "draft").mkdir()
    (tmp_path / "draft" / "paper.md").write_text("# 深層学習の高速化\n", encoding="utf-8")
    ctx = _ctx(tmp_path)
    assert derive_queries(ctx) == ["深層学習の高速化"]
    ctx.config.paper.title = None

    other = tmp_path / "proj2"
    (other / "draft").mkdir(parents=True)
    (other / "draft" / "paper.md").write_text("# On AI\n", encoding="utf-8")
    assert derive_queries(_ctx(other)) == ["On AI"]


def test_gap013_f4_markup_stripped(tmp_path):
    (tmp_path / "draft").mkdir()
    (tmp_path / "draft" / "paper.md").write_text(
        "# **Bold** [Sparse Retrieval](http://x.example) ##\n", encoding="utf-8")
    ctx = _ctx(tmp_path)
    assert derive_queries(ctx) == ["Bold Sparse Retrieval"]


def test_gap013_f5_content_parens_kept_tag_parens_stripped(tmp_path):
    (tmp_path / "draft").mkdir()
    (tmp_path / "draft" / "paper.md").write_text(
        "# Attention (Is All You Need)\n", encoding="utf-8")
    ctx = _ctx(tmp_path)
    assert derive_queries(ctx) == ["Attention (Is All You Need)"]
    ctx.config.paper.title = None

    other = tmp_path / "proj3"
    (other / "draft").mkdir(parents=True)
    (other / "draft" / "paper.md").write_text("# Sparse Retrieval (PF Pilot 2)\n",
                                              encoding="utf-8")
    assert derive_queries(_ctx(other)) == ["Sparse Retrieval"]


def test_gap013_f6_year_does_not_rescue_generic_title(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.config.paper.title = "My Project 2024"
    # no draft/README → config title is generic-only → falls to dir name
    q = derive_queries(ctx)
    assert "My Project 2024" not in q


def test_gap013_b_empty_pool_novelty_degrades_not_pass(tmp_path):
    """B-G13: P07 must not PASS a novelty attack against zero prior art."""
    ctx = _ctx(tmp_path)
    ctx.offline = False
    ctx.workspace.reports_dir.mkdir(parents=True, exist_ok=True)
    (ctx.workspace.reports_dir / "literature_discovery.json").write_text(
        _json.dumps({"discovered_at": "t", "queries": {}, "unique_works": {}}),
        encoding="utf-8")
    outcome = run_novelty_attack(ctx)
    assert outcome.verdict == Verdict.DEGRADED


# ---------------------------------------------------------------------------
# GAP-011: pfget label binding — the prose around a provenance macro must
# name the bound metric's field (U2 fail-closed on label mismatch)
# ---------------------------------------------------------------------------

def _g11_ctx(tmp_path, macro_key: str, field: str, sentence: str):
    """Manuscript with one pfget use + matching metrics/numbers artifacts."""
    ctx = _ctx(tmp_path)
    _write_manuscript(ctx, {"results.tex": sentence + "\n"})
    run_numbers_units_audit(ctx)
    (ctx.workspace.reports_dir / "paper_metrics.json").write_text(_json.dumps(
        {"computed_at": "t", "sources": {},
         "metrics": {macro_key: {"source": "results/x.csv", "field": field,
                                 "mean": 0.11, "n": 3}}}), encoding="utf-8")
    from paper_factory.statistics.metrics import expected_macro_entries
    entries = expected_macro_entries({macro_key: {"mean": 0.11, "n": 3}})
    gen = ctx.workspace.paper_dir / "generated"
    gen.mkdir(parents=True, exist_ok=True)
    lines = ["% generated",
             "\\makeatletter",
             "\\newcommand{\\pfget}[1]{\\ifcsname pf@#1\\endcsname\\csname pf@#1\\endcsname"
             "\\else\\textbf{??}\\fi}",
             "\\makeatother"]
    lines += [f"\\expandafter\\gdef\\csname pf@{k}\\endcsname{{{v}}}"
              for k, v in entries.items()]
    (gen / "numbers.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return ctx, entries


def test_gap011_mislabeled_pfget_use_fails(tmp_path):
    """Reviewer chain finding: 'latency improved to \\pfget{<nll-macro>}' must
    NOT pass — the value belongs to nll, the sentence says latency."""
    ctx, entries = _g11_ctx(
        tmp_path, "runs__exp__nll", "nll",
        "The latency improved to $\\pfget{runsexp nllmean}$.".replace("runsexp nll", "runsexpnll"))
    # sanity: the macro used must exist in generated entries
    mean_macro = next(k for k in entries if k.endswith("mean"))
    _write_manuscript(ctx, {"results.tex":
                            f"The latency improved to $\\pfget{{{mean_macro}}}$.\n"})
    run_numbers_units_audit(ctx)
    _, states = _closure_states(ctx)
    assert states["U2"] == "FAIL", states


def test_gap011_correctly_labeled_pfget_use_passes(tmp_path):
    ctx, entries = _g11_ctx(
        tmp_path, "runs__exp__nll", "nll", "placeholder")
    mean_macro = next(k for k in entries if k.endswith("mean"))
    _write_manuscript(ctx, {"results.tex":
                            f"The nll improved to $\\pfget{{{mean_macro}}}$.\n"})
    run_numbers_units_audit(ctx)
    _, states = _closure_states(ctx)
    assert states["U2"] == "PASS", states


def test_gap011_alias_labels_pass(tmp_path):
    """Field aliases count as naming: 'negative log-likelihood' names nll."""
    ctx, entries = _g11_ctx(
        tmp_path, "runs__exp__nll", "nll", "placeholder")
    mean_macro = next(k for k in entries if k.endswith("mean"))
    _write_manuscript(ctx, {"results.tex":
                            f"The negative log-likelihood dropped to "
                            f"$\\pfget{{{mean_macro}}}$.\n"})
    run_numbers_units_audit(ctx)
    _, states = _closure_states(ctx)
    assert states["U2"] == "PASS", states


def test_gap011_metric_without_field_skips_label_check(tmp_path):
    """Legacy metrics without a 'field' key are unaffected (unbound checks
    still apply — only the label check is skipped)."""
    ctx, entries = _g11_ctx(
        tmp_path, "realkey", "", "placeholder")
    mean_macro = next(k for k in entries if k.endswith("mean"))
    _write_manuscript(ctx, {"results.tex": f"The value is $\\pfget{{{mean_macro}}}$.\n"})
    run_numbers_units_audit(ctx)
    _, states = _closure_states(ctx)
    assert states["U2"] == "PASS", states


def test_gap011_compose_output_label_binds(tmp_path):
    """The deterministic composer names the metric key (which contains the
    field) next to every pfget use — compose output must pass GAP-011."""
    from paper_factory.manuscript.compose import _compose_section
    ctx = _ctx(tmp_path)
    results = tmp_path / "results"
    results.mkdir()
    rows = ["seed,load,fpr"]
    for seed in (42, 43, 44):
        for load in ("0.90", "0.95"):
            rows.append(f"{seed},{load},{0.01 + seed * 1e-4 + float(load):.6f}")
    (results / "data.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    assert run_statistics(ctx).verdict == Verdict.PASS
    text = _compose_section("results", ctx)
    sections = ctx.workspace.paper_dir / "sections"
    sections.mkdir(parents=True, exist_ok=True)
    (sections / "results.tex").write_text(text, encoding="utf-8")
    run_numbers_units_audit(ctx)
    _, states = _closure_states(ctx)
    assert states["U2"] == "PASS", states


# ---------------------------------------------------------------------------
# GAP-011 review round (B-a nearest-anchor attribution, B-e group binding,
# A-F-A camelcase fields, B-c skip visibility)
# ---------------------------------------------------------------------------

def _g11_grouped_ctx(tmp_path, sentence: str):
    """Two groups of the same metric (fpr at load 0.90 / 0.95), real P09 path."""
    ctx = _ctx(tmp_path)
    results = tmp_path / "results"
    results.mkdir()
    rows = ["seed,load,fpr"]
    for seed in (42, 43, 44):
        for load in ("0.90", "0.95"):
            rows.append(f"{seed},{load},{0.01 + seed * 1e-4 + float(load):.6f}")
    (results / "data.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    assert run_statistics(ctx).verdict == Verdict.PASS
    _write_manuscript(ctx, {"results.tex": sentence + "\n"})
    run_numbers_units_audit(ctx)
    return ctx


def _macro_for(metrics, field, group_val):
    from paper_factory.statistics.metrics import macro_base_names
    keys = [k for k, v in metrics.items()
            if v["field"] == field
            and str({**(v.get("group") or {}),
                     **(v.get("fixed_design") or {})}.get("load")) == group_val]
    assert keys, (field, group_val, list(metrics))
    return macro_base_names(list(metrics.keys()))[keys[0]] + "mean"


def test_gap011_b_a_nearest_anchor_attribution(tmp_path):
    """B-a (MAJOR): 'The latency reaches \\pfget{<nll-macro>} and the loss is
    fine' — with BOTH fields as metrics, the nearest mention to the macro is
    'latency', not the macro's own field 'nll'."""
    ctx = _ctx(tmp_path)
    _write_manuscript(ctx, {"results.tex": "placeholder\n"})
    (ctx.workspace.reports_dir / "paper_metrics.json").write_text(_json.dumps(
        {"computed_at": "t", "sources": {},
         "metrics": {"runs__exp__nll": {"source": "results/x.csv", "field": "nll",
                                        "mean": 5.0, "n": 3},
                     "runs__exp__latency": {"source": "results/x.csv",
                                            "field": "latency", "mean": 1.0, "n": 3}}}),
        encoding="utf-8")
    from paper_factory.statistics.metrics import expected_macro_entries
    entries = expected_macro_entries(
        {"runs__exp__nll": {"mean": 5.0, "n": 3},
         "runs__exp__latency": {"mean": 1.0, "n": 3}})
    gen = ctx.workspace.paper_dir / "generated"
    gen.mkdir(parents=True, exist_ok=True)
    lines = ["% generated", "\\makeatletter",
             "\\newcommand{\\pfget}[1]{\\ifcsname pf@#1\\endcsname\\csname pf@#1\\endcsname"
             "\\else\\textbf{??}\\fi}", "\\makeatother"]
    lines += [f"\\expandafter\\gdef\\csname pf@{k}\\endcsname{{{v}}}"
              for k, v in entries.items()]
    (gen / "numbers.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")
    nll_macro = next(k for k in entries if k.startswith("runsexpnll") and k.endswith("mean"))
    _write_manuscript(ctx, {"results.tex":
                            f"The latency reaches $\\pfget{{{nll_macro}}}$ "
                            "and the loss is fine.\n"})
    run_numbers_units_audit(ctx)
    _, states = _closure_states(ctx)
    assert states["U2"] == "FAIL", states


def test_gap011_b_e_wrong_group_macro_fails(tmp_path):
    """B-e (MAJOR): 'the fpr at load 0.9' citing the load-0.95 macro."""
    ctx = _g11_grouped_ctx(tmp_path, "placeholder")
    metrics = _json.loads(
        (ctx.workspace.reports_dir / "paper_metrics.json").read_text())["metrics"]
    macro095 = _macro_for(metrics, "fpr", "0.95")
    _write_manuscript(ctx, {"results.tex":
                            f"The fpr at load 0.9 is $\\pfget{{{macro095}}}$.\n"})
    run_numbers_units_audit(ctx)
    _, states = _closure_states(ctx)
    assert states["U2"] == "FAIL", states


def test_gap011_b_e_right_group_macro_passes(tmp_path):
    ctx = _g11_grouped_ctx(tmp_path, "placeholder")
    metrics = _json.loads(
        (ctx.workspace.reports_dir / "paper_metrics.json").read_text())["metrics"]
    macro090 = _macro_for(metrics, "fpr", "0.90")
    _write_manuscript(ctx, {"results.tex":
                            f"The fpr at load 0.9 is $\\pfget{{{macro090}}}$.\n"})
    run_numbers_units_audit(ctx)
    _, states = _closure_states(ctx)
    assert states["U2"] == "PASS", states


def test_gap011_no_group_in_context_is_fine(tmp_path):
    """No design point named → no group requirement."""
    ctx = _g11_grouped_ctx(tmp_path, "placeholder")
    metrics = _json.loads(
        (ctx.workspace.reports_dir / "paper_metrics.json").read_text())["metrics"]
    macro095 = _macro_for(metrics, "fpr", "0.95")
    _write_manuscript(ctx, {"results.tex":
                            f"Across conditions the fpr stayed low, e.g. $\\pfget{{{macro095}}}$.\n"})
    run_numbers_units_audit(ctx)
    _, states = _closure_states(ctx)
    assert states["U2"] == "PASS", states


def test_gap011_a_camelcase_field_namable_in_prose(tmp_path):
    """A-F-A: field 'falsePositiveRate' is namable as 'false positive rate'."""
    ctx, entries = _g11_ctx(tmp_path, "runs__exp__falsePositiveRate",
                            "falsePositiveRate", "placeholder")
    mean_macro = next(k for k in entries if k.endswith("mean"))
    _write_manuscript(ctx, {"results.tex":
                            f"The false positive rate dropped to $\\pfget{{{mean_macro}}}$.\n"})
    run_numbers_units_audit(ctx)
    _, states = _closure_states(ctx)
    assert states["U2"] == "PASS", states


# ---------------------------------------------------------------------------
# GAP-011 review round 2 (A-R2-1 dim-token fields, B-r1/r2 unmeasured design
# points, A-R2-2 enumeration exception)
# ---------------------------------------------------------------------------

def test_gap011_dim_token_field_compose_closes(tmp_path):
    """A-R2-1 (MAJOR): a 'score' outcome column must be closable — the field
    names itself when dim-token filtering would strip everything."""
    from paper_factory.manuscript.compose import _compose_section
    ctx = _ctx(tmp_path)
    results = tmp_path / "results"
    results.mkdir()
    rows = ["seed,method,score"]
    for seed in (1, 2, 3):
        for meth in ("a", "b"):
            rows.append(f"{seed},{meth},{0.5 + seed * 0.01 + (0.2 if meth == 'b' else 0):.4f}")
    (results / "data.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    assert run_statistics(ctx).verdict == Verdict.PASS
    text = _compose_section("results", ctx)
    sections = ctx.workspace.paper_dir / "sections"
    sections.mkdir(parents=True, exist_ok=True)
    (sections / "results.tex").write_text(text, encoding="utf-8")
    run_numbers_units_audit(ctx)
    _, states = _closure_states(ctx)
    assert states["U2"] == "PASS", states


def test_gap011_b_r1_unmeasured_design_point_without_sibling_fails(tmp_path):
    """B-r1: only load 0.95 measured; text claims 'at load 0.9' → FAIL even
    though no sibling group exists."""
    ctx = _ctx(tmp_path)
    results = tmp_path / "results"
    results.mkdir()
    rows = ["seed,load,fpr"] + [f"{s},0.95,{0.01 + s * 1e-4:.6f}" for s in (42, 43, 44)]
    (results / "data.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    assert run_statistics(ctx).verdict == Verdict.PASS
    metrics = _json.loads(
        (ctx.workspace.reports_dir / "paper_metrics.json").read_text())["metrics"]
    macro = _macro_for(metrics, "fpr", "0.95")
    _write_manuscript(ctx, {"results.tex":
                            f"The fpr at load 0.9 is $\\pfget{{{macro}}}$.\n"})
    run_numbers_units_audit(ctx)
    _, states = _closure_states(ctx)
    assert states["U2"] == "FAIL", states


def test_gap011_b_r2_unknown_design_point_among_siblings_fails(tmp_path):
    """B-r2: groups 0.90/0.95 measured; text claims 'at load 0.7' → FAIL."""
    ctx = _g11_grouped_ctx(tmp_path, "placeholder")
    metrics = _json.loads(
        (ctx.workspace.reports_dir / "paper_metrics.json").read_text())["metrics"]
    macro090 = _macro_for(metrics, "fpr", "0.90")
    _write_manuscript(ctx, {"results.tex":
                            f"The fpr at load 0.7 is $\\pfget{{{macro090}}}$.\n"})
    run_numbers_units_audit(ctx)
    _, states = _closure_states(ctx)
    assert states["U2"] == "FAIL", states


def test_gap011_a_r2_2_enumeration_passes(tmp_path):
    """A-R2-2: 'The fpr and latency both improved: \\pfget{fpr} and
    \\pfget{latency}' — enumeration, each mention owned by its own macro."""
    ctx = _ctx(tmp_path)
    results = tmp_path / "results"
    results.mkdir()
    rows = ["seed,fpr,latency"] + [f"{s},{0.01 + s * 1e-4:.6f},{1.0 + s * 0.01:.4f}"
                                   for s in (42, 43, 44)]
    (results / "data.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    assert run_statistics(ctx).verdict == Verdict.PASS
    metrics = _json.loads(
        (ctx.workspace.reports_dir / "paper_metrics.json").read_text())["metrics"]
    from paper_factory.statistics.metrics import macro_base_names
    bases = macro_base_names(list(metrics.keys()))
    fpr_m = bases[next(k for k, v in metrics.items() if v["field"] == "fpr")] + "mean"
    lat_m = bases[next(k for k, v in metrics.items() if v["field"] == "latency")] + "mean"
    _write_manuscript(ctx, {"results.tex":
                            f"The fpr and latency both improved: $\\pfget{{{fpr_m}}}$ "
                            f"and $\\pfget{{{lat_m}}}$ respectively.\n"})
    run_numbers_units_audit(ctx)
    _, states = _closure_states(ctx)
    assert states["U2"] == "PASS", states


# ---------------------------------------------------------------------------
# GAP-011 review round 3 (A-R3-1: design points attribute to nearest carrier
# macro; enumerations and prior-work references are not macro claims)
# ---------------------------------------------------------------------------

def _g11_grouped_ctx_1dec(tmp_path, sentence: str):
    """Same as _g11_grouped_ctx but with single-decimal design points
    (0.9/1.0) — P22's raw-decimal gate flags 2+-decimal literals in
    manuscripts, which is orthogonal to GAP-011 (label/group binding)."""
    ctx = _ctx(tmp_path)
    results = tmp_path / "results"
    results.mkdir(parents=True)
    rows = ["seed,load,fpr"]
    for seed in (42, 43, 44):
        for load in ("0.9", "1.0"):
            rows.append(f"{seed},{load},{0.01 + seed * 1e-4 + float(load):.6f}")
    (results / "data.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    assert run_statistics(ctx).verdict == Verdict.PASS
    _write_manuscript(ctx, {"results.tex": sentence + "\n"})
    run_numbers_units_audit(ctx)
    return ctx


def test_gap011_r3_canonical_comparison_sentence_passes(tmp_path):
    """A-R3-1 (MAJOR): 'The fpr at load 0.9 is \\pfget{F09} and at load 1.0
    it is \\pfget{F10}' — the canonical comparison must pass."""
    ctx = _g11_grouped_ctx_1dec(tmp_path, "placeholder")
    metrics = _json.loads(
        (ctx.workspace.reports_dir / "paper_metrics.json").read_text())["metrics"]
    m09 = _macro_for(metrics, "fpr", "0.9")
    m10 = _macro_for(metrics, "fpr", "1.0")
    _write_manuscript(ctx, {"results.tex":
                            f"The fpr at load 0.9 is $\\pfget{{{m09}}}$ and at "
                            f"load 1.0 it is $\\pfget{{{m10}}}$.\n"})
    run_numbers_units_audit(ctx)
    _, states = _closure_states(ctx)
    assert states["U2"] == "PASS", states


def test_gap011_r3_design_space_enumeration_passes(tmp_path):
    """'We cover loads 0.9 and 1.0; at load 1.0 the fpr is …' — enumeration
    is not a macro claim."""
    ctx = _g11_grouped_ctx_1dec(tmp_path, "placeholder")
    metrics = _json.loads(
        (ctx.workspace.reports_dir / "paper_metrics.json").read_text())["metrics"]
    m10 = _macro_for(metrics, "fpr", "1.0")
    _write_manuscript(ctx, {"results.tex":
                            f"We cover loads 0.9 and 1.0; at load 1.0 the fpr "
                            f"is $\\pfget{{{m10}}}$.\n"})
    run_numbers_units_audit(ctx)
    _, states = _closure_states(ctx)
    assert states["U2"] == "PASS", states


def test_gap011_r3_prior_work_design_point_passes(tmp_path):
    """A foreign protocol's design point near a correct macro is not the
    macro's claim."""
    ctx = _g11_grouped_ctx_1dec(tmp_path, "placeholder")
    metrics = _json.loads(
        (ctx.workspace.reports_dir / "paper_metrics.json").read_text())["metrics"]
    m10 = _macro_for(metrics, "fpr", "1.0")
    _write_manuscript(ctx, {"results.tex":
                            f"Following the load 2.0 protocol of prior work, the "
                            f"fpr at load 1.0 is $\\pfget{{{m10}}}$.\n"})
    run_numbers_units_audit(ctx)
    _, states = _closure_states(ctx)
    assert states["U2"] == "PASS", states


# ---------------------------------------------------------------------------
# GAP-011 review round 4 (B-W1 decoy carrier, B-W2 ref-cue laundering,
# B-W3 enumeration hiding unmeasured, B-W4 plural single-value evasion)
# ---------------------------------------------------------------------------

def test_gap011_b_w1_cross_field_decoy_does_not_steal_attribution(tmp_path):
    """W1: a latency macro (group 0.9) parked next to the number must not
    absorb the design-point check for the fpr macro (group 0.95)."""
    ctx = _ctx(tmp_path)
    results = tmp_path / "results"
    results.mkdir()
    rows = ["seed,load,fpr,latency"]
    for seed in (42, 43, 44):
        for load in ("0.9", "1.0"):
            rows.append(f"{seed},{load},{0.01 + seed * 1e-4 + float(load):.6f},"
                        f"{1.0 + seed * 0.01 + float(load):.4f}")
    (results / "data.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    assert run_statistics(ctx).verdict == Verdict.PASS
    metrics = _json.loads(
        (ctx.workspace.reports_dir / "paper_metrics.json").read_text())["metrics"]
    lat09 = _macro_for(metrics, "latency", "0.9")
    fpr10 = _macro_for(metrics, "fpr", "1.0")
    _write_manuscript(ctx, {"results.tex":
                            f"At load 0.9 ($\\pfget{{{lat09}}}$ for latency) "
                            f"the fpr is $\\pfget{{{fpr10}}}$.\n"})
    run_numbers_units_audit(ctx)
    _, states = _closure_states(ctx)
    assert states["U2"] == "FAIL", states  # fpr at load 0.9 cited with 1.0 value


def test_gap011_b_w2_ref_cue_needs_own_point_named(tmp_path):
    """W2: 'following the load 0.9 protocol of prior work, our fpr is
    \\pfget{<1.0>}' — the cue must not launder a claim that never names its
    own design point."""
    ctx = _g11_grouped_ctx_1dec(tmp_path, "placeholder")
    metrics = _json.loads(
        (ctx.workspace.reports_dir / "paper_metrics.json").read_text())["metrics"]
    fpr10 = _macro_for(metrics, "fpr", "1.0")
    _write_manuscript(ctx, {"results.tex":
                            f"Following the load 0.9 protocol of prior work, "
                            f"our fpr is $\\pfget{{{fpr10}}}$.\n"})
    run_numbers_units_audit(ctx)
    _, states = _closure_states(ctx)
    assert states["U2"] == "FAIL", states


def test_gap011_b_w3_enumeration_with_unmeasured_point_fails(tmp_path):
    """W3: 'at load 0.9 and 2.0 is \\pfget{<0.9>}' — the enumerated 2.0 is
    unmeasured; the enumeration form must not hide it."""
    ctx = _g11_grouped_ctx_1dec(tmp_path, "placeholder")
    metrics = _json.loads(
        (ctx.workspace.reports_dir / "paper_metrics.json").read_text())["metrics"]
    fpr09 = _macro_for(metrics, "fpr", "0.9")
    _write_manuscript(ctx, {"results.tex":
                            f"The fpr at load 0.9 and 2.0 is $\\pfget{{{fpr09}}}$.\n"})
    run_numbers_units_audit(ctx)
    _, states = _closure_states(ctx)
    assert states["U2"] == "FAIL", states


def test_gap011_b_w4_plural_single_value_evasion_fails(tmp_path):
    """W4: 'at loads 0.9 is \\pfget{<1.0>}' — plural marker with a single
    value must not deactivate the check."""
    ctx = _g11_grouped_ctx_1dec(tmp_path, "placeholder")
    metrics = _json.loads(
        (ctx.workspace.reports_dir / "paper_metrics.json").read_text())["metrics"]
    fpr10 = _macro_for(metrics, "fpr", "1.0")
    _write_manuscript(ctx, {"results.tex":
                            f"The fpr at loads 0.9 is $\\pfget{{{fpr10}}}$.\n"})
    run_numbers_units_audit(ctx)
    _, states = _closure_states(ctx)
    assert states["U2"] == "FAIL", states


# ---------------------------------------------------------------------------
# GAP-011 review round 5 (B-Y1 hyphen range, B-Y2 adverb chain break,
# A-F1 chain decimals vs clause scan)
# ---------------------------------------------------------------------------

def _w_case(tmp_path, sentence):
    ctx = _g11_grouped_ctx_1dec(tmp_path, "placeholder")
    metrics = _json.loads(
        (ctx.workspace.reports_dir / "paper_metrics.json").read_text())["metrics"]
    fpr09 = _macro_for(metrics, "fpr", "0.9")
    _write_manuscript(ctx, {"results.tex": sentence.format(m=fpr09) + "\n"})
    run_numbers_units_audit(ctx)
    return _closure_states(ctx)[1]


def test_gap011_b_y1_hyphen_range_does_not_hide_unmeasured(tmp_path):
    """'at load 0.9-2.0 is \\pfget{<0.9>}' — the hyphen-linked 2.0 is
    unmeasured and must surface (unicode dashes normalize to '-')."""
    for i, form in enumerate(("The fpr at load 0.9-2.0 is $\\pfget{{{m}}}$.",
                 "The fpr at load 0.9–2.0 is $\\pfget{{{m}}}$.",
                 "The fpr at load 0.9—2.0 is $\\pfget{{{m}}}$.")):
        states = _w_case(tmp_path / f"y1_{i}", form)
        assert states["U2"] == "FAIL", (form, states)


def test_gap011_b_y2_adverb_chain_break_does_not_hide(tmp_path):
    """'at load 0.9 and also 2.0' — the adverb must not break the chain."""
    states = _w_case(tmp_path, "The fpr at load 0.9 and also 2.0 is $\\pfget{{m}}$.")
    assert states["U2"] == "FAIL", states


def test_gap011_a_f1_chain_decimals_do_not_poison_clause_scan(tmp_path):
    """A-F1: 'at load 0.9 and 1.0' (claim role) must judge identically to
    integer points — the chain's decimals are not clause boundaries."""
    states = _w_case(tmp_path, "The fpr at load 0.9 and 1.0 is $\\pfget{{m}}$.")
    assert states["U2"] == "FAIL", states  # 1.0 is a sibling in CLAIM role


def test_gap011_negative_design_value_keeps_sign(tmp_path):
    """B-R6 MINOR: 'at load -1' must read as -1, not 1 — a matching negative
    group passes, a wrong one fails."""
    ctx = _ctx(tmp_path)
    results = tmp_path / "results"
    results.mkdir()
    rows = ["seed,load,fpr"]
    for seed in (42, 43, 44):
        for load in ("-1.0", "1.0"):
            rows.append(f"{seed},{load},{0.01 + seed * 1e-4 + abs(float(load)) * 0.1:.6f}")
    (results / "data.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    assert run_statistics(ctx).verdict == Verdict.PASS
    metrics = _json.loads(
        (ctx.workspace.reports_dir / "paper_metrics.json").read_text())["metrics"]
    m_neg = _macro_for(metrics, "fpr", "-1.0")
    _write_manuscript(ctx, {"results.tex":
                            f"The fpr at load -1 is $\\pfget{{{m_neg}}}$.\n"})
    run_numbers_units_audit(ctx)
    _, states = _closure_states(ctx)
    assert states["U2"] == "PASS", states


# ---------------------------------------------------------------------------
# GAP-3x (real pilot 3): claim vocabulary too narrow (comparative-only) —
# audit/measurement papers extract ZERO claims; markdown reference lists in
# drafts never become a bibliography (P15/P21 DEGRADED, P32 bib_exists FAIL)
# ---------------------------------------------------------------------------

from paper_factory.claims.builder import _clean_for_extraction, _extract_candidates

_P3_DRAFT_STYLE = (
    "Cadence-based structural arithmetic classifies 766,771,200 of "
    "1,020,057,600 scalar coordinates (75.17%) as unreachable.\n"
    "The audit reports that 0 of 168 target gate-scope tensors were owned by Muon.\n"
    "The held-out suite shows 3 true positives and 9 true negatives.\n"
    "The sweep covers 19 attestations across 7 configurations.\n"
    "We discuss related work without numbers.\n")


def test_gap_p3_measurement_verbs_yield_claims():
    """Pilot-3 repro: 'classifies N of M', 'reports 0 of 168', 'shows 3 TP' —
    measurement/audit rhetoric must produce candidates."""
    cands = _extract_candidates(_clean_for_extraction(_P3_DRAFT_STYLE))
    joined = " ".join(c for _, c in cands)
    assert "766,771,200" in joined, cands
    assert "0 of 168" in joined, cands
    assert len(cands) >= 3, cands


def test_gap_p3_numberless_prose_still_not_a_claim():
    cands = _extract_candidates(
        _clean_for_extraction("We discuss related work and future directions."))
    assert cands == []


from paper_factory.literature.draft_refs import parse_markdown_refs

_P3_REFS = """
# References

\\[1\\] Adam Smith and Jane Doe. Mass invariance in conditional networks.
arXiv preprint arXiv:2401.01234, 2024. URL https://arxiv.org/abs/2401.01234.

\\[17\\] PyTorch Contributors. Adam optimizer documentation (PyTorch 2.8).
https://docs.pytorch.org/docs/2.8/generated/torch.optim.Adam.html, 2026.
"""


def test_gap_p3_markdown_refs_parse_to_bib():
    bib = parse_markdown_refs(_P3_REFS)
    assert bib.count("@") == 2, bib
    assert "2401.01234" in bib
    assert "parsed from draft reference list" in bib  # T4 provenance marker
    # entries survive the verifier's own parser
    import tempfile
    from paper_factory.literature.verify import parse_bib
    p = Path(tempfile.mkdtemp()) / "refs.bib"
    p.write_text(bib, encoding="utf-8")
    entries = parse_bib(p)
    assert len(entries) == 2
    assert entries[0]["title"] and "Mass invariance" in entries[0]["title"]


def test_gap_p3_draft_refs_wire_into_bibliography_nodes(tmp_path):
    """With no .bib anywhere, the draft reference list feeds P15/P21/P32."""
    from paper_factory.literature.verify import build_references, run_citation_audit
    (tmp_path / "draft").mkdir()
    (tmp_path / "draft" / "paper.md").write_text(
        "# Title\n\nSome text.\n\n" + _P3_REFS, encoding="utf-8")
    ctx = _ctx(tmp_path)
    out_build = build_references(ctx)
    assert out_build.verdict == Verdict.PASS, out_build.detail
    assert (ctx.workspace.paper_dir / "references.bib").exists()
    out_audit = run_citation_audit(ctx)  # offline ctx: audit degrades, not missing
    assert out_audit.verdict == Verdict.DEGRADED
    assert "no bibliography" not in str(out_audit.detail)


# ---------------------------------------------------------------------------
# GAP-3x review round (B-P3-1 stale derived bib, A-F2 author split,
# A-F3 bare DOI, A-F4 duplicate markers, A-F6 self-refresh, B-c T4 visibility)
# ---------------------------------------------------------------------------

def test_gap_p3_r2_real_bib_displaces_derived(tmp_path):
    """B-P3-1 (MAJOR): when a real .bib arrives, the derived file must leave
    the glob (versioned, not deleted) and the chain must see only the real
    key."""
    from paper_factory.literature.draft_refs import ensure_draft_bib
    from paper_factory.literature.verify import build_references
    (tmp_path / "draft").mkdir()
    (tmp_path / "draft" / "paper.md").write_text(
        "# T\n\ntext\n\n" + _P3_REFS, encoding="utf-8")
    ctx = _ctx(tmp_path)
    derived = ensure_draft_bib(tmp_path)
    assert derived is not None and derived.exists()
    # real bib arrives
    (tmp_path / "literature" / "real.bib").write_text(
        "@article{realkey, title={Real}, year={2024}}\n", encoding="utf-8")
    assert ensure_draft_bib(tmp_path) is None
    assert not derived.exists()
    assert list((tmp_path / "literature").glob("parsed_from_draft.bib.v1.*")), \
        "displaced derived bib must be versioned, not deleted"
    out = build_references(ctx)
    assert out.verdict == Verdict.PASS
    built = (ctx.workspace.paper_dir / "references.bib").read_text()
    assert "realkey" in built and "draftref" not in built


def test_gap_p3_r2_derived_self_refreshes_on_draft_edit(tmp_path):
    """A-F6: editing the draft reference list regenerates the derived bib
    (old content versioned)."""
    from paper_factory.literature.draft_refs import ensure_draft_bib
    (tmp_path / "draft").mkdir()
    d = tmp_path / "draft" / "paper.md"
    d.write_text("# T\n\ntext\n\n" + _P3_REFS, encoding="utf-8")
    first = ensure_draft_bib(tmp_path).read_text()
    d.write_text(d.read_text().replace("Mass invariance", "Mass Variance"),
                 encoding="utf-8")
    second = ensure_draft_bib(tmp_path).read_text()
    assert "Mass Variance" in second and first != second
    assert list((tmp_path / "literature").glob("parsed_from_draft.bib.v1.*"))


def test_gap_p3_r2_initials_author_title_split():
    """A-F2: 'Doe, K. and Roe, L. Another study.' → authors keep initials,
    title clean."""
    from paper_factory.literature.draft_refs import parse_markdown_refs
    bib = parse_markdown_refs(
        "# References\n\n\\[1\\] Doe, K. and Roe, L. Another study on things. "
        "Journal of X, 2024. URL https://arxiv.org/abs/2401.01234.\n")
    assert "author = {Doe, K. and Roe, L}" in bib, bib
    assert "title = {Another study on things" in bib, bib


def test_gap_p3_r2_bare_doi_and_duplicate_markers():
    """A-F3/F4: bare 'doi:10.xxxx/yy' is extracted; duplicate [N] markers get
    suffixed keys, never duplicates."""
    from paper_factory.literature.draft_refs import parse_markdown_refs
    bib = parse_markdown_refs(
        "# References\n\n"
        "\\[3\\] A. First study on topics. J. X, 2023. doi:10.5555/abc.123.\n\n"
        "\\[3\\] B. Second study on topics. J. Y, 2024. "
        "URL https://arxiv.org/abs/2402.00001.\n")
    assert "doi = {10.5555/abc.123}" in bib, bib
    assert "draftref3," in bib and "draftref3b," in bib, bib
    import tempfile
    from paper_factory.literature.verify import parse_bib
    p = Path(tempfile.mkdtemp()) / "r.bib"
    p.write_text(bib, encoding="utf-8")
    keys = [e["key"] for e in parse_bib(p)]
    assert len(keys) == len(set(keys)) == 2


def test_gap_p3_r2_t4_flag_in_citation_audit(tmp_path):
    """B-c: entries from the derived bib carry t4_derived=True in the audit
    records, not just in the filename."""
    from paper_factory.literature.verify import run_citation_audit
    (tmp_path / "draft").mkdir()
    (tmp_path / "draft" / "paper.md").write_text(
        "# T\n\ntext\n\n" + _P3_REFS, encoding="utf-8")
    ctx = _ctx(tmp_path)  # offline → DEGRADED with per-entry records
    out = run_citation_audit(ctx)
    assert out.verdict == Verdict.DEGRADED
    audit = _json.loads(
        (ctx.workspace.reports_dir / "citation_audit.json").read_text())
    assert audit["entries"], audit
    assert all(e.get("t4_derived") is True for e in audit["entries"])


# ---------------------------------------------------------------------------
# GAP-3x review round 3 (B R2-F1 unverifiable T4 citations vs U4 "resolve",
# B R2-F2 note-bound t4 flag, A R2 N-A arXiv old-style, N-B refs-section cut,
# N-C markdown table/heading debris, N-D same-second rename collision)
# ---------------------------------------------------------------------------

def _ctx_online(tmp_path: Path) -> NodeContext:
    """Audit executes (not offline). Safe in tests only for entries WITHOUT
    resolvable identifiers — no-DOI entries never touch the network."""
    ctx = _ctx(tmp_path)
    ctx.offline = False
    return ctx


def test_gap_p3_r3_unverifiable_t4_blocks_u4(tmp_path):
    """B R2-F1 (MAJOR): hallucinated draft references without DOI must NOT
    reach U4 PASS 'all citations resolve'. The derived-bib bridge turned
    'no bibliography → blocked' into 'PASS with MINOR no_doi' — the closure
    attested resolution for citations nothing ever verified."""
    from paper_factory.literature.verify import run_citation_audit
    from paper_factory.release.closure import _u4
    (tmp_path / "draft").mkdir()
    (tmp_path / "draft" / "paper.md").write_text(
        "# T\n\ntext\n\n# References\n\n"
        "\\[1\\] Invented, A. A totally fabricated study on nothing at all. "
        "Journal of Nowhere, 2024.\n\n"
        "\\[2\\] Madeup, B. Another invented result on everything. "
        "Conf. Fake, 2025.\n",
        encoding="utf-8")
    ctx = _ctx_online(tmp_path)
    out = run_citation_audit(ctx)
    assert out.verdict == Verdict.DEGRADED, out.detail
    audit = _json.loads(
        (ctx.workspace.reports_dir / "citation_audit.json").read_text())
    assert all(f["kind"] == "unverifiable_citation" and f["severity"] == "MAJOR"
               for f in audit["findings"]), audit["findings"]
    state, note = _u4(ctx)
    assert state == "DEGRADED", (state, note)
    assert "unverifiable" in note.lower()


def test_gap_p3_r3_u4_no_findings_only_then_resolve_claim(tmp_path):
    """The note may claim 'all citations resolve' ONLY with zero findings."""
    from paper_factory.release.closure import _u4
    ctx = _ctx_online(tmp_path)
    ctx.workspace.reports_dir.mkdir(parents=True, exist_ok=True)
    (ctx.workspace.reports_dir / "citation_audit.json").write_text(_json.dumps({
        "offline": False, "entries": [{"key": "ok", "verdict": "VERIFIED"}],
        "findings": []}))
    state, note = _u4(ctx)
    assert state == "PASS" and "all citations resolve" in note


def test_gap_p3_r3_real_bib_no_doi_honest_note(tmp_path):
    """A real-bib entry without DOI (book/tech report) stays MINOR — U4 PASS,
    but the note must scope the claim instead of a blanket 'all resolve'."""
    from paper_factory.release.closure import _u4
    ctx = _ctx_online(tmp_path)
    ctx.workspace.reports_dir.mkdir(parents=True, exist_ok=True)
    (ctx.workspace.reports_dir / "citation_audit.json").write_text(_json.dumps({
        "offline": False, "entries": [{"key": "book1", "verdict": "NO_DOI"}],
        "findings": [{"severity": "MINOR", "kind": "no_doi", "key": "book1"}]}))
    state, note = _u4(ctx)
    assert state == "PASS"
    assert "not resolvable" in note
    assert "all citations resolve" not in note


def test_gap_p3_r3_u4_unverifiable_network_degraded(tmp_path):
    """Same false-green class as B R2-F1: network-unverifiable citations must
    not be attested as resolving."""
    from paper_factory.release.closure import _u4
    ctx = _ctx_online(tmp_path)
    ctx.workspace.reports_dir.mkdir(parents=True, exist_ok=True)
    (ctx.workspace.reports_dir / "citation_audit.json").write_text(_json.dumps({
        "offline": False, "entries": [{"key": "k", "verdict": "UNKNOWN_NETWORK"}],
        "findings": [{"severity": "MAJOR", "kind": "unverifiable_network",
                      "key": "k", "doi": "10.1/x"}]}))
    state, note = _u4(ctx)
    assert state == "DEGRADED" and "unverifiable" in note


def test_gap_p3_r3_t4_no_doi_is_major_real_bib_no_doi_stays_minor(tmp_path):
    from paper_factory.literature import verify
    ctx = _ctx_online(tmp_path)
    entries = [{"key": "t4x", "doi": None, "eprint": None, "title": "x",
                "t4_derived": True},
               {"key": "realx", "doi": None, "eprint": None, "title": "y",
                "t4_derived": False}]
    records, findings, verdict = verify._audit_entries(ctx, entries)
    by_key = {f["key"]: f for f in findings}
    assert by_key["t4x"]["kind"] == "unverifiable_citation"
    assert by_key["t4x"]["severity"] == "MAJOR"
    assert by_key["realx"]["kind"] == "no_doi"
    assert by_key["realx"]["severity"] == "MINOR"
    assert verdict == Verdict.DEGRADED
    rec = {r["key"]: r for r in records}
    assert rec["t4x"]["verdict"] == "UNVERIFIABLE_T4"
    assert rec["realx"]["verdict"] == "NO_DOI"


def test_gap_p3_r3_arxiv_eprint_synthesizes_datacite_doi(tmp_path, monkeypatch):
    """arXiv eprints are verified via their official DataCite DOI — a fake
    eprint becomes a false_citation CRITICAL, not a MINOR shrug."""
    from paper_factory.literature import verify
    seen = {}

    def fake_resolve(doi, timeout=20):
        seen["doi"] = doi
        return {"doi": doi, "verdict": "NOT_FOUND", "sources": {}}

    monkeypatch.setattr(verify, "resolve_doi", fake_resolve)
    ctx = _ctx_online(tmp_path)
    entries = [{"key": "k1", "doi": None, "eprint": "2401.99999",
                "title": "t", "t4_derived": True}]
    records, findings, verdict = verify._audit_entries(ctx, entries)
    assert seen["doi"] == "10.48550/arXiv.2401.99999"
    assert records[0]["doi_source"] == "arxiv_synthesized"
    assert findings[0]["kind"] == "false_citation"
    assert findings[0]["severity"] == "CRITICAL"


def test_gap_p3_r3_t4_flag_from_note_content(tmp_path):
    """B R2-F2: after build_references copies derived entries into
    paper/references.bib, the manuscript-path audit still flags them
    t4_derived — via the provenance NOTE in the entry, not the filename."""
    from paper_factory.literature.verify import build_references, run_citation_audit
    (tmp_path / "draft").mkdir()
    (tmp_path / "draft" / "paper.md").write_text(
        "# T\n\ntext\n\n" + _P3_REFS, encoding="utf-8")
    ctx = _ctx(tmp_path)
    assert build_references(ctx).verdict == Verdict.PASS
    out = run_citation_audit(ctx)  # reads paper/references.bib (manuscript path)
    assert out.verdict == Verdict.DEGRADED  # offline
    audit = _json.loads(
        (ctx.workspace.reports_dir / "citation_audit.json").read_text())
    assert audit["bib_files"][0].endswith("references.bib"), audit["bib_files"]
    assert audit["entries"], audit
    assert all(e.get("t4_derived") is True for e in audit["entries"])


def test_gap_p3_r3_arxiv_old_style_eprint():
    """A R2 N-A: old-style arXiv ids carry a slash (cs/0601001) — the regex
    must span it."""
    from paper_factory.literature.draft_refs import parse_markdown_refs
    bib = parse_markdown_refs(
        "# References\n\n\\[1\\] Old, S. A classic result on many things. "
        "URL https://arxiv.org/abs/cs/0601001, 2006.\n")
    assert "eprint = {cs/0601001}" in bib, bib


def test_gap_p3_r3_claims_cut_at_references(tmp_path):
    """A R2 N-B: reference-list content (cue verb + year inside a TITLE) must
    not become a claim."""
    from paper_factory.claims.builder import run_claim_graph
    from paper_factory.claims.graph import load_claims
    (tmp_path / "draft").mkdir()
    (tmp_path / "draft" / "paper.md").write_text(
        "# T\n\nThe audit shows 42 cases hold across all arms.\n\n"
        "# References\n\n"
        "\\[1\\] Pineau, J. Improving reproducibility in machine learning "
        "research: A report from the NeurIPS 2019 reproducibility program. "
        "2020.\n",
        encoding="utf-8")
    ctx = _ctx(tmp_path)
    run_claim_graph(ctx)
    graph = load_claims(ctx.workspace.claims_dir / "claims.yaml")
    stmts = " ".join(c.statement for c in graph.claims)
    assert graph.claims, "the real claim above the references must survive"
    assert "NeurIPS" not in stmts
    assert "reproducibility" not in stmts


def test_gap_p3_r3_heading_and_table_debris_not_claims():
    """A R2 N-C: a markdown heading directly above a claim sentence is
    stripped from the statement; markdown table rows never become claims."""
    from paper_factory.claims.builder import (
        _clean_for_extraction, _extract_candidates, _is_structural_fragment)
    text = _clean_for_extraction(
        "## Limitations\n\nThe audit shows 42 cases hold across arms.\n\n"
        "| arm | tokens |\n|---|---|\n| muon shows 5 tokens | 4.6 |.\n")
    cands = [c for _, c in _extract_candidates(text)
             if not _is_structural_fragment(c)]
    assert any(c.startswith("The audit shows") for c in cands), cands
    assert not any("Limitations" in c for c in cands), cands
    assert not any("muon shows" in c for c in cands), cands


def test_gap_p3_r3_versioned_rename_same_second(tmp_path, monkeypatch):
    """A R2 N-D: two versioned renames in the same UTC second must both
    survive — POSIX rename would otherwise overwrite the earlier version."""
    from paper_factory.literature import draft_refs

    class _FrozenDT:
        @staticmethod
        def now(tz=None):
            from datetime import datetime as _dt
            return _dt(2026, 9, 30, 12, 0, 0)

    monkeypatch.setattr(draft_refs, "datetime", _FrozenDT)
    f = tmp_path / "parsed_from_draft.bib"
    f.write_text("v1", encoding="utf-8")
    d1 = draft_refs._versioned_rename(f)
    f.write_text("v2", encoding="utf-8")
    d2 = draft_refs._versioned_rename(f)
    assert d1.name != d2.name
    assert d1.read_text() == "v1" and d2.read_text() == "v2"


# ---------------------------------------------------------------------------
# GAP-3x review round 4 (A R3-1 eprint version suffix → false CRITICAL,
# A R3-2 LaTeX refs cut, A R3-3 pipe-in-prose, A R3-4 note payload robustness,
# A R3-5 mid-text References heading, B R3-1 remediation re-audit t4 flag,
# B R3-2 stale final audit masking)
# ---------------------------------------------------------------------------

def test_gap_p3_r4_eprint_version_suffix_stripped(tmp_path, monkeypatch):
    """A R3-1 (CRITICAL): arXiv DataCite DOIs are versionless — an eprint with
    v2 suffix must be stripped, else a REAL paper 404s into false_citation."""
    from paper_factory.literature import verify
    seen = {}

    def fake_resolve(doi, timeout=20):
        seen["doi"] = doi
        return {"doi": doi, "verdict": "VERIFIED", "sources": {}}

    monkeypatch.setattr(verify, "resolve_doi", fake_resolve)
    ctx = _ctx_online(tmp_path)
    entries = [{"key": "k", "doi": None, "eprint": "2401.12345v2",
                "title": "t", "t4_derived": False}]
    records, findings, verdict = verify._audit_entries(ctx, entries)
    assert seen["doi"] == "10.48550/arXiv.2401.12345", seen
    # no false_citation CRITICAL; a MINOR identity_unjudgeable is the honest
    # record for a title-less stub resolve (final-acceptance visibility rule)
    assert not any(f["severity"] in ("CRITICAL", "MAJOR") for f in findings), findings


def test_gap_p3_r4_latex_refs_section_cut(tmp_path):
    """A R3-2 (MAJOR): the reference cut must also work for LaTeX drafts —
    \\section{References} with \\bibitem entries below."""
    from paper_factory.claims.builder import run_claim_graph
    from paper_factory.claims.graph import load_claims
    (tmp_path / "draft").mkdir()
    (tmp_path / "draft" / "paper.tex").write_text(
        "\\section{Results}\nThe audit shows 42 cases hold across all arms.\n"
        "\\section{References}\n"
        "\\bibitem{rcnn} Ren, S. Faster R-CNN improves detection by 30 "
        "percent in 2015 settings.\n",
        encoding="utf-8")
    ctx = _ctx(tmp_path)
    run_claim_graph(ctx)
    graph = load_claims(ctx.workspace.claims_dir / "claims.yaml")
    stmts = " ".join(c.statement for c in graph.claims)
    assert graph.claims, "the real claim must survive"
    assert "R-CNN" not in stmts, stmts


def test_gap_p3_r4_mid_text_references_heading_not_a_cut(tmp_path):
    """A R3-5 (MAJOR): a '# References' heading WITHOUT entry markers after it
    is a discussion section — nothing below it may be cut."""
    from paper_factory.claims.builder import _cut_reference_section
    text = ("# Study\n\nWe discuss prior work.\n\n# References\n\n"
            "This section argues the references in 2024 literature show 5 "
            "trends clearly.\n\n# Results\n\nThe audit shows 42 cases hold.\n")
    cut = _cut_reference_section(text)
    assert "42 cases hold" in cut, "content below a marker-less References heading was cut"
    assert "5 trends" in cut


def test_gap_p3_r4_inline_math_pipes_keep_claim():
    """A R3-3 (MAJOR): |S|, P(A|B), norms must not reject real claims — only
    markdown table GRID rows (line starting with pipe, ≥3 pipes)."""
    from paper_factory.claims.builder import (
        _clean_for_extraction, _extract_candidates, _is_structural_fragment)
    text = _clean_for_extraction(
        "We find the cardinality |S| exceeds 2 in 80% of measured runs.\n\n"
        "| arm | tokens | nll |\n|---|---|---|\n| muon shows 5 tokens | x | 4.6 |.\n")
    cands = [c for _, c in _extract_candidates(text)
             if not _is_structural_fragment(c)]
    assert any("cardinality" in c for c in cands), cands
    assert not any("muon shows" in c for c in cands), cands


def test_gap_p3_r4_t4_flag_robust_to_nasty_note_payloads(tmp_path):
    """A R3-4 (MAJOR): T4 provenance detection must survive quotes, @ and
    inner braces in the note — the flag is span-bound, not regex-field-bound."""
    from paper_factory.literature.verify import parse_bib
    bib = tmp_path / "nasty.bib"
    bib.write_text(
        '@misc{weird1,\n  title = {X},\n'
        '  note = {He said "internal draft", parsed from draft reference list (T4)}\n}\n'
        '@misc{weird2,\n  title = {Y},\n'
        '  note = {Contact foo@bar.edu, parsed from draft reference list (T4)}\n}\n'
        '@misc{weird3,\n  title = {Z},\n'
        '  note = {see {Smith 2020}, parsed from draft reference list (T4)}\n}\n'
        '@misc{clean1,\n  title = {W},\n  note = {ordinary note}\n}\n',
        encoding="utf-8")
    entries = {e["key"]: e for e in parse_bib(bib)}
    assert entries["weird1"]["t4_derived"] is True
    assert entries["weird2"]["t4_derived"] is True
    assert entries["weird3"]["t4_derived"] is True
    assert entries["clean1"]["t4_derived"] is False


def test_gap_p3_r4_remediation_reaudit_keeps_t4_flag(tmp_path):
    """B R3-1 (MAJOR): the remediation re-audit parses references.bib via
    parse_bib — the T4 flag must survive THAT path, so the final audit still
    carries unverifiable_citation (MAJOR), not a downgraded MINOR no_doi."""
    from paper_factory.literature import verify
    ctx = _ctx_online(tmp_path)
    ctx.workspace.paper_dir.mkdir(parents=True, exist_ok=True)
    bib = ctx.workspace.paper_dir / "references.bib"
    bib.write_text(
        "@misc{draftref2,\n  title = {Madeup, B. Another invented result},\n"
        "  note = {parsed from draft reference list (T4) — verify before citation}\n}\n",
        encoding="utf-8")
    entries = verify.parse_bib(bib)  # exactly what _remediate_citation_finding does
    records, findings, verdict = verify._audit_entries(ctx, entries)
    assert any(f["kind"] == "unverifiable_citation" and f["severity"] == "MAJOR"
               and f["key"] == "draftref2" for f in findings), findings
    assert verdict == Verdict.DEGRADED


def test_gap_p3_r4_stale_final_never_masks_fresher_audit(tmp_path):
    """B R3-2 (MAJOR): a stale citation_audit_final.json must not override a
    FRESHER P21 audit with stricter findings. Inverse: a fresh final wins."""
    from paper_factory.release.closure import _u4
    ctx = _ctx_online(tmp_path)
    reports = ctx.workspace.reports_dir
    reports.mkdir(parents=True, exist_ok=True)
    strict = {"audited_at": "2026-09-30T15:00:00Z", "offline": False,
              "entries": [], "findings": [
                  {"severity": "MAJOR", "kind": "unverifiable_citation",
                   "key": "draftref2"}]}
    lax = {"audited_at": "2026-09-30T14:00:00Z", "offline": False,
           "entries": [], "findings": [
               {"severity": "MINOR", "kind": "no_doi", "key": "draftref2"}]}
    (reports / "citation_audit.json").write_text(_json.dumps(strict))
    (reports / "citation_audit_final.json").write_text(_json.dumps(lax))
    state, note = _u4(ctx)
    assert state == "DEGRADED", (state, note)
    # inverse: final is NEWER → it wins (post-remediation state is authoritative)
    lax["audited_at"] = "2026-09-30T16:00:00Z"
    (reports / "citation_audit_final.json").write_text(_json.dumps(lax))
    state, note = _u4(ctx)
    assert state == "PASS", (state, note)
    assert "not resolvable" in note


# ---------------------------------------------------------------------------
# GAP-3x review round 4b (A R4-1 eprint V-case, A R4-2 bullet-list refs,
# A R4-3 mid-line [N] citation false cut, A R4-5 multi-pipe prose)
# ---------------------------------------------------------------------------

def test_gap_p3_r4b_eprint_uppercase_version_stripped(tmp_path, monkeypatch):
    """A R4-1: V2 (uppercase) must strip exactly like v2."""
    from paper_factory.literature import verify
    seen = {}

    def fake_resolve(doi, timeout=20):
        seen["doi"] = doi
        return {"doi": doi, "verdict": "VERIFIED", "sources": {}}

    monkeypatch.setattr(verify, "resolve_doi", fake_resolve)
    ctx = _ctx_online(tmp_path)
    entries = [{"key": "k", "doi": None, "eprint": "2401.12345V2",
                "title": "t", "t4_derived": False}]
    verify._audit_entries(ctx, entries)
    assert seen["doi"] == "10.48550/arXiv.2401.12345", seen


def test_gap_p3_r4b_bullet_list_references_cut():
    """A R4-2: bullet-list bibliographies (no [N] markers) after a References
    heading must also cut — else their titles become bogus claims."""
    from paper_factory.claims.builder import _cut_reference_section
    text = ("# Study\n\nThe audit shows 42 cases hold across arms.\n\n"
            "# References\n\n"
            "- Ren, S. Faster R-CNN improves detection by 30 percent in 2015.\n"
            "- Pineau, J. A report from the 2019 program shows 3 trends.\n")
    cut = _cut_reference_section(text)
    assert "42 cases hold" in cut
    assert "R-CNN" not in cut


def test_gap_p3_r4b_midline_citation_marker_no_false_cut():
    """A R4-3: a mid-line [1] CITATION after a '# References' discussion
    heading is not bibliography evidence — nothing is cut."""
    from paper_factory.claims.builder import _cut_reference_section
    text = ("# Study\n\n# References\n\n"
            "We argue the approach in [1] differs fundamentally from later "
            "work in this area.\n\n"
            "# Results\n\nThe audit reduces errors by 15 percent in 42 cold "
            "runs overall.\n")
    cut = _cut_reference_section(text)
    assert "reduces errors by 15 percent" in cut, "false cut on mid-line [N] citation"


def test_gap_p3_r4b_multi_pipe_prose_kept():
    """A R4-5: multi-pipe PROSE is not a table row (a grid row ENDS at its
    last pipe). Note: a candidate literally STARTING with '|S|' was already
    rejected pre-R3 by the sentence-starts-with-a-letter rule — unchanged."""
    from paper_factory.claims.builder import (
        _clean_for_extraction, _extract_candidates, _is_structural_fragment)
    text = _clean_for_extraction(
        "The values |S| and |T| both show gains of 30% in the 42 measured "
        "runs today.\n")
    cands = [c for _, c in _extract_candidates(text)
             if not _is_structural_fragment(c)]
    assert any("both show gains" in c for c in cands), cands


def test_gap_p3_r5_build_references_preserves_at_sign_entries(tmp_path):
    """B R4-F1 (MAJOR): build_references copies via the span splitter — an '@'
    inside a field (URL userinfo) must neither truncate the T4 note nor drop
    the entry silently. The manuscript-path audit must still see MAJOR
    unverifiable_citation, and U4 must stay DEGRADED."""
    from paper_factory.literature.verify import build_references, run_citation_audit
    from paper_factory.release.closure import _u4
    (tmp_path / "draft").mkdir()
    (tmp_path / "draft" / "paper.md").write_text(
        "# T\n\ntext\n\n# References\n\n"
        "\\[1\\] Author, A. Results at scale on many benchmarks. "
        "URL https://example.org/u@host/page, 2024.\n",
        encoding="utf-8")
    ctx = _ctx_online(tmp_path)
    out = build_references(ctx)
    assert out.verdict == Verdict.PASS
    assert out.detail["kept"], "entry with @-URL was silently dropped"
    built = (ctx.workspace.paper_dir / "references.bib").read_text()
    assert "parsed from draft reference list" in built, built
    out_audit = run_citation_audit(ctx)  # manuscript path now
    audit = _json.loads(
        (ctx.workspace.reports_dir / "citation_audit.json").read_text())
    assert any(f["kind"] == "unverifiable_citation" and f["severity"] == "MAJOR"
               for f in audit["findings"]), audit["findings"]
    state, note = _u4(ctx)
    assert state == "DEGRADED", (state, note)


# ---------------------------------------------------------------------------
# FINAL ACCEPTANCE (2026-10-01): citation IDENTITY. DOI resolvability alone
# is not verification — the resolved work must BE the cited work. P21/U4 must
# never attest a real-but-different DOI as VERIFIED/PASS.
# ---------------------------------------------------------------------------


def _fake_resolve_title(title):
    def fake(doi, timeout=20):
        return {"doi": doi, "checked_at": "2026-10-01T00:00:00Z",
                "sources": {"crossref": {"status": "found", "http": 200}},
                "verdict": "VERIFIED", "title": title}
    return fake


def test_citation_identity_wrong_paper_doi_never_verified(tmp_path, monkeypatch):
    """Negative control: the draft cites paper A, the DOI is real and
    resolvable but belongs to paper B → CRITICAL identity mismatch, never
    VERIFIED."""
    from paper_factory.literature import verify
    monkeypatch.setattr(
        verify, "resolve_doi",
        _fake_resolve_title("Deep Residual Learning for Image Recognition"))
    ctx = _ctx_online(tmp_path)
    entries = [{"key": "attn", "doi": "10.1000/real-but-other-paper",
                "eprint": None, "title": "Attention Is All You Need",
                "t4_derived": False}]
    records, findings, _verdict = verify._audit_entries(ctx, entries)
    assert records[0]["verdict"] == "IDENTITY_MISMATCH", records
    assert records[0]["identity_check"] == "mismatch"
    assert findings[0]["kind"] == "citation_identity_mismatch"
    assert findings[0]["severity"] == "CRITICAL"
    assert findings[0]["key"] == "attn"


def test_citation_identity_u4_fails_on_mismatch(tmp_path):
    """U4 treats an identity mismatch like a false citation: FAIL, named key."""
    from paper_factory.release.closure import _u4
    ctx = _ctx_online(tmp_path)
    ctx.workspace.reports_dir.mkdir(parents=True, exist_ok=True)
    (ctx.workspace.reports_dir / "citation_audit.json").write_text(_json.dumps({
        "offline": False,
        "entries": [{"key": "attn", "verdict": "IDENTITY_MISMATCH"}],
        "findings": [{"severity": "CRITICAL", "kind": "citation_identity_mismatch",
                      "key": "attn", "doi": "10.1000/x"}]}))
    state, note = _u4(ctx)
    assert state == "FAIL", (state, note)
    assert "attn" in note


def test_citation_identity_harmless_title_variants_pass(tmp_path, monkeypatch):
    """Positive control: punctuation/unicode/whitespace/case variants of the
    CORRECT title must not fail."""
    from paper_factory.literature import verify
    resolved = "Mass Invariance: Schrödinger's Framework for Multi-Scale Systems"
    monkeypatch.setattr(verify, "resolve_doi", _fake_resolve_title(resolved))
    variants = [
        "Mass Invariance: Schrödinger's Framework for Multi-Scale Systems",
        "mass invariance: schrödinger's framework for multi-scale systems",
        "  Mass   Invariance:  Schrödinger's Framework  for Multi-Scale Systems ",
        "Mass Invariance—Schrödinger's Framework for Multi-Scale Systems",
        "Mass Invariance: Schrödinger's Framework for Multi-Scale Systems.",
        # accent-free + curly apostrophe + non-breaking hyphen
        "Mass Invariance: Schrodinger’s Framework for Multi‑Scale Systems",
    ]
    for claimed in variants:
        ctx = _ctx_online(tmp_path)
        entries = [{"key": "k", "doi": "10.1000/right", "eprint": None,
                    "title": claimed, "t4_derived": False}]
        records, findings, _ = verify._audit_entries(ctx, entries)
        assert records[0]["verdict"] == "VERIFIED", (claimed, records[0])
        assert records[0]["identity_check"] == "match"
        assert findings == [], (claimed, findings)


def test_citation_identity_unjudgeable_when_title_missing(tmp_path, monkeypatch):
    """Nothing to compare → no fabricated mismatch; VERIFIED stands on
    resolvability alone, the record says the identity check could not run,
    and a MINOR keeps the gap visible instead of silently passing."""
    from paper_factory.literature import verify
    monkeypatch.setattr(verify, "resolve_doi", _fake_resolve_title(None))
    ctx = _ctx_online(tmp_path)
    entries = [{"key": "k", "doi": "10.1000/x", "eprint": None,
                "title": None, "t4_derived": False}]
    records, findings, _ = verify._audit_entries(ctx, entries)
    assert records[0]["verdict"] == "VERIFIED"
    assert records[0]["identity_check"] == "unjudgeable"
    assert findings == [{"severity": "MINOR", "kind": "identity_unjudgeable",
                         "key": "k", "doi": "10.1000/x"}]


def test_citation_identity_build_references_drops_mismatched(tmp_path, monkeypatch):
    """A proven identity mismatch is excluded from the manuscript bibliography
    like a false citation — and the exclusion is recorded."""
    from paper_factory.literature import verify
    from paper_factory.literature.verify import build_references, run_citation_audit
    lit = tmp_path / "literature"
    lit.mkdir()
    (lit / "refs.bib").write_text(
        "@article{good, title={The Real Paper}, doi={10.1000/good}}\n"
        "@article{bad, title={Attention Is All You Need}, doi={10.1000/other}}\n",
        encoding="utf-8")

    def fake(doi, timeout=20):
        titles = {"10.1000/good": "The Real Paper",
                  "10.1000/other": "Deep Residual Learning for Image Recognition"}
        return {"doi": doi, "verdict": "VERIFIED", "sources": {}, "title": titles[doi]}

    monkeypatch.setattr(verify, "resolve_doi", fake)
    ctx = _ctx_online(tmp_path)
    out_audit = run_citation_audit(ctx)
    assert out_audit.verdict == Verdict.PASS, out_audit.detail  # audit executed
    out = build_references(ctx)
    assert "bad" in out.detail["dropped_false"], out.detail
    built = (ctx.workspace.paper_dir / "references.bib").read_text()
    assert "good" in built
    assert "doi={10.1000/other}" not in built


def test_citation_identity_remediation_drops_and_resolves(tmp_path, monkeypatch):
    """Remediation routes citation_identity_mismatch through the citation lane:
    drop the specific wrong-DOI entry, re-audit, RESOLVED only when the bound
    key is actually gone."""
    ctx = _ctx(tmp_path)
    _g4_claims(ctx)
    ctx.workspace.paper_dir.mkdir(parents=True, exist_ok=True)
    bib = ctx.workspace.paper_dir / "references.bib"
    bib.write_text("@article{x, doi={10.1000/other}, title={Attention Is All You Need}}\n",
                   encoding="utf-8")
    _g4_review(ctx, [_g4_finding("F01", kind="citation_identity_mismatch",
                                 category="citation",
                                 details={"doi": "10.1000/other"})])

    from paper_factory.literature import verify

    def _rebuild_drops_key(ctx_):
        bib.write_text("@article{ok, doi={10.1/real}}\n", encoding="utf-8")

    monkeypatch.setattr(verify, "build_references", _rebuild_drops_key)
    monkeypatch.setattr(verify, "_audit_entries", lambda ctx_, entries: ([], [], None))
    outcome = run_remediation(ctx)
    reviews, _ = load_reviews(ctx.workspace.reviews_dir)
    assert reviews[0].findings[0].disposition == Disposition.RESOLVED
    assert outcome.verdict == Verdict.PASS


# ---------------------------------------------------------------------------
# Citation identity — Round 2 (Reviewer A F1-F8 / Reviewer B B-1..B-4):
# the check must hold on the arXiv/DataCite path, on real BibTeX field
# shapes, and against LaTeX-escaped titles — without flagging correct
# citations and without stale audits dropping corrected entries.
# ---------------------------------------------------------------------------


def test_citation_identity_openalex_title_feeds_check(tmp_path, monkeypatch):
    """A-F1: a DOI that resolves ONLY via OpenAlex (all DataCite/arXiv DOIs)
    previously had rec['title']=None → identity unjudgeable → silent bypass.
    resolve_doi must take the title from the OpenAlex body as fallback."""
    import io
    import urllib.error
    from paper_factory.literature import verify

    class _Resp:
        def __init__(self, payload):
            self._b = _json.dumps(payload).encode()

        def read(self):
            return self._b

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=20):
        url = req.full_url
        if "crossref" in url:
            raise urllib.error.HTTPError(url, 404, "nf", {}, io.BytesIO(b""))
        return _Resp({"title": "The OpenAlex Only Paper"})

    monkeypatch.setattr(verify.urllib.request, "urlopen", fake_urlopen)
    rec = verify.resolve_doi("10.48550/arXiv.2401.00001")
    assert rec["verdict"] == "VERIFIED"
    assert rec["title"] == "The OpenAlex Only Paper", rec

    # and the audit path must therefore catch a wrong arXiv DOI
    ctx = _ctx_online(tmp_path)
    entries = [{"key": "k", "doi": None, "eprint": "2401.00001",
                "title": "A Completely Different Work", "t4_derived": False}]
    _records, findings, _v = verify._audit_entries(ctx, entries)
    assert findings[0]["kind"] == "citation_identity_mismatch", findings
    assert findings[0]["severity"] == "CRITICAL"


def test_citation_identity_bib_field_edge_shapes(tmp_path):
    """A-F2/F8: title as LAST field without trailing comma (legal BibTeX) and
    titles containing `},` must parse — otherwise claimed_title=None silently
    bypasses the identity check."""
    from paper_factory.literature.verify import parse_bib
    bib = tmp_path / "refs.bib"
    bib.write_text(
        "@article{last, doi={10.1/a}, title={The Last Field Title}}\n"
        "@article{braces, title={Sets {A}, {B} and C}, doi={10.1/b}}\n"
        "@article{quoted, title=\"A Quoted Title\", doi={10.1/c}}\n"
        "@article{dbl, title={{Double Braced Title}}, doi={10.1/d}}\n",
        encoding="utf-8")
    entries = {e["key"]: e for e in parse_bib(bib)}
    assert entries["last"]["title"] == "The Last Field Title"
    assert entries["braces"]["title"] == "Sets {A}, {B} and C"
    assert entries["quoted"]["title"] == "A Quoted Title"
    assert entries["dbl"]["title"] == "{Double Braced Title}"


def test_citation_identity_latex_accents_and_macros_match(tmp_path, monkeypatch):
    """B-1/A-F5: standard BibTeX accent escapes and formatting macros in the
    bib title are the SAME work as the clean Crossref title — never CRITICAL."""
    from paper_factory.literature import verify
    pairs = [
        ("Schr{\\\"o}dinger's Equation in {\\emph{Quantum}} Mechanics",
         "Schrödinger's Equation in Quantum Mechanics"),
        ("Caf{\\'e} Society at {\\it Large}", "Café Society at Large"),
        ("Na{\\\"\\i}ve Bayes Revisited", "Naïve Bayes Revisited"),
        ("{\\\"U}ber die Masseninvarianz", "Über die Masseninvarianz"),
        ("{\\`E}tude sur la Th{\\`e}orie", "Ètude sur la Thèorie"),
    ]
    for claimed, resolved in pairs:
        monkeypatch.setattr(verify, "resolve_doi", _fake_resolve_title(resolved))
        ctx = _ctx_online(tmp_path)
        entries = [{"key": "k", "doi": "10.1/x", "eprint": None,
                    "title": claimed, "t4_derived": False}]
        records, findings, _ = verify._audit_entries(ctx, entries)
        assert records[0]["verdict"] == "VERIFIED", (claimed, records[0])
        assert findings == [] or all(f["kind"] != "citation_identity_mismatch"
                                     for f in findings), (claimed, findings)


def test_citation_identity_subtitle_prefix_is_same_work(tmp_path, monkeypatch):
    """A-F4: Crossref carries 'Title: Subtitle', the bib often only the main
    title — a token-boundary prefix is the same work."""
    from paper_factory.literature import verify
    monkeypatch.setattr(verify, "resolve_doi",
                        _fake_resolve_title("Deep Learning: Methods and Applications"))
    ctx = _ctx_online(tmp_path)
    entries = [{"key": "k", "doi": "10.1/dl", "eprint": None,
                "title": "Deep Learning", "t4_derived": False}]
    records, findings, _ = verify._audit_entries(ctx, entries)
    assert records[0]["verdict"] == "VERIFIED", records[0]
    assert not any(f["kind"] == "citation_identity_mismatch" for f in findings)


def test_citation_identity_umlaut_transliteration_matches(tmp_path, monkeypatch):
    """A-F6: BibTeX transliteration convention Mueller/Müller is one author."""
    from paper_factory.literature import verify
    monkeypatch.setattr(verify, "resolve_doi",
                        _fake_resolve_title("Müller on Mass Invariance"))
    ctx = _ctx_online(tmp_path)
    entries = [{"key": "k", "doi": "10.1/m", "eprint": None,
                "title": "Mueller on Mass Invariance", "t4_derived": False}]
    records, findings, _ = verify._audit_entries(ctx, entries)
    assert records[0]["verdict"] == "VERIFIED", records[0]
    assert not any(f["kind"] == "citation_identity_mismatch" for f in findings)


def test_citation_identity_degenerate_and_short_titles_unjudgeable(tmp_path, monkeypatch):
    """A-F3/F7: one-word or punctuation-only titles cannot prove identity —
    honest unjudgeable (visible MINOR), never a silent pass and never a
    fabricated CRITICAL."""
    from paper_factory.literature import verify
    monkeypatch.setattr(verify, "resolve_doi", _fake_resolve_title("Introduction"))
    for claimed in ("Introduction", "---", "{}"):
        ctx = _ctx_online(tmp_path)
        entries = [{"key": "k", "doi": "10.1/x", "eprint": None,
                    "title": claimed, "t4_derived": False}]
        records, findings, _ = verify._audit_entries(ctx, entries)
        assert records[0]["verdict"] == "VERIFIED", (claimed, records[0])
        assert records[0]["identity_check"] == "unjudgeable", (claimed, records[0])
        assert not any(f["severity"] == "CRITICAL" for f in findings), (claimed, findings)
        assert any(f["kind"] == "identity_unjudgeable" and f["severity"] == "MINOR"
                   for f in findings), (claimed, findings)


def test_citation_identity_u4_scopes_unjudgeable_minors(tmp_path):
    """U4 must not attest blanket resolution when identity was unjudgeable."""
    from paper_factory.release.closure import _u4
    ctx = _ctx_online(tmp_path)
    ctx.workspace.reports_dir.mkdir(parents=True, exist_ok=True)
    (ctx.workspace.reports_dir / "citation_audit.json").write_text(_json.dumps({
        "offline": False,
        "entries": [{"key": "k", "verdict": "VERIFIED", "identity_check": "unjudgeable"}],
        "findings": [{"severity": "MINOR", "kind": "identity_unjudgeable",
                      "key": "k", "doi": "10.1/x"}]}))
    state, note = _u4(ctx)
    assert state == "PASS"
    assert "all citations resolve" not in note
    assert "identity" in note.lower()


def test_citation_identity_build_references_keeps_corrected_doi(tmp_path):
    """B-2: exclusion binds (key, doi) — a stale audit finding must not drop
    an entry whose DOI the author has since corrected under the same key."""
    from paper_factory.literature.verify import build_references
    lit = tmp_path / "literature"
    lit.mkdir()
    (lit / "refs.bib").write_text(
        "@article{fixed, title={The Real Paper}, doi={10.1000/corrected}}\n",
        encoding="utf-8")
    ctx = _ctx(tmp_path)
    ctx.workspace.reports_dir.mkdir(parents=True, exist_ok=True)
    (ctx.workspace.reports_dir / "citation_audit.json").write_text(_json.dumps({
        "offline": False,
        "entries": [{"key": "fixed", "verdict": "IDENTITY_MISMATCH"}],
        "findings": [{"severity": "CRITICAL", "kind": "citation_identity_mismatch",
                      "key": "fixed", "doi": "10.1000/wrong"}]}))
    out = build_references(ctx)
    assert out.detail["kept"] == 1, out.detail
    assert out.detail["dropped_false"] == []
    built = (ctx.workspace.paper_dir / "references.bib").read_text()
    assert "10.1000/corrected" in built


def test_citation_identity_u4_record_without_finding_still_fails(tmp_path):
    """B-3 (defense in depth): a record verdict of IDENTITY_MISMATCH must fail
    U4 even if the findings list is empty/corrupt."""
    from paper_factory.release.closure import _u4
    ctx = _ctx_online(tmp_path)
    ctx.workspace.reports_dir.mkdir(parents=True, exist_ok=True)
    (ctx.workspace.reports_dir / "citation_audit.json").write_text(_json.dumps({
        "offline": False,
        "entries": [{"key": "ghost", "verdict": "IDENTITY_MISMATCH"}],
        "findings": []}))
    state, note = _u4(ctx)
    assert state == "FAIL", (state, note)
    assert "ghost" in note


def test_citation_identity_same_second_final_never_masks_audit(tmp_path):
    """B-4: on a timestamp tie the stricter P21 audit wins — a same-second
    post-remediation final must not mask a fresh CRITICAL."""
    from paper_factory.release.closure import _u4
    ctx = _ctx_online(tmp_path)
    reports = ctx.workspace.reports_dir
    reports.mkdir(parents=True, exist_ok=True)
    ts = "2026-10-01T12:00:00Z"
    (reports / "citation_audit.json").write_text(_json.dumps({
        "audited_at": ts, "offline": False, "entries": [],
        "findings": [{"severity": "CRITICAL", "kind": "citation_identity_mismatch",
                      "key": "x", "doi": "10.1/x"}]}))
    (reports / "citation_audit_final.json").write_text(_json.dumps({
        "audited_at": ts, "offline": False, "entries": [], "findings": [],
        "post_remediation": True}))
    state, note = _u4(ctx)
    assert state == "FAIL", (state, note)


# ---------------------------------------------------------------------------
# Citation identity — Round 3 (Reviewer A N8 / Reviewer B R2-1..R2-3)
# ---------------------------------------------------------------------------


def test_citation_identity_booktitle_not_matched_as_title(tmp_path):
    """A-N8 (MAJOR): `_bib_field` must not match `title=` inside `booktitle=`
    or `subtitle=` — the proceedings title is NOT the cited work's title."""
    from paper_factory.literature.verify import parse_bib
    bib = tmp_path / "refs.bib"
    bib.write_text(
        "@inproceedings{paper,\n"
        "  booktitle = {Advances in Neural Information Processing Systems 30},\n"
        "  title = {Attention Is All You Need},\n"
        "  doi = {10.1/attn}}\n"
        "@article{sub, subtitle = {A Subtitle Only Entry}, doi={10.1/sub}}\n",
        encoding="utf-8")
    entries = {e["key"]: e for e in parse_bib(bib)}
    assert entries["paper"]["title"] == "Attention Is All You Need"
    assert entries["sub"]["title"] is None  # subtitle is not the work's title


def test_citation_identity_unbraced_accent_keeps_following_space(tmp_path, monkeypatch):
    """B-R2-2 (MAJOR): `Caf\\'e Central` must normalize with the word boundary
    intact — the accent macro must not eat the following space."""
    from paper_factory.literature import verify
    pairs = [
        ("Caf\\'e Central Methods", "Café Central Methods"),
        ("H\\^otels of Z\\~urich", "Hôtels of Zürich"),
        ("\\`A Propos de Rien", "À Propos de Rien"),
    ]
    for claimed, resolved in pairs:
        monkeypatch.setattr(verify, "resolve_doi", _fake_resolve_title(resolved))
        ctx = _ctx_online(tmp_path)
        entries = [{"key": "k", "doi": "10.1/x", "eprint": None,
                    "title": claimed, "t4_derived": False}]
        records, findings, _ = verify._audit_entries(ctx, entries)
        assert records[0]["verdict"] == "VERIFIED", (claimed, records[0])
        assert not any(f["kind"] == "citation_identity_mismatch"
                       for f in findings), (claimed, findings)


def test_citation_identity_prefix_only_with_subtitle_separator(tmp_path, monkeypatch):
    """B-R2-3 / A-N10 (MAJOR): the prefix tolerance exists for the
    'Title: Subtitle' convention ONLY — a plain longer title is a DIFFERENT
    work ('Gaussian Processes' ≠ 'Gaussian Processes for Machine Learning')."""
    from paper_factory.literature import verify
    ctx = _ctx_online(tmp_path)
    monkeypatch.setattr(verify, "resolve_doi",
                        _fake_resolve_title("Gaussian Processes for Machine Learning"))
    entries = [{"key": "gp", "doi": "10.1/gpml", "eprint": None,
                "title": "Gaussian Processes", "t4_derived": False}]
    records, findings, _ = verify._audit_entries(ctx, entries)
    assert records[0]["verdict"] == "IDENTITY_MISMATCH", records[0]
    assert findings[0]["kind"] == "citation_identity_mismatch"
    # with a subtitle separator the convention applies and the prefix matches
    monkeypatch.setattr(verify, "resolve_doi",
                        _fake_resolve_title("Deep Learning: Methods and Applications"))
    entries = [{"key": "dl", "doi": "10.1/dl", "eprint": None,
                "title": "Deep Learning", "t4_derived": False}]
    records, findings, _ = verify._audit_entries(ctx, entries)
    assert records[0]["verdict"] == "VERIFIED", records[0]
    assert not any(f["kind"] == "citation_identity_mismatch" for f in findings)


def test_citation_identity_eprint_only_entry_dropped_via_synth_doi(tmp_path):
    """B-R2-1 (CRITICAL): an eprint-only entry (no doi field) must be dropped
    when the audit finding carries the SYNTHESIZED DataCite DOI — else the
    proven-fake citation ships in the manuscript bib forever."""
    from paper_factory.literature.verify import build_references
    lit = tmp_path / "literature"
    lit.mkdir()
    (lit / "refs.bib").write_text(
        "@article{fake, title={Invented Results}, eprint={2401.99999}}\n"
        "@article{real, title={The Real Paper}, doi={10.1/real}}\n",
        encoding="utf-8")
    ctx = _ctx(tmp_path)
    ctx.workspace.reports_dir.mkdir(parents=True, exist_ok=True)
    (ctx.workspace.reports_dir / "citation_audit.json").write_text(_json.dumps({
        "offline": False,
        "entries": [{"key": "fake", "verdict": "NOT_FOUND"}],
        "findings": [{"severity": "CRITICAL", "kind": "false_citation",
                      "key": "fake", "doi": "10.48550/arXiv.2401.99999"}]}))
    out = build_references(ctx)
    assert "fake" in out.detail["dropped_false"], out.detail
    built = (ctx.workspace.paper_dir / "references.bib").read_text()
    assert "2401.99999" not in built
    assert "10.1/real" in built


def test_citation_identity_eprint_remediation_resolves_not_vacuous(tmp_path, monkeypatch):
    """B-R2-1 (CRITICAL): remediation must bind a synthesized-DOI finding to
    the eprint-only entry (or fall back to the entry key) — never vacuous
    NOT_APPLICABLE while the toxic entry stays in the manuscript."""
    ctx = _ctx(tmp_path)
    _g4_claims(ctx)
    ctx.workspace.paper_dir.mkdir(parents=True, exist_ok=True)
    bib = ctx.workspace.paper_dir / "references.bib"
    bib.write_text("@article{fake, title={Invented Results}, eprint={2401.99999}}\n",
                   encoding="utf-8")
    _g4_review(ctx, [_g4_finding("F01", kind="false_citation", category="citation",
                                 details={"doi": "10.48550/arXiv.2401.99999",
                                          "key": "fake"})])

    from paper_factory.literature import verify

    def _rebuild_drops_key(ctx_):
        bib.write_text("@article{ok, doi={10.1/real}}\n", encoding="utf-8")

    monkeypatch.setattr(verify, "build_references", _rebuild_drops_key)
    monkeypatch.setattr(verify, "_audit_entries", lambda ctx_, entries: ([], [], None))
    outcome = run_remediation(ctx)
    reviews, _ = load_reviews(ctx.workspace.reviews_dir)
    disp = reviews[0].findings[0].disposition
    assert disp == Disposition.RESOLVED, disp
    assert outcome.verdict == Verdict.PASS


def test_citation_identity_finding_doi_url_prefix_normalized(tmp_path):
    """NIT hardening: a finding DOI carrying a https://doi.org/ prefix must
    still bind to the bare entry DOI."""
    from paper_factory.literature.verify import build_references
    lit = tmp_path / "literature"
    lit.mkdir()
    (lit / "refs.bib").write_text(
        "@article{x, title={Some Work}, doi={10.1/bad}}\n", encoding="utf-8")
    ctx = _ctx(tmp_path)
    ctx.workspace.reports_dir.mkdir(parents=True, exist_ok=True)
    (ctx.workspace.reports_dir / "citation_audit.json").write_text(_json.dumps({
        "offline": False, "entries": [],
        "findings": [{"severity": "CRITICAL", "kind": "citation_identity_mismatch",
                      "key": "x", "doi": "https://doi.org/10.1/bad"}]}))
    out = build_references(ctx)
    assert "x" in out.detail["dropped_false"], out.detail


# ---------------------------------------------------------------------------
# Citation identity — Round 4 (Reviewer A P1/P3 / Reviewer B R3-1/R3-2)
# ---------------------------------------------------------------------------


def test_citation_identity_hyphen_subtitle_separator(tmp_path, monkeypatch):
    """A-P1 (MAJOR): 'Title - Subtitle' (ASCII hyphen, older Springer/
    DataCite idiom) is the same work — but only with whitespace context,
    a bare compound hyphen ('Multi-Scale') is not a subtitle separator."""
    from paper_factory.literature import verify
    monkeypatch.setattr(verify, "resolve_doi",
                        _fake_resolve_title("Deep Learning - Methods and Applications"))
    ctx = _ctx_online(tmp_path)
    entries = [{"key": "k", "doi": "10.1/dl", "eprint": None,
                "title": "Deep Learning", "t4_derived": False}]
    records, findings, _ = verify._audit_entries(ctx, entries)
    assert records[0]["verdict"] == "VERIFIED", records[0]
    assert not any(f["kind"] == "citation_identity_mismatch" for f in findings)


def test_citation_identity_claimed_side_colon_is_mismatch(tmp_path, monkeypatch):
    """B-R3-2 (MAJOR): the subtitle tolerance is one-directional — a bib title
    'X: A Closer Look' resolving to plain 'X' means the DOI points at a
    DIFFERENT work (parasite/derivative title at the original's DOI)."""
    from paper_factory.literature import verify
    monkeypatch.setattr(verify, "resolve_doi",
                        _fake_resolve_title("Attention Is All You Need"))
    ctx = _ctx_online(tmp_path)
    entries = [{"key": "k", "doi": "10.1/attn", "eprint": None,
                "title": "Attention Is All You Need: A Closer Look",
                "t4_derived": False}]
    records, findings, _ = verify._audit_entries(ctx, entries)
    assert records[0]["verdict"] == "IDENTITY_MISMATCH", records[0]
    assert findings[0]["kind"] == "citation_identity_mismatch"
    assert findings[0]["severity"] == "CRITICAL"


def test_citation_identity_entry_doi_url_prefix_normalized(tmp_path):
    """A-P3 (MAJOR): Zotero/web exports write doi={https://doi.org/…} — the
    ENTRY side of the exclusion binding must be normalized exactly like the
    finding side, else a proven-mismatched entry survives the drop."""
    from paper_factory.literature.verify import build_references
    lit = tmp_path / "literature"
    lit.mkdir()
    (lit / "refs.bib").write_text(
        "@article{x, title={Attention Is All You Need}, "
        "doi={https://doi.org/10.1000/other}}\n",
        encoding="utf-8")
    ctx = _ctx(tmp_path)
    ctx.workspace.reports_dir.mkdir(parents=True, exist_ok=True)
    (ctx.workspace.reports_dir / "citation_audit.json").write_text(_json.dumps({
        "offline": False, "entries": [],
        "findings": [{"severity": "CRITICAL", "kind": "citation_identity_mismatch",
                      "key": "x", "doi": "10.1000/other"}]}))
    out = build_references(ctx)
    assert "x" in out.detail["dropped_false"], out.detail


def test_citation_identity_remediation_same_second_u4_not_blocked(tmp_path):
    """B-R3-1 (MAJOR): with sub-second timestamps a legitimate remediation
    final written right after the P21 audit WINS the freshness race — a fixed
    citation must not keep U4 red. (Equal timestamps still fail closed.)"""
    from paper_factory.release.closure import _u4
    ctx = _ctx_online(tmp_path)
    reports = ctx.workspace.reports_dir
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "citation_audit.json").write_text(_json.dumps({
        "audited_at": "2026-10-01T12:00:00.000001Z", "offline": False,
        "entries": [{"key": "fake", "verdict": "NOT_FOUND"}],
        "findings": [{"severity": "CRITICAL", "kind": "false_citation",
                      "key": "fake", "doi": "10.48550/arXiv.2401.99999"}]}))
    (reports / "citation_audit_final.json").write_text(_json.dumps({
        "audited_at": "2026-10-01T12:00:00.000002Z", "offline": False,
        "entries": [], "findings": [], "post_remediation": True}))
    state, note = _u4(ctx)
    assert state == "PASS", (state, note)


def test_citation_identity_utcnow_subsecond_resolution():
    """B-R3-1: utcnow must carry sub-second precision so a remediation re-audit
    directly after P21 in the same second orders correctly (ISO-8601 kept)."""
    import re as _re
    from paper_factory.core.util import utcnow
    ts = utcnow()
    assert _re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z$", ts), ts


# ---------------------------------------------------------------------------
# DataCite coverage (Pilot-3-Prep, 2026-10-01): OpenAlex does not index every
# registered DataCite DOI (e.g. 10.48550/arXiv.1706.03762 — the most-cited
# paper in the field 404s on OpenAlex while resolving fine on DataCite).
# Without a DataCite source a REAL arXiv citation becomes a false
# false_citation CRITICAL. resolve_doi therefore checks Crossref, OpenAlex
# AND DataCite; the DataCite title feeds the identity check as fallback.
# ---------------------------------------------------------------------------


def _fake_urlopen_route(routes):
    """routes: url-substring -> ('ok', payload) | ('http', code) | ('error',)"""
    import io
    import urllib.error

    class _Resp:
        def __init__(self, payload):
            self._b = _json.dumps(payload).encode()

        def read(self):
            return self._b

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake(req, timeout=20):
        url = req.full_url
        for needle, action in routes.items():
            if needle in url:
                if action[0] == "ok":
                    return _Resp(action[1])
                if action[0] == "http":
                    raise urllib.error.HTTPError(url, action[1], "x", {},
                                                 io.BytesIO(b""))
                raise urllib.error.URLError("down")
        raise AssertionError(f"unrouted url {url}")
    return fake


def test_datacite_third_source_resolves_real_arxiv_doi(tmp_path, monkeypatch):
    """Real-world repro 2026-10-01: Crossref never carries DataCite DOIs and
    OpenAlex missed 10.48550/arXiv.1706.03762 — only DataCite resolves it.
    A correct citation must be VERIFIED, not false_citation."""
    from paper_factory.literature import verify
    monkeypatch.setattr(verify.urllib.request, "urlopen", _fake_urlopen_route({
        "api.crossref.org": ("http", 404),
        "api.openalex.org": ("http", 404),
        "api.datacite.org": ("ok", {"data": {"attributes": {
            "titles": [{"title": "Attention Is All You Need"}]}}}),
    }))
    rec = verify.resolve_doi("10.48550/arXiv.1706.03762")
    assert rec["verdict"] == "VERIFIED", rec
    assert rec["title"] == "Attention Is All You Need"
    assert rec["sources"]["datacite"]["status"] == "found"

    # and the identity check consumes the DataCite title (wrong title fails)
    ctx = _ctx_online(tmp_path)
    entries = [{"key": "attn", "doi": None, "eprint": "1706.03762",
                "title": "A Completely Different Paper", "t4_derived": False}]
    records, findings, _ = verify._audit_entries(ctx, entries)
    assert records[0]["verdict"] == "IDENTITY_MISMATCH", records[0]
    assert findings[0]["kind"] == "citation_identity_mismatch"


def test_datacite_down_but_404_elsewhere_is_unknown_network(tmp_path, monkeypatch):
    """Source mix: one outage among 404s means we cannot KNOW the DOI is
    unregistered — UNKNOWN_NETWORK (A-D2 semantics), never a false
    NOT_FOUND/CRITICAL on a possibly real citation."""
    from paper_factory.literature import verify
    monkeypatch.setattr(verify.urllib.request, "urlopen", _fake_urlopen_route({
        "api.crossref.org": ("http", 404),
        "api.openalex.org": ("http", 404),
        "api.datacite.org": ("error",),
    }))
    rec = verify.resolve_doi("10.48550/arXiv.9999.99999")
    assert rec["verdict"] == "UNKNOWN_NETWORK", rec


def test_datacite_malformed_payload_no_crash(tmp_path, monkeypatch):
    """A DataCite payload without titles must not crash; title stays None and
    the identity check honestly reports unjudgeable."""
    from paper_factory.literature import verify
    monkeypatch.setattr(verify.urllib.request, "urlopen", _fake_urlopen_route({
        "api.crossref.org": ("http", 404),
        "api.openalex.org": ("http", 404),
        "api.datacite.org": ("ok", {"data": {"attributes": {}}}),
    }))
    rec = verify.resolve_doi("10.48550/arXiv.1706.03762")
    assert rec["verdict"] == "VERIFIED"
    assert rec.get("title") is None


# ---------------------------------------------------------------------------
# DataCite hardening (Reviewer A R5 D1-D3 / Reviewer B R5-1..R5-3)
# ---------------------------------------------------------------------------


def test_datacite_null_data_payloads_no_crash(tmp_path, monkeypatch):
    """A-D1/B-R5-1 (MAJOR): JSON:API-conformant `data: null` and non-dict
    payloads must never crash the whole citation audit — title stays None,
    the entry is VERIFIED on resolvability, identity honestly unjudgeable."""
    from paper_factory.literature import verify
    for payload in ({"data": None}, {"data": "oops"},
                    {"data": {"attributes": None}},
                    {"data": {"attributes": "oops"}},
                    {"data": {"attributes": {"titles": "oops"}}},
                    {"data": {"attributes": {"titles": [None, 42]}}}):
        monkeypatch.setattr(verify.urllib.request, "urlopen", _fake_urlopen_route({
            "api.crossref.org": ("http", 404),
            "api.openalex.org": ("http", 404),
            "api.datacite.org": ("ok", payload),
        }))
        rec = verify.resolve_doi("10.48550/arXiv.1706.03762")
        assert rec["verdict"] == "VERIFIED", (payload, rec)
        assert rec.get("title") is None, (payload, rec)


def test_datacite_html_entities_match_clean_bib_title(tmp_path, monkeypatch):
    """B-R5-2 (MAJOR): DataCite titles are registrant-supplied and may carry
    HTML entities — 'Pros &amp; Cons' must match the bib's 'Pros & Cons',
    never a false CRITICAL. Unescaping lives in _norm_title (both sides)."""
    from paper_factory.literature import verify
    monkeypatch.setattr(verify.urllib.request, "urlopen", _fake_urlopen_route({
        "api.crossref.org": ("http", 404),
        "api.openalex.org": ("http", 404),
        "api.datacite.org": ("ok", {"data": {"attributes": {
            "titles": [{"title": "Pros &amp; Cons of Attention"}]}}}),
    }))
    rec = verify.resolve_doi("10.1/x")
    assert rec["title"] == "Pros &amp; Cons of Attention"  # raw stored…
    ctx = _ctx_online(tmp_path)
    entries = [{"key": "k", "doi": "10.1/x", "eprint": None,
                "title": "Pros & Cons of Attention", "t4_derived": False}]
    records, findings, _ = verify._audit_entries(ctx, entries)
    assert records[0]["verdict"] == "VERIFIED", records[0]
    assert not any(f["kind"] == "citation_identity_mismatch" for f in findings)


def test_datacite_prefers_original_over_translated_title(tmp_path, monkeypatch):
    """B-R5-3 (MINOR): with multiple titles (translations first), prefer the
    entry without lang/titleType — the original work title."""
    from paper_factory.literature import verify
    monkeypatch.setattr(verify.urllib.request, "urlopen", _fake_urlopen_route({
        "api.crossref.org": ("http", 404),
        "api.openalex.org": ("http", 404),
        "api.datacite.org": ("ok", {"data": {"attributes": {"titles": [
            {"title": "Aufmerksamkeit ist alles", "lang": "de"},
            {"title": "Attention Is All You Need"}]}}}),
    }))
    rec = verify.resolve_doi("10.48550/arXiv.1706.03762")
    assert rec["title"] == "Attention Is All You Need", rec


def test_datacite_all_lang_titles_prefer_english_original(tmp_path, monkeypatch):
    """B-R6-1: when EVERY title carries a lang, the preference must still
    pick the English original over a first-listed translation."""
    from paper_factory.literature import verify
    monkeypatch.setattr(verify.urllib.request, "urlopen", _fake_urlopen_route({
        "api.crossref.org": ("http", 404),
        "api.openalex.org": ("http", 404),
        "api.datacite.org": ("ok", {"data": {"attributes": {"titles": [
            {"title": "Aufmerksamkeit ist alles", "lang": "de",
             "titleType": "TranslatedTitle"},
            {"title": "Attention Is All You Need", "lang": "en"}]}}}),
    }))
    rec = verify.resolve_doi("10.48550/arXiv.1706.03762")
    assert rec["title"] == "Attention Is All You Need", rec


def test_error_mix_is_unknown_network_not_false_not_found(tmp_path, monkeypatch):
    """A-D2: with ANY source unreachable the audit cannot KNOW the DOI is
    unregistered — 404+404+error must be UNKNOWN_NETWORK (MAJOR, entry stays),
    never NOT_FOUND (CRITICAL, entry dropped)."""
    from paper_factory.literature import verify
    monkeypatch.setattr(verify.urllib.request, "urlopen", _fake_urlopen_route({
        "api.crossref.org": ("error",),
        "api.openalex.org": ("http", 404),
        "api.datacite.org": ("error",),
    }))
    rec = verify.resolve_doi("10.1/maybe-real")
    assert rec["verdict"] == "UNKNOWN_NETWORK", rec


def test_http_500_mix_is_unknown_network_not_not_found(tmp_path, monkeypatch):
    """B-R6: a 5xx/rate-limit answer is not evidence of absence — a DOI that
    three flaky registries failed to serve must stay UNKNOWN_NETWORK (entry
    kept, MAJOR), never NOT_FOUND (CRITICAL, entry dropped)."""
    from paper_factory.literature import verify
    monkeypatch.setattr(verify.urllib.request, "urlopen", _fake_urlopen_route({
        "api.crossref.org": ("http", 500),
        "api.openalex.org": ("http", 429),
        "api.datacite.org": ("http", 503),
    }))
    rec = verify.resolve_doi("10.1/flaky")
    assert rec["verdict"] == "UNKNOWN_NETWORK", rec
    # and the all-404 case is still a true NOT_FOUND
    monkeypatch.setattr(verify.urllib.request, "urlopen", _fake_urlopen_route({
        "api.crossref.org": ("http", 404),
        "api.openalex.org": ("http", 404),
        "api.datacite.org": ("http", 404),
    }))
    rec = verify.resolve_doi("10.1/really-gone")
    assert rec["verdict"] == "NOT_FOUND", rec


def test_empty_openalex_title_does_not_block_datacite_fallback(tmp_path, monkeypatch):
    """A-D3: an empty-string OpenAlex title must not block the DataCite
    fallback title."""
    from paper_factory.literature import verify
    monkeypatch.setattr(verify.urllib.request, "urlopen", _fake_urlopen_route({
        "api.crossref.org": ("http", 404),
        "api.openalex.org": ("ok", {"title": ""}),
        "api.datacite.org": ("ok", {"data": {"attributes": {
            "titles": [{"title": "The Real Title Here"}]}}}),
    }))
    rec = verify.resolve_doi("10.1/x")
    assert rec["title"] == "The Real Title Here", rec


# ---------------------------------------------------------------------------
# Draft-ref title cleanup (Pilot-3 identity rerun, 2026-10-01): the markdown
# reference parser's title zone carried bibliography apparatus ('arXiv
# preprint arXiv:…, 2024. URL'), venue sentences ('… In Proceedings of …')
# and orphaned author-list tails ('Dahl. On empirical comparisons…'). The
# citation-identity check compares the claimed title against the registry
# title — with the junk, EVERY draft-derived entry mismatched (verified by
# direct probe: all 12 already-verified pilot refs returned False). The fix
# narrows the claimed title in the parser (draft_refs._clean_title); the
# matcher itself stays strict.
# ---------------------------------------------------------------------------


def test_gap_p3_title_cleanup_strips_arxiv_apparatus():
    """'Title. arXiv preprint arXiv:XXXX, YEAR. URL' narrows to the title."""
    from paper_factory.literature.draft_refs import parse_markdown_refs
    bib = parse_markdown_refs(
        "# References\n\n"
        "\\[1\\] Dami Choi, Christopher J. Shallue, Zachary Nado, Jaehoon "
        "Lee, Chris J. Maddison, and George E. Dahl. On empirical comparisons "
        "of optimizers for deep learning. arXiv preprint arXiv:1910.05446, "
        "2019. URL https://arxiv.org/abs/1910.05446.\n")
    assert "title = {On empirical comparisons of optimizers for deep learning}" in bib, bib


def test_gap_p3_title_cleanup_strips_venue_sentence():
    """'. In International Conference on Learning Representations, 2022.' and
    '. Journal of Machine Learning Research, 23(120):1–39, 2022.' go."""
    from paper_factory.literature.draft_refs import parse_markdown_refs
    bib = parse_markdown_refs(
        "# References\n\n"
        "\\[3\\] Tim Dettmers, Mike Lewis, Sam Shleifer, and Luke Zettlemoyer. "
        "8-bit optimizers via block-wise quantization. In International "
        "Conference on Learning Representations, 2022. URL "
        "https://openreview.net/forum?id=shpkpVXzo3h.\n\n"
        "\\[5\\] William Fedus, Barret Zoph, and Noam Shazeer. Switch "
        "transformers: Scaling to trillion parameter models with simple and "
        "efficient sparsity. Journal of Machine Learning Research, "
        "23(120):1-39, 2022. URL https://www.jmlr.org/papers/v23/21-0998.html.\n")
    assert "title = {8-bit optimizers via block-wise quantization}" in bib, bib
    assert ("title = {Switch transformers: Scaling to trillion parameter "
            "models with simple and efficient sparsity}") in bib, bib


def test_gap_p3_title_cleanup_strips_doi_apparatus():
    """'Datasheets for datasets. Communications of the ACM, 64(12):86–92,
    2021. doi: 10.1145/3458723.' narrows to the title (no URL at all)."""
    from paper_factory.literature.draft_refs import parse_markdown_refs
    bib = parse_markdown_refs(
        "# References\n\n"
        "\\[6\\] Timnit Gebru, Jamie Morgenstern, Briana Vecchione, and Kate "
        "Crawford. Datasheets for datasets. Communications of the ACM, "
        "64(12):86-92, 2021. doi: 10.1145/3458723.\n")
    assert "title = {Datasheets for datasets}" in bib, bib


def test_gap_p3_title_cleanup_drops_orphaned_author_tail():
    """The last-initial split leaves tails like 'Dahl. <title>.' /
    'Kingma and Jimmy Ba. <title>.' — the tail goes, the title stays."""
    from paper_factory.literature.draft_refs import parse_markdown_refs
    bib = parse_markdown_refs(
        "# References\n\n"
        "\\[9\\] Diederik P. Kingma and Jimmy Ba. Adam: A method for "
        "stochastic optimization. In International Conference on Learning "
        "Representations, 2015. URL https://arxiv.org/abs/1412.6980.\n\n"
        "\\[20\\] Ashish Vaswani, Noam Shazeer, Niki Parmar, Jakob Uszkoreit, "
        "Llion Jones, Aidan N. Gomez, Lukasz Kaiser, and Illia Polosukhin. "
        "Attention is all you need. In Advances in Neural Information "
        "Processing Systems, volume 30, 2017. URL "
        "https://papers.neurips.cc/paper/2017/hash/x-Abstract.html.\n")
    assert "title = {Adam: A method for stochastic optimization}" in bib, bib
    assert "title = {Attention is all you need}" in bib, bib


def test_gap_p3_title_cleanup_position0_in_guard():
    """A title legitimately STARTING with 'In …' must never be cut."""
    from paper_factory.literature.draft_refs import _clean_title
    assert _clean_title("In search of mass invariance") == \
        ("In search of mass invariance", False)


def test_gap_p3_title_cleanup_never_empty():
    """Degenerate entries keep their raw title rather than emitting ''."""
    from paper_factory.literature.draft_refs import parse_markdown_refs
    bib = parse_markdown_refs(
        "# References\n\n"
        "\\[1\\] Jane Doe. arXiv preprint arXiv:2401.01234, 2024. "
        "URL https://arxiv.org/abs/2401.01234.\n")
    assert "title = {}" not in bib


# the 12 refs the 2026-09-30 pilot run VERIFIED, claimed-as-parsed vs
# registry-resolved — every pair must MATCH after cleanup (offline fixture,
# resolved titles taken from citation_audit_final.json of that run)
_PILOT3_IDENTITY_PAIRS = [
    ("On empirical comparisons of optimizers for deep learning. arXiv "
     "preprint arXiv:1910.05446, 2019. URL",
     "On Empirical Comparisons of Optimizers for Deep Learning"),
    ("Datasheets for datasets. Communications of the ACM, 64(12):86-92, "
     "2021. doi: 10.1145/3458723.", "Datasheets for datasets"),
    ("State of the art: Reproducibility in artificial intelligence. In "
     "Proceedings of the Thirty-Second AAAI Conference on Artificial "
     "Intelligence, volume 32, 2018. doi: 10.1609/aaai.v32i1.11503. URL",
     "State of the Art: Reproducibility in Artificial Intelligence"),
    ("Deep networks with stochastic depth. In European Conference on "
     "Computer Vision, pages 646-661, 2016. doi: 10.1007/978-3-319-46493-0_39.",
     "Deep Networks with Stochastic Depth"),
    ("Kingma and Jimmy Ba. Adam: A method for stochastic optimization. In "
     "International Conference on Learning Representations, 2015. URL",
     "Adam: A Method for Stochastic Optimization"),
    ("SentencePiece: A simple and language independent subword tokenizer and "
     "detokenizer for neural text processing. In Proceedings of the 2018 "
     "Conference on Empirical Methods in Natural Language Processing: System "
     "Demonstrations, pages 66-71, 2018. doi: 10.18653/v1/D18-2012. URL",
     "SentencePiece: A simple and language independent subword tokenizer and "
     "detokenizer for neural text processing"),
    ("Muon is scalable for LLM training. arXiv preprint arXiv:2502.16982, "
     "2025. URL", "Muon is Scalable for LLM Training"),
    ("Model cards for model reporting. In Proceedings of the Conference on "
     "Fairness, Accountability, and Transparency, pages 220-229, 2019. doi: "
     "10.1145/3287560.3287596.", "Model Cards for Model Reporting"),
    ("The rationale of PROV. Web Semantics: Science, Services and Agents on "
     "the World Wide Web, 35(4):235-257, 2015. doi: "
     "10.1016/j.websem.2015.04.001. URL", "The rationale of PROV"),
    ("The FineWeb datasets: Decanting the web for the finest text data at "
     "scale. In Advances in Neural Information Processing Systems, volume "
     "37, 2024. doi: 10.52202/079017-0970. URL",
     "The FineWeb Datasets: Decanting the Web for the Finest Text Data at "
     "Scale"),
    ("Mixture-of-Depths: Dynamically allocating compute in transformer-based "
     "language models. arXiv preprint arXiv:2404.02258, 2024. URL",
     "Mixture-of-Depths: Dynamically Allocating Compute in Transformer-Based "
     "Language Models"),
    ("Le, Geoffrey Hinton, and Jeff Dean. Outrageously large neural "
     "networks: The sparsely-gated mixture-of-experts layer. In "
     "International Conference on Learning Representations, 2017. URL",
     "Outrageously Large Neural Networks: The Sparsely-Gated Mixture-of-"
     "Experts Layer"),
]


def test_gap_p3_title_cleanup_pilot3_pairs_all_match():
    """Every previously-verified pilot-3 reference must survive the identity
    check after cleanup (regression: without cleanup ALL 12 mismatched).
    Matches must be EXACT after normalization — a prefix-only match on a
    parser-cut title is downgraded to unjudgeable by the verifier
    (reviewer A R2-B1), so the pilot must not rely on it."""
    from paper_factory.literature.draft_refs import _clean_title
    from paper_factory.literature.verify import _norm_title, _titles_match
    for claimed, resolved in _PILOT3_IDENTITY_PAIRS:
        cleaned, _cut = _clean_title(claimed)
        assert _titles_match(cleaned, resolved) is True, \
            f"claimed={claimed!r} cleaned={cleaned!r} resolved={resolved!r}"
        assert _norm_title(cleaned) == _norm_title(resolved), \
            f"prefix-only match would be downgraded: {cleaned!r}"


# ---------------------------------------------------------------------------
# Reviewer-A R2 hardening of the title cleanup (2026-10-01):
# B1 cut-produced prefix must not prove identity; B2 no narrowing below
# 2 tokens; B4 'arXiv'/'URL' as genuine title words must not cut;
# B5 venue detection generalized to any capitalized year-carrying sentence.
# ---------------------------------------------------------------------------


def test_gap_p3_b1_cut_prefix_match_is_unjudgeable(tmp_path, monkeypatch):
    """B1 (MAJOR): a parser-CUT title whose only match basis is the
    subtitle-prefix rule must NOT prove identity — the cut manufactured the
    prefix. Without the downgrade, a DOI of a different work whose title
    merely extends the cut fragment would PASS silently."""
    from paper_factory.literature import verify
    monkeypatch.setattr(
        verify, "resolve_doi",
        _fake_resolve_title("Adam: A Method for Stochastic Optimization"))
    ctx = _ctx_online(tmp_path)
    entries = [{"key": "cutpre", "doi": "10.48550/arXiv.1412.6980",
                "eprint": None, "title": "Adam: A method",
                "t4_derived": True, "title_cut": True}]
    records, findings, _ = verify._audit_entries(ctx, entries)
    assert records[0]["verdict"] == "VERIFIED"  # DOI resolution is real
    assert records[0]["identity_check"] == "unjudgeable", records
    assert any(f["kind"] == "identity_unjudgeable" and
               f["severity"] == "MINOR" for f in findings), findings
    # the SAME title WITHOUT the cut flag keeps the prefix tolerance —
    # an author-written short title is legitimate 'Title' vs
    # 'Title: Subtitle' evidence
    entries[0]["title_cut"] = False
    records2, _, _ = verify._audit_entries(ctx, entries)
    assert records2[0]["identity_check"] == "match", records2


def test_gap_p3_b1_cut_exact_match_still_passes(tmp_path, monkeypatch):
    """B1 complement: a cut title matching by full equality still proves
    identity (the pilot's 19 matches are all exact)."""
    from paper_factory.literature import verify
    monkeypatch.setattr(
        verify, "resolve_doi",
        _fake_resolve_title("Adam: A Method for Stochastic Optimization"))
    ctx = _ctx_online(tmp_path)
    entries = [{"key": "cutexact", "doi": "10.48550/arXiv.1412.6980",
                "eprint": None,
                "title": "Adam: A method for stochastic optimization",
                "t4_derived": True, "title_cut": True}]
    records, findings, _ = verify._audit_entries(ctx, entries)
    assert records[0]["identity_check"] == "match", records
    assert not [f for f in findings if f.get("key") == "cutexact"]


def test_gap_p3_b2_no_narrowing_below_two_tokens():
    """B2 (MAJOR): a >=2-token title is never narrowed below 2 tokens — that
    would downgrade a would-be CRITICAL mismatch to MINOR unjudgeable."""
    from paper_factory.literature.draft_refs import _clean_title
    raw = "Dahl. arXiv preprint arXiv:1910.05446, 2019."
    cleaned, cut = _clean_title(raw)
    # apparatus cut would leave 'Dahl' (1 token) → raw title kept instead
    assert (cleaned, cut) == (raw, False)


def test_gap_p3_b4_arxiv_and_url_as_title_words_not_cut():
    """B4 (MAJOR): 'arXiv' without an identifier and 'URL' as a word are
    genuine title content and must survive."""
    from paper_factory.literature.draft_refs import _clean_title
    assert _clean_title("A survey of arXiv preprints") == \
        ("A survey of arXiv preprints", False)
    assert _clean_title("What's in a URL? A study of web identifiers") == \
        ("What's in a URL? A study of web identifiers", False)


def test_gap_p3_b5_year_carrying_venue_sentence_cut():
    """B5 (MAJOR): venues outside the keyword list are caught by the generic
    'capitalized sentence carrying a year' rule."""
    from paper_factory.literature.draft_refs import _clean_title
    assert _clean_title(
        "A real result. PLOS ONE, 19(8):e123, 2023.") == ("A real result", True)
    assert _clean_title(
        "Another result. Bioinformatics, 36(4):1-9, 2020.") == \
        ("Another result", True)


def test_gap_p3_b3_name_tail_tradeoff_pinned_fail_visible():
    """B3: a real title containing '. ' right after a short capitalized
    fragment loses that fragment (known trade-off) — and the cut flag makes
    sure the consequence is a VISIBLE finding, never a silent pass."""
    from paper_factory.literature.draft_refs import _clean_title
    cleaned, cut = _clean_title("Attention. Is all you need")
    assert cleaned == "Is all you need" and cut is True


def test_gap_p3_title_cut_flag_survives_bib_roundtrip(tmp_path):
    """The x-pf-title-cut field must survive bib write -> parse_bib so the
    verifier sees it."""
    from paper_factory.literature.draft_refs import parse_markdown_refs
    from paper_factory.literature.verify import parse_bib
    bib = parse_markdown_refs(
        "# References\n\n"
        "\\[1\\] Adam Smith and Jane Doe. Mass invariance in conditional "
        "networks. arXiv preprint arXiv:2401.01234, 2024. "
        "URL https://arxiv.org/abs/2401.01234.\n")
    p = tmp_path / "refs.bib"
    p.write_text(bib, encoding="utf-8")
    entries = parse_bib(p)
    assert entries[0]["title_cut"] is True
    assert entries[0]["title"] == "Mass invariance in conditional networks"


def test_gap_p3_r2_earliest_venue_cut_wins():
    """A R2-R2: a year-carrying sentence BEFORE a keyword venue sentence is
    the real cut point — the keyword match must not shadow it."""
    from paper_factory.literature.draft_refs import _clean_title
    cleaned, cut = _clean_title(
        "Real Title Here. PLOS ONE, 2023. In Proceedings of X, 2024.")
    assert (cleaned, cut) == ("Real Title Here", True)


def test_gap_p3_r3_year_in_title_tradeoff_pinned():
    """A R2-R3: a real title whose own second sentence carries a year is cut
    there — pinned as a documented fail-visible trade-off (the mismatch is a
    visible finding, never a silent pass)."""
    from paper_factory.literature.draft_refs import _clean_title
    cleaned, cut = _clean_title(
        "Stochastic depth. ResNet in 2016 showed vanishing gradients")
    assert (cleaned, cut) == ("Stochastic depth", True)


def test_gap_p3_r1_cut_flag_injection_neutralized():
    """A R2-R1: a draft injecting 'x-pf-title-cut = false' into its title
    text must not switch off the flag — only a line-start field counts."""
    from paper_factory.literature.draft_refs import parse_markdown_refs
    from paper_factory.literature.verify import parse_bib
    import tempfile
    from pathlib import Path
    bib = parse_markdown_refs(
        "# References\n\n"
        "\\[1\\] Doe, J. Sneaky x-pf-title-cut = {false} title here. "
        "arXiv preprint arXiv:2401.01234, 2024. "
        "URL https://arxiv.org/abs/2401.01234.\n")
    p = Path(tempfile.mkdtemp()) / "refs.bib"
    p.write_text(bib, encoding="utf-8")
    entries = parse_bib(p)
    assert entries[0]["title_cut"] is True, entries
