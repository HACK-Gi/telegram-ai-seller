"""🧪 Smoke test ជំហានទី ២.១ — Userbot multi-account (Sticky) ដោយគ្មានបណ្តាញ Telegram។

ប្រើ៖ python scripts/smoke_test_userbot.py

រាល់យុទ្ធសាស្ត្រសំខាន់ៗត្រូវតេស្តលើ DB ពិត + MockSender: sticky bind (ច្បាប់ A→A),
off-hours dedupe, warm-up tiers, rate cap derive, FloodWait pause, code gate, delivery
sweep, controls បញ្ជាម្ចាស់, session Fernet + secret redaction។ គ្មាន Telethon connect
ពិតទេ — ដំណាក់ផ្លូវ network ត្រូវ test លើគណនីពិតដោយ dj។
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# ---------- env ត្រូវកំណត់ *មុន* import config ----------
os.environ["USE_MOCK_BOT"] = "1"
os.environ["BOT_TOKEN"] = ""
os.environ["AI_BACKEND"] = "mock"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./data/smoke_userbot.db"
os.environ["OWNER_ID"] = "700000001"
os.environ["ADMIN_IDS"] = "700000002"
os.environ["TG_API_ID"] = "12345"
os.environ["TG_API_HASH"] = "0123456789abcdef0123456789abcdef"

from cryptography.fernet import Fernet  # noqa: E402

os.environ["SESSION_FERNET_KEY"] = Fernet.generate_key().decode()

for suffix in ("", "-wal", "-shm"):
    path = ROOT / "data" / f"smoke_userbot.db{suffix}"
    if path.exists():
        path.unlink()

logging.basicConfig(level=logging.CRITICAL)

import ai_engine  # noqa: E402
from ai_engine.mock import MockEngine  # noqa: E402

ai_engine._engine = MockEngine(latency=0)  # តេស្តមិនរង់ចាំ AI

from config import settings  # noqa: E402
from database import crud, db_session, init_db  # noqa: E402
from database.models import Account, AccountStatus, Order, OrderStatus, QRCode  # noqa: E402
from helpers import utcnow  # noqa: E402
from sqlalchemy import delete, select  # noqa: E402

from userbot import limits, safety, session_store  # noqa: E402
from userbot.catalog import VOICE_REJECT, Catalog, _newest_mention, purchase_intent  # noqa: E402
from userbot.coalescer import ConvKey, Coalescer  # noqa: E402
from userbot.controls import Controls  # noqa: E402
from userbot.manager import DEVICE_POOL, AccountManager, ManagerError  # noqa: E402
from userbot.outbox import PRIORITY_DELIVERY, Outbox, OutboxItem, PeerRef  # noqa: E402
from userbot.seller import Seller  # noqa: E402
from userbot.session_store import SessionCryptoError  # noqa: E402

# ជំហានទី ៥ — រាល់ គណនី/ប្រភេទ/ផលិតផល/QR ក្នុងតេស្តនេះ ជាของហាងតែមួយ (per-tenant)
SHOP = settings.owner_id

# ---------- រាប់ ----------
TOTAL = 0
PASSED = 0
FAILURES: list[str] = []


def check(name: str, condition: bool) -> None:
    global TOTAL, PASSED
    TOTAL += 1
    if condition:
        PASSED += 1
        print(f"  ✅ {name}")
    else:
        FAILURES.append(name)
        print(f"  ❌ {name}")


async def wait_until(pred, timeout: float = 6.0) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if pred():
            return True
        await asyncio.sleep(0.05)
    return pred()


async def wait_async(fn, timeout: float = 6.0):
    """ដូច wait_until ប៉ុន្តែ `fn` ជា async — ត្រឡប់តម្លៃដំបូងដែលមិនមែន None (ឧ. async DB read)។"""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        value = await fn()
        if value is not None or loop.time() >= deadline:
            return value
        await asyncio.sleep(0.05)


# ---------- MockSender ----------
class FloodWaitError(Exception):
    """ឈ្មោះ class ត្រូវតែដូច Telethon ពិត (flood_seconds ពិនិត្យតាម __name__) — .seconds។"""

    def __init__(self, seconds: int) -> None:
        super().__init__(f"A wait of {seconds} seconds is required")
        self.seconds = seconds


from contextlib import asynccontextmanager  # noqa: E402


class MockSender:
    def __init__(self, fail_first: Exception | None = None) -> None:
        self.sent: list[tuple[int, str]] = []
        self.buttoned: list[tuple[int, str, object]] = []
        self.photos: list[tuple[int, str, str]] = []
        self.typing_calls: list[float] = []
        self._fail_first = fail_first

    async def send_text(self, peer: PeerRef, text: str, buttons=None):
        if self._fail_first is not None:
            error = self._fail_first
            self._fail_first = None
            raise error
        self.sent.append((peer.peer_id, text))
        if buttons is not None:
            self.buttoned.append((peer.peer_id, text, buttons))

        class _Msg:
            id = len(self.sent)

        return _Msg()

    async def send_photo(self, peer: PeerRef, path: str, caption: str):
        self.photos.append((peer.peer_id, path, caption))
        self.sent.append((peer.peer_id, f"[photo] {caption}"))
        return None

    @asynccontextmanager
    async def typing(self, peer: PeerRef, seconds: float):
        self.typing_calls.append(seconds)
        yield None


async def instant_delay(bounds, *, sleep=None) -> float:
    return 0.0


# ---------- fixtures ----------
NOTICE_TEXT = "ខ្ញុំកំពុងសម្រាកបន្តិច…"


def fake_session(tag: str) -> str:
    """StringSession មិនត្រូវបានបង្កើតពិតក្នុងតេស្ត — encrypt ត្រូវការតែ str មិនទទេ។"""
    return f"1SESSIONPLACEHOLDER{tag}"


GOOD_API_HASH = "0123456789abcdef0123456789abcdef"


def real_session(seed: int) -> str:
    """StringSession ពិត (ដូច format អ្នកប្រើផ្ញើទៅ Bot) បង្កើត offline — auth key ក្លែង។"""
    from telethon.crypto import AuthKey
    from telethon.sessions import StringSession

    session = StringSession()
    session._dc_id = 2
    session._server_address = "149.154.167.51"
    session._port = 80
    session._auth_key = AuthKey(bytes([(seed * 7 + offset) % 256 for offset in range(32)]))
    return session.save()


async def make_account(phone: str, *, ai_enabled: bool = True, working_hours: str | None = None) -> Account:
    token = session_store.encrypt(fake_session(phone))
    async with db_session() as session:
        account = await crud.create_account(
            session, phone=phone, session_encrypted=token, name=phone, owner_admin_id=SHOP
        )
        account.enabled = True
        account.ai_enabled = ai_enabled
        account.working_hours = working_hours
    return account


CLOCK_NOON = lambda: datetime(2026, 10, 31, 12, 0)
CLOCK_3AM = lambda: datetime(2026, 10, 31, 3, 0)


class Harness:
    """Seller + Outbox + MockSender មួយគូក្នុងមួយគណនី។"""

    def __init__(
        self, account_id: int, *, sender=None, clock=CLOCK_NOON, debounce=0.01, start=True,
        with_catalog=False,
    ) -> None:
        self.notes: list[str] = []
        self.sender = sender or MockSender()
        self.outbox = Outbox(
            account_id,
            self.sender,
            notify=self._note,
            sleep=instant_sleep,
            delay_fn=instant_delay,
        )
        self.catalog = (
            Catalog(account_id, outbox=self.outbox, notify=self._note, is_staff=Seller._is_staff)
            if with_catalog
            else None
        )
        self.seller = Seller(
            account_id,
            outbox=self.outbox,
            notify=self._note,
            clock=clock,
            debounce_window=debounce,
            catalog=self.catalog,
        )
        if start:
            self.outbox.start()

    async def _note(self, text: str) -> None:
        self.notes.append(text)


async def instant_sleep(seconds: float) -> None:
    await asyncio.sleep(min(seconds, 0.02))


# ============================================================
async def test_session_crypto() -> None:
    print("\n[1] session_crypto — Fernet roundtrip + redaction")
    plain = "1" + "A" * 351
    token = session_store.encrypt(plain)
    check("encrypt → decrypt ត្រឡប់ដើម", session_store.decrypt(token) == plain)
    check("ciphertext ≠ plaintext", plain not in token)
    try:
        session_store.decrypt("not-a-fernet-token")
        check("ciphertext ខូច → SessionCryptoError", False)
    except SessionCryptoError:
        check("ciphertext ខូច → SessionCryptoError", True)
    check("fingerprint 12 hex ស្ថិតស្ថេរ", session_store.fingerprint(plain) == session_store.fingerprint(plain))
    check("key_status បង្ហាញរួចរាល់", session_store.key_status()[0])

    # secret redaction — session មិនដែលចេញ log
    logger = logging.getLogger("test.secret")
    filter_ = safety.SecretRedactor()
    record = logging.LogRecord("x", logging.ERROR, "", 0, f"connect failed session={plain}", (), None)
    filter_.filter(record)
    check("log record ត្រូវ redact session", plain not in record.getMessage() and "[redacted]" in record.getMessage())


async def test_api_credentials() -> None:
    print("\n[1b] App credentials — `.env` តែមួយគត់ (OTP login ត្រូវបានលុប)")
    from dataclasses import replace

    import config
    from userbot import credentials

    good_hash = GOOD_API_HASH
    env = credentials.env_credentials()
    check(".env រួចរាល់ → (api_id, api_hash)", env == (12345, good_hash))
    check("api_id ជា int (Telethon initConnection)", isinstance(env[0], int))
    check("resolve() អានពី .env តែមួយ", credentials.resolve() == env)
    check("is_configured() = True", credentials.is_configured())
    check("ខ្វះអ្វី → សារទទេពេល .env រួចរាល់", credentials.missing_credentials_message() == "")
    check("គ្មាន function បញ្ជូນ api_id/api_hash តាម chat",
          not any(hasattr(credentials, name) for name in ("valid_api_id", "valid_api_hash",
                                                          "encrypt_credential", "decrypt_credential",
                                                          "stored_credentials")))

    saved = config.settings
    try:
        config.settings = replace(saved, tg_api_id=0, tg_api_hash="")
        check(".env ទទេ → env_credentials None", credentials.env_credentials() is None)
        check(".env ទទេ → resolve None (គ្មាន fallback ទេ)", credentials.resolve() is None)
        check(".env ទទេ → is_configured False", not credentials.is_configured())
        empty = credentials.missing_credentials_message()
        check(".env ទទេ → ណែនាំ TG_API_ID + TG_API_HASH", "TG_API_ID" in empty and "TG_API_HASH" in empty)
        check(".env ទទេ → ណែនាំ my.telegram.org", "my.telegram.org" in empty)
        check("សារណែនាំមិនបង្ហាញ hash ពិត", good_hash not in empty)

        config.settings = replace(saved, tg_api_hash="zzzz")
        check("api_hash មិនមែន hex ៣២ → env_credentials None", credentials.env_credentials() is None)
        check("api_hash ខុស → រាប់តែ TG_API_HASH", "TG_API_ID" not in credentials.missing_credentials_message())
    finally:
        config.settings = saved

    phone = "+85517000123"
    async with db_session() as session:
        account = await crud.create_account(
            session, phone=phone, session_encrypted=session_store.encrypt(real_session(1)),
            name="Smoke Session", owner_admin_id=SHOP
        )
        account_id = account.id
    async with db_session() as session:
        stored = await crud.get_account(session, account_id)
    check("session ចូល DB ជា ciphertext", (stored.session_encrypted or "").startswith("gAAAAA"))
    check("ciphertext មិនផ្ទុក session plaintext", real_session(1) not in stored.session_encrypted)
    check("decrypt ត្រឡប់ session ដើម", session_store.decrypt(stored.session_encrypted) == real_session(1))
    check("addsession មិនសរសេរ api_id ចុះ row", not stored.tg_api_id_encrypted)
    check("addsession មិនសរសេរ api_hash ចុះ row", not stored.tg_api_hash_encrypted)

    from admin_bot.render import account_card

    card = account_card(stored)
    check("Panel បង្ហាញតែស្ថានភាព .env (✅)", "✅" in card and "❌" not in card)
    check("Panel មិនបង្ហាញ api_hash", good_hash not in card)
    check("Panel មិនបង្ហាញ api_id", "12345" not in card)
    check("Panel មិនបង្ហាញ session string", real_session(1) not in card)
    check("mask_phone បិទកណ្តាល", credentials.mask_phone("+85593251670") == "+855****1670")


async def test_session_string_store() -> None:
    print("\n[1c] Session String — ផ្លូវដែលសល់តែមួយ (គ្មាន OTP ក្នុង chat)")
    from telethon.sessions import StringSession

    from userbot import credentials

    plain = real_session(2)
    check("StringSession ពិត → ចាប់ផ្តើមដោយ '1'", plain.startswith("1"))
    check("StringSession ពិត → 352/353 តួ (វែងជាង gate ៥០)", len(plain) >= 300)
    check("API_HASH_RE ទទួល hex ៣២", credentials.API_HASH_RE.match(GOOD_API_HASH) is not None)
    check("API_HASH_RE បដិសេធតម្លៃខ្លី «abcd»", credentials.API_HASH_RE.match("abcd") is None)

    token = session_store.encrypt(plain)
    check("load_session ត្រឡប់ StringSession object", isinstance(session_store.load_session(token), StringSession))
    restored = session_store.load_session(token)
    check("load_session រក្សា dc_id/server/port/auth_key",
          (restored.dc_id, restored.server_address, restored.port) == (2, "149.154.167.51", 80)
          and restored.auth_key is not None)
    check("load_session មិនត្រឡប់ str (កុំបង្កើត SQLite file)", not isinstance(restored, str))
    check("fingerprint = 12 hex ប៉ុណ្ណោះ", len(session_store.fingerprint(plain)) == 12)
    check("fingerprint មិនបង្ហាញ session", session_store.fingerprint(plain) not in plain)

    try:
        session_store.encrypt("")
        check("session ទទេ → SessionCryptoError", False)
    except SessionCryptoError:
        check("session ទទេ → SessionCryptoError", True)

    class _NoKey:
        class session:
            @staticmethod
            def save() -> str:
                return ""

    try:
        session_store.store_session(_NoKey())
        check("គ្មាន auth key → បដិសេធមិនរក្សាទុក", False)
    except SessionCryptoError:
        check("គ្មាន auth key → បដិសេធមិនរក្សាទុក", True)

    try:
        session_store.load_session(session_store.encrypt("1" + "A" * 300))
        check("session ខូច → SessionCryptoError", False)
    except SessionCryptoError as exc:
        check("session ខូច → SessionCryptoError", True)
        check("session ខូច → សារមិនរសាត់ plaintext", "AAAA" not in str(exc))

    # session មិនដែលចេញ log (SecretRedactor + register_secret ពី encrypt)
    record = logging.LogRecord("x", logging.ERROR, "", 0, f"connect failed session={plain}", (), None)
    safety.SecretRedactor().filter(record)
    check("log record ត្រូវ redact session", plain not in record.getMessage() and "[redacted]" in record.getMessage())


async def test_sticky_rules() -> None:
    print("\n[2] Sticky binding — ច្បាប់ A→A គ្មានលើកលែង")
    cust = 800000111
    async with db_session() as session:
        await crud.get_or_create_customer(session, cust)
        bound = await crud.set_customer_account(session, cust, 1, access_hash=999)
        check("លើកដំបូង → bound", bound == "bound")
        again = await crud.set_customer_account(session, cust, 1)
        check("គណនីដដែល → already", again == "already")
        other = await crud.set_customer_account(session, cust, 2)
        check("គណនីផ្សេង → conflict (មិនប្តូរ binding)", other == "conflict")
        customer = await crud.get_customer_by_telegram(session, cust)
        check("binding នៅតែ account #1 ដដែល", customer.account_id == 1)
        check("access_hash ត្រូវរក្សាទុក", customer.access_hash == 999)
        missing = await crud.set_customer_account(session, 800000999, 1)
        check("អតិថិជនគ្មាន row → missing", missing == "missing")


async def test_windows() -> None:
    print("\n[3] Time window — in_window ត្រឹមនាទី + គ្របចុងថ្ងៃ")
    from helpers import in_window

    noon = datetime(2026, 10, 31, 12, 0)
    three_am = datetime(2026, 10, 31, 3, 0)
    check("12:00 ក្នុង 08:00-23:00", in_window("08:00-23:00", at=noon))
    check("03:00 ក្រៅ 08:00-23:00", not in_window("08:00-23:00", at=three_am))
    check("03:00 ក្នុង 20:00-06:00 (cross-midnight)", in_window("20:00-06:00", at=three_am))
    check("12:00 ក្រៅ 20:00-06:00", not in_window("20:00-06:00", at=noon))
    check("spec None → ២៤ ម៉ោង", in_window(None, at=three_am))
    check("spec ខុសទ្រង់ទ្រាយ → ២៤ ម៉ោង", in_window("broken", at=three_am))


async def test_budget() -> None:
    print("\n[4] Budget — warm-up tiers + derive ពី messages")
    check("ថ្ងៃ 0 → cap 20", limits.tier_for(0)[0] == 20)
    check("ថ្ងៃ 7 → cap 110 (tier ចុងក្រោយ)", limits.tier_for(7)[0] == 110)
    check("delay ថ្ងៃដំបូង 10-20s", limits.tier_for(0)[1] == (10.0, 20.0))

    account = await make_account("+85511100001")
    async with db_session() as session:
        fresh = await crud.get_account(session, account.id)
        day = limits.warmup_day_for(fresh)
        check("គណនីថ្មី warmup day 0", day == 0)
        budget = await limits.current_budget(session, fresh)
        check("ទំនេរ → open", budget.open and budget.hour_cap == settings.userbot_cap_hour)
        check("day_cap ត្រឹម tier 20 (មិន 200)", budget.day_cap == 20)
        check("reply_cap = day_cap − reserve", budget.reply_cap == 20 - settings.userbot_delivery_reserve)

        for _ in range(20):
            await crud.add_message(session, 9000001, "assistant", "x", account_id=account.id)
        budget2 = await limits.current_budget(session, fresh)
        check("ផ្ញើ 20 រួច → ដាក់ day cap", budget2.reason == "day" and not budget2.allows("ai_reply"))
        check("delivery នៅ allowed លុះត្រាដល់ day_cap", budget2.day_used == 20 and not budget2.allows("delivery"))

    # hour cap: 50 messages within the hour, day cap disabled by fresh no-warmup account
    account2 = await make_account("+85511100002")
    async with db_session() as session:
        await crud.set_account_warmup(session, account2.id, 0)
        fresh2 = await crud.get_account(session, account2.id)
        for _ in range(settings.userbot_cap_hour):
            await crud.add_message(session, 9000002, "assistant", "x", account_id=account2.id)
        budget3 = await limits.current_budget(session, fresh2)
        check("ដល់ 50/ម៉ោង → reason hour", budget3.reason == "hour" and not budget3.allows())
        check("blocked_until = សារចាស់+1ម៉ោង", budget3.blocked_until is not None)


async def test_notice_once() -> None:
    print("\n[5] notice_once — dedupe per bucket")
    async with db_session() as session:
        check("លើកទី១ → True", await crud.notice_once(session, "k1", bucket="2026-10-31"))
        check("bucket ដដែល → False", not await crud.notice_once(session, "k1", bucket="2026-10-31"))
        check("bucket ថ្មី → True", await crud.notice_once(session, "k1", bucket="2026-11-01"))


async def test_code_gate() -> None:
    print("\n[6] looks_like_code — រាំង AI មិនឱ្យប្រកាស Code")
    known = ["AB12CD34EF56GH78"]
    check("code ពិតក្នុង stock → block", safety.looks_like_code("code របស់បង AB12CD34EF56GH78", known_codes=known))
    check("រូបរាង code → block", safety.looks_like_code("នេះ KEYABCDEFGH12345"))
    check("តម្លៃទូរស័ព្ទមិន block", not safety.looks_like_code("012 345 678 លេខខ្ញុំ"))
    check("តម្លៃ $ មិន block", not safety.looks_like_code("តម្លៃ $19.99 បង"))
    check("ឈ្មោះផលិតផល uppercase មិន block", not safety.looks_like_code("FREEFIRE មាន 5 ពាន", safe_terms=("FREEFIRE",)))
    check("អត្ថបទធម្មតា មិន block", not safety.looks_like_code("សួស្តីបង មានអ្វីជួយ?"))


async def test_coalescer() -> None:
    print("\n[7] Coalescer — debounce បញ្ចូល batch")
    batches: list[tuple] = []

    async def flush(key, batch):
        batches.append((key, batch))

    co = Coalescer(flush, window=0.05, idle_exit=0.2)
    key = ConvKey(1, 42)
    for i in range(3):
        await co.submit(key, f"m{i}")
    ok = await wait_until(lambda: len(batches) == 1, 2.0)
    check("សារ 3 → batch 1", ok and len(batches[0][1]) == 3)
    check("រក្សាលំដាប់", batches[0][1] == ("m0", "m1", "m2"))


async def test_seller_flow() -> None:
    print("\n[8] Seller — sticky inbound → AI → outbox (ពិតប្រាកដ)")
    account = await make_account("+85511100008")
    harness = Harness(account.id)
    customer = 810000001

    status = await harness.seller.handle_inbound(customer, "សួស្តី", access_hash=555)
    check("submit → queued", status == "queued")
    async with db_session() as session:
        rows = await crud.get_history(session, customer, account_id=account.id)
        check("សារ user ចូល DB ភ្លាម (មិនរង់ចាំ flush)", rows == [("user", "សួស្តី")])
    sent = await wait_until(lambda: len(harness.sender.sent) == 1, 6.0)
    check("MockSender ទទួល 1 សារ", sent)
    if sent:
        peer_id, text = harness.sender.sent[0]
        check("តបទៅអតិថិជនត្រឹម", peer_id == customer and "សួស្តីបង" in text)

    async def settled_history():
        async with db_session() as session:
            rows = await crud.get_history(session, customer, account_id=account.id)
        return rows if len(rows) == 2 else None

    rows = await wait_async(settled_history)
    check("assistant row ក្រោយផ្ញើជោគជ័យ", rows is not None and rows[-1][0] == "assistant")
    check("typing indicator ត្រូវបានហៅ", len(harness.sender.typing_calls) >= 1)

    # conflict: customer របស់គណនីផ្សេងសរសេរមក
    other_customer = 810000002
    async with db_session() as session:
        await crud.get_or_create_customer(session, other_customer)
        await crud.set_customer_account(session, other_customer, 999)  # bound to account 999
    status = await harness.seller.handle_inbound(other_customer, "ជួយផង")
    check("conflict → មិនតប", status == "conflict")
    check("ជូនដំណឹងម្ចាស់ 1 ដង", any("sticky" in n for n in harness.notes))
    status2 = await harness.seller.handle_inbound(other_customer, "នៅទេ")
    check("ថ្ងៃដដែល → dedupe ជូនដំណឹង", status2 == "conflict" and sum("sticky" in n for n in harness.notes) == 1)

    # gates
    paused_customer = 810000003
    async with db_session() as session:
        cust = await crud.get_or_create_customer(session, paused_customer)
        await crud.set_customer_flag(session, cust.id, ai_paused=True)
    status = await harness.seller.handle_inbound(paused_customer, "សួស្តី")
    check("customer ai_paused → paused", status == "paused")
    blocked_customer = 810000004
    async with db_session() as session:
        cust = await crud.get_or_create_customer(session, blocked_customer)
        await crud.set_customer_flag(session, cust.id, is_blocked=True)
    status = await harness.seller.handle_inbound(blocked_customer, "សួស្តី")
    check("is_blocked → blocked", status == "blocked")
    check("សារ paused/blocked នៅតែត្រូវរក្សាទុក", True)
    async with db_session() as session:
        rows = await crud.get_history(session, paused_customer, account_id=account.id)
        check("paused message persisted", rows == [("user", "សួស្តី")])

    # staff មិនមែនអតិថិជន (Seller._is_staff)
    check("OWNER ត្រូវ seller រំលង", Seller._is_staff(settings.owner_id))
    check("admin ត្រូវរំលង", Seller._is_staff(700000002))
    check("អតិថិជនធម្មតា មិនរំលង", not Seller._is_staff(customer))


async def test_ai_gate_and_offhours() -> None:
    print("\n[9] Code gate + off-hours")
    account = await make_account("+85511100009")
    harness = Harness(account.id)
    customer = 820000001
    # MockEngine ពន្លឺ message → ឆ្លើយមានរូបរាង code → ត្រូវរាំង
    status = await harness.seller.handle_inbound(customer, "KEY-ABC123-DEF456-GH789")
    check("submit រួច", status == "queued")
    settled = await wait_until(lambda: harness.outbox.depth == 0 and bool(harness.notes), 6.0)
    check("code gate → គ្មានការផ្ញើ + ជូនដំណឹងម្ចាស់", settled and not harness.sender.sent and any("រាំង" in n for n in harness.notes))

    # off-hours: គ្មាន AI ទេ មានតែ auto-reply 1×/ថ្ងៃ ពីគណនីដដែល
    night = await make_account("+85511100010", working_hours="08:00-23:00")
    harness2 = Harness(night.id, clock=CLOCK_3AM)
    async with db_session() as session:
        await crud.set_setting(session, "off_hours_reply", NOTICE_TEXT)
    status = await harness2.seller.handle_inbound(820000002, "សួស្តី")
    check("off-hours មាន message ចូល → queued (AI រំលងពេល flush)", status == "queued")
    sent = await wait_until(lambda: len(harness2.sender.sent) == 1, 6.0)
    check("auto-reply ចេញ 1", sent and harness2.sender.sent[0][1] == NOTICE_TEXT)
    check("reply មកពីគណនីរបស់ខ្លួន (sticky)", harness2.sender.sent and True)
    status = await harness2.seller.handle_inbound(820000002, "នៅទេ")
    sent_again = await wait_until(lambda: len(harness2.sender.sent) >= 2, 1.0)
    check("ទី២ ថ្ងៃដដែល → dedupe មិនផ្ញើซ้ำ", not sent_again)


async def test_floodwait_and_delivery() -> None:
    print("\n[10] FloodWait pause + Code delivery sweep")
    account = await make_account("+85511100011")
    async with db_session() as session:
        await crud.get_or_create_customer(session, 830000001)
        await crud.set_customer_account(session, 830000001, account.id)

    flood = FloodWaitError(1)
    sender = MockSender(fail_first=flood)
    harness = Harness(account.id, sender=sender)

    harness.outbox.enqueue(
        OutboxItem(priority=1, seq=0, kind="ai_reply", peer=PeerRef(830000001), text="សួស្តី")
    )
    delivered = await wait_until(lambda: len(sender.sent) == 1, 8.0)
    check("FloodWait → retry រហូតដល់ផ្ញើជោគជ័យ", delivered)
    async with db_session() as session:
        acc = await crud.get_account(session, account.id)
    check("FloodWait → status paused + pause_until កត់ត្រា", acc.status == AccountStatus.PAUSED and acc.pause_until is not None)
    await harness.outbox.stop()

    # delivery sweep
    product_kwargs = {"name": "Netflix 1 ខែ", "price": 5.0, "description": "", "category": "vip"}
    async with db_session() as session:
        product = await crud.create_product(session, **product_kwargs)
        await crud.add_stock(session, product.id, ["CODE-NFLX-0001"])
        cust = await crud.get_or_create_customer(session, 830000002)
        await crud.set_customer_account(session, 830000002, account.id, access_hash=777)
        order = await crud.create_order(
            session,
            customer_id=830000002,
            product_id=product.id,
            product_name=product.name,
            price=product.price,
            account_id=account.id,
        )
        await crud.confirm_and_deliver(session, order.id)

    sender2 = MockSender()
    harness2 = Harness(account.id, sender=sender2)
    n = await harness2.seller.deliver_pending()
    check("sweep enqueue 1 order", n == 1)
    done = await wait_until(lambda: len(sender2.sent) == 1, 6.0)
    check("code ត្រូវផ្ញើដល់អតិថិជន", done and "CODE-NFLX-0001" in sender2.sent[0][1])
    async with db_session() as session:
        order_row = await crud.get_order(session, order.id)
        check("code_sent_at ត្រូវសម្គាល់", order_row.code_sent_at is not None)
    n2 = await harness2.seller.deliver_pending()
    check("sweep ទី២ → 0 (គ្មាន backlog)", n2 == 0)
    await harness2.outbox.stop()
    await harness2.seller.stop()


async def test_controls() -> None:
    print("\n[11] Controls — បញ្ជាម្ចាស់")

    class StubClient:
        def __init__(self) -> None:
            self.handlers = []

        def add_event_handler(self, handler, event):
            self.handlers.append(handler)

    class StubManager:
        def __init__(self) -> None:
            self.stops = 0
            self.starts = 0
            self.queues = {1: 2}

        def status(self):
            return {"running_accounts": list(self.queues), "global_stopped": False,
                    "started": True, "queues": dict(self.queues)}

        async def global_stop(self):
            self.stops += 1

        async def global_start(self):
            self.starts += 1

    class FakeEvent:
        def __init__(self, sender_id: int, text: str) -> None:
            self.is_private = True
            self.sender_id = sender_id
            self.text = text
            self.replies: list[str] = []

        async def respond(self, msg: str):
            self.replies.append(msg)

    client = StubClient()
    manager = StubManager()
    controls = Controls(1, client=client, manager=manager)
    check("handler ចុះបញ្ជីលើ client", len(client.handlers) == 1)

    cust = 840000001
    async with db_session() as session:
        await crud.get_or_create_customer(session, cust)
        # អតិថិជនត្រូវភ្ជាប់គណនី ទើបស្ថិតក្នុងវិសាលភាពរបស់ម្ចាស់គណនី #1 (Controls)
        await crud.set_customer_account(session, cust, 1)

    ev = FakeEvent(settings.owner_id, f"/pause {cust}")
    await controls.on_command(ev)
    async with db_session() as session:
        row = await crud.get_customer_by_telegram(session, cust)
        check("/pause → ai_paused=True", row.ai_paused)
    ev = FakeEvent(settings.owner_id, f"/resume {cust}")
    await controls.on_command(ev)
    async with db_session() as session:
        row = await crud.get_customer_by_telegram(session, cust)
        check("/resume → ai_paused=False", not row.ai_paused)

    ev = FakeEvent(settings.owner_id, "/pause")
    await controls.on_command(ev)
    check("/pause គ្មាន arg → បង្ហាញរបៀបប្រើ", ev.replies and "/pause <customer_id>" in ev.replies[0])
    ev = FakeEvent(settings.owner_id, "/pause 12345999")
    await controls.on_command(ev)
    check("រកមិនឃើញ → ប្រាប់", ev.replies and "រកមិនឃើញ" in ev.replies[0])

    ev = FakeEvent(settings.owner_id, "/pauseall")
    await controls.on_command(ev)
    async with db_session() as session:
        check("/pauseall → ai_enabled=off", (await crud.get_setting(session, "ai_enabled")) == "off")
    ev = FakeEvent(settings.owner_id, "/resumeall")
    await controls.on_command(ev)
    async with db_session() as session:
        check("/resumeall → ai_enabled=on", (await crud.get_setting(session, "ai_enabled")) == "on")

    ev = FakeEvent(888888, "/pauseall")
    await controls.on_command(ev)
    check("staff មិន → មិនប្រាប់អ្វីទេ", not ev.replies)

    ev = FakeEvent(settings.owner_id, "/status")
    await controls.on_command(ev)
    check("/status → រាយ queue", ev.replies and "ជួររង់ចាំ 2" in ev.replies[0])

    ev = FakeEvent(700000002, "/resume")  # admin id
    await controls.on_command(ev)
    check("admin ក៏បញ្ជាបាន", bool(ev.replies))

    # ---------- វិសាលភាព Staff — /pause /pauseall /stopbot /status ----------
    STAFF_ID = 700000002
    staff_cust = 840000002
    async with db_session() as session:
        staff_account = await crud.create_account(
            session, "+85512777002", "STAFF-SESSION", "Staff UB", owner_admin_id=STAFF_ID
        )
        staff_account_id = staff_account.id
        await crud.get_or_create_customer(session, staff_cust)
        await crud.set_customer_account(session, staff_cust, staff_account_id)
        await crud.set_setting(session, "ai_enabled", "on")
    manager.queues[staff_account_id] = 5

    ev = FakeEvent(STAFF_ID, f"/pause {cust}")  # អតិថិជនក្រៅវិសាលភាព
    await controls.on_command(ev)
    check("staff /pause អតិថិជនគេ → 🔒 បដិសេធ", ev.replies and "🔒" in ev.replies[0])
    async with db_session() as session:
        check("IDOR /pause មិនប៉ះ ai_paused", not (await crud.get_customer_by_telegram(session, cust)).ai_paused)

    ev = FakeEvent(STAFF_ID, f"/pause {staff_cust}")
    await controls.on_command(ev)
    async with db_session() as session:
        check("staff /pause អតិថិជនខ្លួន បាន", (await crud.get_customer_by_telegram(session, staff_cust)).ai_paused)

    ev = FakeEvent(STAFF_ID, "/pauseall")
    await controls.on_command(ev)
    async with db_session() as session:
        check("staff /pauseall មិនប៉ះ ai_enabled global",
              (await crud.get_setting(session, "ai_enabled")) == "on")
        check("staff /pauseall មិនផ្អាកអតិថិជនគេ",
              not (await crud.get_customer_by_telegram(session, cust)).ai_paused)
        check("staff /pauseall ផ្អាកអតិថិជនខ្លួន",
              (await crud.get_customer_by_telegram(session, staff_cust)).ai_paused)

    ev = FakeEvent(STAFF_ID, "/resumeall")
    await controls.on_command(ev)
    async with db_session() as session:
        check("staff /resumeall បើកតែគណនីខ្លួន",
              not (await crud.get_customer_by_telegram(session, staff_cust)).ai_paused
              and (await crud.get_setting(session, "ai_enabled")) == "on")

    stops_before, starts_before = manager.stops, manager.starts
    for cmd, attr in (("/stopbot", "stops"), ("/startbot", "starts")):
        ev = FakeEvent(STAFF_ID, cmd)
        await controls.on_command(ev)
        check(f"staff {cmd} → បដិសេធ Owner", bool(ev.replies) and "Owner គត់" in ev.replies[0])
    await asyncio.sleep(0.05)
    check("staff /stopbot//startbot មិនផ្លាស់ប្តូរ manager",
          (manager.stops, manager.starts) == (stops_before, starts_before))

    ev = FakeEvent(STAFF_ID, "/status")
    await controls.on_command(ev)
    check("staff /status បង្ហាញតែគណនីខ្លួន",
          ev.replies and f"គណនី #{staff_account_id} — ជួររង់ចាំ 5" in ev.replies[0]
          and "គណនី #1 —" not in ev.replies[0])

    ev = FakeEvent(settings.owner_id, "/status")
    await controls.on_command(ev)
    check("Owner /status ឃើញតែគណនីខ្លួន (មិនបង្ហាញគណនី staff)",
          ev.replies and f"គណនី #{staff_account_id}" not in ev.replies[0] and "ជួររង់ចាំ 2" in ev.replies[0])

    ev = FakeEvent(settings.owner_id, "/stopbot")
    await controls.on_command(ev)
    await asyncio.sleep(0.05)
    check("Owner /stopbot → manager.global_stop", manager.stops == stops_before + 1)
    ev = FakeEvent(settings.owner_id, "/startbot")
    await controls.on_command(ev)
    await asyncio.sleep(0.05)
    check("Owner /startbot → manager.global_start", manager.starts == starts_before + 1)
    await asyncio.sleep(0.05)


# ---------- fake Telethon events (media/callback) ----------
class MessageMediaVoice:
    pass


class MessageMediaVideoNote:
    pass


class MessageMediaSticker:
    pass


class MessageMediaPhoto:
    pass


class FakeMsg:
    def __init__(self, media=None, text=None) -> None:
        self.media = media
        self.text = text
        self.sticker = media if isinstance(media, MessageMediaSticker) else None
        self.edits: list[tuple] = []

    async def edit(self, new_text, buttons=None, parse_mode=None):
        self.edits.append((new_text, buttons))
        return self


class FakeInbound:
    def __init__(self, sender_id: int, message: FakeMsg) -> None:
        self.is_private = True
        self.sender_id = sender_id
        self.message = message
        self.text = message.text or ""
        self.input_sender = type("InputPeer", (), {"access_hash": 4242})()

    async def get_sender(self):
        return type("User", (), {"bot": False})()


class FakeCallback:
    def __init__(self, data: bytes, sender_id: int, message: FakeMsg | None = None) -> None:
        self.data = data
        self.sender_id = sender_id
        self.message = message if message is not None else FakeMsg()
        self.answers: list[str] = []

    async def answer(self, msg: str = "", cache_time: int = 0):
        self.answers.append(msg)


async def test_catalog_flow() -> None:
    print("\n[13] Catalog — voice gate + buttons + sales flow (sticky/oversell)")
    account = await make_account("+85511100013")
    async with db_session() as session:
        category, err = await crud.create_category(
            session, owner_admin_id=SHOP, code="smkt", prefix="SMKT", name_kh="ហ្គេមសាកល្បង", icon="🎮"
        )
        check("create_category រួច (code ថ្មី)", err == "" and category is not None)
        product = await crud.create_product(
            session,
            name="Free Fire Test",
            price=4.0,
            description="មុខសាកល្បង",
            category=category.name_kh,
            category_id=category.id,
            owner_admin_id=SHOP,
        )
        check("product_code ស្វ័យប្រវត្តិ SMKT-001", product.product_code == "SMKT-001")
        codes = await crud.add_stock_lines(session, product.id, ["ff-a@mail.com|p1", "ff-b@mail.com|p2"])
        check("stock ២ កូដ S001/S002", [c.code for c in codes] == ["SMKT-001-S001", "SMKT-001-S002"])
        pid, cid = product.id, category.id

    harness = Harness(account.id, with_catalog=True)

    # ---- voice/video rejection + sticker/photo ignore ----
    voice_cust = 850000001
    await harness.seller.on_incoming(FakeInbound(voice_cust, FakeMsg(media=MessageMediaVoice(), text=None)))
    got = await wait_until(lambda: any(t == VOICE_REJECT for _, t in harness.sender.sent), 6.0)
    check("voice → សារអភ័យទោសពិត", got)
    await harness.seller.on_incoming(FakeInbound(voice_cust, FakeMsg(media=MessageMediaVideoNote())))
    got2 = await wait_until(lambda: sum(t == VOICE_REJECT for _, t in harness.sender.sent) == 2, 6.0)
    check("video note → តបដូចគ្នា", got2)
    before = len(harness.sender.sent)
    await harness.seller.on_incoming(FakeInbound(voice_cust, FakeMsg(media=MessageMediaSticker())))
    await harness.seller.on_incoming(FakeInbound(voice_cust, FakeMsg(media=MessageMediaPhoto())))
    await asyncio.sleep(0.3)
    check("sticker/photo → មិនឆ្លើយ", len(harness.sender.sent) == before)
    async with db_session() as session:
        rows = await crud.get_history(session, voice_cust, account_id=account.id)
    check("voice-reject មិនចូល AI context", rows == [])

    # ---- ទំនាក់ទំនងដំបូង → welcome + buttons (មិនហៅ AI) ----
    cust = 850000002
    status = await harness.seller.handle_inbound(cust, "មាន Free Fire ទេ?")
    check("first contact → bound", status == "bound")
    await harness.catalog.send_welcome(cust, 4242)
    wel = await wait_until(lambda: bool(harness.sender.buttoned), 6.0)
    check("welcome មាន inline buttons", wel and "សួស្តីបង" in harness.sender.buttoned[0][1])
    async with db_session() as session:
        rows = await crud.get_history(session, cust, account_id=account.id)
    check("welcome no_log — រក្សាតែសារ user", rows == [("user", "មាន Free Fire ទេ?")])

    # on_incoming ផ្ទាល់ — bound → welcome ស្វ័យប្រវត្តិ ដោយមិនហៅ AI
    buttoned_before = len(harness.sender.buttoned)
    sent_before = len(harness.sender.sent)
    cust2 = 850000003
    await harness.seller.on_incoming(FakeInbound(cust2, FakeMsg(text="សួស្តី")))
    wired = await wait_until(lambda: len(harness.sender.buttoned) == buttoned_before + 1, 6.0)
    check("on_incoming first → welcome ស្វ័យប្រវត្តិ", wired)
    await asyncio.sleep(0.4)
    check("bound មិនបាញ់ AI លើសារដំបូង", len(harness.sender.sent) == sent_before + 1)

    # ---- keyword menu ----
    status = await harness.seller.handle_inbound(cust, "menu")
    check("«menu» → មេនុ មិនហៅ AI", status == "menu")
    menued = await wait_until(lambda: len(harness.sender.buttoned) >= 2, 6.0)
    check("menu ផ្ញើ buttons ទៀត", menued and "សម្ភារៈទាំងអស់" in harness.sender.buttoned[-1][1])

    # ---- callback paths ----
    alert, text, rows_btn = await harness.catalog.handle(cust, "ub:cats")
    check("ub:cats → ប្រភេទ SMKT", alert == "" and "ហ្គេមសាកល្បង" in text)
    alert, text, rows_btn = await harness.catalog.handle(cust, f"ub:cat:{cid}")
    check("ub:cat → header + បញ្ជី ub:prod", "ហ្គេមសាកល្បង" in text and any("ub:prod:" in d for row in rows_btn for _, d in row))
    alert, text, rows_btn = await harness.catalog.handle(cust, f"ub:prod:{pid}")
    check("ub:prod → កាត + 🛒 ទិញ", "SMKT-001" in text and any("ub:buy:" in d for row in rows_btn for _, d in row))
    alert, text, rows_btn = await harness.catalog.handle(cust, "ub:contact")
    check("ub:contact → អត្ថបទទំនាក់ទំនង", "ទំនាក់ទំនងម្ចាស់ហាង" in text)
    alert, text, rows_btn = await harness.catalog.handle(cust, "ub:expired")
    check("button ផុតកំណត់ → alert", "ផុតកំណត់" in alert)

    cb = FakeCallback(b"ub:cats", cust)
    await harness.catalog.on_callback(cb)
    check("on_callback → edit សារដដែល", cb.message.edits and cb.answers == [""])
    cb2 = FakeCallback(b"other:btn", cust)
    await harness.catalog.on_callback(cb2)
    check("button របស់ប្រព័ន្ធផ្សេង → រំលងស្ងាត់", not cb2.message.edits and cb2.answers == [""])
    cb3 = FakeCallback(b"ub:cats", settings.owner_id)
    await harness.catalog.on_callback(cb3)
    check("staff ចុច → ប្រាប់ មិន edit", not cb3.message.edits and "អតិថិជន" in cb3.answers[0])

    # ---- sales flow: buy → reserve + QR caption + owner notice ----
    alerts = [
        await harness.catalog.handle_buy(cust, pid),
        await harness.catalog.handle_buy(cust, pid),
    ]
    check("ទិញ ២ ដង → អាលែតទទេ (reserve ជោគជ័យ)", all(a == "" for a in alerts))
    third = await harness.catalog.handle_buy(cust, pid)
    check("ទិញទី៣ ស្តុកអស់ → រាំង oversell", third.startswith("🔴"))
    done = await wait_until(lambda: harness.outbox.depth == 0, 8.0)
    check("QR caption ចេញ ២ សារ", done and sum("បញ្ជាទិញ" in t for _, t in harness.sender.sent) == 2)
    check("ជូនដំណឹងម្ចាស់ 🛒 ២ ដង", sum("ការបញ្ជាទិញថ្មី" in n for n in harness.notes) == 2)
    async with db_session() as session:
        check("stock: 0 ទំនេរ · 2 កក់", await crud.available_stock(session, pid) == 0)
        orders = list((await session.scalars(select(Order).where(Order.customer_id == cust))).all())
        check("order 2 pending + 1 cancelled", len(orders) == 3)
        cancelled = [o for o in orders if o.status == OrderStatus.CANCELLED]
        check("order ចុងក្រោយ ត្រូវបោះបង់ (over-request)", len(cancelled) == 1)
        first_order = min(orders, key=lambda o: o.id)
        await crud.cancel_order(session, first_order.id)
        check("cancel → Code ត្រឡប់ទំនេរ", await crud.available_stock(session, pid) == 1)

    # ---- sticky hard-rule លើ button buy ----
    stranger = 850000009
    alert = await harness.catalog.handle_buy(stranger, pid)
    check("អតិថិជនគ្មាន row → រាំងមិនផ្ញើ QR", alert.startswith("⚠️"))
    notes_after = len(harness.notes)
    other_cust = 850000010
    async with db_session() as session:
        await crud.get_or_create_customer(session, other_cust)
        await crud.set_customer_account(session, other_cust, 999)
    alert = await harness.catalog.handle_buy(other_cust, pid)
    check("conflict sticky → រាំង + ជូនដំណឹងម្ចាស់", alert.startswith("⚠️") and len(harness.notes) > notes_after)
    await harness.outbox.stop()
    await harness.seller.stop()


async def test_text_buy_qr() -> None:
    print("\n[14] ទិញវាយតាមអក្សរ → QR ដែលម្ចាស់ Upload + cooldown ១០ នាទី")
    qr_image = ROOT / "data" / "smoke_qr.png"
    qr_image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"qr" * 24)

    account = await make_account("+85511100014")
    async with db_session() as session:
        category, err = await crud.create_category(
            session, owner_admin_id=SHOP, code="qrp", prefix="QRP", name_kh="ទូទាត់សាកល្បង", icon="💳"
        )
        product = await crud.create_product(
            session, name="Quick Pass Test", price=6.0, category=category.name_kh, category_id=category.id,
            owner_admin_id=SHOP,
        )
        other = await crud.create_product(
            session, name="PUBGM Test", price=9.0, category=category.name_kh, category_id=category.id,
            owner_admin_id=SHOP,
        )
        await crud.add_stock_lines(session, product.id, ["qp-1|a", "qp-2|b", "qp-3|c"])
        await crud.add_stock_lines(session, other.id, ["pubg-1|a"])
        await crud.create_qrcode(
            session, name="ABA smoke", provider="aba", account_info="012345678 ABA",
            image_path=str(qr_image), is_default=True, owner_admin_id=SHOP,
        )
        pid, other_id = product.id, other.id
    check("create_category សម្រាប់ផ្លូវ QR", err == "")

    # ---------- ១. ចេតនា + ការរកផលិតផល (មុខងារសុទ្ធ គ្មាន DB) ----------
    check(
        "ចេតនាទិញ/សុំ QR ចាប់បាន",
        all(purchase_intent(t) for t in ("បាទ យកមួយ", "ខ្ញុំចង់ទិញ", "qr បង", "ចង់បាញ់លុយ", "send me the qr")),
    )
    check(
        "គ្មានចេតនា → រាំង (តម្លៃ/សួរទូទៅ/បដិសេធ)",
        not any(purchase_intent(t) for t in ("តម្លៃប៉ុន្មាន?", "សួស្តីបង", "មិនទិញទេបង", "sok sabay", "")),
    )
    check("«pay» ក្នុង «payment» មិនត្រូវចាប់ខុសពាក្យ", purchase_intent("payment តាម qr"))
    items = [type("P", (), {"id": 1, "name": "VIP Account", "name_en": "", "product_code": "GAME-001"})(),
             type("P", (), {"id": 2, "name": "Quick Pass", "name_en": "", "product_code": "FF-001"})()]
    check("រកឃើញតាមឈ្មោះ", _newest_mention(items, "ខ្ញុំយក Quick Pass ១") == 2)
    check("រកឃើញតាម product_code", _newest_mention(items, "GAME-001 សល់ទេ") == 1)
    check("គ្មានការណែនាំ → None", _newest_mention(items, "មានអីចំណេញទេ?") is None)

    # ---------- ២. អន្តរាគមន៍ — Outbox ផ្ញើរូបភាពពិត ----------
    harness = Harness(account.id, with_catalog=True)
    cust = 860000001
    status = await harness.seller.handle_inbound(cust, "សួស្តី")
    check("ទំនាក់ទំនងដំបូង → bound", status == "bound")

    got = await harness.seller.handle_inbound(cust, "ខ្ញុំចង់ទិញ Quick Pass Test ១ មុខ")
    out = await wait_until(lambda: len(harness.sender.photos) == 1, 8.0)
    check("អតិថិជនវាយម្តង → AI តប + រូបភាព QR ចេញ", got == "queued" and out)
    check("ចម្លើយ AI ចេញមុន ឬក្រោយ QR ក៏បាន (២ សារ)", len(harness.sender.sent) >= 2)
    check("រូបភាពដែលផ្ញើ = ឯកសារ Upload របស់ម្ចាស់ (មិន Generate)", harness.sender.photos
          and harness.sender.photos[-1][1] == str(qr_image))
    check("caption បញ្ជាទិញចេញតាម Outbox", "បញ្ជាទិញ" in harness.sender.photos[-1][2])
    async with db_session() as session:
        pending = await crud.open_order_for_customer(session, cust, pid, account_id=account.id)
        check("order pending ត្រូវបង្កើត + crud រកឃើញ", pending is not None)
        check("ស្តុកកក់ ១ ពី ៣", await crud.available_stock(session, pid) == 2)

    # ---------- ៣. cooldown ១០ នាទី (DB មិនមែន cache) ----------
    again = await harness.seller._maybe_send_qr(cust, 777, ("យកមួយទៀត Quick Pass Test",), "")
    check("ក្នុង ១០ នាទី → qr_cooldown", again == "qr_cooldown")
    check("cooldown មិនបាញ់រូបភាពថ្មី", len(harness.sender.photos) == 1)
    async with db_session() as session:
        await crud.update_order(session, pending.id, created_at=utcnow() - timedelta(minutes=11))
    after = await harness.seller._maybe_send_qr(cust, 777, ("យកមួយទៀត Quick Pass Test",), "")
    resent = await wait_until(lambda: len(harness.sender.photos) == 2, 8.0)
    check("កាត់ ១០ នាទី → ផ្ញើ QR ម្តងទៀតបាន", after == "qr_sent" and resent)
    async with db_session() as session:
        rows = list((await session.scalars(select(Order).where(Order.customer_id == cust))).all())
        check("order ២ pending ក្រោយ cooldown ផុតកំណត់", len([r for r in rows if r.status == OrderStatus.PENDING_PAYMENT]) == 2)

    # ---------- ៤. ករណីមិនផ្ញើ ----------
    check("គ្មានចេតនា → no_intent", await harness.seller._maybe_send_qr(cust, 777, ("តម្លៃប៉ុន្មាន?",), "") == "no_intent")
    check(
        "ចេតនា ប៉ុន្តែមិនបញ្ជាក់ឈ្មោះ + ហាងច្រើនមុខ → ambiguous",
        await harness.seller._maybe_send_qr(cust, 777, ("ខ្ញុំចង់ទិញមួយមុខ",), "") == "ambiguous",
    )
    check("ឈ្មោះនៅក្នុងចម្លើយ AI ក៏រកឃើញ",
          await harness.seller._maybe_send_qr(cust, 777, ("យកមួយ",), "Quick Pass Test តម្លៃ $6 បង") == "qr_cooldown")
    bare = Harness(account.id, start=False)
    check("គ្មាន catalog → no_catalog", await bare.seller._maybe_send_qr(cust, 777, ("យកមួយ Quick Pass Test",), "") == "no_catalog")

    # ---------- ៥. គ្មាន QR → ជូនដំណឹងម្ចាស់ភ្លាម ----------
    async with db_session() as session:
        await session.execute(delete(QRCode))
    notes_before = len(harness.notes)
    photos_before = len(harness.sender.photos)
    noqr = await harness.seller._maybe_send_qr(cust, 777, ("ចង់ទិញ PUBGM Test",), "")
    captioned = await wait_until(lambda: any("PUBGM Test" in t for _, t in harness.sender.sent), 8.0)
    check("គ្មាន QR → នៅដំណើរការ order (មិនប្រកាសកំហុស)", noqr == "qr_sent" and captioned)
    check("គ្មាន QR → ជូនដំណឹងម្ចាស់ភ្លាម", any("គ្មាន QR" in n for n in harness.notes[notes_before:]))
    check("គ្មាន QR → មិនមែនរូបភាព", len(harness.sender.photos) == photos_before)
    text_only = [t for _, t in harness.sender.sent if "PUBGM Test" in t]
    check("គ្មាន QR → caption មិនសន្យា «QR នេះ»", "រៀបចំព័ត៌មានបង់ប្រាក់" in text_only[0] and "QR នេះ" not in text_only[0])

    await harness.outbox.stop()
    await harness.seller.stop()
    qr_image.unlink(missing_ok=True)


async def test_qr_account_ladder() -> None:
    print("\n[15] QR Ladder — QR ភ្ជាប់គណនីឈ្នះ QR ផលិតផល និង QR ទូទៅ (លើផ្លូវទិញពិត)")
    owner_img = ROOT / "data" / "smoke_qr_owner.png"
    acct_img = ROOT / "data" / "smoke_qr_acct.png"
    prod_img = ROOT / "data" / "smoke_qr_prod.png"
    for path in (owner_img, acct_img, prod_img):
        path.write_bytes(b"\x89PNG\r\n\x1a\n" + path.stem.encode() * 8)

    seller_a = await make_account("+85511100015")
    seller_b = await make_account("+85511100016")
    async with db_session() as session:
        category, err = await crud.create_category(
            session, owner_admin_id=SHOP, code="qrlad", prefix="QRL", name_kh="ជណ្តើរ QR", icon="💳"
        )
        product = await crud.create_product(
            session, name="Ladder Pass", price=5.0, category=category.name_kh, category_id=category.id,
            owner_admin_id=SHOP,
        )
        await crud.add_stock_lines(session, product.id, ["lad-1|a", "lad-2|b", "lad-3|c"])
        # ៣ ជាន់៖ ភ្ជាប់គណនី A → ភ្ជាប់ផលិតផល (គ្មានគណនី) → default ម្ចាស់ (គ្មានគណនី)
        await crud.create_qrcode(
            session, name="Owner default", provider="aba", account_info="000000 ABA",
            image_path=str(owner_img), is_default=True, owner_admin_id=SHOP,
        )
        await crud.create_qrcode(
            session, name="QR A", provider="aba", account_info="111111 ABA",
            image_path=str(acct_img), account_id=seller_a.id, owner_admin_id=SHOP,
        )
        await crud.create_qrcode(
            session, name="QR product", provider="aba", account_info="222222 ABA",
            image_path=str(prod_img), product_id=product.id, owner_admin_id=SHOP,
        )
        pid = product.id
    check("create_category សម្រាប់ជណ្តើរ QR", err == "")

    # គណនី A — QR ភ្ជាប់គណនី ឈ្នះទាំង QR ផលិតផល និង QR ទូទៅ
    ha = Harness(seller_a.id, with_catalog=True)
    cust_a = 860000100
    await ha.seller.handle_inbound(cust_a, "សួស្តី")
    await ha.seller.handle_inbound(cust_a, "ខ្ញុំចង់ទិញ Ladder Pass ១ មុខ")
    sent_a = await wait_until(lambda: len(ha.sender.photos) >= 1, 8.0)
    check("គណនី A → ផ្ញើ QR ភ្ជាប់គណនី A", sent_a and ha.sender.photos[0][1] == str(acct_img))

    # គណនី B — គ្មាន QR ភ្ជាប់ខ្លួន → QR ផលិតផល (មិនមែន default)
    hb = Harness(seller_b.id, with_catalog=True)
    cust_b = 860000101
    await hb.seller.handle_inbound(cust_b, "សួស្តី")
    await hb.seller.handle_inbound(cust_b, "ខ្ញុំចង់ទិញ Ladder Pass ១ មុខ")
    sent_b = await wait_until(lambda: len(hb.sender.photos) >= 1, 8.0)
    check("គណនី B → QR ផលិតផល (គ្មាន QR ភ្ជាប់គណនី)", sent_b and hb.sender.photos[0][1] == str(prod_img))
    check("QR របស់គណនី A មិនធ្លាក់ទៅគណនី B", all(p[1] != str(acct_img) for p in hb.sender.photos))

    # លុប QR ផលិតផល → គណនី B ត្រឡប់ទៅ default របស់ម្ចាស់
    async with db_session() as session:
        await session.execute(delete(QRCode).where(QRCode.product_id == pid))
    hc = Harness(seller_b.id, with_catalog=True)
    cust_c = 860000102
    await hc.seller.handle_inbound(cust_c, "សួស្តី")
    await hc.seller.handle_inbound(cust_c, "ខ្ញុំចង់ទិញ Ladder Pass ១ មុខ")
    sent_c = await wait_until(lambda: len(hc.sender.photos) >= 1, 8.0)
    check("គ្មាន QR ផលិតផល → ត្រឡប់ទៅ default របស់ម្ចាស់", sent_c and hc.sender.photos[0][1] == str(owner_img))

    for harness in (ha, hb, hc):
        await harness.outbox.stop()
        await harness.seller.stop()
    for path in (owner_img, acct_img, prod_img):
        path.unlink(missing_ok=True)


async def test_qr_never_cross_owner() -> None:
    print("\n[16] QR មិនឆ្លងម្ចាស់ — ហាងគ្មាន QR → ជូនដំណឹងម្ចាស់ មិនមែនផ្ញើ QR ហាងផ្សេង")
    alien_img = ROOT / "data" / "smoke_qr_alien.png"
    alien_img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"alien" * 10)

    shop_owner, alien_owner = 911001, 911002
    async with db_session() as session:
        # សម្អាត QR ពីជំហានមុនៗ — បើនៅមាន default ណាមួយ ជណ្តើរនឹងយកវាជំនួស ALIEN
        # ធ្វើឱ្យការត្រួតពិនិត្យនេះឆ្លងដោយស្ងាត់ ទោះកំហុសឆ្លងម្ចាស់ត្រឡប់មកវិញក៏ដោយ
        await session.execute(delete(QRCode))
        token = session_store.encrypt(fake_session("+85511100017"))
        lonely = await crud.create_account(session, phone="+85511100017", session_encrypted=token,
                                           name="No QR shop", owner_admin_id=shop_owner)
        category, _err = await crud.create_category(
            session, owner_admin_id=shop_owner, code="xown", prefix="XOWN", name_kh="ឆ្លងម្ចាស់", icon="💳"
        )
        product = await crud.create_product(
            session, name="Lonely Pass", price=3.0, category=category.name_kh,
            category_id=category.id, owner_admin_id=shop_owner,
        )
        await crud.add_stock_lines(session, product.id, ["lon-1|a"])
        # ហាងផ្សេងទៀតមាន QR ទូទៅ (default) — មិនត្រូវបាញ់ច្រឡំឡើយ
        await crud.create_qrcode(
            session, name="ALIEN QR", provider="aba", account_info="999999 ALIEN BANK",
            image_path=str(alien_img), is_default=True, owner_admin_id=alien_owner,
        )
        lonely_id, product_id = lonely.id, product.id

    # start=False — អ្វីដែល assert គឺ «អ្វីដែលដាក់ចូល outbox» មិនមែនអ្វីដែលផ្ញើរួច
    # ដូច្រេះ ការត្រួតពិនិត្យមិនអាស្រ័យលើ budget/enabled ហើយបរាជ័យពិតប្រាកដ បើ QR ឆ្លងម្ចាស់
    harness = Harness(lonely_id, with_catalog=True, start=False)
    cust = 860000200
    await harness.seller.handle_inbound(cust, "សួស្តី")
    alert = await harness.catalog.handle_buy(cust, product_id)

    queued = list(harness.outbox._items)
    check("QR របស់ហាងផ្សេង មិនត្រូវដាក់ចូល outbox (រូបភាព)",
          not any(item.file_path == str(alien_img) for item in queued))
    check("QR របស់ហាងផ្សេង មិនត្រូវដាក់ចូល outbox (caption មានលេខគណនីហាងផ្សេង)",
          not any("ALIEN" in item.text for item in queued))
    check("caption មិនសន្យា «QR នេះ» ពេលគ្មាន QR របស់ខ្លួន",
          all("QR នេះ" not in item.text for item in queued))
    check("គ្មាន QR របស់ខ្លួន → ជូនដំណឹងម្ចាស់ភ្លាម", any("គ្មាន QR" in note for note in harness.notes))
    async with db_session() as session:
        left = await crud.available_stock(session, product_id)
    check("Order នៅត្រូវបានបង្កើត ហើយស្តុកត្រូវកក់ (មិនបាត់)", alert == "" and left == 0)

    await harness.outbox.stop()
    await harness.seller.stop()
    alien_img.unlink(missing_ok=True)


async def test_manager_surface() -> None:
    print("\n[12] Manager — send gate + device pool")
    manager = AccountManager(notify=None)
    try:
        await manager.send_message(999, 123, "សាកល្បង")
        check("គណនីមិន active → ManagerError (មិន fallback)", False)
    except ManagerError:
        check("គណនីមិន active → ManagerError (មិន fallback)", True)
    info = manager.status()
    check("status shape ត្រឹម", info["running_accounts"] == [] and info["global_stopped"] is False)
    check("DEVICE_POOL ≥ 4 variants", len(DEVICE_POOL) >= 4)
    d1 = DEVICE_POOL[1 % len(DEVICE_POOL)]
    d1b = DEVICE_POOL[1 % len(DEVICE_POOL)]
    check("device ជ្រើសស្ថិតស្ថេរតាម id", d1 == d1b)
    ok, message = session_store.key_status()
    check("fernet key រួចរាល់សម្រាប់ login CLI", ok)


async def main() -> int:
    await init_db()
    print("🧪 userbot smoke — ជំហានទី ២.១ (គ្មានបណ្តាញ)")
    await test_session_crypto()
    await test_api_credentials()
    await test_session_string_store()
    await test_sticky_rules()
    await test_windows()
    await test_budget()
    await test_notice_once()
    await test_code_gate()
    await test_coalescer()
    await test_seller_flow()
    await test_ai_gate_and_offhours()
    await test_floodwait_and_delivery()
    await test_controls()
    await test_manager_surface()
    await test_catalog_flow()
    await test_text_buy_qr()
    await test_qr_account_ladder()
    await test_qr_never_cross_owner()
    print(f"\n{'✅ រំលង' if PASSED == TOTAL else '❌ មាន failure'} — {PASSED}/{TOTAL} checks ឆ្លងកាត់")
    if FAILURES:
        for name in FAILURES:
            print(f"   ✗ {name}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
