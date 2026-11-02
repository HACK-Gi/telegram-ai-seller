"""🌐 Bot Auto Sell — Make Session — បង្កើត Telegram Session String តាម web (Telethon)។

ហេតុផល៖ ភ្ញៀវភាគច្រើនមិនរត់ Python លើកុំព្យូទ័រខ្លួន ដូច្នេះពួកគេត្រូវការទំព័រមួយដែល
បង្កើត StringSession ជូន រួចចម្លងវាទៅផ្ញើ Bot តាម `/addsession`។

សុវត្ថិភាព (សំខាន់ជាងអ្វីទាំងអស់)៖

* **គ្មាន DB, គ្មាន file, គ្មាន log** នៃ api_id/api_hash/លេខទូរស័ព្ទ/OTP/2FA/session string
  — ទាំងអស់រស់តែក្នុង memory របស់ request នោះ ហើយត្រូវលុបភ្លាមបន្ទាប់ពីប្រើ។
* ចន្លោះ `/send_otp` → `/verify_otp` រក្សាទុកដោយ **token Fernet ដែលផ្ទុក data ខ្លួនឯង**
  (stateless) — មិនមែន dict ក្នុង process ទេ ព្រោះ serverless isolate មួយទំនេរអាច
  ខុសគ្នារវាង request ទី១ និងទី២។ token មាន TTL ហើយ ប្រើបានតែម្តង (jti blocklist)។
* លេខទូរស័ព្ទមិនត្រូវរក្សាទុកសូម្បីតែសម្រាប់ rate limit — យើងរក្សាតែ hash របស់វា។
* ប្រើ HTTPS (Vercel ផ្តល់) + CORS បិទខ្វែង-origin លើកម្រិប (domain ក្នុង env)។
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import sys
import time
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from flask import Flask, jsonify, render_template, request
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from telethon import TelegramClient
from telethon.sessions import StringSession

BASE_DIR = Path(__file__).resolve().parent
API_HASH_RE = re.compile(r"^[0-9a-fA-F]{32}$")

# .env ជិតខាង ត្រូវបានប្រើតែពេលរត់លើកុំព្យូទ័ររបស់ម្ចាស់ — Vercel ប្រើ Env Variables។
try:
    from dotenv import load_dotenv

    load_dotenv(BASE_DIR / ".env")
except ImportError:  # dotenv មិនជាការចាំបាច់នៅ production
    pass

# TTL របស់ token «រង់ចាំ OTP» — យូរគ្រប់គ្រាន់សម្រាប់អាន SMS ម្តង ខ្លីគ្រប់គ្រាន់សម្រាប់កុំឱ្យ
# ទិន្នន័យសម្ងាត់នៅសល់យូរ។ កែតាម env SESSION_WEB_TTL (វិនាទី)។
PENDING_TTL = int(os.getenv("SESSION_WEB_TTL") or 600)
MAX_CODE_TRIES = 5
# budget របស់ Telegram 1 ដង រួម + wait_for។ 45s ជាង `maxDuration` របស់ Vercel (៦០s) បន្តិច
# ហើយតូចគ្រប់គ្រាន់សម្រាប់ IP datacenter (AWS) ដែល Telegram ឆ្លើយយឺត — បើយូរជាងនេះ
# platform កាត់ request មុន ទើបភ្ញៀវឃើញតែ 504 ទទេ។
LOGIN_TIMEOUT = float(os.getenv("SESSION_WEB_TIMEOUT") or 30)
DEFAULT_REGION_CC = "+855"  # ភ្ញៀវរបស់ប្រព័ន្ធនេះភាគច្រើនជាខ្មែរ


APP_VERSION = "2026.11.02a"


def _secret_key() -> tuple[bytes, str]:
    """Fernet key សម្រាប់ pending token — ខ្វះ/ខុស → បង្កើតបណ្តោះអាសន្ន (តែមួយ process)។

    ត្រឡប់ (key, source); source ទទេ = គ្មាន env ដែល production serverless នេះសម្លាប់ flow
    (token ពី `/send_otp` isolate មួយ read មិនបានពី isolate មួយទៀត) ទើប routes ប្រាប់ម្ចាស់។
    """
    raw = (os.getenv("SESSION_WEB_SECRET") or "").strip()
    if raw:
        try:
            Fernet(raw.encode())  # ផ្ទៀង key មុន ទើបបរាជ័យច្បាស់នៅទីនេះ មិនមែនពេលភ្ញៀវចុច «ផ្ញើ OTP»
            return raw.encode(), "env"
        except (ValueError, TypeError):
            # `log` មិនទាន់មានពេល import → print
            print("⚠️  session_web: SESSION_WEB_SECRET មិនមែន Fernet key ត្រឹមត្រូវ — បង្កើតបណ្តោះអាសន្ន",
                  flush=True)
    return Fernet.generate_key(), ""


SECRET, SECRET_SOURCE = _secret_key()
FERNET = Fernet(SECRET)

# pending token ដែលប្រើហើយ — best effort (isolate ចាស់) ប៉ុន្តែ TTL កំណត់រយៈពេលបាន
_USED: set[str] = set()
# rate limit តាមលេខទូរស័ព្ទ (រក្សាតែ hash) — ការពារការសុំ OTP ទ្រង់ទ្រាយ large
_PHONE_HITS: dict[str, list[float]] = {}
PHONE_LIMIT = 3
PHONE_WINDOW = 600.0

app = Flask(__name__)
# storage_uri="memory://" = ជ្រើសរើសដោយដឹង full: Vercel មិនមាន Redis/consistent store
# ទេ ដូច្នេះ limit គឺ per-isolate។ ការពារបន្ថែមកម្រិតតាមលេខទូរស័ព្ទ (_PHONE_HITS)។
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["30 per hour"],
    app=app,
    storage_uri="memory://",
)


@app.after_request
def _no_store(response):
    response.headers["Cache-Control"] = "no-store"
    return response


def _origins() -> list[str]:
    """CORS អនុញ្ញាតតែ domain របស់ app ខ្លួន (same-origin មិនត្រូវការ CORS ទេ)។"""
    base = (os.getenv("SESSION_WEB_URL") or "").strip().rstrip("/")
    return [base] if base.startswith("https://") else []


_origins() and CORS(app, resources={r("/verify_otp"): {"origins": _origins()}, r("/send_otp"): {"origins": _origins()}})

logging.getLogger("telethon").setLevel(logging.ERROR)
logging.getLogger("werkzeug").setLevel(logging.WARNING)
log = logging.getLogger("session_web")
# គ្មាន handler → root មិន print ទេ ហើយ Vercel runtime logs ឃើញតែ werkzeug access line
# ទើប debug ពី production ធ្វើមិនបាន។ StreamHandler(stderr) គឺជាអ្វីដែល Vercel ចាប់។
if not log.handlers:
    _handler = logging.StreamHandler(sys.stderr)
    _handler.setFormatter(logging.Formatter("[session_web] %(levelname)s: %(message)s"))
    log.addHandler(_handler)
log.setLevel(logging.INFO)
log.propagate = False

try:  # ឈ្មោះ class ត្រូវ version ទើប ប្រើ isinstance បាន (fallback ទៅឈ្មោះ)
    from telethon.errors import SessionPasswordNeededError as _PASSWORD_NEEDED
except ImportError:  # pragma: no cover
    _PASSWORD_NEEDED = None


# ---------------- helpers ----------------
def normalize_phone(raw: str) -> str | None:
    """`093251670` / `093 251 670` / `+85593251670` → E.164 — គ្មានបន្ថែម dependency។"""
    text = re.sub(r"[^\d+]", "", raw or "")
    if text.startswith("00"):
        text = "+" + text[2:]
    if text.startswith("+"):
        digits = text[1:]
    elif text.startswith("0"):
        digits = DEFAULT_REGION_CC[1:] + text[1:]
    elif len(text) >= 8:
        digits = DEFAULT_REGION_CC[1:] + text
    else:
        return None
    if not (9 <= len(digits) <= 15):
        return None
    return f"+{digits}"


def _issue(payload: dict) -> str:
    return FERNET.encrypt(json.dumps(payload, separators=(",", ":")).encode()).decode()


def _read(token: str) -> dict | None:
    """TTL + single-use — ខុស/ផុតកំណត់ → None (មិនបែក exception ដល់ភ្ញៀវទេ)។"""
    try:
        payload = json.loads(FERNET.decrypt(token.encode(), ttl=PENDING_TTL))
    except (InvalidToken, ValueError, TypeError):
        return None
    jti = payload.get("jti")
    if not jti or jti in _USED:
        return None
    return payload


def _consume(token: str) -> None:
    payload = _read(token)
    if payload:
        _USED.add(payload["jti"])
        if len(_USED) > 4096:
            _USED.clear()


def _reissue(payload: dict) -> str:
    """token ថ្មីសម្រាប់ «OTP ខុស → សាកម្តងទៀត» ឬ «ត្រូវការ 2FA» — ត្រូវ jti ថ្មី  otherwise
    token នោះត្រូវ blocklist បដិសេធ (jti ចាស់ត្រូវបាន mark ប្រើហើយ)។"""
    payload = dict(payload)
    payload["jti"] = os.urandom(9).hex()
    return _issue(payload)


def _phone_allowed(phone: str) -> bool:
    key = hashlib.sha256(phone.encode()).hexdigest()[:16]
    now = time.time()
    hits = [t for t in _PHONE_HITS.get(key, []) if now - t < PHONE_WINDOW]
    if len(hits) >= PHONE_LIMIT:
        return False
    hits.append(now)
    _PHONE_HITS[key] = hits
    return True


def _client_creds(data: dict) -> tuple[int, str]:
    return int(data["api_id"]), data["api_hash"]


async def _login(phone: str, api_id: int, api_hash: str, code: str, password: str | None,
                 phone_code_hash: str) -> tuple[str, str]:
    """→ ("ok", session_string) ឬ ("2fa", "") ឬ ("failed", "") ឬ raise។ client ត្រូវ disconnect ជានិច្ច។

    `connection_retries`/`request_retries` = ១ ដោយចេតនា: serverless (Vercel) មាន
    maxDuration តឹង ហើយ Telethon លំនាំដើម retry ៥ ដង × ១s + auto_reconnect នឹង
    គណនារយៈពេលជា ២០–៣០s ពេលបណ្តាញយឺត ទើប platform កាត់ request ជា 504 ដោយ
    គ្មានសារអ្វីឡើយ — បរាជ័យលឿន ប្រាប់ឱ្យដឹងហេតុ ល្អជាង suspend រហូតដាច់។
    """
    client = TelegramClient(
        StringSession(), api_id, api_hash,
        connection_retries=1, request_retries=1, retry_delay=1, auto_reconnect=False,
    )
    try:
        await asyncio.wait_for(client.connect(), timeout=LOGIN_TIMEOUT)
        try:
            if password:
                await client.sign_in(password=password)
            else:
                await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
        except Exception as exc:  # noqa: BLE001
            if _is_password_needed(exc):
                return "2fa", ""
            raise
        saved = client.session.save()
        return ("ok", saved) if saved else ("failed", "")
    finally:
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            pass


async def _request_code(phone: str, api_id: int, api_hash: str) -> str:
    client = TelegramClient(
        StringSession(), api_id, api_hash,
        connection_retries=1, request_retries=1, retry_delay=1, auto_reconnect=False,
    )
    try:
        await asyncio.wait_for(client.connect(), timeout=LOGIN_TIMEOUT)
        sent = await client.send_code_request(phone)
        return sent.phone_code_hash or ""
    finally:
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            pass


def _error_name(exc: BaseException) -> str:
    return type(exc).__name__


def _is_password_needed(exc: BaseException) -> bool:
    """Telethon ប្តូរឈ្មោះ exception តាម version — ពិនិត្យទាំង class និង name។

    ចំណាំ `PasswordHashInvalidError` **មិនមែន** «ត្រូវការ 2FA» ទេ វាជា «ពាក្យសម្ងាត់ខុស»
    បើរាប់វាជា 2FA ផង flow នឹងវិលត្រឡប់ទៅប្រអប់ 2FA ជារៀងរហូត។
    """
    if _PASSWORD_NEEDED is not None and isinstance(exc, _PASSWORD_NEEDED):
        return True
    return _error_name(exc) == "SessionPasswordNeededError"


_USER_HINTS = {
    "ApiIdInvalidError": "API ID ឬ API Hash មិនត្រឹមត្រូវ — សូមចម្លងពី my.telegram.org/apps ឡើងវិញ",
    "ApiIdInvalid": "API ID ឬ API Hash មិនត្រឹមត្រូវ — សូមចម្លងពី my.telegram.org/apps ឡើងវិញ",
    "SessionRevokedError": "Session ត្រូវបានបោះបង់ — សូមសុំ OTP ថ្មី",
    "PhoneNumberInvalidError": "លេខទូរស័ព្ទខុសទ្រង់ទ្រាយ — ត្រូវជា E.164 (ឧ. +85593251670)",
    "PhoneNumberBannedError": "លេខនេះត្រូវ Telegram ហាមឃាត់ — សាកល្បងគណនីផ្សេង",
    "PhoneNumberAppForbiddenError": "លេខនេះមិនអាចចូលតាម App បែបនេះទេ",
    "SignInAlreadyUsedError": "កូដនេះត្រូវបានប្រើហើយ — សូមសុំ OTP ថ្មី",
    "SessionExpiredError": "សន្ទស្សន៍ OTP ផុតកំណត់ — សូមសុំ OTP ថ្មី",
    "PhoneCodeInvalidError": "កូដ OTP មិនត្រឹមត្រូវ — សូមវាយឡើងវិញ",
    "PassportDataInvalidError": "ពាក្យសម្ងាត់ 2FA មិនត្រឹមត្រូវ",
    "SrpPasswordChangedError": "ពាក្យសម្ងាត់ 2FA មិនត្រឹមត្រូវ",
    "AuthKeyUnregisteredError": "គណនីនេះត្រូវបាន log out — សូមចាប់ផ្តើមឡើងវិញ",
    "FloodWaitError": "Telegram សុំឱ្យរង់ចាំបន្តិច មុនសុំ OTP ថ្មី",
    # កំហុសទូទៅពេល server រត់នៅ IP datacenter (Vercel = AWS) — ភ្ញៀវត្រូវធ្វើតាម App ខ្លួនឯង
    "SignInUnapprovedError": "Telegram សុំឱ្យអនុម័តក្នុង App របស់អ្នក — បើក Telegram រួចចុចបន្ត សាកល្បងឡើងវិញ",
    "PhoneNumberOc2RequestedError": "Telegram ផ្ញើ link ទៅ App របស់អ្នក (មិនមែន SMS) — ពិនិត្យ Telegram រួចសុំ OTP ថ្មី",
    "AuthRestartError": "Telegram សុំចាប់ផ្តើម OTP ឡើងវិញ — សូមសុំ OTP ថ្មី",
    "SessionWaitTooLongError": "រង់ចាំយូរពេក — សូមសុំ OTP ថ្មី",
    "UnauthorizedAccountError": "Telegram មិនអនុញ្ញាតគណនីនេះ — សូមប្រើ scripts/get_session.py លើកុំព្យូទ័ររបស់អ្នក",
}


def _friendly(exc: BaseException) -> str:
    name = _error_name(exc)
    if name in _USER_HINTS:
        return _USER_HINTS[name]
    for suffix in ("Error", "Exception"):
        if name.endswith(suffix) and name[: -len(suffix)] in _USER_HINTS:
            return _USER_HINTS[name[: -len(suffix)]]
    if "Flood" in name:
        return "Telegram កំណត់ចំនួនដង (FloodWait) — សូមរង់ចាំប៉ុន្មាននាទី រួចសាកល្បងឡើងវិញ"
    if isinstance(exc, (OSError, asyncio.TimeoutError)):
        return "មិនអាចទាក់ទង Telegram បាន — ពិនិត្យអ៊ីនធឺណិត រួចសាកល្បងឡើងវិញ"
    return "ធ្វើការមិនបានសម្រេច — សូមសាកល្បងឡើងវិញ ឬប្រើ `scripts/get_session.py` ក្នុងកុំព្យូទ័ររបស់អ្នក"


# ---------------- routes ----------------
@app.get("/")
@limiter.exempt
def index():
    return render_template("index.html", ttl_minutes=max(1, int(PENDING_TTL // 60)))


@app.get("/health")
@limiter.exempt
def health():
    return jsonify({
        "ok": True,
        "secret_configured": bool(SECRET_SOURCE),
        "ttl": PENDING_TTL,
        "timeout": LOGIN_TIMEOUT,
        "version": APP_VERSION,
    })


def _require_secret():
    """SESSION_WEB_SECRET ខ្វះ → token មាន key មួយ isolate ប៉ុណ្ណោះ ទើប verify បរាជ័យ
    «ផុតកំណត់» ទោះ OTP ត្រូវ (serverless isolate ខុសគ្នា) ។ ប្រាប់ម្ចាស់ច្បាស់ជាងឱ្យភ្ញៀវ
    ទន្ទងមិនដឹង។ ត្រឡប់ None បើ OK ឬ error response បើខ្វះ។"""
    if SECRET_SOURCE:
        return None
    return jsonify({
        "status": "error",
        "detail": "secret_missing",
        "message": "Server មិនទាន់មាន SESSION_WEB_SECRET — ម្ចាស់គេហទំព័រត្រូវបន្ថែម Environment "
                   "Variable នេះ រួច Redeploy (បើខ្វះ token រវាង OTP ពេល verify នឹងបរាជ័យ)",
    }), 503


@app.post("/send_otp")
@limiter.limit("5 per hour")
def send_otp():
    data = request.get_json(silent=True) or {}
    api_id_raw = str(data.get("api_id") or "").strip()
    api_hash = str(data.get("api_hash") or "").strip()
    phone = normalize_phone(str(data.get("phone") or ""))
    if not api_id_raw.isdigit() or int(api_id_raw) <= 0:
        return jsonify({"status": "error", "detail": "api_id_invalid",
                        "message": "API ID ត្រូវតែជាលេខ (យកពី my.telegram.org/apps)"}), 400
    if not API_HASH_RE.match(api_hash):
        return jsonify({"status": "error", "detail": "api_hash_invalid",
                        "message": "API Hash ត្រូវជា hex ៣២ តួអក្សរ"}), 400
    if phone is None:
        return jsonify({"status": "error", "detail": "phone_invalid",
                        "message": "លេខទូរស័ព្ទខុសទ្រង់ទ្រាយ — វាយ 093251670 ឬ +85593251670"}), 400
    blocked = _require_secret()
    if blocked is not None:
        return blocked
    if not _phone_allowed(phone):
        return jsonify({"status": "error", "detail": "phone_rate_limited",
                        "message": "សុំ OTP ច្រើនដងពេក — សូមរង់ចាំ ១០ នាទី"}), 429

    started = time.monotonic()
    try:
        phone_code_hash = asyncio.run(asyncio.wait_for(
            _request_code(phone, int(api_id_raw), api_hash), timeout=LOGIN_TIMEOUT + 5))
    except Exception as exc:  # noqa: BLE001
        name = _error_name(exc)
        # តួអក្សរ/ឈ្មោះ class តែប៉ុណ្ណោះ — គ្មាន api_hash គ្មានលេខទូរស័ព្ទគ្មាន session
        log.info("send_otp failed: %s (%dms)", name, int((time.monotonic() - started) * 1000))
        return jsonify({"status": "error", "detail": name, "message": _friendly(exc)}), 502
    log.info("send_otp ok: hash_len=%d (%dms)", len(phone_code_hash),
             int((time.monotonic() - started) * 1000))
    if not phone_code_hash:
        return jsonify({"status": "error", "detail": "no_phone_code_hash",
                        "message": "Telegram មិនផ្តល់សន្ទស្សន៍ OTP — សូមសាកល្បងឡើងវិញ"}), 502

    token = _issue(
        {
            "jti": os.urandom(9).hex(),
            "api_id": int(api_id_raw),
            "api_hash": api_hash,
            "phone": phone,
            "hash": phone_code_hash,
            "tries": 0,
            "stage": "code",
        }
    )
    return jsonify({"status": "code_sent", "request_id": token})


@app.post("/verify_otp")
@limiter.limit("10 per hour")
def verify_otp():
    body = request.get_json(silent=True) or {}
    token = str(body.get("request_id") or "")
    code = str(body.get("otp") or body.get("code") or "").strip()
    password = str(body.get("password") or "")
    # វាស់វែងទាំងអស់ គ្មានខ្លឹមសារ (OTP/ពាក្យសម្ងាត់/token) — សម្រាប់ debug ពី Vercel log បាន
    log.info("verify_otp: token_len=%d otp_len=%d has_password=%s",
             len(token), len(code), bool(password))
    payload = _read(token)
    if payload is None:
        return jsonify({"status": "error", "detail": "token_expired", "restart": True,
                        "message": "សំណើនេះផុតកំណត់ ឬប្រើហើយ — សូមសុំ OTP ថ្មី"}), 400

    api_id, api_hash = _client_creds(payload)
    started = time.monotonic()
    try:
        # budget សរុប មិនមែនតែ `connect` — `sign_in` អាចអត់ឆ្លើយ ទើប Vercel កាត់ជា 504 ដោយ
        # គ្មានសារ ហើយភ្ញៀវឃើញតែ «Error Code»។ wait_for ធានាឱ្យមានចម្លើយក្នុង ~LOGIN_TIMEOUT
        stage, session_string = asyncio.run(asyncio.wait_for(
            _login(payload["phone"], api_id, api_hash, code, password or None, payload["hash"]),
            timeout=LOGIN_TIMEOUT + 5,
        ))
    except Exception as exc:  # noqa: BLE001
        name = _error_name(exc)
        log.info("verify failed: %s (%dms)", name, int((time.monotonic() - started) * 1000))
        if name in ("PhoneCodeInvalidError", "SessionExpiredError", "SignInCodeChangedError"):
            _consume(token)  # កូដខុស ១ ដង → លុកត្រឹម token ចាស់ចេញពីការប្រើឡើងវិញ
            tries = int(payload.get("tries") or 0) + 1
            if tries >= MAX_CODE_TRIES or name != "PhoneCodeInvalidError":
                return jsonify({"status": "error", "detail": name,
                                "message": _friendly(exc), "restart": True}), 401
            payload["tries"] = tries
            return jsonify(
                {"status": "error", "detail": name, "message": _friendly(exc),
                 "request_id": _reissue(payload)}
            ), 401
        return jsonify({"status": "error", "detail": name,
                        "message": _friendly(exc), "restart": True}), 502

    if stage == "2fa":
        _consume(token)
        payload["stage"] = "password"
        log.info("verify → 2fa_required (%dms)", int((time.monotonic() - started) * 1000))
        return jsonify({"status": "2fa_required", "request_id": _reissue(payload)})

    _consume(token)
    log.info("verify done: stage=%s session_len=%d (%dms)", stage, len(session_string or ""),
             int((time.monotonic() - started) * 1000))  # ប្រវែងតែប៉ុណ្ណោះ — គ្មានខ្លឹមសារ session
    if stage != "ok" or not session_string:
        return jsonify(
            {"status": "error", "detail": f"stage_{stage}",
             "message": "ចូលបាន ប៉ុន្តែ Telegram មិនផ្តល់ session — សូមសុំ OTP ថ្មី"}
        ), 502
    return jsonify({"status": "ok", "session_string": session_string})


@app.errorhandler(429)
def rate_limited(_error):
    return jsonify({"status": "error", "message": "រង់ចាំបន្តិចមុនសាកល្បងឡើងវិញ (កំណត់ចំនួនដង)"}), 429


@app.errorhandler(500)
def server_error(error):
    name = type(error).__name__
    log.info("internal error: %s", name)
    return jsonify({"status": "error", "detail": name,
                    "message": f"កំហុសពី server ({name}) — សូមសាកល្បងឡើងវិញ"}), 500


if __name__ == "__main__":
    host = os.getenv("SESSION_WEB_HOST") or "127.0.0.1"
    port = int(os.getenv("SESSION_WEB_PORT") or 5050)
    print(f"🔐 Make Session web រត់នៅ http://{host}:{port}  (Ctrl+C ដើម្បីបិទ)")
    app.run(host=host, port=port, debug=False)
