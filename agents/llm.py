"""Model clients.

`AzureOpenAIClient` talks to a model deployed in Microsoft Foundry (Azure
OpenAI chat completions API) with nothing but the standard library.
`OfflineClient` returns deterministic, template-based answers built from
the same prompt payload, so the whole pipeline runs in tests and demos
without spending credit. `get_client()` picks Azure when its environment
variables are set and falls back to offline otherwise.
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Protocol

API_VERSION = "2024-10-21"


class LLMError(RuntimeError):
    pass


class LLMClient(Protocol):
    name: str

    def complete_json(self, system: str, payload: dict[str, Any], *, temperature: float = 0.4) -> dict[str, Any]:
        """Send a system prompt plus a JSON payload; return the model's JSON reply."""
        ...


class AzureOpenAIClient:
    name = "azure-openai"

    def __init__(self, endpoint: str, api_key: str, deployment: str, *, timeout: float = 30.0, retries: int = 2):
        self.url = f"{endpoint.rstrip('/')}/openai/deployments/{deployment}/chat/completions?api-version={API_VERSION}"
        self.api_key = api_key
        self.deployment = deployment
        self.timeout = timeout
        self.retries = retries
        self.calls = 0
        self.tokens = 0
        self._lock = threading.Lock()  # agents call in parallel

    def complete_json(self, system: str, payload: dict[str, Any], *, temperature: float = 0.4) -> dict[str, Any]:
        body = json.dumps(
            {
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                "temperature": temperature,
                "response_format": {"type": "json_object"},
            }
        ).encode()
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            req = urllib.request.Request(
                self.url, data=body, headers={"Content-Type": "application/json", "api-key": self.api_key}
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = json.loads(resp.read())
                with self._lock:
                    self.calls += 1
                    self.tokens += data.get("usage", {}).get("total_tokens", 0)
                return json.loads(data["choices"][0]["message"]["content"])
            except urllib.error.HTTPError as exc:
                last = exc
                if exc.code not in (408, 429, 500, 502, 503, 504):
                    break
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError) as exc:
                last = exc
            time.sleep(1.5 * (attempt + 1))
        raise LLMError(f"Azure OpenAI call failed: {last}")


class OfflineClient:
    """Deterministic stand-in. Each agent registers a template for its task."""

    name = "offline"

    def __init__(self) -> None:
        self.calls = 0

    def complete_json(self, system: str, payload: dict[str, Any], *, temperature: float = 0.4) -> dict[str, Any]:
        from .offline import respond  # local import keeps templates out of the hot path

        self.calls += 1
        return respond(payload)


def get_client() -> LLMClient:
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
    key = os.environ.get("AZURE_OPENAI_API_KEY")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4.1-mini")
    if endpoint and key and os.environ.get("INSIGHTS_OFFLINE") != "1":
        return AzureOpenAIClient(endpoint, key, deployment)
    return OfflineClient()
