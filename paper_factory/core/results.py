"""Verdict/result enums. States are honest: nothing is silently rounded up to PASS."""
from __future__ import annotations

import enum


class Verdict(str, enum.Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    DEGRADED = "DEGRADED"
    HUMAN_REQUIRED = "HUMAN_REQUIRED"
    UNAVAILABLE = "UNAVAILABLE"
    NOT_RUN = "NOT_RUN"
    UNSUPPORTED_ENVIRONMENT = "UNSUPPORTED_ENVIRONMENT"
    INVALIDATED = "INVALIDATED"
    SKIPPED_DEPENDENCY = "SKIPPED_DEPENDENCY"

    @property
    def is_ok(self) -> bool:
        return self in {Verdict.PASS, Verdict.DEGRADED}

    @property
    def blocks_closure(self) -> bool:
        return self in {Verdict.FAIL, Verdict.INVALIDATED}


class ClaimStatus(str, enum.Enum):
    PROPOSED = "PROPOSED"
    EVIDENCE_FOUND = "EVIDENCE_FOUND"
    VERIFIED = "VERIFIED"
    PARTIAL = "PARTIAL"
    CONTRADICTED = "CONTRADICTED"
    UNSUPPORTED = "UNSUPPORTED"
    RETIRED = "RETIRED"


class Severity(str, enum.Enum):
    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    MINOR = "MINOR"
    NIT = "NIT"


class Disposition(str, enum.Enum):
    RESOLVED = "RESOLVED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    ACCEPTED_LIMITATION = "ACCEPTED_LIMITATION"
    AUTHOR_DECISION = "AUTHOR_DECISION"
    DEFERRED = "DEFERRED"  # concrete action identified, needs writer/human
    UNRESOLVED = "UNRESOLVED"  # remediation attempted, post-condition not met
    INVALID_REMEDIATION_ARTIFACT = "INVALID_REMEDIATION_ARTIFACT"  # broken binding


# dispositions that legitimately close a CRITICAL/MAJOR finding; everything
# else (None, DEFERRED, UNRESOLVED, INVALID_REMEDIATION_ARTIFACT) blocks closure
CLOSED_DISPOSITIONS = {Disposition.RESOLVED, Disposition.NOT_APPLICABLE,
                       Disposition.ACCEPTED_LIMITATION, Disposition.AUTHOR_DECISION}


class EvidenceTier(str, enum.Enum):
    T0 = "T0"  # empirical source evidence
    T1 = "T1"  # derived evidence
    T2 = "T2"  # external literature
    T3 = "T3"  # project rationale / chat provenance
    T4 = "T4"  # manuscript prose / drafts
