"""Self-contained HTML dashboard for the PAPER FACTORY installation.

Deterministic: reads paper_factory/state/*.json (and an optional finished
workspace's reports) and embeds them verbatim. No external assets, no network.
"""
from __future__ import annotations

import html
import json
import subprocess
from pathlib import Path

from ..core.util import utcnow
from ..dag.executor import run_status_overall

STATE_DIR = Path(__file__).resolve().parent.parent / "state"
REPO = STATE_DIR.parents[1]

_BADGE = {
    "PASS": "#22c55e", "DEGRADED": "#eab308", "FAIL": "#ef4444",
    "HUMAN_REQUIRED": "#a855f7", "UNAVAILABLE": "#64748b", "NOT_RUN": "#94a3b8",
    "SKIPPED_DEPENDENCY": "#f97316", "GATE": "#3b82f6",
    "CLOSED": "#22c55e", "FAILED": "#ef4444", "INCOMPLETE": "#f97316",
    "EMPTY": "#64748b",
}


def _load(name: str) -> dict:
    p = STATE_DIR / name
    return json.loads(p.read_text()) if p.exists() else {}


def _badge(state: str) -> str:
    color = _BADGE.get(state, "#64748b")
    return (f'<span style="background:{color};color:#0f172a;padding:2px 10px;'
            f'border-radius:12px;font-weight:600;font-size:12px">{html.escape(state)}</span>')


def _git_state() -> dict:
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=REPO, capture_output=True,
                              text=True).stdout.strip()

    return {"repo": str(REPO), "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
            "head": git("rev-parse", "--short", "HEAD"),
            "commits": git("rev-list", "--count", "HEAD"),
            "dirty": git("status", "--short").splitlines()}


