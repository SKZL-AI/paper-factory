"""Reproduction differential (WP6): compare two ExecutionReceipts.

Classification rules — adversarial tests pin every branch:

- UNAVAILABLE: either side did not run to a clean exit (status != completed
  or exit_code != 0). Nothing to compare.
- INCOMPARABLE: the capsule_digests differ — by construction these are not
  the same declared computation, so no output comparison is meaningful.
- REPRODUCED_EXACT: same capsule_digest, identical output sets, all content
  hashes equal. This is the only claim made from hashes alone.
- NONDETERMINISTIC_DECLARED: same capsule_digest; every differing output is
  covered by an explicit nondeterminism declaration in the capsule, all
  other outputs hash-equal. Declarations are matched by fnmatch glob against
  paths relative to the capsule root.
- REPRODUCED_SEMANTIC: same capsule_digest; every differing output is either
  declared-nondeterministic or accepted by an explicitly declared domain
  rule (e.g. float_tolerance) verified against actual content, all other
  outputs hash-equal. SEMANTIC IS NEVER CLAIMED WITHOUT A DECLARED RULE
  plus content evidence — if the rule cannot be evaluated (no content loader)
  the output counts as unexplained and the result is MISMATCH.
- MISMATCH: same capsule_digest but outputs differ with no declared
  explanation, or an expected output is missing on one side.

Default for files is the exact content hash; semantic rules are opt-in,
declared in the capsule, and content-verified via caller-provided loaders
(receipts carry hashes, and hashes alone can never prove float equality).
"""
from __future__ import annotations

import enum
import fnmatch
import json
from collections.abc import Callable

from .capsule import ExecutionReceipt, ReproductionCapsule, SemanticRule


class ReproClassification(str, enum.Enum):
    REPRODUCED_EXACT = "REPRODUCED_EXACT"
    REPRODUCED_SEMANTIC = "REPRODUCED_SEMANTIC"
    MISMATCH = "MISMATCH"
    NONDETERMINISTIC_DECLARED = "NONDETERMINISTIC_DECLARED"
    UNAVAILABLE = "UNAVAILABLE"
    INCOMPARABLE = "INCOMPARABLE"


class ReproductionComparison:
    """Structured differential result (dataclass-free to stay dependency-light,
    but immutable-by-convention value object)."""

    def __init__(self, classification: ReproClassification,
                 differing_outputs: tuple[str, ...] = (),
                 missing_outputs: tuple[str, ...] = (),
                 notes: tuple[str, ...] = ()) -> None:
        self.classification = classification
        self.differing_outputs = differing_outputs
        self.missing_outputs = missing_outputs
        self.notes = notes

    def __eq__(self, other: object) -> bool:
        return isinstance(other, ReproductionComparison) and \
            self.__dict__ == other.__dict__

    def __repr__(self) -> str:
        return (f"ReproductionComparison({self.classification.value}, "
                f"differing={list(self.differing_outputs)}, "
                f"missing={list(self.missing_outputs)})")


def _unavailable_reason(r: ExecutionReceipt, side: str) -> str | None:
    if r.status != "completed":
        return f"{side}: status={r.status} ({r.failure_reason or 'no reason'})"
    if r.exit_code != 0:
        return f"{side}: exit_code={r.exit_code}"
    return None


def _floats_equal_within(a: object, b: object, tolerance: float) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) <= tolerance
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(
            _floats_equal_within(x, y, tolerance) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(
            _floats_equal_within(a[k], b[k], tolerance) for k in a)
    return a == b


def _semantic_match(rule: SemanticRule, content_a: bytes,
                    content_b: bytes) -> bool:
    if rule.kind != "float_tolerance":
        return False
    try:
        doc_a = json.loads(content_a)
        doc_b = json.loads(content_b)
    except (ValueError, UnicodeDecodeError):
        return False  # rule not applicable to non-JSON content: unexplained
    return _floats_equal_within(doc_a, doc_b, rule.tolerance)


def compare_executions(
    a: ExecutionReceipt,
    b: ExecutionReceipt,
    capsule: ReproductionCapsule | None = None,
    *,
    content_a: Callable[[str], bytes] | None = None,
    content_b: Callable[[str], bytes] | None = None,
) -> ReproductionComparison:
    """Compare two receipts. `capsule` supplies the nondeterminism and
    semantic declarations; `content_a`/`content_b` load output content by
    rel_path from each side (required to evaluate semantic rules — hashes
    alone can never prove tolerance equality)."""
    for receipt, side in ((a, "a"), (b, "b")):
        reason = _unavailable_reason(receipt, side)
        if reason is not None:
            return ReproductionComparison(ReproClassification.UNAVAILABLE,
                                          notes=(reason,))

    if a.capsule_digest != b.capsule_digest:
        return ReproductionComparison(
            ReproClassification.INCOMPARABLE,
            notes=(("capsule_digests differ — not the same declared "
                   "computation"),))

    outs_a = {f.rel_path: f.sha256 for f in a.outputs}
    outs_b = {f.rel_path: f.sha256 for f in b.outputs}
    missing = tuple(sorted(outs_a.keys() ^ outs_b.keys()))
    if missing:
        return ReproductionComparison(ReproClassification.MISMATCH,
                                      missing_outputs=missing,
                                      notes=(("outputs present on only one "
                                             "side"),))
    differing = tuple(sorted(p for p in outs_a if outs_a[p] != outs_b[p]))
    if not differing:
        return ReproductionComparison(ReproClassification.REPRODUCED_EXACT)

    declared_nondet = [d.pattern for d in capsule.nondeterministic_outputs] \
        if capsule else []
    rules = capsule.semantic_rules if capsule else []

    def is_declared_nondet(path: str) -> bool:
        return any(fnmatch.fnmatch(path, pat) for pat in declared_nondet)

    def rule_for(path: str) -> SemanticRule | None:
        return next((r for r in rules if fnmatch.fnmatch(path, r.applies_to)),
                    None)

    unexplained: list[str] = []
    used_semantic = False
    for path in differing:
        if is_declared_nondet(path):
            continue
        rule = rule_for(path)
        if (rule is not None and content_a is not None
                and content_b is not None):
            try:
                if _semantic_match(rule, content_a(path), content_b(path)):
                    used_semantic = True
                    continue
            except OSError:
                pass
        unexplained.append(path)

    if unexplained:
        return ReproductionComparison(
            ReproClassification.MISMATCH, differing_outputs=tuple(differing),
            notes=(f"unexplained differing outputs: {sorted(unexplained)}",))
    if used_semantic:
        return ReproductionComparison(
            ReproClassification.REPRODUCED_SEMANTIC,
            differing_outputs=tuple(differing),
            notes=(("differing outputs accepted via declared semantic rules "
                   "and/or nondeterminism declarations"),))
    return ReproductionComparison(
        ReproClassification.NONDETERMINISTIC_DECLARED,
        differing_outputs=tuple(differing),
        notes=(("all differing outputs covered by nondeterminism "
               "declarations"),))
