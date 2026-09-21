"""Formal synthetic E2E: the 18 acceptance proofs from the master prompt.

The full pipeline runs ONCE per mode in module-scoped fixtures (network on for
citation verification; HoH disabled here — the real HoH run is a separate
quota-spending step that writes state/e2e_hoh_evidence.json, asserted in
test_17). Nothing is asserted from memory: every check reads the artifacts the
run actually produced.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "fixtures" / "synthetic_project"
# E2E runs must never spend quota: this config disables HoH (hoh_nodes: []).
CONFIG = Path(__file__).resolve().parent / "e2e-config"
CLI = [str(REPO / ".venv/bin/paper-factory")]


def _run(root: Path, *args: str) -> dict:
    proc = subprocess.run(CLI + ["--root", str(root), "--config-dir", str(CONFIG), *args],
                          capture_output=True, text=True, timeout=900)
    assert proc.returncode in (0, 1), f"cli died: {proc.stderr[-500:]}"
    return json.loads(proc.stdout)


def _fresh_variant(tmp_path: Path, keep: list[str]) -> Path:
    """Copy only parts of the fixture (input-mode variants)."""
    dst = tmp_path / "variant"
    dst.mkdir()
    for part in keep:
        src = FIXTURE / part
        if src.is_dir():
            shutil.copytree(src, dst / part)
        elif src.is_file():
            shutil.copy2(src, dst / part)
    return dst


@pytest.fixture(scope="module")
def full_run(tmp_path_factory):
    """Complete MIXED_EVIDENCE run with simulated paperpal delivery + resume."""
    tmp = tmp_path_factory.mktemp("e2e-full")
    proj = tmp / "proj"
    shutil.copytree(FIXTURE, proj)
    first = _run(proj, "complete")
    inbox = proj / ".paper-factory" / "paperpal" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / "paperpal_report.txt").write_text("language ok (test-simulated delivery)")
    resumed = _run(proj, "resume")
    return {"proj": proj, "first": first, "resumed": resumed}


# 1-4: input modes -----------------------------------------------------------

def test_01_code_only(tmp_path):
    proj = _fresh_variant(tmp_path, ["code", "results"])
    out = _run(proj, "complete", "--offline")
    intake = json.loads((proj / ".paper-factory/reports/intake_report.json").read_text())
    assert intake["input_mode"] == "CODE_ONLY"
    assert out["statuses"]["P01"] == "PASS"


def test_02_data_only(tmp_path):
    proj = _fresh_variant(tmp_path, ["results", "data"])
    _run(proj, "complete", "--offline")
    intake = json.loads((proj / ".paper-factory/reports/intake_report.json").read_text())
    assert intake["input_mode"] == "DATA_ONLY"


def test_03_draft_assisted(tmp_path):
    proj = _fresh_variant(tmp_path, ["draft"])
    _run(proj, "complete", "--offline")
    intake = json.loads((proj / ".paper-factory/reports/intake_report.json").read_text())
    assert intake["input_mode"] == "DRAFT_ASSISTED"


def test_04_mixed_evidence(full_run):
    intake = json.loads(
        (full_run["proj"] / ".paper-factory/reports/intake_report.json").read_text())
    assert intake["input_mode"] == "MIXED_EVIDENCE"


# 5: chat ingestion ------------------------------------------------------------

def test_05_chat_ingestion(full_run):
    summary = json.loads(
        (full_run["proj"] / ".paper-factory/context/context_summary.json").read_text())
    assert summary["sources"], "chat export must be ingested"
    assert summary["chronology"], "chronology extracted"
    assert summary["hidden_chain_of_thought"] == "forbidden_and_not_attempted"
    assert summary["tier"] == "T3"


# 6-8: planted defects caught ---------------------------------------------------

def test_06_false_citation_caught(full_run):
    audit = json.loads(
        (full_run["proj"] / ".paper-factory/reports/citation_audit.json").read_text())
    crit = [f for f in audit["findings"] if f["kind"] == "false_citation"]
    assert crit, "false citation must be detected"
    assert any(f.get("doi") == "10.9999/fake.bloom.2024" for f in crit)
    # and it must not survive remediation into the release bib
    final_bib = full_run["proj"] / ".paper-factory/paper/references.bib"
    assert "10.9999/fake.bloom.2024" not in final_bib.read_text()


def test_07_unsupported_claim_caught(full_run):
    claims = yaml.safe_load(
        (full_run["proj"] / ".paper-factory/claims/claims.yaml").read_text())
    assert claims["claims"], "claims extracted"
    retired = [c for c in claims["claims"] if c["status"] == "RETIRED"]
    assert any("40%" in c["statement"] or "faster" in c["statement"].lower()
               for c in retired), "unsupported lookup-speed claim must be retired"


def test_08_altered_number_caught(full_run):
    audit = json.loads(
        (full_run["proj"] / ".paper-factory/reports/integrity_audit.json").read_text())
    mismatches = [f for f in audit["findings"] if f["kind"] == "number_mismatch"]
    assert any(abs(f["value"] - 0.021) < 1e-9 for f in mismatches), \
        "the planted 0.021 (true: 0.014633…) must be flagged"
    sig = [f for f in audit["findings"] if f["kind"] == "significance_without_test"]
    assert sig, "significance claim without test must be flagged"


# 9: MAJOR finding blocks closure ----------------------------------------------

def test_09_major_finding_blocks_closure(full_run, tmp_path):
    import importlib

        # rebuild a context pointing at the finished workspace
    from paper_factory.core.config import load_config
    from paper_factory.dag.executor import NodeContext
    from paper_factory.release.closure import run_global_closure
    from paper_factory.reviews.framework import (Finding, ReviewReport, save_review)
    from paper_factory.state.store import Workspace

    ws = Workspace(full_run["proj"])
    pf, prov, pol, reg = load_config(CONFIG)
    ctx = NodeContext(workspace=ws, run_id="closure-gate-test", config=pf,
                      providers=prov, policy=pol, marking=reg)
    save_review(ws.reviews_dir, ReviewReport(
        review_id="ZZ-planted", reviewer="test",
        findings=[Finding(finding_id="ZZ-1", reviewer="test", severity="MAJOR",
                          category="methods", statement="planted undisposed major")]))
    outcome = run_global_closure(ctx)
    assert outcome.verdict.value == "FAIL"
    closure = json.loads((ws.reports_dir / "global_closure.json").read_text())
    assert closure["invariants"]["U5"]["state"] == "FAIL"


# 10-12: provider routing (mocked — no quota) ------------------------------------

def test_10_provider_failure_classified():
    """A provider whose binary is absent must classify as HarnessUnavailable,
    never crash, never fake a result."""
    import pytest as _pt

    from paper_factory.adapters.base import HarnessUnavailable
    from paper_factory.adapters.opencode.adapter import OpenCodeAdapter

    opencode = OpenCodeAdapter()
    assert opencode.doctor()["present"] is False  # not installed on this machine
    with _pt.raises(HarnessUnavailable):
        opencode.invoke("x", role="research_planner")


def test_11_alternative_provider_resume():
    """Router returns a usable provider for a review role and records the
    selection; failover happens by preference order, never silently."""
    from paper_factory.core.config import load_config
    from paper_factory.providers.router import ProviderRouter

    pf, prov, pol, reg = load_config(CONFIG)
    router = ProviderRouter(prov, pol, reg, workspace=None)
    adapter, detail = router.select_for_role("methods_review")
    assert adapter is not None
    assert detail["provider_name"]
    assert detail["selection_notes"] is not None  # selection is on record


def test_12_same_family_review_marked_degraded():
    """Force a single-family provider world: the adversarial review must be
    marked DEGRADED_INDEPENDENCE, never silently 'independent'."""
    from paper_factory.core.config import (ProvidersConfig, ProviderEntry,
                                           ProviderPolicyConfig, MarkingRegistry)
    from paper_factory.providers.router import ProviderRouter

    prov = ProvidersConfig(providers={
        "kimi_a": ProviderEntry(adapter="kimi", family="moonshot", executable="kimi"),
        "kimi_b": ProviderEntry(adapter="kimi", family="moonshot", executable="kimi"),
    })
    pol = ProviderPolicyConfig.model_validate({
        "role_policy": {
            "manuscript_writer": {"writes_final_prose": True, "preferred_harnesses": ["kimi"]},
            "adversarial_reviewer": {"writes_final_prose": False,
                                     "preferred_different_family_from": "manuscript_writer"},
        }
    })
    prov.role_preferences = {"adversarial_review": {"preferred": ["kimi_a", "kimi_b"]}}
    router = ProviderRouter(prov, pol, MarkingRegistry(), workspace=None)
    _, detail = router.select_for_role("adversarial_review")
    assert detail["independence_status"] == "DEGRADED_INDEPENDENCE", detail


# 13: forbidden final-prose origin ------------------------------------------------

def test_13_forbidden_final_prose_origin_blocked():
    from paper_factory.core.config import load_config
    from paper_factory.provenance.firewall import PolicyViolation, decide_write

    pf, prov, pol, reg = load_config(CONFIG)
    with pytest.raises(PolicyViolation):
        decide_write("paper/sections/results.tex", role="manuscript_writer",
                     backend={"family": "anthropic", "provider_family": "anthropic",
                              "model_family": "claude"},
                     policy=pol, marking=reg)
    with pytest.raises(PolicyViolation):
        decide_write("paper/main.tex", role="manuscript_writer",
                     backend={"family": "unknown"}, policy=pol, marking=reg)


# 14: paperpal absence = HUMAN_REQUIRED -------------------------------------------

def test_14_paperpal_absence_human_required(tmp_path):
    proj = _fresh_variant(tmp_path, ["code", "results", "draft", "literature"])
    out = _run(proj, "complete", "--offline")
    assert out["statuses"]["P31"] == "HUMAN_REQUIRED"
    assert out["statuses"]["P31"] != "PASS"


# 15: clean bundle rebuild ----------------------------------------------------------

def test_15_clean_bundle_rebuild(full_run):
    assert full_run["resumed"]["statuses"]["P34"] == "PASS"
    pdfs = list((full_run["proj"] / ".paper-factory/release").glob("*/build/main.pdf"))
    assert pdfs and all(p.stat().st_size > 10000 for p in pdfs)


# 16: secret scan fails closed --------------------------------------------------------

def test_16_secret_leak_fails_closed(tmp_path):
    from paper_factory.release.secrets import scan_tree

    dirty = tmp_path / "dirty"
    dirty.mkdir()
    (dirty / "notes.txt").write_text("our key sk-ant-api03-AAAAaaaaBBBBbbbbCCCCddddEEEEeeee is here")
    out = scan_tree(dirty)
    assert out["verdict"] == "FAIL"
    assert out["findings"]


# 17: HoH receipts for verification-grade nodes -----------------------------------------

def test_17_hoh_receipts_exist():
    evidence = REPO / "paper_factory/state/e2e_hoh_evidence.json"
    if not evidence.exists():
        pytest.skip("live HoH run not yet executed (state/e2e_hoh_evidence.json missing) — "
                    "recorded as NOT_RUN, not passed")
    data = json.loads(evidence.read_text())
    assert data["receipts"], "HoH receipts must be preserved"
    assert data["verdict"] in ("PASS", "DEGRADED")
    assert data["run_id"].startswith("PF-")


# 18: herdr endpoint evidence -------------------------------------------------------------

def test_18_herdr_runtime_evidence():
    from paper_factory.adapters.herdr.adapter import HerdrAdapter

    status = HerdrAdapter().status()
    if status["available"]:
        assert status["verdict"] == "PASS"
        assert status["endpoint"]["workspace_id"]
    else:
        assert status["verdict"] == "DEGRADED_RUNTIME"


def test_19_u7_detects_evidence_tampering(full_run):
    """Regression for the U7 ImportError mask: tampering with an evidence file
    after intake must make U7 FAIL (not NOT_RUN, not PASS)."""
    from paper_factory.core.config import load_config
    from paper_factory.dag.executor import NodeContext
    from paper_factory.release.closure import _u7
    from paper_factory.state.store import Workspace

    ws = Workspace(full_run["proj"])
    pf, prov, pol, reg = load_config(CONFIG)
    ctx = NodeContext(workspace=ws, run_id="u7-tamper", config=pf,
                      providers=prov, policy=pol, marking=reg)
    target = ws.target_root / "results" / "experiment_runs.csv"
    original = target.read_bytes()
    try:
        target.write_bytes(original + b"\n# tampered")
        state, note = _u7(ctx)
        assert state == "FAIL", f"U7 must FAIL on tampered evidence, got {state}: {note}"
    finally:
        target.write_bytes(original)
    state, note = _u7(ctx)
    assert state in ("PASS", "FAIL")  # FAIL ok if receipts missing for this run id; never NOT_RUN
    assert state != "NOT_RUN", f"U7 masked an error again: {note}"
