"""Configuration loading for PAPER FACTORY.

Four YAML files, all with built-in defaults derived from the v1.1 blueprint
examples. None of them may contain secrets; provider entries reference
environment variable *names*, never values.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

# ---------------------------------------------------------------- paper-factory.yaml


class PaperCfg(BaseModel):
    id: str = "auto"
    title: str | None = None
    target: str = "preprint"
    canonical_format: str = "latex"
    draft_is_authoritative: bool = False
    # arXiv venue compliance (P32, see docs/ARXIV_COMPLIANCE.md)
    license: str | None = None  # one of the six arXiv options — irrevocable
    type: str = "research"  # research | review | position
    category: str | None = None  # e.g. cs.AI
    journal_ref: str | None = None  # required for review/position in cs.*


class ChatsCfg(BaseModel):
    enabled: bool = True
    local_discovery: bool = True
    extra_paths: list[str] = Field(default_factory=list)
    hidden_chain_of_thought: Literal["forbidden"] = "forbidden"


class InputsCfg(BaseModel):
    mode: str = "auto"  # auto | CODE_ONLY | DATA_ONLY | DRAFT_ASSISTED | MIXED_EVIDENCE
    paths: list[str] = Field(default_factory=list)
    chats: ChatsCfg = Field(default_factory=ChatsCfg)


class EvidenceCfg(BaseModel):
    authority_order: list[str] = Field(default_factory=lambda: ["T0", "T1", "T2", "T3", "T4"])
    require_claim_ids: bool = True
    require_number_provenance: bool = True


class LiteratureCfg(BaseModel):
    paperqa2: bool = True
    crossref: bool = True
    openalex: bool = True
    semantic_scholar: bool = True
    zotero: str = "auto"
    scite: str = "auto"
    unpaywall: str = "auto"


class VerificationCfg(BaseModel):
    veriharness: str = "required_for_acceptance"
    herdr: str = "preferred"
    model_diversity: str = "preferred"
    block_on_unresolved_major: bool = True
    global_closure: bool = True
    # Quota-aware default: one representative verification node gets a real HoH
    # run; the dashboard reports exactly which nodes carry HoH receipts.
    hoh_nodes: list[str] = Field(default_factory=lambda: ["P05"])
    # Shadow/differential mode (plan §3 Phase 5): native PF result vs HoH result
    # are compared per node and recorded; empty default = shadow off. Never
    # changes node verdicts.
    shadow_nodes: list[str] = Field(default_factory=list)


class PaperpalCfg(BaseModel):
    mode: str = "auto"  # auto | api | word_auto | manual_bridge | disabled
    api_if_supported: bool = True
    manual_bridge_if_needed: bool = True
    semantic_diff_after_edit: bool = True


class ReleaseCfg(BaseModel):
    clean_build: bool = True
    secret_scan: bool = True
    include_chat_logs: bool = False
    include_internal_reviews: bool = False
    require_human_final_signoff: bool = True


class PaperFactoryConfig(BaseModel):
    version: int = 1
    paper: PaperCfg = Field(default_factory=PaperCfg)
    inputs: InputsCfg = Field(default_factory=InputsCfg)
    evidence: EvidenceCfg = Field(default_factory=EvidenceCfg)
    literature: LiteratureCfg = Field(default_factory=LiteratureCfg)
    verification: VerificationCfg = Field(default_factory=VerificationCfg)
    paperpal: PaperpalCfg = Field(default_factory=PaperpalCfg)
    release: ReleaseCfg = Field(default_factory=ReleaseCfg)


# ---------------------------------------------------------------- providers.yaml


class ProviderEntry(BaseModel):
    adapter: str
    enabled: str = "auto"  # auto | true | false
    family: str = "unknown"
    executable: str | None = None
    base_url_env: str | None = None
    api_key_env: str | None = None
    model: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class RoutingCfg(BaseModel):
    independence_required_for: list[str] = Field(
        default_factory=lambda: [
            "methods_review",
            "statistics_review",
            "adversarial_review",
            "semantic_diff",
        ]
    )
    native_cli_first: bool = True
    gateway_second: bool = True
    allow_degraded_independence: bool = True


class ProvidersConfig(BaseModel):
    version: int = 1
    routing: RoutingCfg = Field(default_factory=RoutingCfg)
    providers: dict[str, ProviderEntry] = Field(default_factory=dict)
    role_preferences: dict[str, dict[str, list[str]]] = Field(default_factory=dict)


# ---------------------------------------------------------------- provider-policy.yaml


class ProvenancePolicyCfg(BaseModel):
    disallow_anthropic_generated_final_prose: bool = True
    unknown_backend_final_prose: Literal["deny", "allow"] = "deny"
    enforce_path_guard: bool = True
    do_not_claim_watermark_free_without_evidence: bool = True


class RolePolicyEntry(BaseModel):
    writes_final_prose: bool = False
    forbidden_model_families: list[str] = Field(default_factory=list)
    unknown_backend: Literal["deny", "allow"] = "allow"
    preferred_harnesses: list[str] = Field(default_factory=list)
    sandbox: str | None = None
    preferred_different_family_from: str | None = None


class ProviderPolicyConfig(BaseModel):
    version: int = 1
    frontends: dict[str, Any] = Field(default_factory=dict)
    provenance: ProvenancePolicyCfg = Field(default_factory=ProvenancePolicyCfg)
    protected_final_prose_paths: list[str] = Field(
        default_factory=lambda: [
            "paper/main.tex",
            "paper/sections/**/*.tex",
            "paper/appendix/**/*.tex",
            "paper/generated/captions*.tex",
            "paper/cover_letter.*",
            "paper/response_to_reviewers.*",
        ]
    )
    role_policy: dict[str, RolePolicyEntry] = Field(default_factory=dict)
    paperpal: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------- model-marking-registry.yaml


class MarkingEntry(BaseModel):
    provider_family: str
    model_family: str
    status: Literal[
        "documented_marking", "documented_no_marking", "unknown", "not_applicable", "human"
    ]
    scope: str = "generated_text"
    verified_at: str | None = None
    source_type: str | None = None
    source: str | None = None
    notes: str | None = None


class MarkingRegistry(BaseModel):
    version: int = 1
    policy_note: str = (
        "This registry reports only documented status. Unknown does not mean unmarked."
    )
    entries: list[MarkingEntry] = Field(default_factory=list)

    def status_for(self, provider_family: str, model_family: str) -> str:
        for e in self.entries:
            if e.provider_family == provider_family and e.model_family in (model_family, "*"):
                return str(e.status)
        return "unknown"


# ---------------------------------------------------------------- loading


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data or {}


def load_config(
    config_dir: Path,
) -> tuple[PaperFactoryConfig, ProvidersConfig, ProviderPolicyConfig, MarkingRegistry]:
    """Load all four config files from *config_dir*, falling back to defaults."""
    pf = PaperFactoryConfig(**_load_yaml(config_dir / "paper-factory.yaml"))
    prov = ProvidersConfig(**_load_yaml(config_dir / "providers.yaml"))
    pol = ProviderPolicyConfig(**_load_yaml(config_dir / "provider-policy.yaml"))
    reg = MarkingRegistry(**_load_yaml(config_dir / "model-marking-registry.yaml"))
    return pf, prov, pol, reg


def default_config_dir() -> Path:
    import os

    env = os.environ.get("PAPER_FACTORY_CONFIG_DIR")
    if env:
        return Path(env)
    return Path.home() / ".config" / "paper-factory"
