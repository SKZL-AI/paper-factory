"""Harness adapter base.

Discovery is probe-only: an adapter may run ``<exe> --help`` and
``<exe> --version`` to learn capabilities, nothing more. Capabilities are
NEVER inferred from the harness name; they come from parsing the help text
(see ``capabilities_from_help``). Real invocations go through ``invoke()``
and always produce an :class:`InvocationReceipt`.
"""
from __future__ import annotations

import abc
import re
import shutil
import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from ..core.config import ProviderEntry
from ..core.util import append_jsonl, sha256_bytes, utcnow

PROBE_TIMEOUT = 20  # seconds; --help/--version probes only

ALL_CAPABILITIES = frozenset(
    {
        "non_interactive",
        "structured_output",
        "json_events",
        "schema_constrained_output",
        "read_only_mode",
        "workspace_write_mode",
        "sandbox",
        "custom_model",
        "custom_provider",
        "custom_base_url",
        "session_resume",
        "server_mode",
        "sdk_or_rpc",
        "tool_use",
        "web_search",
        "skills",
        "slash_commands",
    }
)


class HarnessUnavailable(Exception):
    """The harness binary/endpoint is missing, broken, or refused the call."""


class InvocationReceipt(BaseModel):
    """One record per real harness invocation. Hashes, never raw content."""

    harness: str
    harness_version: str | None = None
    provider: str = "unknown"
    provider_family: str = "unknown"
    model: str | None = None
    model_family: str = "unknown"
    endpoint_alias: str | None = None
    role: str | None = None
    writes_final_prose: bool = False
    marking_status: str = "unknown"
    session_identity: dict[str, Any] = Field(default_factory=dict)
    timestamp: str = ""
    prompt_sha256: str = ""
    response_sha256: str | None = None
    exit_code: int = -1
    detail: dict[str, Any] = Field(default_factory=dict)

    def to_jsonl(self, path: Path) -> None:
        append_jsonl(Path(path), self.model_dump(mode="json"))


_VERSION_RE = re.compile(r"(\d+(?:\.\d+)+)")


def capabilities_from_help(help_text: str, rules: dict[str, str]) -> set[str]:
    """Map help text to capability strings. *rules*: capability -> regex.

    Pure function (no subprocess) so tests can feed cached/synthetic help.
    """
    caps: set[str] = set()
    for cap, pattern in rules.items():
        if cap not in ALL_CAPABILITIES:
            raise ValueError(f"unknown capability string: {cap!r}")
        if re.search(pattern, help_text, re.IGNORECASE | re.MULTILINE):
            caps.add(cap)
    return caps


