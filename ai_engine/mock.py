"""Backend mock — ប្រើសម្រាប់សាកល្បងដោយគ្មាន m៉ាស៊ីន AI (AI_BACKEND=mock)។"""
from __future__ import annotations

import asyncio

from ai_engine.base import AIEngine, Turn

RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("សួស្តី", "hi", "hello"), "សួស្តីបង! 🙏 មានអ្វីអាចជួយបានទេ?"),
    (("តម្លៃ", "price", "ប៉ុន្មាន"), "តម្លៃ {price} បង។ បងចង់យកទេ?"),
    (("ចង់ទិញ", "ទិញ", "buy", "យក"), "បានបង! បងអាចទូទាត់តាម QR រួចផ្ញើ Slip មកខ្ញុំបានភ្លាមៗ 🙏"),
    (("slip", "បានបង់", "បង់ប្រាក់រួច"), "អរគុណបង! ខ្ញុំបានទទួល Slip ហើយ ខ្ញុំនឹងប្រគល់ Code ឱ្យបងឆាប់ៗនេះ 🙂"),
    (("មិនដឹង", "ជួបមនុស្ស", "human"), "ខ្ញុំនឹងឱ្យអ្នកគ្រប់គ្រងទាក់ទងទៅអ្នកវិញបង 🙏"),
)


class MockEngine(AIEngine):
    name = "mock"

    def __init__(self, latency: float = 0.2) -> None:
        self.latency = latency
        self.calls: list[int] = []  # ចំនួន turns ដែលបានផ្ញើមក (សម្រាប់តេស្ត context)

    async def generate(self, system: str, history: list[Turn], user_text: str) -> str:
        await asyncio.sleep(self.latency)
        self.calls.append(len(history))
        lowered = user_text.lower()
        for keywords, template in RULES:
            if any(word.lower() in lowered for word in keywords):
                return template.format(price="$5.00")
        return f"[mock] ខ្ញុំទទួលបាន: {user_text[:80]}"
