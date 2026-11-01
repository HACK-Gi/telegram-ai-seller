"""Seller — logic ឆ្លើយតប Inbound ក្នុងមួយគណនី (Sticky ឥតខ្ចោះ)។

ច្បាប់ Telegram ដែលមិនអាចរំលងបាន៖ អតិថិជនសរសេរមក A → មានតែ A ទេដែលតបបាន។
កូដរាំង ៣ ជាន់៖
1. ការ bind ត្រូវកំណត់តែម្តង (`crud.set_customer_account`) — conflict = មិនតប + ជូនដំណឹងម្ចាស់
2. គ្រប់ការផ្ញើចេញឆ្លងកាត់ Outbox របស់គណនីនេះតែមួយ (គ្មាន path អនុញ្ញាត cross-account)
3. គ្មាន កន្លែងណាបង្កើត peer ថ្មី — គ្រាន់តែឆ្លើយអ្នកដែលសរសេរមកមុន

Off-hours៖ តប auto-reply ពី គណនីដដែល (dedupe 1×/ថ្ងៃ/អតិថិជន) ហើយមិនហៅ AI។
Debounce៖ 3 វិនាទី (Coalescer) — batch មួយ = AI call មួយ។
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import timedelta

from ai_engine import get_engine
from ai_engine.base import AIError, Turn
from ai_engine.chain import SAFE_REPLY, AIAllFailed
from ai_engine.prompting import compose_system_prompt, format_catalog
from config import settings
from database import crud
from database.session import db_session
from helpers import in_window, local_now, money, utcnow
from userbot import limits, safety
from userbot.catalog import CATALOG_KEYWORDS, VOICE_REJECT, purchase_intent
from userbot.coalescer import ConvKey, Coalescer
from userbot.outbox import PRIORITY_DELIVERY, PRIORITY_NOTICE, PRIORITY_REPLY, Outbox, OutboxItem, PeerRef

log = logging.getLogger("userbot.seller")

SWEEP_INTERVAL = 30.0
QR_COOLDOWN = timedelta(minutes=10)

DELIVERY_TEMPLATE = (
    "✅ បានបញ្ជាក់ការបង់ប្រាក់រួច!\n\n"
    "🎫 Code របស់បង: {code}\n"
    "📦 {product} × {quantity} · {total}\n\n"
    "សូមប្រើឱ្យបានចំណេញបង 🙏"
)


class Seller:
    def __init__(
        self,
        account_id: int,
        *,
        client=None,
        outbox: Outbox,
        notify: Callable[[str], Awaitable[None]] | None = None,
        clock: Callable[[], object] = local_now,
        debounce_window: float = 3.0,
        catalog=None,
    ) -> None:
        self.account_id = account_id
        self.client = client
        self.outbox = outbox
        self.catalog = catalog
        self._notify = notify or (lambda text: asyncio.sleep(0))
        self._clock = clock
        self._coalescer = Coalescer(self._flush, window=debounce_window)
        self._queued_deliveries: set[int] = set()
        self._sweep_task: asyncio.Task | None = None

    # ---------- ច្រកចូល Telethon ----------
    async def on_incoming(self, event) -> None:
        try:
            if not event.is_private:
                return
            peer_id = event.sender_id
            if peer_id is None:
                return
            sender = await event.get_sender()
            if sender is None or getattr(sender, "bot", False):
                return
            if self._is_staff(peer_id):
                return  # បញ្ជាម្ចាស់ → Controls ទទួល មិនមែនអតិថិជនទេ
            access_hash = getattr(event.input_sender, "access_hash", None)
            media_status = await self._classify_media(event)
            if media_status is not None:
                if media_status == "reject":
                    await self.enqueue_text(peer_id, access_hash, VOICE_REJECT)
                return
            text = event.text or ""
            status = await self.handle_inbound(peer_id, text, access_hash=access_hash)
            if status == "bound" and self.catalog is not None:
                await self.catalog.send_welcome(peer_id, access_hash)  # ទំនាក់ទំនងដំបូង = សួស្តី + សម្ភារៈ
        except Exception:  # noqa: BLE001
            log.exception("seller កំហុសគណនី %s", self.account_id)

    @staticmethod
    async def _classify_media(event) -> str | None:
        """'reject' = voice/video note តបដោយសារទារសំឡេង · 'ignore' = sticker/media ផ្សេង
        (សlip រូបភាព → 'ignore' ព្រោះ panel/owner រក្សាទុកតាម path ផ្សេង) · None = អក្សរ។"""
        message = getattr(event, "message", None)
        if message is None:
            return None
        media = getattr(message, "media", None)
        if media is None:
            return None
        cls = type(media).__name__
        if cls in ("MessageMediaVoice", "MessageMediaVideoNote", "MessageMediaAudio"):
            return "reject"
        if cls in ("MessageMediaSticker", "MessageMediaGame") or getattr(message, "sticker", None) is not None:
            return "ignore"
        if message.text:
            return None  # រូបភាពមាន caption → ចាត់ទុកជាអក្សរ
        return "ignore"  # រូបភាព/video/document ទាំងអស់ — ម្ចាស់ handle ដោយដៃ

    async def enqueue_text(self, peer_id: int, access_hash: int | None, text: str) -> None:
        """ឆ្លើយតបរាវ (voice-reject/...) តាម Outbox តែមួយ — រាប់ budget + delay ដូចសារ AI។"""
        self.outbox.enqueue(
            OutboxItem(
                priority=PRIORITY_REPLY,
                seq=0,
                kind=limits.KIND_AI_REPLY,
                peer=PeerRef(peer_id, access_hash),
                text=text,
                no_log=True,
            )
        )

    @staticmethod
    def _is_staff(user_id: int) -> bool:
        return user_id == settings.owner_id or user_id in settings.admin_ids

    async def _customer_snapshot(self, peer_id: int) -> int | None:
        """access_hash បច្ចុប្បន្ន (StringSession មិន cache entity ក្រោយ restart)។"""
        async with db_session() as session:
            await crud.get_or_create_customer(session, peer_id)
            customer = await crud.get_customer_by_telegram(session, peer_id)
            return customer.access_hash if customer else None

    # ---------- ស្នូល (ស្អាត តេស្តបាន គ្មាន Telethon) ----------
    async def handle_inbound(self, peer_id: int, text: str, *, access_hash: int | None = None) -> str:
        """ត្រឡប់ status ដែលតេស្តអាច read៖ bound/already/conflict/blocked/paused/ai_off/queued។"""
        text = (text or "").strip()
        if not text:
            return "empty"
        if self.catalog is not None and text.lower() in CATALOG_KEYWORDS:
            customer = await self._customer_snapshot(peer_id)
            await self.catalog.send_catalog(peer_id, customer)
            return "menu"
        async with db_session() as session:
            await crud.get_or_create_customer(session, peer_id)
            bind = await crud.set_customer_account(session, peer_id, self.account_id, access_hash)
            await crud.add_message(session, peer_id, "user", text, account_id=self.account_id)
            if bind == "conflict":
                # អតិថិជនរបស់គណនីផ្សេងសរសេរមក — តបអត់បាន គ្រាន់តែប្រាប់ម្ចាស់
                owner_row = await crud.get_customer_by_telegram(session, peer_id)
                bound_to = owner_row.account_id if owner_row else None
                if await crud.notice_once(session, f"conflict:{peer_id}", bucket=utcnow().strftime("%Y-%m-%d")):
                    await self._notify(
                        f"⚠️ អតិថិជន {peer_id} សរសេរមកគណនី #{self.account_id} "
                        f"ប៉ុន្តែគេជាអតិថិជនរបស់គណនី #{bound_to} — ខ្ញុំមិនបានតប (ច្បាប់ sticky)។"
                    )
                return "conflict"
            customer = await crud.get_customer_by_telegram(session, peer_id)
            if customer is None:
                return "missing"
            if customer.is_blocked:
                return "blocked"
            if bind == "bound" and self.catalog is not None:
                return "bound"  # ទំនាក់ទំនងដំបូង → welcome+catalog ពី on_incoming មិនហៅ AI
            if not customer.ai_paused:
                account = await crud.get_account(session, self.account_id)
                if account is not None and account.ai_enabled:
                    if await crud.get_setting(session, "ai_enabled", "on") == "on":
                        await self._coalescer.submit(ConvKey(self.account_id, peer_id), text)
                        return "queued"
                    return "ai_off"
                return "account_off"
            return "paused"

    # ---------- បង្ហាញ batch រួចមក (Coalescer flush) ----------
    async def _flush(self, key: ConvKey, batch: tuple[str, ...]) -> str:
        peer_id = key.peer_id
        async with db_session() as session:
            account = await crud.get_account(session, self.account_id)
            if account is None or not account.ai_enabled:
                return "account_off"
            if await crud.get_setting(session, "ai_enabled", "on") != "on":
                return "ai_off"
            customer = await crud.get_customer_by_telegram(session, peer_id)
            if customer is None or customer.is_blocked or customer.ai_paused:
                return "skip"
            if customer.account_id != self.account_id:
                return "conflict"  # កុំតបពីគណនីខុស ទោះករណីណាក៏ដោយ

            window_spec = account.working_hours or await crud.get_setting(session, "working_hours", settings.working_hours)
            if not in_window(window_spec, at=self._clock()):
                bucket = utcnow().strftime("%Y-%m-%d")
                if await crud.notice_once(session, f"offhours:{self.account_id}:{peer_id}", bucket=bucket):
                    notice = await crud.get_setting(session, "off_hours_reply")
                    self.outbox.enqueue(
                        OutboxItem(
                            priority=PRIORITY_NOTICE,
                            seq=0,
                            kind=limits.KIND_NOTICE,
                            peer=PeerRef(peer_id, customer.access_hash),
                            text=notice,
                        )
                    )
                    return "off_hours"
                return "off_hours_quiet"

            access_hash = customer.access_hash

        reply = await self._generate(peer_id, batch)
        if reply is None:
            return "no_reply"

        self.outbox.enqueue(
            OutboxItem(
                priority=PRIORITY_REPLY,
                seq=0,
                kind=limits.KIND_AI_REPLY,
                peer=PeerRef(peer_id, access_hash),
                text=reply,
            )
        )
        await self._maybe_send_qr(peer_id, access_hash, batch, reply)
        return "queued"

    async def _maybe_send_qr(self, peer_id: int, access_hash: int | None, batch: tuple[str, ...], reply: str) -> str:
        """ចេតនាទិញវាយតាមអក្សរ → រកផលិតផល → `Catalog.handle_buy` (QR ពិត ដែលម្ចាស់ Upload)។

        ប្រើ Order ក្នុង DB ជា cooldown មិនមែន cache ក្នុង memory៖ វារស់កាត់ restart ហើយ
        រាំងស្តុកត្រូវកក់ ២ ដងសម្រាប់ការបញ្ជាទិញតែមួយ។ ជួរនេះបន្ថែមពី AI reply ទេ ហើយ
        មាន Outbox របស់គណនីដដែលរាប់ budget (មិនឆ្លង chat ផ្ទាល់)។
        """
        if self.catalog is None:
            return "no_catalog"
        text = "\n".join(batch)
        if not purchase_intent(text):
            return "no_intent"
        product_id = await self.catalog.resolve_purchase_target(text, reply=reply)
        if product_id is None:
            return "ambiguous"
        async with db_session() as session:
            pending = await crud.open_order_for_customer(
                session, peer_id, product_id, account_id=self.account_id
            )
        if pending is not None and utcnow() - pending.created_at < QR_COOLDOWN:
            return "qr_cooldown"
        alert = await self.catalog.handle_buy(peer_id, product_id)
        if alert:
            self.outbox.enqueue(
                OutboxItem(
                    priority=PRIORITY_REPLY,
                    seq=0,
                    kind=limits.KIND_AI_REPLY,
                    peer=PeerRef(peer_id, access_hash),
                    text=alert,
                )
            )
            return "buy_alert"
        return "qr_sent"

    async def _generate(self, peer_id: int, batch: tuple[str, ...]) -> str | None:
        user_text = "\n".join(batch)
        async with db_session() as session:
            system = compose_system_prompt(
                await crud.get_setting(session, "system_prompt"),
                await crud.get_setting(session, "few_shot"),
                format_catalog(await crud.products_for_account(session, self.account_id)),
            )
            products = await crud.products_for_account(session, self.account_id)
            known_codes = await crud.unsold_codes_for_products(session, [p.id for p in products])
            rows = await crud.get_history(
                session, peer_id, limit=settings.ai_history_limit + len(batch), account_id=self.account_id
            )
        history = list(rows)
        to_strip = len(batch)
        while to_strip and history and history[-1][0] == "user":
            history.pop()
            to_strip -= 1

        try:
            reply = await get_engine().generate(system, [Turn(role, content) for role, content in history], user_text)
        except AIAllFailed as exc:
            async with db_session() as session:
                if await crud.notice_once(
                    session, f"ai:{self.account_id}", bucket=utcnow().strftime("%Y-%m-%dT%H")
                ):
                    await self._notify(
                        f"⚠️ AI ទាំងអស់បរាជ័យ! (គណនី #{self.account_id})\n{exc}"
                    )
            return SAFE_REPLY
        except AIError as exc:
            await self._notify(f"🤖 AI មានបញ្ហា (គណនី #{self.account_id}): {exc}")
            return None

        reply = (reply or "").strip()
        if not reply:
            return None
        safe_terms = tuple(p.name for p in products)
        if safety.looks_like_code(reply, known_codes=known_codes, safe_terms=safe_terms):
            # ការបដិសេធនេះគឺជាការការពារ៖ code ពិតមិនដែលចេញតាម AI ទេ (ម្ចាស់ approve តាម panel)
            async with db_session() as session:
                if await crud.notice_once(
                    session, f"codegate:{self.account_id}:{peer_id}", bucket=utcnow().strftime("%Y-%m-%dT%H")
                ):
                    await self._notify(
                        f"🚫 ខ្ញុំបានរាំងឆ្លើយដែលមានរូបរាង Code សម្រាប់អតិថិជន <code>{peer_id}</code> "
                        f"(គណនី #{self.account_id}) — ច្បាប់: មានតែម្ចាស់ទេដែលបញ្ជេញ Code។"
                    )
            return None
        return reply

    # ---------- Code delivery sweep ----------
    async def start(self) -> None:
        if self._sweep_task is None or self._sweep_task.done():
            self._sweep_task = asyncio.create_task(self._sweep_loop(), name=f"deliver:{self.account_id}")

    async def stop(self) -> None:
        if self._sweep_task is not None:
            self._sweep_task.cancel()
            try:
                await self._sweep_task
            except asyncio.CancelledError:
                pass
            self._sweep_task = None
        await self._coalescer.drain()

    async def _sweep_loop(self) -> None:
        while True:
            try:
                await self.deliver_pending()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("delivery sweep កំហុសគណនី %s", self.account_id)
            await asyncio.sleep(SWEEP_INTERVAL)

    async def deliver_pending(self) -> int:
        """Order ដែលម្ចាស់ confirm រួច ប៉ុន្តែ code មិនទាន់ផ្ញើ (រួមទាំងក្រោយ restart)។
        ផ្ញើពីគណនី sticky របស់ order នោះតែមួយ — PRIORITY_DELIVERY មុន AI ទាំងអស់។"""
        enqueued = 0
        async with db_session() as session:
            orders = await crud.orders_awaiting_code(session, self.account_id)
            for order in orders:
                if order.id in self._queued_deliveries:
                    continue
                customer = await crud.get_customer_by_telegram(session, order.customer_id)
                if customer is None or customer.account_id != self.account_id:
                    continue  # គ្មាន sticky binding → គ្មានការផ្ញើ (មិនដែល outreach)
                self._queued_deliveries.add(order.id)
                enqueued += 1
                self.outbox.enqueue(
                    OutboxItem(
                        priority=PRIORITY_DELIVERY,
                        seq=0,
                        kind=limits.KIND_DELIVERY,
                        peer=PeerRef(order.customer_id, customer.access_hash),
                        text=DELIVERY_TEMPLATE.format(
                            code=order.delivered_code,
                            product=order.product_name,
                            quantity=order.quantity,
                            total=money(order.price * order.quantity),
                        ),
                        order_id=order.id,
                    )
                )
        return enqueued
