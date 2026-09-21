"""Claude Code adapter. Non-interactive mode: ``claude -p``.

Capabilities are parsed from the real ``claude --help`` output, e.g.:
``--output-format text|json|stream-json``, ``--json-schema``,
``--permission-mode ... plan``, ``--resume``/``--continue``.
"""
from __future__ import annotations

from typing import ClassVar

from ..base import HarnessAdapter


class ClaudeAdapter(HarnessAdapter):
    kind = "claude"
    default_executable = "claude"
    HELP_RULES: ClassVar[dict[str, str]] = {
        "non_interactive": r"--print\b",
        "structured_output": r"--output-format[^\n]*json",
        "json_events": r"stream-json",
        "schema_constrained_output": r"--json-schema\b",
        "read_only_mode": r'"plan"',
        "workspace_write_mode": r"acceptEdits|bypassPermissions",
        "custom_model": r"--model\b",
        "custom_provider": r"Bedrock|Vertex|Foundry",
        "session_resume": r"--resume\b|--continue\b",
        "sdk_or_rpc": r"--input-format[^\n]*stream-json",
        "tool_use": r"--allowedTools|--tools\b",
        "skills": r"--disable-slash-commands[^\n]*skills",
        "slash_commands": r"slash.commands",
    }

    def _build_argv(self, prompt, *, role, writes_final_prose, extra_flags):
        argv = [self.executable, "--print", "--output-format", "text"]
        if self.config.model:
            argv += ["--model", self.config.model]
        argv += list(extra_flags)
        argv.append(prompt)
        return argv
