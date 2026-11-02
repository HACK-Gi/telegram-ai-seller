"""Backend OpenAI-compatible (/v1/chat/completions) — vLLM, LM Studio, OpenRouter, Qwen endpoint..."""
from __future__ import annotations

import asyncio
from urllib.parse import urlparse

import aiohttp

from ai_engine.base import AIEngine, AIError, Turn, clamp


def _hint_for(endpoint: str) -> str:
    """Local endpoint down → most likely the Qoder proxy isn't running."""
    host = urlparse(endpoint).hostname or ""
    if host in ("127.0.0.1", "localhost", "::1"):
        return (
            f"\n({endpoint} មិនឆ្លើយ — បើវាជា Qoder Proxy សូមរត់: ./scripts/run_qoder_proxy.sh"
            f" ឬ ./scripts/install_qoder.sh បើគ្មាន qodercli)"
        )
    return ""


def to_messages(system: str, history: list[Turn], user_text: str) -> list[dict[str, str]]:
    messages = [{"role": "system", "content": system}]
    messages.extend({"role": turn.role, "content": turn.content} for turn in history)
    messages.append({"role": "user", "content": user_text})
    return messages


class OpenAICompatEngine(AIEngine):
    name = "openai"

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "",
        timeout: int = 60,
        temperature: float = 0.7,
    ) -> None:
        self.endpoint = base_url.rstrip("/") + "/chat/completions"
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.temperature = temperature
        self._session: aiohttp.ClientSession | None = None

    async def _http(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def generate(self, system: str, history: list[Turn], user_text: str) -> str:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {
            "model": self.model,
            "messages": to_messages(system, history, user_text),
            "temperature": self.temperature,
            "stream": False,
        }
        try:
            session = await self._http()
            async with session.post(
                self.endpoint,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            ) as response:
                body = await response.text()
                if response.status != 200:
                    raise AIError(f"HTTP {response.status}: {body[:300]}")
                data = await response.json(content_type=None)
        except AIError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            raise AIError(f"មិនអាចទាក់ទង endpoint បាន: {exc}{_hint_for(self.endpoint)}") from exc

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AIError(f"ទម្រង់ឆ្លើយមិនត្រឹមត្រូវ: {str(data)[:300]}") from exc
        return clamp(content)

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
