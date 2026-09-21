"""Collect the state/*.json reports: provider/harness capabilities, provenance
policy report. Each adapter is probed via doctor() only (no quota spend).
"""
from __future__ import annotations

import json
from pathlib import Path

from ..core.config import default_config_dir, load_config
from ..core.util import utcnow, write_json

STATE_DIR = Path(__file__).resolve().parent.parent / "state"


def collect_provider_capabilities(config_dir: Path | None = None) -> dict:
    from ..providers.router import ProviderRouter

    pf, prov, pol, reg = load_config(config_dir or default_config_dir())
    router = ProviderRouter(prov, pol, reg, workspace=None)
    out = {"collected_at": utcnow(), "providers": {}}
    for name in prov.providers:
        try:
            adapter = router.adapter_for(name)
            diag = adapter.doctor()
            backend = adapter.provider_identity()
            out["providers"][name] = {
                "doctor": diag,
                "backend": backend,
                "capabilities": sorted(adapter.capabilities()),
                "marking_status": reg.status_for(backend.get("provider_family", "unknown"),
                                                 backend.get("model_family", "unknown")),
            }
        except Exception as exc:
            out["providers"][name] = {"error": f"{type(exc).__name__}: {exc}"}
    write_json(STATE_DIR / "provider_capabilities.json", out)
    return out


def collect_harness_capabilities() -> dict:
    from ..adapters.claude.adapter import ClaudeAdapter
    from ..adapters.codex.adapter import CodexAdapter
    from ..adapters.kimi.adapter import KimiAdapter
    from ..adapters.litellm.adapter import LiteLLMAdapter
    from ..adapters.opencode.adapter import OpenCodeAdapter
    from ..adapters.pi.adapter import PiAdapter

    out = {"collected_at": utcnow(), "harnesses": {}}
    for cls in (ClaudeAdapter, CodexAdapter, KimiAdapter, PiAdapter, LiteLLMAdapter, OpenCodeAdapter):
        try:
            a = cls()
            out["harnesses"][a.name] = {
                "doctor": a.doctor(),
                "version": a.version(),
                "capabilities": sorted(a.capabilities()),
            }
        except Exception as exc:
            out["harnesses"][cls.__name__] = {"error": f"{type(exc).__name__}: {exc}"}
    write_json(STATE_DIR / "harness_capabilities.json", out)
    return out


def collect_provenance_policy_report(config_dir: Path | None = None) -> dict:
    pf, prov, pol, reg = load_config(config_dir or default_config_dir())
    out = {
        "collected_at": utcnow(),
        "policy": pol.provenance.model_dump(),
        "protected_paths": pol.protected_final_prose_paths,
        "marking_registry": [e.model_dump() for e in reg.entries],
        "honesty_note": ("Report language is 'Claude-origin final prose excluded' when the "
                         "policy holds — never 'watermark-free'."),
    }
    write_json(STATE_DIR / "provenance_policy_report.json", out)
    return out


def collect_e2e_report() -> dict:
    import subprocess

    proc = subprocess.run(
        [str(STATE_DIR.parents[1] / ".venv/bin/python"), "-m", "pytest", "tests/", "-q",
         "--tb=no", "-p", "no:cacheprovider"],
        cwd=STATE_DIR.parents[1], capture_output=True, text=True, timeout=1200)
    out = {"collected_at": utcnow(), "exit_code": proc.returncode,
           "summary_line": proc.stdout.strip().splitlines()[-1] if proc.stdout else "",
           "stdout_tail": proc.stdout.strip().splitlines()[-30:]}
    write_json(STATE_DIR / "synthetic_e2e_report.json", out)
    return out


if __name__ == "__main__":
    collect_provider_capabilities()
    collect_harness_capabilities()
    collect_provenance_policy_report()
    collect_e2e_report()
    print("state reports written to", STATE_DIR)
