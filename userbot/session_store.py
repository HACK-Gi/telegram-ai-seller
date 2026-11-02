"""Fernet encryption សម្រាប់ Telethon `StringSession` — ទិន្នន័យសម្ងាត់បំផុតក្នុងប្រព័ន្ធ។

គ្មាន session ណាសរសេរលើ disk ឬចូល log ទេ។ `data/sessions/` មិនត្រូវបង្កើតទៀតឡើយ។
ការផ្ទុក session ត្រូវតែត្រឡប់ជា **StringSession object** ប៉ុណ្ណោះ៖ បើឆ្លងកាត់ `str`
Telethon នឹងបង្កើត `SQLiteSession` file រាវលើ disk ដែលមាន auth key នៅក្នុងនោះ។
"""
from __future__ import annotations

import hashlib
import struct

from cryptography.fernet import Fernet, InvalidToken
from telethon.sessions import StringSession

from config import settings
from userbot import safety

KEY_HELP = (
    "សូមកំណត់ SESSION_FERNET_KEY ក្នុង .env ជាមុន — បង្កើតដោយ៖\n"
    "  python scripts/generate_keys.py --write"
)


class SessionCryptoError(RuntimeError):
    """key ខ្វះ/ខុសប្រវែង ឬ ciphertext អានមិនបាន (key ប្តូរ ឬ data ខូច)។"""


def key_status() -> tuple[bool, str]:
    raw = (settings.fernet_key or "").strip()
    if not raw:
        return False, (
            "មិនទាន់កំណត់ SESSION_FERNET_KEY ក្នុង .env — "
            "បង្កើតដោយ៖ python scripts/generate_keys.py --write រួច restart bot"
        )
    try:
        Fernet(raw.encode())
    except (ValueError, TypeError):
        return False, (
            "SESSION_FERNET_KEY ខុសទ្រង់ទ្រាយ (ត្រូវជា Fernet key 44 តួអក្សរ) — "
            "បង្កើតថ្មីដោយ៖ python scripts/generate_keys.py --write --force"
        )
    return True, "រួចរាល់"


def _fernet() -> Fernet:
    raw = (settings.fernet_key or "").strip()
    if not raw:
        raise SessionCryptoError(KEY_HELP)
    try:
        return Fernet(raw.encode())
    except (ValueError, TypeError) as exc:
        raise SessionCryptoError(f"{type(exc).__name__} — {KEY_HELP}") from None


def encrypt(plaintext: str) -> str:
    if not plaintext:
        raise SessionCryptoError("session ទទេ — ចុះឈ្មោះឡើងវិញតាម /addaccount ក្នុង Admin Bot")
    safety.register_secret(plaintext)
    token = _fernet().encrypt(plaintext.encode()).decode()
    safety.register_secret(token)
    return token


def decrypt(token: str) -> str:
    if not token:
        raise SessionCryptoError("គណនីនេះមិនមាន session ទេ")
    try:
        plaintext = _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        # កុំដាក់ token fragment ណាក្នុងសារខុស ព្រោះវាអាចជា session រស់របស់គណនី
        raise SessionCryptoError("session អានមិនបាន (key ប្តូរ ឬទិន្នន័យខូច)") from None
    safety.register_secret(plaintext)
    return plaintext


def load_session(token: str) -> StringSession:
    plaintext = decrypt(token)
    try:
        return StringSession(plaintext)
    except (ValueError, struct.error) as exc:
        # ValueError = «Not a valid string»/base64 ខូច, struct.error = ប្រវែង byte ខុស
        # (session ត្រូវកាត់ ឬលាយគណនីផ្សេង) — ទាំងពីរគឺ «session ខូច» មិនមែនកំហុសកូដទេ
        raise SessionCryptoError(f"session មិនត្រឹមត្រូវ: {type(exc).__name__}") from None


def store_session(client) -> str:
    """`client.session.save()` → Fernet token។ StringSession().save() ត្រឡប់ `''`
    ពេលគ្មាន auth key ដូច្នេះយើងបដិសេធ ជំនួសឱ្យការរក្សាទុក «ចុះឈ្មោះ» ដែលពិតជាមិនបាន។"""
    raw = client.session.save()
    if isinstance(raw, bytes):
        raw = raw.decode()
    if not raw:
        raise SessionCryptoError("គ្មាន auth key ក្នុង session — ត្រូវចុះឈ្មោះឡើងវិញ")
    return encrypt(raw)


def fingerprint(plaintext: str) -> str:
    """តែ 12 hex ប៉ុណ្ណោះ — បោះពុម្ពក្នុង terminal/log ដោយសុវត្ថិភាព។"""
    return hashlib.sha256((plaintext or "").encode()).hexdigest()[:12]
