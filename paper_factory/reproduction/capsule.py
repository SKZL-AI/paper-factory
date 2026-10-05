"""Reproduction Capsule v1 — versioned, harness-neutral contract (ROADMAP v1.3, WP4).

PF owns these types; runners (pf_native local runner now, workflow backends
later) consume a ReproductionCapsule and produce an ExecutionReceipt. Strict
everywhere: unknown fields are rejected so provider-specific leakage cannot
slip in silently, and unknown/newer schema versions fail visibly.

Content-addressed identity: `capsule_digest` is a stable SHA-256 over exactly
the fields that semantically determine the scientific computation. Timestamps,
mtimes, random runtime fields, identifiers and comparison policy are excluded
by construction (the capsule carries no such fields in the digest payload).
`execution_id` (one concrete run) lives on the receipt and never enters the
digest — the digest is the semantic reproduction identity, not a run identity.

Digest field list (v1), all under canonical serialization
(`json.dumps(payload, sort_keys=True, separators=(",", ":"))`, UTF-8):

- schema_version (a v2 semantic change must not silently collide with v1)
- command (argv, order-preserving)
- cwd (working-directory semantics, relative to the capsule root)
- code_refs / config_refs / input_refs (rel_path + sha256, order-normalized
  by rel_path — the *set* of declared files binds, not the list order)
- parameters flagged deterministic=True (name + value, order-normalized)
- environment identity (python/tool versions, platform, dependency-lock
  reference, container image)

Excluded on purpose: capsule_id and provenance_refs (identifiers/provenance,
not computation), producer (who built the capsule, not what it computes),
expected_outputs and nondeterministic_outputs/semantic_rules (comparison
policy — two capsules differing only there describe the *same* computation),
and any timestamp/mtime/random field.

All rel_paths inside a capsule are relative to the capsule root; the process
runs in `capsule_root / cwd`. rel_paths reject control characters (same
convention as verification.artifact_binding: a newline in a path would
silently forge or split manifest lines), and — exactly like `cwd` — absolute
paths, backslashes and `..` (all variants a path could escape the root with).
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..verification.contract import BackendIdentity

SCHEMA_VERSION = 1

_SHA256_PATTERN = r"[0-9a-f]{64}"


def utcnow() -> datetime:
    return datetime.now(UTC)


def _check_no_control_chars(v: str, field_name: str) -> str:
    if any(ord(c) < 32 or ord(c) == 127 for c in v):
        raise ValueError(f"{field_name} must not contain control characters")
    return v


def sha256_file(path) -> str:
    """Streaming SHA-256 of a file (runner + tests)."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class Strict(BaseModel):
    """Base: no unknown fields, no silent type reinterpretations."""

    model_config = ConfigDict(extra="forbid", frozen=False, str_strip_whitespace=True)


# --------------------------------------------------------------------------- #
# References & environment
# --------------------------------------------------------------------------- #


class FileRef(Strict):
    """A declared or produced file: path relative to the capsule root + content hash."""

    rel_path: str
    sha256: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("rel_path")
    @classmethod
    def _rel_path_is_safe_relative(cls, v: str) -> str:
        """Same rules as ReproductionCapsule.cwd (review B-MINOR-2,
        2026-10-05): absolute paths, backslashes and '..' are rejected — a
        declared ref must stay inside the capsule root, never escape it or
        address foreign files via absolute paths / Windows separators."""
        _check_no_control_chars(v, "rel_path")
        if v.startswith("/") or "\\" in v:
            raise ValueError("rel_path must be a relative POSIX path")
        parts = [p for p in v.split("/") if p not in ("", ".")]
        if any(p == ".." for p in parts):
            raise ValueError("rel_path must not escape the capsule root (no '..')")
        return v


class EnvironmentIdentity(Strict):
    """What the environment must look like for the computation to be the same.

    All fields are identity data, not runtime telemetry; nothing here changes
    between two runs of the same capsule, so all of it belongs in the digest.
    """

    python_version: str
    platform: str  # e.g. "linux-x86_64" (os + machine)
    tool_versions: dict[str, str] = Field(default_factory=dict)
    dependency_lock_ref: FileRef | None = None
    container_image: str | None = None


# --------------------------------------------------------------------------- #
# Declarations & comparison policy (never in the digest)
# --------------------------------------------------------------------------- #


