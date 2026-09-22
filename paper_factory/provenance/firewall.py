"""Final-prose origin firewall — a hard path-level guard, code-enforced.

Protected paths (default: paper/main.tex, paper/sections/**, ...) may only be
modified by an invocation whose role has writes_final_prose=true AND whose
backend identity is allowed by the provenance policy AND whose model family is
not forbidden for that role.

Unknown backend + deny-policy ⇒ denied. Documented marking (e.g. anthropic)
+ strict policy ⇒ denied. This is origin control, never watermark removal.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePath

from ..core.config import MarkingRegistry, ProviderPolicyConfig


class PolicyViolation(Exception):
    """Raised when a write to a protected path is not allowed. Never caught silently."""


def normalize_rel_path(rel_path: str) -> str:
    """Canonical form for policy checks. Rejects traversal and absolutes."""
    import posixpath

    if rel_path.startswith(("/", "~")):
        raise PolicyViolation(f"absolute path not allowed for policy check: {rel_path!r}")
    norm = posixpath.normpath(rel_path.replace("\\", "/"))
    if norm.startswith("..") or "/../" in rel_path.replace("\\", "/"):
        raise PolicyViolation(f"path traversal not allowed for policy check: {rel_path!r}")
    return norm


_FAMILY_CLASSES = {
    "anthropic": "anthropic", "claude": "anthropic",
    "openai": "openai", "gpt": "openai",
    "moonshot": "moonshot", "kimi": "moonshot",
    "zai": "glm", "glm": "glm",
    "deepseek": "deepseek",
    "deterministic": "deterministic", "paper-factory": "deterministic",
    "human": "human",
}


def _norm_family(family: str | None) -> str:
    """Normalize to a family CLASS: prefix/alias matching, never free text.
    "claude-3-opus" → anthropic; "anthropic-vertex" → anthropic."""
    f = (family or "").strip().lower()
    if not f:
        return "unknown"
    if f in _FAMILY_CLASSES:
        return _FAMILY_CLASSES[f]
    for prefix, cls in _FAMILY_CLASSES.items():
        if f.startswith(prefix) or prefix in f:
            return cls
    return "unknown"


def is_protected(rel_path: str, patterns: list[str]) -> bool:
    rel_path = normalize_rel_path(rel_path)
    p = PurePath(rel_path)
    for pat in patterns:
        try:
            if p.full_match(pat):
                return True
        except (ValueError, AttributeError):
            # Python <3.13 has no full_match; fall back to fnmatch with ** emulation
            import fnmatch

            if fnmatch.fnmatch(rel_path, pat) or fnmatch.fnmatch(rel_path, pat.replace("**/", "")):
                return True
    return False


@dataclass(frozen=True)
class WriteDecision:
    allowed: bool
    reason: str
    backend_family: str
    marking_status: str


def decide_write(rel_path: str, *, role: str, backend: dict, policy: ProviderPolicyConfig,
                 marking: MarkingRegistry) -> WriteDecision:
    if not policy.provenance.enforce_path_guard:
        return WriteDecision(True, "path guard disabled by policy", backend.get("family", "unknown"),
                             "not_checked")
    if not is_protected(rel_path, policy.protected_final_prose_paths):
        return WriteDecision(True, "path not protected", backend.get("family", "unknown"),
                             "not_applicable")

    role_policy = policy.role_policy.get(role)
    if role_policy is None or not role_policy.writes_final_prose:
        raise PolicyViolation(f"role '{role}' has writes_final_prose=false; cannot modify {rel_path}")

    family = _norm_family(backend.get("family"))
    forbidden = {_norm_family(f) for f in role_policy.forbidden_model_families}
    # marking registry: raw exact match first (entries are stored raw), then a
    # class-level fallback so "anthropic-vertex"/"claude-3" still find the
    # anthropic/claude entry. Normalized values must never replace the raw
    # lookup — that kills the documented_marking backstop (regression R3).
    raw_pf = backend.get("provider_family", "unknown")
    raw_mf = backend.get("model_family", "unknown")
    status = marking.status_for(raw_pf, raw_mf)
    if status == "unknown":
        pf_cls = _norm_family(raw_pf)
        mf_cls = _norm_family(raw_mf)
        for e in marking.entries:
            if _norm_family(e.provider_family) == pf_cls and (
                    e.model_family == "*" or _norm_family(e.model_family) == mf_cls):
                status = str(e.status)
                break

    if family in forbidden:
        raise PolicyViolation(
            f"model family '{family}' is forbidden for role '{role}' (protected path {rel_path})")
    if family == "unknown" and (role_policy.unknown_backend == "deny"
                                or policy.provenance.unknown_backend_final_prose == "deny"):
        raise PolicyViolation(f"backend identity unknown for role '{role}'; policy denies unknown "
                              f"origin on protected path {rel_path}")
    if (policy.provenance.disallow_anthropic_generated_final_prose
            and family == "anthropic"):
        raise PolicyViolation("strict provenance: anthropic/claude backend may not originate "
                              f"final prose ({rel_path})")
    if status == "documented_marking":
        raise PolicyViolation(f"backend has documented content marking; excluded from final prose "
                              f"({rel_path})")
    return WriteDecision(True, "origin allowed", family, status)
