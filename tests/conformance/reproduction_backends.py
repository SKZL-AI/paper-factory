"""Reproduction-backend conformance registry (v1.4 WP-A).

The semantics every Reproduction backend must honour, derived from what the
PF native local runner (WP5) and the Snakemake adapter (WP7) actually
implement today — deliberately NOT generalized beyond that:

1.  input binding      — declared code/config/input refs are hash-verified
                          before anything executes (CapsuleIntegrityError);
                          a backend run directory must not even be created.
2.  output binding     — declared expected_outputs are collected with content
                          hashes; a completed job reports exactly the files
                          the patterns match.
3.  undeclared output  — a job writing outside expected_outputs raises
                          UndeclaredOutputError (fail-visible, not sanitized).
4.  environment        — the receipt carries an honest backend identity
                          (kind, name, resolved version — never fabricated).
5.  failure            — a job exiting nonzero is recorded in the receipt
                          (status=failed), never raised, never hidden.
6.  timeout            — exceeding the timeout is recorded (status=timeout,
                          exit_code=None), the wrapper is reaped.
7.  duplicate execution— the same capsule run twice yields REPRODUCED_EXACT.
8.  partial outputs    — a job that succeeds but omits an expected output is
                          recorded honestly (fewer outputs, still completed);
                          the differential classifies MISMATCH/missing.
9.  cleanup            — no backend-owned scratch leaks; the caller's capsule
                          root is never polluted with backend metadata
                          (staging pattern for external backends).
10. nondeterminism     — outputs declared nondeterministic may differ between
                          runs of the same capsule (NONDETERMINISTIC_DECLARED);
                          the same difference without a declaration is MISMATCH.
11. receipt            — mandatory fields, capsule_digest identical to the
                          capsule's own digest, ordered timestamps.
12. availability       — an external backend whose binary is missing raises
                          its UnavailableError (fail-visible), never fakes.

The suite in ``test_reproduction_backends.py`` instantiates this registry
for every registered backend. External backends are skipped honestly when
their binary is absent. Real executions only — no LLM, no HoH, no network.
"""
from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from paper_factory.reproduction import (
    ExecutionReceipt,
    FileRef,
    LocalReproductionRunner,
    NondeterminismDecl,
    ReproductionCapsule,
    SnakemakeBackend,
    SnakemakeUnavailableError,
    sha256_file,
    snakemake_binary,
)
from paper_factory.reproduction import snakemake_backend

PILOT_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "repro_pilot"


@dataclass(frozen=True)
class BackendSpec:
    """One backend instantiation of the conformance suite."""

    name: str
    factory: Callable[[], object]
    available: bool
    skip_reason: str | None
    invoke: Callable[[object, ReproductionCapsule, Path, Path | None, float],
                     ExecutionReceipt]
    has_external_binary: bool
    binary_module: object | None      # module owning the resolver fn
    binary_attr: str | None           # resolver attribute name
    unavailable_exc: type[Exception] | None
    leak_glob: str | None             # private scratch dirs, None if none
    metadata_dirs: tuple[str, ...]    # backend bookkeeping never in caller root


def _local_invoke(runner, capsule, root, work, timeout) -> ExecutionReceipt:
    return runner.run(capsule, root, timeout=timeout)


def _external_invoke(runner, capsule, root, work, timeout) -> ExecutionReceipt:
    return runner.run(capsule, root, timeout=timeout, run_dir=work)


BACKENDS: list[BackendSpec] = [
    BackendSpec(
        name="local",
        factory=LocalReproductionRunner,
        available=True,
        skip_reason=None,
        invoke=_local_invoke,
        has_external_binary=False,
        binary_module=None,
        binary_attr=None,
        unavailable_exc=None,
        leak_glob=None,
        metadata_dirs=(),
    ),
    BackendSpec(
        name="snakemake",
        factory=SnakemakeBackend,
        available=snakemake_binary() is not None,
        skip_reason="snakemake not installed (optional extra)",
        invoke=_external_invoke,
        has_external_binary=True,
        binary_module=snakemake_backend,
        binary_attr="snakemake_binary",
        unavailable_exc=SnakemakeUnavailableError,
        leak_glob="pf-snakemake-*",
        metadata_dirs=(".snakemake",),
    ),
]


def ensure_available(spec: BackendSpec) -> None:
    """Skip this conformance instance honestly when the backend is absent."""
    import pytest

    if not spec.available:
        pytest.skip(spec.skip_reason)


# --------------------------------------------------------------------------- #
# Capsule builders (shared by every backend instance)
# --------------------------------------------------------------------------- #


def pilot_capsule() -> ReproductionCapsule:
    """Pre-built deterministic pilot capsule with the interpreter swapped for
    the test's own executable (the committed JSON stays path-free)."""
    capsule = ReproductionCapsule.model_validate_json(
        (PILOT_FIXTURE / "capsule.json").read_text(encoding="utf-8"))
    return capsule.model_copy(update={"command": [sys.executable, *capsule.command[1:]]})


def pilot_root(tmp_path: Path, name: str = "pilot") -> Path:
    root = tmp_path / name
    shutil.copytree(PILOT_FIXTURE, root)
    return root


def script_capsule(root: Path, code: str, outputs: list[str],
                   *, cwd: str = ".") -> ReproductionCapsule:
    """A capsule around a single stdlib script placed in `root` (which the
    caller creates and populates). Declares the script as a code ref."""
    script = root / "case.py"
    script.write_text(code, encoding="utf-8")
    rel = "case.py" if cwd == "." else f"{cwd}/case.py"
    return ReproductionCapsule(
        capsule_id="case-1",
        command=[sys.executable, "case.py"],
        cwd=cwd,
        code_refs=[FileRef(rel_path=rel, sha256=sha256_file(script))],
        environment={"python_version": "3", "platform": "test"},
        expected_outputs=outputs,
        producer={"kind": "pf_native", "name": "conformance", "version": "0"},
    )