class ParameterDecl(Strict):
    """A declared parameter. deterministic=False marks runtime-varying input
    (e.g. a seed source the caller injects per run); it is recorded for
    provenance but excluded from the capsule_digest."""

    name: str
    value: str
    deterministic: bool = True


class NondeterminismDecl(Strict):
    """Declared nondeterminism for an output path (glob, matched with fnmatch
    against paths relative to the capsule root). The output may differ between
    runs of the same capsule without failing the differential — this is an
    explicit, upfront declaration, never a post-hoc excuse."""

    pattern: str
    reason: str


class SemanticRule(Strict):
    """Domain-specific comparison rule enabling REPRODUCED_SEMANTIC. Without a
    matching declared rule a differing output is NEVER classified semantic —
    the default for files is the exact content hash."""

    rule_id: str
    applies_to: str  # glob, matched with fnmatch against rel_paths
    kind: Literal["float_tolerance"] = "float_tolerance"
    tolerance: float = Field(gt=0.0)


# --------------------------------------------------------------------------- #
# Capsule & receipt
# --------------------------------------------------------------------------- #


class ReproductionCapsule(Strict):
    schema_version: Literal[1] = SCHEMA_VERSION
    capsule_id: str
    command: list[str] = Field(min_length=1)
    cwd: str = "."
    code_refs: list[FileRef] = Field(default_factory=list)
    config_refs: list[FileRef] = Field(default_factory=list)
    input_refs: list[FileRef] = Field(default_factory=list)
    parameters: list[ParameterDecl] = Field(default_factory=list)
    environment: EnvironmentIdentity
    expected_outputs: list[str] = Field(min_length=1)
    nondeterministic_outputs: list[NondeterminismDecl] = Field(default_factory=list)
    semantic_rules: list[SemanticRule] = Field(default_factory=list)
    producer: BackendIdentity
    provenance_refs: list[str] = Field(default_factory=list)

    @field_validator("command")
    @classmethod
    def _command_no_control_chars(cls, v: list[str]) -> list[str]:
        for entry in v:
            _check_no_control_chars(entry, "command entries")
        return v

    @field_validator("cwd")
    @classmethod
    def _cwd_is_safe_relative(cls, v: str) -> str:
        _check_no_control_chars(v, "cwd")
        if v.startswith("/") or "\\" in v:
            raise ValueError("cwd must be a relative POSIX path")
        parts = [p for p in v.split("/") if p not in ("", ".")]
        if any(p == ".." for p in parts):
            raise ValueError("cwd must not escape the capsule root (no '..')")
        return v or "."

    @property
    def capsule_digest(self) -> str:
        """Content-addressed semantic identity — see module docstring for the
        exact field list and canonical serialization. Stable across runs,
        machines-independent of where the capsule file lives."""
        payload = {
            "schema_version": self.schema_version,
            "command": list(self.command),
            "cwd": self.cwd,
            "code_refs": _sorted_ref_payload(self.code_refs),
            "config_refs": _sorted_ref_payload(self.config_refs),
            "input_refs": _sorted_ref_payload(self.input_refs),
            "parameters": sorted(
                ({"name": p.name, "value": p.value}
                 for p in self.parameters if p.deterministic),
                key=lambda d: d["name"],
            ),
            "environment": self.environment.model_dump(mode="json", exclude_none=True),
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _sorted_ref_payload(refs: list[FileRef]) -> list[dict]:
    return [
        {"rel_path": r.rel_path, "sha256": r.sha256}
        for r in sorted(refs, key=lambda r: r.rel_path)
    ]


class ExecutionReceipt(Strict):
    """Receipt for one concrete execution of a capsule. Carries everything the
    differential needs (hashes, exit code, status) and everything that must
    stay OUT of the capsule_digest: timestamps, execution identity, backend."""

    schema_version: Literal[1] = SCHEMA_VERSION
    receipt_id: str
    execution_id: str
    capsule_id: str
    capsule_digest: str = Field(pattern=_SHA256_PATTERN)
    status: Literal["completed", "failed", "timeout"]
    exit_code: int | None = None
    outputs: list[FileRef] = Field(default_factory=list)
    stdout_sha256: str | None = Field(default=None, pattern=_SHA256_PATTERN)
    stderr_sha256: str | None = Field(default=None, pattern=_SHA256_PATTERN)
    backend: BackendIdentity
    started_at: datetime
    finished_at: datetime
    failure_reason: str | None = None
