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

STATE_DIR = Path(__file__).resolve().parent.parent / "state"
REPO = STATE_DIR.parents[1]

_BADGE = {
    "PASS": "#22c55e", "DEGRADED": "#eab308", "FAIL": "#ef4444",
    "HUMAN_REQUIRED": "#a855f7", "UNAVAILABLE": "#64748b", "NOT_RUN": "#94a3b8",
    "SKIPPED_DEPENDENCY": "#f97316", "GATE": "#3b82f6",
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
        fam = (info.get("backend") or {}).get("family", "unknown")
        board_rows.append(row([f"Provider {name}", _badge(state),
                               html.escape(f"family={fam} marking={info.get('marking_status', 'unknown')}")]))

    dag_rows = [row([nid, _badge(state)]) for nid, state in sorted(run_statuses.items())]
    closure_rows = [row([uid, _badge(v["state"]), html.escape(v["note"][:90])])
                    for uid, v in (closure.get("invariants") or {}).items()]

    gap_rows = [row([html.escape(r["req"]), _badge(r["class"]),
                     html.escape(str(r["evidence"])[:110])])
                for r in matrix.get("requirements", [])]

    hoh_html = ""
    if hoh:
        hoh_html = (f"<p>Run <code>{html.escape(str(hoh.get('run_id')))}</code> — "
                    f"{_badge(str(hoh.get('verdict', 'NOT_RUN')))} "
                    f"receipts: <b>{len(hoh.get('receipts') or [])}</b> · "
                    f"accepted: {html.escape(str(hoh.get('accepted')))} · "
                    f"stage: {html.escape(str(hoh.get('stage')))}</p>")
    else:
        hoh_html = f"<p>{_badge('NOT_RUN')} no live HoH evidence recorded</p>"

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

<h2>6 · Synthetischer E2E</h2>
<div class="card"><p>exit={e2e.get('exit_code', '—')} · {html.escape(str(e2e.get('summary_line', '—')))}</p></div>

<h2>7 · Parallelitäts-Audit (B1 / O177)</h2>
<div class="card"><p>{html.escape(str(concurrency.get('verdict', '—')))}</p>
<p class="muted">{html.escape(str((concurrency.get('updates') or [{}])[-1].get('finding', ''))[:400])}</p></div>

<h2>8 · Provenance-Policy</h2>
<div class="card"><p>{html.escape(json.dumps(provenance.get('policy', {}), ensure_ascii=False))}</p>
<p class="muted">{html.escape(str(provenance.get('honesty_note', '')))}</p></div>

<h2>9 · Git-State</h2>
<div class="card"><p>repo <code>{html.escape(git['repo'])}</code> · branch <code>{git['branch']}</code>
 · HEAD <code>{git['head']}</code> · commits {git['commits']} · dirty files: {len(git['dirty'])}</p></div>
</body></html>"""

    out = out or (REPO / "dashboard" / "index.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(doc, encoding="utf-8")
    return out
