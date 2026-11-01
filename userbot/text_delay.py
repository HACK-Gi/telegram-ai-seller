"""ការពន្យារពេលដូចមនុស្ស — គន្លឹះក្នុងការកុំឱ្យគណនីត្រូវចាប់សញ្ញា។

គ្រប់ function ទទួល `rand`/`sleep` ចូល ដើម្បីតេស្តកំណត់ពេលវេលាដោយមិនរង់ចាំពិត។
"""
from __future__ import annotations

import asyncio
import random

MIN_DELAY, MAX_DELAY = 5.0, 15.0
TYPING_MIN, TYPING_MAX = 2.0, 5.0
# Telethon `action()` ខ្លីជាង 5s គឺគ្មានន័យទេ (វា cancel ខ្លួនឯងរហូតដល់អស់) ដូច្នេះកាត់ត្រឹម 4s
TELETHON_TYPING_WINDOW = 4.0

CHARS_PER_SECOND = 12.0
PAUSE_PER_SENTENCE = 0.35


def jitter(low: float, high: float, rand: random.Random | None = None) -> float:
    return (rand or random).uniform(low, high)


async def human_delay(
    bounds: tuple[float, float] = (MIN_DELAY, MAX_DELAY),
    *,
    rand: random.Random | None = None,
    sleep=asyncio.sleep,
) -> float:
    """រង់ចាំមួយចន្លោះ 5–15s (warm-up ប្រើ 10–20s) ហើយត្រឡប់ចំនួនវិនាទីដែលបានរង់ចាំ។"""
    seconds = jitter(bounds[0], bounds[1], rand)
    await sleep(seconds)
    return seconds


def typing_seconds(text: str, *, rand: random.Random | None = None) -> float:
    """2–5s សម្រាប់សារខ្លី ប៉ុន្តែវែងតាមប្រវែងសារ ដូចមនុស្សវាយ។"""
    body = text or ""
    base = max(TYPING_MIN, min(TYPING_MAX, len(body) / CHARS_PER_SECOND))
    extra = PAUSE_PER_SENTENCE * max(0, body.count(".") - 1)
    return round(min(TELETHON_TYPING_WINDOW, base + extra), 2)
