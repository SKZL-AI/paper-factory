"""Codex CLI adapter. Non-interactive mode: ``codex exec --skip-git-repo-check``.

Capabilities are parsed from ``codex --help`` plus ``codex exec --help``
(e.g. ``--json`` JSONL events, ``--output-schema``, ``--sandbox
read-only|workspace-write``, ``--search``, ``mcp-server`` subcommand).
"""
from __future__ import annotations

from typing import ClassVar

from ..base import HarnessAdapter


class CodexAdapter(HarnessAdapter):
    kind = "codex"
    default_executable = "codex"
    EXTRA_HELP_ARGS = ("exec", "--help")
    HELP_RULES: ClassVar[dict[str, str]] = {
        "non_interactive": r"^\s*exec\s+Run Codex non-interactively",
        "structured_output": r"--json\b|--output-last-message",
        "json_events": r"--json\b",
        "schema_constrained_output": r"--output-schema\b",
        "read_only_mode": r"read-only",
        "workspace_write_mode": r"workspace-write",
        "sandbox": r"--sandbox\b",
        "custom_model": r"--model\b",
        "custom_provider": r"--local-provider|--oss\b",
        "custom_base_url": r"-c, --config\b",
        "session_resume": r"^\s*resume\s+Resume a previous",
        "server_mode": r"mcp-server|app-server|exec-server",
        "sdk_or_rpc": r"mcp-server|app-server",
        "tool_use": r"model-generated shell commands",
        "web_search": r"--search\b",
    }

    def _build_argv(self, prompt, *, role, writes_final_prose, extra_flags):
        argv = [self.executable, "exec", "--skip-git-repo-check"]
        if self.config.model:
            argv += ["--model", self.config.model]
        argv += list(extra_flags)
        argv.append(prompt)
        return argv
