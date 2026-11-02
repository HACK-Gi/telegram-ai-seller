"""ការកំណត់កណ្តាល — អានពី .env ម្តងតែប៉ុណ្ណោះ។"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

MEDIA_DIR = BASE_DIR / "media"
PRODUCT_MEDIA_DIR = MEDIA_DIR / "products"
QR_MEDIA_DIR = MEDIA_DIR / "qr"
BACKUP_DIR = BASE_DIR / "backups"
LOG_DIR = BASE_DIR / "logs"
SESSION_DIR = BASE_DIR / "data" / "sessions"

# គេហទំព័រ «Make Session» (session_web/) — ភ្ញៀវបង្កើត Session String ខ្លួនឯង មុនផ្ញើមក
# /addsession។ កែតាម SESSION_WEB_URL; ដាក់វត្ថុដែលមិនចាប់ផ្តើមដោយ http = លាក់តំណ។
DEFAULT_SESSION_WEB_URL = "https://bot-auto-sell-make-session.vercel.app"

for _d in (PRODUCT_MEDIA_DIR, QR_MEDIA_DIR, BACKUP_DIR, LOG_DIR, SESSION_DIR, MEDIA_DIR):
    _d.mkdir(parents=True, exist_ok=True)


def _int(name: str, default: int = 0) -> int:
    raw = (os.getenv(name) or "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        raise ValueError(f"{name} ត្រូវតែជាលេខ, បានទទួល '{raw}'") from None


def _ids(name: str) -> tuple[int, ...]:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return ()
    return tuple(int(p.strip()) for p in raw.split(",") if p.strip())


def _bool(name: str, default: bool = False) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    bot_token: str
    owner_id: int
    admin_ids: tuple[int, ...]
    timezone: str
    use_mock_bot: bool
    database_url: str
    fernet_key: str

    ai_backend: str
    groq_api_key: str
    groq_model: str
    groq_base_url: str
    qoder_cli_bin: str
    qoder_cli_args: str
    qoder_cli_timeout: int
    openai_base_url: str
    openai_api_key: str
    openai_model: str
    ollama_base_url: str
    ollama_model: str
    ai_history_limit: int
    ai_timeout: int

    tg_api_id: int
    tg_api_hash: str

    userbot_cap_hour: int
    userbot_cap_day: int
    userbot_delivery_reserve: int

    working_hours: str
    stock_alert_threshold: int
    language: str
    session_web_url: str

    def is_owner(self, user_id: int) -> bool:
        return user_id == self.owner_id


def _load() -> Settings:
    owner_id = _int("OWNER_ID")
    if owner_id == 0:
        raise RuntimeError("កំណត់ OWNER_ID ក្នុង .env ជាមុនសិន (រក ID ពី @userinfobot)")
    return Settings(
        bot_token=(os.getenv("BOT_TOKEN") or "").strip(),
        owner_id=owner_id,
        admin_ids=_ids("ADMIN_IDS"),
        timezone=(os.getenv("TIMEZONE") or "Asia/Phnom_Penh").strip(),
        use_mock_bot=_bool("USE_MOCK_BOT"),
        database_url=(os.getenv("DATABASE_URL") or "sqlite+aiosqlite:///./data/app.db").strip(),
        fernet_key=(os.getenv("SESSION_FERNET_KEY") or "").strip(),
        ai_backend=(os.getenv("AI_BACKEND") or "groq").strip().lower(),
        groq_api_key=(os.getenv("GROQ_API_KEY") or "").strip(),
        groq_model=(os.getenv("GROQ_MODEL") or "qwen/qwen3.8-27b").strip(),
        groq_base_url=(os.getenv("GROQ_BASE_URL") or "https://api.groq.com/openai/v1").strip(),
        qoder_cli_bin=(os.getenv("QODER_CLI_BIN") or "qoder").strip(),
        qoder_cli_args=(os.getenv("QODER_CLI_ARGS") or "-p {prompt}").strip(),
        qoder_cli_timeout=_int("QODER_CLI_TIMEOUT", 90),
        openai_base_url=(os.getenv("OPENAI_BASE_URL") or "http://127.0.0.1:8000/v1").strip(),
        openai_api_key=(os.getenv("OPENAI_API_KEY") or "").strip(),
        openai_model=(os.getenv("OPENAI_MODEL") or "qwen3-8b-flash").strip(),
        ollama_base_url=(os.getenv("OLLAMA_BASE_URL") or "http://127.0.0.1:11434").strip(),
        ollama_model=(os.getenv("OLLAMA_MODEL") or "qwen3:8b").strip(),
        ai_history_limit=_int("AI_HISTORY_LIMIT", 20),
        ai_timeout=_int("AI_TIMEOUT", 60),
        tg_api_id=_int("TG_API_ID"),
        tg_api_hash=(os.getenv("TG_API_HASH") or "").strip(),
        userbot_cap_hour=_int("USERBOT_CAP_HOUR", 50),
        userbot_cap_day=_int("USERBOT_CAP_DAY", 200),
        userbot_delivery_reserve=_int("USERBOT_DELIVERY_RESERVE", 10),
        working_hours=(os.getenv("WORKING_HOURS") or "08:00-23:00").strip(),
        stock_alert_threshold=_int("STOCK_ALERT_THRESHOLD", 5),
        language=(os.getenv("LANGUAGE") or "km").strip().lower(),
        session_web_url=(os.getenv("SESSION_WEB_URL") or DEFAULT_SESSION_WEB_URL).strip(),
    )


settings = _load()
