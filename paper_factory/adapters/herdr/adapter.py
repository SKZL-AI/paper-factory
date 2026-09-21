"""Herdr adapter: runtime/session/worktree infrastructure evidence.

Herdr owns sessions, panes, worktrees, restore. It never decides scientific
truth. This adapter only records *that* a run happened inside Herdr (or
honestly reports DEGRADED_RUNTIME when it did not).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any


class HerdrAdapter:
    def available(self) -> bool:
        return os.environ.get("HERDR_ENV") == "1" and bool(shutil.which("herdr"))

    def self_endpoint(self) -> dict[str, Any]:
        return {
            "workspace_id": os.environ.get("HERDR_WORKSPACE_ID"),
            "tab_id": os.environ.get("HERDR_TAB_ID"),
            "pane_id": os.environ.get("HERDR_PANE_ID"),
            "socket": os.environ.get("HERDR_SOCKET_PATH"),
        }

    def status(self) -> dict[str, Any]:
        if not self.available():
            return {"available": False, "verdict": "DEGRADED_RUNTIME"}
        out: dict[str, Any] = {"available": True, "endpoint": self.self_endpoint()}
        try:
            proc = subprocess.run(["herdr", "status"], capture_output=True, text=True, timeout=15)
            out["server"] = proc.stdout.strip().splitlines()[:10]
        except (OSError, subprocess.TimeoutExpired) as exc:
            out["server_error"] = str(exc)
            out["verdict"] = "DEGRADED_RUNTIME"
        else:
            out["verdict"] = "PASS" if proc.returncode == 0 else "DEGRADED_RUNTIME"
        return out

    def snapshot_evidence(self) -> dict[str, Any]:
        """Record a herdr api snapshot as runtime evidence for a PF node."""
        if not self.available():
            return {"available": False}
        try:
            proc = subprocess.run(["herdr", "api", "snapshot"], capture_output=True,
                                  text=True, timeout=20)
            data = json.loads(proc.stdout) if proc.returncode == 0 else {"raw": proc.stdout[:2000]}
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
            return {"available": True, "snapshot_error": str(exc)}
        return {"available": True, "snapshot": data}
