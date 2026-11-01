"""ជំនួយទូទៅ៖ ពេលវេលា (UTC ក្នុង DB) និងការរៀបចំអក្សរសម្រាប់ HTML។"""
from __future__ import annotations

import html
from datetime import datetime, timedelta, tzinfo
from zoneinfo import ZoneInfo

from config import settings

# SQLite + SQLAlchemy ដំណើរការបានស្ងប់ស្ងាត់បំផុតជាមួយ naive UTC
# ដូច្នេះគ្រប់ timestamp ក្នុង DB គឺ naive UTC; បង្ហាញជាម៉ោងក្នុងស្រុកតាមរយៈ as_local()។
def utcnow() -> datetime:
    return datetime.now(ZoneInfo("UTC")).replace(tzinfo=None)


def local_tz() -> tzinfo:
    return ZoneInfo(settings.timezone)


def local_now() -> datetime:
    return datetime.now(local_tz())


def as_local(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(local_tz())


def format_dt(dt: datetime | None, fmt: str = "%d/%m/%Y %H:%M") -> str:
    local = as_local(dt)
    return local.strftime(fmt) if local else "—"


def local_day_start(days_ago: int = 0) -> datetime:
    """ព្រឹកម៉ោង ០០:០០ (ម៉ោងក្នុងស្រុក) នៃថ្ងៃមុន `days_ago` ថ្ងៃ គិតជា naive UTC។"""
    now = local_now() - timedelta(days=days_ago)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)


def parse_window(spec: str | None) -> tuple[int, int] | None:
    """'08:30-22:15' -> (510, 1335) នាទីពីកណ្តាលចន ម៉ោងក្នុងស្រុក។ None/ខុសទ្រង់ទ្រាយ -> None (២៤ ម៉ោង)"""
    if not spec:
        return None
    try:
        left, right = spec.split("-", 1)
        lh, lm = left.strip().split(":")
        rh, rm = right.strip().split(":")
        return int(lh) * 60 + int(lm), int(rh) * 60 + int(rm)
    except (ValueError, AttributeError):
        return None


def in_window(spec: str | None, at: datetime | None = None) -> bool:
    """ពិតប្រាកដដល់នាទី ហើយគ្របរាល់ចុងថ្ងៃ (20:00-06:00)។ spec None = ២៤ ម៉ោង។"""
    window = parse_window(spec)
    if window is None:
        return True
    at = at or local_now()
    start, end = window
    minutes = at.hour * 60 + at.minute
    return start <= minutes < end if start <= end else minutes >= start or minutes < end


def ago(dt: datetime | None) -> str:
    """'4 នាទីមុន' — សម្រាប់ Panel បង្ហាញ heartbeat ដោយស្មោះត្រង់។"""
    if dt is None:
        return "មិនដែល"
    delta = utcnow() - dt
    seconds = int(delta.total_seconds())
    if seconds < 0:
        return "អនាគត"
    if seconds < 60:
        return f"{seconds} វិនាទីមុន"
    if seconds < 3600:
        return f"{seconds // 60} នាទីមុន"
    if seconds < 86400:
        return f"{seconds // 3600} ម៉ោងមុន"
    return f"{seconds // 86400} ថ្ងៃមុន"


def parse_hours(spec: str) -> tuple[int, int] | None:
    """'08:00-23:00' -> (8, 23)។ ទទេ ឬខុសទ្រង់ទ្រាយ -> None (មានន័យថា ២៤ ម៉ោង)"""
    try:
        left, right = spec.split("-", 1)
        return int(left.split(":")[0]), int(right.split(":")[0])
    except (ValueError, AttributeError):
        return None


def in_working_hours(spec: str, at: datetime | None = None) -> bool:
    hours = parse_hours(spec)
    if hours is None:
        return True
    at = at or local_now()
    start, end = hours
    return start <= at.hour < end if start <= end else at.hour >= start or at.hour < end


def esc(text: object) -> str:
    """គេប្រើ ParseMode.HTML គ្រប់ទីកន្លែង ដូច្នេះត្រូវ escape អត្ថបទពីអ្នកប្រើ។"""
    return html.escape(str(text if text is not None else ""), quote=False)


def money(value: float | int | None) -> str:
    return f"${(value or 0):,.2f}"


def shorten(text: str, limit: int = 60) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def pagination_pages(total: int, per_page: int = 10) -> int:
    return max(1, -(-total // per_page))
