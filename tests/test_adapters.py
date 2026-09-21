"""Adapter tests. No real invocations: subprocess is mocked for invoke();
the only real processes ever started are --help/--version probes of the
locally installed CLIs (claude, codex, kimi, pi).
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import ClassVar

import pytest

from paper_factory.adapters.base import (
    ALL_CAPABILITIES,
    HarnessUnavailable,
    InvocationReceipt,
    capabilities_from_help,
)
from paper_factory.adapters.claude.adapter import ClaudeAdapter
from paper_factory.adapters.codex.adapter import CodexAdapter
from paper_factory.adapters.kimi.adapter import KimiAdapter
from paper_factory.adapters.litellm.adapter import LiteLLMAdapter
from paper_factory.adapters.opencode.adapter import OpenCodeAdapter
from paper_factory.adapters.pi.adapter import PiAdapter
from paper_factory.core.config import ProviderEntry
from paper_factory.core.util import read_jsonl, sha256_bytes

ALL_ADAPTERS = [ClaudeAdapter, CodexAdapter, KimiAdapter, PiAdapter, LiteLLMAdapter, OpenCodeAdapter]
INSTALLED = {ClaudeAdapter, CodexAdapter, KimiAdapter, PiAdapter}


# ---------------------------------------------------------------- doctor


@pytest.mark.parametrize("cls", ALL_ADAPTERS, ids=lambda c: c.kind)
def test_doctor_runs_without_error(cls, monkeypatch):
    monkeypatch.delenv("PF_TEST_GATEWAY_URL", raising=False)
    cfg = ProviderEntry(adapter=cls.kind, base_url_env="PF_TEST_GATEWAY_URL")
    diag = cls(config=cfg).doctor()
    assert diag["present"] in (True, False)
    assert diag["verdict"] in ("PASS", "UNAVAILABLE")
    assert isinstance(diag["capabilities"], list)
    assert set(diag["capabilities"]) <= ALL_CAPABILITIES


@pytest.mark.parametrize("cls", sorted(INSTALLED, key=lambda c: c.kind), ids=lambda c: c.kind)
def test_installed_harnesses_are_present(cls):
    diag = cls(config=ProviderEntry(adapter=cls.kind)).doctor()
    assert diag["present"] is True, f"{cls.kind} should be installed on this machine"
    assert diag["version"], f"{cls.kind} version probe returned nothing"


def test_opencode_unavailable_not_error():
    diag = OpenCodeAdapter(config=ProviderEntry(adapter="opencode")).doctor()
    if not diag["present"]:  # not installed on this machine
        assert diag["verdict"] == "UNAVAILABLE"
        assert diag["capabilities"] == []


def test_litellm_unavailable_without_base_url(monkeypatch):
    monkeypatch.delenv("PF_TEST_UNSET_GATEWAY", raising=False)
    ad = LiteLLMAdapter(config=ProviderEntry(adapter="litellm", base_url_env="PF_TEST_UNSET_GATEWAY"))
    diag = ad.doctor()
    assert diag["present"] is False
    assert "not set" in diag["note"]


# ------------------------------------------------------- capability parsing


# Synthetic help snippets (written for this test, not captured CLI output).
FAKE_CLAUDE_HELP = """
  -p, --print                           Print response and exit
  --output-format <format>              Output format: "text", "json", "stream-json"
  --json-schema <schema>                JSON Schema for structured output validation
  --permission-mode <mode>              (choices: "acceptEdits", "plan", "bypassPermissions")
  -r, --resume [value]                  Resume a conversation by session ID
  --disable-slash-commands              Disable all skills
  --allowedTools <tools...>             tool names to allow
  --model <model>                       Model for the current session
