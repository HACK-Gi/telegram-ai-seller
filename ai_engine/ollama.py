"""Backend Ollama (/api/chat, stream=false)។"""
from __future__ import annotations

import asyncio

import aiohttp

from ai_engine.base import AIEngine, AIError, Turn, clamp
from ai_engine.openai_compat import to_messages


class OllamaEngine(AIEngine):
    name = "ollama"

    def __init__(self, base_url: str, model: str, timeout: int = 60, temperature: float = 0.7) -> None:
        self.endpoint = base_url.rstrip("/") + "/api/chat"
        self.model = model
        self.timeout = timeout
        self.temperature = temperature
        self._session: aiohttp.ClientSession | None = None

    async def _http(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def generate(self, system: str, history: list[Turn], user_text: str) -> str:
        payload = {
            "model": self.model,
            "messages": to_messages(system, history, user_text),
            "stream": False,
            "options": {"temperature": self.temperature},
        }
        try:
            session = await self._http()
            async with session.post(
                self.endpoint,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            ) as response:
                body = await response.text()
                if response.status != 200:
                    raise AIError(f"HTTP {response.status}: {body[:300]}")
                data = await response.json(content_type=None)
        except AIError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            raise AIError(f"មិនអាចទាក់ទង Ollama បាន: {exc}") from exc

        try:
            content = data["message"]["content"]
        except (KeyError, TypeError) as exc:
            raise AIError(f"ទម្រង់ឆ្លើយមិនត្រឹមត្រូវ: {str(data)[:300]}") from exc
        return clamp(content)

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
