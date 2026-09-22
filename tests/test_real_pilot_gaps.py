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
