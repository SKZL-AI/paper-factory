"""Router tests. doctor() is faked (present) so selection logic is tested
without subprocesses; adapter.invoke is replaced by a fake receipt factory.
No harness is ever really invoked here.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from paper_factory.adapters.base import HarnessAdapter, HarnessUnavailable, InvocationReceipt
from paper_factory.core.config import (
    MarkingEntry,
    MarkingRegistry,
    ProviderEntry,
    ProviderPolicyConfig,
    ProvidersConfig,
    RolePolicyEntry,
    RoutingCfg,
)
from paper_factory.core.util import read_jsonl, sha256_bytes
from paper_factory.providers.router import PolicyViolation, ProviderRouter
from paper_factory.state.store import Workspace


def _cfg(providers: dict[str, ProviderEntry], role_prefs=None, routing=None) -> ProvidersConfig:
    return ProvidersConfig(
        providers=providers,
        role_preferences=role_prefs or {},
        routing=routing or RoutingCfg(),
    )


def _router(tmp_path: Path, cfg, policy=None, marking=None) -> ProviderRouter:
    return ProviderRouter(
        cfg,
        policy or ProviderPolicyConfig(),
        marking or MarkingRegistry(),
        Workspace(tmp_path),
    )


@pytest.fixture(autouse=True)
def fake_doctor(monkeypatch):
    """Every harness looks present; version probes stay real-but-unused."""
    monkeypatch.setattr(
        HarnessAdapter, "doctor", lambda self: {"present": True, "version": "0.0.0-test"}
    )


def _fake_invoke(self, prompt, *, role=None, writes_final_prose=False, timeout=600, extra_flags=()):
    return InvocationReceipt(
        harness=self.name,
        provider=self.name,
        role=role,
        writes_final_prose=writes_final_prose,
        prompt_sha256=sha256_bytes(prompt.encode()),
        response_sha256=sha256_bytes(b"fake"),
        exit_code=0,
    )


@pytest.fixture(autouse=True)
def fake_invoke_all(monkeypatch):
    monkeypatch.setattr(HarnessAdapter, "invoke", _fake_invoke)


# ---------------------------------------------------------------- selection


def test_selects_first_preferred(tmp_path):
    cfg = _cfg(
        {"claude": ProviderEntry(adapter="claude"), "codex": ProviderEntry(adapter="codex")},
        {"reviewer": {"preferred": ["claude", "codex"]}},
    )
    adapter, detail = _router(tmp_path, cfg).select_for_role("reviewer")
    assert adapter.name == "claude"
    assert detail["backend"]["provider_family"] == "anthropic"


def test_forbidden_model_family_is_blocked(tmp_path):
    cfg = _cfg(
        {"claude": ProviderEntry(adapter="claude"), "codex": ProviderEntry(adapter="codex")},
        {"writer": {"preferred": ["claude", "codex"]}},
    )
    policy = ProviderPolicyConfig(
        role_policy={"writer": RolePolicyEntry(forbidden_model_families=["claude"])}
    )
    adapter, detail = _router(tmp_path, cfg, policy).select_for_role("writer")
    assert adapter.name == "codex"
    assert any("claude: skipped" in n for n in detail["selection_notes"])


def test_forbidden_family_no_fallback_raises(tmp_path):
    cfg = _cfg({"claude": ProviderEntry(adapter="claude")}, {"w": {"preferred": ["claude"]}})
    policy = ProviderPolicyConfig(
        role_policy={"w": RolePolicyEntry(forbidden_model_families=["claude"])}
    )
    with pytest.raises(HarnessUnavailable):
        _router(tmp_path, cfg, policy).select_for_role("w")


def test_unknown_backend_deny(tmp_path):
    cfg = _cfg({"pi": ProviderEntry(adapter="pi")}, {"rev": {"preferred": ["pi"]}})
    policy = ProviderPolicyConfig(
        role_policy={"rev": RolePolicyEntry(unknown_backend="deny")}
    )
    with pytest.raises(HarnessUnavailable):
        _router(tmp_path, cfg, policy).select_for_role("rev")


def test_unknown_backend_allow_selects(tmp_path):
    cfg = _cfg({"pi": ProviderEntry(adapter="pi")}, {"rev": {"preferred": ["pi"]}})
    policy = ProviderPolicyConfig(
        role_policy={"rev": RolePolicyEntry(unknown_backend="allow")}
    )
    adapter, detail = _router(tmp_path, cfg, policy).select_for_role("rev")
    assert adapter.name == "pi"
    assert detail["backend"]["provider_family"] == "unknown"


# ---------------------------------------------------------------- independence


def _independence_setup(tmp_path, routing=None, extra_providers=None):
    providers = {
        "claude": ProviderEntry(adapter="claude"),
        "kimi": ProviderEntry(adapter="kimi"),
        **(extra_providers or {}),
    }
    cfg = _cfg(
        providers,
        {
            "draft_writer": {"preferred": ["claude"]},
            "methods_review": {"preferred": ["claude", "kimi"]},
        },
        routing=routing,
    )
    policy = ProviderPolicyConfig(
        role_policy={
            "methods_review": RolePolicyEntry(preferred_different_family_from="draft_writer")
        }
    )
    return _router(tmp_path, cfg, policy)


def test_independence_picks_different_family(tmp_path):
    router = _independence_setup(tmp_path)
    adapter, detail = router.select_for_role("methods_review")
    assert adapter.name == "kimi"
    assert detail["independence_status"] == "independent"
    assert detail["independence_from"]["model_family"] == "claude"


def test_independence_degraded_is_explicit(tmp_path):
    # only claude-family providers exist -> independence impossible
    router = _router(
        tmp_path,
        _cfg(
            {"claude": ProviderEntry(adapter="claude")},
            {
                "draft_writer": {"preferred": ["claude"]},
                "methods_review": {"preferred": ["claude"]},
            },
        ),
        ProviderPolicyConfig(
            role_policy={
                "methods_review": RolePolicyEntry(preferred_different_family_from="draft_writer")
            }
        ),
    )
    adapter, detail = router.select_for_role("methods_review")
    assert adapter.name == "claude"
    assert detail["independence_status"] == "DEGRADED_INDEPENDENCE"


def test_independence_not_allowed_raises(tmp_path):
    router = _router(
        tmp_path,
        _cfg(
            {"claude": ProviderEntry(adapter="claude")},
            {
                "draft_writer": {"preferred": ["claude"]},
                "methods_review": {"preferred": ["claude"]},
            },
            routing=RoutingCfg(allow_degraded_independence=False),
        ),
        ProviderPolicyConfig(
            role_policy={
                "methods_review": RolePolicyEntry(preferred_different_family_from="draft_writer")
            }
        ),
    )
    with pytest.raises(HarnessUnavailable):
        router.select_for_role("methods_review")


# ---------------------------------------------------------------- invoke gates


def test_writes_final_prose_hard_block(tmp_path):
    cfg = _cfg({"claude": ProviderEntry(adapter="claude")}, {"w": {"preferred": ["claude"]}})
    policy = ProviderPolicyConfig(
        role_policy={"w": RolePolicyEntry(writes_final_prose=False)}
    )
    router = _router(tmp_path, cfg, policy)
    with pytest.raises(PolicyViolation):
        router.invoke("w", "write the abstract", writes_final_prose=True)


def test_marking_documented_blocks_final_prose(tmp_path):
    cfg = _cfg({"codex": ProviderEntry(adapter="codex")}, {"w": {"preferred": ["codex"]}})
    policy = ProviderPolicyConfig(
        role_policy={"w": RolePolicyEntry(writes_final_prose=True)}
    )
    marking = MarkingRegistry(
        entries=[
            MarkingEntry(
                provider_family="openai", model_family="gpt", status="documented_marking"
            )
        ]
    )
    router = _router(tmp_path, cfg, policy, marking)
    with pytest.raises(PolicyViolation):
        router.invoke("w", "write", writes_final_prose=True)


def test_anthropic_final_prose_disallowed(tmp_path):
    cfg = _cfg({"claude": ProviderEntry(adapter="claude")}, {"w": {"preferred": ["claude"]}})
    policy = ProviderPolicyConfig(
        role_policy={"w": RolePolicyEntry(writes_final_prose=True)}
    )
    marking = MarkingRegistry(
        entries=[
            MarkingEntry(
                provider_family="anthropic", model_family="claude",
                status="documented_no_marking",
            )
        ]
    )
    router = _router(tmp_path, cfg, policy, marking)
    with pytest.raises(PolicyViolation):
        router.invoke("w", "write", writes_final_prose=True)


def test_invoke_success_writes_receipt(tmp_path):
    cfg = _cfg({"codex": ProviderEntry(adapter="codex")}, {"rev": {"preferred": ["codex"]}})
    marking = MarkingRegistry(
        entries=[
            MarkingEntry(
                provider_family="openai", model_family="gpt",
                status="documented_no_marking",
            )
        ]
    )
    ws = Workspace(tmp_path)
    router = ProviderRouter(cfg, ProviderPolicyConfig(), marking, ws)
    receipt = router.invoke("rev", "check the stats", writes_final_prose=False)
    assert receipt.marking_status == "documented_no_marking"
    lines = read_jsonl(ws.receipts_dir / "invocations.jsonl")
    assert len(lines) == 1
    assert lines[0]["prompt_sha256"] == sha256_bytes(b"check the stats")
    assert lines[0]["provider_family"] == "openai"


def test_invoke_blocked_writes_no_receipt(tmp_path):
    cfg = _cfg({"claude": ProviderEntry(adapter="claude")}, {"w": {"preferred": ["claude"]}})
    policy = ProviderPolicyConfig(
        role_policy={"w": RolePolicyEntry(writes_final_prose=False)}
    )
    ws = Workspace(tmp_path)
    router = ProviderRouter(cfg, policy, MarkingRegistry(), ws)
    with pytest.raises(PolicyViolation):
        router.invoke("w", "write", writes_final_prose=True)
    assert not (ws.receipts_dir / "invocations.jsonl").exists()