class HarnessAdapter(abc.ABC):
    """One adapter per harness *kind*; instances are per configured provider."""

    kind: str = "unknown"
    default_executable: str = ""
    #: capability -> regex matched against the harness' own --help text
    HELP_RULES: ClassVar[dict[str, str]] = {}
    #: extra probe commands whose help output is concatenated (e.g. ["exec", "--help"])
    EXTRA_HELP_ARGS: ClassVar[tuple[str, ...]] = ()

    def __init__(self, name: str | None = None, config: ProviderEntry | None = None):
        self.name = name or self.kind
        self.config = config or ProviderEntry(adapter=self.kind)
        exe = self.config.executable or self.default_executable
        resolved = shutil.which(exe) if exe else None
        self.executable: str | None = resolved or (exe if exe and Path(exe).exists() else None)
        self._help_cache: str | None = None
        self._version_cache: str | None | bool = False
        self._caps_cache: set[str] | None = None

    # -- probes (the only subprocesses discovery may run) ------------------
    def _probe(self, args: Iterable[str]) -> tuple[int, str]:
        if not self.executable:
            return -1, ""
        try:
            proc = subprocess.run(
                [self.executable, *args],
                capture_output=True,
                text=True,
                timeout=PROBE_TIMEOUT,
                check=False,
            )
            return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
        except (OSError, subprocess.TimeoutExpired):
            return -1, ""

    def help_text(self) -> str:
        if self._help_cache is None:
            parts = [self._probe(["--help"])[1]]
            if self.EXTRA_HELP_ARGS:
                parts.append(self._probe(list(self.EXTRA_HELP_ARGS))[1])
            self._help_cache = "\n".join(parts)
        return self._help_cache

    def version(self) -> str | None:
        if self._version_cache is False:
            rc, out = self._probe(["--version"])
            m = _VERSION_RE.search(out) if rc == 0 or out else None
            self._version_cache = m.group(1) if m else None
        return self._version_cache  # type: ignore[return-value]

    def present(self) -> bool:
        return self.executable is not None and bool(self.help_text().strip())

    # -- discovery ---------------------------------------------------------
    def capabilities(self) -> set[str]:
        if self._caps_cache is None:
            if not self.present():
                self._caps_cache = set()
            else:
                self._caps_cache = capabilities_from_help(self.help_text(), self.HELP_RULES)
        return self._caps_cache

    def doctor(self) -> dict[str, Any]:
        ok = self.present()
        out: dict[str, Any] = {
            "harness": self.name,
            "kind": self.kind,
            "executable": self.executable,
            "present": ok,
            "version": self.version() if ok else None,
            "capabilities": sorted(self.capabilities()),
            "verdict": "PASS" if ok else "UNAVAILABLE",
        }
        if not ok:
            out["note"] = "executable not found or --help probe failed"
        return out

    # -- identity (honest: unknown stays unknown) ---------------------------
    def provider_identity(self) -> dict[str, Any]:
        from ..providers.identity import resolve_backend

        return resolve_backend(self.kind, self.config)

    def model_identity(self) -> dict[str, Any]:
        backend = self.provider_identity()
        return {
            "model": self.config.model,
            "model_family": backend.get("model_family", "unknown"),
            "source": "providers.yaml" if self.config.model else "harness_default",
        }

    def session_identity(self) -> dict[str, Any]:
        return {
            "supported": "session_resume" in self.capabilities(),
            "session_id": None,
            "source": "not_created_by_adapter",
        }

    # -- invocation ---------------------------------------------------------
    @abc.abstractmethod
    def _build_argv(
        self,
        prompt: str,
        *,
        role: str | None,
        writes_final_prose: bool,
        extra_flags: tuple[str, ...],
    ) -> list[str]:
        """Assemble the non-interactive command line for one invocation."""

    def invoke(
        self,
        prompt: str,
        *,
        role: str | None = None,
        writes_final_prose: bool = False,
        timeout: int = 600,
        extra_flags: tuple[str, ...] = (),
    ) -> InvocationReceipt:
        if not self.doctor()["present"]:
            raise HarnessUnavailable(f"harness {self.name!r} is not available")
        argv = self._build_argv(
            prompt, role=role, writes_final_prose=writes_final_prose, extra_flags=tuple(extra_flags)
        )
        try:
            proc = subprocess.run(
                argv, capture_output=True, text=True, timeout=timeout, check=False
            )
            response = proc.stdout or ""
            exit_code = proc.returncode
            stderr_tail = (proc.stderr or "")[-2000:]
        except subprocess.TimeoutExpired as exc:
            response = exc.stdout if isinstance(exc.stdout, str) else ""
            exit_code = -1
            stderr_tail = f"TIMEOUT after {timeout}s"
        except OSError as exc:
            raise HarnessUnavailable(f"failed to exec {argv[0]!r}: {exc}") from exc
        backend = self.provider_identity()
        return InvocationReceipt(
            harness=self.name,
            harness_version=self.version(),
            provider=self.name,
            provider_family=backend.get("provider_family", "unknown"),
            model=self.config.model,
            model_family=backend.get("model_family", "unknown"),
            endpoint_alias=backend.get("endpoint_alias"),
            role=role,
            writes_final_prose=writes_final_prose,
            session_identity=self.session_identity(),
            timestamp=utcnow(),
            prompt_sha256=sha256_bytes(prompt.encode("utf-8")),
            response_sha256=sha256_bytes(response.encode("utf-8")),
            exit_code=exit_code,
            detail={"argv0": argv[0], "stderr_tail": stderr_tail},
        )
