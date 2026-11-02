"""🧪 តេស្ត «គ្មានសម្ងាត់ក្នុង log» — ចាប់ log ពិត (handler + SecretRedactor ដូច production)។

អ្វីដែលត្រូវបិទជានិច្ច៖ លេខទូរស័ព្ទពេញលេញ, Session String, OTP/2FA, API Hash និង
ខ្លឹមសារ Prompt (វាអាចផ្ទុកសារអតិថិជន ឬ session ដែលគេបិទបញ្ចូល)។ តេស្តនេះមិនអាន
source រក pattern ទេ — វា *រត់* path ពិត រួចអាន log ដែលចេញមែន (Capture handler +
ឯកសារ app.log) ហើយប្រៀបធៀបនឹង អត្ថបទរាវរបស់ record ដើម ដើម្បីធានាថាតេស្តមិនដូចទទេ។

ប្រើ៖ python scripts/test_privacy.py
"""
from __future__ import annotations

import ast
import asyncio
import logging
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DB = ROOT / "data" / "test_privacy.db"
LOG_DIR = ROOT / "data" / "privacy_logs"
for suffix in ("", "-wal", "-shm"):
    path = Path(str(DB) + suffix)
    if path.exists():
        path.unlink()
LOG_DIR.mkdir(parents=True, exist_ok=True)
for name in ("app.log", "app.log.1"):
    path = LOG_DIR / name
    if path.exists():
        path.unlink()

os.environ["USE_MOCK_BOT"] = "1"
os.environ["BOT_TOKEN"] = ""
os.environ["AI_BACKEND"] = "mock"
os.environ["LOG_LEVEL"] = "debug"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{DB}"
os.environ["TG_API_ID"] = "12345"
os.environ["TG_API_HASH"] = "0123456789abcdef0123456789abcdef"
from cryptography.fernet import Fernet  # noqa: E402

os.environ["SESSION_FERNET_KEY"] = Fernet.generate_key().decode()

import main  # noqa: E402
from admin_bot import keyboards, render  # noqa: E402
from admin_bot.handlers import accounts as accounts_handlers  # noqa: E402
from ai_engine import AIAllFailed  # noqa: E402
from database import crud, db_session, init_db  # noqa: E402
from database.models import AccountStatus  # noqa: E402
from userbot import manager as manager_module  # noqa: E402
from userbot import safety, session_store  # noqa: E402
from userbot.seller import Seller  # noqa: E402

PHONE = "+85593251670"
PHONE_LOCAL = "093251670"
SESSION = "1" + "aB3dE" * 70  # 351 តួអក្សរ urlsafe-base64 ដូច StringSession ពិត
OTP = "94813"
TWOFA = "SuperSecret2FAPass"
API_HASH = "0123456789abcdef0123456789abcdef"
SENTINEL = "PROMPT-SENTINEL-7788"
SECRETS = (PHONE, PHONE_LOCAL, SESSION, OTP, TWOFA, API_HASH, SENTINEL)

_checks: list[tuple[str, bool]] = []


def check(label: str, condition: bool) -> None:
    _checks.append((label, bool(condition)))
    print(("  ✅ " if condition else "  ❌ ") + label)


class Capture(logging.Handler):
    """ចាប់រាល់ record ដែល handler production ទទួល (filter តែមួយ ដូចគ្នា)។"""

    def __init__(self) -> None:
        super().__init__()
        self.formatter = logging.Formatter("%(levelname)-7s | %(name)s | %(message)s")
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.lines.append(self.format(record))
        except Exception:  # noqa: BLE001
            self.handleError(record)


def leaked(text: str) -> list[str]:
    return [secret for secret in SECRETS if secret in text]


def stripped(lines: list[str]) -> list[str]:
    return leaked("\n".join(lines))


