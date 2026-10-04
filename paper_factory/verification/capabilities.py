"""Capability declarations for verification backends (plan §4, Phase 3).

Only the model and a plain construction helper live here. Actual capability
discovery reuses the existing doctor/inventory probes — no parallel stack.
"""
from __future__ import annotations

import enum

from .contract import BackendIdentity, Strict


class CapabilityStatus(str, enum.Enum):
    SUPPORTED = "SUPPORTED"
    SUPPORTED_DEGRADED = "SUPPORTED_DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"
    UNSUPPORTED = "UNSUPPORTED"
    REQUIRES_NETWORK = "REQUIRES_NETWORK"
    REQUIRES_HUMAN = "REQUIRES_HUMAN"


class CapabilityDeclaration(Strict):
    backend: BackendIdentity
    capability: str
    status: CapabilityStatus
    detail: str = ""


def declare(backend: BackendIdentity, capability: str, status: CapabilityStatus,
            detail: str = "") -> CapabilityDeclaration:
    return CapabilityDeclaration(backend=backend, capability=capability,
                                 status=status, detail=detail)
