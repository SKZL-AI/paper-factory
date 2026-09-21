"""OpenCode adapter.

Not installed on every machine. When the binary is missing, doctor()
reports UNAVAILABLE (never an error) and capabilities stay empty — they are
probe-derived only, never assumed. The backend model is whatever OpenCode
is configured to use (e.g. GLM); identity resolution never infers it from
the harness name.
"""
from __future__ import annotations

from typing import ClassVar

from ..base import HarnessAdapter


class OpenCodeAdapter(HarnessAdapter):
    kind = "opencode"
    default_executable = "opencode"
    HELP_RULES: ClassVar[dict[str, str]] = {
        "non_interactive": r"\brun\b[^\n]*non-interactive|--print\b",
        "structured_output": r"--format\b[^\n]*json|--json\b",
        "json_events": r"--print-logs|stream-json",
        "custom_model": r"--model\b|-m\b",
        "custom_provider": r"--provider\b",
        "session_resume": r"--session\b|--continue\b",
        "server_mode": r"\bserve\b|\bserver\b",
        "tool_use": r"--tools\b",
    }

    def _build_argv(self, prompt, *, role, writes_final_prose, extra_flags):
        argv = [self.executable, "run"]
        if self.config.model:
            argv += ["--model", self.config.model]
        argv += list(extra_flags)
        argv.append(prompt)
        return argv
