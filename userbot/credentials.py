"""App credentials (`api_id` + `api_hash`) ក្នុងមួយគណនី — Telegram តម្រូវឱ្យម្ចាស់គណនី
បង្កើត App ផ្ទាល់ខ្លួននៅ my.telegram.org ដូច្នេះពួកវាមិនមែនជា config របស់ process ទេ។

គោលការណ៍៖

* **Encrypt ដោយ Fernet ដូច session** (`userbot.session_store`) — key តែមួយ, គ្មាន plaintext
  ក្នុង DB, គ្មាន plaintext ក្នុង log។ `session_store.encrypt()` ចុះឈ្មោះតម្លៃជា secret
  ដូច្នេះ log ណាក៏រាយតម្លៃនេះមិនចេញដែរ។
* **Fallback ទៅ .env** សម្រាប់គណនីដែល login មុនមុខងារនេះ — បើគ្មាន fallback ការដំឡើង
  ដែលកំពុងរត់នឹងដាច់ session ទាំងអស់ភ្លាមៗពេល deploy។
* **Validation មុនផ្ញើទៅ Telegram** — api_id/api_hash ខុសទ្រង់ទ្រាយគឺជាកំហុសអ្នកប្រើ
  មិនមែនកំហុស network ទេ ដូច្នេះវាត្រូវចាប់នៅ chat មិនមែននៅ Telethon។
"""
from __future__ import annotations

import re
from typing import Any

from userbot import session_store

API_HASH_RE = re.compile(r"^[0-9a-fA-F]{32}$")
API_ID_MIN_DIGITS = 6
API_ID_MAX_DIGITS = 10


def valid_api_id(raw: str) -> int | None:
    """`api_id` ត្រូវជាលេខ ៦–១០ ខ្ទង់។ បរាជ័យ → `None`។"""
    text = (raw or "").strip().replace(" ", "")
    if not text.isdigit() or not (API_ID_MIN_DIGITS <= len(text) <= API_ID_MAX_DIGITS):
        return None
    value = int(text)
    return value if value > 0 else None


def valid_api_hash(raw: str) -> str | None:
    """`api_hash` ត្រូវជា hex ៣២ តួអក្សរ។ បរាជ័យ → `None`។"""
    text = (raw or "").strip()
    return text if API_HASH_RE.match(text) else None


def mask_phone(phone: str) -> str:
    """`+85593251670` → `+855****5670` — សម្រាប់ log និងសារជូនដំណឹងប៉ុណ្ណោះ។"""
    text = (phone or "").strip()
    if len(text) <= 8:
        return "*" * len(text)
    return f"{text[:4]}****{text[-4:]}"


def encrypt_credential(value: str) -> str:
    """api_id/api_hash → Fernet token (បដិសេធតម្លៃទទេ ដូច្នេះគ្មានជួរពាក់កណ្តាល)។"""
    return session_store.encrypt((value or "").strip())


def decrypt_credential(token: str) -> str:
    return session_store.decrypt(token)


def stored_credentials(account: Any) -> tuple[int, str] | None:
    """Credentials ដែលរក្សាទុកក្នុងជួរគណនី (មិនរាប់ .env)។ ខូច/ខ្វះ → `None`។"""
    raw_id = getattr(account, "tg_api_id_encrypted", None)
    raw_hash = getattr(account, "tg_api_hash_encrypted", None)
    if not raw_id or not raw_hash:
        return None
    try:
        api_id = int(decrypt_credential(raw_id))
        api_hash = decrypt_credential(raw_hash)
    except (session_store.SessionCryptoError, ValueError, TypeError):
        return None
    return (api_id, api_hash) if api_hash else None


def env_credentials() -> tuple[int, str] | None:
    from config import settings

    if settings.tg_api_id and settings.tg_api_hash:
        return int(settings.tg_api_id), settings.tg_api_hash
    return None


def resolve(account: Any) -> tuple[int, str] | None:
    """Credentials សម្រាប់ភ្ជាប់គណនី — របស់គណនីជាអាទិភាព បន្ទាប់មក .env។"""
    return stored_credentials(account) or env_credentials()


def is_configured(account: Any) -> bool:
    """សម្រាប់ Panel — បង្ហាញ «Configured» ប៉ុណ្ណោះ មិនដែលតម្លៃពិត។"""
    return resolve(account) is not None
