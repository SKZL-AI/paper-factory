"""Deterministic DAG executor with honest terminal states and resume support."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..core.config import MarkingRegistry, PaperFactoryConfig, ProviderPolicyConfig, ProvidersConfig
from ..core.results import Verdict
from ..core.util import sha256_json, utcnow, write_json
from ..state.store import Workspace
from .nodes import NODE_MAP, NODES, Node, topo_order


@dataclass
class NodeOutcome:
    verdict: Verdict
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class NodeContext:
    workspace: Workspace
    run_id: str
    config: PaperFactoryConfig
    providers: ProvidersConfig
    policy: ProviderPolicyConfig
    marking: MarkingRegistry
    router: Any = None          # providers.router.ProviderRouter, set lazily
    offline: bool = False
    strict: bool = False
    target_venue: str | None = None
    node_statuses: dict[str, Verdict] = field(default_factory=dict)


Handler = Callable[[NodeContext, Node], NodeOutcome]

OK_STATES = {Verdict.PASS, Verdict.DEGRADED}


class Executor:
    def __init__(self, ctx: NodeContext, handlers: dict[str, Handler]):
        self.ctx = ctx
        self.handlers = handlers
        self.ws = ctx.workspace

    def plan(self) -> list[dict[str, Any]]:
        rows = []
        for nid in topo_order():
            n = NODE_MAP[nid]
            rows.append({
                "id": n.id, "name": n.name, "kind": n.kind, "deps": list(n.deps),
                "writes_final_prose": n.writes_final_prose, "veriharness": n.veriharness,
                "optional": n.optional,
                "current_status": self.ws.node_status(self.ctx.run_id, n.id),
            })
        return rows

    def execute(self, resume: bool = True) -> dict[str, Verdict]:
        statuses: dict[str, Verdict] = {}
        for nid in topo_order():
            node = NODE_MAP[nid]
            dep_states = [statuses[d] for d in node.deps]
            if any(s in (Verdict.FAIL, Verdict.INVALIDATED) for s in dep_states):
                verdict = Verdict.FAIL if self.ctx.strict else Verdict.SKIPPED_DEPENDENCY
                statuses[nid] = verdict
                self._record(node, verdict, {"reason": "dependency_failed"})
                continue
            if any(s in (Verdict.HUMAN_REQUIRED,) for s in dep_states):
                statuses[nid] = Verdict.SKIPPED_DEPENDENCY
                self._record(node, Verdict.SKIPPED_DEPENDENCY, {"reason": "dependency_human_required"})
                continue
            blocking = (Verdict.SKIPPED_DEPENDENCY, Verdict.FAIL, Verdict.NOT_RUN,
                        Verdict.UNSUPPORTED_ENVIRONMENT, Verdict.INVALIDATED)
            if any(s in blocking for s in dep_states):
                statuses[nid] = Verdict.SKIPPED_DEPENDENCY
                self._record(node, Verdict.SKIPPED_DEPENDENCY, {"reason": "dependency_not_satisfied"})
                continue
            existing = self.ws.node_status(self.ctx.run_id, nid)
            if resume and existing in (Verdict.PASS.value, Verdict.DEGRADED.value):
                statuses[nid] = Verdict(existing)
                continue
            handler = self.handlers.get(nid)
            if handler is None:
                outcome = NodeOutcome(Verdict.NOT_RUN, {"reason": "no handler registered"})
            else:
                self.ws.event(self.ctx.run_id, "node_start", nid)
                try:
                    outcome = handler(self.ctx, node)
                except Exception as exc:  # a crashed node is FAIL with the error on record
                    outcome = NodeOutcome(Verdict.FAIL, {"exception": f"{type(exc).__name__}: {exc}"})
            statuses[nid] = outcome.verdict
            self._record(node, outcome.verdict, outcome.detail)
            self.ws.event(self.ctx.run_id, "node_end", nid, {"verdict": outcome.verdict.value})
        self.ctx.node_statuses = statuses
        self._write_run_report(statuses)
        return statuses

    def _record(self, node: Node, verdict: Verdict, detail: dict[str, Any]) -> None:
        self.ws.set_node_status(self.ctx.run_id, node.id, verdict.value, detail)

    def _write_run_report(self, statuses: dict[str, Verdict]) -> None:
        report = {
            "run_id": self.ctx.run_id,
            "finished_at": utcnow(),
            "statuses": {k: v.value for k, v in statuses.items()},
            "summary": {
                "pass": sum(1 for v in statuses.values() if v == Verdict.PASS),
                "degraded": sum(1 for v in statuses.values() if v == Verdict.DEGRADED),
                "fail": sum(1 for v in statuses.values() if v in (Verdict.FAIL, Verdict.INVALIDATED)),
                "human_required": sum(1 for v in statuses.values() if v == Verdict.HUMAN_REQUIRED),
                "not_run": sum(1 for v in statuses.values() if v == Verdict.NOT_RUN),
                "skipped": sum(1 for v in statuses.values() if v == Verdict.SKIPPED_DEPENDENCY),
            },
        }
        write_json(self.ws.reports_dir / f"run_{self.ctx.run_id}.json", report)
        digest = sha256_json(report["statuses"])
        self.ws.event(self.ctx.run_id, "run_report", payload={"statuses_sha256": digest})


def run_status_overall(statuses: dict[str, Verdict | str]) -> str:
    """Canonical overall-state aggregation — the single truth for CLI and dashboard.

    Precedence (fail-closed): FAILED > HUMAN_REQUIRED > INCOMPLETE > DEGRADED > CLOSED.
    A DEGRADED node must never disappear into a blind CLOSED; an unknown node id or
    an unknown state string is never a CLOSED either. Note on hand-maintained status
    dicts (dashboard summaries): an ABSENT optional node contributes nothing (treated
    like not-run), while a DEGRADED optional node stays visible — summaries should
    therefore record optional nodes explicitly (post-pilot review B-G9).
    """
    if not statuses:
        return "EMPTY"
    norm: dict[str, Verdict | str] = {}
    for nid, v in statuses.items():
        if isinstance(v, Verdict):
            norm[nid] = v
        else:
            try:
                norm[nid] = Verdict(str(v))
            except ValueError:
                norm[nid] = str(v)  # unknown state string — fails the closed-world check
    if any(nid not in NODE_MAP for nid in norm):
        return "INCOMPLETE"
    values = set(norm.values())
    if values & {Verdict.FAIL, Verdict.INVALIDATED}:
        return "FAILED"
    if Verdict.HUMAN_REQUIRED in values:
        return "HUMAN_REQUIRED"
    if not values <= OK_STATES | {Verdict.SKIPPED_DEPENDENCY, Verdict.NOT_RUN}:
        return "INCOMPLETE"
    # a CLOSED/DEGRADED verdict requires the full required DAG to have been
    # evaluated — absent nodes are unproven, not silent skips (reviewer B-F4)
    missing_required = [nid for nid, n in NODE_MAP.items()
                        if not n.optional and nid not in norm]
    if missing_required:
        return "INCOMPLETE"
    skipped_required = [
        nid for nid, v in norm.items()
        if v in (Verdict.SKIPPED_DEPENDENCY, Verdict.NOT_RUN) and not NODE_MAP[nid].optional
    ]
    p35 = norm.get("P35")
    # closure never evaluated (or required nodes never ran) -> pipeline incomplete
    if p35 in (Verdict.SKIPPED_DEPENDENCY, Verdict.NOT_RUN) or skipped_required:
        return "INCOMPLETE"
    # a degraded node/closure is reported honestly, never rounded up to CLOSED
    if Verdict.DEGRADED in values:
        return "DEGRADED"
    if p35 is not None and p35 is not Verdict.PASS:
        return "INCOMPLETE"
    return "CLOSED"


# CLI process-exit contract — the boundary unattended callers (CI, herdr,
# VeriHarness, shell scripts) actually see. Exit 0 signals CLOSED and nothing
# else; every other overall state is non-zero. 2 is deliberately NOT a run
# state: this CLI already uses 2 for usage errors (argparse, "no run to
# resume", "no report"), so run states start at 3 to keep the meanings distinct.
EXIT_CLOSED = 0
EXIT_FAILED = 1
EXIT_HUMAN_REQUIRED = 3
EXIT_INCOMPLETE = 4
EXIT_DEGRADED = 5
EXIT_EMPTY = 6
EXIT_UNKNOWN = 7  # defensive: an unmapped overall string must never exit 0

OVERALL_EXIT_CODES = {
    "CLOSED": EXIT_CLOSED,
    "FAILED": EXIT_FAILED,
    "HUMAN_REQUIRED": EXIT_HUMAN_REQUIRED,
    "INCOMPLETE": EXIT_INCOMPLETE,
    "DEGRADED": EXIT_DEGRADED,
    "EMPTY": EXIT_EMPTY,
}


def exit_code_for_overall(overall: str) -> int:
    """Canonical process-exit mapping for run_status_overall() values.

    Invariant: exit 0 <=> overall == "CLOSED". Any unknown/future overall
    string fails closed to EXIT_UNKNOWN (non-zero), never to 0.
    """
    return OVERALL_EXIT_CODES.get(overall, EXIT_UNKNOWN)


__all__ = [
    "EXIT_CLOSED",
    "EXIT_DEGRADED",
    "EXIT_EMPTY",
    "EXIT_FAILED",
    "EXIT_HUMAN_REQUIRED",
    "EXIT_INCOMPLETE",
    "EXIT_UNKNOWN",
    "NODES",
    "OK_STATES",
    "OVERALL_EXIT_CODES",
    "Executor",
    "Handler",
    "NodeContext",
    "NodeOutcome",
    "exit_code_for_overall",
    "run_status_overall",
]
