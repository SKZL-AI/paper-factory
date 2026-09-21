"""Kimi Code adapter. Non-interactive mode: ``kimi -p <prompt>``.

Capabilities are parsed from the real ``kimi --help`` output, e.g.
``--output-format text|stream-json``, ``--session``/``--continue``,
``--skills-dir``, the ``acp`` (Agent Client Protocol) server subcommand.
"""
from __future__ import annotations

from typing import ClassVar

from ..base import HarnessAdapter


class KimiAdapter(HarnessAdapter):
    kind = "kimi"
    default_executable = "kimi"
    HELP_RULES: ClassVar[dict[str, str]] = {
        "non_interactive": r"-p, --prompt\b",
        "structured_output": r"stream-json",
        "json_events": r"stream-json",
        "custom_model": r"--model\b",
        "custom_provider": r"Manage LLM providers",
        "session_resume": r"--session\b|--continue\b",
        "read_only_mode": r"--plan\b",
        "server_mode": r"\bacp\b|web \[options\]",
        "sdk_or_rpc": r"Agent Client Protocol|\bacp\b",
        "tool_use": r"edits and commands run automatically",
        "skills": r"--skills-dir\b",
    }

    def _build_argv(self, prompt, *, role, writes_final_prose, extra_flags):
        argv = [self.executable, "--prompt", prompt]
        if self.config.model:
            argv += ["--model", self.config.model]
        argv += list(extra_flags)
        return argv
