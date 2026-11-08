"""OpenAI 互換 API への転送。

OpenAI / Azure OpenAI / vLLM / Ollama など、同じ形の API なら向けられる。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class UpstreamResponse:
    status_code: int
    body: Any
    model: str | None


class OpenAICompatForwarder:
    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        model_override: str | None = None,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model_override = model_override
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)

    async def forward(self, body: dict[str, Any]) -> UpstreamResponse:
        payload = dict(body)
        if self._model_override:
            payload["model"] = self._model_override
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        r = await self._client.post(
            f"{self._base_url}/chat/completions", json=payload, headers=headers
        )
        try:
            data = r.json()
        except ValueError:
            data = {"error": {"message": r.text[:500], "type": "upstream_non_json"}}
        return UpstreamResponse(r.status_code, data, payload.get("model"))

    async def aclose(self) -> None:
        await self._client.aclose()
