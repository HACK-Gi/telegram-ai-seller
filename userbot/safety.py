"""សុវត្ថិភាព userbot — រឿងពីរដែលត្រូវបានបិទទ្វារដោយកូដ មិនមែនដោយការជឿទេ៖

1. **Secret never reaches the log** — session string, OTP, 2FA password។ គន្លឹះ៖
   `str(RPCError)` របស់ Telethon បញ្ចូល repr នៃ request ដែលមាន *អត្ថបទសារ* និង
   *លេខទូរស័ព្ទ* ដូច្នេះ exception ត្រូវ log តាមរយៈ `describe_error()` ប៉ុណ្ណោះ។
2. **AI never reveals a code** — `looks_like_code()` រាំងមុនពេល enqueue (prompt តែមួយ
  មិនគ្រប់គ្រាន់ទេ ព្រោះ model អាចប្រឌិត code ដែលអតិថិជនមានរួច ឬស្រែហា code ដែលគេបញ្ជូល)។
"""
from __future__ import annotations

import logging
import re
import traceback

# Telethon StringSession = urlsafe-base64 នៃ (version, dc_id, ip, port, auth_key 256 bytes)
# → 352 (IPv4) ឬ 368 (IPv6) តួអក្សរ ហើយចាប់ផ្តើមដោយ byte version `b'1'`។
_SESSION_RE = re.compile(r"\b1[A-Za-z0-9_\-]{300,}\b")
_PLACEHOLDER = "[redacted]"

_SECRETS: set[str] = set()


def register_secret(value: object) -> None:
    """ចុះឈ្មោះតម្លៃសម្ងាត់មួយ (session, OTP, password) ដើម្បីបិទក្នុងគ្រប់ log record។"""
    text = str(value or "")
    if len(text) >= 4:
        _SECRETS.add(text)


def clear_secrets() -> None:
    _SECRETS.clear()


def redact(text: str) -> str:
    if not text:
        return text
    for secret in _SECRETS:
        if secret in text:
            text = text.replace(secret, _PLACEHOLDER)
    return _SESSION_RE.sub(_PLACEHOLDER, text)


class SecretRedactor(logging.Filter):
    """ដាក់លើគ្រប់ handler ក្នុង `main.setup_logging()` — មិនមាន message ណាចេញរាវទេ។

    traceback មិនឆ្លងកាត់ `record.getMessage()` ទេ (`log.exception` សរសេរពី
    `record.exc_text` ដាច់ដោយឡែក) ដូច្នេះត្រូវ sanitize វាផង មិនមែនតែ msg ទេ។
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = None
        if record.exc_info:
            record.exc_text = redact("".join(traceback.format_exception(*record.exc_info)).rstrip())
            record.exc_info = None
        if record.stack_info:
            record.stack_info = redact(str(record.stack_info))
        return True


def describe_error(exc: BaseException) -> str:
    """សង្ខេប exception ដោយគ្មាន request repr (អត្ថបទសារ/លេខទូរស័ព្ទ)។"""
    parts = [type(exc).__name__]
    seconds = getattr(exc, "seconds", None)
    if isinstance(seconds, int):
        parts.append(f"seconds={seconds}")
    code = getattr(exc, "code", None)
    if isinstance(code, int):
        parts.append(f"code={code}")
    return " ".join(parts)


_PRICE_RE = re.compile(r"[$€៛]?\s?\d[\d,]*\.\d{2}")
# លេខទូរស័ព្ទខ្មែរ ៩–១១ ខ្ទង់ (word boundary ការពារកុំឱ្យវាច្របាច់ប្រាក់ run វែងជាងនេះ)
_PHONE_RE = re.compile(r"\+?\b0?\d{9,11}\b")
_CANDIDATE_RES = (
    re.compile(r"\b[A-Z0-9]{8,}\b"),                       # KEYXXXXXXXX
    re.compile(r"\b[A-Z0-9]{3,}(?:-[A-Z0-9]{3,}){2,}\b"),  # KEY-AAA-BBB
    re.compile(r"\b\d{12,16}\b"),                          # លេខកាត / ABA account
)


def looks_like_code(text: str, *, known_codes: tuple[str, ...] | list[str] = (), safe_terms: tuple[str, ...] = ()) -> bool:
    """ពិត = អត្ថបទនេះប្រកាស code ពិត ឬរូបរាង code — ត្រូវ *បោះបង់* ចោល (មិន sanitize)។

    មិន sanitize ទេ ព្រោះឆ្លើយដែលមានរន្ធខូចមើលទៅដូចជាប្រព័ន្ធខូច។

    `known_codes` ជា code ពិតដែលនៅសល់ក្នុង stock នៃផលិតផលគណនីនេះ។
    `safe_terms` ការពារឈ្មោះផលិតផល uppercase (ឧ. FREEFIRE) កុំឱ្យត្រូវចាត់ទុកជា code។
    """
    if not text:
        return False
    lowered = text.casefold()
    for code in known_codes:
        if code and code.casefold() in lowered:
            return True
    probe = text.upper()
    for term in safe_terms:
        if term:
            probe = probe.replace(term.upper(), " ")
    probe = _PRICE_RE.sub(" ", probe)
    probe = _PHONE_RE.sub(" ", probe)
    return any(pattern.search(probe) for pattern in _CANDIDATE_RES)
