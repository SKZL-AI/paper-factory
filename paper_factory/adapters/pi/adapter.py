"""pi adapter. Non-interactive mode: ``pi -p [--] <prompt>``.

Capabilities are parsed from the real ``pi --help`` output, e.g.
``--mode text|json|rpc``, ``--provider``/``--model``, the documented
read-only pattern (``--tools read,grep,find,ls``), ``--skill``.
"""
from __future__ import annotations

from typing import ClassVar

from ..base import HarnessAdapter


class PiAdapter(HarnessAdapter):
    kind = "pi"
    default_executable = "pi"
    HELP_RULES: ClassVar[dict[str, str]] = {
        "non_interactive": r"--print\b",
        "structured_output": r"--mode\b[^\n]*json",
        "sdk_or_rpc": r"\brpc\b",
        "custom_provider": r"--provider\b",
        "custom_model": r"--model\b",
        "custom_base_url": r"BASE_URL",
        "session_resume": r"--resume\b|--continue\b|--fork\b",
        "read_only_mode": r"Read-only mode",
        "workspace_write_mode": r"edit, write tools",
        "tool_use": r"--tools\b|Built-in Tool",
        "skills": r"--skill\b",
    }

    def _build_argv(self, prompt, *, role, writes_final_prose, extra_flags):
        argv = [self.executable, "--print"]
        provider = self.config.config.get("provider") if self.config.config else None
        if provider:
            argv += ["--provider", str(provider)]
        if self.config.model:
            argv += ["--model", self.config.model]
        argv += list(extra_flags)
        argv += ["--", prompt]
        return argv
