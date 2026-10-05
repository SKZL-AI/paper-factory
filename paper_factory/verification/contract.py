"""Versioned contracts for the verification plane (plan §4, Phase 2).

PF owns these types; backends (pf_native, veriharness, external) consume
WorkPackage and produce VerificationResult. Strict everywhere: unknown
fields are rejected so provider-specific leakage cannot slip in silently.
Provider internals (blocked_kind, Herdr pane IDs, ...) belong in
raw_receipt_refs, never in these models.
"""
from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..core.results import EvidenceTier, Severity, Verdict

SCHEMA_VERSION = 1

_SHA256_PATTERN = r"[0-9a-f]{64}"

# Clock-skew tolerance for the future-timestamp check: a receipt stamped a few
# seconds "ahead" of the consumer's clock is tolerated (NTP skew between
# machines is real), anything beyond this is fail-visible. This is NOT a
# freshness bound — freshness is semantic (bindings), not wall-clock age.
_FUTURE_TOLERANCE = timedelta(seconds=30)


def utcnow() -> datetime:
    return datetime.now(UTC)


def normalize_statement(statement: str) -> str:
    """Whitespace-normalized form: single spaces, no leading/trailing whitespace."""
    return " ".join(statement.split())


def statement_digest(statement: str) -> str:
    return hashlib.sha256(normalize_statement(statement).encode("utf-8")).hexdigest()


class Strict(BaseModel):
    """Base: no unknown fields, no silent type reinterpretations."""

    model_config = ConfigDict(extra="forbid", frozen=False, str_strip_whitespace=True)


# --------------------------------------------------------------------------- #
# References
# --------------------------------------------------------------------------- #


class ArtifactRef(Strict):
    rel_path: str
    sha256: str = Field(pattern=_SHA256_PATTERN)
    kind: str

    @field_validator("rel_path")
    @classmethod
    def _no_control_chars(cls, v: str) -> str:
        """Fail-visible on control characters (\\n, \\r, \\t, \\0, ...): they
        would inject extra manifest lines into the artifact_binding digest
        (newline-separated '<sha256>  <rel_path>' format) — silently forging
        or splitting digest lines is exactly what the binding must prevent."""
        if any(ord(c) < 32 or ord(c) == 127 for c in v):
            raise ValueError("rel_path must not contain control characters")
        return v


def artifact_binding(artifacts: list[ArtifactRef]) -> str | None:
    """Single source of truth for binding a result to a work package's artifacts.

    - no artifacts → None (unbound; SEMANTIC_MATCH is then the honest
      differential outcome)
    - exactly one artifact → its sha256
    - more than one → manifest digest: sha256 over the sorted, newline-
      separated lines '<sha256>  <rel_path>' (two spaces). Deterministic and
      independent of artifact order — both differential sides must derive the
      binding through THIS function or MATCH is not provable.
    """
    if not artifacts:
        return None
    if len(artifacts) == 1:
        return artifacts[0].sha256
    lines = sorted(f"{a.sha256}  {a.rel_path}" for a in artifacts)
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


class EvidenceRef(Strict):
    evidence_id: str
    tier: EvidenceTier
    artifact: ArtifactRef | None = None


class BackendIdentity(Strict):
    kind: Literal["pf_native", "veriharness", "external"]
    name: str
    version: str
    detail: dict = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Work package & findings
# --------------------------------------------------------------------------- #


class WorkPackage(Strict):
    schema_version: Literal[1] = SCHEMA_VERSION
    package_id: str
    node_id: str
    spec_markdown: str
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    provenance: dict = Field(default_factory=dict)


class VerificationFinding(Strict):
    kind: str
    severity: Severity
    statement: str
    claim_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    statement_hash: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="before")
    @classmethod
    def _fill_statement_hash(cls, data: object) -> object:
        if isinstance(data, dict) and isinstance(data.get("statement"), str):
            data["statement_hash"] = statement_digest(data["statement"])
        return data


# --------------------------------------------------------------------------- #
# Results & receipts
# --------------------------------------------------------------------------- #


class VerificationResult(Strict):
    schema_version: Literal[1] = SCHEMA_VERSION
    package_id: str
    backend: BackendIdentity
    verdict: Verdict
    findings: list[VerificationFinding] = Field(default_factory=list)
    receipts: list[ExecutionReceipt] = Field(default_factory=list)
    artifact_sha256: str | None = Field(default=None, pattern=_SHA256_PATTERN)
    started_at: datetime
    finished_at: datetime
    failure_reason: str | None = None
    raw_receipt_refs: list[str] = Field(default_factory=list)

    def check_receipt_freshness(
        self,
        expect: ReceiptExpectation | None = None,
        *,
        raws: list[dict | None] | None = None,
    ) -> None:
        """Consumption-time freshness check for every ExecutionReceipt this
        result carries (WP2, v1.3). The gate path calls this before a
        result's receipts may satisfy a gate; the first failing receipt
        raises ReceiptFreshnessError (fail-visible, fail-fast).

        ``raws``: optional per-receipt raw JSON payloads (same order as
        self.receipts) enabling the missing-timestamp dimension; entries may
        be None where no raw payload exists.
        """
        for idx, receipt in enumerate(self.receipts):
            raw = raws[idx] if raws is not None and idx < len(raws) else None
            receipt.check_freshness(expect, raw=raw)


