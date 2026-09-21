"""Provider router: policy-enforced selection and invocation.

Selection never upgrades silently: when independence between model families
is required but no independent family is available, the detail dict carries
``DEGRADED_INDEPENDENCE`` instead of pretending independence. Final-prose
writes are gated by role policy AND the marking registry; violations raise
:class:`PolicyViolation` before any subprocess starts.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..adapters.base import HarnessAdapter, HarnessUnavailable, InvocationReceipt
from ..adapters.claude.adapter import ClaudeAdapter
from ..adapters.codex.adapter import CodexAdapter
from ..adapters.kimi.adapter import KimiAdapter
from ..adapters.litellm.adapter import LiteLLMAdapter
from ..adapters.opencode.adapter import OpenCodeAdapter
from ..adapters.pi.adapter import PiAdapter
from ..core.config import (
    MarkingRegistry,
    ProviderPolicyConfig,
    ProvidersConfig,
    RolePolicyEntry,
)
from ..core.util import append_jsonl, utcnow

ADAPTER_REGISTRY: dict[str, type[HarnessAdapter]] = {
    "claude": ClaudeAdapter,
    "codex": CodexAdapter,
    "kimi": KimiAdapter,
    "pi": PiAdapter,
    "litellm": LiteLLMAdapter,
    "opencode": OpenCodeAdapter,
}

UNKNOWN_FAMILIES = {"unknown", "unknown-compatible", ""}


def _marking_status(registry: MarkingRegistry, provider_family: str, model_family: str) -> str:
    """Like MarkingRegistry.status_for but robust: core's status_for assumes an
    enum (``.value``) while the pydantic Literal field stays a plain str."""
    for e in registry.entries:
        if e.provider_family == provider_family and e.model_family in (model_family, "*"):
            return str(e.status)
    return "unknown"


class PolicyViolation(Exception):
    """A role policy or marking-registry rule forbids this invocation."""


class ProviderRouter:
    def __init__(
        self,
        providers_cfg: ProvidersConfig,
        policy: ProviderPolicyConfig,
        marking: MarkingRegistry,
        workspace: Any,
    ):
        self.cfg = providers_cfg
        self.policy = policy
        self.marking = marking
        self.workspace = workspace
        self._adapters: dict[str, HarnessAdapter] = {}
        self._doctor_cache: dict[str, dict[str, Any]] = {}
        self._family_cache: dict[str, str] = {}

    # -- adapter plumbing ----------------------------------------------------
    def adapter_for(self, provider_name: str) -> HarnessAdapter:
        if provider_name not in self._adapters:
            entry = self.cfg.providers.get(provider_name)
            if entry is None:
                raise HarnessUnavailable(f"provider {provider_name!r} not in providers.yaml")
            cls = ADAPTER_REGISTRY.get(entry.adapter)
            if cls is None:
                raise HarnessUnavailable(f"no adapter registered for kind {entry.adapter!r}")
            self._adapters[provider_name] = cls(name=provider_name, config=entry)
        return self._adapters[provider_name]

    def _doctor(self, provider_name: str) -> dict[str, Any]:
        if provider_name not in self._doctor_cache:
            self._doctor_cache[provider_name] = self.adapter_for(provider_name).doctor()
        return self._doctor_cache[provider_name]

    # -- selection -----------------------------------------------------------
    def _candidates_for_role(self, role: str) -> list[str]:
        prefs = self.cfg.role_preferences.get(role, {})
        preferred = list(prefs.get("preferred", []))
        rest = [n for n in self.cfg.providers if n not in preferred]
        return preferred + rest

    def _check_candidate(
        self, name: str, role: str, rp: RolePolicyEntry
    ) -> tuple[dict[str, Any] | None, str | None]:
        """Return (backend, None) if usable, else (None, skip_reason)."""
        entry = self.cfg.providers.get(name)
        if entry is None:
            return None, "not in providers.yaml"
        if entry.enabled == "false":
            return None, "disabled in providers.yaml"
        if not self._doctor(name).get("present"):
            return None, "doctor: not present"
        backend = self.adapter_for(name).provider_identity()
        forbidden = set(rp.forbidden_model_families)
        if (
            backend["model_family"] in forbidden
            or backend["provider_family"] in forbidden
        ):
            return None, f"forbidden_model_families: {sorted(forbidden)}"
        if rp.unknown_backend == "deny" and (
            backend["provider_family"] in UNKNOWN_FAMILIES
            or backend["model_family"] in UNKNOWN_FAMILIES
        ):
            return None, "unknown_backend denied by role policy"
        return backend, None

    def _primary_family_for_role(self, role: str) -> str:
        """Model family of the first usable provider for *role* (independence off)."""
        if role in self._family_cache:
            return self._family_cache[role]
        rp = self.policy.role_policy.get(role, RolePolicyEntry())
        family = "unknown"
        for name in self._candidates_for_role(role):
            backend, _reason = self._check_candidate(name, role, rp)
            if backend is not None:
                family = backend["model_family"]
                break
        self._family_cache[role] = family
        return family

    def select_for_role(self, role: str) -> tuple[HarnessAdapter, dict[str, Any]]:
        rp = self.policy.role_policy.get(role, RolePolicyEntry())
        other_role = rp.preferred_different_family_from
        independence_required = role in self.cfg.routing.independence_required_for or bool(
            other_role
        )
        other_family = self._primary_family_for_role(other_role) if other_role else None

        detail: dict[str, Any] = {
            "role": role,
            "selection_notes": [],
            "independence_required": independence_required,
            "independence_status": "not_required",
        }
        if other_role:
            detail["independence_from"] = {"role": other_role, "model_family": other_family}

        fallback: tuple[HarnessAdapter, dict[str, Any]] | None = None
        for name in self._candidates_for_role(role):
            backend, reason = self._check_candidate(name, role, rp)
            if backend is None:
                detail["selection_notes"].append(f"{name}: skipped ({reason})")
                continue
            adapter = self.adapter_for(name)
            candidate_detail = {
                **detail,
                "provider_name": name,
                "backend": backend,
                "timestamp": utcnow(),
            }
            if not independence_required:
                return adapter, candidate_detail
            same_family = (
                other_family is not None
                and other_family not in UNKNOWN_FAMILIES
                and backend["model_family"] == other_family
            )
            if not same_family and backend["model_family"] not in UNKNOWN_FAMILIES:
                candidate_detail["independence_status"] = "independent"
                return adapter, candidate_detail
            candidate_detail["independence_status"] = "DEGRADED_INDEPENDENCE"
            candidate_detail["selection_notes"].append(
                f"{name}: model family {backend['model_family']!r} not independent"
            )
            if fallback is None:
                fallback = (adapter, candidate_detail)

        if fallback is not None and self.cfg.routing.allow_degraded_independence:
            fb = fallback[1]
            fb["selection_notes"].append(
                "no independent family available -> DEGRADED_INDEPENDENCE (explicit, not silent)"
            )
            return fallback
        raise HarnessUnavailable(
            f"no usable provider for role {role!r}: "
            + "; ".join(detail["selection_notes"] or ["no candidates"])
        )

    # -- invocation ------------------------------------------------------------
    def _check_final_prose_allowed(self, role: str, backend: dict[str, Any]) -> str:
        """Return marking status; raise PolicyViolation if final prose is forbidden."""
        rp = self.policy.role_policy.get(role, RolePolicyEntry())
        if not rp.writes_final_prose:
            raise PolicyViolation(
                f"role {role!r} has writes_final_prose=false; request denied"
            )
        status = _marking_status(self.marking, backend["provider_family"], backend["model_family"])
        if status == "documented_marking":
            raise PolicyViolation(
                f"provider {backend['provider_family']!r}/{backend['model_family']!r} has "
                "documented_marking; may not write final prose"
            )
        if status == "unknown" and self.policy.provenance.unknown_backend_final_prose == "deny":
            raise PolicyViolation(
                f"marking status unknown for {backend['provider_family']!r}/"
                f"{backend['model_family']!r}; final prose denied"
            )
        if (
            self.policy.provenance.disallow_anthropic_generated_final_prose
            and backend["provider_family"] == "anthropic"
        ):
            raise PolicyViolation("anthropic-generated final prose is disallowed by policy")
        return status

    def invoke(
        self,
        role: str,
        prompt: str,
        *,
        writes_final_prose: bool = False,
        timeout: int = 600,
        extra_flags: tuple[str, ...] = (),
    ) -> InvocationReceipt:
        adapter, detail = self.select_for_role(role)
        backend = detail["backend"]
        marking_status = "unknown"
        if writes_final_prose:
            marking_status = self._check_final_prose_allowed(role, backend)
        else:
            marking_status = _marking_status(
                self.marking, backend["provider_family"], backend["model_family"]
            )
        receipt = adapter.invoke(
            prompt,
            role=role,
            writes_final_prose=writes_final_prose,
            timeout=timeout,
            extra_flags=extra_flags,
        )
        receipt.provider = detail["provider_name"]
        # the router stamps the authoritative, honestly-resolved identity
        receipt.provider_family = backend["provider_family"]
        receipt.model_family = backend["model_family"]
        receipt.endpoint_alias = backend.get("endpoint_alias")
        receipt.marking_status = marking_status
        receipt.detail = {**receipt.detail, "routing": detail}
        out = Path(self.workspace.receipts_dir) / "invocations.jsonl"
        append_jsonl(out, receipt.model_dump(mode="json"))
        return receipt