def render_dashboard(workspace_reports: Path | None = None, out: Path | None = None) -> Path:
    doctor = _load("doctor.json")
    matrix = _load("veriharness_capability_matrix.json")
    providers = _load("provider_capabilities.json")
    harnesses = _load("harness_capabilities.json")
    provenance = _load("provenance_policy_report.json")
    e2e = _load("synthetic_e2e_report.json")
    hoh = _load("e2e_hoh_evidence.json")
    concurrency = _load("concurrency_audit.json")
    pilot = _load("real_pilot_01_summary.json")
    git = _git_state()

    run_statuses: dict[str, str] = {}
    closure: dict = {}
    if workspace_reports and workspace_reports.exists():
        runs = sorted(workspace_reports.glob("run_*.json"))
        if runs:
            run_statuses = json.loads(runs[-1].read_text())["statuses"]
        gc = workspace_reports / "global_closure.json"
        if gc.exists():
            closure = json.loads(gc.read_text())

    def row(cells: list[str]) -> str:
        return "<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"

    # system board
    board_rows = []
    for name, info in (harnesses.get("harnesses") or {}).items():
        present = (info.get("doctor") or {}).get("present")
        state = "PASS" if present else "UNAVAILABLE"
        board_rows.append(row([f"Harness {name}", _badge(state),
                               html.escape(str(info.get("version") or "—"))]))
    for name, info in (providers.get("providers") or {}).items():
        d = info.get("doctor") or {}
        state = "PASS" if d.get("present") else "UNAVAILABLE"
        fam = (info.get("backend") or {}).get("provider_family", "unknown")
        board_rows.append(row([f"Provider {name}", _badge(state),
                               html.escape(f"family={fam} marking={info.get('marking_status', 'unknown')}")]))

    dag_rows = [row([nid, _badge(state)]) for nid, state in sorted(run_statuses.items())]
    closure_rows = [row([uid, _badge(v["state"]), html.escape(v["note"][:90])])
                    for uid, v in (closure.get("invariants") or {}).items()]

    gap_rows = [row([html.escape(r["req"]), _badge(r["class"]),
                     html.escape(str(r["evidence"])[:110])])
                for r in matrix.get("requirements", [])]

    e2e_rows = [row([html.escape(t["name"]), _badge(t["state"]),
                     f"{t['time_s']}s"]) for t in e2e.get("tests", [])]
    e2e_html = (f"<p>exit={e2e.get('exit_code', '—')} · "
                f"{html.escape(str(e2e.get('summary_line', '—')))}</p>"
                f"<table>{''.join(e2e_rows)}</table>" if e2e.get("tests")
                else f"<p>exit={e2e.get('exit_code', '—')} · "
                     f"{html.escape(str(e2e.get('summary_line', '—')))}</p>")

    hoh_html = ""
    if hoh:
        hoh_html = (f"<p>Run <code>{html.escape(str(hoh.get('run_id')))}</code> — "
                    f"{_badge(str(hoh.get('verdict', 'NOT_RUN')))} "
                    f"receipts: <b>{len(hoh.get('receipts') or [])}</b> · "
                    f"accepted: {html.escape(str(hoh.get('accepted')))} · "
                    f"stage: {html.escape(str(hoh.get('stage')))}</p>")
    else:
        hoh_html = f"<p>{_badge('NOT_RUN')} no live HoH evidence recorded</p>"

    def _pilot_card(pilot: dict, section: str, title: str) -> str:
        # canonical overall: computed by the same aggregation the CLI uses —
        # the stored field is never a second truth
        p_statuses = pilot.get("statuses") or {}
        p_overall = run_status_overall(p_statuses)
        p_dag = "".join(row([nid, _badge(state)])
                        for nid, state in sorted(p_statuses.items()))
        p_closure = "".join(row([uid, _badge(state)])
                            for uid, state in sorted((pilot.get("closure") or {}).items()))
        cm = pilot.get("claim_matrix") or {}
        p_claims = "".join(row([k, str(v)]) for k, v in cm.items() if k != "note")
        p_gaps = "".join(row([html.escape(g)]) for g in pilot.get("gaps", []))
        p_hr = "".join(row([html.escape(h)]) for h in pilot.get("human_required", []))
        rf = pilot.get("review_findings") or {}
        p_notes = "".join(row([f"<code>{html.escape(k)}</code>", html.escape(v)])
                          for k, v in sorted((pilot.get("status_notes") or {}).items()))
        corrections = (pilot.get("post_pilot_audit") or {}).get("corrections") or []
        p_corr = "".join(row([f"<code>{html.escape(str(c.get('field')))}</code>",
                              _badge(str(c.get("was"))), _badge(str(c.get("now"))),
                              html.escape(str(c.get("reason")))])
                         for c in corrections)
        corr_html = (f'<h3 style="color:#93c5fd">Post-Pilot-Audit-Korrekturen '
                     f'({html.escape(str((pilot.get("post_pilot_audit") or {}).get("commit", "")))})</h3>'
                     f"<table>{p_corr}</table>" if corrections else "")
        notes_html = (f'<h3 style="color:#93c5fd">Status-Erklärungen</h3><table>{p_notes}</table>'
                      if p_notes else "")
        claims_html = (f'<h3 style="color:#93c5fd">Claim-Status</h3><table>{p_claims}</table>'
                       if p_claims else "")
        return f"""
<h2>{section} · {html.escape(title)} — {html.escape(str(pilot.get('project', '')))}</h2>
<div class="card">
 <p>Modus <code>{html.escape(str(pilot.get('input_mode')))}</code> · run
 <code>{html.escape(str(pilot.get('run_id')))}</code> · overall
 {_badge(p_overall)} · baseline <code>{html.escape(str(pilot.get('baseline_head')))}</code>
 · Tests: {html.escape(str(pilot.get('tests')))}</p>
 <p class="muted">{html.escape(str(pilot.get('headline', '')))}</p>
 <p class="muted">Closure failed on: {html.escape(str(pilot.get('closure_failed')))}
 · unresolved blocking: {html.escape(str(pilot.get('unresolved_blocking')))}
 · review findings: {html.escape(json.dumps(rf))}</p>
 <h3 style="color:#93c5fd">Pipeline P00–P37</h3><table>{p_dag}</table>
 {notes_html}
 <h3 style="color:#93c5fd">Closure U1–U16</h3><table>{p_closure}</table>
 {corr_html}
 {claims_html}
 <h3 style="color:#93c5fd">Gaps</h3><table>{p_gaps}</table>
 <h3 style="color:#93c5fd">HUMAN_REQUIRED</h3><table>{p_hr}</table>
</div>"""

    pilot_html = ""
    if pilot:
        pilot_html += _pilot_card(pilot, "10", "REAL PILOT 01")
    rerun = _load("real_pilot_01_rerun_summary.json")
    if rerun:
        pilot_html += _pilot_card(rerun, "11", "REAL PILOT 01 — RE-RUN (post GAP-003/004/005/010/006)")
    pilot02 = _load("real_pilot_02_summary.json")
    if pilot02:
        pilot_html += _pilot_card(pilot02, "12", "REAL PILOT 02 — TSCG-2.0")
    pilot03 = _load("real_pilot_03_summary.json")
    if pilot03:
        pilot_html += _pilot_card(pilot03, "13", "REAL PILOT 03 — MassInv Paper 1 (Draft-References-Brücke)")

    doc = f"""<!DOCTYPE html>
<html lang="de"><head><meta charset="utf-8"><title>PAPER FACTORY — Dashboard</title>
<style>
 body {{ font-family: ui-sans-serif, system-ui, sans-serif; background:#0b1220; color:#e2e8f0; margin:0; padding:2rem; }}
 h1 {{ color:#f8fafc; }} h2 {{ color:#93c5fd; border-bottom:1px solid #1e293b; padding-bottom:.3rem; margin-top:2rem; }}
 table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; }}
 td {{ border-bottom: 1px solid #1e293b; padding: 6px 10px; font-size: 14px; }}
 tr:hover {{ background:#111a2e; }}
 code {{ background:#1e293b; padding:1px 6px; border-radius:4px; }}
 .card {{ background:#0f172a; border:1px solid #1e293b; border-radius:12px; padding:1rem 1.4rem; margin:1rem 0; }}
 .muted {{ color:#94a3b8; font-size:13px; }}
</style></head><body>
<h1>PAPER FACTORY — Projekt-Dashboard</h1>
<p class="muted">Generiert: {utcnow()} · deterministisch aus <code>paper_factory/state/*.json</code>
{(f" + Workspace-Reports {html.escape(str(workspace_reports))}" if workspace_reports else "")}</p>

<h2>1 · System-Status (Harnesses & Provider)</h2>
<div class="card"><table>{"".join(board_rows) or "<tr><td>keine Daten</td></tr>"}</table></div>

<h2>2 · DAG P00–P37 (letzter Lauf)</h2>
<div class="card"><table>{"".join(dag_rows) or "<tr><td>kein Lauf aufgezeichnet</td></tr>"}</table></div>

<h2>3 · Globale Closure U1–U16</h2>
<div class="card"><table>{"".join(closure_rows) or "<tr><td>keine Closure aufgezeichnet</td></tr>"}</table></div>

<h2>4 · VeriHarness-Capability-Matrix</h2>
<div class="card"><table>{"".join(gap_rows)}</table></div>

<h2>5 · HoH-Live-Evidenz</h2>
<div class="card">{hoh_html}</div>

<h2>6 · Synthetischer E2E (18 Akzeptanztests + Suite)</h2>
<div class="card">{e2e_html}</div>

<h2>7 · Parallelitäts-Audit (B1 / O177)</h2>
<div class="card"><p>{html.escape(str(concurrency.get('verdict', '—')))}</p>
<p class="muted">{html.escape(str((concurrency.get('updates') or [{}])[-1].get('finding', ''))[:400])}</p></div>

<h2>8 · Provenance-Policy</h2>
<div class="card"><p>{html.escape(json.dumps(provenance.get('policy', {}), ensure_ascii=False))}</p>
<p class="muted">{html.escape(str(provenance.get('honesty_note', '')))}</p></div>

<h2>9 · Git-State</h2>
<div class="card"><p>repo <code>{html.escape(git['repo'])}</code> · branch <code>{git['branch']}</code>
 · HEAD <code>{git['head']}</code> · commits {git['commits']} · dirty files: {len(git['dirty'])}</p>
<p class="muted">Snapshot zum Generierungszeitpunkt — ein committed Dashboard liegt
immer einen Commit hinter dem Commit, der es enthält (kein Self-Reference-Loop);
der aktuelle Runtime-HEAD ist nur per <code>git rev-parse</code> verbindlich.</p></div>

{pilot_html}
</body></html>"""

    out = out or (REPO / "dashboard" / "index.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(doc, encoding="utf-8")
    return out
