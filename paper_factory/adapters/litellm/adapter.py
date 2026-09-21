"""LiteLLM gateway adapter (OpenAI-compatible HTTP endpoint, no binary).

No local executable is required. The endpoint is probed (``GET /models``)
ONLY when ``base_url_env`` resolves to a configured URL; otherwise the
adapter reports UNAVAILABLE without touching the network. Config never
contains secrets — only the *names* of the env vars holding them.
"""
from __future__ import annotations

import os
from typing import Any, ClassVar

from ...core.util import sha256_bytes, utcnow
from ..base import HarnessAdapter, HarnessUnavailable, InvocationReceipt

# Static capabilities of the OpenAI-compatible gateway contract. These come
# from the API contract, not from name-guessing; there is no --help to parse.
_GATEWAY_CAPABILITIES = frozenset(
    {"non_interactive", "structured_output", "custom_model", "custom_provider", "custom_base_url"}
)


class LiteLLMAdapter(HarnessAdapter):
    kind = "litellm"
    default_executable = ""  # gateway: no binary
    HELP_RULES: ClassVar[dict[str, str]] = {}

    def __init__(self, name: str | None = None, config=None):
        super().__init__(name, config)
        self.base_url_env = self.config.base_url_env
        self.api_key_env = self.config.api_key_env

    def _base_url(self, env: dict[str, str] | None = None) -> str | None:
        env = os.environ if env is None else env
        raw = env.get(self.base_url_env or "", "")
        return raw.rstrip("/") or None

    def present(self) -> bool:  # type: ignore[override]
        return self._base_url() is not None

    def capabilities(self) -> set[str]:  # type: ignore[override]
        return set(_GATEWAY_CAPABILITIES) if self.present() else set()

    def doctor(self) -> dict[str, Any]:  # type: ignore[override]
        out: dict[str, Any] = {
            "harness": self.name,
            "kind": self.kind,
            "executable": None,
            "base_url_env": self.base_url_env,
            "api_key_env": self.api_key_env,
            "present": False,
            "version": None,
            "capabilities": [],
            "verdict": "UNAVAILABLE",
        }
        base = self._base_url()
        if not base:
            out["note"] = f"env var {self.base_url_env!r} not set; endpoint not probed"
            return out
        out["endpoint_alias"] = self.provider_identity().get("endpoint_alias")
        if not self.api_key_env or not os.environ.get(self.api_key_env):
            out["note"] = f"env var {self.api_key_env!r} not set; endpoint not probed"
            return out
        import requests

        try:
            resp = requests.get(
                f"{base}/models",
                headers={"Authorization": f"Bearer {os.environ[self.api_key_env]}"},
                timeout=10,
            )
            out["present"] = resp.status_code == 200
            out["http_status"] = resp.status_code
            if out["present"]:
                out["verdict"] = "PASS"
                out["capabilities"] = sorted(_GATEWAY_CAPABILITIES)
        except requests.RequestException as exc:  # network down, DNS, TLS, ...
            out["note"] = f"probe failed: {type(exc).__name__}"
        return out

    def _build_argv(self, prompt, *, role, writes_final_prose, extra_flags) -> list[str]:
        raise NotImplementedError("litellm is an HTTP gateway; invoke() posts directly")

    def invoke(self, prompt, *, role=None, writes_final_prose=False, timeout=600, extra_flags=()):
        base = self._base_url()
        if not base or not self.api_key_env or not os.environ.get(self.api_key_env):
            raise HarnessUnavailable(f"gateway {self.name!r} is not configured")
        import requests

        exit_code = 0
        response_text = ""
        try:
            resp = requests.post(
                f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {os.environ[self.api_key_env]}"},
                json={
                    "model": self.config.model,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=timeout,
            )
            exit_code = 0 if resp.status_code == 200 else resp.status_code
            data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            response_text = (
                data.get("choices", [{}])[0].get("message", {}).get("content", "") or resp.text
            )
        except requests.RequestException as exc:
            raise HarnessUnavailable(f"gateway {self.name!r} request failed: {exc}") from exc
        backend = self.provider_identity()
        return InvocationReceipt(
            harness=self.name,
            harness_version=None,
            provider=self.name,
            provider_family=backend.get("provider_family", "unknown"),
            model=self.config.model,
            model_family=backend.get("model_family", "unknown"),
            endpoint_alias=backend.get("endpoint_alias"),
            role=role,
            writes_final_prose=writes_final_prose,
            session_identity={"supported": False, "session_id": None, "source": "stateless_http"},
            timestamp=utcnow(),
            prompt_sha256=sha256_bytes(prompt.encode("utf-8")),
            response_sha256=sha256_bytes(response_text.encode("utf-8")),
            exit_code=exit_code,
            detail={"endpoint_alias": backend.get("endpoint_alias")},
        )
