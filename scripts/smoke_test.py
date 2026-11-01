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

    async def feed(self, kind: str, label: str, *, expect_reply: bool = True, user_id: int = OWNER, **fields):
        before = len(self.session.sent)
        update = Update.model_validate(_payload(kind, user_id, **fields), context={"bot": self.bot})
        result = await self.dispatcher.feed_update(self.bot, update)

        self.checked += 1
        if result is UNHANDLED:
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

    print("— QR ស្វ័យប្រវត្តិ —")
    await panel.cb("qr:newgen")
    await panel.msg("ABA SMOKE")
    await panel.msg("aba")
    await panel.msg("https://pay.aba.example/smoke")
    async with db_session() as session:
        qrs = await crud.list_qrcodes(session)
        qr_id = qrs[0].id if qrs else None
    if qr_id is None:
        panel.errors.append("✗ រកមិនឃើញ QR ក្នុង DB")
    else:
        await panel.cb(f"qr:default:{qr_id}")
        await panel.cb(f"qr:view:{qr_id}")
        await panel.cb(f"qr:link:{qr_id}")

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
