"""Honest backend/provider identity resolution.

Harness and backend model are separate concepts: OpenCode serving GLM must
surface as backend ``glm``, and a Claude CLI pointed at a foreign
``ANTHROPIC_BASE_URL`` is NOT evidence of an Anthropic backend. Rules:
- Never infer the backend from the harness name alone; use config + env.
- An explicit ``family`` in providers.yaml wins over defaults.
- Unknown stays ``unknown`` (or ``unknown-compatible`` for a redirected
  endpoint) — guessing is forbidden.
"""
from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

from ..core.config import ProviderEntry

#: first-match prefix table on the *configured model string* (config is
#: evidence; the harness name is not)
MODEL_FAMILY_PREFIXES: tuple[tuple[str, str], ...] = (
    ("claude", "claude"),
    ("gpt", "gpt"),
    ("o1", "gpt"),
    ("o3", "gpt"),
    ("o4", "gpt"),
    ("glm", "glm"),
    ("kimi", "kimi"),
    ("k2", "kimi"),
    ("moonshot", "kimi"),
    ("gemini", "gemini"),
    ("deepseek", "deepseek"),
    ("qwen", "qwen"),
    ("llama", "llama"),
    ("mistral", "mistral"),
    ("mixtral", "mistral"),
)

#: honest per-harness defaults when nothing is configured/redirected
_HARNESS_DEFAULTS: dict[str, dict[str, str]] = {
    "claude": {"provider_family": "anthropic", "model_family": "claude"},
    "codex": {"provider_family": "openai", "model_family": "gpt"},
    "kimi": {"provider_family": "moonshot", "model_family": "kimi"},
}

_ANTHROPIC_DEFAULT_HOSTS = {"api.anthropic.com", "api.anthropic.com:443"}


def model_family_from_string(model: str | None) -> str:
    if not model:
        return "unknown"
    low = model.lower()
    for prefix, family in MODEL_FAMILY_PREFIXES:
        if low.startswith(prefix):
            return family
    return "unknown"


def _endpoint_alias(url: str) -> str | None:
    host = urlparse(url).netloc
    return host or None


def resolve_backend(
    harness_name: str,
    harness_config: ProviderEntry,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Resolve provider/model family for one configured harness instance.

    Returns dict with keys: provider_family, model_family, endpoint_alias,
    basis (what the verdict rests on).
    """
    env = os.environ if env is None else env
    out: dict[str, Any] = {
        "provider_family": "unknown",
        "model_family": "unknown",
        "endpoint_alias": None,
        "basis": "none",
    }

    configured_family = (harness_config.family or "unknown").strip()
    if configured_family and configured_family != "unknown":
        out["provider_family"] = configured_family
        out["basis"] = "providers.yaml family"

    if harness_name == "claude":
        base_url = env.get("ANTHROPIC_BASE_URL", "").strip()
        if base_url:
            alias = _endpoint_alias(base_url)
            out["endpoint_alias"] = alias
            if alias not in _ANTHROPIC_DEFAULT_HOSTS:
                # redirected endpoint: do NOT guess what is behind it
                out["provider_family"] = "unknown-compatible"
                out["model_family"] = "unknown"
                out["basis"] = "env ANTHROPIC_BASE_URL redirect"
                return out
        if out["provider_family"] == "unknown":
            out.update(_HARNESS_DEFAULTS["claude"])
            out["basis"] = "harness default (claude CLI, default endpoint)"
        if harness_config.model:
            fam = model_family_from_string(harness_config.model)
            if fam != "unknown":
                out["model_family"] = fam
        return out

    if harness_name in ("codex", "kimi"):
        if out["provider_family"] == "unknown":
            out.update(_HARNESS_DEFAULTS[harness_name])
            out["basis"] = f"harness default ({harness_name} CLI)"
        if harness_config.model:
            fam = model_family_from_string(harness_config.model)
            out["model_family"] = fam if fam != "unknown" else out["model_family"]
        return out

    if harness_name == "pi":
        # pi defaults to google but is multi-provider; until providers.yaml
        # pins a provider/model we honestly report unknown.
        provider = (harness_config.config or {}).get("provider")
        if provider and out["provider_family"] == "unknown":
            out["provider_family"] = str(provider)
            out["basis"] = "providers.yaml config.provider"
        fam = model_family_from_string(harness_config.model)
        if fam != "unknown":
            out["model_family"] = fam
            if out["basis"] == "none":
                out["basis"] = "providers.yaml model"
        return out

    if harness_name == "litellm":
        base_url = env.get(harness_config.base_url_env or "", "").strip()
        if base_url:
            out["endpoint_alias"] = _endpoint_alias(base_url)
            if out["basis"] == "none":
                out["basis"] = f"env {harness_config.base_url_env}"
        fam = model_family_from_string(harness_config.model)
        if fam != "unknown":
            out["model_family"] = fam
        return out

    # opencode and anything else: config is the only evidence
    fam = model_family_from_string(harness_config.model)
    if fam != "unknown":
        out["model_family"] = fam
        if out["basis"] == "none":
            out["basis"] = "providers.yaml model"
    return out