"""


def test_capabilities_from_cached_help():
    caps = capabilities_from_help(FAKE_CLAUDE_HELP, ClaudeAdapter.HELP_RULES)
    assert {"non_interactive", "structured_output", "json_events",
            "schema_constrained_output", "read_only_mode", "workspace_write_mode",
            "session_resume", "skills", "slash_commands", "tool_use",
            "custom_model"} - caps == set()
    assert "sandbox" not in caps  # claude --help advertises no sandbox flag


def test_capabilities_empty_help_yields_nothing():
    assert capabilities_from_help("", CodexAdapter.HELP_RULES) == set()


def test_rules_only_use_known_capability_strings():
    for cls in ALL_ADAPTERS:
        assert set(cls.HELP_RULES) <= ALL_CAPABILITIES


def test_real_capabilities_match_probe():
    caps = ClaudeAdapter(config=ProviderEntry(adapter="claude")).capabilities()
    assert {"non_interactive", "json_events", "schema_constrained_output"} <= caps
    caps = CodexAdapter(config=ProviderEntry(adapter="codex")).capabilities()
    assert {"non_interactive", "json_events", "sandbox", "read_only_mode"} <= caps


# ------------------------------------------------------- invoke (mocked)


class _FakeProc:
    def __init__(self, stdout="RESPONSE-TEXT", returncode=0, stderr=""):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def _patch_runtime(monkeypatch, adapter):
    monkeypatch.setattr(adapter, "doctor", lambda: {"present": True})
    monkeypatch.setattr(adapter, "version", lambda: "9.9.9-test")
    monkeypatch.setattr(adapter, "capabilities", lambda: {"session_resume"})
    captured = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        return _FakeProc()

    monkeypatch.setattr(subprocess, "run", fake_run)
    return captured


def test_invoke_mocked_receipt_hashes(monkeypatch):
    ad = ClaudeAdapter(config=ProviderEntry(adapter="claude"))
    captured = _patch_runtime(monkeypatch, ad)
    receipt = ad.invoke("hello world", role="reviewer")
    assert receipt.exit_code == 0
    assert receipt.prompt_sha256 == sha256_bytes(b"hello world")
    assert receipt.response_sha256 == sha256_bytes(b"RESPONSE-TEXT")
    assert receipt.harness_version == "9.9.9-test"
    assert receipt.provider_family == "anthropic"
    assert receipt.model_family == "claude"
    assert captured["argv"][1] == "--print"
    assert captured["argv"][-1] == "hello world"


@pytest.mark.parametrize(
    "cls,expect",
    [
        (ClaudeAdapter, ["--print"]),
        (CodexAdapter, ["exec", "--skip-git-repo-check"]),
        (KimiAdapter, ["--prompt"]),
        (PiAdapter, ["--print"]),
    ],
    ids=lambda x: x.kind if isinstance(x, type) else "+".join(x),
)
def test_build_argv_noninteractive(monkeypatch, cls, expect):
    ad = cls(config=ProviderEntry(adapter=cls.kind))
    captured = _patch_runtime(monkeypatch, ad)
    ad.invoke("p", role="r")
    argv = captured["argv"]
    for flag in expect:
        assert flag in argv


def test_invoke_raises_when_unavailable():
    ad = OpenCodeAdapter(
        name="opencode", config=ProviderEntry(adapter="opencode", executable="/nonexistent/opencode")
    )
    with pytest.raises(HarnessUnavailable):
        ad.invoke("hello", role="reviewer")


def test_litellm_invoke_mocked(monkeypatch):
    monkeypatch.setenv("PF_TEST_GW_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("PF_TEST_GW_KEY", "redacted")
    ad = LiteLLMAdapter(
        config=ProviderEntry(
            adapter="litellm", base_url_env="PF_TEST_GW_URL", api_key_env="PF_TEST_GW_KEY",
            model="glm-4.6",
        )
    )

    class FakeResp:
        status_code = 200
        headers: ClassVar[dict[str, str]] = {"content-type": "application/json"}

        def json(self):
            return {"choices": [{"message": {"content": "GW-RESP"}}]}

    import requests

    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResp())
    receipt = ad.invoke("hello", role="writer")
    assert receipt.exit_code == 0
    assert receipt.endpoint_alias == "127.0.0.1:9"
    assert receipt.model_family == "glm"  # from configured model string, not the harness name
    assert receipt.response_sha256 == sha256_bytes(b"GW-RESP")


# ------------------------------------------------------- receipt jsonl


def test_receipt_to_jsonl(tmp_path: Path):
    r = InvocationReceipt(harness="claude", prompt_sha256="a" * 64, exit_code=0)
    out = tmp_path / "invocations.jsonl"
    r.to_jsonl(out)
    r.to_jsonl(out)
    lines = read_jsonl(out)
    assert len(lines) == 2
    assert lines[0]["harness"] == "claude"
    assert lines[0]["marking_status"] == "unknown"
