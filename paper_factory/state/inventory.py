"""Bootstrap inventory: inspect the machine, harnesses, research systems and
provider configurations (structure only — never secret values)."""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any

from ..core.util import utcnow, write_json

TOOLS = [
    "python3", "uv", "git", "node", "npm", "latexmk", "pdflatex", "xelatex",
    "dot", "qpdf", "pdftotext", "jq", "rg", "gitleaks", "trufflehog",
]
HARNESSES = ["opencode", "pi", "kimi", "codex", "claude"]
RESEARCH = ["hoh", "herdr", "paperqa", "zotero-cli"]


def _probe(cmd: list[str], timeout: int = 20) -> dict[str, Any]:
    exe = shutil.which(cmd[0])
    if not exe:
        return {"present": False}
    out: dict[str, Any] = {"present": True, "path": exe}
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out["exit_code"] = proc.returncode
        out["version_output"] = (proc.stdout.strip() or proc.stderr.strip()).splitlines()[:3]
    except subprocess.TimeoutExpired:
        out["exit_code"] = None
        out["version_output"] = ["<timeout>"]
    except OSError as exc:
        out["error"] = str(exc)
    return out


def _gpu_note() -> dict[str, Any]:
    # House rule: never nvidia-smi. Device-node presence only.
    devs = sorted(str(p) for p in Path("/dev").glob("nvidia*"))
    return {
        "device_nodes": devs,
        "driver_state": "not_probed",
        "note": "nvidia-smi is forbidden on this machine (driver wedge incident 2026-08-03).",
    }


def _env_key_names() -> dict[str, bool]:
    names = [
        "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "MOONSHOT_API_KEY", "KIMI_API_KEY",
        "ZAI_API_KEY", "GLM_API_KEY", "DEEPSEEK_API_KEY", "LITELLM_API_KEY",
        "PAPER_FACTORY_LITELLM_BASE_URL", "PAPER_FACTORY_LITELLM_API_KEY",
        "HERDR_ENV", "HERDR_SOCKET_PATH", "HERDR_WORKSPACE_ID",
    ]
    return {n: (n in os.environ) for n in names}


def _provider_config_structure() -> dict[str, Any]:
    """Read provider config *structure*; redact anything that looks like a secret."""
    out: dict[str, Any] = {}

    def redact(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {
                k: ("***" if any(s in k.upper() for s in ("KEY", "TOKEN", "SECRET", "PASS")) else redact(v))
                for k, v in obj.items()
            }
        if isinstance(obj, list):
            return [redact(v) for v in obj]
        return obj

    home = Path.home()
    candidates = {
        "claude_settings": home / ".claude" / "settings.json",
        "codex_config_toml": home / ".codex" / "config.toml",
        "kimi_config": home / ".kimi-code" / "config.toml",
        "pi_config": home / ".pi" / "config.json",
        "opencode_config": home / ".config" / "opencode" / "config.json",
    }
    for name, path in candidates.items():
        if not path.exists():
            out[name] = {"present": False}
            continue
        entry: dict[str, Any] = {"present": True, "path": str(path)}
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            if path.suffix == ".json":
                entry["structure"] = redact(json.loads(text))
            else:
                # TOML: keep only section headers and key names
                lines = []
                for line in text.splitlines():
                    s = line.strip()
                    if s.startswith("[") or ("=" in s and not any(
                            t in s.lower() for t in ("key", "token", "secret"))):
                        lines.append(s.split("=")[0].strip() + (" =" if "=" in s else ""))
                entry["structure"] = lines[:60]
        except (OSError, json.JSONDecodeError) as exc:
            entry["error"] = str(exc)
        out[name] = entry
    return out


def _pip_probe(dist: str) -> dict[str, Any]:
    try:
        from importlib.metadata import version

        return {"present": True, "installed_version": version(dist)}
    except Exception:
        return {"present": False}


def collect_inventory() -> dict[str, Any]:
    inv: dict[str, Any] = {
        "collected_at": utcnow(),
        "machine": {
            "os": platform.system(),
            "os_release": platform.release(),
            "platform": platform.platform(),
            "python": platform.python_version(),
            "shell": os.environ.get("SHELL"),
            "cpu_count": os.cpu_count(),
            "wsl": "microsoft" in platform.release().lower(),
            "gpu": _gpu_note(),
        },
        "tools": {t: _probe([t, "--version"]) for t in TOOLS},
        "harnesses": {h: _probe([h, "--version"]) for h in HARNESSES},
        "research_systems": {r: _probe([r, "--version"]) for r in RESEARCH},
        "env_key_names_present": _env_key_names(),
        "provider_config_structure": _provider_config_structure(),
    }
    # herdr server status (cheap, local socket)
    if shutil.which("herdr"):
        try:
            proc = subprocess.run(["herdr", "status"], capture_output=True, text=True, timeout=15)
            inv["research_systems"]["herdr"]["server_status"] = proc.stdout.strip().splitlines()[:8]
        except (subprocess.TimeoutExpired, OSError) as exc:
            inv["research_systems"]["herdr"]["server_status_error"] = str(exc)
    return inv


def write_inventory(path: Path) -> dict[str, Any]:
    inv = collect_inventory()
    write_json(path, inv)
    return inv
