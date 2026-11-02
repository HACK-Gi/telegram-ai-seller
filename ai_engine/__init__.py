"""Factory — ជ្រើសរើស backend តាម AI_BACKEND ក្នុង .env ហើយរក្សា instance តែមួយ។"""
from __future__ import annotations

import os

from ai_engine.base import AIEngine, AIError, Turn
from ai_engine.chain import AIAllFailed, BackendChain, SAFE_REPLY
from config import settings

__all__ = [
    "AIEngine",
    "AIError",
    "AIAllFailed",
    "BackendChain",
    "SAFE_REPLY",
    "Turn",
    "get_engine",
    "close_engine",
]

_engine: AIEngine | None = None


def _build() -> AIEngine:
    backend = settings.ai_backend
    if backend == "mock":
        from ai_engine.mock import MockEngine

        return MockEngine()
    if backend == "groq":
        from ai_engine.groq import GroqEngine

        return GroqEngine()
    if backend == "qoder_cli":
        from ai_engine.qoder_cli import QoderCLIEngine

        return QoderCLIEngine(
            binary=settings.qoder_cli_bin,
            args_template=settings.qoder_cli_args,
            timeout=settings.qoder_cli_timeout,
        )
    if backend == "openai":
        from ai_engine.openai_compat import OpenAICompatEngine

        return OpenAICompatEngine(
            base_url=settings.openai_base_url,
            model=settings.openai_model,
            api_key=settings.openai_api_key,
            timeout=settings.ai_timeout,
        )
    if backend == "ollama":
        from ai_engine.ollama import OllamaEngine

        return OllamaEngine(
            base_url=settings.ollama_base_url,
            model=settings.ollama_model,
            timeout=settings.ai_timeout,
        )
    raise AIError(f"AI_BACKEND '{backend}' មិនស្គាល់ (mock | groq | qoder_cli | openai | ollama)")


def _fallback_engines(primary: AIEngine) -> list[AIEngine]:
    """Chain fallback ស្វ័យប្រវត្តិ៖ Groq/OpenAI-compat តាមលំដាប់ បញ្ចប់ដោយ mock
    (AI_BACKEND=mock នៅតែសុទ្ធ ដើម្បីតេស្ត)។"""
    if primary.name == "mock":
        return []
    chain: list[AIEngine] = []
    # Fallback to Groq if primary is not Groq
    if primary.name != "groq" and os.getenv("GROQ_API_KEY"):
        from ai_engine.groq import GroqEngine
        try:
            chain.append(GroqEngine())
        except Exception:
            pass
    # Fallback to OpenAI if primary is not OpenAI
    if primary.name != "openai" and settings.openai_base_url:
        from ai_engine.openai_compat import OpenAICompatEngine

        chain.append(
            OpenAICompatEngine(
                base_url=settings.openai_base_url,
                model=settings.openai_model,
                api_key=settings.openai_api_key,
                timeout=settings.ai_timeout,
            )
        )
    # Last resort: mock — បើគ្រប់ backend ពិតបរាជ័យ កុំឱ្យ Bot ស្ងាត់
    # (seller.py ជូនដំណឹងម្ចាស់ នៅពេលចម្លើយមកពី mock)។
    from ai_engine.mock import MockEngine

    chain.append(MockEngine())
    return chain


def get_engine() -> AIEngine:
    global _engine
    if _engine is None:
        primary = _build()
        fallbacks = _fallback_engines(primary)
        _engine = BackendChain([primary, *fallbacks]) if fallbacks else primary
    return _engine


async def close_engine() -> None:
    global _engine
    if _engine is not None:
        await _engine.close()
        _engine = None
