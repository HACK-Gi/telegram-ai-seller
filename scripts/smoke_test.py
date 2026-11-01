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
    return {"id": user_id, "is_bot": user_id == OWNER, "first_name": "Owner" if user_id == OWNER else "Stranger"}


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

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(f"{record.name}: {record.getMessage()}")


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


async def wait_for_text_since(panel: Panel, mark: int, fragment: str, timeout: float = 3.0) -> bool:
    """រង់ចាំសារថ្មី (ចាប់ពី `mark`) — login រត់ក្នុង Task ដាច់ពី handler។"""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if any(fragment in item for item in panel.session.texts[mark:]):
            return True
        await asyncio.sleep(0.02)
    return any(fragment in item for item in panel.session.texts[mark:])


# ---------- Fake Telethon client — chat login ដោយគ្មានបណ្តាញ ----------
class SessionPasswordNeededError(Exception):
    """ឈ្មោះ class ត្រូវដូច Telethon — chat_login dispatch តាម `type(exc).__name__`។"""


class PhoneCodeInvalidError(Exception):
    pass


class _FakeSession:
    def save(self) -> str:
        return "1FAKESESSION" + "X" * 120


class _FakeSent:
    phone_code_hash = "FAKE-CODE-HASH"


class _FakeMe:
    id = 777000999
    username = "smoke_login"
    first_name = "Smoke"
    last_name = "Login"


class FakeClient:
    def __init__(self, *, need_2fa: bool = False, reject_code: str = "") -> None:
        self.session = _FakeSession()
        self.need_2fa = need_2fa
        self.reject_code = reject_code
        self.codes: list[str] = []
        self.passwords: list[str] = []
        self.disconnected = False

    async def connect(self) -> bool:
        return True

    async def send_code_request(self, phone: str) -> _FakeSent:
        return _FakeSent()

    async def sign_in(self, *, phone=None, code=None, phone_code_hash=None, password=None):
        if code is not None:
            self.codes.append(code)
            if code == self.reject_code:
                raise PhoneCodeInvalidError("invalid")
            if self.need_2fa:
                raise SessionPasswordNeededError("2fa")
            return True
        self.passwords.append(password)
        return True

    async def get_me(self) -> _FakeMe:
        return _FakeMe()

    async def is_user_authorized(self) -> bool:
        return True

    async def disconnect(self) -> None:
        self.disconnected = True


