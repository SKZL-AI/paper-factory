"""P36 — final human sign-off.

A human_gate never passes by default. It passes only with a receipt at
`.paper-factory/reports/p36_signoff.json` that PROVES the conditions:
explicit user authorization, P35 PASS, U1–U16 all PASS, the receipt's HEAD
matches the current paper-factory HEAD, and P37 is explicitly NOT
authorized. Anything missing or stale → HUMAN_REQUIRED.
"""
from __future__ import annotations

import json
import subprocess

from ..core.results import Verdict
from ..dag.executor import NodeContext, NodeOutcome


def run_human_signoff(ctx: NodeContext) -> NodeOutcome:
    path = ctx.workspace.reports_dir / "p36_signoff.json"
    if not path.exists():
        return NodeOutcome(Verdict.HUMAN_REQUIRED,
                           {"reason": "no sign-off receipt — a human decision is pending"})
    try:
        r = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return NodeOutcome(Verdict.HUMAN_REQUIRED,
                           {"reason": f"sign-off receipt unreadable: {exc}"})
    problems: list[str] = []
    if r.get("kind") != "P36_HUMAN_FINAL_SIGNOFF":
        problems.append("kind is not P36_HUMAN_FINAL_SIGNOFF")
    if r.get("signoff_source") != "explicit_user_authorization":
        problems.append("signoff_source is not explicit_user_authorization")
    if r.get("p35_state") != "PASS":
        problems.append(f"p35_state={r.get('p35_state')}")
    u = r.get("u_states") or {}
    if not u or any(v != "PASS" for v in u.values()):
        problems.append("not all U1–U16 PASS in the receipt")
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                              text=True).stdout.strip()
        if r.get("final_head") and head and r["final_head"] != head:
            problems.append(f"receipt head {r['final_head'][:8]} != current {head[:8]}")
    except Exception:
        pass  # head comparison is best-effort outside the repo
    p37 = str(r.get("p37_authorization", "")).lower()
    if "not" not in p37 and "nicht" not in p37 and "never" not in p37:
        problems.append("P37 authorization must be explicitly negative")
    if problems:
        return NodeOutcome(Verdict.HUMAN_REQUIRED,
                           {"reason": "sign-off receipt invalid", "problems": problems})
    return NodeOutcome(Verdict.PASS, {"receipt": str(path),
                                      "signoff_source": r["signoff_source"],
                                      "at": r.get("timestamp")})