class ReceiptFreshnessError(ValueError):
    """Fail-visible at CONSUMPTION time (WP2, v1.3): an ExecutionReceipt that
    fails a semantic freshness check must never satisfy a gate. Loading stays
    lenient for backward compatibility (old v1.2 receipts still deserialize);
    the check runs where the receipt is USED, so a stale/replayed/rebound
    receipt breaks the consuming run loudly instead of silently green-lighting
    it."""


@dataclass(frozen=True)
class ReceiptExpectation:
    """The semantic context a receipt is consumed against.

    Freshness is NOT wall-clock age: a receipt is fresh iff it still belongs
    to the CURRENT artifact binding, backend, run and contract schema. All
    fields are optional — a dimension that is not knowable at the call site
    is not checked (fail-visible beats fail-spurious), except where noted.

    - artifact_sha256: the binding the receipt must carry; a mismatch means
      the receipt belongs to an older artifact state (stale receipt).
    - backend_kind: the backend the receipt must come from ("veriharness").
    - run_id: the run the receipt is being consumed for; together with
      known_receipt_runs this detects wrong-run usage and replay.
    - declared_schema_version: schema_version found in the receipt's raw
      JSON payload (absent = honest v1 default, consistent with the loading
      boundary; a present-but-wrong version is fail-visible).
    - now: reference clock for timestamp checks (tests inject fixed values).
    - known_receipt_runs: store-backed mapping receipt_id -> run_id already
      recorded in the state store; proves replay/wrong-run "soweit im Store
      nachweisbar". A receipt whose ID the store ties to another run is a
      replay even if every field matches.
    - max_age_seconds: OPTIONAL wall-clock guard, default None (off). Only
      when a caller sets it does age become a freshness dimension.
    """

    artifact_sha256: str | None = None
    backend_kind: str | None = None
    run_id: str | None = None
    declared_schema_version: int | None = None
    now: datetime | None = None
    known_receipt_runs: Mapping[str, str] | None = None
    max_age_seconds: float | None = None


class ExecutionReceipt(Strict):
    receipt_id: str
    backend: BackendIdentity
    artifact_sha256: str = Field(pattern=_SHA256_PATTERN)
    sha256: str = Field(pattern=_SHA256_PATTERN)
    created_at: datetime = Field(default_factory=utcnow)

    def check_freshness(
        self, expect: ReceiptExpectation | None = None, *, raw: dict | None = None
    ) -> None:
        """Semantic freshness check at consumption time (WP2, v1.3). Raises
        ReceiptFreshnessError on every provable contradiction; returns None
        when the receipt is fresh in the given expectation context.

        ``raw``: the receipt's raw JSON payload, when available. Two checks
        need it because pydantic model defaults hide them: a missing
        created_at (the model would silently fill utcnow()) and a
        schema_version key the strict model would reject at load time.
        Backward compatibility is preserved by checking at consumption, not
        at load: v1.2-era receipts without timestamps/schema_version still
        deserialize; a caller that consumes them without raw payloads simply
        cannot apply those two dimensions (documented, not assumed).
        """
        expect = expect or ReceiptExpectation()
        where = f"receipt {self.receipt_id!r}"

        if expect.declared_schema_version is not None and (
            expect.declared_schema_version != SCHEMA_VERSION
        ):
            raise ReceiptFreshnessError(
                f"{where}: schema_version {expect.declared_schema_version} does not match "
                f"current contract schema_version {SCHEMA_VERSION}; refusing to consume a "
                "receipt from an unknown contract generation"
            )
        if raw is not None and "created_at" not in raw:
            raise ReceiptFreshnessError(
                f"{where}: receipt payload carries no created_at timestamp; refusing to "
                "consume a receipt whose creation time is unprovable"
            )

        now = expect.now or datetime.now(UTC)
        if self.created_at > now + _FUTURE_TOLERANCE:
            raise ReceiptFreshnessError(
                f"{where}: created_at {self.created_at.isoformat()} is in the future "
                f"relative to the consumer clock ({now.isoformat()}); refusing to consume"
            )
        if expect.max_age_seconds is not None:
            age = (now - self.created_at).total_seconds()
            if age > expect.max_age_seconds:
                raise ReceiptFreshnessError(
                    f"{where}: age {age:.0f}s exceeds the configured wall-clock bound "
                    f"of {expect.max_age_seconds:.0f}s (optional guard, explicitly enabled "
                    "by the caller)"
                )

        if expect.artifact_sha256 is not None and (
            self.artifact_sha256 != expect.artifact_sha256
        ):
            raise ReceiptFreshnessError(
                f"{where}: bound to artifact {self.artifact_sha256}, but the current "
                f"binding is {expect.artifact_sha256} — stale receipt from an older "
                "artifact state; refusing to let it satisfy the current gate"
            )
        if expect.backend_kind is not None and self.backend.kind != expect.backend_kind:
            raise ReceiptFreshnessError(
                f"{where}: issued by backend {self.backend.kind!r}, expected "
                f"{expect.backend_kind!r}; wrong-backend receipt refused"
            )
        if expect.known_receipt_runs is not None:
            known_run = expect.known_receipt_runs.get(self.receipt_id)
            if known_run is not None and known_run != (expect.run_id or ""):
                raise ReceiptFreshnessError(
                    f"{where}: receipt_id is already recorded for run {known_run!r}, not "
                    f"{expect.run_id!r} — replay of a consumed receipt (store-backed "
                    "evidence); refusing to consume it again"
                )