class FakeClientFactory:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.instances: list[FakeClient] = []
        self.creds: list[tuple[int, str]] = []

    def __call__(self, device_index: int, api_id: int, api_hash: str) -> FakeClient:
        self.creds.append((api_id, api_hash))
        client = FakeClient(**self.kwargs)
        self.instances.append(client)
        return client

    @property
    def last(self) -> FakeClient:
        return self.instances[-1]


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
    for name in ("products", "qr", "prompt", "orders", "customers", "accounts", "analytics", "settings", "admins"):
        await panel.cb(f"menu:{name}")

    print("— បង្កើតផលិតផល + Stock —")
    await panel.cb("prod:add")
    await panel.msg("Game Key SMOKE")
    await panel.msg("-key សម្រាប់សាកល្បង")
    await panel.msg("4.99")
    await panel.msg("ហ្គេម")
    await panel.msg("skip")
    async with db_session() as session:
        products, _total = await crud.list_products(session, page=1, per_page=10)
        product_id = next((item.id for item in products if item.name == "Game Key SMOKE"), None)
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
        async with db_session() as session:
            cat_rows = await crud.list_all_categories(session)
            game_cat = next(c for c in cat_rows if c.code == "game_acc")
            game_cat_id = game_cat.id
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
        smoke_cat = await crud.get_category_by_code(session, "smoke_cat")
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
        if await crud.get_category(session, smoke_cat_id) is not None:
            panel.errors.append("✗ លុបប្រភេទមិនបាន")
    await panel.cb(f"cat:askdel:{game_cat_id}")
    await panel.cb(f"cat:del:{game_cat_id}")  # blocked — មានផលិតផល
    async with db_session() as session:
        if await crud.get_category(session, game_cat_id) is None:
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
    async with db_session() as session:
        account = await crud.create_account(session, "+85512999000", "SMOKE-NOT-A-REAL-SESSION")
        account_id = account.id
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
    await panel.msg("/addadmin 777000123 Admin SMOKE")
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

    mark = panel.mark()
    await panel.cb("menu:categories", user_id=STAFF)
    expect("staff ឃើញប្រភេទដែលមានផលិតផលខ្លួន", panel.said_since(mark, "គណនីហ្គេម"))
    expect("staff មិនឃើញប្រភេទទទេ (ខោអាវ)", panel.says_not_since(mark, "ខោអាវ"))

    mark = panel.mark()
    await panel.cb("cat:add", user_id=STAFF, unhandled_ok=True)
    expect("staff បន័ែមប្រភេទមិនបាន", panel.said_since(mark, OWNER_ONLY_TEXT))
    async with db_session() as session:
        expect("cat:add មិនតັ້ FSM របស់ staff", await crud.get_category_by_code(session, "staff_try") is None)

    async with db_session() as session:
        before = await crud.get_category(session, game_cat_id)
        was_active = bool(before and before.is_active)
    mark = panel.mark()
    await panel.cb(f"cat:toggle:{game_cat_id}", user_id=STAFF, unhandled_ok=True)
    expect("staff បិទ/បើកប្រភេទមិនបាន", panel.said_since(mark, OWNER_ONLY_TEXT))
    async with db_session() as session:
        after = await crud.get_category(session, game_cat_id)
        expect("cat:toggle មិនប៉ះ is_active", bool(after and after.is_active) == was_active)

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
    expect("staff ឃើញគណនីខ្លួន", panel.said_since(mark, STAFF_PHONE))
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
    expect("staff /pauseall មិនបាន", panel.said_since(mark, "គត់ Owner"))
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
    expect("Owner ឃើញផលិតផល staff", panel.said_since(mark, "Staff Key ONLY"))

    print("— Chat Login — /addaccount + OTP auto-delete + 2FA + /cancel —")
    from sqlalchemy import select as _select

    from database.models import Account as _Account
    from userbot import chat_login, session_store

    async def fetch_account(phone: str):
        async with db_session() as session:
            return await session.scalar(_select(_Account).where(_Account.phone == phone))

    def use_coordinator(**kwargs) -> FakeClientFactory:
        factory = FakeClientFactory(**kwargs)
        chat_login.reset_coordinator()
        chat_login._coordinator = chat_login.LoginCoordinator(client_factory=factory)  # noqa: SLF001
        return factory

    # តម្លៃដាច់គេ — បើជាលេខធម្មតា វានឹងឃើញ «លេច» ក្នុងឧទាហរណ៍/លេខផ្សេង ហើយការតេស្តក្លាយជាកុហក
    API_ID = "3141592"
    API_HASH = "0123456789abcdef0123456789abcdef"

    async def start_login(phone: str) -> None:
        """`/addaccount` → api_id → api_hash ដល់ចំនុចដែល Bot ផ្ញើ OTP។"""
        await panel.msg(f"/addaccount {phone}", user_id=STAFF, expect_reply=False)
        await panel.msg(API_ID, user_id=STAFF, expect_reply=False)
        await panel.msg(API_HASH, user_id=STAFF, expect_reply=False)

    mark = panel.mark()
    await panel.msg("/addaccount 12abc", user_id=STAFF)
    expect("លេខខុស → បដិសេធ", panel.said_since(mark, "លេខទូរស័ព្ទខុសទ្រង់ទ្រាយ"))

    # api_id / api_hash — validation + auto-delete
    factory = use_coordinator()
    mark = panel.mark()
    phone_mark = len(panel.session.sent)
    await panel.msg("/addaccount +85512777009", user_id=STAFF, expect_reply=False)
    expect("សារលេខទូរស័ព្ទត្រូវលុប", "deleteMessage" in panel.session.sent[phone_mark:])
    expect("ណែនាំទៅ my.telegram.org", await wait_for_text_since(panel, mark, "my.telegram.org"))
    await panel.msg("12ab", user_id=STAFF, expect_reply=False)
    expect("api_id ខុស → បដិសេធ", panel.said_since(mark, "api_id មិនត្រឹមត្រូវ"))
    api_mark = len(panel.session.sent)
    await panel.msg(API_ID, user_id=STAFF, expect_reply=False)
    expect("សារ api_id ត្រូវលុប", "deleteMessage" in panel.session.sent[api_mark:])
    expect("សួរ api_hash", panel.said_since(mark, "App api_hash"))
    await panel.msg("abcd", user_id=STAFF, expect_reply=False)
    expect("api_hash ខុស → បដិសេធ", panel.said_since(mark, "api_hash មិនត្រឹមត្រូវ"))
    expect("គ្មាន OTP មុន api_hash ត្រឹមត្រូវ", panel.says_not_since(mark, "កូដ OTP"))
    await panel.msg("/cancel", user_id=STAFF)
    expect("/cancel ពេលនៅ api_hash → គ្មាន pending", not chat_login.get_coordinator().has_pending(STAFF, STAFF))

    factory = use_coordinator()
    login_phone = "+85512777000"
    otp = "741852"
    mark = panel.mark()
    secrets_mark = len(panel.session.sent)
    await start_login(login_phone)
    expect("OTP ត្រូវសួរ", await wait_for_text_since(panel, mark, "កូដ OTP"))
    expect("api_id/api_hash ផ្ញើទៅ client", factory.creds == [(int(API_ID), API_HASH)])
    deleted = [item for item in panel.session.sent[secrets_mark:] if "deleteMessage" in item]
    expect("សារ phone/api_id/api_hash ត្រូវលុប ៣", len(deleted) >= 3)
    expect("coordinator មាន pending", chat_login.get_coordinator().has_pending(STAFF, STAFF))
    api_mark = len(panel.session.sent)
    await panel.msg(otp, user_id=STAFF, expect_reply=False)
    expect("សារ OTP ត្រូវលុបភ្លាម", "deleteMessage" in panel.session.sent[api_mark:])
    expect("OTP មិនដែលចេញជាសារ Bot", panel.says_not_since(0, otp))
    done = await wait_for_text_since(panel, mark, "ភ្ជាប់រួច")
    expect("login ជោគជ័យ → ជូនដំណឹង", done)
    logged = await fetch_account(login_phone)
    expect("Account row ត្រូវបង្កើត", logged is not None)
    if logged is not None:
        expect("គណនីជាប់នឹង staff (owner_admin_id)", logged.owner_admin_id == STAFF)
        expect("session ក្នុង DB ជា ciphertext", "FAKESESSION" not in (logged.session_encrypted or ""))
        expect("decrypt ត្រឡប់ session ដើម", session_store.decrypt(logged.session_encrypted).startswith("1FAKESESSION"))
        from userbot import credentials as _credentials

        expect("api_id ក្នុង DB ជា ciphertext", API_ID not in (logged.tg_api_id_encrypted or ""))
        expect("api_hash ក្នុង DB ជា ciphertext", API_HASH not in (logged.tg_api_hash_encrypted or ""))
        expect(
            "decrypt creds ត្រឡប់ api_id/api_hash ដើម",
            _credentials.stored_credentials(logged) == (int(API_ID), API_HASH),
        )
    expect("api_hash មិនដែលចេញជាសារ Bot", panel.says_not_since(mark, API_HASH))
    expect("api_id មិនដែលចេញជាសារ Bot", panel.says_not_since(mark, API_ID))
    expect("session string មិនដែលចេញ chat", panel.says_not_since(0, "FAKESESSION"))
    expect("FakeClient ត្រូវ disconnect", factory.last.disconnected)

    factory = use_coordinator(need_2fa=True)
    password = "smoke-2fa-secret"
    mark = panel.mark()
    await start_login(login_phone)
    await wait_for_text_since(panel, mark, "កូដ OTP")
    await panel.msg(otp, user_id=STAFF, expect_reply=False)
    expect("2FA ត្រូវសួរ", await wait_for_text_since(panel, mark, "ផ្ញើពាក្យសម្ងាត់ Cloud"))
    api_mark = len(panel.session.sent)
    await panel.msg(password, user_id=STAFF, expect_reply=False)
    expect("សារ 2FA ត្រូវលុបភ្លាម", "deleteMessage" in panel.session.sent[api_mark:])
    expect("2FA មិនដែលចេញជាសារ Bot", panel.says_not_since(0, password))
    expect("login 2FA ជោគជ័យ", await wait_for_text_since(panel, mark, "ភ្ជាប់រួច"))
    expect("password ផ្ញើទៅ client", factory.last.passwords == [password])

    factory = use_coordinator(reject_code="000000")
    mark = panel.mark()
    await start_login("+85512777001")
    await wait_for_text_since(panel, mark, "កូដ OTP")
    for attempt in range(3):
        await panel.msg("000000", user_id=STAFF, expect_reply=False)
        if attempt < 2:
            await wait_for_text_since(panel, mark, "កូដមុនខុស")
    expect("OTP ខុស ៣ ដង → បញ្ចប់", await wait_for_text_since(panel, mark, "កូដ OTP ខុស ៣ ដង"))
    expect("គ្មាន pending ក្រោយបរាជ័យ", not chat_login.get_coordinator().has_pending(STAFF, STAFF))
    expect("login បរាជ័យ → គ្មាន orphan row", await fetch_account("+85512777001") is None)

    factory = use_coordinator()
    mark = panel.mark()
    await start_login("+85512777002")
    await wait_for_text_since(panel, mark, "កូដ OTP")
    expect("pending មុន /cancel", chat_login.get_coordinator().has_pending(STAFF, STAFF))
    mark = panel.mark()
    await panel.msg("/cancel", user_id=STAFF)
    expect("/cancel បោះបង់ login", panel.said_since(mark, "បានបោះបង់ការ login"))
    expect("គ្មាន pending ក្រោយ /cancel", not chat_login.get_coordinator().has_pending(STAFF, STAFF))
    expect("client ត្រូវ disconnect (/cancel)", factory.last.disconnected)
    expect("/cancel → គ្មាន Account row", await fetch_account("+85512777002") is None)

    # OTP timeout — អតិថិជនមិនវាយកូដ → coordinator បញ្ចប់ខ្លួនឯង (កុំឱ្យ pending ជាប់)
    factory = use_coordinator()
    saved_timeout = chat_login.CODE_TIMEOUT
    chat_login.CODE_TIMEOUT = 0.2
    mark = panel.mark()
    await start_login("+85512777003")
    expect("អត់ឆ្លើយក្នុង CODE_TIMEOUT → បញ្ចប់", await wait_for_text_since(panel, mark, "មិនឃើញកូដ OTP"))
    chat_login.CODE_TIMEOUT = saved_timeout
    expect("គ្មាន pending ក្រោយ timeout", not chat_login.get_coordinator().has_pending(STAFF, STAFF))
    expect("timeout → គ្មាន orphan row", await fetch_account("+85512777003") is None)
    expect("timeout → client ត្រូវ disconnect", factory.last.disconnected)
    await chat_login.get_coordinator().shutdown()

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
        (staff, "/addadmin បន្ថែម staff ក្នុង DB"),
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
