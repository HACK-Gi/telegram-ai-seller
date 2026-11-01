"""កម្រិតការផ្ញើក្នុងមួយគណនី — រាប់ពីតារាង `messages` ដោយផ្ទាល់ (derive) ជំនួស counter។

អត្ថប្រយោជន៍៖ គ្មាន reset job, គ្មាន drift ក្រោយ restart, ហើយរាប់ទាំងសារដែលម្ចាស់
វាយដោយខ្លួនឯង (ដែលក៏រាប់ចូល flood របស់ Telegram ដែរ)។ វិនដូវម៉ោងជា *sliding*
(យើងរាប់ 60 នាទីចុងក្រោយ) ដូច្នេះវាអាចទទួលបាន burst តិចតួចបន្ទាប់ព្រំដែន —
នេះជាលទ្ធផលដែលយើងទទួលស្គាល់ មិនមែនកំហុសទេ។
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from config import settings
from database import crud
from helpers import local_day_start, utcnow
from userbot import text_delay

KIND_DELIVERY = "delivery"
KIND_AI_REPLY = "ai_reply"
KIND_NOTICE = "notice"
KIND_PING = "ping"

# (day_greater_than, daily_cap, delay_range) — ថ្ងៃទី ៧ ឡើងទៅប្រើ CAP_DAY ពេញ
WARMUP_TIERS: tuple[tuple[int, int, tuple[float, float]], ...] = (
    (0, 20, (10.0, 20.0)),
    (1, 25, (10.0, 20.0)),
    (3, 40, (8.0, 16.0)),
    (5, 70, (6.0, 14.0)),
    (6, 110, (5.0, 12.0)),
)


@dataclass(frozen=True)
class Budget:
    hour_used: int
    hour_cap: int
    day_used: int
    day_cap: int          # កម្រិតថ្ងៃសរុប (warm-up tier ឬ CAP_DAY)
    reply_cap: int        # day_cap ដក reserve ទុកឱ្យការផ្ញើ Code
    delay: tuple[float, float]
    warmup_day: int
    blocked_until: datetime | None
    reason: str  # "" | "hour" | "day" | "flood"

    @property
    def open(self) -> bool:
        return self.blocked_until is None

    def allows(self, kind: str = KIND_AI_REPLY) -> bool:
        if self.blocked_until is not None:
            return False
        if kind == KIND_DELIVERY:
            return self.day_used < self.day_cap
        return self.hour_used < self.hour_cap and self.day_used < self.reply_cap

    def describe(self) -> str:
        return f"⏱ {self.hour_used}/{self.hour_cap} ម៉ោងនេះ · 📅 {self.day_used}/{self.day_cap} ថ្ងៃនេះ"


def tier_for(warmup_day: int) -> tuple[int, tuple[float, float]]:
    cap, delay = WARMUP_TIERS[0][1], WARMUP_TIERS[0][2]
    for threshold, tier_cap, tier_delay in WARMUP_TIERS:
        if warmup_day >= threshold:
            cap, delay = tier_cap, tier_delay
    return cap, delay


def warmup_day_for(account, now: datetime | None = None) -> int:
    """-1 = គ្មាន warm-up (skip ឬគណនីចាស់)។"""
    days = int(getattr(account, "warmup_days", 0) or 0)
    started = getattr(account, "warmup_started_at", None)
    if days <= 0 or started is None:
        return -1
    return max(0, ((now or utcnow()) - started).days)


async def current_budget(session, account, *, now: datetime | None = None) -> Budget:
    """ស្ថានភាព budget បច្ចុប្បន្ន — `Budget.allows(kind)` ជ្រើសរើសកម្រិតតាមប្រភេទសារ។"""
    now = now or utcnow()
    hour_start = now - timedelta(hours=1)
    day_start = local_day_start(0)
    hour_used, day_used = await crud.sent_counts_for_account(session, account.id, hour_start, day_start)

    cap_hour = settings.userbot_cap_hour
    cap_day = settings.userbot_cap_day
    delay = (text_delay.MIN_DELAY, text_delay.MAX_DELAY)

    day = warmup_day_for(account, now)
    if day >= 0:
        tier_cap, tier_delay = tier_for(day)
        cap_day = min(cap_day, tier_cap)
        delay = tier_delay
    reply_cap = max(1, cap_day - settings.userbot_delivery_reserve)

    blocked_until: datetime | None = None
    reason = ""
    pause_until = getattr(account, "pause_until", None)
    if pause_until is not None and pause_until > now:
        blocked_until, reason = pause_until, "flood"
    elif hour_used >= cap_hour:
        oldest = await crud.oldest_sent_in_window(session, account.id, hour_start)
        blocked_until = (oldest + timedelta(hours=1)) if oldest else now + timedelta(minutes=5)
        reason = "hour"
    elif day_used >= cap_day:
        blocked_until = local_day_start(-1)  # កម្រិតថ្ងៃរีសេតនៅម៉ោង ០០:០០ ម៉ោងក្នុងស្រុក
        reason = "day"

    return Budget(
        hour_used=hour_used,
        hour_cap=cap_hour,
        day_used=day_used,
        day_cap=cap_day,
        reply_cap=reply_cap,
        delay=delay,
        warmup_day=day,
        blocked_until=blocked_until,
        reason=reason,
    )
