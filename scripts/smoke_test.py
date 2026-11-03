"""🧪 Smoke test — រត់ Admin Panel ទាំងមូលលើ MockSession (គ្មាន BOT_TOKEN, គ្មានបណ្តាញ)។

ប្រើ៖ python scripts/smoke_test.py

វាបង្កើត DB សាកល្បងដាច់ដោយឡែក បញ្ជូន update ក្លែងក្លាយឆ្លងកាត់ dispatcher រួចពិនិត្យថា
(១) រាល់ ការចុចប៊ូតុង/សារ មាន handler ទទួល (២) គ្មាន ERROR log លាក់ខ្លួន (៣) ទិន្នន័យក្នុង DB ត្រឹមត្រូវ។
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# ត្រូវកំណត់មុន import config (config អាន .env តែម្តងគត់)
os.environ["USE_MOCK_BOT"] = "1"
os.environ["BOT_TOKEN"] = ""
os.environ["AI_BACKEND"] = "mock"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./data/smoke_test.db"
# Chat login តេស្តលើ FakeClient (គ្មានបណ្តាញ) — ត្រូវការ credential/Fernet មិនទទេ
os.environ["TG_API_ID"] = "12345"
os.environ["TG_API_HASH"] = "0123456789abcdef0123456789abcdef"
from cryptography.fernet import Fernet  # noqa: E402

os.environ["SESSION_FERNET_KEY"] = Fernet.generate_key().decode()

from aiogram.dispatcher.event.bases import UNHANDLED  # noqa: E402
from aiogram.types import Update  # noqa: E402

from admin_bot.bot import build_dispatcher, create_bot  # noqa: E402
from config import settings  # noqa: E402
from database import crud, db_session, init_db  # noqa: E402

OWNER = settings.owner_id
STRANGER = 999000111
CUSTOMER_TG = 555000111

_sequence = iter(range(1, 100_000))


def _user(user_id: int) -> dict:
    return {"id": user_id, "is_bot": False, "first_name": "Owner" if user_id == OWNER else "Stranger"}


def _chat(user_id: int) -> dict:
    return {"id": user_id, "type": "private", "first_name": "Owner"}


def _payload(kind: str, user_id: int, **fields) -> dict:
    """សាង Update payload (message ឬ callback_query) ក្នុង chat ឯកជនរបស់ user_id។"""
    now = datetime.now().isoformat()
    if kind == "message":
        body = {"message_id": next(_sequence), "date": now, "chat": _chat(user_id), "from": _user(user_id), **fields}
    else:
        body = {
            "id": f"q{next(_sequence)}",
            "from": _user(user_id),
            "chat_instance": "1",
            "message": {"message_id": 1, "date": now, "chat": _chat(user_id), "from": _user(OWNER), "text": "…"},
            **fields,
        }
    return {"update_id": next(_sequence), kind: body}


class Recorder(logging.Handler):
    """ចាប់ ERROR ទាំងអស់ — on_error របស់ dispatcher គ្រាន់តែ log មិន raise ទេ។"""

    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self.records: list[str] = []
        self.raw: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(f"{record.name}: {record.getMessage()}")
        self.raw.append(record)


class Panel:
    def __init__(self, bot, dispatcher) -> None:
        self.bot = bot
        self.dispatcher = dispatcher
        self.session = bot.session
        self.errors: list[str] = []
        self.checked = 0

    async def feed(self, kind: str, label: str, *, expect_reply: bool = True, unhandled_ok: bool = False,
                   user_id: int = OWNER, **fields):
        before = len(self.session.sent)
        update = Update.model_validate(_payload(kind, user_id, **fields), context={"bot": self.bot})
        result = await self.dispatcher.feed_update(self.bot, update)

        self.checked += 1
        if result is UNHANDLED and not unhandled_ok:
            self.errors.append(f"✗ {label}: គ្មាន handler ទទួល (UNHANDLED)")
        elif expect_reply and len(self.session.sent) == before:
            self.errors.append(f"✗ {label}: គ្មានសារតប ជូន owner")
        return result

    async def msg(self, text: str, **kwargs):
        return await self.feed("message", f"msg {text[:32]!r}", text=text, **kwargs)

    async def cb(self, data: str, **kwargs):
        return await self.feed("callback_query", f"cb {data!r}", data=data, **kwargs)

    def said(self, fragment: str) -> bool:
        return any(fragment in item for item in self.session.texts)

    def mark(self) -> int:
        """ចំណុចយោង — ប្រើជាមួយ said_since ដើម្បីវាស់តែសារដែលចេញ *ក្រោយ* ជំហាននេះ។"""
        return len(self.session.texts)

    def said_since(self, mark: int, fragment: str) -> bool:
        return any(fragment in item for item in self.session.texts[mark:])

    def says_not_since(self, mark: int, fragment: str) -> bool:
        return not any(fragment in item for item in self.session.texts[mark:])


# ---------- Fake Telethon — ចុះឈ្មោះ Session String ដោយគ្មានបណ្តាញ ----------
# ចំណុចប្រទាក់ពិតរបស់ accounts.md_login_session:
#   TelegramClient(StringSession(session_string), api_id, api_hash) → 3 positional args
API_ID_ENV = 12345
API_HASH_ENV = "0123456789abcdef0123456789abcdef"
# Sentinel ដាច់គេ វែងជាង threshold ៥០ និងចាប់ផ្តើមដោយលេខ ដូច StringSession ពិត
SESSION_A = "1" + "A" * 249
SESSION_B = "2" + "B" * 249
LOGIN_PHONE = "+85512777000"
from userbot.safety import mask_phone as _mask  # noqa: E402
MASKED_PHONE = _mask(LOGIN_PHONE)  # Panel/log បង្ហាញតែទ្រង់ទ្រាយបិទកណ្តាល


class AuthKeyUnregisteredError(Exception):
    """ឈ្មោះ class ត្រូវដូច Telethon — សារបរាជ័យបញ្ចេញតែ `type(exc).__name__`។"""


class _FakeStringSession:
    """កុំ allow Telethon decode តម្លៃក្លែងក្លាយ ហើយចាំ input ដើមដើម្បីវាស់។"""

    seen: list[str] = []

    def __init__(self, value: str = "") -> None:
        _FakeStringSession.seen.append(value)
        self.value = value


class _FakeMe:
    def __init__(self, phone: str) -> None:
        self.id = 777000999
        self.phone = phone
        self.username = "smoke_login"
        self.first_name = "Smoke"
        self.last_name = "Login"


class FakeClient:
    """ក្លែង TelegramClient តាម `mode` — គ្រប់សាขារបស់ md_login_session។"""

    mode = "ok"          # ok | unauthorized | no_me | auth_revoked
    phone = LOGIN_PHONE
    built: list["FakeClient"] = []

    def __init__(self, session, api_id, api_hash) -> None:
        self.session = session
        self.creds = (api_id, api_hash)
        self.disconnected = False
        FakeClient.built.append(self)

    @classmethod
    def reset(cls, mode: str = "ok", *, phone: str = LOGIN_PHONE) -> None:
        cls.mode = mode
        cls.phone = phone
        cls.built.clear()
        _FakeStringSession.seen.clear()

    @classmethod
    def last(cls) -> "FakeClient":
        return cls.built[-1]

    async def connect(self) -> bool:
        if self.mode == "auth_revoked":
            raise AuthKeyUnregisteredError("auth key unregistered")
        return True

    async def get_me(self):
        return None if self.mode == "no_me" else _FakeMe(self.phone)

    async def is_user_authorized(self) -> bool:
        return self.mode != "unauthorized"

    async def disconnect(self) -> None:
        self.disconnected = True


class FakeManager:
    """ជំនួស AccountManager — វាស់តែថា addsession ជោគជ័យហើយ userbot ត្រូវ hot-reload។"""

    def __init__(self) -> None:
        self.reconciled = 0

    async def reconcile(self) -> None:
        self.reconciled += 1


def install_fake_telethon() -> None:
    """accounts.py វាយ `from telethon import TelegramClient` ក្នុង function → patch តែ module attribute។"""
    import telethon
    from telethon import sessions as telethon_sessions

    telethon.TelegramClient = FakeClient
    telethon_sessions.StringSession = _FakeStringSession


async def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    recorder = Recorder()
    logging.getLogger().addHandler(recorder)

    os.chdir(ROOT)
    Path("data/smoke_test.db").unlink(missing_ok=True)
    await init_db()

    bot = create_bot()
    dispatcher = build_dispatcher()
    panel = Panel(bot, dispatcher)

    print("— ការពារអ្នកប្រើអនាមិក —")
    await panel.feed("message", "stranger /start", expect_reply=False, user_id=STRANGER, text="/start")
    await panel.feed("callback_query", "stranger cb", expect_reply=False, user_id=STRANGER, data="menu:main")

    print("— មេនុសំខាន់ —")
    await panel.msg("/start")
    await panel.msg("/menu")
    await panel.msg("/id")
    await panel.msg("/help")
    for name in ("products", "qr", "prompt", "orders", "customers", "accounts", "analytics", "settings"):
        await panel.cb(f"menu:{name}")
    # ជំហានទី ១ — «Admins» ត្រូវលុបចេញពី Panel ទាំងស្រុង (គ្មាន handler, គ្មានប៊ូតុង)
    mark = panel.mark()
    await panel.cb("menu:admins", unhandled_ok=True, expect_reply=False)
    if not panel.says_not_since(mark, "Admins"):
        panel.errors.append("✗ «Admins» នៅសល់ក្នុង Panel")
    mark = panel.mark()
    await panel.msg("/start")
    if not panel.says_not_since(mark, "Admins"):
        panel.errors.append("✗ មេនុសំខាន់ នៅបង្ហាញប៊ូតុង Admins")

    print("— បង្កើតផលិតផល + Stock —")
    await panel.cb("prod:add")
    await panel.msg("Game Key SMOKE")
    await panel.msg("-key សម្រាប់សាកល្បង")
    await panel.msg("4.99")
    await panel.msg("ហ្គេម")
    await panel.msg("skip")
    async with db_session() as session:
        products, _total = await crud.list_products(
            session, search="Game Key SMOKE", page=1, per_page=10, owner_admin_id=OWNER
        )
        product_id = next((item.id for item in products if item.name == "Game Key SMOKE"), None)
        cat_rows = await crud.list_all_categories(session, OWNER)
        game_row = next((row for row in cat_rows if row.code == "game_acc"), None)
        game_cat_id = game_row.id if game_row else 0
    if product_id is None:
        panel.errors.append("✗ រកមិនឃើញផលិតផល 'Game Key SMOKE' ក្នុង DB")
    else:
        await panel.cb(f"prod:stock:{product_id}:auto")
        await panel.msg("KEY-AAA\nKEY-BBB\nKEY-CCC")
        await panel.cb(f"prod:view:{product_id}")
        await panel.cb(f"prod:toggle:{product_id}")
        await panel.cb(f"prod:toggle:{product_id}")
        await panel.cb("prod:search")
        await panel.msg("SMOKE")
        await panel.cb("prod:categories")
        if game_cat_id:
            await panel.cb(f"prod:filter:{game_cat_id}")
        await panel.cb("prod:filter:")

    print("— 📦 គ្រប់គ្រងប្រភេទ —")
    await panel.msg("/categories")
    await panel.cb("cat:add")
    await panel.msg("smoke_cat")
    await panel.msg("ប្រភេទសាកល្បង")
    await panel.msg("Smoke Cat")
    await panel.msg("🧪")
    await panel.msg("SMK")
    await panel.msg("-")
    async with db_session() as session:
        smoke_cat = await crud.get_category_by_code(session, "smoke_cat", owner_admin_id=OWNER)
        if smoke_cat is None:
            panel.errors.append("✗ មិនបានបង្កើតប្រភេទ smoke_cat")
            smoke_cat_id = None
        else:
            smoke_cat_id = smoke_cat.id
            if smoke_cat.product_prefix != "SMK":
                panel.errors.append(f"✗ prefix រក្សាទុកខុស ({smoke_cat.product_prefix})")
    if smoke_cat_id:
        await panel.cb(f"cat:view:{smoke_cat_id}")
        await panel.cb(f"cat:f:name_kh:{smoke_cat_id}")
        await panel.msg("ប្រភេទសាកល្បង ២")
        await panel.cb(f"cat:toggle:{smoke_cat_id}")
        await panel.cb("cat:add")
        await panel.msg("smoke_cat")  # code ស្ទួន → ត្រូវតែបដិសេធ
        await panel.msg("smoke_cat_dup_exit")  # ចេញពី AddCategory.code
        await panel.msg("/cancel")
    await panel.cb(f"cat:askdel:{smoke_cat_id}")
    await panel.cb(f"cat:del:{smoke_cat_id}")
    async with db_session() as session:
        if await crud.get_category(session, smoke_cat_id, owner_admin_id=OWNER) is not None:
            panel.errors.append("✗ លុបប្រភេទមិនបាន")
    await panel.cb(f"cat:askdel:{game_cat_id}")
    await panel.cb(f"cat:del:{game_cat_id}")  # blocked — មានផលិតផល
    async with db_session() as session:
        if await crud.get_category(session, game_cat_id, owner_admin_id=OWNER) is None:
            panel.errors.append("✗ ប្រភេទដែលមានផលិតផល ត្រូវតែលុបមិនបាន")
    await panel.msg("/addcategory")
    await panel.msg("smoke_abandoned")
    await panel.msg("/cancel")
    await panel.msg("/lowstock")
    await panel.msg("/products")
    await panel.msg("/addstock")
    await panel.msg("/addstock does_not_exist")
    async with db_session() as session:
        smokes, _n = await crud.list_products(session, search="SMOKE")
        smoke_product = smokes[0] if smokes else None
    if smoke_product:
        await panel.msg(f"/addstock {smoke_product.product_code}")
        await panel.msg("freshowner@mail.com|secret9")
        async with db_session() as session:
            codes = await crud.list_stock(session, smoke_product.id, limit=50)
        generated = [c.code for c in codes if c.code.endswith("-S004")]
        if not generated:
            panel.errors.append(f"✗ /addstock មិនបានបង្កើត code ថ្មី ({[c.code for c in codes]})")
        elif smoke_product.product_code and not generated[0].startswith(smoke_product.product_code):
            panel.errors.append(f"✗ code ថ្មីមិនតាម prefix ({generated[0]})")

    print("— QR (Upload only) —")
    await panel.cb("qr:add")
    await panel.cb("qr:addto:0")
    await panel.msg("ABA SMOKE")
    await panel.msg("aba")
    await panel.msg("012 345 678 · ABA · Sok Dara")
    await panel.msg("skip")
    async with db_session() as session:
        qrs = await crud.list_qrcodes(session)
        qr_id = qrs[0].id if qrs else None
    if qr_id is None:
        panel.errors.append("✗ រកមិនឃើញ QR ក្នុង DB")
    else:
        async with db_session() as session:
            qr = await crud.get_qrcode(session, qr_id)
        if qr is not None and qr.image_file_id:
            panel.errors.append(f"✗ QR មានរូបដោយស្វ័យប្រវត្តិ ({qr.image_file_id}) — ត្រូវទទេ")
        await panel.cb(f"qr:image:{qr_id}")
        await panel.msg("skip")
        await panel.cb(f"qr:default:{qr_id}")
        await panel.cb(f"qr:view:{qr_id}")
        await panel.cb(f"qr:link:{qr_id}")
    for gone in ("qr:newgen", f"qr:regen:{qr_id or 1}"):
        handled = await panel.cb(gone, unhandled_ok=True, expect_reply=False)
        if handled is not UNHANDLED:
            panel.errors.append(f"✗ វិធីបង្កើត QR ស្វ័យប្រវត្តិ នៅមាន ({gone})")

    print("— Order ដោយដៃ → Confirm & Deliver —")
    # Order ដោយដៃ ត្រូវការគណនីរបស់ tenant នេះខ្លួនឯង (មិនមែន «Owner ឃើញទាំងអស់» ទៀតទេ)
    async with db_session() as session:
        account = await crud.create_account(
            session, "+85512999000", "SMOKE-NOT-A-REAL-SESSION", owner_admin_id=OWNER
        )
        account_id = account.id
    await panel.cb("ord:add")
    await panel.msg(str(CUSTOMER_TG))
    await panel.msg(str(product_id))
    async with db_session() as session:
        orders, _ = await crud.list_orders(session, page=1, per_page=5)
        order_id = orders[0].id if orders else None
    if order_id is None:
        panel.errors.append("✗ មិនបានបង្កើត Order")
    else:
        await panel.cb(f"ord:view:{order_id}")
        await panel.cb(f"ord:note:{order_id}")
        await panel.msg("សាកល្បង memo")
        await panel.cb(f"ord:confirm:{order_id}")
        if not panel.said("KEY-"):
            panel.errors.append("✗ Confirm & Deliver មិនបានបង្ហាញ Code")
    await panel.cb("ord:list:all")
    await panel.cb("ord:list:pending_payment")
    await panel.msg("/orders")

    print("— CRM —")
    await panel.cb("menu:customers")
    async with db_session() as session:
        customers, _ = await crud.list_customers(session, page=1, per_page=10)
        customer_pk = customers[0].id if customers else None
    if customer_pk is None:
        panel.errors.append("✗ មិនមានអតិថិជនក្នុង DB")
    else:
        await panel.cb(f"cus:view:{customer_pk}")
        await panel.cb(f"cus:pause:{customer_pk}")
        await panel.cb(f"cus:resume:{customer_pk}")
        await panel.cb(f"cus:tagsel:{customer_pk}")
        await panel.cb(f"cus:note:{customer_pk}")
        await panel.msg("ចំណាំសាកល្បង")
        await panel.cb(f"cus:orders:{customer_pk}")
    await panel.msg("/pauseall")
    await panel.msg("/resumeall")
    await panel.cb("cus:search")
    await panel.msg("555")

    print("— AI Prompt —")
    await panel.cb("menu:prompt")
    await panel.cb("prompt:show")
    await panel.cb("prompt:fs")
    await panel.cb("prompt:fs:edit")
    await panel.msg("អតិថិជន: សួស្តី\nអ្នកលក់: សួស្តីបង 🙏")
    await panel.cb("prompt:fs:default")
    await panel.cb("prompt:test")
    await panel.cb("ptest:3")
    await panel.cb("ptest:custom")
    await panel.msg("តម្លៃប៉ុន្មាន?")

    print("— គណនី + Analytics + Settings —")
    await panel.cb("acc:howto")
    await panel.cb("menu:accounts")
    await panel.cb(f"acc:view:{account_id}")
    await panel.cb(f"acc:ai:{account_id}")
    await panel.cb(f"acc:ai:{account_id}")
    await panel.cb(f"acc:primary:{account_id}")
    await panel.cb("ana:send")
    await panel.msg("/stats")
    await panel.cb("set:ai")
    await panel.cb("set:userbot")
    await panel.cb("set:hours")
    await panel.msg("08:00-23:00")
    await panel.cb("set:offreply")
    await panel.msg("ខ្ញុំសម្រាកបន្តិច 🙏")
    await panel.cb("set:threshold")
    await panel.msg("5")
    await panel.cb("set:lang")
    await panel.cb("set:lang:km")
    await panel.cb("set:backup")
    # ជំហានទី ២ — «Add Admin» ត្រូវលុប: អ្នកប្រើណា ចុច /start = ម្ចាស់ហាងខ្លួនឯងភ្លាម
    # (feed() រាប់ error ឯង បើ /start គ្មានសារតប)
    await panel.msg("/start", user_id=777000123)
    mark = panel.mark()
    await panel.msg("/addadmin 777000123 Admin SMOKE", unhandled_ok=True, expect_reply=False)
    if not panel.says_not_since(mark, "បានបន័ែម Admin"):
        panel.errors.append("✗ /addadmin នៅដំណើរការ")
    await panel.cb("menu:main")
    await panel.msg("/cancel")

    print("— RBAC — វិសាលភាព Staff (Owner-only + IDOR) —")
    STAFF = 777000456
    STAFF_PHONE = "+85512777456"
    OWNER_ONLY_TEXT = "ម្ចាស់ (Owner)"

    def expect(label: str, ok: bool) -> None:
        if not ok:
            panel.errors.append(f"✗ {label}")

    async with db_session() as session:
        await crud.add_admin(session, STAFF, "Staff SMOKE")
        staff_account = await crud.create_account(
            session, STAFF_PHONE, "STAFF-NOT-A-REAL-SESSION", "Staff SMOKE",
            owner_admin_id=STAFF, enabled=True,
        )
        staff_account_id = staff_account.id
        await crud.get_or_create_customer(session, 555000901)
        await crud.set_customer_account(session, 555000901, staff_account_id)
        await crud.get_or_create_customer(session, 555000902)
        await crud.set_customer_account(session, 555000902, account_id)
        staff_customer = await crud.get_customer_by_telegram(session, 555000901)
        owner_customer = await crud.get_customer_by_telegram(session, 555000902)
        staff_qr = await crud.create_qrcode(
            session, name="ABA STAFF", provider="ABA", account_info="https://pay.aba.example/staff",
            owner_admin_id=STAFF,
        )
        staff_qr_id = staff_qr.id
        staff_order = await crud.create_order(
            session, customer_id=555000901, product_id=product_id, product_name="Staff Order SMOKE",
            price=2.5, account_id=staff_account_id,
        )
        staff_order_id = staff_order.id

    mark = panel.mark()
    await panel.cb("prod:add", user_id=STAFF)
    await panel.msg("Staff Key ONLY", user_id=STAFF)
    await panel.msg("-staff note", user_id=STAFF)
    await panel.msg("2.50", user_id=STAFF)
    await panel.msg("ហ្គេម", user_id=STAFF)
    await panel.msg("skip", user_id=STAFF)
    async with db_session() as session:
        staff_products, _n = await crud.list_products(session, search="Staff Key", owner_admin_id=STAFF)
        staff_product_id = staff_products[0].id if staff_products else None
    expect("staff បង្កើតផលិតផលបាន + ភ្ជាប់ម្ចាស់", staff_product_id is not None)

    mark = panel.mark()
    await panel.msg("/products", user_id=STAFF)
    expect("staff ឃើញផលិតផលខ្លួន", panel.said_since(mark, "Staff Key ONLY"))
    expect("staff មិនឃើញផលិតផល owner", panel.says_not_since(mark, "Game Key SMOKE"))

    mark = panel.mark()
    await panel.cb(f"prod:view:{product_id}", user_id=STAFF)
    expect("IDOR prod:view → បដិសេធ", panel.said_since(mark, "រកមិនឃើញផលិតផល"))
    expect("IDOR prod:view មិនបង្ហាញឈ្មោះផលិតផល owner", panel.says_not_since(mark, "Game Key SMOKE"))

    await panel.cb(f"prod:del:{product_id}", user_id=STAFF)
    await panel.cb(f"prod:askdel:{product_id}", user_id=STAFF)
    async with db_session() as session:
        expect("IDOR prod:del លុបមិនបាន (owner នៅដដែល)", await crud.get_product(session, product_id) is not None)

    # ជំហានទី ៥ — ប្រភេទជា per-tenant: staff = ម្ចាស់ហាងខ្លួន គ្រប់គ្រងបញ្ជីរបស់ខ្លួន
    # ហាង STAFF កើតតាម add_admin (មិនមែន auto_register) ទើបยังគ្មានប្រភេទរបស់ខ្លួន
    mark = panel.mark()
    await panel.cb("menu:categories", user_id=STAFF)
    expect("staff មិនឃើញប្រភេទរបស់ Owner (per-tenant)", panel.says_not_since(mark, "គណនីហ្គេម"))
    expect("staff ឃើញសារ «មិនទាន់មានប្រភេទ» សម្រាប់ហាងខ្លួន", panel.said_since(mark, "មិនទាន់មានប្រភេទ"))

    mark = panel.mark()
    await panel.cb("cat:add", user_id=STAFF)
    await panel.msg("staff_cat", user_id=STAFF)
    await panel.msg("ប្រភេទ Staff", user_id=STAFF)
    await panel.msg("-", user_id=STAFF)
    await panel.msg("🧺", user_id=STAFF)
    await panel.msg("STF", user_id=STAFF)
    await panel.msg("-", user_id=STAFF)
    async with db_session() as session:
        staff_cat = await crud.get_category_by_code(session, "staff_cat", owner_admin_id=STAFF)
        expect("staff បន័ែមប្រភេទរបស់ខ្លួនបាន (code ស្ទួន cross-tenant បាន)", staff_cat is not None)
        expect("ប្រភេទ staff ភ្ជាប់ម្ចាស់ត្រូវ", staff_cat is not None and staff_cat.owner_admin_id == STAFF)
        staff_cat_id = staff_cat.id if staff_cat else 0
        stolen = await crud.get_category(session, staff_cat_id, owner_admin_id=OWNER)
        expect("Owner ចុច ID ប្រភេទរបស់ staff → IDOR បដិសេធ", stolen is None)
        cross = await crud.get_category_by_code(session, "smoke_cat", owner_admin_id=STAFF)
        expect("staff search code របស់ Owner → រកមិនឃើញ", cross is None)

    mark = panel.mark()
    await panel.cb("menu:categories", user_id=OWNER)
    expect("Owner មិនឃើញប្រភេទរបស់ staff", panel.says_not_since(mark, "ប្រភេទ Staff"))

    async with db_session() as session:
        before = await crud.get_category(session, game_cat_id, owner_admin_id=OWNER)
        was_active = bool(before and before.is_active)
    await panel.cb(f"cat:toggle:{game_cat_id}", user_id=STAFF)
    async with db_session() as session:
        after = await crud.get_category(session, game_cat_id, owner_admin_id=OWNER)
        expect("IDOR cat:toggle ប្រភេទ Owner → is_active មិនប្តូរ",
               bool(after and after.is_active) == was_active)
        held = await crud.get_category(session, staff_cat_id, owner_admin_id=STAFF)
    await panel.cb(f"cat:toggle:{staff_cat_id}", user_id=STAFF)
    async with db_session() as session:
        flipped = await crud.get_category(session, staff_cat_id, owner_admin_id=STAFF)
        expect("staff toggle ប្រភេទខ្លួន ប្តូរ is_active",
               flipped is not None and held is not None and flipped.is_active != held.is_active)
    await panel.cb(f"cat:askdel:{staff_cat_id}", user_id=STAFF)
    await panel.cb(f"cat:del:{staff_cat_id}", user_id=STAFF)
    async with db_session() as session:
        expect("staff លុបប្រភេទរបស់ខ្លួនបាន",
               await crud.get_category(session, staff_cat_id, owner_admin_id=STAFF) is None)
        expect("លុបរបស់ staff → ប្រភេទ Owner នៅគ្រប់ ៨",
               len(await crud.list_all_categories(session, OWNER)) == 8)

    for target, name in (("settings", "⚙️"), ("prompt", "🧠")):
        mark = panel.mark()
        await panel.cb(f"menu:{target}", user_id=STAFF, unhandled_ok=True)
        expect(f"staff ចូល {target} មិនបាន", panel.said_since(mark, OWNER_ONLY_TEXT))

    mark = panel.mark()
    await panel.cb(f"ord:view:{order_id}", user_id=STAFF)
    expect("IDOR ord:view → បដិសេធ", panel.said_since(mark, "រកមិនឃើញ") and panel.says_not_since(mark, "Game Key SMOKE"))
    mark = panel.mark()
    await panel.cb(f"ord:view:{staff_order_id}", user_id=STAFF)
    expect("staff ឃើញ Order ខ្លួន", panel.said_since(mark, "Staff Order SMOKE"))
    await panel.cb(f"ord:confirm:{order_id}", user_id=STAFF)
    async with db_session() as session:
        guarded = await crud.get_order(session, order_id, account_ids=(staff_account_id,))
        expect("IDOR ord:confirm មិនបាន deliver", guarded is None)

    mark = panel.mark()
    await panel.cb(f"qr:view:{qr_id}", user_id=STAFF)
    expect("IDOR qr:view → បដិសេធ", panel.said_since(mark, "រកមិនឃើញ") and panel.says_not_since(mark, "ABA SMOKE"))
    mark = panel.mark()
    await panel.cb(f"qr:default:{qr_id}", user_id=STAFF)
    expect("staff កំណត់ default QR owner មិនបាន", panel.said_since(mark, "រកមិនឃើញ"))
    async with db_session() as session:
        owner_qr = await crud.get_qrcode(session, qr_id, owner_admin_id=None)
        expect("default QR owner នៅដដែល", bool(owner_qr and owner_qr.is_default))

    # ជំហានទី ២.២ — QR ភ្ជាប់គណនី + វិសាលភាពតាម account_ids
    mark = panel.mark()
    await panel.cb("qr:add", user_id=STAFF)
    expect("qr:add សួរថាគណនីណាទទួលប្រាក់", panel.said_since(mark, "គណនីណាដែល QR នេះទទួលប្រាក់?"))
    mark = panel.mark()
    await panel.cb(f"qr:addto:{account_id}", user_id=STAFF)
    expect("staff ភ្ជាប់ QR នឹងគណនីរបស់ owner មិនបាន", panel.said_since(mark, "មិនមែនរបស់អ្នក"))
    mark = panel.mark()
    await panel.cb(f"qr:addto:{staff_account_id}", user_id=STAFF)
    await panel.msg("ABA STAFF ACCT", user_id=STAFF)
    await panel.msg("aba", user_id=STAFF)
    await panel.msg("098 765 432 · ABA · Staff", user_id=STAFF)
    await panel.msg("skip", user_id=STAFF)
    async with db_session() as session:
        mine = await crud.list_qrcodes(session, owner_admin_id=STAFF)
        bound = [item for item in mine if item.name == "ABA STAFF ACCT"]
        bound_id = bound[0].id if bound else None
    expect("staff បង្កើត QR ភ្ជាប់គណនីខ្លួនបាន", bound_id is not None and bound[0].account_id == staff_account_id)
    if bound_id is not None:
        mark = panel.mark()
        await panel.cb(f"qr:view:{bound_id}", user_id=STAFF)
        expect("card បង្ហាញគណនីដែល QR ភ្ជាប់", panel.said_since(mark, "គណនីដែលលក់"))

    async with db_session() as session:
        await crud.create_qrcode(
            session, name="QR KHIR ACCOUNT SMOKE", provider="ABA", account_info="owner account number",
            owner_admin_id=STAFF, account_id=account_id,
        )
        visible = await crud.list_qrcodes(session, owner_admin_id=STAFF, account_ids=(staff_account_id,))
        unscoped = await crud.list_qrcodes(session, owner_admin_id=STAFF)
    expect(
        "QR ដែលភ្ជាប់គណនីក្រៅវិសាលភាព មិនលេចក្នុងបញ្ជី staff",
        any(item.name == "QR KHIR ACCOUNT SMOKE" for item in unscoped)
        and not any(item.name == "QR KHIR ACCOUNT SMOKE" for item in visible),
    )
    mark = panel.mark()
    await panel.cb("menu:qr", user_id=STAFF)
    expect("បញ្ជី QR ក្នុង Panel មិនបង្ហាញ QR ក្រៅគណនី staff", panel.says_not_since(mark, "QR KHIR ACCOUNT SMOKE"))

    # លំដាប់ជ្រើស QR តាមគណនីលក់ — ប្រាក់ត្រូវចូលគណនីដែលត្រូវគ្នា
    async with db_session() as session:
        await crud.create_qrcode(
            session, name="QR ACCT SMOKE", provider="ABA", account_info="account specific",
            owner_admin_id=OWNER, account_id=account_id,
        )
        picked = await crud.best_qrcode(session, owner_admin_id=OWNER, account_id=account_id)
        other = await crud.best_qrcode(session, owner_admin_id=OWNER, account_id=staff_account_id)
        plain = await crud.best_qrcode(session, owner_admin_id=OWNER)
    expect("QR ភ្ជាប់គណនីឈ្នះលើ default ទូទៅ", picked is not None and picked.name == "QR ACCT SMOKE")
    expect(
        "លក់លើគណនីផ្សេង → fallback QR ទូទៅ មិនយក QR គណនីអ្នកដទៃ",
        other is not None and other.account_id is None,
    )
    expect("គ្មាន account_id → វិធីចាស់នៅដំណើរការ", plain is not None and plain.name == "ABA SMOKE")

    mark = panel.mark()
    await panel.msg("/accounts", user_id=STAFF)
    expect("staff ឃើញគណនីខ្លួន (លេខបិទកណ្តាល)", panel.said_since(mark, _mask(STAFF_PHONE)))
    expect("staff មិនឃើញគណនី owner", panel.says_not_since(mark, "+85512999000"))
    mark = panel.mark()
    await panel.cb(f"acc:view:{account_id}", user_id=STAFF)
    expect("IDOR acc:view → បដិសេធ", panel.said_since(mark, "រកមិនឃើញ"))
    mark = panel.mark()
    await panel.cb(f"acc:ai:{account_id}", user_id=STAFF)
    expect("IDOR acc:ai → បដិសេធ", panel.said_since(mark, "រកមិនឃើញ"))
    mark = panel.mark()
    await panel.cb(f"acc:primary:{staff_account_id}", user_id=STAFF, unhandled_ok=True)
    expect("staff កំណត់ Primary មិនបាន", panel.said_since(mark, OWNER_ONLY_TEXT))
    mark = panel.mark()
    await panel.cb(f"acc:askowner:{staff_account_id}", user_id=STAFF, unhandled_ok=True)
    expect("staff ប្ដូរម្ចាស់គណនីមិនបាន", panel.said_since(mark, OWNER_ONLY_TEXT))
    async with db_session() as session:
        staff_row = await crud.get_account(session, staff_account_id)
        expect("staff មិនបានក្លាយជា primary", staff_row is not None and not staff_row.is_primary)
        expect("staff មិនបានប្ដូរម្ចាស់គណនីខ្លួន", staff_row is not None and staff_row.owner_admin_id == STAFF)

    mark = panel.mark()
    await panel.cb(f"cus:view:{owner_customer.id}", user_id=STAFF)
    expect("IDOR cus:view → បដិសេធ", panel.said_since(mark, "រកមិនឃើញអតិថិជន"))
    await panel.cb(f"cus:pause:{owner_customer.id}", user_id=STAFF)
    async with db_session() as session:
        untouched = await crud.get_customer_by_telegram(session, 555000902)
        expect("IDOR cus:pause មិនប៉ះអតិថិជន owner", untouched is not None and not untouched.ai_paused)
    mark = panel.mark()
    await panel.cb(f"cus:view:{staff_customer.id}", user_id=STAFF)
    expect("staff ឃើញអតិថិជនខ្លួន", panel.says_not_since(mark, "រកមិនឃើញអតិថិជន"))
    mark = panel.mark()
    async with db_session() as session:
        ai_before = await crud.get_setting(session, "ai_enabled", "on")
    await panel.msg("/pauseall", user_id=STAFF)
    expect("staff /pauseall ផ្អាកតែហាងខ្លួន (មិនមែន global)", panel.said_since(mark, "គណនីរបស់អ្នក"))
    async with db_session() as session:
        expect("staff /pauseall មិនប៉ះ ai_enabled global",
               (await crud.get_setting(session, "ai_enabled", "on")) == ai_before)
        expect("staff /pauseall មិនផ្អាកអតិថិជន owner",
               not (await crud.get_customer_by_telegram(session, 555000902)).ai_paused)

    mark = panel.mark()
    await panel.msg("/lowstock", user_id=STAFF)
    expect("staff /lowstock មិនបង្ហាញ stock owner", panel.says_not_since(mark, "Game Key SMOKE"))
    mark = panel.mark()
    await panel.cb(f"prod:view:{staff_product_id}", user_id=OWNER)
    expect("Owner មិនឃើញផលិតផល staff (IDOR ទិន្នន័យលម្អិត)",
           panel.said_since(mark, "រកមិនឃើញផលិតផល") and panel.says_not_since(mark, "Staff Key ONLY"))

    print("— ចុះឈ្មោះគណនី — Session String (OTP login ត្រូវបានលុបចោល) —")
    import dataclasses

    import config
    from admin_bot.handlers import accounts as accounts_handlers
    from database.models import Account as _Account
    from sqlalchemy import select as _select
    from userbot import manager as manager_module
    from userbot import session_store

    install_fake_telethon()

    async def fetch_account(phone: str):
        async with db_session() as session:
            return await session.scalar(_select(_Account).where(_Account.phone == phone))

    async def account_count(phone: str) -> int:
        async with db_session() as session:
            return len((await session.scalars(_select(_Account).where(_Account.phone == phone))).all())

    async def add_session(user_id: int = STAFF) -> None:
        await panel.msg("/addsession", user_id=user_id)

    # ១) OTP លុបចេញពី code មែន ឬ — រចនាសម្ព័ន្ធ (កុំឱ្យ FSM ចាស់ត្រឡប់មកវិញដោយស្ងាត់)
    expect("Session FSM មាន waiting_session", hasattr(accounts_handlers.LoginStates, "waiting_session"))
    expect(
        "OTP FSM states ត្រូវបានលុប (waiting_phone/code/password មិនមាន)",
        not any(
            hasattr(accounts_handlers.LoginStates, name)
            for name in ("waiting_phone", "waiting_code", "waiting_password")
        ),
    )
    expect(
        "គ្មាន OTP handler ក្នុង accounts (md_login_code/md_login_password/_begin_login)",
        not any(
            hasattr(accounts_handlers, name)
            for name in ("md_login_code", "md_login_password", "_begin_login", "login_key")
        ),
    )

    # ២) ទ្វារចូលចាស់ → បញ្ជូនទៅ Session String តែប៉ុណ្ណោះ
    mark = panel.mark()
    await panel.msg(f"/addaccount {LOGIN_PHONE}", user_id=STAFF)
    expect("/addaccount → បង្ហាញសារណែនាំឱ្យប្រើ /addsession", panel.said_since(mark, "សូមប្រើ Session String"))
    expect("/addaccount → OTP login ត្រូវបានបិទ", panel.said_since(mark, "OTP login ត្រូវបានបិទ"))
    expect("/addaccount មិនបង្ហាញ OTP FSM", panel.says_not_since(mark, "កូដ OTP"))

    mark = panel.mark()
    sent_mark = len(panel.session.sent)
    await panel.cb("acc:add")
    expect("acc:add មាន handler ទទួល (answerCallbackQuery ប៉ុណ្ណោះ)",
           "answerCallbackQuery" in panel.session.sent[sent_mark:] and panel.says_not_since(mark, "កូដ OTP"))

    # ៣) /addsession → ការណែនាំ Session String
    mark = panel.mark()
    await add_session()
    expect("/addsession → បង្ហាញការណែនាំ Session String", panel.said_since(mark, "Session String"))
    expect("/addsession → ណែនាំ my.telegram.org", panel.said_since(mark, "my.telegram.org"))
    expect("/addsession → រំលឹកសារ Auto-delete", panel.said_since(mark, "សារនេះនឹងត្រូវលុបភ្លាម"))
    expect("/addsession → រំលឹក Encrypt + Save", panel.said_since(mark, "Encrypt + Save"))
    expect("/addsession → បង្ហាញតំណ Web App", panel.said_since(mark, config.settings.session_web_url))

    # ប៊ូតុង 🌐 ត្រូវជា **URL button** (Telegram បើក browser) មិនមែន callback_data — ៦៤ bytes មិនគ្រប់
    from admin_bot import keyboards as kb
    menu = kb.main_menu(True)
    menu_urls = {b.url for row in menu.inline_keyboard for b in row if b.url}
    menu_cbs = {b.callback_data for row in menu.inline_keyboard for b in row if b.callback_data}
    expect("main_menu → ប៊ូតុង 🌐 ជា URL button ទៅ Web App", config.settings.session_web_url in menu_urls)
    expect("main_menu → ប៊ូតុងផ្សេងនៅជា callback_data (មិនប្តូរ behavior)",
           {"menu:accounts", "acc:addsession", "menu:products", "menu:settings"} <= menu_cbs)
    expect("main_menu → គ្មានប៊ូតុង «Admins» / Add Admin ទៀត",
           not any("Admins" in (b.text or "") or "addadmin" in (b.callback_data or "")
                   for row in menu.inline_keyboard for b in row))
    expect("accounts_menu → មាន URL button ទៅ Web App",
           config.settings.session_web_url in {b.url for row in kb.accounts_menu([]).inline_keyboard
                                               for b in row if b.url})

    mark = panel.mark()
    await panel.cb("acc:howto")
    expect("acc:howto → api_hash មិនដែលវាយតាម chat", panel.said_since(mark, "api_hash មិនដែលវាយតាម chat"))
    expect("acc:howto → បង្ហាញតំណ Web App", panel.said_since(mark, config.settings.session_web_url))
    # មិនទាន់ deploy (URL មិនចាប់ផ្តើមដោយ http) → សារ + ប៊ូតុង 🌐 ត្រូវតែលាក់តំណ
    #  patch ទាំង `config.settings` (keyboards.web_app_row អានពេលហៅ) និង handler របស់ខ្លួន
    no_url = dataclasses.replace(config.settings, session_web_url="off")
    settings_backup = config.settings
    accounts_handlers.settings = no_url
    config.settings = no_url
    mark = panel.mark()
    await panel.cb("acc:howto")
    expect("URL=off → acc:howto លាក់តំណ Web App", not panel.said_since(mark, "🌐"))
    mark = panel.mark()
    await panel.msg("/start")
    expect("URL=off → /start គ្មានប៊ូតុង 🌐", not panel.said_since(mark, "🌐"))
    accounts_handlers.settings = config.settings
    config.settings = settings_backup

    mark = panel.mark()
    await panel.msg("/cancel", user_id=STAFF)
    expect("/cancel បោះបង់ waiting_session", panel.said_since(mark, "បានបោះបង់"))

    # ៤) បដិសេធតាមទ្រង់ទ្រាយ — លុបសារមុន validate ជានិច្ច
    FakeClient.reset()
    mark = panel.mark()
    sent_mark = len(panel.session.sent)
    await add_session()
    await panel.msg("1short-session", user_id=STAFF)
    expect("Session ខ្លី (< 50 តួ) → បដិសេធ", panel.said_since(mark, "Session String ខុសទ្រង់ទ្រាយ"))
    expect("Session ខុសទ្រង់ទ្រាយ → សារត្រូវលុប", "deleteMessage" in panel.session.sent[sent_mark:])
    expect("Session ខុសទ្រង់ទ្រាយ → មិនភ្ជាប់ client", not FakeClient.built)
    mark = panel.mark()
    await panel.msg("/menu", user_id=STAFF)
    expect("Session ខុស → FSM ស្អាត (សារបន្ទាប់មិនត្រូវបានស៊ី)",
           panel.says_not_since(mark, "Session String ខុសទ្រង់ទ្រាយ"))

    mark = panel.mark()
    await add_session()
    await panel.msg("Z" * 200, user_id=STAFF)
    expect("Session មិនចាប់ផ្តើមដោយលេខ → បដិសេធ", panel.said_since(mark, "Session String ខុសទ្រង់ទ្រាយ"))

    # ៥) Session ភ្ជាប់បានតែមិន authorized / ខូច auth key → បដិសេធ + ណែនាំបង្កើតថ្មី
    FakeClient.reset("unauthorized")
    mark = panel.mark()
    await add_session()
    await panel.msg(SESSION_A, user_id=STAFF)
    expect("Session មិន authorized → បដិសេធ", panel.said_since(mark, "មិនត្រឹមត្រូវ ឬផុតកំណត់"))
    expect("Session ខូច → ណែនាំបង្កើតថ្មី (get_session.py)", panel.said_since(mark, "get_session.py"))
    expect("Session ខូច → client ត្រូវ disconnect", FakeClient.last().disconnected)
    expect("Session ខូច → គ្មាន Account row", await fetch_account(LOGIN_PHONE) is None)

    FakeClient.reset("no_me")
    mark = panel.mark()
    await add_session()
    await panel.msg(SESSION_A, user_id=STAFF)
    expect("get_me() ទទេ → បដិសេធដូចគ្នា", panel.said_since(mark, "មិនត្រឹមត្រូវ ឬផុតកំណត់"))

    # ៦) exception ពី Telegram (auth key ត្រូវបាន withdraw) → បដិសេធ ហើយ session មិនរសាត់ចូល log
    #    recorder ត្រូវដកជាបណ្តោះអាសន្ន ព្រោះ ERROR គឺអ្វីដែលករណីនេះ «ចង់បាន»
    root = logging.getLogger()
    root.removeHandler(recorder)
    sink = Recorder()
    root.addHandler(sink)
    FakeClient.reset("auth_revoked")
    mark = panel.mark()
    await add_session()
    await panel.msg(SESSION_A, user_id=STAFF)
    root.removeHandler(sink)
    root.addHandler(recorder)
    expect("Session ខូច (AuthKeyUnregistered) → បដិសេធ + បញ្ជាក់ប្រភេទកំហុស",
           panel.said_since(mark, "❌ បរាជ័យ: AuthKeyUnregisteredError"))
    expect("Session ខូច → គ្មាន row ក្រោយ exception", await fetch_account(LOGIN_PHONE) is None)
    dumped = "\n".join(logging.Formatter("%(message)s").format(record) for record in sink.raw)
    expect("Session String មិនត្រូវ log", SESSION_A not in dumped)
    expect("Session String មិនត្រូវបង្ហាញក្នុង Panel/chat", panel.says_not_since(0, SESSION_A))

    # ៧) api_id/api_hash អានពី .env តែប៉ុណ្ណោះ — ខ្វះ → និន្នាការមុន មិនភ្ជាប់
    saved_settings = config.settings
    config.settings = dataclasses.replace(saved_settings, tg_api_id=0, tg_api_hash="")
    FakeClient.reset()
    mark = panel.mark()
    await add_session()
    await panel.msg(SESSION_A, user_id=STAFF)
    config.settings = saved_settings
    expect(".env ខ្វះ credentials → បដិសេធ + ណែនាំ TG_API_ID", panel.said_since(mark, "TG_API_ID"))
    expect(".env ខ្វះ → គ្មាន client ភ្ជាប់", not FakeClient.built)

    # ៨) Session ត្រឹមត្រូវ → Encrypt + Save DB + hot-reload + បង្ហាញក្នុង /accounts
    fake_manager = FakeManager()
    manager_module._manager = fake_manager
    FakeClient.reset()
    mark = panel.mark()
    sent_mark = len(panel.session.sent)
    await add_session()
    await panel.msg(SESSION_A, user_id=STAFF)
    expect("Session ត្រឹមត្រូវ → ភ្ជាប់រួច", panel.said_since(mark, "✅ ភ្ជាប់រួច"))
    expect("Session String ត្រូវ Auto-delete បន្ទាប់ពីអាន", "deleteMessage" in panel.session.sent[sent_mark:])
    expect("StringSession ទទួល input ដើមតែមួយ", _FakeStringSession.seen == [SESSION_A])
    expect("api_id/api_hash យកពី .env បញ្ជូនទៅ client", FakeClient.last().creds == (API_ID_ENV, API_HASH_ENV))
    logged = await fetch_account(LOGIN_PHONE)
    expect("Account row ត្រូវបង្កើត", logged is not None)
    logged_id = logged.id if logged else None
    if logged is not None:
        expect("គណនីជាប់នឹង staff (owner_admin_id)", logged.owner_admin_id == STAFF)
        expect("session ចូល DB ជា ciphertext (Encrypt)",
               (logged.session_encrypted or "").startswith("gAAAAA") and SESSION_A not in logged.session_encrypted)
        expect("decrypt ត្រឡប់ session ដើម", session_store.decrypt(logged.session_encrypted) == SESSION_A)
        expect("addsession មិនសរសេរ api_id/api_hash ចុះ row",
               not (logged.tg_api_id_encrypted or logged.tg_api_hash_encrypted))
    expect("api_hash មិនដែលបង្ហាញក្នុង chat", panel.says_not_since(0, API_HASH_ENV))
    expect("client ត្រូវ disconnect ក្រោយ save", FakeClient.last().disconnected)
    expect("បន្ទាប់ពី Save → userbot reconcile ចាប់ផ្តើមគណនី", fake_manager.reconciled == 1)
    mark = panel.mark()
    await panel.msg("/accounts", user_id=STAFF)
    expect("បន្ទាប់ពី Save → Account បង្ហាញក្នុង /accounts (លេខបិទកណ្តាល)", panel.said_since(mark, MASKED_PHONE))

    # ៩) លេខដើម + session ថ្មី → upsert (មិនបង្កើត row ស្ទួន)
    FakeClient.reset()
    mark = panel.mark()
    await add_session()
    await panel.msg(SESSION_B, user_id=STAFF)
    expect("Session ថ្មីលើលេខដើម → ភ្ជាប់រួច (upsert)", panel.said_since(mark, "✅ ភ្ជាប់រួច"))
    again = await fetch_account(LOGIN_PHONE)
    expect("upsert → រក្សា account id ដើម", again is not None and again.id == logged_id)
    expect("upsert → គ្មាន row ស្ទួន", await account_count(LOGIN_PHONE) == 1)
    expect("upsert → ciphertext ថ្មីជំនួសដើម",
           again is not None and session_store.decrypt(again.session_encrypted) == SESSION_B)

    # ១០) លេខជាគណនីរបស់ admin ផ្សេង → បដិសេធ (IDOR) មិនប៉ះ row
    reconciled_before = fake_manager.reconciled
    FakeClient.reset()
    mark = panel.mark()
    await add_session(OWNER)
    await panel.msg(SESSION_A, user_id=OWNER)
    expect("លេខជាគណនី admin ផ្សេង → បដិសេធ", panel.said_since(mark, "admin ផ្សេងហើយ"))
    expect("IDOR → client ត្រូវ disconnect", FakeClient.last().disconnected)
    expect("IDOR → session មិនត្រូវ replace",
           (await fetch_account(LOGIN_PHONE)).session_encrypted == (again.session_encrypted if again else None))
    expect("IDOR បរាជ័យ → មិន reconcile ថ្មី", fake_manager.reconciled == reconciled_before)
    manager_module._manager = None

    # ១១) Multi-user — គ្រប់ tenant ឃើញតែគណនីខ្លួន រួមទាំង Owner (ទិន្នន័យលម្អិតមិន cross-tenant)
    STAFF2 = 777000457
    async with db_session() as session:
        await crud.add_admin(session, STAFF2, "Staff SMOKE 2")
        await session.commit()
    mark = panel.mark()
    await panel.msg("/accounts", user_id=STAFF2)
    expect("Staff ទី២ → /accounts មិនបង្ហាញគណនីរបស់ Staff ទី១", not panel.said_since(mark, MASKED_PHONE))
    mark = panel.mark()
    await panel.msg("/accounts", user_id=OWNER)
    expect("Owner → /accounts មិនឃើញគណនីរបស់ Staff (IDOR/ទិន្នន័យលម្អិត)",
           not panel.said_since(mark, MASKED_PHONE))
    expect("គ្រប់ path → លេខទូរស័ព្ទពេញលេញមិនដែលចេញក្នុង chat", panel.says_not_since(0, LOGIN_PHONE))

    expect("គ្រប់ flow → គ្មានសារ «កូដ OTP» សោះ", panel.says_not_since(0, "កូដ OTP"))

    print("— កិច្ចស្វ័យប្រវត្តិ + ទិន្នន័យ —")
    from services.reports import build_report
    from services.scheduler import auto_backup, daily_report, low_stock_watch

    async with db_session() as session:
        report = await build_report(session, "today")
    if "របាយការណ៍" not in report:
        panel.errors.append("✗ build_report មិនបានបង្កើតអត្ថបទ")
    await daily_report(bot)
    await low_stock_watch(bot)
    await auto_backup()

    async with db_session() as session:
        product = await crud.get_product(session, product_id) if product_id else None
        remaining = await crud.stock_remaining(session, product_id) if product_id else -1
        sold = await crud.sold_stock_count(session, product_id) if product_id else -1
        order = await crud.get_order(session, order_id) if order_id else None
        customer = await crud.get_customer_by_telegram(session, CUSTOMER_TG)
        staff = await crud.is_staff(session, 777000123)

    checks = [
        (product is not None and "ហ្គេម" in (product.category or "") and (product.product_code or "").startswith("GAME-"), f"ផលិតផល mirror category ត្រូវ ({product.category if product else '—'} / {product.product_code if product else '—'})"),
        (remaining == 3 and sold == 1, f"Stock ត្រូវកាត់ ១ (សល់={remaining} លក់={sold})"),
        (order is not None and order.status == "delivered", f"Order → delivered ({order.status if order else '—'})"),
        (customer is not None and customer.total_orders == 1, "Customer រាប់ Order បាន ១"),
        (staff, "អ្នកប្រើថ្មី /start → auto-register ក្នុង DB"),
    ]
    for ok, label in checks:
        if not ok:
            panel.errors.append(f"✗ {label}")

    panel.errors.extend(f"✗ ERROR log: {line}" for line in recorder.records)
    await bot.session.close()

    print(f"\nសាកល្បង {panel.checked} ជំហាន · API calls {len(bot.session.sent)} · អត្ថបទ {len(bot.session.texts)}")
    if panel.errors:
        print("\nបរាជ័យ:")
        for line in panel.errors:
            print("  " + line)
        return 1
    print("✅ គ្រប់ជំហានដំណើរការរលូន")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
