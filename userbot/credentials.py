"""App credentials (`api_id` + `api_hash`) — អានពី `.env` តែមួយគត់។

ហេតុផលសុវត្ថិភាព៖ `api_hash` ជា secret របស់ App មួយ ហើយ chat របស់ Admin Bot មិនមែន
កន្លែងសុវត្ថិភាពទេ (aiogram រក្សា update, log, backup) — ដូច្នេះអ្នកប្រើមិនវាយវាតាម Bot ទេ
គឺដាក់ក្នុង `.env` ដោយខ្លួនឯង។

គោលការណ៍បច្ចេកទេស៖

* **`api_id` ត្រូវជា `int`** មុនបញ្ជូនទៅ `TelegramClient` — Telethon ដាក់វាក្នុង
  `initConnection` ដូច្នេះតម្លៃខុសប្រភេទនឹងបែកជា `TypeError` កណ្តាលការ login ហើយ
  អ្នកប្រើឃើញតែ «កំហុសពី Telegram» ដែលអានមិនយល់។
* **គ្មានតម្លៃពិតចូល log ឬ Panel** — អនុញ្ញាតតែ `mask_phone()` និងសារ «`.env` ខ្វះ»។
"""
from __future__ import annotations

import re

API_HASH_RE = re.compile(r"^[0-9a-fA-F]{32}$")


def mask_phone(phone: str) -> str:
    """`+85593251670` → `+855****1670` — សម្រាប់ log និងសារជូនដំណឹងប៉ុណ្ណោះ។

    ប្រតិបត្តិការពិតនៅ `userbot.safety.mask_phone` (canonical) — នេះជា alias ចាស់។
    """
    from userbot import safety

    return safety.mask_phone(phone)


def env_credentials() -> tuple[int, str] | None:
    """`api_id`/`api_hash` ពី .env — ខ្វះ ឬខុសទ្រង់ទ្រាយ → `None` (កុំបញ្ជូនទៅ Telethon)។"""
    from config import settings

    api_id = int(settings.tg_api_id or 0)
    api_hash = (settings.tg_api_hash or "").strip()
    if api_id <= 0 or not API_HASH_RE.match(api_hash):
        return None
    return api_id, api_hash


def missing_credentials_message() -> str:
    """សារខ្មែរប្រាប់ថាត្រូវកែអ្វីក្នុង `.env` — គ្មានតម្លៃពិតណាមួយឡើយ។ រួចរាល់ → `""`។"""
    from config import settings

    problems: list[str] = []
    if not int(settings.tg_api_id or 0):
        problems.append("`TG_API_ID` — ទទេ ឬមិនមែនលេខ")
    if not API_HASH_RE.match((settings.tg_api_hash or "").strip()):
        problems.append("`TG_API_HASH` — ទទេ ឬមិនមែន hex ៣២ តួអក្សរ")
    if not problems:
        return ""
    return (
        "🚫 មិនអាចចាប់ផ្តើម login បានទេ — `.env` ខ្វះ/ខុស៖\n"
        + "\n".join(f"   • {line}" for line in problems)
        + "\n\nយកតម្លៃពី <b>my.telegram.org → API development tools</b> រួចដាក់ក្នុង"
        " <code>.env</code> ហើយ restart bot។ កុំវាយ api_hash ក្នុង chat នេះទេ។"
    )


def resolve() -> tuple[int, str] | None:
    """Credentials សម្រាប់ភ្ជាប់គណនីណាក៏ដោយ — គឺ `.env` តែមួយ។"""
    return env_credentials()


def is_configured() -> bool:
    """សម្រាប់ Panel — បង្ហាញតែ «រួចរាល់/មិនទាន់» មិនមែនតម្លៃពិត។"""
    return env_credentials() is not None
