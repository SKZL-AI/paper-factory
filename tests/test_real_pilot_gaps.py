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
from paper_factory.statistics.metrics import run_statistics
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
    import hashlib
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
from paper_factory.dag.executor import (EXIT_DEGRADED, EXIT_EMPTY, EXIT_FAILED,
                                        EXIT_HUMAN_REQUIRED, EXIT_INCOMPLETE,
                                        EXIT_UNKNOWN, OVERALL_EXIT_CODES,
                                        exit_code_for_overall, run_status_overall)
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
    from paper_factory.reviews.framework import (Finding, ReviewReport,
                                                 save_review)
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
from paper_factory.claims.graph import (Claim, ClaimGraph, load_claims,
                                        save_claims)
from paper_factory.core.results import ClaimStatus, Disposition, Severity
from paper_factory.release.closure import _u5
from paper_factory.reviews.framework import (Finding, ReviewReport,
                                             load_reviews, save_review,
                                             unresolved_blocking)
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

    import paper_factory.literature.verify as verify

    def _rebuild_drops_key(ctx_):
        bib.write_text("@article{ok, doi={10.1/real}}\n", encoding="utf-8")
        return None

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

    import paper_factory.literature.verify as verify
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

    import paper_factory.literature.verify as verify

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

    import paper_factory.literature.verify as verify
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

    import paper_factory.literature.verify as verify
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
