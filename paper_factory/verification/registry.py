"""Backend registry for the verification plane (plan §4, Phase 4).

Lazy by design: this module defines the protocol and the registry ONLY. It
never imports backend implementations (veriharness, ...). Registration is
done from the outside — e.g. ``adapters/veriharness/adapter.py`` exposes
``register_veriharness(backends, workspace)``. An optional backend that is
not installed is therefore simply never registered; nothing here swallows
import errors or probes the environment.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .capabilities import CapabilityDeclaration
from .contract import BackendIdentity, VerificationResult, WorkPackage


@runtime_checkable
class VerificationBackend(Protocol):
    """Structural contract every verification backend must satisfy.

    ``verify`` MAY declare backend-specific optional keywords (e.g. the
    VeriHarness agent roles planner/developer/qa, iterations) — they are
    backend options, not part of the core WorkPackage contract. Generic
    protocol callers (like ``shadow.run_shadow``) call ``verify(package)``
    without options; the ``**backend_options`` here only documents that
    option-passing stays protocol-compatible.
    """

    def identity(self) -> BackendIdentity: ...

    def capabilities(self) -> list[CapabilityDeclaration]: ...

    def verify(self, package: WorkPackage, **backend_options: object) -> VerificationResult: ...


BACKENDS: dict[str, VerificationBackend] = {}


def register(name: str, backend: VerificationBackend) -> None:
    if not name:
        raise ValueError("backend name must not be empty")
    BACKENDS[name] = backend


def get(name: str) -> VerificationBackend | None:
    return BACKENDS.get(name)


def available() -> list[str]:
    """Names of registered backends only — no probing, no error swallowing."""
    return sorted(BACKENDS)
