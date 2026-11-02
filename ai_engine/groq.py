"""Groq API Engine — ឥតគិតថ្លៃ និងលឿន (OpenAI-compatible)"""
import os
import logging
from openai import AsyncOpenAI

from ai_engine.base import AIEngine, AIError, Turn

logger = logging.getLogger(__name__)


class GroqEngine(AIEngine):
    """Groq API Backend"""

    name = "groq"

    def __init__(self):
        api_key = os.getenv("GROQ_API_KEY", "").strip()
        if not api_key:
            raise AIError(
                "GROQ_API_KEY មិនបានកំណត់ក្នុង .env!\n"
                "យក Key ពី https://console.groq.com/keys"
            )

        self.model = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")
        self.base_url = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
        self.timeout = int(os.getenv("AI_TIMEOUT", "60"))

        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=self.base_url,
            timeout=self.timeout,
        )
        logger.info(f"GroqEngine initialized (model={self.model})")

    async def generate(self, system: str, history: list[Turn], user_text: str) -> str:
        """ហៅ Groq API ដើម្បីបង្កើតការឆ្លើយតប"""

        # បង្កើត Messages Array
        messages = [{"role": "system", "content": system}]

        # បន្ថែម History (យក ១០ ចុងក្រោយ)
        for turn in history[-10:]:
            messages.append({
                "role": turn.role,
                "content": turn.content,
            })

        # បន្ថែមសារថ្មី
        messages.append({"role": "user", "content": user_text})

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.7,
                max_tokens=1024,
                top_p=0.9,
            )

            reply = response.choices[0].message.content.strip()
            if not reply:
                raise AIError("Groq ត្រឡប់ការឆ្លើយតបទទេ")

            return reply

        except Exception as e:
            logger.error(f"Groq API error: {type(e).__name__}: {e}")
            raise AIError(f"Groq API error: {e}")

    async def close(self) -> None:
        await self.client.close()

