"""Catalog — សម្ភារៈ-inline សម្រាប់អតិថិជន (buttons) លើគណនី userbot។

គោលការណ៍៖
* គ្មាន AI ក្នុង button flow ទេ — អតិថិជនចុច → កែសារដដែល (edit) មិនបាញ់សារថ្មី
* ការផ្ញើចេញទាំងអស់ (welcome/QR) ឆ្លងកាត់ Outbox របស់គណនី sticky តែមួយ —
  រាប់ budget, គោរព FloodWait, human delay ដូចសារ AI
* Sticky hard-rule៖ គ្មាន binding ឬ conflict → មិនដំណើរការ + ជូនដំណឹងម្ចាស់
* បន្ទាត់ `ub:*` ជាកម្មសិទ្ធិរបស់ module នេះតែមួយ
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from telethon import Button

from database import crud
from database.models import Account
from database.session import db_session
from helpers import esc, money
from sqlalchemy import select
from userbot import limits
from userbot.outbox import PRIORITY_REPLY, Outbox, OutboxItem, PeerRef

log = logging.getLogger("userbot.catalog")

WELCOME_TEXT = (
    "សួស្តីបង 🙏 សូមស្វាគមន៍មកកាន់ហាងរបស់យើង!\n\n"
    "ចុចប្រភេទខាងក្រោមដើម្បីមើលផលិតផល ឬវាយសួរតាមអក្សរបានទាំងស្រុង"
)
VOICE_REJECT = (
    "🙏 សូមអភ័យទោសបង! ខ្ញុំមិនអាចស្តាប់សំឡេងបានទេបង\n"
    "សូមវាយជាអក្សរ ឬផ្ញើរូបភាព (slip ក៏បាន) ជំនួសវិញ 🙏\n"
    "បងអាចវាយ «menu» ដើម្បីមើលផលិតផលទាំងអស់"
)
CATALOG_KEYWORDS = frozenset({"menu", "មេនុ", "សម្ភារៈ", "catalog", "list", "products", "ផលិតផល"})
MAX_BUTTON_ROWS = 10


class Catalog:
    def __init__(
        self,
        account_id: int,
        *,
        outbox: Outbox,
        notify: Callable[[str], Awaitable[None]] | None = None,
        is_staff: Callable[[int], bool] = lambda user_id: False,
    ) -> None:
        self.account_id = account_id
        self.outbox = outbox
        self._notify = notify or (lambda text: asyncio.sleep(0))
        self._is_staff = is_staff

    # ---------- ជំនួយ ----------
    @staticmethod
    def _rows(pairs: list[list[tuple[str, str]]]) -> Any:
        return [
            [Button.inline(text[:64], data=data.encode("utf-8")[:64]) for text, data in row]
            for row in pairs[:MAX_BUTTON_ROWS]
        ]

    async def _visible_products(self, session) -> list:
        return await crud.products_for_account(session, self.account_id)

    # ---------- សម្ភារៈ (text + rows) ----------
    async def categories_text(self) -> tuple[str, list[list[tuple[str, str]]]]:
        async with db_session() as session:
            products = await self._visible_products(session)
            categories = await crud.list_all_categories(session, active_only=True)
        in_scope: dict[int, int] = {}
        for product in products:
            if product.category_id is not None:
                in_scope[product.category_id] = in_scope.get(product.category_id, 0) + 1
        rows: list[list[tuple[str, str]]] = []
        lines = ["🛍 <b>សម្ភារៈទាំងអស់</b> — ជ្រើសរើសប្រភេទបង:", ""]
        shown = 0
        for category in categories:
            count = in_scope.get(category.id, 0)
            if count == 0:
                continue
            rows.append([(f"{category.icon} {category.name_kh} ({count})", f"ub:cat:{category.id}")])
            lines.append(f"{category.icon} {category.name_kh} — {count} មុខ")
            shown += 1
        if shown == 0:
            fallback = sum(1 for product in products if product.is_active)
            rows.append([(f"📦 ទូទៅ ({fallback})", "ub:cat:0")])
            lines.append(f"📦 ទូទៅ — {fallback} មុខ")
        rows.append([("🔍 ស្វែងរក", "ub:search"), ("👤 ទំនាក់ទំនងម្ចាស់", "ub:contact")])
        return "\n".join(lines), rows

    async def category_products_text(self, category_id: int) -> tuple[str, list[list[tuple[str, str]]]]:
        async with db_session() as session:
            products = await self._visible_products(session)
            category = await crud.get_category(session, category_id) if category_id else None
        if category_id and category is None:
            return "⚠️ ប្រភេទនេះលែងមានទេបង — សូមជ្រើសរើសថ្មី", [[("📦 ប្រភេទទាំងអស់", "ub:cats")]]
        if category is not None:
            pool = [
                p
                for p in products
                if p.is_active and (p.category_id == category.id or (category.code == "gen" and p.category_id is None))
            ]
            header = f"{category.icon} <b>{esc(category.name_kh)}</b> — {len(pool)} មុខ\n"
        else:
            pool = [p for p in products if p.is_active]
            header = "📦 <b>ទូទៅ</b> — រាល់ផលិតផល\n"
        rows: list[list[tuple[str, str]]] = []
        if not pool:
            header += "\n<i>មិនទាន់មានផលិតផលក្នុងប្រភេទនេះទេ</i>"
        for product in pool[:MAX_BUTTON_ROWS]:
            rows.append([(f"{esc(product.name)} · {money(product.final_price)}", f"ub:prod:{product.id}")])
        if len(pool) > MAX_BUTTON_ROWS:
            header += f"<i>(បង្ហាញ {MAX_BUTTON_ROWS} មុខដំបូង — សួរបន្ថែមតាមអក្សរបង)</i>\n"
        rows.append([("⬅️ ប្រភេទទាំងអស់", "ub:cats"), ("🔍 ស្វែងរក", "ub:search")])
        return header, rows

    async def product_card_text(self, product_id: int) -> tuple[str, list[list[tuple[str, str]]]]:
        async with db_session() as session:
            product = await crud.get_product(session, product_id)
            products = {p.id for p in await self._visible_products(session)}
            available = await crud.available_stock(session, product_id) if product else 0
        if product is None or product.id not in products or not product.is_active:
            return "⚠️ ផលិតផលនេះមិនត្រូវបានលក់នៅលើគណនីនេះទេបង", [[("📦 ប្រភេទទាំងអស់", "ub:cats")]]
        stock_line = f"🟢 សល់ <b>{available}</b>" if available else "🔴 ស្តុកអស់ — សូមទាក់ទងម្ចាស់"
        text = (
            f"📦 <b>{esc(product.name)}</b>"
            + (f"  <code>{esc(product.product_code)}</code>" if product.product_code else "")
            + "\n"
            + f"💰 <b>{money(product.final_price)}</b>"
            + (f" <s>{money(product.price)}</s> (-{product.discount_percent}%)" if product.discount_percent else "")
            + f"\n📝 {esc(product.description) if product.description else '—'}"
            + f"\n{stock_line}"
        )
        rows: list[list[tuple[str, str]]] = []
        if available:
            rows.append([(f"🛒 ទិញឥឡូវ {money(product.final_price)}", f"ub:buy:{product.id}")])
        rows.append([("⬅️ ប្រភេទទាំងអស់", "ub:cats")])
        return text, rows

    async def contact_text(self) -> tuple[str, list[list[tuple[str, str]]]]:
        async with db_session() as session:
            username = (await crud.get_setting(session, "owner_username")).strip()
            phone = await session.scalar(select(Account.phone).where(Account.is_primary.is_(True)))
        lines = ["👤 <b>ទំនាក់ទំនងម្ចាស់ហាង</b>"]
        if username:
            lines.append(f"· @{esc(username)}")
        if phone:
            lines.append(f"· គណនី Telegram: <code>{esc(phone)}</code>")
        if not username and not phone:
            lines.append("· សរសេរមកគណនីនេះ ម្ចាស់នឹងឆ្លើយតបឆាប់ៗខ្លាំង")
        lines.append("· បើជាប់ចំណុចណា សរសេរ «ជួយ» មកបង 🙏")
        return "\n".join(lines), [[("⬅️ ប្រភេទទាំងអស់", "ub:cats")]]

    # ---------- ផ្លូវចម្បងសម្រាប់ button click ----------
    async def handle(self, peer_id: int, data: str) -> tuple[str, str, list[list[tuple[str, str]]] | None]:
        """(alert, new_text, new_rows) — គ្មាន edit សម្រាប់ purchase (ផ្ញើសារថ្មី)។"""
        parts = data.split(":")
        action = parts[1] if len(parts) > 1 else ""
        if action == "cats":
            text, rows = await self.categories_text()
            return "", text, rows
        if action == "cat":
            cid = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
            text, rows = await self.category_products_text(cid)
            return "", text, rows
        if action == "prod":
            pid = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
            text, rows = await self.product_card_text(pid)
            return "", text, rows
        if action == "search":
            return (
                "",
                "🔍 វាយអ្វីដែលបងចង់បានតាមអក្សរបង ហើយខ្ញុំជួយរកបង 🙏\nឧ. «VIP» ឬ «AI»",
                [[("⬅️ ប្រភេទទាំងអស់", "ub:cats")]],
            )
        if action == "contact":
            text, rows = await self.contact_text()
            return "", text, rows
        if action == "buy":
            pid = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
            alert = await self.handle_buy(peer_id, pid)
            return alert, "", None
        return "⚠️ ម៉ឺនុនេះផុតកំណត់ — សូមចុច «menu» ម្តងទៀត", "", None

    # ---------- ទិញ: reserve + order + QR ----------
    async def handle_buy(self, peer_id: int, product_id: int) -> str:
        async with db_session() as session:
            bind = await crud.set_customer_account(session, peer_id, self.account_id)
            if bind != "already":
                await self._notify_owner(
                    f"⚠️ ការទិញត្រូវបានរាំង (ស្ថានភាព sticky «{bind}») សម្រាប់អតិថិជន {peer_id} — ច្បាប់ sticky។"
                )
                return "⚠️ ខ្ញុំមិនអាចបញ្ជាទិញពីគណនីនេះបានទេ — សូមសរសេរមកគណនីដែលបងធ្លាប់សរសេរ"
            products = {p.id: p for p in await self._visible_products(session)}
            product = products.get(product_id)
            if product is None or not product.is_active:
                return "⚠️ ផលិតផលនេះលែងលក់ទេបង"
            order = await crud.create_order(
                session,
                customer_id=peer_id,
                product_id=product.id,
                product_name=product.name,
                price=product.final_price,
                quantity=1,
                account_id=self.account_id,
            )
            reserved = await crud.reserve_stock(session, product.id, 1, peer_id, order_id=order.id)
            if not reserved:
                await crud.cancel_order(session, order.id)
                return "🔴 ស្តុកអស់បណ្តោះអាសន្ន — សូមសរសេរប្រាប់ខ្ញុំ ឬមើលផលិតផលផ្សេងបង 🙏"
            qr = await crud.best_qrcode(session, product.id)
            total = money(product.final_price)
            customer = await crud.get_customer_by_telegram(session, peer_id)
            access_hash = customer.access_hash if customer else None
            order_id = order.id
            name = product.name

        caption = (
            f"🛒 បញ្ជាទិញ <code>#{order_id}</code> — {name}\n"
            f"💰 សរុប: <b>{total}</b>\n\n"
            "1️⃣ បង់ប្រាក់តាម QR នេះ\n"
            "2️⃣ ផ្ញើ <b>រូបភាព slip</b> មកក្នុង chat នេះ\n"
            "3️⃣ រង់ចាំម្ចាស់ផ្ទៀងផ្ទាត់ → Code ត្រូវប្រគល់ 🙏\n"
            "<i>ស្តុកត្រូវបានកក់សម្រាប់បញ្ជានេះ (reserve)</i>"
        )
        file_path = qr.image_path if qr and qr.image_path and Path(qr.image_path).exists() else None
        if file_path is None and qr and qr.account_info:
            caption += f"\n🏦 {qr.account_info}"
        self.outbox.enqueue(
            OutboxItem(
                priority=PRIORITY_REPLY,
                seq=0,
                kind=limits.KIND_AI_REPLY,
                peer=PeerRef(peer_id, access_hash),
                text=caption,
                file_path=file_path,
                # ចៀសវាង order_id — Outbox ចាត់ទុក order_id = «code delivered» → mark_code_sent
            )
        )
        await self._notify_owner(
            f"🛒 ការបញ្ជាទិញថ្មី #{order_id} — {name} ({total})\n"
            f"អតិថិជន: <code>{peer_id}</code> · គណនី #{self.account_id} · ស្តុកកក់រួច"
        )
        return ""

    async def _notify_owner(self, text: str) -> None:
        try:
            await self._notify(text)
        except Exception:  # noqa: BLE001
            log.warning("catalog notify មិនបាន")

    # ---------- ទំនាក់ទំនង Telethon ----------
    async def on_callback(self, event) -> None:
        try:
            data = event.data.decode("utf-8", "replace")
            if not data.startswith("ub:"):
                await event.answer()
                return
            peer_id = event.sender_id
            if peer_id is None:
                await event.answer("⚠️ មិនឃើញអ្នកប្រើ", cache_time=1)
                return
            if self._is_staff(peer_id):
                await event.answer("ម៉ឺនុសម្រាប់អតិថិជនប៉ុណ្ណោះ 🙂", cache_time=1)
                return
            alert, text, rows = await self.handle(peer_id, data)
            if rows is not None:
                if event.message is not None:
                    await event.message.edit(text, buttons=self._rows(rows), parse_mode=None)
                await event.answer("", cache_time=1)
            else:
                await event.answer(alert, cache_time=5)
        except Exception:  # noqa: BLE001
            log.exception("catalog callback កំហុសគណនី %s", self.account_id)
            try:
                await event.answer("⚠️ មានបញ្ហាបន្តិច — សាកល្បងម្តងទៀត", cache_time=5)
            except Exception:  # noqa: BLE001
                pass

    # ---------- Welcome / keyword ----------
    async def _send_menu(self, peer_id: int, access_hash: int | None, header: str) -> None:
        text, rows = await self.categories_text()
        self.outbox.enqueue(
            OutboxItem(
                priority=PRIORITY_REPLY,
                seq=0,
                kind=limits.KIND_AI_REPLY,
                peer=PeerRef(peer_id, access_hash),
                text=(header + "\n\n" + text) if header else text,
                buttons=self._rows(rows),
                no_log=True,
            )
        )

    async def send_welcome(self, peer_id: int, access_hash: int | None = None) -> None:
        await self._send_menu(peer_id, access_hash, WELCOME_TEXT)

    async def send_catalog(self, peer_id: int, access_hash: int | None = None) -> None:
        await self._send_menu(peer_id, access_hash, "")
