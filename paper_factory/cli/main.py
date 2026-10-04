"""paper-factory CLI — the canonical entry point. Works with no interactive
harness running."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..core.config import default_config_dir, load_config
from ..core.util import utcnow
from ..dag.executor import (
    EXIT_INCOMPLETE,
    Executor,
    NodeContext,
    exit_code_for_overall,
    run_status_overall,
)
from ..dag.handlers import build_handlers
from ..state.store import Workspace


def _ctx(args: argparse.Namespace, run_id: str) -> NodeContext:
    ws = Workspace(Path(args.root))
    pf, prov, pol, reg = load_config(Path(args.config_dir))
    return NodeContext(
        workspace=ws,
        run_id=run_id,
        config=pf,
        providers=prov,
        policy=pol,
        marking=reg,
        offline=getattr(args, "offline", False),
        strict=getattr(args, "strict", False),
        target_venue=getattr(args, "target", None),
        config_dir=Path(args.config_dir),
    )


def _print_json(obj) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def cmd_doctor(args) -> int:
    from ..state.inventory import write_inventory

    state_dir = Path(__file__).resolve().parent.parent / "state"
    inv = write_inventory(state_dir / "doctor.json")
    _print_json({
        "written": str(state_dir / "doctor.json"),
        "harnesses": {k: v.get("present", False) for k, v in inv["harnesses"].items()},
        "research_systems": {k: v.get("present", False) for k, v in inv["research_systems"].items()},
    })
    return 0


def cmd_plan(args) -> int:
    ws = Workspace(Path(args.root))
    run_id = args.run_id or ws.latest_run_id() or "PLAN"
    ctx = _ctx(args, run_id)
    ex = Executor(ctx, build_handlers(ctx.config.verification.hoh_nodes,
                                      cfg_shadow_nodes=ctx.config.verification.shadow_nodes))
    _print_json({"run_id": run_id, "plan": ex.plan()})
    return 0


def _execute(args, run_id: str, resume: bool) -> int:
    ctx = _ctx(args, run_id)
    ctx.workspace.create_run(run_id)
    ex = Executor(ctx, build_handlers(ctx.config.verification.hoh_nodes,
                                      cfg_shadow_nodes=ctx.config.verification.shadow_nodes))
    if getattr(args, "dry_run", False):
        _print_json({"dry_run": True, "run_id": run_id, "plan": ex.plan()})
        return 0
    statuses = ex.execute(resume=resume)
    overall = run_status_overall(statuses)
    code = exit_code_for_overall(overall)
    _print_json({
        "run_id": run_id,
        "overall": overall,
        "exit_code": code,
        "statuses": {k: v.value for k, v in statuses.items()},
    })
    # Process-boundary contract: exit 0 means CLOSED and nothing else. Every
    # non-closed terminal state (FAILED/HUMAN_REQUIRED/INCOMPLETE/DEGRADED/
    # EMPTY) exits non-zero so unattended callers never see a false-green.
    # Usage errors keep exit 2 (argparse convention); dry-run is an explicit
    # operator plan print and stays 0 without claiming a pipeline result.
    return code


def cmd_run(args) -> int:
    run_id = args.run_id or f"run-{utcnow().replace(':', '').replace('-', '')}"
    return _execute(args, run_id, resume=False)


def cmd_complete(args) -> int:
    run_id = args.run_id or f"complete-{utcnow().replace(':', '').replace('-', '')}"
    return _execute(args, run_id, resume=getattr(args, "resume", False))


def cmd_resume(args) -> int:
    ws = Workspace(Path(args.root))
    run_id = args.run_id or ws.latest_run_id()
    if not run_id:
        print("no run to resume", file=sys.stderr)
        return 2
    return _execute(args, run_id, resume=True)


def cmd_status(args) -> int:
    ws = Workspace(Path(args.root))
    run_id = args.run_id or ws.latest_run_id()
    if not run_id:
        _print_json({"status": "no runs"})
        return 0
    _print_json({"run_id": run_id, "statuses": ws.all_node_statuses(run_id)})
    return 0


def cmd_report(args) -> int:
    ws = Workspace(Path(args.root))
    run_id = args.run_id or ws.latest_run_id()
    rep = ws.reports_dir / f"run_{run_id}.json" if run_id else None
    if rep and rep.exists():
        print(rep.read_text(encoding="utf-8"))
        return 0
    print(f"no report for run {run_id}", file=sys.stderr)
    return 2


def cmd_audit(args) -> int:
    ws = Workspace(Path(args.root))
    run_id = args.run_id or ws.latest_run_id()
    if not run_id:
        print("no run", file=sys.stderr)
        return 2
    _print_json({"run_id": run_id, "receipts": ws.receipts_for(run_id)})
    return 0


def cmd_release(args) -> int:
    ws = Workspace(Path(args.root))
    run_id = args.run_id or ws.latest_run_id()
    _print_json({"run_id": run_id, "release": "NOT_RUN", "reason": "release pipeline builds during P33-P35"})
    # fail-closed like the run commands: exit 0 is reserved for real success,
    # and this stub has never produced a release (reviewer B, post-pilot audit)
    return EXIT_INCOMPLETE


def cmd_intake(args) -> int:
    run_id = args.run_id or f"intake-{utcnow().replace(':', '').replace('-', '')}"
    return _execute(args, run_id, resume=False)


def cmd_compliance(args) -> int:
    """Standalone venue-compliance check (P32) without a full pipeline run."""
    from ..venue.compliance import run_venue_compliance

    ctx = _ctx(args, args.run_id or f"compliance-{utcnow().replace(':', '').replace('-', '')}")
    outcome = run_venue_compliance(ctx)
    ws = ctx.workspace
    report = {}
    rep_path = ws.reports_dir / "venue_compliance.json"
    if rep_path.exists():
        report = json.loads(rep_path.read_text(encoding="utf-8"))
    _print_json({"venue": report.get("venue"), "verdict": outcome.verdict.value,
                 "failed": report.get("failed", []), "checks": report.get("checks", {})})
    return 0 if outcome.verdict.value == "PASS" else EXIT_INCOMPLETE


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="paper-factory",
                                description="Harness-neutral evidence-first paper production system.")
    p.add_argument("--root", default=".", help="target project root (default: cwd)")
    p.add_argument("--config-dir", default=str(default_config_dir()))
    sub = p.add_subparsers(dest="command", required=True)

    def add(name, fn, **kw):
        sp = sub.add_parser(name, **kw)
        sp.add_argument("--run-id", default=None)
        sp.set_defaults(func=fn)
        return sp

    add("doctor", cmd_doctor)
    add("plan", cmd_plan)
    add("status", cmd_status)
    add("report", cmd_report)
    add("audit", cmd_audit)
    add("intake", cmd_intake)
    add("release", cmd_release)
    spc = add("compliance", cmd_compliance)
    spc.add_argument("--target", default=None, help="venue override (e.g. arxiv)")

    sp = add("run", cmd_run)
    sp.add_argument("--dry-run", action="store_true")
    sp.add_argument("--strict", action="store_true")
    sp.add_argument("--offline", action="store_true")
    sp.add_argument("--target", default=None)

    sp = add("complete", cmd_complete)
    sp.add_argument("--dry-run", action="store_true")
    sp.add_argument("--resume", action="store_true")
    sp.add_argument("--strict", action="store_true")
    sp.add_argument("--offline", action="store_true")
    sp.add_argument("--target", default=None)

    sp = add("resume", cmd_resume)
    sp.add_argument("--strict", action="store_true")
    sp.add_argument("--offline", action="store_true")
    sp.add_argument("--target", default=None)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
