"""Shared mapping engine for the interchange exporters (WP9/WP10/WP11).

One engine, two projections: `ExportBundle` validates the PF-side evidence
once — fail-visible, no silent repairs — and both `rocrate.py` and `prov.py`
build their format purely from a validated bundle. The Workflow Card
reuses the same validation via `ExportBundle.build` as well.

Validation rules (fail-visible by contract, mirroring the capsule/runner
docstrings):

- a receipt must belong to the capsule (capsule_id AND capsule_digest must
  match) — a receipt for a different declared computation can never be
  exported as if it ran this capsule;
- a completed receipt with empty outputs is rejected when the capsule
  declares expected outputs: the Process Run Crate profile expects
  `result` entities, and a "successful" run that produced no evidence is
  exactly what must not pass silently.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..reproduction.capsule import ExecutionReceipt, FileRef, ReproductionCapsule


class ExportError(RuntimeError):
    """Mandatory export input is missing or inconsistent. Raised before any
    output is produced — exports are all-or-nothing, never half-true."""


@dataclass(frozen=True)
class ExportBundle:
    """Validated PF-side evidence, consumed by every exporter."""

    capsule: ReproductionCapsule
    receipts: tuple[ExecutionReceipt, ...]

    @classmethod
    def build(
        cls,
        capsule: ReproductionCapsule,
        receipts: list[ExecutionReceipt] | tuple[ExecutionReceipt, ...] = (),
    ) -> ExportBundle:
        bundle = cls(capsule=capsule, receipts=tuple(receipts))
        bundle.validate()
        return bundle

    def validate(self) -> None:
        expected = list(self.capsule.expected_outputs)
        for receipt in self.receipts:
            if receipt.capsule_id != self.capsule.capsule_id:
                raise ExportError(
                    "receipt does not belong to this capsule: "
                    f"receipt.capsule_id={receipt.capsule_id!r}, "
                    f"capsule.capsule_id={self.capsule.capsule_id!r}")
            if receipt.capsule_digest != self.capsule.capsule_digest:
                raise ExportError(
                    "receipt capsule_digest does not match the capsule: "
                    f"receipt={receipt.capsule_digest}, "
                    f"capsule={self.capsule.capsule_digest} — not the same "
                    "declared computation")
            if (receipt.status == "completed" and not receipt.outputs
                    and expected):
                raise ExportError(
                    f"receipt {receipt.execution_id} is completed but carries "
                    "no output hashes while the capsule declares "
                    f"expected_outputs={expected} — refusing to export a run "
                    "with no output evidence")

    # -- projections used by the format exporters -------------------------- #

    @property
    def inputs(self) -> tuple[FileRef, ...]:
        return tuple(self.capsule.input_refs)

    @property
    def configs(self) -> tuple[FileRef, ...]:
        return tuple(self.capsule.config_refs)

    @property
    def code(self) -> tuple[FileRef, ...]:
        return tuple(self.capsule.code_refs)

    @property
    def dependency_lock(self) -> FileRef | None:
        return self.capsule.environment.dependency_lock_ref

    def declared_refs(self) -> tuple[FileRef, ...]:
        """Every declared file (inputs + configs + code + dependency lock).
        Order is deterministic (grouped, then by rel_path within the group)."""
        refs: list[FileRef] = []
        for group in (self.inputs, self.configs, self.code):
            refs.extend(group)
        if self.dependency_lock is not None:
            refs.append(self.dependency_lock)
        return tuple(refs)

    def output_variants(self) -> dict[str, tuple[FileRef, ...]]:
        """rel_path -> tuple of distinct FileRefs (one per distinct sha256)
        across all receipts, sorted by hash. A single entry means every run
        produced identical content for that path; multiple entries mean the
        path is declared-nondeterministic or genuinely divergent — the
        exporters must represent each variant as its own entity."""
        by_path: dict[str, dict[str, FileRef]] = {}
        for receipt in self.receipts:
            for ref in receipt.outputs:
                by_path.setdefault(ref.rel_path, {})[ref.sha256] = ref
        return {
            path: tuple(variants[h] for h in sorted(variants))
            for path, variants in sorted(by_path.items())
        }
