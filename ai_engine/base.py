"""AIEngine — ចំណុចប្រសព្វតែមួយសម្រាប់គ្រប់ backend (Qoder CLI / OpenAI-compat / Ollama / mock)។

Userbot ប្រើតែ `generate()` ដូច្នេះការប្តូរ backend មិនប៉ះកូដផ្សេងទេ។
"""
from __future__ import annotations

import abc
import re
from dataclasses import dataclass


class AIError(Exception):
    """កំហុសពី backend (timeout, បណ្តាញ, CLI មិនមាន, ឬ តម្លៃឆ្លើយមិនត្រឹមត្រូវ)។"""


@dataclass(frozen=True)
class Turn:
    role: str  # "user" | "assistant"
    content: str


class AIEngine(abc.ABC):
    name: str = "base"

    @abc.abstractmethod
    async def generate(self, system: str, history: list[Turn], user_text: str) -> str:
        """ផ្តល់ system prompt + ប្រវត្តិ + សារចុងក្រោយ ហើយត្រឡប់អត្ថបទឆ្លើយតប។

        បោះ AIError ជំនួសឱ្យ exception របស់ library ខាងក្រៅ។
        """

    async def close(self) -> None:
        return None

    async def __aenter__(self) -> "AIEngine":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()


def clamp(text: str, limit: int = 3500) -> str:
    text = (text or "").strip()
    return text[:limit]


# ---------- ការពារ Echo (ចម្លងសារអតិថិជនត្រឡប់មកវិញ) ----------

MIN_REPLY_LEN = 5

_LINE_MARKER = re.compile(
    r"^\s*(?:\[[^\]]*\]|(?:អតិថិជន|អ្នក|user|customer|bot|assistant|ai)\s*[:៖])\s*",
    re.IGNORECASE,
)
_ECHO_PHRASE = re.compile(r"^ខ្ញុំទទួលបាន\s*[:៖]?\s*")
_FOREIGN_SCRIPT = re.compile(r"[\u0e00-\u0e7f\u3040-\u30ff\u31f0-\u31ff\u4e00-\u9fff\uac00-\ud7af]+")


def _norm(text: str) -> str:
    return re.sub(r"[\s៖:.,!?]+$", "", re.sub(r"\s+", "", text or "")).lower()


def strip_echo(reply: str, user_text: str) -> str:
    """កាត់ខ្សែដែលចម្លងសារអតិថិជនត្រឡប់មកវិញ (រួមទាំង fallback `[mock] ខ្ញុំទទួលបាន:`)។"""
    echoed = _norm(user_text)
    if not echoed:
        return (reply or "").strip()
    kept = []
    for line in (reply or "").splitlines():
        core = _LINE_MARKER.sub("", line).strip()
        if core:
            variant = _ECHO_PHRASE.sub("", core)
            if _norm(core) == echoed or (variant != core and _norm(variant) == echoed):
                continue
        kept.append(line)
    return "\n".join(kept).strip()


def accept_reply(reply: str, user_text: str) -> str:
    """បើចម្លើយត្រឹមត្រូវ → ត្រឡប់វា បើទទេ/ខ្លីពេក/ជា echo សុទ្ធ → "" ដើម្បី Retry ឬ Fallback។"""
    cleaned = strip_echo(reply or "", user_text)
    cleaned = _FOREIGN_SCRIPT.sub("", cleaned).strip()
    if len(cleaned) < MIN_REPLY_LEN:
        return ""
    if _norm(cleaned) == _norm(user_text):
        return ""
    return cleaned
