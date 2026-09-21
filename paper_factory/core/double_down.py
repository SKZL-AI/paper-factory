"""Double-down loop recorder (L17): an R&D negative is never an endpoint.

Semantics enforced here:
- the measurement verdict itself is never touched (firewall: Messung ≠ Konsequenz);
- each round is a sequential PAIR (2 perspectives) with context escalation
  (inherits all prior failures; never repeats a refuted path);
- minimum 5 rounds unless (a) an empirically proven fruitful result
  (early exit allowed) or (b) documented certainty of unsolvability;
- every round is a ledger entry.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .util import append_jsonl, read_jsonl, utcnow

MIN_ROUNDS = 5


def open_double_down(state_dir: Path, *, finding: str, root_cause: str,
                     root_cause_proof: str) -> dict[str, Any]:
    entry = {
        "kind": "double_down_open",
        "opened_at": utcnow(),
        "finding": finding,
        "root_cause": root_cause,
        "root_cause_proof": root_cause_proof,
        "measurement_verdict_untouched": True,
        "rounds": [],
    }
    append_jsonl(state_dir / "double_down_ledger.jsonl", entry)
    return entry


def record_round(state_dir: Path, *, finding: str, round_no: int,
                 perspectives: tuple[str, str], candidates: list[str],
                 verdict: str, inherited_failures: list[str]) -> dict[str, Any]:
    if len(perspectives) != 2:
        raise ValueError("L17: each round is a sequential PAIR (exactly 2 perspectives)")
    entry = {
        "kind": "double_down_round",
        "recorded_at": utcnow(),
        "finding": finding,
        "round": round_no,
        "perspectives": list(perspectives),
        "candidates_tried": candidates,
        "inherited_failures_from_prior_rounds": inherited_failures,
        "verdict": verdict,
    }
    append_jsonl(state_dir / "double_down_ledger.jsonl", entry)
    return entry


def may_close(state_dir: Path, finding: str, *, fruitful_proof: str | None = None,
              unsolvable_reason: str | None = None) -> tuple[bool, str]:
    rounds = [e for e in read_jsonl(state_dir / "double_down_ledger.jsonl")
              if e.get("kind") == "double_down_round" and e.get("finding") == finding]
    if fruitful_proof:
        return True, f"early exit: fruitful result proven ({fruitful_proof})"
    if len(rounds) >= MIN_ROUNDS and unsolvable_reason:
        return True, f"closed after {len(rounds)} rounds: {unsolvable_reason}"
    if len(rounds) >= MIN_ROUNDS and not unsolvable_reason:
        return False, "5+ rounds reached but no documented unsolvability reason"
    return False, f"only {len(rounds)}/{MIN_ROUNDS} rounds documented"
