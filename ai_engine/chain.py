"""BackendChain — លំដាប់ backend (ឧ. qoder_cli → openai) ជាមួយការត្រួតពិនិត្យចម្លើយ។

- ចម្លើយទទេ/ខ្លីពេក/ជា echo → Retry ម្តងនៅ backend ដដែល រួចលោតទៅ backend បន្ទាប់។
- AIError នៅ backend ណា → ទៅ backend បន្ទាប់ភ្លាម (មិន retry ការហៅថ្លៃ)។
- គ្រប់ backend បរាជ័យ → AIAllFailed (អ្នកហៅ ជូនដំណឹងម្ចាស់ + ផ្ញើ SAFE_REPLY)។
"""
from __future__ import annotations

from ai_engine.base import AIEngine, AIError, Turn, accept_reply

SAFE_REPLY = "សូមរង់ចាំបន្តិច ខ្ញុំកំពុងពិនិត្យ។"


class AIAllFailed(AIError):
    """គ្រប់ backend ក្នុង chain បរាជ័យ — `.attempts` មានបញ្ជីមូលហេតុ per backend។"""

    def __init__(self, attempts: list[str]) -> None:
        self.attempts = list(attempts)
        super().__init__(" | ".join(self.attempts) or "គ្មាន backend ដែលដំណើរការ")


class BackendChain(AIEngine):
    def __init__(self, engines: list[AIEngine]) -> None:
        if not engines:
            raise ValueError("BackendChain ត្រូវការយ៉ាងហោចណាស់ ១ backend")
        self._engines = list(engines)
        self.last_backend = ""
        self.fell_back = False
        self.attempts: list[str] = []

    @property
    def name(self) -> str:  # type: ignore[override]
        if len(self._engines) == 1:
            return self._engines[0].name
        return f"{self._engines[0].name} → fallback: {', '.join(e.name for e in self._engines[1:])}"

    async def generate(self, system: str, history: list[Turn], user_text: str) -> str:
        self.fell_back = False
        self.attempts = []
        for index, engine in enumerate(self._engines):
            for _ in range(2):  # retry ម្តង សម្រាប់តែករណីចម្លើយមិនត្រឹមត្រូវ (echo/ទទេ)
                try:
                    raw = await engine.generate(system, history, user_text)
                except AIError as exc:
                    self.attempts.append(f"{engine.name}: {exc}")
                    break
                reply = accept_reply(raw, user_text)
                if reply:
                    self.last_backend = engine.name
                    self.fell_back = index > 0
                    return reply
                self.attempts.append(f"{engine.name}: ចម្លើយជា echo ឬខ្លីពេក — បដិសេធ")
        raise AIAllFailed(self.attempts)

    async def close(self) -> None:
        for engine in self._engines:
            await engine.close()