async def main_flow() -> int:
    await init_db()

    print("— ១) ឯកតា safety: mask / placeholder / redact —")
    safety.register_secret(PHONE)
    safety.register_secret(PHONE_LOCAL)
    safety.register_secret(SESSION)
    safety.register_secret(OTP)
    safety.register_secret(TWOFA)
    safety.register_secret(API_HASH)
    check("mask_phone បិទកណ្តាល", safety.mask_phone(PHONE) == "+855****1670")
    check("mask_phone មិនត្រឡប់លេខពេញ", PHONE not in safety.mask_phone(PHONE))
    check("placeholder វែង → បិទកណ្តាល", safety.mask_phone("tg:900321") == "tg:****0321")
    check("placeholder ខ្លី → តារាងទាំងអស់", safety.mask_phone("tg:9003") == "*" * 7)
    check("លេខខ្លី → តារាងទាំងអស់", safety.mask_phone("01234") == "*****")
    check("account_phone_key ប្រើលេខពិត បើមាន", safety.account_phone_key(PHONE, 9001) == PHONE)
    check("account_phone_key គ្មានលេខ → tg:<id>", safety.account_phone_key(None, 9003) == "tg:9003")
    check("redact លុប Session String រាវ", leaked(safety.redact(f"login {SESSION} ok")) == [])
    check("redact លុប OTP/password ដែលចុះឈ្មោះ", OTP not in safety.redact(f"កូដ {OTP}"))
    check("describe_error មានតែ type", safety.describe_error(ValueError("x")) == "ValueError")

    print("— ២) SecretRedactor លើ log path ពិត (exception + args + stack) —")
    main.LOG_DIR = LOG_DIR
    main.setup_logging()
    capture = Capture()
    capture.addFilter(safety.SecretRedactor())
    root = logging.getLogger()
    root.addHandler(capture)

    try:
        raise RuntimeError(f"RPCError: phone={PHONE} session={SESSION} otp={OTP} hash={API_HASH}")
    except RuntimeError as exc:
        naked = f"{exc}"
        logging.getLogger("userbot.chat_login").exception("login បរាជ័យ %s", naked)
    check("តេស្តមិនដូចទទេ — សារដើមមានសម្ងាត់", len(leaked(naked)) == 4)
    check("log ចាប់បានមិនមានសម្ងាត់", stripped(capture.lines) == [])
    check("log មាន [redacted] ជំនួស", "[redacted]" in "\n".join(capture.lines))

    capture.lines.clear()
    logging.getLogger("userbot.outbox").warning("%s %s %s", PHONE, SESSION, OTP)
    check("args %s ត្រូវបិទដែរ", stripped(capture.lines) == [])

    capture.lines.clear()
    logging.getLogger("userbot.seller").debug("traceback", stack_info=True,
                                             exc_info=ValueError(f"session {SESSION}"))
    check("stack_info + exc_info ត្រូវ sanitize", stripped(capture.lines) == [])

    file_text = (LOG_DIR / "app.log").read_text(encoding="utf-8", errors="replace")
    check("app.log មិនមានសម្ងាត់", leaked(file_text) == [])
    check("app.log មានតំណាង [redacted]", "[redacted]" in file_text)

    print("— ៣) ផ្ទាំង Panel / ផ្នែក chat មិនបង្ហាញសម្ងាត់ —")
    async with db_session() as session:
        token = session_store.encrypt(SESSION)
        account = await crud.create_account(
            session, PHONE, token, name="Shop A", owner_admin_id=1001, enabled=True
        )
        await crud.set_account_status(
            session, account.id, AccountStatus.OFFLINE, f"fail {type(RuntimeError).__name__}"
        )
        await session.commit()
    card = render.account_card(account)
    row = render.account_row(account, 1)
    markup_text = str(keyboards.accounts_menu([account], None))
    check("account_card មាន 🔐 Session: ✅ Configured", "Session:" in card and "Configured" in card)
    check("account_card គ្មានលេខទូរស័ព្ទពេញ", leaked(card) == [])
    check("account_card គ្មាន API hash", API_HASH not in card and "12345" not in card)
    check("account_row បង្ហាញលេខបិទកណ្តាល", "+855****1670" in row and leaked(row) == [])
    check("ប៊ូតុងគណនី (button text) គ្មានសម្ងាត់", leaked(markup_text) == [])

    class FakeMessage:
        def __init__(self, text: str) -> None:
            self.text = text
            self.deleted = False

        async def delete(self) -> None:
            self.deleted = True

    secret_message = FakeMessage(SESSION)
    capture.lines.clear()
    await accounts_handlers._delete_secret(secret_message)
    check("សារដែលមាន session ត្រូវលុបភ្លាម", secret_message.deleted)

    class DyingMessage:
        async def delete(self) -> None:
            raise OSError(f"cannot delete {SESSION} {PHONE}")

    capture.lines.clear()
    await accounts_handlers._delete_secret(DyingMessage())
    check("លុបមិនបាន → log មានតែ type", stripped(capture.lines) == [] and "OSError" in " ".join(capture.lines))

    print("— ៤) Prompt មិនដែលចូល log (វាស់តែប្រវែង) —")
    async with db_session() as session:
        await crud.set_setting(session, "system_prompt", f"SELLER-PROMPT-TEXT {SENTINEL} {SESSION}")
        await crud.add_message(session, 5001, "user", f"សួស្ដី {PHONE} លេខកូដ {OTP} {SENTINEL}", account_id=account.id)
        await crud.add_message(session, 5001, "assistant", "hello friend", account_id=account.id)
        await session.commit()
    capture.lines.clear()
    seller = Seller(account.id, outbox=None)
    reply = await seller._generate(5001, (f"ចង់ទិញ {SENTINEL} {PHONE}",))
    joined = " ".join(capture.lines)
    check("AI ឆ្លើយ (mock) មិនទទេ", bool(reply))
    check("log មានវាស់ប្រវែង 'AI call'", "AI call" in joined and "chars" in joined)
    check("log គ្មានខ្លឹមសារ prompt", stripped(capture.lines) == [])
    check("log គ្មានខ្លឹមសារ system prompt", "SELLER-PROMPT-TEXT" not in joined)

    print("— ៥) កំហុសភ្ជាប់គណនី — notify/last_error/log មានតែ type —")
    notices: list[str] = []

    class BoomClient:
        def __init__(self, session, api_id, api_hash) -> None:
            self.session = session

        async def connect(self) -> bool:
            return True

        async def is_user_authorized(self) -> bool:
            return True

        async def get_me(self):
            raise RuntimeError(f"AuthFailed body: phone {PHONE} session {SESSION} otp {OTP}")

        async def disconnect(self) -> None:
            return None

        def add_event_handler(self, *args, **kwargs) -> None:
            return None

    def boom_make_client(account_id, session, device_index=None, *, api_id, api_hash):
        return BoomClient(session, api_id, api_hash)

    async def notify(text: str) -> None:
        notices.append(text)
        logging.getLogger("test.notify").info(text)

    # session string ក្លែង → ត្រូវជំនួស StringSession ពិត (Fernet នៅដំណើរការពិត)
    session_store.StringSession = type("FakeSession", (object,), {"__init__": lambda self, value="": None})
    original_make_client = manager_module.make_client
    manager_module.make_client = boom_make_client
    manager = manager_module.AccountManager(notify=notify)
    capture.lines.clear()
    ok = await manager.start_client(account)
    manager_module.make_client = original_make_client
    async with db_session() as session:
        stored = await crud.get_account(session, account.id)
    check("ភ្ជាប់មិនបាន → start_client False", ok is False)
    check("notify គ្មានសម្ងាត់", leaked(" ".join(notices)) == [])
    check("last_error ក្នុង DB គ្មានសម្ងាត់", leaked(stored.last_error or "") == [])
    check("last_error នៅសល់ type ឱ្យ debug", "RuntimeError" in (stored.last_error or ""))
    check("status → offline", stored.status == AccountStatus.OFFLINE)
    check("log ពេលភ្ជាប់មិនបាន គ្មានសម្ងាត់", stripped(capture.lines) == [])

    print("— ៦) ច្បាប់ក្នុង source (AST) — ការពារអនាគត —")
    offenders_raw: list[str] = []
    offenders_phone: list[str] = []
    ai_engine_logs: list[str] = []
    paths: list[Path] = [ROOT / "main.py"]
    for package in ("admin_bot", "userbot", "services", "ai_engine"):
        paths.extend(sorted((ROOT / package).rglob("*.py")))
    for path in paths:
        if "__pycache__" in path.parts or path.name.startswith("test_") or path.name == "smoke_test.py":
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute) or func.attr not in {
                "debug", "info", "warning", "error", "exception", "critical"
            }:
                continue
            head = func.value
            while isinstance(head, ast.Attribute):
                head = head.value
            if not (isinstance(head, ast.Name) and head.id in {"log", "logger", "logging"}):
                continue
            text = ast.unparse(node)
            if "exc_info" in text or "describe_error" in text or "__name__" in text:
                safe_exc = True
            else:
                safe_exc = not re.search(
                    r"(,\s*(e|err|exc|error|exception)\b|str\((e|err|exc|error|exception)\)|"
                    r"\{(e|err|exc|error|exception)\})",
                    text,
                )
            if not safe_exc:
                offenders_raw.append(f"{path.name}:{node.lineno}")
            if ".phone" in text and "mask_phone" not in text:
                offenders_phone.append(f"{path.name}:{node.lineno}")
            if path.parts[-2] == "ai_engine" and re.search(
                r"(system|prompt|history|user_text|content|reply)", text
            ):
                ai_engine_logs.append(f"{path.name}:{node.lineno}")
    check("គ្មាន log ណាបញ្ចូល exception ដោយផ្ទាល់", offenders_raw == [])
    check("គ្មាន log ណាបង្ហាញ .phone ដោយគ្មាន mask_phone", offenders_phone == [])
    check("ai_engine មិន log ខ្លឹមសារ prompt/system/history", ai_engine_logs == [])

    capture.lines.clear()
    logging.getLogger("cleanup").info("សាក បិទ capture")
    root.removeHandler(capture)

    failed = [label for label, ok_ in _checks if not ok_]
    print(f"\n{'✅ ជោគជ័យ' if not failed else '❌ បរាជ័យ'} — {len(_checks) - len(failed)}/{len(_checks)} checks")
    for label in failed:
        print(f"  ✗ {label}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_flow()))
